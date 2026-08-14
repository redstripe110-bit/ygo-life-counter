#!/usr/bin/env python3
"""依存ライブラリなしでチップチューン風のBGM/SEを合成して WAV を書き出す。
   すべてオリジナルの手打ちシーケンス（既存楽曲の複製は一切していない）。

   v2: ステレオ化・音数増し
     - リードはデチューンした2音をL/Rに振って太く
     - サブベース／コードスタブ／ピンポンディレイ／短いルームを追加
     - ドラムをレイヤー化（キックにクリック、スネア2層、オープンハット、クラッシュ、フィル）
     - 24bit ステレオで書き出し
   ループ本体の後ろに先頭0.5秒ぶんのコピーを余白として付ける（デコード時の末尾欠け対策）。"""
import math, struct, wave, random, json
from array import array

SR = 44100

# ---------------------------------------------------------------- 基礎

def midi(name):
    table = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}
    return 12 * (int(name[-1]) + 1) + table[name[:-1]]

def hz(name):
    return 440.0 * (2.0 ** ((midi(name) - 69) / 12.0))

def mono(n):
    return array('d', [0.0]) * n

def cents(f, c):
    return f * (2.0 ** (c / 1200.0))

# ---------------------------------------------------------------- 波形

def env_at(t, dur, a, d, s, r):
    if t < a:
        return t / a if a > 0 else 1.0
    if t < a + d:
        return 1.0 - (1.0 - s) * (t - a) / d if d > 0 else s
    if t < dur:
        return s
    rt = t - dur
    return s * max(0.0, 1.0 - rt / r) if r > 0 else 0.0

def tone(dst, start, dur, freq, kind='square', amp=0.2, duty=0.5,
         a=0.004, d=0.05, s=0.7, r=0.08, vib=0.0, vibhz=6.0, glide=None,
         pwm=0.0, pwmhz=0.7):
    """1音を mono バッファに加算。ループ境界は巻き込む。"""
    n = len(dst)
    total = dur + r
    cnt = int(total * SR)
    i0 = int(start * SR)
    ph = 0.0
    tau = 2 * math.pi
    for i in range(cnt):
        t = i / SR
        e = env_at(t, dur, a, d, s, r)
        if e <= 0.0:
            continue
        f = glide[0] + (glide[1] - glide[0]) * min(1.0, t / total) if glide else freq
        if vib:
            f *= 1.0 + vib * math.sin(tau * vibhz * t)
        ph += f / SR
        p = ph % 1.0
        if kind == 'square':
            dd = duty + pwm * math.sin(tau * pwmhz * t) if pwm else duty
            v = 1.0 if p < dd else -1.0
        elif kind == 'saw':
            v = 2.0 * p - 1.0
        elif kind == 'tri':
            v = 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p
        else:
            v = math.sin(tau * p)
        dst[(i0 + i) % n] += v * amp * e

def noise(dst, start, dur, amp=0.2, decay=None, hp=0.0, seed=None):
    rnd = random.Random(seed if seed is not None else 12345)
    n = len(dst)
    cnt = int(dur * SR)
    i0 = int(start * SR)
    prev = 0.0
    k = decay if decay else dur
    for i in range(cnt):
        e = math.exp(-(i / SR) / (k * 0.35))
        x = rnd.uniform(-1.0, 1.0)
        y = x - hp * prev
        prev = x
        dst[(i0 + i) % n] += y * amp * e

# ---------------------------------------------------------------- ドラム（レイヤー）

def kick(dst, start, amp=0.6):
    n = len(dst)
    i0 = int(start * SR)
    ph = 0.0
    for i in range(int(0.18 * SR)):          # 本体（ピッチ落ち）
        t = i / SR
        ph += (44 + 130 * math.exp(-t / 0.020)) / SR
        dst[(i0 + i) % n] += math.sin(2 * math.pi * ph) * amp * math.exp(-t / 0.060)
    ph = 0.0
    for i in range(int(0.28 * SR)):          # サブの余韻
        t = i / SR
        ph += 42 / SR
        dst[(i0 + i) % n] += math.sin(2 * math.pi * ph) * amp * 0.34 * math.exp(-t / 0.11)
    noise(dst, start, 0.006, amp=amp * 0.30, decay=0.004, hp=0.9, seed=41)  # クリック

