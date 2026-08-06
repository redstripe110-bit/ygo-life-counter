#!/usr/bin/env python3
"""依存ライブラリなしでチップチューン風のBGM/SEを合成して WAV を書き出す。
   すべてオリジナルの手打ちシーケンス（既存楽曲の複製は一切していない）。"""
import math, struct, wave, random
from array import array

SR = 44100

# ---------------------------------------------------------------- 基礎

def midi(name):
    """'A#3' -> MIDI番号"""
    table = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}
    i = 1 if len(name) > 2 else 1
    key = name[:-1]
    octv = int(name[-1])
    return 12 * (octv + 1) + table[key]

def hz(name):
    return 440.0 * (2.0 ** ((midi(name) - 69) / 12.0))

def buf(seconds):
    return array('d', [0.0]) * int(SR * seconds)

def add(dst, pos, val):
    """ループ境界をまたぐ音は先頭に回り込ませる（シームレスループのため）"""
    n = len(dst)
    dst[pos % n] += val

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
    """簡易ADSR（秒指定）"""
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
    """1音を書き込む。glide=(from,to) で周波数を滑らせる"""
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
    """ノイズ（ハイパス風の一次差分つき）"""
    rnd = random.Random(seed if seed is not None else 12345)
    n = int(dur * SR)
    i0 = int(start * SR)
    prev = 0.0
    k = decay if decay else dur
    for i in range(n):
        t = i / SR
        e = math.exp(-t / (k * 0.35))
        x = rnd.uniform(-1.0, 1.0)
        y = x - hp * prev
        prev = x
        add(dst, i0 + i, y * amp * e)

# ---------------------------------------------------------------- ドラム

def kick(dst, start, amp=0.55):
    n = int(0.14 * SR); i0 = int(start * SR); ph = 0.0
    for i in range(n):
        t = i / SR
        f = 45 + 115 * math.exp(-t / 0.022)
        ph += f / SR
        e = math.exp(-t / 0.055)
        add(dst, i0 + i, math.sin(2 * math.pi * ph) * amp * e)

def snare(dst, start, amp=0.34, seed=7):
    noise(dst, start, 0.14, amp=amp, decay=0.10, hp=0.55, seed=seed)
    tone(dst, start, 0.05, 190, 'tri', amp=amp * 0.5, a=0.001, d=0.03, s=0.2, r=0.03)

def hat(dst, start, amp=0.12, dur=0.035, seed=3):
    noise(dst, start, dur, amp=amp, decay=dur, hp=0.92, seed=seed)

# ---------------------------------------------------------------- 仕上げ

def lowpass(b, cutoff=6500.0):
    x = math.exp(-2 * math.pi * cutoff / SR)
    y = 0.0
    for i in range(len(b)):
        y = (1 - x) * b[i] + x * y
        b[i] = y

def finalize(b, peak=0.86):
    m = max(abs(v) for v in b) or 1.0
    g = peak / m
    for i in range(len(b)):
        v = b[i] * g
        b[i] = math.tanh(v * 1.15) * 0.92   # 軽くサチュレート

def write_wav(path, b):
    w = wave.open(path, 'wb')
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(b''.join(struct.pack('<h', int(max(-1.0, min(1.0, v)) * 32767)) for v in b))
    w.close()
    print('  ->', path, '%.1fs' % (len(b) / SR))

# ---------------------------------------------------------------- 楽曲

def play(dst, spb, pattern, kind, amp, duty=0.5, oct_shift=0, **kw):
    """pattern: [(beat, len_in_beats, 'A4' or None), ...]"""
    for beat, ln, note in pattern:
        if note is None:
            continue
        f = hz(note) * (2.0 ** oct_shift)
        tone(dst, beat * spb, ln * spb * 0.92, f, kind, amp, duty, **kw)

def arp(start_beat, beats, notes, step=0.25):
    """アルペジオ用のパターン生成"""
    out = []
    n = int(beats / step)
    for i in range(n):
        out.append((start_beat + i * step, step, notes[i % len(notes)]))
    return out

def bars(bpm, count):
    spb = 60.0 / bpm
    return spb, spb * 4 * count


