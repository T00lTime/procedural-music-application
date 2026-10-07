#!/usr/bin/env python3
"""Measure a WAV's transient/timbral profile — the numbers I use to "see" sound.

Usage:
    python3 analyze.py FILE [FILE ...]
Prints onset, decay times, spectral centroid, band shares and stereo correlation
for each file so variants can be compared side by side. Writes a spectrogram PNG
if ffmpeg is available.
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

BANDS = [(0, 200, "<200"), (200, 1000, "200-1k"), (1000, 3000, "1k-3k"),
         (3000, 6000, "3k-6k"), (6000, 12000, "6k-12k"), (12000, 24000, ">12k")]


def load(path: str):
    w = wave.open(path)
    sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, ch).astype(np.float64) / 32768.0
    return x, sr


def band_share(seg: np.ndarray, sr: int):
    m = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / sr)
    e = m ** 2
    tot = e.sum() or 1
    return {name: 100 * e[(f >= lo) & (f < hi)].sum() / tot for lo, hi, name in BANDS}


def report(path: str) -> None:
    x, sr = load(path)
    mono = x.mean(axis=1)
    peak = np.max(np.abs(mono))
    rms = np.sqrt(np.mean(mono ** 2))
    print(f"\n=== {Path(path).name} ===")
    print(f"  {len(mono)/sr:.2f}s · {sr} Hz · {x.shape[1]}ch · peak {20*np.log10(peak+1e-12):.1f} dBFS · rms {20*np.log10(rms+1e-12):.1f} dBFS")

    # 0.5 ms envelope -> onset + decay
    h = max(1, int(0.0005 * sr))
    env = np.array([np.max(np.abs(mono[i:i + h])) for i in range(0, len(mono) - h, h)])
    db = 20 * np.log10(np.maximum(env, 1e-9))
    pk = int(np.argmax(env))
    seg = db[pk:]

    def dt(level_drop):
        idx = np.argmax(seg < db[pk] - level_drop)
        return f"{idx*0.5:.1f} ms" if np.any(seg < db[pk] - level_drop) else "—"

    corr = np.corrcoef(x[:, 0], x[:, 1])[0, 1] if x.shape[1] > 1 else 1.0
    print(f"  onset {pk*0.5:.1f} ms · decay -6/-12/-20/-40 dB: {dt(6)} / {dt(12)} / {dt(20)} / {dt(40)} · L/R {corr:.3f}")

    for label, (a, b) in {"transient 0-8ms": (0.0, 0.008), "event 0-60ms": (0.0, 0.060)}.items():
        s = mono[pk * h: pk * h + int(b * sr)]
        if len(s) < 256:
            continue
        m = np.abs(np.fft.rfft(s * np.hanning(len(s))))
        f = np.fft.rfftfreq(len(s), 1 / sr)
        cent = np.sum(f * m) / max(m.sum(), 1e-9)
        share = band_share(s, sr)
        print(f"  {label}: centroid {cent:.0f} Hz, peak {f[np.argmax(m)]:.0f} Hz")
        print("    " + ", ".join(f"{k}={v:.1f}%" for k, v in share.items()))

    png = "/tmp/" + Path(path).stem + "-spec.png"
    try:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
                        "-lavfi", "showspectrumpic=s=1200x560:legend=1:scale=log", png], check=True)
        print(f"  spectrogram: {png}")
    except Exception:
        pass


if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(p)
