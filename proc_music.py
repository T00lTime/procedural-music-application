#!/usr/bin/env python3
"""Procedural (algorithmic) royalty-free music generator — pure stdlib.

No samples: every sound is synthesized from math (sine/triangle/saw/noise) and
written straight to a WAV. A track is a pure function of its parameters, so this
script writes the audio AND a recipe (JSON + Markdown) describing exactly how to
recreate it. Back up the recipe, not the multi-MB WAV.

Tuning: equal temperament from A4 = 432 Hz by default (`--a4`), so the whole piece
follows the reference.

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
VERSION = 3  # bump when the synth changes (invalidates old recipes)
A4_DEFAULT = 432.0          # "classical" A reference (was 440)
DETUNE_DEFAULT = 7.0        # cents between the two pad/arp oscillators
CUTOFF_DEFAULT = 9000.0     # one-pole lowpass cutoff (Hz)
DRIVE_DEFAULT = 1.3         # tanh soft-clip drive

NOTE_SEMIS = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
              "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}
PROGRESSIONS = {
    "minor": [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],
    "major": [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],
}
TRIAD = {"maj": [0, 4, 7], "min": [0, 3, 7]}
STYLE = {
    "calm":   {"bpm": 70,  "pad": 0.30, "arp": 0.18, "bass": 0.22, "kick": 0.0,  "hat": 0.0},
    "upbeat": {"bpm": 112, "pad": 0.18, "arp": 0.22, "bass": 0.28, "kick": 0.55, "hat": 0.18},
    "dark":   {"bpm": 84,  "pad": 0.34, "arp": 0.14, "bass": 0.30, "kick": 0.35, "hat": 0.06},
    "sparse": {"bpm": 64,  "pad": 0.26, "arp": 0.10, "bass": 0.20, "kick": 0.0,  "hat": 0.0},
}


def note_freq(semitone_from_a4: float, a4: float = A4_DEFAULT) -> float:
    return a4 * (2.0 ** (semitone_from_a4 / 12.0))


class Buffer:
    def __init__(self, seconds: int):
        self.n = seconds * SR
        self.L = [0.0] * self.n
        self.R = [0.0] * self.n

    def add(self, start: int, samples: list[float], gain: float, pan: float = 0.0) -> None:
        gl = gain * (1.0 - max(0.0, pan))
        gr = gain * (1.0 + min(0.0, pan))
        for i, s in enumerate(samples):
            j = start + i
            if 0 <= j < self.n:
                self.L[j] += s * gl
                self.R[j] += s * gr

    def shape(self, cutoff: float = CUTOFF_DEFAULT, drive: float = DRIVE_DEFAULT) -> None:
        """One-pole lowpass + tanh soft-clip, in a single pass (deterministic)."""
        alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / SR)
        norm = math.tanh(drive) or 1.0
        for ch in (self.L, self.R):
            y = 0.0
            for i in range(len(ch)):
                y += alpha * (ch[i] - y)
                ch[i] = math.tanh(drive * y) / norm

    def write(self, path: str) -> None:
        peak = max(1e-9, max(abs(v) for v in self.L + self.R))
        norm = 0.89 / peak
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            frames = bytearray()
            for l, r in zip(self.L, self.R):
                frames += struct.pack("<hh", int(max(-1, min(1, l * norm)) * 32767),
                                            int(max(-1, min(1, r * norm)) * 32767))
            w.writeframes(bytes(frames))


def env(i: int, length: int, a: float = 0.01, d: float = 0.15, s: float = 0.6) -> float:
    t = i / SR
    if t < a:
        return t / a
    if t < a + d:
        return 1.0 - (1.0 - s) * ((t - a) / d)
    rel = (length - i) / SR
    if rel < 0.12:
        return s * max(0.0, rel / 0.12)
    return s


def tone(freq: float, seconds: float, wave_kind: str = "sine") -> list[float]:
    n = int(seconds * SR)
    out = []
    for i in range(n):
        ph = 2 * math.pi * freq * i / SR
        if wave_kind == "sine":
            v = math.sin(ph)
        elif wave_kind == "tri":
            v = 2 / math.pi * math.asin(math.sin(ph))
        else:  # soft saw
            v = 2 * ((freq * i / SR) % 1.0) - 1.0
        out.append(v * env(i, n))
    return out


def kick(seconds: float = 0.25) -> list[float]:
    n = int(seconds * SR)
    out = []
    for i in range(n):
        t = i / SR
        f = 120 * math.exp(-t * 28) + 42
        out.append(math.sin(2 * math.pi * f * t) * math.exp(-t * 12))
    return out


def hat(rnd: random.Random, seconds: float = 0.06) -> list[float]:
    n = int(seconds * SR)
    return [(rnd.random() * 2 - 1) * math.exp(-(i / SR) * 60) for i in range(n)]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render(out: str, seed: int, seconds: int, bpm: int, style: str, key: str, mode: str,
           a4: float = A4_DEFAULT, detune: float = DETUNE_DEFAULT,
           cutoff: float = CUTOFF_DEFAULT, drive: float = DRIVE_DEFAULT,
           use_filter: bool = True) -> dict:
    """Deterministic render. All randomness flows from `rnd`."""
    rnd = random.Random(seed)
    st = STYLE[style]
    bpm_eff = bpm or st["bpm"]
    beat = 60.0 / bpm_eff
    bar = beat * 4
    tonic = NOTE_SEMIS[key]
    prog = PROGRESSIONS[mode]
    ratio = 2.0 ** (detune / 1200.0) if detune else 1.0

    buf = Buffer(seconds)

    def osc(start: int, freq: float, dur: float, kind: str, gain: float, pan: float) -> None:
        if detune:
            # two slightly-detuned oscillators -> thicker, wider
            buf.add(start, tone(freq, dur, kind), gain * 0.72, pan)
            buf.add(start, tone(freq * ratio, dur, kind), gain * 0.72, -pan)
        else:
            buf.add(start, tone(freq, dur, kind), gain, pan)

    bar_idx = 0
    t = 0.0
    while t < seconds - bar:
        root_off, quality = prog[bar_idx % len(prog)]
        root = tonic + root_off
        triad = [root + x for x in TRIAD[quality]]
        for semi in triad:
            osc(int(t * SR), note_freq(semi, a4), bar * 1.05, "tri", st["pad"], rnd.uniform(-0.2, 0.2))
        buf.add(int(t * SR), tone(note_freq(root - 12, a4), bar * 0.95, "sine"), st["bass"])
        for e in range(8):
            semi = triad[e % 3] + (12 if e >= 6 else 0)
            osc(int((t + e * beat / 2) * SR), note_freq(semi, a4), beat * 0.45, "sine",
                st["arp"], rnd.uniform(-0.35, 0.35))
        if st["kick"]:
            for b in (0, 2):
                buf.add(int((t + b * beat) * SR), kick(), st["kick"])
        if st["hat"]:
            for e in range(8):
                buf.add(int((t + e * beat / 2) * SR), hat(rnd), st["hat"], pan=0.2)
        t += bar
        bar_idx += 1

    if use_filter:
        buf.shape(cutoff, drive)
    buf.write(out)
    return {"seed": seed, "seconds": seconds, "bpm": bpm_eff, "style": style, "key": key, "mode": mode,
            "a4": a4, "detune_cents": detune, "filter": use_filter,
            "lowpass_hz": cutoff, "softclip_drive": drive}


def write_recipe(out: str, params: dict) -> dict:
    with wave.open(out, "rb") as w:
        dur = w.getnframes() / w.getframerate()
        chans, sampw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    data = dict(params)
    data.update({
        "generator": "proc_music.py",
        "generator_version": VERSION,
        "generator_sha256": sha256_file(os.path.abspath(__file__)),
        "python_version": platform.python_version(),
        "sample_rate": rate, "channels": chans, "sample_width_bytes": sampw,
        "output": os.path.basename(out),
        "output_seconds": round(dur, 3),
        "output_bytes": os.path.getsize(out),
        "output_sha256": sha256_file(out),
        "reproduce": f"python3 {os.path.abspath(__file__)} --reproduce {os.path.basename(out)}.recipe.json --out REBUILT.wav",
    })
    with open(out + ".recipe.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(out + ".recipe.md", "w", encoding="utf-8") as f:
        f.write(
            f"# Music recipe — {data['output']}\n\n"
            "This WAV is a pure function of the parameters below (recorded from the\n"
            "actual render). Back up this recipe, not the audio.\n\n"
            f"```\npython3 ~/.hermes/skills/creator/procedural-music/scripts/proc_music.py \\\n"
            f"  --out {data['output']} --seed {data['seed']} --seconds {data['seconds']} \\\n"
            f"  --style {data['style']} --key {data['key']} --mode {data['mode']} --bpm {data['bpm']} \\\n"
            f"  --a4 {data['a4']} --detune {data['detune_cents']} --cutoff {data['lowpass_hz']} "
            f"--drive {data['softclip_drive']}" + ("" if data.get("filter", True) else " --no-filter") + "\n```\n\n"
            f"- tuning: A4 = {data['a4']} Hz (all notes follow)\n"
            f"- generator version: {data['generator_version']} (sha256 `{data['generator_sha256'][:12]}…`)\n"
            f"- python: {data['python_version']}\n"
            f"- output: {data['output_seconds']}s · {data['channels']}ch · {data['sample_rate']}Hz · "
            f"{data['output_bytes']} bytes\n"
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
    ap.add_argument("--a4", type=float, default=A4_DEFAULT, help="reference frequency for A4 (default 432)")
    ap.add_argument("--detune", type=float, default=DETUNE_DEFAULT, help="cents between the two oscillators (0 = single)")
    ap.add_argument("--cutoff", type=float, default=CUTOFF_DEFAULT, help="lowpass cutoff Hz")
    ap.add_argument("--drive", type=float, default=DRIVE_DEFAULT, help="soft-clip drive")
    ap.add_argument("--no-filter", action="store_true", help="disable lowpass + soft-clip")
    ap.add_argument("--reproduce", metavar="RECIPE.json", help="rebuild from a recipe file")
    ap.add_argument("--no-recipe", action="store_true", help="skip writing the recipe sidecar")
    args = ap.parse_args()

    if args.reproduce:
        d = json.load(open(args.reproduce, encoding="utf-8"))
        if d.get("generator_sha256") and d["generator_sha256"] != sha256_file(os.path.abspath(__file__)):
            print("WARNING: generator script differs from the one that made this recipe; "
                  "output may not be byte-identical.", file=sys.stderr)
        render(args.out, int(d["seed"]), int(d["seconds"]), int(d["bpm"]), d["style"], d["key"], d["mode"],
               float(d.get("a4", A4_DEFAULT)), float(d.get("detune_cents", DETUNE_DEFAULT)),
               float(d.get("lowpass_hz", CUTOFF_DEFAULT)), float(d.get("softclip_drive", DRIVE_DEFAULT)),
               bool(d.get("filter", True)))
        got = sha256_file(args.out)
        expect = d.get("output_sha256")
        print("MATCH" if got == expect else f"MISMATCH (expected {expect[:12]}…, got {got[:12]}…)")
        return 0

    params = render(args.out, args.seed, args.seconds, args.bpm, args.style, args.key, args.mode,
                    args.a4, args.detune, args.cutoff, args.drive, not args.no_filter)
    if not args.no_recipe:
        data = write_recipe(args.out, params)
        print(f"{args.out}\n  recipe: {args.out}.recipe.json")
        print(f"  sha256: {data['output_sha256'][:16]}…")
    else:
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