# ===== BGM1 : 快活な戦闘曲 =========================================
def bgm1():
    bpm = 148; spb, length = bars(bpm, 8)
    b = buf(length)
    # コード進行 Am - F - C - G （4小節 x 2）
    roots = ['A2', 'F2', 'C3', 'G2'] * 2
    # ベース：8分の刻み
    bass = []
    for bar in range(8):
        r = roots[bar]
        for k in range(8):
            n = r if k % 4 != 3 else r  # 同音刻み
            bass.append((bar * 4 + k * 0.5, 0.45, n))
    play(b, spb, bass, 'square', 0.20, duty=0.5, a=0.002, d=0.03, s=0.75, r=0.04)

    # リード：勇ましい8分メロディ
    mel = [
        'A4','C5','E5','C5','A4','B4','C5','E5',
        'F4','A4','C5','A4','F4','G4','A4','C5',
        'C5','E5','G5','E5','C5','D5','E5','G5',
        'G4','B4','D5','B4','G4','A4','B4','D5',
    ]
    lead = []
    for bar in range(8):
        for k in range(4):
            idx = (bar % 4) * 8 + k * 2
            lead.append((bar * 4 + k, 0.45, mel[idx]))
            lead.append((bar * 4 + k + 0.5, 0.45, mel[idx + 1]))
    play(b, spb, lead, 'square', 0.17, duty=0.5, a=0.003, d=0.06, s=0.62, r=0.09)

    # ハモリ（3度下・控えめ）
    play(b, spb, [(t, l, n) for (t, l, n) in lead if int(t * 2) % 2 == 0],
         'tri', 0.075, oct_shift=-1, a=0.005, d=0.08, s=0.5, r=0.1)

    # ドラム
    for bar in range(8):
        t0 = bar * 4
        kick(b, (t0 + 0) * spb); kick(b, (t0 + 2) * spb)
        kick(b, (t0 + 2.75) * spb, 0.4)
        snare(b, (t0 + 1) * spb); snare(b, (t0 + 3) * spb)
        for k in range(8):
            hat(b, (t0 + k * 0.5) * spb, 0.10 if k % 2 == 0 else 0.07)
    lowpass(b, 8200); finalize(b)
    return b

# ===== BGM2 : 少し緊張 =============================================
def bgm2():
    bpm = 156; spb, length = bars(bpm, 8)
    b = buf(length)
    roots = ['A2', 'A2', 'F2', 'F2', 'D2', 'D2', 'E2', 'E2']
    bass = []
    for bar in range(8):
        r = roots[bar]
        for k in range(8):
            bass.append((bar * 4 + k * 0.5, 0.42, r))
    play(b, spb, bass, 'square', 0.22, duty=0.35, a=0.002, d=0.03, s=0.7, r=0.04)

    # 不安げなアルペジオ（16分）
    chords = [['A3','C4','E4','C4'], ['A3','C4','E4','C4'],
              ['F3','A3','C4','A3'], ['F3','A3','C4','A3'],
              ['D3','F3','A3','F3'], ['D3','F3','A3','F3'],
              ['E3','G#3','B3','G#3'], ['E3','G#3','B3','G#3']]
    ap = []
    for bar in range(8):
        ap += arp(bar * 4, 4, chords[bar], 0.25)
    play(b, spb, ap, 'square', 0.11, duty=0.25, a=0.002, d=0.04, s=0.45, r=0.05)

    # 上物：長めのメロディ（少し不安定な半音を含む）
    mel = [(0,2,'E5'),(2,1,'D5'),(3,1,'C5'),
           (4,2,'C5'),(6,2,'B4'),
           (8,2,'A4'),(10,1,'C5'),(11,1,'D5'),
           (12,3,'E5'),(15,1,'F5'),
           (16,2,'D5'),(18,2,'C5'),
           (20,2,'B4'),(22,2,'A4'),
           (24,2,'G#4'),(26,2,'B4'),
           (28,4,'E5')]
    play(b, spb, mel, 'tri', 0.19, a=0.02, d=0.15, s=0.6, r=0.14, vib=0.005, vibhz=5.5)

    for bar in range(8):
        t0 = bar * 4
        kick(b, (t0 + 0) * spb); kick(b, (t0 + 1.5) * spb, 0.4); kick(b, (t0 + 2.5) * spb, 0.45)
        snare(b, (t0 + 1) * spb); snare(b, (t0 + 3) * spb)
        for k in range(8):
            hat(b, (t0 + k * 0.5) * spb, 0.09)
    lowpass(b, 7600); finalize(b)
    return b

