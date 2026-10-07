# procedural-music-application

A tiny, dependency-free **procedural music generator**. It composes original,
royalty-free music from pure mathematics — **no samples, no SoundFonts, no MIDI,
no AI models** — and writes a WAV **plus a recipe** that can recreate that WAV
byte-for-byte.

- **$0 and copyright-safe** — every sound is synthesized from sine / triangle /
  saw / noise waveforms. Nothing is sampled or borrowed.
- **Deterministic** — a track is a pure function of its parameters + seed, so you
  version the *numbers*, not the multi-MB audio.
- **Tunable** — **A4 = 432 Hz** by default (classical); every note follows it.
- **Shaped** — detuned oscillators, a one-pole lowpass, and a `tanh` soft-clip.
- **Pure stdlib** — Python 3.9+, nothing to `pip install`.

License: **GPL-3.0** (see [`LICENSE`](LICENSE)).

---

## What it is (and the idea behind it)

You are not sampling an instrument — you are **drawing the waveform**. Each note is
a mathematical curve (`sin`, `asin(sin)`, etc.) shaped by an amplitude envelope;
the drums are a pitch-swept sine and decayed noise; the arrangement comes from
scales, chord progressions, and arpeggios. Because the whole thing is a formula, a
track is fully described by its parameters — so the repo stores **recipes**
(the numbers) instead of regenerable audio.

Full explainer: [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md).

## Quick start

```bash
git clone https://github.com/T00lTime/procedural-music-application.git
cd procedural-music-application
python3 proc_music.py --out track.wav --style calm --key A --mode minor --seconds 45 --seed 42
```

That writes `track.wav` plus `track.wav.recipe.json` and `track.wav.recipe.md`.
(The `.wav` is gitignored on purpose.)

## Flags

| Flag | Default | What it does |
|---|---|---|
| `--out PATH` | *required* | output WAV path (also determines the recipe filenames) |
| `--seed N` | `1` | randomness source (panning, hat noise); same inputs = identical bytes |
| `--seconds N` | `45` | length in seconds |
| `--bpm N` | style | tempo override (`0` = use the style's tempo) |
| `--style` | `calm` | `calm` `upbeat` `dark` `sparse` (mood, tempo, layers) |
| `--key` | `A` | `C C# D D# E F F# G G# A A# B` |
| `--mode` | `minor` | `minor` `major` (chord family + progression) |
| `--a4 HZ` | `432` | reference frequency for A4 (classical = 432; historical 440) |
| `--detune CENTS` | `7` | cents between the two oscillators per pad/arp note (`0` = single) |
| `--cutoff HZ` | `9000` | one-pole lowpass cutoff |
| `--drive X` | `1.3` | `tanh` soft-clip drive |
| `--no-filter` | off | disable the lowpass + soft-clip stage |
| `--no-recipe` | off | do not write the recipe sidecars |
| `--reproduce RECIPE.json` | — | rebuild audio from a recipe and verify its SHA-256 |

### Styles at a glance

| style | bpm | pad | arp | bass | kick | hat |
|---|---|---|---|---|---|---|
| calm | 70 | ✓ | ✓ | ✓ | — | — |
| upbeat | 112 | ✓ | ✓ | ✓ | ✓ | ✓ |
| dark | 84 | ✓ | ✓ | ✓ | ✓ | ✓ |
| sparse | 64 | ✓ | ✓ | ✓ | — | — |

## Examples

```bash
# calm bed, classical tuning
python3 proc_music.py --out bed.wav --style calm --key D --mode minor --seconds 180 --seed 3551

# upbeat major in E, one minute
python3 proc_music.py --out mine.wav --style upbeat --key E --mode major --bpm 128 --seconds 60 --seed 7

# dark minor in F#, 90 seconds, no detune
python3 proc_music.py --out dark.wav --style dark --key F# --mode minor --seconds 90 --detune 0

# reproduce a recipe and verify it byte-for-byte
python3 proc_music.py --reproduce bed.wav.recipe.json --out rebuilt.wav      # prints MATCH
```

## Recipes (the important part)

Every render writes two tiny sidecars next to the WAV:

- `*.recipe.json` — machine-readable: all inputs, `a4`, detune, filter settings,
  generator **version + SHA-256**, Python version, and the output SHA-256/size/duration.
- `*.recipe.md` — a human cheat sheet with the exact rebuild command.

Back up the recipe, not the audio: `--reproduce` rebuilds the WAV and prints
`MATCH` when it is byte-identical. If the generator script has changed since the
recipe was made, it warns (the SHA-256 in the recipe is the script that made it).

## Versioning / snapshots (naming convention)

This repo uses the same **timestamped-snapshot** convention as the agent backups:

```
snapshots/YYYY-MM-DD_HH-MM/     # one dir per snapshot
  proc_music.py                 # that version of the script
  MANIFEST.json                 # timestamp, version, sha256, python version, note
latest/                         # local-only mirror of the newest snapshot (gitignored)
```

- Multiple snapshots per day never overwrite each other; a same-minute second
  snapshot gets a `-2`, `-3`, … suffix.
- Take one whenever you tweak the generator:

```bash
python3 snapshot.py --note "add stereo delay"
```

## Repo layout

```
proc_music.py            the generator (the thing you tweak)
snapshot.py              create a timestamped snapshot + refresh latest/
docs/HOW-IT-WORKS.md     the "where do the sounds come from" explainer
snapshots/<ts>/          timestamped versions (naming convention above)
README.md · LICENSE · .gitignore
```

## Notes / gotchas

- **Determinism:** all randomness flows from `--seed`; same params + same script
  version = identical bytes. Bump `VERSION` in `proc_music.py` when you change the
  synth (it invalidates old recipes).
- **Tuning:** A4 defaults to 432 Hz. Tracks made before this used 440 Hz; pass
  `--a4 440` to render with the old reference.
- **Looping:** make `--seconds` a whole multiple of the bar time (`bar = 4·60/bpm`)
  for a clean loop.
- **Seed's real effect** is small (panning + hat noise); the big audible levers are
  `--style`, `--key`, `--mode`, `--bpm`, `--seconds`.
