# AI Handoff Report (Complete Project History and Technical Context)

Generated: 2026-02-21  
Repo: `Working-Oryx-QMK-Sync`  
Scope: Full summary of ideas, implementations, bugs, regressions, and current state so another AI can continue without redoing failed paths.

## 1) Project Goal and Constraints

### Primary goal
- Keep a Moonlander layout managed in Oryx, while applying custom QMK behavior automatically in CI.
- Avoid merge conflicts by patching downloaded Oryx source during GitHub Actions runs.

### Secondary goals
- Improve tap/hold and tap-dance behavior consistency (especially fast typing cases).
- Keep workflow output as `.bin` and publish firmware as release asset.
- Stabilize language-switch key behavior and RGB language indication.

### Important operational constraints discovered
- Oryx-generated code structure changes across revisions.
- Tap-dance indices (`DANCE_n`) can renumber between Oryx exports.
- Oryx QMK module owns `raw_hid_receive()`, so custom raw HID command handlers cannot be added via an alternate callback name.
- Workflow run `head_sha` does not necessarily equal post-run auto-commit SHA (layout sync commit is created later in same run).

---

## 2) Repository Architecture (Current)

### Core files
- `scripts/patch_keymap.py`
  - Injection and patch orchestration against freshly downloaded Oryx `keymap.c`.
  - Current mode: Oryx-managed language key semantics, script-managed RGB hook and selected tap-dance compatibility passes.
- `custom_qmk/custom_code.c`
  - Custom firmware logic included into generated keymap by wrapper injection.
  - Contains language indicator colors and RGB override logic.
- `.github/workflows/fetch-and-build-layout.yml`
  - Fetches latest Oryx revision by GraphQL.
  - Applies patch script.
  - Builds firmware in Docker.
  - Uploads artifact and publishes release asset.
  - Commits synced layout folder back to repo.
- `3aMQz/*`
  - Auto-synced generated layout snapshot from latest successful run.

### Injection model
- Workflow downloads Oryx source zip.
- Copies `custom_qmk/custom_code.c` into the downloaded source folder.
- Runs `scripts/patch_keymap.py`.
- Patcher renames Oryx `process_record_user` -> `process_record_user_oryx`.
- Patcher appends wrapper `process_record_user` that calls `process_record_user_custom` first, then Oryx handler.

---

## 3) Chronological History of Work

## Phase A: Tap-dance/tap-hold stabilization work

### Problems reported
- Tap-dance keys appeared to require extra taps (double action triggering only on triple tap).
- Hold-vs-tap resolution felt too aggressive/short.
- Space/Shift dual-role was tap-biased during fast chords.

### Ideas implemented
- Added/adjusted tap-dance fallback behavior:
  - `DOUBLE_SINGLE_TAP` -> `DOUBLE_TAP` fallback where appropriate.
  - `SINGLE_HOLD` -> `SINGLE_TAP` fallback where explicit hold branch missing.
- Added space/shift hold preference when interrupted by another key.
- Added optional tap-term transforms and clamps (later disabled/commented per user direction to keep Oryx-managed terms).

### Key lesson
- Broad script-side timing overrides can conflict with user tuning done in Oryx; keeping tap term source of truth in Oryx reduced confusion.

---

## Phase B: Language key behavioral iterations

### Target behavior changed multiple times during debugging
- User requested variants including:
  - single tap language toggle,
  - double tap resync/reset,
  - hold as ctrl,
  - strong hold preference when chorded.

### Implemented attempts
- Added language tap-dance patching passes in script:
  - dynamic dance index detection,
  - hold preference on interrupt,
  - duplicate-trigger guards,
  - resync behavior hooks.
- Added RGB indicator hook and custom language state logic.

### Why these attempts became problematic
- Oryx source evolved from tap-dance-based language mapping to dual-function code paths (`DUAL_FUNC_2`), reducing reliability of tap-dance-specific patch assumptions.
- Multiple overlapping state systems (Oryx mapping + injected behavior + OS shortcut semantics) made behavior hard to reason about.

### Resulting strategy change
- A/B mode introduced: disable script-level language behavior patching entirely and leave language semantics to Oryx.
- This was committed (`586a879`) and became the long-term direction for key semantics.

---

## Phase C: Oryx source freshness and sync diagnostics

### Reported concern
- “Newest Oryx change not picked up by fetch/build.”

### What was checked
- Oryx GraphQL latest hash.
- Workflow run metadata.
- Repo synced snapshot serial/hash in generated files.
- Direct Oryx zip provided by user was inspected and compared.

### Findings
- Workflow was fetching latest revision correctly.
- Confusion came from behavior differences caused by Oryx-generated logic itself, not stale fetch.
- `head_sha` in run list is start SHA; post-run sync commit appears later and must be pulled.