# ===== BGM3 : あと少し！さらに緊張 =================================
def bgm3():
    bpm = 168; spb, length = bars(bpm, 8)
    b = buf(length)
    # 半音で押し上げるベース
    roots = ['A2','A2','A#2','A#2','B2','B2','C3','C3']
    bass = []
    for bar in range(8):
        r = roots[bar]
        for k in range(16):
            bass.append((bar * 4 + k * 0.25, 0.22, r))
    play(b, spb, bass, 'square', 0.21, duty=0.3, a=0.001, d=0.02, s=0.72, r=0.02)

    chords = [['A3','C4','E4','G4'], ['A3','C4','E4','G4'],
              ['A#3','C#4','F4','G#4'], ['A#3','C#4','F4','G#4'],
              ['B3','D4','F#4','A4'], ['B3','D4','F#4','A4'],
              ['C4','D#4','G4','A#4'], ['C4','D#4','G4','A#4']]
    ap = []
    for bar in range(8):
        ap += arp(bar * 4, 4, chords[bar], 0.125)
    play(b, spb, ap, 'square', 0.095, duty=0.2, a=0.001, d=0.025, s=0.4, r=0.03)

    mel = [(0,1.5,'E5'),(1.5,0.5,'F5'),(2,2,'E5'),
           (4,1.5,'G5'),(5.5,0.5,'F5'),(6,2,'E5'),
           (8,1.5,'F5'),(9.5,0.5,'F#5'),(10,2,'F5'),
           (12,2,'G#5'),(14,2,'F5'),
           (16,1.5,'F#5'),(17.5,0.5,'G5'),(18,2,'F#5'),
           (20,1.5,'A5'),(21.5,0.5,'G5'),(22,2,'F#5'),
           (24,1.5,'G5'),(25.5,0.5,'G#5'),(26,2,'G5'),
           (28,4,'A#5')]
    play(b, spb, mel, 'square', 0.16, duty=0.42, a=0.008, d=0.1, s=0.6, r=0.1,
         vib=0.008, vibhz=6.5)

    for bar in range(8):
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

# ===== BGM4 : お互いギリギリ・ハラハラ =============================
def bgm4():
    bpm = 182; spb, length = bars(bpm, 8)
    b = buf(length)
    # トライトーンで揺れるベース
    pat = ['D2','G#2','D2','G#2','C2','F#2','C2','F#2']
    bass = []
    for bar in range(8):
        r = pat[bar]
        for k in range(16):
            bass.append((bar * 4 + k * 0.25, 0.2, r))
    play(b, spb, bass, 'saw', 0.19, a=0.001, d=0.02, s=0.7, r=0.02)

    # 減七のアルペジオ（16分・休みなし）
    dim = [['D4','F4','G#4','B4'], ['D4','F4','G#4','B4'],
           ['D#4','F#4','A4','C5'], ['D#4','F#4','A4','C5'],
           ['C4','D#4','F#4','A4'], ['C4','D#4','F#4','A4'],
           ['C#4','E4','G4','A#4'], ['C#4','E4','G4','A#4']]
    ap = []
    for bar in range(8):
        ap += arp(bar * 4, 4, dim[bar] + list(reversed(dim[bar])), 0.125)
    play(b, spb, ap, 'square', 0.10, duty=0.16, a=0.001, d=0.02, s=0.35, r=0.025)

    # 上で鳴り続ける不安な持続音（トレモロ）
    hold = [(0,4,'A5'),(4,4,'A#5'),(8,4,'A5'),(12,4,'G#5'),
            (16,4,'A5'),(20,4,'C6'),(24,4,'A#5'),(28,4,'A5')]
    play(b, spb, hold, 'tri', 0.13, a=0.05, d=0.2, s=0.75, r=0.2, vib=0.012, vibhz=8.0)

    # 心拍のような低音
    for bar in range(8):
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
    # ピロピロピロ（下降する短い矩形波）
    for i, f in enumerate((1245, 1046, 880)):
        t = 0.02 + i * 0.10
        tone(b, t, 0.055, f, 'square', 0.26, duty=0.5, a=0.001, d=0.02, s=0.7, r=0.03)
        tone(b, t, 0.055, f * 1.5, 'square', 0.08, duty=0.25, a=0.001, d=0.02, s=0.5, r=0.03)
    # …（間）… ピコン
    tone(b, 0.42, 0.07, 0, 'sine', 0.30, a=0.002, d=0.05, s=0.6, r=0.05,
         glide=(1568, 2093))
    tone(b, 0.49, 0.30, 2093, 'tri', 0.26, a=0.002, d=0.12, s=0.35, r=0.28)
    tone(b, 0.49, 0.30, 3136, 'sine', 0.10, a=0.002, d=0.10, s=0.25, r=0.26)
    lowpass(b, 11000); finalize(b, 0.9)
    return b

def coin():
    b = buf(0.9)
    for f, a in ((1318, 0.22), (1975, 0.16), (2637, 0.10), (3520, 0.06)):
        tone(b, 0.0, 0.55, f, 'sine', a, a=0.002, d=0.25, s=0.25, r=0.3)
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
    jobs = [('bgm1', bgm1), ('bgm2', bgm2), ('bgm3', bgm3), ('bgm4', bgm4),
            ('damage', damage), ('coin', coin), ('dice', dice)]
    for name, fn in jobs:
        print('rendering', name, '...')
        write_wav('%s/%s.wav' % (out, name), fn())
