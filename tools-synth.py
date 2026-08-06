#!/usr/bin/env python3
"""依存ライブラリなしでチップチューン風のBGM/SEを合成して WAV を書き出す。
   すべてオリジナルの手打ちシーケンス（既存楽曲の複製は一切していない）。
   BGMは16小節・A→Bの2部構成で、末尾の余韻は先頭に回り込ませてシームレスにループする。"""
import math, struct, wave, random, json
from array import array

SR = 44100

# ---------------------------------------------------------------- 基礎

def midi(name):
    table = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}
    return 12 * (int(name[-1]) + 1) + table[name[:-1]]

def hz(name):
    return 440.0 * (2.0 ** ((midi(name) - 69) / 12.0))

def buf(seconds):
    return array('d', [0.0]) * int(SR * seconds)

def add(dst, pos, val):
    """ループ境界をまたぐ音は先頭に回り込ませる（シームレスループのため）"""
    dst[pos % len(dst)] += val

# ---------------------------------------------------------------- 波形

def osc(kind, phase, duty=0.5):
    if kind == 'square':
        return 1.0 if (phase % 1.0) < duty else -1.0
    if kind == 'saw':
        return 2.0 * (phase % 1.0) - 1.0
    if kind == 'tri':
        p = phase % 1.0
        return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p
    if kind == 'sine':
        return math.sin(2 * math.pi * phase)
    return 0.0

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
         a=0.004, d=0.05, s=0.7, r=0.08, vib=0.0, vibhz=6.0, glide=None):
    total = dur + r
    n = int(total * SR)
    i0 = int(start * SR)
    ph = 0.0
    for i in range(n):
        t = i / SR
        e = env_at(t, dur, a, d, s, r)
        if e <= 0.0:
            continue
        f = freq
        if glide:
            k = min(1.0, t / total)
            f = glide[0] + (glide[1] - glide[0]) * k
        if vib:
            f *= 1.0 + vib * math.sin(2 * math.pi * vibhz * t)
        ph += f / SR
        add(dst, i0 + i, osc(kind, ph, duty) * amp * e)

def noise(dst, start, dur, amp=0.2, decay=None, hp=0.0, seed=None):
    rnd = random.Random(seed if seed is not None else 12345)
    n = int(dur * SR)
    i0 = int(start * SR)
    prev = 0.0
    k = decay if decay else dur
    for i in range(n):
        e = math.exp(-(i / SR) / (k * 0.35))
        x = rnd.uniform(-1.0, 1.0)
        y = x - hp * prev
        prev = x
        add(dst, i0 + i, y * amp * e)

# ---------------------------------------------------------------- ドラム

def kick(dst, start, amp=0.55):
    n = int(0.14 * SR); i0 = int(start * SR); ph = 0.0
    for i in range(n):
        t = i / SR
        ph += (45 + 115 * math.exp(-t / 0.022)) / SR
        add(dst, i0 + i, math.sin(2 * math.pi * ph) * amp * math.exp(-t / 0.055))

def snare(dst, start, amp=0.34, seed=7):
    noise(dst, start, 0.14, amp=amp, decay=0.10, hp=0.55, seed=seed)
    tone(dst, start, 0.05, 190, 'tri', amp=amp * 0.5, a=0.001, d=0.03, s=0.2, r=0.03)

def hat(dst, start, amp=0.12, dur=0.035, seed=3):
    noise(dst, start, dur, amp=amp, decay=dur, hp=0.92, seed=seed)

# ---------------------------------------------------------------- 仕上げ

def lowpass(b, cutoff=6500.0):
    """一次ローパス。ループ継ぎ目で状態が飛ばないよう、1周ぶん空回しして
       フィルタ状態を温めてから本番の書き込みを行う。"""
    x = math.exp(-2 * math.pi * cutoff / SR)
    y = 0.0
    for i in range(len(b)):          # 空回し（bは書き換えない）
        y = (1 - x) * b[i] + x * y
    for i in range(len(b)):
        y = (1 - x) * b[i] + x * y
        b[i] = y

