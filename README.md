Hey! This repo combines a ZSA Moonlander's online Oryx layout with custom QMK firmware. The Oryx web configurator is great but has gaps I fill here: a 12-note chromatic MIDI piano layer, Hebrew/English language-aware RGB, text automation via F-key placeholders, and CI that builds it all automatically.

Open https://configure.zsa.io/moonlander/layouts/3aMQz/latest/0 to see the base layout — most keys are peach-colored labels that mark function-key placeholders which get replaced with real behavior by the patch script after the firmware builds.

The rest of this README is AI-generated technical documentation that explains each feature in depth. Contact me at me@yiftah.com with questions.

# Custom QMK Firmware for ZSA Moonlander

Advanced MIDI keyboard, language-aware RGB, and Windows text automation — managed through Oryx with zero-merge-conflict CI/CD injection.

## Overview

This repository provides custom QMK firmware for the ZSA Moonlander keyboard, combining:

- **MIDI Layer**: Two-octave polyphonic MIDI input (12 bass notes + 14 melody notes + 10 sharps) with bass transpose shifter
- **Language-Aware RGB**: Hebrew/English indicator with Windows sync
- **Windhawk Mod**: Windows-side text automation (wrong-language fixer, case cycler)
- **CI/CD Pipeline**: Automated Oryx → patch → build → release workflow