def snare(dst, start, amp=0.36, seed=7):
    noise(dst, start, 0.16, amp=amp * 0.95, decay=0.085, hp=0.62, seed=seed)      # 明るい層
    noise(dst, start, 0.20, amp=amp * 0.42, decay=0.14,  hp=0.18, seed=seed + 90) # 胴鳴り
    tone(dst, start, 0.05, 0, 'tri', amp * 0.45, a=0.001, d=0.03, s=0.2, r=0.03,
         glide=(250, 170))
    tone(dst, start, 0.04, 330, 'tri', amp * 0.20, a=0.001, d=0.03, s=0.2, r=0.03)

def hat(dst, start, amp=0.12, dur=0.032, seed=3):
    noise(dst, start, dur, amp=amp, decay=dur, hp=0.93, seed=seed)

def openhat(dst, start, amp=0.10, seed=5):
    noise(dst, start, 0.20, amp=amp, decay=0.15, hp=0.90, seed=seed)

def crash(dst, start, amp=0.20, seed=11):
    noise(dst, start, 1.4, amp=amp, decay=0.9, hp=0.86, seed=seed)
    noise(dst, start, 1.4, amp=amp * 0.4, decay=1.2, hp=0.55, seed=seed + 7)

def tom(dst, start, f0, amp=0.28):
    tone(dst, start, 0.10, 0, 'sine', amp, a=0.001, d=0.07, s=0.3, r=0.10,
         glide=(f0, f0 * 0.7))
    noise(dst, start, 0.05, amp=amp * 0.20, decay=0.04, hp=0.5, seed=int(f0))

# ---------------------------------------------------------------- エフェクト

def delay_line(src, d, fb):
    """フィードバックディレイのウェット成分。ループを想定して2周まわし、
       2周目だけを返すことで継ぎ目でも余韻が途切れない。"""
    n = len(src)
    out = mono(n)
    dl = [0.0] * d
    p = 0
    for rep in (0, 1):
        for i in range(n):
            y = dl[p]
            dl[p] = src[i] + y * fb
            p += 1
            if p == d:
                p = 0
            if rep:
                out[i] = y
    return out

def room(src, taps=((0.019, 0.30), (0.031, 0.22), (0.047, 0.16), (0.071, 0.11))):
    """ごく短いマルチタップの残響。空間を足すだけで濁らせない程度に。"""
    n = len(src)
    out = mono(n)
    for sec, g in taps:
        d = int(sec * SR)
        for i in range(n):
            out[(i + d) % n] += src[i] * g
    return out

def mix_into(L, R, src, gain=1.0, pan=0.0):
    """equal-power パンでステレオバスに加算"""
    ang = (pan + 1.0) * math.pi / 4.0
    gl = math.cos(ang) * gain
    gr = math.sin(ang) * gain
    for i in range(len(src)):
        v = src[i]
        if v:
            L[i] += v * gl
            R[i] += v * gr

def lowpass(b, cutoff=6500.0):
    """一次ローパス。ループ継ぎ目で状態が飛ばないよう1周空回ししてから本番。"""
    x = math.exp(-2 * math.pi * cutoff / SR)
    y = 0.0
    for i in range(len(b)):
        y = (1 - x) * b[i] + x * y
    for i in range(len(b)):
        y = (1 - x) * b[i] + x * y
        b[i] = y

def finalize(L, R, peak=0.90):
    m = max(max(abs(v) for v in L), max(abs(v) for v in R)) or 1.0
    g = peak / m
    for ch in (L, R):
        for i in range(len(ch)):
            ch[i] = math.tanh(ch[i] * g * 1.45) * 0.88

def with_tail(ch, pad_sec=0.5):
    n = len(ch)
    m = int(pad_sec * SR)
    out = array('d', [0.0]) * (n + m)
    for i in range(n + m):
        out[i] = ch[i % n]
    return out

def write_wav24(path, L, R):
    """24bit ステレオで書き出す（AACに渡す前の量子化ノイズを避ける）"""
    w = wave.open(path, 'wb')
    w.setnchannels(2); w.setsampwidth(3); w.setframerate(SR)
    frames = bytearray()
    for i in range(len(L)):
        for v in (L[i], R[i]):
            x = int(max(-1.0, min(1.0, v)) * 8388607)
            frames += struct.pack('<i', x)[0:3]
    w.writeframes(bytes(frames))
    w.close()
    print('  ->', path, '%.3fs stereo/24bit' % (len(L) / SR))

# ---------------------------------------------------------------- 便利関数

def notes(dst, spb, pattern, kind, amp, **kw):
    for beat, ln, note in pattern:
        if note is None:
            continue
        tone(dst, beat * spb, ln * spb * 0.92, hz(note), kind, amp, **kw)