def finalize(b, peak=0.86):
    m = max(abs(v) for v in b) or 1.0
    g = peak / m
    for i in range(len(b)):
        b[i] = math.tanh(b[i] * g * 1.15) * 0.92

def with_tail(b, pad_sec=0.5):
    """ループ本体の後ろに『先頭のコピー』を余白として足す。
       AACやmp3のデコード時に末尾が数十ms削られても、アプリ側が
       正確なループ長で loopEnd を指定すれば中身が欠けない。"""
    n = len(b)
    m = int(pad_sec * SR)
    out = array('d', [0.0]) * (n + m)
    for i in range(n + m):
        out[i] = b[i % n]
    return out

def write_wav(path, b):
    w = wave.open(path, 'wb')
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(b''.join(struct.pack('<h', int(max(-1.0, min(1.0, v)) * 32767)) for v in b))
    w.close()
    print('  ->', path, '%.3fs (%d samples)' % (len(b) / SR, len(b)))
    return len(b) / SR

# ---------------------------------------------------------------- 便利関数

def play(dst, spb, pattern, kind, amp, duty=0.5, oct_shift=0, **kw):
    for beat, ln, note in pattern:
        if note is None:
            continue
        tone(dst, beat * spb, ln * spb * 0.92, hz(note) * (2.0 ** oct_shift),
             kind, amp, duty, **kw)

def arp(start_beat, beats, notes, step=0.25):
    return [(start_beat + i * step, step, notes[i % len(notes)])
            for i in range(int(beats / step))]

def eighths(bar, tokens):
    """'A4 C5 E5 ...' の8音を8分音符として並べる"""
    ns = tokens.split()
    return [(bar * 4 + i * 0.5, 0.45, ns[i]) for i in range(len(ns))]

def bars(bpm, count):
    spb = 60.0 / bpm
    return spb, spb * 4 * count


# ===== BGM1 : 快活な戦闘曲（16小節 A8+B8）=========================
BGM1 = [
    # A：Am - F - C - G を2回
    ('A2', 'A4 C5 E5 C5 A4 B4 C5 E5'),
    ('F2', 'F4 A4 C5 A4 F4 G4 A4 C5'),
    ('C3', 'C5 E5 G5 E5 C5 D5 E5 G5'),
    ('G2', 'G4 B4 D5 B4 G4 A4 B4 D5'),
    ('A2', 'A4 E5 A5 E5 C5 E5 A4 C5'),
    ('F2', 'F4 C5 F5 C5 A4 C5 F4 A4'),
    ('C3', 'C5 G5 E5 C5 G4 C5 E5 G5'),
    ('G2', 'G4 D5 B4 G4 D5 F5 E5 D5'),
    # B：Am - G - F - E で少し陰りを出してから戻る
    ('A2', 'E5 A5 G5 E5 A4 C5 E5 A5'),
    ('G2', 'D5 G5 F5 D5 B4 D5 G5 B5'),
    ('F2', 'C5 F5 E5 C5 A4 C5 F5 A5'),
    ('E2', 'B4 E5 D5 B4 G#4 B4 E5 G#5'),
    ('A2', 'A5 G5 E5 C5 A4 C5 E5 G5'),
    ('G2', 'G5 F5 D5 B4 G4 B4 D5 F5'),
    ('F2', 'F5 E5 C5 A4 F4 A4 C5 E5'),
    ('E2', 'E5 D5 B4 G#4 E4 G#4 B4 D5'),
]

