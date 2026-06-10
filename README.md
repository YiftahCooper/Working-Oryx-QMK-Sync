# Custom QMK Firmware for ZSA Moonlander

Advanced MIDI keyboard, language-aware RGB, and Windows text automation — managed through Oryx with zero-merge-conflict CI/CD injection.

## Overview

This repository provides custom QMK firmware for the ZSA Moonlander keyboard, combining:

- **MIDI Layer**: Two-octave polyphonic MIDI input with bass transpose shifter
- **Language-Aware RGB**: Hebrew/English indicator with Windows sync
- **Windhawk Mod**: Windows-side text automation (wrong-language fixer, case cycler)
- **CI/CD Pipeline**: Automated Oryx → patch → build → release workflow

The key innovation: Oryx (ZSA's online layout editor) has no native MIDI support. Instead of manually maintaining merge-conflict-prone `keymap.c` files, this project downloads fresh Oryx source in CI, runs `scripts/patch_keymap.py` to inject custom code, builds via Docker, and publishes `.bin` firmware. **No merge conflicts. Only custom code is tracked.**

## Project Structure

```
Working-Oryx-QMK-Sync/
├── custom_qmk/               ← Canonical custom firmware (custom_code.c)
│   └── custom_code.c         ← MIDI bass shifter, language RGB, tap-dance handlers
├── scripts/                  ← Python patching engine
│   └── patch_keymap.py       ← 11+ deterministic transformations injected into Oryx source
├── host_tools/windhawk/      ← Windows Windhawk mod (v1.2.0)
│   └── moonlander_language_sync.wh.cpp  ← F18/F19/F22 hotkeys, clipboard automation
├── docs/                     ← Handoff reports & setup guides
├── .github/workflows/        ← CI: fetch Oryx → patch → build → release
│   └── fetch-and-build-layout.yml
├── 3aMQz/                    ← Auto-synced patched layout snapshot (committed by workflow)
│   ├── keymap.c              ← Oryx-generated + patched MIDI layer
│   ├── config.h              ← MIDI_ADVANCED, low-latency settings
│   ── rules.mk              ← MIDI_ENABLE = yes
├── Dockerfile                ← Debian arm-none-eabi QMK build container
└── qmk_firmware/             ← ZSA QMK fork (submodule, fetched at build time)
```

## Features

### 1. MIDI Layer (Layer 2)

Two octaves of polyphonic MIDI input with split melody/bass and a transpose shifter. Uses **MIDI_ADVANCED** (not MIDI_BASIC) so note keycodes route through `process_midi()` which decodes by keycode value — required for the bass shifter to work correctly.

#### Note Map

**Melody (Row 2, natural/white keys):**

| Hand | Keys | Notes |
|---|---|---|
| Left | k20–k26 | `C3 D3 E3 F3 G3 A3 B3` |
| Right | k27–k2d | `C4 D4 E4 F4 G4 A4 B4` |

**Sharps/flats (Row 1, biased right so each accidental sits above the next natural):**

| Hand | Notes |
|---|---|
| Left (octave 3) | `C#3 D#3  F#3 G#3 A#3` |
| Right (octave 4) | `Db4 Eb4  Gb4 Ab4 Bb4` (enharmonic = `C#4 D#4 F#4 G#4 A#4`) |

**Bass (Rows 3–4, left hand only; F#2 omitted to fit 11 keys):**

| Row | Keys | Notes |
|---|---|---|
| Row 3 (BASS1–6) | k30–k35 | `C2 C#2 D2 D#2 E2 F2` |
| Row 4 (BASS7–11) | k40–k44 | `G2 G#2 A2 A#2 B2` |

#### Bass Shifter (Thumb Cluster)

Two purple-lit left thumb keys: **BASS_up** (k51) and **BASS_down** (k52). Each tap transposes all bass notes ±1 semitone (free transpose across octaves, clamped −24..+24). Melody keys are in a higher keycode range and are never affected.

**Implementation**: The firmware intercepts bass keys by **MIDI keycode range** (`MI_C2..MI_B2`), not by matrix position. On press, the shifter forwards a transposed note keycode to `process_midi()`, which emits the real MIDI note. Each held key snapshots its shifted note keycode so that a shift change mid-hold cannot strand a stuck note.

> **Note on pitch**: Under QMK MIDI, the keycode octave is **relative** to the global `midi_config.octave` (default puts `MI_C` at note 48 / C3). Keycode names describe note *relationships*; absolute pitch follows the global octave. The firmware sets `midi_config.octave = 1` at init so `MI_C2` sounds as C2 (not C5).

#### Build Requirements (injected automatically by `patch_keymap.py`)

- `MIDI_ENABLE = yes` in `rules.mk`
- `#define MIDI_ADVANCED` in `config.h`
- `DEBOUNCE = 1` and `USB_POLLING_INTERVAL_MS = 1` for low-latency MIDI

### 2. Language-Aware RGB

The left thumb indicator key lights **blue** (English) or **red** (Hebrew). State is synced from Windows over RAW HID using Oryx's `ORYX_STATUS_LED_CONTROL` command (`0x0A`):
- Param[0] = `0x00` → English
- Param[0] = `0x01` → Hebrew

The indicator only acts on the base layer (Layer 0); other layers use Oryx-configured per-layer colors. This prevents the language RGB from overriding MIDI layer bass key colors.

### 3. Tap-Dance Stabilization

`patch_keymap.py` normalizes tap-dance handlers to fix tapping-term races:
- `SINGLE_HOLD` → `SINGLE_TAP` fallback
- `DOUBLE_SINGLE_TAP` → `DOUBLE_TAP`
- Hold-preference on Space/Shift and F18 language dances

### 4. Windhawk Mod (Windows)

`host_tools/windhawk/moonlander_language_sync.wh.cpp` (v1.2.0):

| Hotkey | Function |
|---|---|
| **F18** | Language-switch (Win+Space / Alt+Shift / Ctrl+Shift) |
| **F22** | Wrong-language fixer — flips Hebrew ↔ English by physical QWERTY position |
| **F19** | Case cycler — lower → UPPER → Title → lower |

Also syncs Windows input language to keyboard RGB over RAW HID (polled ~120 ms).

**Collision note**: F21, F23 are already used as mod-tap triggers in the keymap; map only F22 and F19 in Oryx.

**Wrong-language fixer**: Uses the Microsoft kbdhebl3 (Hebrew Standard) layout. Hebrew has no case, so transcription defaults to lowercase. Use F19 to cycle case afterward.

**Case cycler**: After pasting, the text stays highlighted so you can press F19 again to keep cycling.

### 5. Keymap (Base Layer Snapshot)

A modified QWERTY layout with dual-function thumb keys (managed in Oryx, snapshot at `3aMQz/keymap.c`):

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

## Build Pipeline

Triggered manually via **Actions → Fetch and build layout** (`fetch-and-build-layout.yml`).

**Parameters**: Layout ID (`3aMQz`), geometry (`moonlander/reva`).

**Steps**:
1. Downloads Oryx source → `oryx_source/`
2. Copies `custom_qmk/custom_code.c` → `oryx_source/`
3. Runs `scripts/patch_keymap.py` on `oryx_source/` (11+ transformations)
4. Builds via Docker using ZSA's QMK fork
5. Publishes `.bin` as release artifact
6. Commits patched snapshot to `3aMQz/`

**What the patch script injects**:
- MIDI custom-keycode enum near top of `keymap.c`
- Layer 2 MIDI keycodes (preserving user-added keys like RGB toggles)
- `#define MIDI_ADVANCED` in `config.h`
- `MIDI_ENABLE = yes` in `rules.mk`
- Low-latency settings (`DEBOUNCE = 1`, `USB_POLLING_INTERVAL_MS = 1`)
- MIDI octave fix (`midi_config.octave = 1` in `keyboard_post_init_user`)
- Tap-dance stabilization patches
- Language RGB indicator hook

## Requirements

- **Hardware**: ZSA Moonlander keyboard
- **Firmware flashing**: [Wally](https://www.zsa.io/wally) or [ZSA Keymapp](https://www.zsa.io/flash)
- **GitHub account**: for Actions (CI builds)
- **Windhawk** (Windows-only, optional): https://windhawk.net/ — install `moonlander_language_sync.wh.cpp`
- **Docker** (for local builds; not needed for CI-only usage)

## Development Workflow

### Making Layout Changes

1. Edit your layout in Oryx (https://configure.zsa.io/)
2. Trigger **Actions → Fetch and build layout** on GitHub
3. Wait ~3-5 minutes for the build
4. `git pull` to get the updated `3aMQz/` folder
5. Flash the `.bin` from the release artifacts

### Adding Custom Firmware Code

1. Edit `custom_qmk/custom_code.c`
2. Commit and push
3. The next workflow run will copy your changes into the build

### Modifying the Patch Script

1. Edit `scripts/patch_keymap.py`
2. Test locally: `python3 scripts/patch_keymap.py 3aMQz`
3. Commit and push
4. The next workflow run will use your updated patch

### Local Testing

```bash
# Clone the ZSA QMK fork
git clone --depth 1 https://github.com/zsa/qmk_firmware.git qmk_firmware
cd qmk_firmware
git checkout firmware25
git submodule update --init --recursive

# Copy your layout
cp -r ../3aMQz keyboards/zsa/moonlander/reva/keymaps/

# Build
make zsa/moonlander/reva:3aMQz
```

## Design Decisions

### Why MIDI_ADVANCED instead of MIDI_BASIC?

Investigation of QMK source confirmed:
- **MIDI_BASIC** routes note keycodes through `process_music()`, which (a) requires MIDI mode toggled ON (`MI_ON`) and (b) derives the note from **matrix position**, ignoring the note keycode entirely. `register_code16()` never emits MIDI.
- **MIDI_ADVANCED** routes note keycodes through `process_midi()`, which decodes the note **by keycode value** (`midi_compute_note`) and tracks note-on/off. No mode toggle needed.

**Decision**: Use MIDI_ADVANCED (strict superset; future-proof). The bass shifter forwards a transposed note keycode to `process_midi()`, keeping the per-key snapshot so press/release use the same shifted keycode (no stuck notes).

### Why F19/F22 instead of F21/F23?

The base keymap already emits F18 (×2), F21 (`LT(14,KC_F21)`), and F23 (`LT(9,KC_F23)`). Global Windhawk hotkeys must use scancodes NOT used by the keymap, else normal key presses would trigger them. Free F-keys: F13–F17, F19, F20, F22, F24.

**Decision**: F19 (case cycler) and F22 (wrong-language fixer). F18 is shared intentionally (the keyboard's F18 language key is exactly what we want mirrored to the OS).

### Why preserve-by-default for Layer 2?

The original patch script overwrote the entire Layer 2 body, wiping any keys the user added in Oryx (e.g., RGB toggles, layer-toggle keys). The rewrite only overwrites the exact MIDI note positions and preserves everything else from the Oryx source.

## Troubleshooting

### MIDI notes sound one octave too high

The firmware sets `midi_config.octave = 1` at init. If notes are still wrong, check your DAW's MIDI channel mapping.

### MIDI latency is too high

The firmware uses `DEBOUNCE = 1` and `USB_POLLING_INTERVAL_MS = 1`. If latency persists:
- Disable RGB effects on the MIDI layer (use the RGB_TOG key you added)
- Reduce your DAW's audio buffer size (128 or 256 samples)
- Use ASIO drivers on Windows

### Windhawk mod not working

- Ensure Windhawk is installed and the mod is enabled
- Check that F18/F19/F22 are mapped in Oryx (not F21/F23)
- The mod polls language state every ~120ms; rapid switching may lag

### Build fails with "not enough USB endpoints"

The Moonlander with MIDI + RAW HID + NKRO can exceed the STM32F303's USB endpoint limit. The firmware already disables `MOUSEKEY_ENABLE` and `CONSOLE_ENABLE` to free endpoints. If it still fails, you may need to disable additional features.

## License

This project is provided as-is for personal use. QMK firmware is licensed under GPL-2.0.

## Acknowledgments

- ZSA Technology Labs for the Moonlander and Oryx
- QMK community for the firmware framework
- Microsoft for the kbdhebl3 Hebrew keyboard layout specification