def notes_detuned(dstA, dstB, spb, pattern, kind, amp, det=7.0, **kw):
    """±det セントに広げた2声。dstA/dstB を左右に振って使う。"""
    for beat, ln, note in pattern:
        if note is None:
            continue
        f = hz(note)
        tone(dstA, beat * spb, ln * spb * 0.92, cents(f, -det), kind, amp, **kw)
        tone(dstB, beat * spb, ln * spb * 0.92, cents(f, +det), kind, amp, **kw)

def arp(start_beat, beats, ns, step=0.25):
    return [(start_beat + i * step, step, ns[i % len(ns)])
            for i in range(int(beats / step))]

def eighths(bar, tokens):
    ns = tokens.split()
    return [(bar * 4 + i * 0.5, 0.45, ns[i]) for i in range(len(ns))]

def bars(bpm, count):
    spb = 60.0 / bpm
    return spb, spb * 4 * count

def down(root, oct_down=1):
    return root[:-1] + str(int(root[-1]) - oct_down)


# ===== BGM1 : 快活な戦闘曲（16小節 A8+B8）=========================
BGM1 = [
    ('A2', 'A4 C5 E5 C5 A4 B4 C5 E5', ['A3','C4','E4']),
    ('F2', 'F4 A4 C5 A4 F4 G4 A4 C5', ['F3','A3','C4']),
    ('C3', 'C5 E5 G5 E5 C5 D5 E5 G5', ['C4','E4','G4']),
    ('G2', 'G4 B4 D5 B4 G4 A4 B4 D5', ['G3','B3','D4']),
    ('A2', 'A4 E5 A5 E5 C5 E5 A4 C5', ['A3','C4','E4']),
    ('F2', 'F4 C5 F5 C5 A4 C5 F4 A4', ['F3','A3','C4']),
    ('C3', 'C5 G5 E5 C5 G4 C5 E5 G5', ['C4','E4','G4']),
    ('G2', 'G4 D5 B4 G4 D5 F5 E5 D5', ['G3','B3','D4']),
    ('A2', 'E5 A5 G5 E5 A4 C5 E5 A5', ['A3','C4','E4']),
    ('G2', 'D5 G5 F5 D5 B4 D5 G5 B5', ['G3','B3','D4']),
    ('F2', 'C5 F5 E5 C5 A4 C5 F5 A5', ['F3','A3','C4']),
    ('E2', 'B4 E5 D5 B4 G#4 B4 E5 G#5', ['E3','G#3','B3']),
    ('A2', 'A5 G5 E5 C5 A4 C5 E5 G5', ['A3','C4','E4']),
    ('G2', 'G5 F5 D5 B4 G4 B4 D5 F5', ['G3','B3','D4']),
    ('F2', 'F5 E5 C5 A4 F4 A4 C5 E5', ['F3','A3','C4']),
    ('E2', 'E5 D5 B4 G#4 E4 G#4 B4 D5', ['E3','G#3','B3']),
]