def bgm1():
    bpm = 148; spb, length = bars(bpm, 16)
    b = buf(length)
    bass, lead = [], []
    for i, (root, mel) in enumerate(BGM1):
        bass += [(i * 4 + k * 0.5, 0.45, root) for k in range(8)]
        lead += eighths(i, mel)
    play(b, spb, bass, 'square', 0.20, duty=0.5, a=0.002, d=0.03, s=0.75, r=0.04)
    play(b, spb, lead, 'square', 0.17, duty=0.5, a=0.003, d=0.06, s=0.62, r=0.09)
    # ハモリ（拍頭のみ・1オクターブ下）
    play(b, spb, [n for n in lead if float(n[0]) == int(n[0])],
         'tri', 0.075, oct_shift=-1, a=0.005, d=0.08, s=0.5, r=0.1)
    for bar in range(16):
        t0 = bar * 4
        kick(b, t0 * spb); kick(b, (t0 + 2) * spb); kick(b, (t0 + 2.75) * spb, 0.4)
        snare(b, (t0 + 1) * spb); snare(b, (t0 + 3) * spb)
        if bar % 8 == 7:
            for k in range(4):
                snare(b, (t0 + 3.5 + k * 0.125) * spb, 0.24, seed=k)
        for k in range(8):
            hat(b, (t0 + k * 0.5) * spb, 0.10 if k % 2 == 0 else 0.07)
    lowpass(b, 8200); finalize(b)
    return b

# ===== BGM2 : 少し緊張（16小節）===================================
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
    b = buf(length)
    bass, ap = [], []
    for i, (root, ch) in enumerate(BGM2_CHORDS):
        bass += [(i * 4 + k * 0.5, 0.42, root) for k in range(8)]
        ap += arp(i * 4, 4, ch, 0.25)
    play(b, spb, bass, 'square', 0.22, duty=0.35, a=0.002, d=0.03, s=0.7, r=0.04)
    play(b, spb, ap, 'square', 0.11, duty=0.25, a=0.002, d=0.04, s=0.45, r=0.05)
    play(b, spb, BGM2_MEL, 'tri', 0.19, a=0.02, d=0.15, s=0.6, r=0.14, vib=0.005, vibhz=5.5)
    for bar in range(16):
        t0 = bar * 4
        kick(b, t0 * spb); kick(b, (t0 + 1.5) * spb, 0.4); kick(b, (t0 + 2.5) * spb, 0.45)
        snare(b, (t0 + 1) * spb); snare(b, (t0 + 3) * spb)
        for k in range(8):
            hat(b, (t0 + k * 0.5) * spb, 0.09)
    lowpass(b, 7600); finalize(b)
    return b

# ===== BGM3 : あと少し！さらに緊張（16小節）=======================
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
    b = buf(length)
    bass, ap = [], []
    for i, (root, ch) in enumerate(BGM3_BARS):
        bass += [(i * 4 + k * 0.25, 0.22, root) for k in range(16)]
        ap += arp(i * 4, 4, ch, 0.125)
    play(b, spb, bass, 'square', 0.21, duty=0.3, a=0.001, d=0.02, s=0.72, r=0.02)
    play(b, spb, ap, 'square', 0.095, duty=0.2, a=0.001, d=0.025, s=0.4, r=0.03)
    play(b, spb, BGM3_MEL, 'square', 0.16, duty=0.42, a=0.008, d=0.1, s=0.6, r=0.1,
         vib=0.008, vibhz=6.5)
    for bar in range(16):
        t0 = bar * 4
        for k in (0, 1.5, 2, 3.5):
            kick(b, (t0 + k) * spb, 0.5)
        snare(b, (t0 + 1) * spb); snare(b, (t0 + 3) * spb)
        if bar % 4 == 3:
            for k in range(4):
                snare(b, (t0 + 3.5 + k * 0.125) * spb, 0.22, seed=k)
        for k in range(16):
            hat(b, (t0 + k * 0.25) * spb, 0.075, dur=0.022)
    lowpass(b, 8800); finalize(b)
    return b