---

## Phase D: Workflow output and release improvements

### User request
- Publish built `.bin` as release asset directly.

### Implementation
- Added release asset publishing step using `softprops/action-gh-release`.
- Kept artifact upload and added release tagging by geometry/layout/hash.

### Additional workflow bug fixed later
- FN24 verification logic initially asserted no `KC_F24` remained anywhere after patch.
- New Oryx revision used `KC_F24` in non-tap-dance code (`DUAL_FUNC_4`), causing false failure on run #53.
- Fixed in commit `0198224`: checks now only target tap-dance `register/unregister(KC_F24)` patterns.

---

## Phase E: Windhawk/host-sync architecture for language RGB

### Motivation
- Keyboard-only counter logic can drift from OS language state.
- User already runs Windhawk, so host integration is acceptable.

### Initial implementation (commit `4367c96`) included
- Windhawk mod file:
  - `host_tools/windhawk/moonlander_language_sync.wh.cpp`
  - Maps `F18` to language shortcut.
  - Sends OS language state over RAW HID.
- Firmware additions in `custom_qmk/custom_code.c` for host-fed language state.
- Setup docs in `docs/windhawk-language-sync.md`.

### Bug in initial implementation
- Host sent custom RAW HID command (`0xA0`) expecting a custom callback (`raw_hid_receive_oryx`).
- Oryx module owns `raw_hid_receive()` and ignores unknown command IDs.
- Result: language key shortcut could work, but RGB state never updated.

### Corrected implementation (commit `6fdd23d`)
- Reused Oryx-supported command channel: `ORYX_STATUS_LED_CONTROL` (`0x0A`) with payload `0/1`.
- Firmware now reads `rawhid_state.status_led_control` in `custom_language_rgb_indicator()`.
- Added retry backoff in Windhawk mod to avoid aggressive repeated device scans when send fails.

### Current caveat
- `status_led_control` is a bool in Oryx state; using `0/1` language state aligns with this.

---

## 4) Important Bugs, Root Causes, and Lessons Learned

### Bug: “Double tap action triggers only when triple tapped”
- Root cause: interrupted double taps entered `DOUBLE_SINGLE_TAP` path with no equivalent behavior.
- Fix: clone/normalize `DOUBLE_SINGLE_TAP` where safe.
- Lesson: tap-dance state branches must be normalized or explicitly handled.

### Bug: “Space/Shift outputs tap during fast chord typing”
- Root cause: interrupt path still resolving to tap in generated dance logic.
- Fix: hold preference patch in dance step assignment for relevant key.
- Lesson: interruption handling is as important as base tapping term.

### Bug: workflow run #53 failure on invariant check
- Root cause: invariant checked for any `KC_F24`, not just target tap-dance locations.
- Fix: narrow checks to `register/unregister(KC_F24)` in dance handlers.
- Lesson: invariants should match exact transformed pattern, not broad token existence.

### Bug: language RGB not syncing with Windhawk host state
- Root cause: unsupported custom raw HID command path.
- Fix: piggyback on Oryx-supported `ORYX_STATUS_LED_CONTROL` command.
- Lesson: when Oryx module owns a core callback, extend via supported protocol paths.

### Bug: temporary delay after flash before key appears to work
- Most likely contributors:
  - device reconnect sequencing after flashing,
  - host-side HID enumeration timing,
  - prior aggressive retry behavior in initial Windhawk implementation.
- Mitigation added:
  - retry backoff in Windhawk sender,
  - state resend scheduling.

---

## 5) Current Code State (As of This Report)

### `scripts/patch_keymap.py` current behavior
- Language key semantics patching: disabled (`enable_language_injection = False`).
- Language RGB hook patching: enabled (`enable_language_rgb_hook_injection = True`).
- Tap-term overrides: disabled/commented; Oryx is source of truth for tapping terms.
- FN24 replacement: active for tap-dance target only.
- Process record wrapper injection: idempotent.

### `custom_qmk/custom_code.c` current behavior
- Keeps local language state variable and guard helpers.
- RGB indicator chooses language state using:
  - `rawhid_state.status_led_control` when `RAW_ENABLE` is active.
  - fallback local variable otherwise.
- Still contains legacy `custom_language_toggle()` using `LALT(KC_LEFT_SHIFT)`; currently not wired by script-side language semantics (language key semantics are Oryx-managed).

### `.github/workflows/fetch-and-build-layout.yml` current behavior
- Fetches latest Oryx revision via GraphQL.
- Validates FN24 patterns pre/post patch using dance-specific regex counts.
- Builds and publishes firmware release asset.
- Commits updated layout snapshot folder back to repo.