def bgm1():
    bpm = 148; spb, length = bars(bpm, 16)
    n = int(SR * length)
    L, R = mono(n), mono(n)
    leadA, leadB, spark = mono(n), mono(n), mono(n)
    bass, sub, stab, drum, hatL, hatR = mono(n), mono(n), mono(n), mono(n), mono(n), mono(n)

    bpat, lpat, spat = [], [], []
    for i, (root, mel, chord) in enumerate(BGM1):
        bpat += [(i * 4 + k * 0.5, 0.45, root) for k in range(8)]
        lpat += eighths(i, mel)
        for off in (1.5, 3.5):                       # 裏拍のコードスタブ
            for c in chord:
                spat.append((i * 4 + off, 0.35, c))

    notes(bass, spb, bpat, 'square', 0.20, duty=0.5, a=0.002, d=0.03, s=0.75, r=0.04)
    notes(sub,  spb, [(t, l, down(x, 1)) for t, l, x in bpat], 'sine', 0.16,
          a=0.003, d=0.04, s=0.8, r=0.05)
    notes_detuned(leadA, leadB, spb, lpat, 'square', 0.15, det=8,
                  duty=0.5, a=0.003, d=0.06, s=0.62, r=0.09, pwm=0.06, pwmhz=0.4)
    notes(spark, spb, [x for x in lpat if float(x[0]) == int(x[0])], 'saw', 0.045,
          a=0.004, d=0.05, s=0.35, r=0.07)
    notes(stab, spb, spat, 'square', 0.055, duty=0.32, a=0.002, d=0.09, s=0.0, r=0.06)

    for bar in range(16):
        t0 = bar * 4
        kick(drum, t0 * spb); kick(drum, (t0 + 2) * spb); kick(drum, (t0 + 2.75) * spb, 0.44)
        snare(drum, (t0 + 1) * spb); snare(drum, (t0 + 3) * spb)
        if bar % 8 == 0:
            crash(drum, t0 * spb, 0.17)
        if bar % 8 == 7:                              # フィル
            for k, f0 in enumerate((300, 240, 190, 150)):
                tom(drum, (t0 + 3.0 + k * 0.25) * spb, f0, 0.26)
        for k in range(8):
            dst = hatL if k % 2 == 0 else hatR
            if k == 7:
                openhat(dst, (t0 + k * 0.5) * spb, 0.085)
            else:
                hat(dst, (t0 + k * 0.5) * spb, 0.105 if k % 2 == 0 else 0.075)

    echoL = delay_line(leadA, int(0.375 * spb * SR), 0.34)
    echoR = delay_line(leadB, int(0.75 * spb * SR), 0.28)

    mix_into(L, R, bass, 1.0, 0.0);   mix_into(L, R, sub, 1.0, 0.0)
    mix_into(L, R, leadA, 1.0, -0.52); mix_into(L, R, leadB, 1.0, 0.52)
    mix_into(L, R, spark, 1.0, 0.0)
    mix_into(L, R, echoL, 0.30, 0.85); mix_into(L, R, echoR, 0.26, -0.85)
    mix_into(L, R, stab, 1.0, -0.62);  mix_into(L, R, stab, 0.85, 0.66)
    mix_into(L, R, drum, 1.0, 0.0)
    mix_into(L, R, hatL, 1.0, -0.48);  mix_into(L, R, hatR, 1.0, 0.48)

    amb = room(leadA); mix_into(L, R, amb, 0.10, -0.6)
    amb = room(leadB); mix_into(L, R, amb, 0.10, 0.6)
    lowpass(L, 12500); lowpass(R, 12500); finalize(L, R)
    return L, R

# ===== BGM2 : 少し緊張 ============================================
BGM2_CHORDS = [
    ('A2', ['A3','C4','E4','C4']), ('A2', ['A3','C4','E4','C4']),
    ('F2', ['F3','A3','C4','A3']), ('F2', ['F3','A3','C4','A3']),
    ('D2', ['D3','F3','A3','F3']), ('D2', ['D3','F3','A3','F3']),
    ('E2', ['E3','G#3','B3','G#3']), ('E2', ['E3','G#3','B3','G#3']),
    ('A2', ['A3','C4','F4','C4']), ('A2', ['A3','C4','F4','C4']),
    ('G2', ['G3','A#3','D4','A#3']), ('G2', ['G3','A#3','D4','A#3']),
    ('F2', ['F3','A3','C4','E4']), ('F2', ['F3','A3','C4','E4']),
    ('E2', ['E3','G#3','B3','D4']), ('E2', ['E3','G#3','B3','D4']),
]
BGM2_MEL = [
    (0,2,'E5'),(2,1,'D5'),(3,1,'C5'), (4,2,'C5'),(6,2,'B4'),
    (8,2,'A4'),(10,1,'C5'),(11,1,'D5'), (12,3,'E5'),(15,1,'F5'),
    (16,2,'D5'),(18,2,'C5'), (20,2,'B4'),(22,2,'A4'),
    (24,2,'G#4'),(26,2,'B4'), (28,4,'E5'),
    (32,2,'F5'),(34,1,'E5'),(35,1,'C5'), (36,2,'A4'),(38,2,'C5'),
    (40,2,'D5'),(42,1,'F5'),(43,1,'D5'), (44,3,'A#4'),(47,1,'C5'),
    (48,2,'C5'),(50,2,'E5'), (52,2,'F5'),(54,2,'E5'),
    (56,2,'D5'),(58,1,'C5'),(59,1,'B4'), (60,4,'A4'),
]

