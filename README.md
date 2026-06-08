# Custom QMK Build for ZSA Moonlander (Clever Injection Method)

Custom QMK firmware and host-side tooling for the ZSA Moonlander — managed through
Oryx layout editing with zero-merge-conflict CI/CD injection of advanced features.

## Project Layout

```
Working-Oryx-QMK-Sync/
├── custom_qmk/               ← Canonical custom firmware (custom_code.c)
├── scripts/                  ← Python patching engine (patch_keymap.py)
├── host_tools/windhawk/      ← Windows Windhawk mod (.wh.cpp)
├── docs/                     ← Handoff reports & setup guides
├── .github/workflows/        ← CI: fetch Oryx source → patch → build → release
├── 3aMQz/                    ← Auto-synced patched layout snapshot
├── Dockerfile                ← Debian arm-none-eabi QMK build container
└── qmk_firmware/             ← ZSA QMK fork (submodule, fetched at build time)
```

## How It Works

**Oryx** (ZSA's online layout editor) is used to design the key layout visually,
but it has no native MIDI keycode support. Instead of manually maintaining an
Oryx-generated `keymap.c` (merge-conflict-prone), this project downloads the
fresh Oryx source in CI, runs `scripts/patch_keymap.py` to inject custom QMK
code (11 deterministic transformations), builds via Docker using ZSA's QMK fork,
and publishes the `.bin` as a release artifact.

No merge conflicts. Only custom code is tracked.

## Features

### MIDI Layer (Layer 2)

Two octaves of polyphonic MIDI input with split melody/bass and a transpose
shifter. Uses **MIDI_ADVANCED** so note keycodes route through `process_midi()`
(decodes by keycode value, not matrix position — required for the bass shifter).

#### Note map

Melody (Row 2, natural/white keys):

| Hand | Keys | Notes |
|---|---|---|
| Left | k20–k26 | `C3 D3 E3 F3 G3 A3 B3` |
| Right | k27–k2d | `C4 D4 E4 F4 G4 A4 B4` |

Sharps/flats (Row 1, biased right so each accidental sits above the next natural):

| Hand | Notes |
|---|---|
| Left (octave 3) | `C#3 D#3  F#3 G#3 A#3` |
| Right (octave 4) | `Db4 Eb4  Gb4 Ab4 Bb4` (enharmonic = `C#4 D#4 F#4 G#4 A#4`) |

Bass (Rows 3–4, left hand only; F#2 omitted to fit 11 keys):

| Row | Keys | Notes |
|---|---|---|
| Row 3 (BASS1–6) | k30–k35 | `C2 C#2 D2 D#2 E2 F2` |
| Row 4 (BASS7–11) | k40–k44 | `G2 G#2 A2 A#2 B2` |

#### Bass shifter (thumb cluster)

Two purple-lit left thumb keys: **BASS_up** (k51) and **BASS_down** (k52). Each
tap transposes all bass notes ±1 semitone (free transpose across octaves, clamped
−24..+24). Melody keys are in a higher keycode range and are never affected.

The firmware intercepts bass keys by **MIDI keycode range** (`MI_C2..MI_B2`), not
by matrix position. On press, the shifter forwards a transposed note keycode to
`process_midi()`, which emits the real MIDI note. Each held key snapshots its
shifted note keycode so that a shift change mid-hold cannot strand a stuck note.

> Note: under QMK MIDI, the keycode octave is **relative** to the global
> `midi_config.octave` (default puts `MI_C` at note 48 / C3). Keycode names
> describe note *relationships*; absolute pitch follows the global octave.

#### Build requirements (injected automatically by `patch_keymap.py`)

- `MIDI_ENABLE = yes` in `rules.mk`
- `#define MIDI_ADVANCED` in `config.h`
- `DEBOUNCE = 1` and `USB_POLLING_INTERVAL_MS = 1` for low-latency MIDI

### Language-Aware RGB

The left thumb indicator key lights **blue** (English) or **red** (Hebrew).
State is synced from Windows over RAW HID using Oryx's `ORYX_STATUS_LED_CONTROL`
command (`0x0A`):
- Param[0] = `0x00` → English
- Param[0] = `0x01` → Hebrew

The indicator only acts on the base layer (Layer 0); other layers use
Oryx-configured per-layer colors.

### Tap-Dance Stabilization

`patch_keymap.py` normalizes tap-dance handlers to fix tapping-term races:
`SINGLE_HOLD` → `SINGLE_TAP` fallback, `DOUBLE_SINGLE_TAP` → `DOUBLE_TAP`, and
hold-preference on Space/Shift and F18 language dances.

### Keymap (Base Layer Snapshot)

A modified QWERTY layout with dual-function thumb keys (managed in Oryx, snapshot
at `3aMQz/keymap.c`):

| Key | Function |
|---|---|
| DUAL_FUNC_0 (k22) | Tap: Ctrl+A / Hold: Alt+Shift+[ |
| DUAL_FUNC_1 (k2b) | Tap: Ctrl+E / Hold: Alt+Shift+] |
| TD(DANCE_0, left thumb) | Tap: Shift / Double: Caps |
| TD(DANCE_1, left thumb) | Tap: Space / Double: . + Space |
| TD(DANCE_2, right thumb) | Tap: Ctrl+S / Hold: Ctrl+Alt+Shift+5 |
| ST_MACRO_1 | Unicode `U+200A` + Enter |
| ST_MACRO_2 | Unicode `U+00A3` + Enter |
| ST_MACRO_14–19 | Unicode `U+200E` LTR mark inserts |

## Windhawk Mod (Windows)

`host_tools/windhawk/moonlander_language_sync.wh.cpp` (v1.2.0):

| Hotkey | Function |
|---|---|
| F18 | Language-switch (Win+Space / Alt+Shift / Ctrl+Shift) |
| F22 | Wrong-language fixer — flips Hebrew ↔ English by physical QWERTY position |
| F19 | Case cycler — lower → UPPER → Title → lower |

Also syncs Windows input language to keyboard RGB over RAW HID (polled ~120 ms).
**Collision note**: F21, F23 are already used as mod-tap triggers in the keymap;
map only F22 and F19 in Oryx. Setup at `docs/windhawk-language-sync.md`.

## Build Pipeline

Triggered manually via **Actions → Fetch and build layout** (`fetch-and-build-layout.yml`).
Parameters: Layout ID (`3aMQz`), geometry (`moonlander/reva`). Downloads Oryx
source → `patch_keymap.py` injection → Docker QMK build → `.bin` release artifact
→ commits patched snapshot to `3aMQz/`.

## Requirements

- ZSA Moonlander keyboard
- [Wally](https://www.zsa.io/wally) for flashing firmware
- GitHub account (for Actions)
- [Windhawk](https://windhawk.net/) (Windows-only, optional)
- Docker (for local builds; not needed for CI-only usage)