### Generated snapshot
- Latest visible auto-sync commit after rebase: `1ee8112` (layout edited, hash `LvDJr6`), changed `3aMQz/custom_code.c`.

---

## 6) Commit Map (Key Milestones)

### Most relevant recent commits
- `6fdd23d` Fix Windhawk language sync transport and RGB state wiring
- `0198224` Fix FN24 invariant check for non-tap-dance KC_F24 uses
- `4367c96` Add Windhawk language sync bridge and RAW HID firmware hook
- `586a879` Temporarily disable language injection for A/B test
- `4be52be` Publish built firmware as GitHub release asset
- `73f929f` Detect language tap-dance index dynamically
- `bf9b461` Set language tap-dance tapping term to 2000ms (historical, now effectively bypassed by current mode)
- `de98bc2` Refactor patcher passes and make wrapper injection idempotent
- `c181eaf` Use Oryx tap terms and enforce language key behavior
- `61be29c` Fix tap-dance case rewriting and language toggle duplication

### Frequent auto-sync commits
- Many `Keyboard layout edited. [oryx:<hash> geom:moonlander/reva]` commits update `3aMQz/*`.

---

## 7) Dead Ends and Mistakes to Avoid Repeating

### Do not assume tap-dance index numbers are stable
- Always detect dynamically from content patterns.

### Do not enforce global “no token remains” invariants
- Use context-aware checks (e.g., specific function calls in target handler).

### Do not implement custom raw HID receive symbol expecting Oryx to call it
- Oryx module handles `raw_hid_receive()`; use supported Oryx command channels instead.

### Do not mix too many overlapping language behaviors
- Keep key semantics in Oryx.
- Keep RGB sync in host bridge + indicator hook.

### Do not interpret run `head_sha` as final synced layout commit
- Pull after workflow and inspect new commit(s) on `main`.

---

## 8) Current Open Questions / Residual Risks

### Not yet fully re-validated by user after latest fixes
- Need confirmation that latest flashed firmware + latest Windhawk mod now updates RGB correctly.

### Potential protocol coupling risk
- Using `rawhid_state.status_led_control` as language state piggybacks on an Oryx-defined field.
- If Oryx internals change this behavior in future firmware versions, host sync could break.

### Host dependency
- Windhawk mod must run on each host PC for OS-synced RGB behavior.
- Without mod, keyboard falls back to firmware state and may not reflect true OS language.

---

## 9) Practical Runbook for Next AI

### Step 1: Verify repository cleanliness and remote sync
- Ignore existing local temporary folders unless user asks cleanup:
  - `__tmp_*`, `_tmp_*` (untracked local diagnostics artifacts).

### Step 2: If user reports firmware behavior mismatch
- Check latest workflow run status and failing step.
- Confirm if post-run auto-commit exists and is pulled locally.
- Inspect `3aMQz/keymap.c` and `3aMQz/custom_code.c` from latest sync.

### Step 3: If language RGB still fails
- Confirm flashed firmware includes `custom_language_rgb_indicator()` with `rawhid_state.status_led_control` read.
- Confirm Windhawk mod version includes Oryx command `0x0A` path and retry backoff.
- Ask user to enable `debugLogging` in Windhawk mod and share logs.

### Step 4: If CI fails on FN24 checks again
- Re-check pattern assumptions against latest Oryx source structure before broad edits.

---

## 10) User-Facing State Summary (for continuity)

- User’s key concern evolved from tap-dance timing bugs to language key reliability and OS-synced RGB.
- Current architecture intentionally separates responsibilities:
  - Oryx defines language key tap/hold semantics.
  - Injection script avoids language semantic overrides.
  - Windhawk host bridge reports OS language state.
  - Firmware indicator hook renders color based on host-fed state.
- Latest major fixes were pushed; next required action is user validation after flashing the newest build and updating Windhawk mod code.

---

## 11) Files Added/Modified for Handoff Era

- `docs/windhawk-language-sync.md`
- `host_tools/windhawk/moonlander_language_sync.wh.cpp`
- `custom_qmk/custom_code.c`
- `scripts/patch_keymap.py`
- `.github/workflows/fetch-and-build-layout.yml`
- `README.md`

---

## 12) Final Notes for Next AI

- Treat `custom_qmk/custom_code.c` as source of truth for custom firmware behavior; `3aMQz/custom_code.c` is generated snapshot.
- Preserve user preference: keep Oryx authoritative for language key semantics unless explicitly asked otherwise.
- If changing host protocol again, validate against Oryx module source (`zsa/qmk_modules/oryx/oryx.c`) before implementation.
- Maintain non-destructive git hygiene: never reset or clean user temp dirs without explicit request.