def bgm2():
    bpm = 156; spb, length = bars(bpm, 16)
    n = int(SR * length)
    L, R = mono(n), mono(n)
    leadA, leadB = mono(n), mono(n)
    bass, sub, apL, apR, drum, hatL, hatR = (mono(n) for _ in range(7))

    bpat = []
    for i, (root, ch) in enumerate(BGM2_CHORDS):
        bpat += [(i * 4 + k * 0.5, 0.42, root) for k in range(8)]
        for j, ev in enumerate(arp(i * 4, 4, ch, 0.25)):
            notes(apL if j % 2 == 0 else apR, spb, [ev], 'square', 0.10,
                  duty=0.25, a=0.002, d=0.04, s=0.45, r=0.05)

    notes(bass, spb, bpat, 'square', 0.21, duty=0.35, a=0.002, d=0.03, s=0.7, r=0.04)
    notes(sub,  spb, [(t, l, down(x, 1)) for t, l, x in bpat], 'sine', 0.15,
          a=0.003, d=0.04, s=0.8, r=0.05)
    notes_detuned(leadA, leadB, spb, BGM2_MEL, 'tri', 0.17, det=9,
                  a=0.02, d=0.15, s=0.6, r=0.14, vib=0.005, vibhz=5.5)

    for bar in range(16):
        t0 = bar * 4
        kick(drum, t0 * spb); kick(drum, (t0 + 1.5) * spb, 0.44); kick(drum, (t0 + 2.5) * spb, 0.48)
        snare(drum, (t0 + 1) * spb); snare(drum, (t0 + 3) * spb)
        if bar % 8 == 0:
            crash(drum, t0 * spb, 0.15)
        for k in range(8):
            dst = hatL if k % 2 == 0 else hatR
            hat(dst, (t0 + k * 0.5) * spb, 0.095)

    echoL = delay_line(leadA, int(0.5 * spb * SR), 0.36)
    echoR = delay_line(leadB, int(0.75 * spb * SR), 0.30)

    mix_into(L, R, bass, 1.0, 0.0); mix_into(L, R, sub, 1.0, 0.0)
    mix_into(L, R, leadA, 1.0, -0.50); mix_into(L, R, leadB, 1.0, 0.50)
    mix_into(L, R, echoL, 0.34, 0.88); mix_into(L, R, echoR, 0.30, -0.88)
    mix_into(L, R, apL, 1.0, -0.68); mix_into(L, R, apR, 1.0, 0.68)
    mix_into(L, R, drum, 1.0, 0.0)
    mix_into(L, R, hatL, 1.0, -0.50); mix_into(L, R, hatR, 1.0, 0.50)
    amb = room(leadA); mix_into(L, R, amb, 0.12, 0.55)
    lowpass(L, 11800); lowpass(R, 11800); finalize(L, R)
    return L, R

# ===== BGM3 : あと少し！さらに緊張 ================================
BGM3_BARS = [
    ('A2',  ['A3','C4','E4','G4']),   ('A2',  ['A3','C4','E4','G4']),
    ('A#2', ['A#3','C#4','F4','G#4']),('A#2', ['A#3','C#4','F4','G#4']),
    ('B2',  ['B3','D4','F#4','A4']),  ('B2',  ['B3','D4','F#4','A4']),
    ('C3',  ['C4','D#4','G4','A#4']), ('C3',  ['C4','D#4','G4','A#4']),
    ('C#3', ['C#4','E4','G#4','B4']), ('C#3', ['C#4','E4','G#4','B4']),
    ('D3',  ['D4','F4','A4','C5']),   ('D3',  ['D4','F4','A4','C5']),
    ('D#3', ['D#4','F#4','A#4','C#5']),('D#3',['D#4','F#4','A#4','C#5']),
    ('E3',  ['E4','G4','B4','D5']),   ('E3',  ['E4','G#4','B4','D5']),
]
BGM3_MEL = [
    (0,1.5,'E5'),(1.5,0.5,'F5'),(2,2,'E5'), (4,1.5,'G5'),(5.5,0.5,'F5'),(6,2,'E5'),
    (8,1.5,'F5'),(9.5,0.5,'F#5'),(10,2,'F5'), (12,2,'G#5'),(14,2,'F5'),
    (16,1.5,'F#5'),(17.5,0.5,'G5'),(18,2,'F#5'), (20,1.5,'A5'),(21.5,0.5,'G5'),(22,2,'F#5'),
    (24,1.5,'G5'),(25.5,0.5,'G#5'),(26,2,'G5'), (28,4,'A#5'),
    (32,1.5,'G#5'),(33.5,0.5,'A5'),(34,2,'G#5'), (36,1.5,'B5'),(37.5,0.5,'A5'),(38,2,'G#5'),
    (40,1.5,'A5'),(41.5,0.5,'A#5'),(42,2,'A5'), (44,2,'C6'),(46,2,'A5'),
    (48,1.5,'A#5'),(49.5,0.5,'B5'),(50,2,'A#5'), (52,1.5,'C#6'),(53.5,0.5,'B5'),(54,2,'A#5'),
    (56,2,'B5'),(58,2,'D6'), (60,2,'B5'),(62,2,'E5'),
]

