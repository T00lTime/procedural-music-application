#!/usr/bin/env python3
"""Isolated finger-snap primitive lab.

Renders ONLY a snap (no pad/bass/arp) so the primitive can be heard and tweaked
in isolation — the "solo each primitive" workflow. Targets a real finger snap:
fast broadband crack (~4-5 ms to -6 dB), ~60 ms to -40 dB, peak ~2-6 kHz,
centroid ~5-6 kHz, little low end.

Model: a white-noise burst, spectrally shaped by a highpass (kill rumble) and a
lowpass (tame fizz) plus an optional resonant "thock", then shaped by a direct
crack+tail envelope. Noise-based (a snap is a noise transient, not a tone), so
the decay is fully controllable.

Usage:
    python3 snap_synth.py --out snap.wav --reps 4
    python3 snap_synth.py --out snap.wav --hp 800 --lp 11000 --crack 0.003 --tail 0.02 --tail-amt 0.4 --thock 0.25
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import wave

SR = 44100


def svf_lp(sig: list[float], fc: float, res: float = 1.0) -> list[float]:
    f = 2.0 * math.sin(math.pi * min(fc, SR * 0.45) / SR)
    q = 1.0 / max(0.5, res)
    low = band = 0.0
    out = [0.0] * len(sig)
    for i, x in enumerate(sig):
        high = x - low - q * band
        band += f * high
        low += f * band
        out[i] = low
    return out


def onepole_lp(sig: list[float], fc: float) -> list[float]:
    """Plain one-pole lowpass — stable at any cutoff (no resonance)."""
    a = 1.0 - math.exp(-2.0 * math.pi * min(fc, SR * 0.49) / SR)
    y = 0.0
    out = [0.0] * len(sig)
    for i, x in enumerate(sig):
        y += a * (x - y)
        out[i] = y
    return out


def svf_bp(sig: list[float], fc: float, damping: float) -> list[float]:
    f = 2.0 * math.sin(math.pi * min(fc, SR * 0.45) / SR)
    low = band = 0.0
    out = [0.0] * len(sig)
    for i, x in enumerate(sig):
        high = x - low - damping * band
        band += f * high
        low += f * band
        out[i] = band
    return out


def snap(seed: int, dur: float, hp: float, lp: float, crack: float, tail: float,
         tail_amt: float, thock: float, thock_fc: float) -> list[float]:
    rnd = random.Random(seed)
    n = int(dur * SR)
    x = [rnd.random() * 2 - 1 for _ in range(n)]
    low = onepole_lp(x, hp)                    # remove rumble below hp
    y = [x[i] - low[i] for i in range(n)]
    y = onepole_lp(y, lp)                      # tame extreme fizz above lp
    if thock > 0:                              # resonant "thock" body at ~2 kHz
        r = svf_bp(x, thock_fc, 0.18)
        mr = max(1e-9, max(abs(v) for v in r))
        y = [y[i] + thock * r[i] / mr for i in range(n)]
    for i in range(n):                         # crack + tail envelope (direct control)
        t = i / SR
        y[i] *= math.exp(-t / crack) + tail_amt * math.exp(-t / tail)
    peak = max(1e-9, max(abs(v) for v in y))
    return [math.tanh(1.8 * v / peak * 0.9) for v in y]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--hp", type=float, default=800.0)
    ap.add_argument("--lp", type=float, default=11000.0)
    ap.add_argument("--crack", type=float, default=0.003)
    ap.add_argument("--tail", type=float, default=0.02)
    ap.add_argument("--tail-amt", type=float, default=0.4)
    ap.add_argument("--thock", type=float, default=0.25)
    ap.add_argument("--thock-fc", type=float, default=2200.0)
    args = ap.parse_args()

    dur = args.crack * 8 + args.tail * 6 + 0.02
    total = int((args.reps * args.gap + dur + 0.1) * SR)
    buf = [0.0] * total
    for k in range(args.reps):
        s = snap(args.seed + k, dur, args.hp, args.lp, args.crack, args.tail, args.tail_amt, args.thock, args.thock_fc)
        start = int(k * args.gap * SR)
        for i, v in enumerate(s):
            if start + i < total:
                buf[start + i] += v

    peak = max(1e-9, max(abs(v) for v in buf))
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v / peak * 0.9)) * 32767)) for v in buf))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