The key innovation: Oryx (ZSA's online layout editor) has no native MIDI support. Instead of manually maintaining merge-conflict-prone `keymap.c` files, this project downloads fresh Oryx source in CI, runs `scripts/patch_keymap.py` to inject custom code, builds via Docker, and publishes `.bin` firmware. **No merge conflicts. Only custom code is tracked.**

## Project Structure

```
Working-Oryx-QMK-Sync/
├── custom_qmk/               ← Canonical custom firmware (custom_code.c)
│   └── custom_code.c         ← MIDI bass shifter, language RGB, tap-dance handlers
── scripts/                  ← Python patching engine
│   └── patch_keymap.py       ← 11+ deterministic transformations injected into Oryx source
── host_tools/windhawk/      ← Windows Windhawk mod (v1.2.0)
│   └── moonlander_language_sync.wh.cpp  ← F18/F19/F22 hotkeys, clipboard automation
├── .github/workflows/        ← CI: fetch Oryx → patch → build → release
│   └── fetch-and-build-layout.yml
├── 3aMQz/                    ← Auto-synced patched layout snapshot (committed by workflow)
│   ├── keymap.c              ← Oryx-generated + patched MIDI layer
│   ├── config.h              ← MIDI_ADVANCED, low-latency settings
│   └─ rules.mk              ← MIDI_ENABLE = yes
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

**Sharps/flats (Row 1, biased LEFT so each accidental sits directly above the natural it sharpens):**

| Hand | Notes |
|---|---|
| Left (octave 3) | `C#3 D#3  F#3 G#3 A#3` |
| Right (octave 4) | `Db4 Eb4  Gb4 Ab4 Bb4` (enharmonic = `C#4 D#4 F#4 G#4 A#4`) |

**Bass (Rows 3–4 + thumb cluster, left hand only; full chromatic C2–B2):**

| Row | Keys | Notes |
|---|---|---|
| Row 3 (BASS1–6) | k30–k35 | `C2 C#2 D2 D#2 E2 F2` |
| Row 4 (BASS7–11) | k40–k44 | `F#2 G2 G#2 A2 A#2` |
| Row 5 (BASS12) | k50 | `B2` (left thumb cluster, one semitone below BASS1 root) |

#### Bass Shifter (Thumb Cluster)

Three keys share the left thumb cluster on Layer 2: **BASS12** (k50, the 12th chromatic bass note B2), **BASS_up** (k51), and **BASS_down** (k52). The two shifter keys each tap to transpose all bass notes ±1 semitone (free transpose across octaves, clamped −24..+24). Melody keys are in a higher keycode range and are never affected.

**Implementation**: The firmware intercepts bass keys by **MIDI keycode range** (`MI_C2..MI_B2`), not by matrix position. On press, the shifter forwards a transposed note keycode to `process_midi()`, which emits the real MIDI note. Each held key snapshots its shifted note keycode so that a shift change mid-hold cannot strand a stuck note.

> **Note on pitch**: Under QMK MIDI, the keycode octave is **relative** to the global `midi_config.octave` (default puts `MI_C` at note 48 / C3). Keycode names describe note *relationships*; absolute pitch follows the global octave. The firmware sets `midi_config.octave = 1` at init so `MI_C2` sounds as C2 (not C5).

#### Build Requirements (injected automatically by `patch_keymap.py`)

- `MIDI_ENABLE = yes` in `rules.mk`
- `#define MIDI_ADVANCED` in `config.h`
- `DEBOUNCE_TYPE = sym_eager_pk`, `DEBOUNCE = 5`, and `USB_POLLING_INTERVAL_MS = 1` for low-latency MIDI
- `QMK_KEYS_PER_SCAN = 12` for instant polyphonic MIDI chords

### 2. Language-Aware RGB

The left thumb indicator key (k40) lights **blue** (English) or **red** (Hebrew). State is synced from Windows over RAW HID using Oryx's `ORYX_STATUS_LED_CONTROL` command (`0x0A`):
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

| Hotkey | Source | Function |
|---|---|---|
| **F18** | DANCE_0 (thumb language key) | Language-switch (Win+Space / Alt+Shift / Ctrl+Shift) |
| **F22** | k51 (Tap of RCtrl mod-tap) | Wrong-language fixer — flips Hebrew ↔ English by physical QWERTY position |
| **F19** | k52 (Tap of Shift+Ctrl mod-tap) | Case cycler — lower → UPPER → Title → lower |

Also syncs Windows input language to keyboard RGB over RAW HID (polled ~120 ms).

**Collision note**: F21, F23 are already used as mod-tap triggers in the keymap; map only F22 and F19 in Oryx.

**Wrong-language fixer**: Uses the Microsoft kbdhebl3 (Hebrew Standard) layout. Hebrew has no case, so transcription defaults to lowercase. Use F19 to cycle case afterward.

**Case cycler**: After pasting, the text stays highlighted so you can press F19 again to keep cycling.

### 5. Base Layer Keymap (Layer 0)

A modified QWERTY layout with dual-function thumb keys (managed in Oryx, snapshot at `3aMQz/keymap.c`). Function keys F18/F19/F22 are mapped in Oryx for Windhawk to intercept.

#### Row 0 (k00–k0d, 14 keys)

| Left half | Right half |
|---|---|
| `ESC` `1` `2` `3` `4` `5` `=` | `MEH_T(PageUp)` `6` `7` `8` `9` `0` `Home` |

- `MEH_T`: Hold activates MeH (Alt+Ctrl+Shift), tap sends the key.

#### Row 1 (k10–k1d, 14 keys)

| Left half | Right half |
|---|---|
| **DUAL_FUNC_0** `Q` `W` `E` `R` `T` `-` | `ALL_T(PgDn)` `Y` `U` `I` `O` `P` `End` |

- `ALL_T`: Hold activates ALL (Ctrl+Alt+Shift+Gui), tap sends the key.
- **DUAL_FUNC_0** (custom override): tap → `DELETE`, hold → `CTRL+DELETE`

#### Row 2 (k20–k2d, 14 keys)

| Left half | Right half |
|---|---|
| **DUAL_FUNC_1** `A` `S` `D` `F` `G` `` ` `` | `TG(1)` `H` `J` `K` `L` `;` `\` |

- `TG(1)`: Momentary toggle to Layer 1.
- **DUAL_FUNC_1** (custom override): tap → `BACKSPACE`, hold → `CTRL+BACKSPACE`

#### Row 3 (k30–k3b, 12 keys)

| Left half | Right half |
|---|---|
| `Shift` `Z` `X` `C` `V` `B` | `N` `M` `,` `.` `Up` `OSL(1)` |

- `OSL(1)`: One-shot Layer 1 (next keypress only).

#### Row 4 (k40–k4b, 12 keys)

| Left half | Right half |
|---|---|
| **DANCE_0** `Gui` `Alt` `[` `]` `MT(RAlt,Tab)` | **DUAL_FUNC_2** `'` `/` `←` `↓` `→` |

- `MT(RAlt, Tab)`: Hold Right Alt, tap Tab.
- **DANCE_0** (language key): single tap → `F18` (triggers Windows language switch + RGB sync), hold → `LeftCtrl`, double tap → `F18`, more taps → additional F18 presses
- **DUAL_FUNC_2** (custom override): tap → `ENTER`, hold → `SHIFT+ENTER`

#### Row 5 — Thumb Cluster (k50–k55, 6 keys)

| Left cluster | Right cluster |
|---|---|
| **DANCE_1** `MT(RCtrl,F22)` `MT(Shift+Ctrl,F19)` | `Delete` `Backspace` **DANCE_2** |

- `MT(RCtrl, F22)`: Hold = Right Ctrl, **tap = F22** (Windhawk wrong-language fixer)
- `MT(Shift+Ctrl, F19)`: Hold = Left Shift + Left Ctrl, **tap = F19** (Windhawk case cycler)
- **DANCE_1** (left space/caps): single tap → `SPACE`, hold → `LEFT_SHIFT` (hold-preferences when interrupted), double tap → `CAPS LOCK`, double-single-tap → `CAPS LOCK`
- **DANCE_2** (right space/numdot): single tap → `SPACE`, hold → `SPACE`, double tap → `KP_DOT + SPACE` (period-space shortcut)

#### Per-Key Tapping Term Overrides

Three keys have reduced tapping terms to favor tapping over holding during fast typing:

| Key | Override | Effect |
|---|---|---|
| `KC_I` | `TAPPING_TERM - 70` | Faster tap registration on the home-row letter I |
| `KC_DELETE` | `TAPPING_TERM - 120` | Faster tap on the Delete key in the thumb cluster |
| `KC_BSPC` | `TAPPING_TERM - 120` | Faster tap on the Backspace key in the thumb cluster |

### 6. Macros (ST_MACRO_0 through ST_MACRO_17)

Layer 1 and Layer 3 carry Unicode and editor macros. Highlights:

| Macros | Purpose |
|---|---|
| `ST_MACRO_0` | Unicode `U+20AC` (Euro €) + Enter |
| `ST_MACRO_1` | Cut (`Ctrl+X`) + type `B` |
| `ST_MACRO_5`–`ST_MACRO_11` | Various `Ctrl+X`/zoom/search shortcuts |
| `ST_MACRO_12`, `ST_MACRO_13` | Alt-code input for `U+002E` (period) |
| `ST_MACRO_14`–`ST_MACRO_17` | Unicode `U+002E` input variants |

Macros have deliberate inter-key `SS_DELAY(100)` intervals; these may feel slow if triggered frequently.

## Windhawk Mod Setup

This documents the Windows host-side companion used for text automation and language-aware RGB sync.

### 1. Oryx Configuration

The firmware exposes the Windhawk hotkeys as follows:
- **F18** (language switch): `DANCE_0` tap-dance on the left thumb key (k40) — single tap emits F18, hold emits `LeftCtrl`.
- **F22** (wrong-language fixer): tap of the `MT(RCtrl, F22)` mod-tap at k51.
- **F19** (case cycler): tap of the `MT(Shift+Ctrl, F19)` mod-tap at k52.

### 2. Build and Flash

1. Trigger **Actions → Fetch and build layout** on GitHub.
2. Flash the newly built `.bin` to the Moonlander via Wally or ZSA Keymapp.

### 3. Install the Windhawk Mod

1. Install [Windhawk](https://windhawk.net/) (Windows only).
2. Create a new mod and paste `host_tools/windhawk/moonlander_language_sync.wh.cpp`.
3. Build and enable the mod.
4. Default recommended settings:
   - `enableF18Hotkey = true`
   - `shortcutMode = 1` (Win+Space)
   - `enableF22Hotkey = true`
   - `enableF19Hotkey = true`
   - `pollIntervalMs = 120`
   - `onlyMoonlander = true`

### 4. Verify

1. Tap the left-thumb language tap-dance key (DANCE_0 / k40):
   - Windows should switch language (per your chosen shortcut mode).
   - The same key's RGB indicator should briefly reflect the new state.
2. Select Hebrew-typed text (or English-typed text) and press k51 (F22):
   - The text is replaced with characters flipped to the other alphabet based on physical key position.
3. Select any text and press k52 (F19):
   - Case cycles through `lower` → `UPPER` → `Title` → `lower`.
4. After a paste, the pasted text stays highlighted so F19 can be pressed again to keep cycling.

### 5. Protocol Reference

Windhawk sends an Oryx-native RAW HID command to sync Windows language state to keyboard RGB:

- Command: `ORYX_STATUS_LED_CONTROL` (`0x0A`)
- Payload: `param[0] = 0x00` (English), `0x01` (Hebrew)
- Transport: raw HID output report to any ZSA Moonlander device (filtered by manufacturer + product string)
- Firmware reads mirrored state from `rawhid_state.status_led_control` in `custom_qmk/custom_code.c`.

The indicator only responds on Layer 0; MIDI and other layers use Oryx-configured per-layer colors.

### 6. Troubleshooting

- If language switches but RGB does not update:
  - Set `debugLogging = true` in the mod and check Windhawk's log output.
  - Temporarily set `onlyMoonlander = false` to test broader HID matching.
- If F18 should not trigger the Windows language shortcut:
  - Set `enableF18Hotkey = false`. Keyboard-side language RGB sync still runs.
- If you prefer a different Windows shortcut:
  - `shortcutMode`: `1` = Win+Space (recommended), `2` = Alt+Shift, `3` = Ctrl+Shift, `0` = None.

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
- Low-latency settings (`DEBOUNCE_TYPE sym_eager_pk`, `DEBOUNCE 5`, `USB_POLLING_INTERVAL_MS 1`, `QMK_KEYS_PER_SCAN 12`)
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

The firmware uses `DEBOUNCE_TYPE sym_eager_pk`, `DEBOUNCE 5`, and `USB_POLLING_INTERVAL_MS 1`. If latency persists:
- Disable RGB effects on the MIDI layer (use the RGB_TOG key you added)
- Reduce your DAW's audio buffer size (128 or 256 samples)
- Use ASIO drivers on Windows

### Windhawk mod not working

- Ensure Windhawk is installed and the mod is enabled
- Check that F18/F19/F22 are mapped in Oryx as DANCE_0 / MT-mod-taps (not F21/F23)
- The mod polls language state every ~120ms; rapid switching may lag
- The mod targets `explorer.exe`; if another app has focus the window-level shortcut may not fire

### Build fails with "not enough USB endpoints"

The Moonlander with MIDI + RAW HID + NKRO can exceed the STM32F303's USB endpoint limit. The firmware already disables `MOUSEKEY_ENABLE` and `CONSOLE_ENABLE` to free endpoints. If it still fails, you may need to disable additional features.

## License

This project is provided as-is for personal use. QMK firmware is licensed under GPL-2.0.

## Acknowledgments

- ZSA Technology Labs for the Moonlander and Oryx
- QMK community for the firmware framework
- Microsoft for the kbdhebl3 Hebrew keyboard layout specification