# ===== BGM4 : お互いギリギリ・ハラハラ（16小節）===================
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
    b = buf(length)
    bass, ap = [], []
    for i, (root, dim) in enumerate(BGM4_BARS):
        bass += [(i * 4 + k * 0.25, 0.2, root) for k in range(16)]
        ap += arp(i * 4, 4, dim + list(reversed(dim)), 0.125)
    play(b, spb, bass, 'saw', 0.19, a=0.001, d=0.02, s=0.7, r=0.02)
    play(b, spb, ap, 'square', 0.10, duty=0.16, a=0.001, d=0.02, s=0.35, r=0.025)
    play(b, spb, BGM4_HOLD, 'tri', 0.13, a=0.05, d=0.2, s=0.75, r=0.2, vib=0.012, vibhz=8.0)
    for bar in range(16):
        t0 = bar * 4
        for k in (0, 0.35, 2, 2.35):
            kick(b, (t0 + k) * spb, 0.5)
        snare(b, (t0 + 1) * spb, 0.3); snare(b, (t0 + 3) * spb, 0.3)
        for k in range(16):
            hat(b, (t0 + k * 0.25) * spb, 0.085 if k % 4 == 0 else 0.055, dur=0.02)
    lowpass(b, 9000); finalize(b)
    return b

# ===== SE ==========================================================
def damage():
    """ピロピロピロ…ピコン"""
    b = buf(1.05)
    for i, f in enumerate((1245, 1046, 880)):
        t = 0.02 + i * 0.10
        tone(b, t, 0.055, f, 'square', 0.26, duty=0.5, a=0.001, d=0.02, s=0.7, r=0.03)
        tone(b, t, 0.055, f * 1.5, 'square', 0.08, duty=0.25, a=0.001, d=0.02, s=0.5, r=0.03)
    tone(b, 0.42, 0.07, 0, 'sine', 0.30, a=0.002, d=0.05, s=0.6, r=0.05, glide=(1568, 2093))
    tone(b, 0.49, 0.30, 2093, 'tri', 0.26, a=0.002, d=0.12, s=0.35, r=0.28)
    tone(b, 0.49, 0.30, 3136, 'sine', 0.10, a=0.002, d=0.10, s=0.25, r=0.26)
    lowpass(b, 11000); finalize(b, 0.9)
    return b

def coin():
    b = buf(0.9)
    for f, amp in ((1318, 0.22), (1975, 0.16), (2637, 0.10), (3520, 0.06)):
        tone(b, 0.0, 0.55, f, 'sine', amp, a=0.002, d=0.25, s=0.25, r=0.3)
    tone(b, 0.0, 0.05, 0, 'sine', 0.12, a=0.001, d=0.03, s=0.3, r=0.04, glide=(900, 1600))
    lowpass(b, 12000); finalize(b, 0.85)
    return b

def dice():
    b = buf(1.1)
    rnd = random.Random(99)
    t = 0.0
    for i in range(7):
        noise(b, t, 0.05, amp=0.28 - i * 0.02, decay=0.03, hp=0.85, seed=i)
        tone(b, t, 0.03, rnd.choice((520, 640, 760, 880)), 'tri', 0.10,
             a=0.001, d=0.02, s=0.3, r=0.03)
        t += 0.075 + i * 0.018
    tone(b, t + 0.05, 0.25, 1046, 'tri', 0.18, a=0.003, d=0.12, s=0.3, r=0.22)
    lowpass(b, 11000); finalize(b, 0.85)
    return b


if __name__ == '__main__':
    import sys
    out = sys.argv[1]
    loops = {}
    for name, fn in [('bgm1', bgm1), ('bgm2', bgm2), ('bgm3', bgm3), ('bgm4', bgm4)]:
        print('rendering', name, '...')
        b = fn()
        loops[name] = round(len(b) / SR, 6)          # ループ本体の正確な尺
        write_wav('%s/%s.wav' % (out, name), with_tail(b))
        print('     loop = %.6fs (+0.5s の余白つきで書き出し)' % loops[name])
    for name, fn in [('damage', damage), ('coin', coin), ('dice', dice)]:
        print('rendering', name, '...')
        write_wav('%s/%s.wav' % (out, name), fn())
    # アプリ側がループ終端を正確に指定するための尺一覧
    open('%s/loops.json' % out, 'w').write(json.dumps(loops, indent=1))
    print(json.dumps(loops))