def bgm3():
    bpm = 168; spb, length = bars(bpm, 16)
    n = int(SR * length)
    L, R = mono(n), mono(n)
    leadA, leadB = mono(n), mono(n)
    bass, sub, apL, apR, drum, hatL, hatR = (mono(n) for _ in range(7))

    bpat = []
    for i, (root, ch) in enumerate(BGM3_BARS):
        bpat += [(i * 4 + k * 0.25, 0.22, root) for k in range(16)]
        for j, ev in enumerate(arp(i * 4, 4, ch, 0.125)):
            notes(apL if j % 2 == 0 else apR, spb, [ev], 'square', 0.085,
                  duty=0.2, a=0.001, d=0.025, s=0.4, r=0.03)

    notes(bass, spb, bpat, 'square', 0.20, duty=0.3, a=0.001, d=0.02, s=0.72, r=0.02)
    notes(sub,  spb, [(t, l, down(x, 1)) for t, l, x in bpat], 'sine', 0.14,
          a=0.002, d=0.03, s=0.8, r=0.03)
    notes_detuned(leadA, leadB, spb, BGM3_MEL, 'square', 0.14, det=10,
                  duty=0.42, a=0.008, d=0.1, s=0.6, r=0.1, vib=0.008, vibhz=6.5,
                  pwm=0.05, pwmhz=0.9)

    for bar in range(16):
        t0 = bar * 4
        for k in (0, 1.5, 2, 3.5):
            kick(drum, (t0 + k) * spb, 0.54)
        snare(drum, (t0 + 1) * spb); snare(drum, (t0 + 3) * spb)
        if bar % 8 == 0:
            crash(drum, t0 * spb, 0.16)
        if bar % 4 == 3:
            for k in range(4):
                snare(drum, (t0 + 3.5 + k * 0.125) * spb, 0.24, seed=k)
        for k in range(16):
            dst = hatL if k % 2 == 0 else hatR
            hat(dst, (t0 + k * 0.25) * spb, 0.08, dur=0.022)

    echoL = delay_line(leadA, int(0.375 * spb * SR), 0.32)
    echoR = delay_line(leadB, int(0.5 * spb * SR), 0.28)

    mix_into(L, R, bass, 1.0, 0.0); mix_into(L, R, sub, 1.0, 0.0)
    mix_into(L, R, leadA, 1.0, -0.48); mix_into(L, R, leadB, 1.0, 0.48)
    mix_into(L, R, echoL, 0.30, 0.88); mix_into(L, R, echoR, 0.26, -0.88)
    mix_into(L, R, apL, 1.0, -0.70); mix_into(L, R, apR, 1.0, 0.70)
    mix_into(L, R, drum, 1.0, 0.0)
    mix_into(L, R, hatL, 1.0, -0.52); mix_into(L, R, hatR, 1.0, 0.52)
    amb = room(leadA); mix_into(L, R, amb, 0.11, 0.5)
    lowpass(L, 13000); lowpass(R, 13000); finalize(L, R)
    return L, R

# ===== BGM4 : お互いギリギリ・ハラハラ ============================
BGM4_BARS = [
    ('D2',  ['D4','F4','G#4','B4']),   ('G#2', ['D4','F4','G#4','B4']),
    ('D2',  ['D4','F4','G#4','B4']),   ('G#2', ['D4','F4','G#4','B4']),
    ('D#2', ['D#4','F#4','A4','C5']),  ('A2',  ['D#4','F#4','A4','C5']),
    ('D#2', ['D#4','F#4','A4','C5']),  ('A2',  ['D#4','F#4','A4','C5']),
    ('C2',  ['C4','D#4','F#4','A4']),  ('F#2', ['C4','D#4','F#4','A4']),
    ('C2',  ['C4','D#4','F#4','A4']),  ('F#2', ['C4','D#4','F#4','A4']),
    ('C#2', ['C#4','E4','G4','A#4']),  ('G2',  ['C#4','E4','G4','A#4']),
    ('C#2', ['C#4','E4','G4','A#4']),  ('G2',  ['C#4','E4','G4','A#4']),
]
BGM4_HOLD = [
    (0,4,'A5'),(4,4,'A#5'),(8,4,'A5'),(12,4,'G#5'),
    (16,4,'A5'),(20,4,'C6'),(24,4,'A#5'),(28,4,'A5'),
    (32,4,'C6'),(36,4,'B5'),(40,4,'C6'),(44,4,'D#6'),
    (48,4,'C#6'),(52,4,'C6'),(56,4,'A#5'),(60,4,'A5'),
]

