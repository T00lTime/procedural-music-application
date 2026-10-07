#!/usr/bin/env python3
"""Procedural (algorithmic) royalty-free music generator — pure stdlib.

No samples: every sound is synthesized from math and written straight to a WAV.
A track is a pure function of its parameters, so this script writes the audio AND
a recipe (JSON + Markdown) describing exactly how to recreate it. Back up the
recipe, not the multi-MB WAV.

Tuning: equal temperament from A4 = 432 Hz by default (`--a4`).

v4 focus: stop sounding like a MIDI demo. Per-voice resonant filter envelopes,
real instrument voices (additive pad, plucked arp, warm bass), velocity + timing
humanization, stereo space, and an air shelf.

Usage:
    python3 proc_music.py --out track.wav --seed 42 --seconds 45 --style calm
    python3 proc_music.py --reproduce track.wav.recipe.json --out again.wav
Styles: calm | upbeat | dark | sparse
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import struct
import sys
import wave

SR = 44100
VERSION = 4  # bump when the synth changes (invalidates old recipes)
A4_DEFAULT = 432.0
DETUNE_DEFAULT = 9.0
CUTOFF_DEFAULT = 11000.0
DRIVE_DEFAULT = 1.25
AIR_DEFAULT = 0.35          # high-shelf "air" amount

NOTE_SEMIS = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
              "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}
PROGRESSIONS = {
    "minor": [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],
    "major": [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],
}
TRIAD = {"maj": [0, 4, 7], "min": [0, 3, 7]}
# per-style mix + character
STYLE = {
    "calm":   {"bpm": 68,  "pad": 0.30, "arp": 0.20, "bass": 0.24, "kick": 0.0,  "hat": 0.0,  "snare": 0.0,  "bright": 0.7},
    "upbeat": {"bpm": 112, "pad": 0.16, "arp": 0.24, "bass": 0.30, "kick": 0.55, "hat": 0.16, "snare": 0.22, "bright": 1.0},
    "dark":   {"bpm": 80,  "pad": 0.34, "arp": 0.16, "bass": 0.32, "kick": 0.32, "hat": 0.05, "snare": 0.10, "bright": 0.5},
    "sparse": {"bpm": 62,  "pad": 0.28, "arp": 0.12, "bass": 0.22, "kick": 0.0,  "hat": 0.0,  "snare": 0.0,  "bright": 0.6},
}


def note_freq(semitone_from_a4: float, a4: float = A4_DEFAULT) -> float:
    return a4 * (2.0 ** (semitone_from_a4 / 12.0))


# --------------------------------------------------------------------------- #
# Synthesis primitives
# --------------------------------------------------------------------------- #
def osc(freq: float, n: int, kind: str = "sine") -> list[float]:
    out = [0.0] * n
    w = 2.0 * math.pi * freq / SR
    if kind == "sine":
        for i in range(n):
            out[i] = math.sin(w * i)
    elif kind == "tri":
        for i in range(n):
            out[i] = (2.0 / math.pi) * math.asin(math.sin(w * i))
    else:  # soft saw
        for i in range(n):
            out[i] = 2.0 * (((freq * i / SR) % 1.0)) - 1.0
    return out


def svf_lowpass(sig: list[float], fc0: float, fc1: float, res: float = 1.1, block: int = 48) -> list[float]:
    """2-pole resonant lowpass with an exponential cutoff sweep fc0 -> fc1."""
    n = len(sig)
    out = [0.0] * n
    q = 1.0 / max(0.5, res)
    low = band = 0.0
    f = 0.0
    hi_lim = SR * 0.45
    for i in range(n):
        if i % block == 0:
            frac = i / max(1, n - 1)
            fc = fc0 * ((fc1 / fc0) ** frac)
            f = 2.0 * math.sin(math.pi * min(fc, hi_lim) / SR)
        high = sig[i] - low - q * band
        band += f * high
        low += f * band
        out[i] = low
    return out


def adsr(n: int, a: float, d: float, s: float, r: float) -> list[float]:
    A, D, R = int(a * SR), int(d * SR), int(r * SR)
    out = [0.0] * n
    for i in range(n):
        if A and i < A:
            v = i / A
        elif D and i < A + D:
            v = 1.0 - (1.0 - s) * ((i - A) / D)
        elif R and i >= n - R:
            v = s * ((n - i) / R)
        else:
            v = s
        out[i] = v
    return out


def voice(freq: float, dur: float, kind: str, env: tuple, fc0: float, fc1: float,
          res: float, detune: float, partials=None, trem=(0.0, 0.0, 0.0)) -> list[float]:
    """A single note: oscillator(s) -> filter sweep -> ADSR -> optional tremolo."""
    n = int(dur * SR)
    if not n:
        return []
    if partials:
        sig = [0.0] * n
        for mult, g in partials:
            s = osc(freq * mult, n, kind)
            for i in range(n):
                sig[i] += g * s[i]
    else:
        sig = osc(freq, n, kind)
    if detune:
        ratio = 2.0 ** (detune / 1200.0)
        s2 = osc(freq * ratio, n, kind)
        for i in range(n):
            sig[i] = 0.62 * sig[i] + 0.62 * s2[i]
    sig = svf_lowpass(sig, fc0, fc1, res)
    e = adsr(n, *env)
    rate, depth, phase = trem
    if depth:
        for i in range(n):
            sig[i] *= e[i] * (1.0 - depth + depth * (0.5 + 0.5 * math.sin(2 * math.pi * rate * i / SR + phase)))
    else:
        for i in range(n):
            sig[i] *= e[i]
    return sig


def kick(seconds: float = 0.25) -> list[float]:
    n = int(seconds * SR)
    return [math.sin(2 * math.pi * (120 * math.exp(-(i / SR) * 28) + 42) * (i / SR)) * math.exp(-(i / SR) * 12) for i in range(n)]


def hat(rnd, seconds: float = 0.06) -> list[float]:
    n = int(seconds * SR)
    return [(rnd.random() * 2 - 1) * math.exp(-(i / SR) * 60) for i in range(n)]


def snare(rnd, seconds: float = 0.18) -> list[float]:
    n = int(seconds * SR)
    tone_part = [math.sin(2 * math.pi * 180 * (i / SR)) * math.exp(-(i / SR) * 26) for i in range(n)]
    return [0.5 * tone_part[i] + 0.5 * (rnd.random() * 2 - 1) * math.exp(-(i / SR) * 22) for i in range(n)]


# --------------------------------------------------------------------------- #
# Buffer
# --------------------------------------------------------------------------- #
class Buffer:
    def __init__(self, seconds: int):
        self.n = seconds * SR
        self.L = [0.0] * self.n
        self.R = [0.0] * self.n

    def add(self, start: int, samples: list[float], gain: float, pan: float = 0.0) -> None:
        gl = gain * (1.0 - max(0.0, pan))
        gr = gain * (1.0 + min(0.0, pan))
        L, R, n = self.L, self.R, self.n
        for i, s in enumerate(samples):
            j = start + i
            if 0 <= j < n:
                L[j] += s * gl
                R[j] += s * gr

    def space(self, width: float = 1.0) -> None:
        """Cheap stereo depth: cross-fed early reflections + a Haas delay."""
        L, R, n = self.L, self.R, self.n
        taps = [(0.013, 0.32, 0), (0.021, 0.24, 1), (0.034, 0.18, 0), (0.055, 0.12, 1)]
        for d, g, ch in taps:
            dly = int(d * SR)
            src, dst = (L, R) if ch == 0 else (R, L)
            gg = g * width
            for i in range(dly, n):
                dst[i] += gg * src[i - dly]
        haas = int(0.008 * SR)  # ~8 ms width on the pad/arp
        for i in range(haas, n):
            R[i] += 0.16 * width * L[i - haas]

    def shape(self, cutoff: float = CUTOFF_DEFAULT, drive: float = DRIVE_DEFAULT, air: float = AIR_DEFAULT) -> None:
        """One-pole lowpass + air shelf + tanh soft-clip, single deterministic pass."""
        alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / SR)
        norm = math.tanh(drive) or 1.0
        for ch in (self.L, self.R):
            y = 0.0
            for i in range(len(ch)):
                x = ch[i]
                y += alpha * (x - y)
                shaped = x + air * (x - y)
                ch[i] = math.tanh(drive * shaped) / norm

    def write(self, path: str) -> None:
        n = self.n
        fade_in = max(1, int(0.02 * SR))
        fade_out = max(1, int(0.35 * SR))
        peak = max(1e-9, max(abs(v) for v in self.L + self.R))
        norm = 0.89 / peak
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            frames = bytearray()
            for i, (l, r) in enumerate(zip(self.L, self.R)):
                g = 1.0
                if i < fade_in:
                    g = i / fade_in
                elif i > n - fade_out:
                    g = max(0.0, (n - i) / fade_out)
                frames += struct.pack("<hh", int(max(-1, min(1, l * norm * g)) * 32767),
                                            int(max(-1, min(1, r * norm * g)) * 32767))
            w.writeframes(bytes(frames))


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(out: str, seed: int, seconds: int, bpm: int, style: str, key: str, mode: str,
           a4: float = A4_DEFAULT, detune: float = DETUNE_DEFAULT,
           cutoff: float = CUTOFF_DEFAULT, drive: float = DRIVE_DEFAULT,
           air: float = AIR_DEFAULT, use_filter: bool = True) -> dict:
    rnd = random.Random(seed)
    st = STYLE[style]
    bpm_eff = bpm or st["bpm"]
    beat = 60.0 / bpm_eff
    bar = beat * 4
    tonic = NOTE_SEMIS[key]
    prog = PROGRESSIONS[mode]
    br = st["bright"]

    buf = Buffer(seconds)

    def humanize(base_ms: float = 12.0) -> tuple[int, float]:
        return int(rnd.uniform(0, base_ms) / 1000.0 * SR), rnd.uniform(0.78, 1.0)

    bar_idx = 0
    t = 0.0
    while t < seconds:
        root_off, quality = prog[bar_idx % len(prog)]
        root = tonic + root_off
        triad = [root + x for x in TRIAD[quality]]

        # --- pad: warm additive, slow attack, gentle downward filter sweep ---
        for j, semi in enumerate(triad):
            off, vel = humanize(6)
            pan = (-0.35, 0.0, 0.35)[j % 3] * (0.6 + 0.4 * rnd.random())
            sig = voice(note_freq(semi, a4), bar * 1.15, "sine",
                        (0.9, 0.6, 0.75, 1.1), 2600 * br, 1100, 0.9, detune * 1.3,
                        partials=[(1, 1.0), (2, 0.34), (3, 0.16), (4, 0.07)],
                        trem=(0.14 + 0.05 * rnd.random(), 0.16, rnd.random() * 6.28))
            buf.add(int(t * SR) + off, sig, st["pad"] * vel, pan)

        # --- bass: warm (sine + 2nd harmonic), lowpassed ---
        off, vel = humanize(5)
        b = voice(note_freq(root - 12, a4), bar * 0.98, "sine",
                  (0.02, 0.25, 0.7, 0.2), 500, 380, 0.8, detune * 0.3,
                  partials=[(1, 1.0), (2, 0.28)])
        buf.add(int(t * SR) + off, b, st["bass"] * vel, 0.0)

        # --- arp/pluck: bright attack, quick decay, strong downward sweep ---
        for e in range(8):
            semi = triad[e % 3] + (12 if e >= 6 else 0)
            off, vel = humanize(16)
            pan = 0.5 if (e % 2 == 0) else -0.5
            dur = beat * 0.55
            p = voice(note_freq(semi, a4), dur, "saw",
                      (0.006, 0.28, 0.12, 0.10), 6200 * br, 950, 1.5, detune,
                      partials=[(1, 0.8), (2, 0.25)])
            buf.add(int((t + e * beat / 2) * SR) + off, p, st["arp"] * vel, pan)

        # --- percussion ---
        if st["kick"]:
            for bb in (0, 2):
                off, vel = humanize(3)
                buf.add(int((t + bb * beat) * SR) + off, kick(), st["kick"] * vel)
        if st["snare"]:
            off, vel = humanize(4)
            buf.add(int((t + 2 * beat) * SR) + off, snare(rnd), st["snare"] * vel, 0.1)
        if st["hat"]:
            for e in range(8):
                off, vel = humanize(8)
                buf.add(int((t + e * beat / 2) * SR) + off, hat(rnd), st["hat"] * vel, 0.25 if e % 2 else -0.25)

        t += bar
        bar_idx += 1

    buf.space(width=1.0)
    if use_filter:
        buf.shape(cutoff, drive, air)
    buf.write(out)
    return {"seed": seed, "seconds": seconds, "bpm": bpm_eff, "style": style, "key": key, "mode": mode,
            "a4": a4, "detune_cents": detune, "filter": use_filter,
            "lowpass_hz": cutoff, "softclip_drive": drive, "air": air}


# --------------------------------------------------------------------------- #
# Recipes
# --------------------------------------------------------------------------- #
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_recipe(out: str, params: dict) -> dict:
    with wave.open(out, "rb") as w:
        dur = w.getnframes() / w.getframerate()
        chans, sampw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    data = dict(params)
    data.update({
        "generator": "proc_music.py", "generator_version": VERSION,
        "generator_sha256": sha256_file(os.path.abspath(__file__)),
        "python_version": platform.python_version(),
        "sample_rate": rate, "channels": chans, "sample_width_bytes": sampw,
        "output": os.path.basename(out), "output_seconds": round(dur, 3),
        "output_bytes": os.path.getsize(out), "output_sha256": sha256_file(out),
        "reproduce": f"python3 {os.path.abspath(__file__)} --reproduce {os.path.basename(out)}.recipe.json --out REBUILT.wav",
    })
    with open(out + ".recipe.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(out + ".recipe.md", "w", encoding="utf-8") as f:
        f.write(
            f"# Music recipe — {data['output']}\n\n"
            "This WAV is a pure function of the parameters below. Back up this recipe, not the audio.\n\n"
            f"```\npython3 ~/.hermes/skills/creator/procedural-music/scripts/proc_music.py \\\n"
            f"  --out {data['output']} --seed {data['seed']} --seconds {data['seconds']} \\\n"
            f"  --style {data['style']} --key {data['key']} --mode {data['mode']} --bpm {data['bpm']} \\\n"
            f"  --a4 {data['a4']} --detune {data['detune_cents']} --cutoff {data['lowpass_hz']} "
            f"--drive {data['softclip_drive']} --air {data['air']}"
            + ("" if data.get("filter", True) else " --no-filter") + "\n```\n\n"
            f"- tuning: A4 = {data['a4']} Hz (all notes follow)\n"
            f"- generator version: {data['generator_version']} (sha256 `{data['generator_sha256'][:12]}…`)\n"
            f"- output: {data['output_seconds']}s · {data['channels']}ch · {data['sample_rate']}Hz · {data['output_bytes']} bytes\n"
            f"- output sha256: `{data['output_sha256']}`\n"
        )
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seconds", type=int, default=45)
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--style", choices=list(STYLE), default="calm")
    ap.add_argument("--key", default="A", choices=list(NOTE_SEMIS))
    ap.add_argument("--mode", dest="mode", default="minor", choices=list(SCALES))
    ap.add_argument("--a4", type=float, default=A4_DEFAULT)
    ap.add_argument("--detune", type=float, default=DETUNE_DEFAULT)
    ap.add_argument("--cutoff", type=float, default=CUTOFF_DEFAULT)
    ap.add_argument("--drive", type=float, default=DRIVE_DEFAULT)
    ap.add_argument("--air", type=float, default=AIR_DEFAULT)
    ap.add_argument("--no-filter", action="store_true")
    ap.add_argument("--reproduce", metavar="RECIPE.json")
    ap.add_argument("--no-recipe", action="store_true")
    args = ap.parse_args()

    if args.reproduce:
        d = json.load(open(args.reproduce, encoding="utf-8"))
        if d.get("generator_sha256") and d["generator_sha256"] != sha256_file(os.path.abspath(__file__)):
            print("WARNING: generator script differs from the one that made this recipe; output may differ.", file=sys.stderr)
        render(args.out, int(d["seed"]), int(d["seconds"]), int(d["bpm"]), d["style"], d["key"], d["mode"],
               float(d.get("a4", A4_DEFAULT)), float(d.get("detune_cents", DETUNE_DEFAULT)),
               float(d.get("lowpass_hz", CUTOFF_DEFAULT)), float(d.get("softclip_drive", DRIVE_DEFAULT)),
               float(d.get("air", AIR_DEFAULT)), bool(d.get("filter", True)))
        got, expect = sha256_file(args.out), d.get("output_sha256")
        print("MATCH" if got == expect else f"MISMATCH (expected {expect[:12]}…, got {got[:12]}…)")
        return 0

    params = render(args.out, args.seed, args.seconds, args.bpm, args.style, args.key, args.mode,
                    args.a4, args.detune, args.cutoff, args.drive, args.air, not args.no_filter)
    if not args.no_recipe:
        data = write_recipe(args.out, params)
        print(f"{args.out}\n  recipe: {args.out}.recipe.json\n  sha256: {data['output_sha256'][:16]}…")
    else:
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
