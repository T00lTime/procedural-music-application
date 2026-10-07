# How the Procedural Music Works

**Short answer: there are no samples.** Nothing was downloaded, recorded, or
borrowed. Every sound is synthesized from scratch, sample by sample, by
mathematics, and written straight into the WAV. That's why it's genuinely $0 and
can't trip a copyright claim.

Tool: `~/.hermes/skills/creator/procedural-music/scripts/proc_music.py` (pure
Python stdlib — no numpy, no SoundFonts, no MIDI, no AI model).

---

## 1. The instruments are just waveforms

The `tone()` function turns a frequency into a stream of samples using one of a
few pure-math shapes:

| Layer | Waveform | The math |
|---|---|---|
| **sine** (bass, arpeggio) | sine | `sin(2π·f·t)` |
| **pad** | triangle | `(2/π)·asin(sin(2π·f·t))` |
| **saw** (available) | soft saw | `2·((f·t) mod 1) − 1` |
| **hat** | white noise | `random()·2 − 1`, decayed |

Each sample is shaped by an **envelope** (`env()`): a quick attack, a decay to a
sustain level, and a short release. That amplitude-over-time curve — not any
recording — is what makes a raw tone sound like a played note.

## 2. Pitch comes from a reference frequency

Frequencies use equal temperament from a single reference note, **A4**:

```
f = A4 · 2^(n / 12)      (n = semitones from A4)
```

- `n = 0` → A4
- `n = -12` → A3 (one octave down)
- `n = +7` → E5, etc.

**A4 = 432 Hz** (the "classical" tuning), not 440. Because *every* note is derived
from A4, changing the reference shifts the entire piece — all notes follow. The
reference is recorded in each track's recipe, so a render can be reproduced at the
exact tuning it was made with.

## 3. The drums are also synthesis
- **Kick:** a sine whose frequency sweeps downward over time —
  `f = 120·e^(−28t) + 42` — with amplitude `e^(−12t)`. The classic "thump," no sample.
- **Hi-hat:** a burst of white noise (`random()`) with a fast decay `e^(−60t)` and a
  very short duration.

## 4. The arrangement is music theory
The "composition" is generated, not recorded:
- a **scale** (minor / major semitone patterns),
- a four-chord **progression** (e.g. i → VI → iv → V),
- **triads** per chord, a **bass** on the root an octave down,
- an **arpeggio** cycling the triad on eighth notes.

All chosen by `--key`, `--mode`, `--style`, and `--bpm`.

## 5. Sound shaping (v3 additions)
Still pure math, still $0, still reproducible:
- **Lowpass filter** — a one-pole filter (`y += α·(x − y)` with
  `α = 1 − e^(−2π·fc/SR)`) to roll off harsh highs (`--cutoff`, default 9000 Hz).
- **Soft-clip** — `tanh(drive·x)` for warmth and gentle saturation instead of
  digital edges (`--drive`, default 1.3). Disable the whole stage with `--no-filter`.
- **Detuned oscillators** — each pad/arp note is two oscillators slightly apart in
  pitch (`--detune` cents, default 7), which thickens and widens the sound. Set
  `--detune 0` for a single, pure oscillator.

## 6. Why this matters (the recipe idea)
The only real inputs are the **parameters plus the seed**. The oscillator shapes
and composition rules are code; the randomness is Python's seeded Mersenne Twister
(`random`). So a track is a *pure function of its numbers*. That's why we back up
the **recipe** (`.recipe.json` / `.recipe.md`) instead of the multimegabyte WAV,
and why `--reproduce` can rebuild a **byte-identical** file.

> You're not sampling an instrument — you're **drawing the waveform.**

## Parameters at a glance
| Flag | Default | Purpose |
|---|---|---|
| `--style` | `calm` | `calm` `upbeat` `dark` `sparse` (mood/tempo/layers) |
| `--key` / `--mode` | `A` / `minor` | tonal center and chord family |
| `--bpm` | style | tempo override |
| `--seconds` | 45 | length |
| `--seed` | 1 | randomness (panning, hat noise) |
| `--a4` | **432** | reference frequency for A4 (retunes the whole piece) |
| `--detune` | 7 | cents between the two oscillators per note (0 = single) |
| `--cutoff` | 9000 | lowpass cutoff in Hz |
| `--drive` | 1.3 | soft-clip drive |
| `--no-filter` | off | disable lowpass + soft-clip |
| `--no-recipe` | off | skip writing the recipe sidecars |
| `--reproduce` | — | rebuild from a recipe file |