def bgm4():
    bpm = 182; spb, length = bars(bpm, 16)
    n = int(SR * length)
    L, R = mono(n), mono(n)
    holdA, holdB = mono(n), mono(n)
    bass, sub, apL, apR, padA, padB, drum, hatL, hatR = (mono(n) for _ in range(9))

    bpat = []
    for i, (root, dim) in enumerate(BGM4_BARS):
        bpat += [(i * 4 + k * 0.25, 0.2, root) for k in range(16)]
        for j, ev in enumerate(arp(i * 4, 4, dim + list(reversed(dim)), 0.125)):
            notes(apL if j % 2 == 0 else apR, spb, [ev], 'square', 0.09,
                  duty=0.16, a=0.001, d=0.02, s=0.35, r=0.025)
        if i % 2 == 0:                                   # 不穏なパッド
            for c in dim[:3]:
                tone(padA, i * 4 * spb, 8 * spb * 0.95, cents(hz(c), -9), 'saw', 0.030,
                     a=0.4, d=0.6, s=0.7, r=0.5)
                tone(padB, i * 4 * spb, 8 * spb * 0.95, cents(hz(c), +9), 'saw', 0.030,
                     a=0.4, d=0.6, s=0.7, r=0.5)

    notes(bass, spb, bpat, 'saw', 0.18, a=0.001, d=0.02, s=0.7, r=0.02)
    notes(sub,  spb, [(t, l, down(x, 1)) for t, l, x in bpat], 'sine', 0.15,
          a=0.002, d=0.03, s=0.8, r=0.03)
    notes_detuned(holdA, holdB, spb, BGM4_HOLD, 'tri', 0.12, det=11,
                  a=0.05, d=0.2, s=0.75, r=0.2, vib=0.012, vibhz=8.0)

    for bar in range(16):
        t0 = bar * 4
        for k in (0, 0.35, 2, 2.35):
            kick(drum, (t0 + k) * spb, 0.54)
        snare(drum, (t0 + 1) * spb, 0.32); snare(drum, (t0 + 3) * spb, 0.32)
        if bar % 8 == 0:
            crash(drum, t0 * spb, 0.18)
        if bar % 8 == 7:
            for k, f0 in enumerate((320, 250, 200, 160, 130, 110)):
                tom(drum, (t0 + 3.0 + k * 0.1667) * spb, f0, 0.24)
        for k in range(16):
            dst = hatL if k % 2 == 0 else hatR
            hat(dst, (t0 + k * 0.25) * spb, 0.09 if k % 4 == 0 else 0.06, dur=0.02)

    echoL = delay_line(holdA, int(0.375 * spb * SR), 0.30)
    echoR = delay_line(apR, int(0.75 * spb * SR), 0.26)

    mix_into(L, R, bass, 1.0, 0.0); mix_into(L, R, sub, 1.0, 0.0)
    mix_into(L, R, holdA, 1.0, -0.46); mix_into(L, R, holdB, 1.0, 0.46)
    mix_into(L, R, padA, 1.0, -0.92);  mix_into(L, R, padB, 1.0, 0.92)
    mix_into(L, R, echoL, 0.28, 0.88); mix_into(L, R, echoR, 0.24, -0.88)
    mix_into(L, R, apL, 1.0, -0.70); mix_into(L, R, apR, 1.0, 0.70)
    mix_into(L, R, drum, 1.0, 0.0)
    mix_into(L, R, hatL, 1.0, -0.54); mix_into(L, R, hatR, 1.0, 0.54)
    amb = room(holdA); mix_into(L, R, amb, 0.13, 0.5)
    lowpass(L, 13000); lowpass(R, 13000); finalize(L, R)
    return L, R

# ===== SE ==========================================================
def damage():
    """ピロピロピロ…ピコン"""
    n = int(SR * 1.05)
    a, b = mono(n), mono(n)
    for i, f in enumerate((1245, 1046, 880)):
        t = 0.02 + i * 0.10
        for dst, det in ((a, -6), (b, +6)):
            tone(dst, t, 0.055, cents(f, det), 'square', 0.26, duty=0.5,
                 a=0.001, d=0.02, s=0.7, r=0.03)
            tone(dst, t, 0.055, cents(f * 1.5, det), 'square', 0.08, duty=0.25,
                 a=0.001, d=0.02, s=0.5, r=0.03)
    for dst in (a, b):
        tone(dst, 0.42, 0.07, 0, 'sine', 0.30, a=0.002, d=0.05, s=0.6, r=0.05,
             glide=(1568, 2093))
        tone(dst, 0.49, 0.30, 2093, 'tri', 0.26, a=0.002, d=0.12, s=0.35, r=0.28)
        tone(dst, 0.49, 0.30, 3136, 'sine', 0.10, a=0.002, d=0.10, s=0.25, r=0.26)
    L, R = mono(n), mono(n)
    mix_into(L, R, a, 1.0, -0.25); mix_into(L, R, b, 1.0, 0.25)
    e = delay_line(a, int(0.085 * SR), 0.30)
    mix_into(L, R, e, 0.22, 0.5)
    lowpass(L, 12000); lowpass(R, 12000); finalize(L, R, 0.92)
    return L, R

def coin():
    n = int(SR * 0.9)
    a = mono(n)
    for f, amp in ((1318, 0.22), (1975, 0.16), (2637, 0.10), (3520, 0.06)):
        tone(a, 0.0, 0.55, f, 'sine', amp, a=0.002, d=0.25, s=0.25, r=0.3)
    tone(a, 0.0, 0.05, 0, 'sine', 0.12, a=0.001, d=0.03, s=0.3, r=0.04, glide=(900, 1600))
    L, R = mono(n), mono(n)
    mix_into(L, R, a, 1.0, -0.1)
    mix_into(L, R, delay_line(a, int(0.07 * SR), 0.25), 0.25, 0.45)
    lowpass(L, 13000); lowpass(R, 13000); finalize(L, R, 0.88)
    return L, R

def buzzer():
    """ライフ0の「ビーーー」。矩形波を軽くデチューンして重ね、
       最後だけピッチを落として切る。耳に刺さらないよう高域は削る。"""
    n = int(SR * 2.2)
    a, b = mono(n), mono(n)
    hold = 1.85
    for dst, det in ((a, -5), (b, +5)):
        tone(dst, 0.0, hold, cents(220, det), 'square', 0.30, duty=0.5,
             a=0.006, d=0.10, s=0.95, r=0.30)              # 芯
        tone(dst, 0.0, hold, cents(440, det), 'square', 0.10, duty=0.32,
             a=0.006, d=0.10, s=0.90, r=0.30)              # 上のオクターブで鋭さ
        tone(dst, 0.0, hold, cents(110, det), 'square', 0.14, duty=0.5,
             a=0.008, d=0.12, s=0.90, r=0.30)              # 下で厚み
        tone(dst, hold - 0.05, 0.28, 0, 'square', 0.24, duty=0.5,
             a=0.004, d=0.05, s=0.8, r=0.22, glide=(220, 150))   # 語尾を落として終わる
    L, R = mono(n), mono(n)
    mix_into(L, R, a, 1.0, -0.18)
    mix_into(L, R, b, 1.0, 0.18)
    mix_into(L, R, room(a), 0.10, 0.5)
    lowpass(L, 5200); lowpass(R, 5200)
    finalize(L, R, 0.92)
    return L, R

def dice():
    n = int(SR * 1.1)
    a, b = mono(n), mono(n)
    rnd = random.Random(99)
    t = 0.0
    for i in range(7):
        dst = a if i % 2 == 0 else b
        noise(dst, t, 0.05, amp=0.28 - i * 0.02, decay=0.03, hp=0.85, seed=i)
        tone(dst, t, 0.03, rnd.choice((520, 640, 760, 880)), 'tri', 0.10,
             a=0.001, d=0.02, s=0.3, r=0.03)
        t += 0.075 + i * 0.018
    for dst in (a, b):
        tone(dst, t + 0.05, 0.25, 1046, 'tri', 0.18, a=0.003, d=0.12, s=0.3, r=0.22)
    L, R = mono(n), mono(n)
    mix_into(L, R, a, 1.0, -0.4); mix_into(L, R, b, 1.0, 0.4)
    lowpass(L, 12000); lowpass(R, 12000); finalize(L, R, 0.88)
    return L, R


if __name__ == '__main__':
    import sys
    out = sys.argv[1]
    loops = {}
    for name, fn in [('bgm1', bgm1), ('bgm2', bgm2), ('bgm3', bgm3), ('bgm4', bgm4)]:
        print('rendering', name, '...')
        L, R = fn()
        loops[name] = round(len(L) / SR, 6)
        write_wav24('%s/%s.wav' % (out, name), with_tail(L), with_tail(R))
        print('     loop = %.6fs (+0.5s の余白つき)' % loops[name])
    for name, fn in [('damage', damage), ('coin', coin), ('dice', dice)]:
        print('rendering', name, '...')
        L, R = fn()
        write_wav24('%s/%s.wav' % (out, name), L, R)
    open('%s/loops.json' % out, 'w').write(json.dumps(loops, indent=1))
    print(json.dumps(loops))
