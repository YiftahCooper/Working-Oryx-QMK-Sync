import os
import re
import sys
from typing import Callable

PATCH_MARKER = "ORYX_FN24_NUMDOT_SPACE_PATCH"
MIDI_ENUM_MARKER = "ORYX_MIDI_KEYCODE_ENUM_PATCH"
MIDI_LAYER_MARKER = "ORYX_MIDI_LAYER2_PATCH"
# The MIDI keys live on layer 2 (confirmed against the live Oryx export).
MIDI_LAYER_INDEX = 2
LANGUAGE_TOGGLE_MARKER = "ORYX_LANG_TOGGLE_PATCH"
LANGUAGE_RESYNC_MARKER = "ORYX_LANG_RESYNC_PATCH"
LANGUAGE_RGB_MARKER = "ORYX_LANG_RGB_PATCH"
LANGUAGE_HOLD_PREF_MARKER = "ORYX_LANG_HOLD_PREF_PATCH"
LANGUAGE_ON_DANCE_NOOP_MARKER = "ORYX_LANG_ON_DANCE_NOOP_PATCH"
LANGUAGE_TAP_TERM_MARKER = "ORYX_LANG_TAP_TERM_PATCH"
LANGUAGE_F18_HOLD_MARKER = "ORYX_LANG_F18_HOLD_PREF_PATCH"
LANGUAGE_F18_DOUBLETAP_MARKER = "ORYX_LANG_F18_DOUBLETAP_PATCH"
TAPHOLD_COMPAT_MARKER = "ORYX_TAPHOLD_FALLBACK_PATCH"
DOUBLETAP_COMPAT_MARKER = "ORYX_DOUBLETAP_FALLBACK_PATCH"
SPACESHIFT_HOLD_PREF_MARKER = "ORYX_SPACESHIFT_HOLD_PREF_PATCH"
SPACE_DOT_TERM_MARKER = "ORYX_SPACE_DOT_TERM_PATCH"
LANGUAGE_SWITCH_TAPPING_TERM_MS = 2000
SPACE_DOT_TERM_SCALE_NUM = 6
SPACE_DOT_TERM_SCALE_DEN = 5
# Keep per-key tap windows from collapsing into impractically short ranges.
MAX_TAPPING_TERM_SUBTRACT = 40
RELAX_AGGRESSIVE_TAPPING_TERMS = True


def _find_matching_brace(content: str, open_idx: int) -> int:
    """
    Return index of the matching '}' for the '{' at open_idx.
    Skips braces inside strings and comments to keep block matching stable.
    """
    if open_idx < 0 or open_idx >= len(content) or content[open_idx] != "{":
        return -1

    depth = 0
    i = open_idx
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escape = False

    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if in_char:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_char = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
            if depth < 0:
                return -1
        i += 1

    return -1


def _find_matching_paren(content: str, open_idx: int) -> int:
    """
    Return index of the matching ')' for the '(' at open_idx.
    Skips parens inside strings, char literals, and comments.
    """
    if open_idx < 0 or open_idx >= len(content) or content[open_idx] != "(":
        return -1

    depth = 0
    i = open_idx
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escape = False

    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if in_char:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_char = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
            if depth < 0:
                return -1
        i += 1

    return -1


def _replace_function_body(content: str, function_name: str, body: str) -> str:
    function_pat = re.compile(rf"\b{re.escape(function_name)}\s*\([^)]*\)\s*\{{")
    m = function_pat.search(content)
    if not m:
        return content

    open_brace_idx = content.find("{", m.start())
    if open_brace_idx == -1:
        return content

    close_brace_idx = _find_matching_brace(content, open_brace_idx)
    if close_brace_idx == -1:
        return content

    return content[: open_brace_idx + 1] + body + content[close_brace_idx:]


def _get_function_body(content: str, function_name: str) -> tuple[str, bool]:
    function_pat = re.compile(rf"\b{re.escape(function_name)}\s*\([^)]*\)\s*\{{")
    m = function_pat.search(content)
    if not m:
        return "", False

    open_brace_idx = content.find("{", m.start())
    if open_brace_idx == -1:
        return "", False

    close_brace_idx = _find_matching_brace(content, open_brace_idx)
    if close_brace_idx == -1:
        return "", False

    return content[open_brace_idx + 1 : close_brace_idx], True


def _discover_dance_indices(content: str) -> list[int]:
    """
    Discover tap-dance indices present in the generated keymap so downstream
    patch passes do not repeatedly scan a hardcoded numeric range.
    """
    indices = {
        int(m.group(1))
        for m in re.finditer(r"\bdance_(\d+)_(?:finished|reset)\s*\(", content)
    }
    if indices:
        return sorted(indices)
    # Fallback for unexpected source layouts.
    return list(range(0, 24))


def _replace_case_block(body: str, case_name: str, replacement_builder: Callable[[str], str]) -> tuple[str, bool]:
    """
    Replace one switch-case block while preserving indentation.
    """
    case_pat = re.compile(
        rf"(?P<indent>^[ \t]*)case\s+{re.escape(case_name)}\s*:\s*.*?(?=^[ \t]*case\s+|^[ \t]*default\s*:|}})",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = case_pat.search(body)
    if not match:
        return body, False

    indent = match.group("indent")
    replacement = replacement_builder(indent)
    body_new = case_pat.sub(replacement + "\n", body, count=1)
    return body_new, True


def _replace_fn24_in_space_tap_dance(content: str, dance_indices: list[int]) -> tuple[str, bool]:
    """
    Replace FN24 in the generated right-thumb tap dance with:
      DOUBLE_TAP and DOUBLE_SINGLE_TAP => num-dot then space.
    Target only dance_<n>_finished/reset function bodies.
    """
    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        reset_name = f"dance_{dance_idx}_reset"

        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        if "KC_F24" not in finished_body and PATCH_MARKER not in finished_body:
            continue

        finished_body_new = finished_body
        finished_body_new, replaced_double_tap = _replace_case_block(
            finished_body_new,
            "DOUBLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_TAP: tap_code16(KC_KP_DOT); tap_code16(KC_SPACE); "
                f"break; /* {PATCH_MARKER} */"
            ),
        )
        finished_body_new, replaced_double_single = _replace_case_block(
            finished_body_new,
            "DOUBLE_SINGLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_SINGLE_TAP: tap_code16(KC_KP_DOT); tap_code16(KC_SPACE); "
                f"break; /* {PATCH_MARKER} */"
            ),
        )

        if not replaced_double_tap and not replaced_double_single:
            continue

        content = _replace_function_body(content, finished_name, finished_body_new)

        reset_body, has_reset = _get_function_body(content, reset_name)
        if has_reset:
            reset_body_new = reset_body
            reset_body_new, _ = _replace_case_block(
                reset_body_new,
                "DOUBLE_TAP",
                lambda indent: f"{indent}case DOUBLE_TAP: break; /* {PATCH_MARKER} */",
            )
            reset_body_new, _ = _replace_case_block(
                reset_body_new,
                "DOUBLE_SINGLE_TAP",
                lambda indent: f"{indent}case DOUBLE_SINGLE_TAP: break; /* {PATCH_MARKER} */",
            )
            content = _replace_function_body(content, reset_name, reset_body_new)

        return content, True

    return content, False


def _inject_custom_language_prototypes(content: str) -> tuple[str, bool]:
    if "void custom_language_toggle(void);" in content:
        return content, True

    if "void custom_language_toggled(void);" in content:
        content = content.replace(
            "void custom_language_toggled(void);\n",
            "void custom_language_toggled(void);\n"
            "void custom_language_toggle(void);\n",
            1,
        )
        return content, True

    prototype_block = (
        "\n// --- Custom language hooks (injected) ---\n"
        "void custom_language_toggled(void);\n"
        "void custom_language_toggle(void);\n"
        "void custom_language_resync(void);\n"
        "void custom_language_rgb_indicator(void);\n"
        "// ----------------------------------------\n"
    )

    include_matches = list(re.finditer(r"^\s*#include[^\n]*\n", content, flags=re.MULTILINE))
    if include_matches:
        insert_idx = include_matches[-1].end()
    else:
        insert_idx = 0

    return content[:insert_idx] + prototype_block + content[insert_idx:], True


def _patch_language_switch_tap_dance(content: str, dance_indices: list[int]) -> tuple[str, bool, bool]:
    """
    Enforce language key semantics:
      - SINGLE_TAP: language toggle
      - DOUBLE_TAP: language resync
      - SINGLE_HOLD: Left Ctrl
    """
    any_toggle_patch = False
    any_resync_patch = False

    language_dance_idx = _find_language_switch_dance_index(content, dance_indices)
    if language_dance_idx is None:
        return content, any_toggle_patch, any_resync_patch

    on_name = f"on_dance_{language_dance_idx}"
    finished_name = f"dance_{language_dance_idx}_finished"
    reset_name = f"dance_{language_dance_idx}_reset"

    on_body, has_on = _get_function_body(content, on_name)
    if has_on and LANGUAGE_ON_DANCE_NOOP_MARKER not in on_body:
        on_body_new = (
            "\n"
            "    // Disable generated multi-tap side effects on language key.\n"
            "    (void)state;\n"
            f"    (void)user_data; /* {LANGUAGE_ON_DANCE_NOOP_MARKER} */\n"
        )
        content = _replace_function_body(content, on_name, on_body_new)

    finished_body, has_finished = _get_function_body(content, finished_name)
    if has_finished:
        finished_body_new = finished_body

        # Prefer hold (Ctrl) when the language key is interrupted by another key.
        # This makes fast chords resolve to hold instead of accidental tap-toggles.
        if LANGUAGE_HOLD_PREF_MARKER not in finished_body_new:
            step_assign_pat = re.compile(
                rf"dance_state\s*\[\s*{language_dance_idx}\s*\]\.step\s*=\s*dance_step\s*\(\s*state\s*\)\s*;"
            )
            step_assign_replacement = (
                "if (state->count == 1 && state->interrupted) {\n"
                f"        dance_state[{language_dance_idx}].step = SINGLE_HOLD; /* {LANGUAGE_HOLD_PREF_MARKER} */\n"
                "    } else {\n"
                f"        dance_state[{language_dance_idx}].step = dance_step(state);\n"
                "    }"
            )
            finished_body_new, _ = step_assign_pat.subn(step_assign_replacement, finished_body_new, count=1)

        finished_body_new, single_tap_patched = _replace_case_block(
            finished_body_new,
            "SINGLE_TAP",
            lambda indent: (
                f"{indent}case SINGLE_TAP: custom_language_toggle(); "
                f"break; /* {LANGUAGE_TOGGLE_MARKER} */"
            ),
        )
        if single_tap_patched:
            any_toggle_patch = True

        finished_body_new, _ = _replace_case_block(
            finished_body_new,
            "SINGLE_HOLD",
            lambda indent: f"{indent}case SINGLE_HOLD: register_code16(KC_LEFT_CTRL); break;",
        )

        finished_body_new, double_tap_patched = _replace_case_block(
            finished_body_new,
            "DOUBLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_TAP: custom_language_resync(); "
                f"break; /* {LANGUAGE_RESYNC_MARKER} */"
            ),
        )
        finished_body_new, double_single_patched = _replace_case_block(
            finished_body_new,
            "DOUBLE_SINGLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_SINGLE_TAP: custom_language_resync(); "
                f"break; /* {LANGUAGE_RESYNC_MARKER} */"
            ),
        )
        finished_body_new, double_hold_patched = _replace_case_block(
            finished_body_new,
            "DOUBLE_HOLD",
            lambda indent: (
                f"{indent}case DOUBLE_HOLD: custom_language_resync(); "
                f"break; /* {LANGUAGE_RESYNC_MARKER} */"
            ),
        )
        if double_tap_patched or double_single_patched or double_hold_patched:
            any_resync_patch = True

        content = _replace_function_body(content, finished_name, finished_body_new)

    reset_body, has_reset = _get_function_body(content, reset_name)
    if has_reset:
        reset_body_new = reset_body

        reset_body_new, _ = _replace_case_block(
            reset_body_new,
            "SINGLE_TAP",
            lambda indent: f"{indent}case SINGLE_TAP: break;",
        )
        reset_body_new, _ = _replace_case_block(
            reset_body_new,
            "SINGLE_HOLD",
            lambda indent: f"{indent}case SINGLE_HOLD: unregister_code16(KC_LEFT_CTRL); break;",
        )
        reset_body_new, _ = _replace_case_block(
            reset_body_new,
            "DOUBLE_TAP",
            lambda indent: f"{indent}case DOUBLE_TAP: break; /* {LANGUAGE_RESYNC_MARKER} */",
        )
        reset_body_new, _ = _replace_case_block(
            reset_body_new,
            "DOUBLE_SINGLE_TAP",
            lambda indent: f"{indent}case DOUBLE_SINGLE_TAP: break; /* {LANGUAGE_RESYNC_MARKER} */",
        )
        reset_body_new, _ = _replace_case_block(
            reset_body_new,
            "DOUBLE_HOLD",
            lambda indent: f"{indent}case DOUBLE_HOLD: break; /* {LANGUAGE_RESYNC_MARKER} */",
        )
        content = _replace_function_body(content, reset_name, reset_body_new)

    return content, any_toggle_patch, any_resync_patch


def _patch_rgb_indicator_hook(content: str) -> tuple[str, bool]:
    body, has_fn = _get_function_body(content, "rgb_matrix_indicators_user")
    if not has_fn:
        return content, False

    if "custom_language_rgb_indicator();" in body:
        return content, True

    body_new, return_n = re.subn(
        r"\breturn\s+true\s*;",
        f"custom_language_rgb_indicator(); /* {LANGUAGE_RGB_MARKER} */\n  return true;",
        body,
        count=1,
    )
    if return_n == 0:
        body_new = body + f"\n  custom_language_rgb_indicator(); /* {LANGUAGE_RGB_MARKER} */\n"

    return _replace_function_body(content, "rgb_matrix_indicators_user", body_new), True


def _clone_single_tap_to_single_hold(body: str) -> tuple[str, bool]:
    if "case SINGLE_HOLD:" in body or TAPHOLD_COMPAT_MARKER in body:
        return body, False

    single_tap_case = re.search(
        r"(?P<indent>[ \t]*)case\s+SINGLE_TAP\s*:\s*(?P<action>.*?)\s*break\s*;",
        body,
        flags=re.DOTALL,
    )
    if not single_tap_case:
        return body, False

    indent = single_tap_case.group("indent")
    action = single_tap_case.group("action").strip()
    if not action:
        return body, False

    injected_case = (
        f"{single_tap_case.group(0)}\n"
        f"{indent}case SINGLE_HOLD: {action} break; /* {TAPHOLD_COMPAT_MARKER} */"
    )
    return body[: single_tap_case.start()] + injected_case + body[single_tap_case.end() :], True


def _normalize_tap_dance_hold_resolution(content: str, dance_indices: list[int]) -> tuple[str, int]:
    """
    For tap-dance keys that have SINGLE_TAP but no SINGLE_HOLD branch, mirror the
    old keymap behavior by treating SINGLE_HOLD as SINGLE_TAP.
    """
    patched_finished = 0

    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        finished_body_new, finished_changed = _clone_single_tap_to_single_hold(finished_body)
        if not finished_changed:
            continue

        content = _replace_function_body(content, finished_name, finished_body_new)
        patched_finished += 1

        reset_name = f"dance_{dance_idx}_reset"
        reset_body, has_reset = _get_function_body(content, reset_name)
        if not has_reset:
            continue

        reset_body_new, reset_changed = _clone_single_tap_to_single_hold(reset_body)
        if reset_changed:
            content = _replace_function_body(content, reset_name, reset_body_new)

    return content, patched_finished


def _prefer_hold_for_space_shift_dance(content: str, dance_indices: list[int]) -> tuple[str, bool]:
    """
    For the dance that is SPACE on tap and SHIFT on hold, prefer hold when
    the key is interrupted by another key (fast chord typing).
    """
    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        if SPACESHIFT_HOLD_PREF_MARKER in finished_body:
            return content, True

        if "case SINGLE_TAP: register_code16(KC_SPACE);" not in finished_body:
            continue
        if "case SINGLE_HOLD: register_code16(KC_LEFT_SHIFT);" not in finished_body:
            continue

        step_assign_pat = re.compile(
            rf"dance_state\s*\[\s*{dance_idx}\s*\]\.step\s*=\s*dance_step\s*\(\s*state\s*\)\s*;"
        )
        replacement = (
            "if (state->count == 1 && state->interrupted) {\n"
            f"        dance_state[{dance_idx}].step = SINGLE_HOLD; /* {SPACESHIFT_HOLD_PREF_MARKER} */\n"
            "    } else {\n"
            f"        dance_state[{dance_idx}].step = dance_step(state);\n"
            "    }"
        )
        finished_body_new, replaced = step_assign_pat.subn(replacement, finished_body, count=1)
        if replaced == 0:
            return content, False

        content = _replace_function_body(content, finished_name, finished_body_new)
        return content, True

    return content, False


def _increase_space_dot_tapping_term(content: str, dance_indices: list[int]) -> tuple[str, bool]:
    """
    Increase the dot+space dance tapping term by ~20%.
    Targets the same dance that was patched from KC_F24 to KP_DOT+SPACE.
    """
    target_dance_idx = None
    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if has_finished and PATCH_MARKER in finished_body:
            target_dance_idx = dance_idx
            break

    if target_dance_idx is None:
        return content, False

    tapping_body, has_tapping = _get_function_body(content, "get_tapping_term")
    if not has_tapping:
        return content, False

    if SPACE_DOT_TERM_MARKER in tapping_body:
        return content, True

    dance_case_pat = re.compile(
        rf"case\s+TD\s*\(\s*DANCE_{target_dance_idx}\s*\)\s*:\s*return\s+(?P<expr>[^;]+)\s*;"
    )
    case_match = dance_case_pat.search(tapping_body)
    if case_match:
        base_expr = case_match.group("expr").strip()
        replacement = (
            f"case TD(DANCE_{target_dance_idx}): "
            f"return (uint16_t)((({base_expr}) * {SPACE_DOT_TERM_SCALE_NUM}) / {SPACE_DOT_TERM_SCALE_DEN}); "
            f"/* {SPACE_DOT_TERM_MARKER} */"
        )
        tapping_body_new = dance_case_pat.sub(replacement, tapping_body, count=1)
        return _replace_function_body(content, "get_tapping_term", tapping_body_new), True

    default_pat = re.compile(r"^(?P<indent>\s*)default\s*:", flags=re.MULTILINE)

    def _insert_before_default(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}case TD(DANCE_{target_dance_idx}): "
            f"return (uint16_t)(((TAPPING_TERM) * {SPACE_DOT_TERM_SCALE_NUM}) / {SPACE_DOT_TERM_SCALE_DEN}); "
            f"/* {SPACE_DOT_TERM_MARKER} */\n"
            f"{indent}default:"
        )

    tapping_body_new, inserted = default_pat.subn(_insert_before_default, tapping_body, count=1)
    if inserted == 0:
        return content, False

    return _replace_function_body(content, "get_tapping_term", tapping_body_new), True


def _find_language_switch_dance_index(content: str, dance_indices: list[int]) -> int | None:
    """
    Resolve the language-switch tap dance index from generated Oryx code.
    Oryx can renumber dance slots across revisions.
    """
    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        if "LALT(KC_LEFT_SHIFT)" in finished_body and "KC_F23" in finished_body:
            return dance_idx

    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if has_finished and "LALT(KC_LEFT_SHIFT)" in finished_body:
            return dance_idx

    return None


def _set_language_switch_tapping_term(content: str, dance_indices: list[int]) -> tuple[str, bool]:
    """
    Set a very long tapping term for the language switch key so tap wins unless
    the key is intentionally held for around two seconds.
    """
    tapping_body, has_tapping = _get_function_body(content, "get_tapping_term")
    if not has_tapping:
        return content, False

    language_dance_idx = _find_language_switch_dance_index(content, dance_indices)
    if language_dance_idx is None:
        return content, False

    cleanup_pat = re.compile(
        rf"^\s*case\s+TD\s*\(\s*DANCE_\d+\s*\)\s*:\s*return\s+[^;]+\s*;\s*/\*\s*{LANGUAGE_TAP_TERM_MARKER}\s*\*/\s*$",
        flags=re.MULTILINE,
    )
    tapping_body = cleanup_pat.sub("", tapping_body)

    dance_case_pat = re.compile(
        rf"case\s+TD\s*\(\s*DANCE_{language_dance_idx}\s*\)\s*:\s*return\s+[^;]+\s*;"
    )
    replacement = (
        f"case TD(DANCE_{language_dance_idx}): "
        f"return (uint16_t){LANGUAGE_SWITCH_TAPPING_TERM_MS}; "
        f"/* {LANGUAGE_TAP_TERM_MARKER} */"
    )
    tapping_body_new, replaced = dance_case_pat.subn(replacement, tapping_body, count=1)
    if replaced > 0:
        return _replace_function_body(content, "get_tapping_term", tapping_body_new), True

    default_pat = re.compile(r"^(?P<indent>\s*)default\s*:", flags=re.MULTILINE)

    def _insert_before_default(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}case TD(DANCE_{language_dance_idx}): "
            f"return (uint16_t){LANGUAGE_SWITCH_TAPPING_TERM_MS}; "
            f"/* {LANGUAGE_TAP_TERM_MARKER} */\n"
            f"{indent}default:"
        )

    tapping_body_new, inserted = default_pat.subn(_insert_before_default, tapping_body, count=1)
    if inserted == 0:
        return content, False

    return _replace_function_body(content, "get_tapping_term", tapping_body_new), True


def _clone_double_tap_to_double_single(body: str) -> tuple[str, bool]:
    if "case DOUBLE_TAP:" not in body:
        return body, False

    # Preserve keys that intentionally differentiate double tap from double hold.
    if "case DOUBLE_HOLD:" in body:
        return body, False

    # Preserve dances with custom double-tap handling patched elsewhere.
    if PATCH_MARKER in body:
        return body, False

    double_single_pat = re.compile(
        r"(?P<indent>^[ \t]*)case\s+DOUBLE_SINGLE_TAP\s*:\s*.*?(?=^[ \t]*case\s+|^[ \t]*default\s*:|})",
        flags=re.MULTILINE | re.DOTALL,
    )

    # Repair previously malformed marker rewrites before deciding idempotency.
    malformed_existing = re.search(
        rf"case\s+DOUBLE_SINGLE_TAP\s*:.*?/\*\s*{re.escape(DOUBLETAP_COMPAT_MARKER)}\s*\*/\S",
        body,
        flags=re.DOTALL,
    )

    if DOUBLETAP_COMPAT_MARKER in body and not malformed_existing:
        return body, False

    double_tap_case = re.search(
        r"(?P<indent>^[ \t]*)case\s+DOUBLE_TAP\s*:\s*(?P<action>.*?)\s*break\s*;\s*(?=^[ \t]*case\s+|^[ \t]*default\s*:|})",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not double_tap_case:
        return body, False

    indent = double_tap_case.group("indent")
    action = double_tap_case.group("action").strip()
    if not action:
        return body, False

    replacement_case = (
        f"{indent}case DOUBLE_SINGLE_TAP: {action} break; "
        f"/* {DOUBLETAP_COMPAT_MARKER} */"
    )

    if "case DOUBLE_SINGLE_TAP:" in body:
        body_new, replaced = double_single_pat.subn(replacement_case + "\n", body, count=1)
        return body_new, replaced > 0

    insert_idx = double_tap_case.end()
    body_new = body[:insert_idx] + f"\n{replacement_case}" + body[insert_idx:]
    return body_new, True


def _normalize_tap_dance_double_tap_resolution(content: str, dance_indices: list[int]) -> tuple[str, int]:
    """
    Treat interrupted doubles (DOUBLE_SINGLE_TAP) like DOUBLE_TAP for dances
    that do not define DOUBLE_HOLD behavior.
    """
    patched_finished = 0

    for dance_idx in dance_indices:
        finished_name = f"dance_{dance_idx}_finished"
        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        finished_body_new, finished_changed = _clone_double_tap_to_double_single(finished_body)
        if not finished_changed:
            continue

        content = _replace_function_body(content, finished_name, finished_body_new)
        patched_finished += 1

        reset_name = f"dance_{dance_idx}_reset"
        reset_body, has_reset = _get_function_body(content, reset_name)
        if not has_reset:
            continue

        reset_body_new, reset_changed = _clone_double_tap_to_double_single(reset_body)
        if reset_changed:
            content = _replace_function_body(content, reset_name, reset_body_new)

    return content, patched_finished


def _relax_aggressive_tapping_terms(content: str) -> tuple[str, int]:
    """
    Oryx can emit very small per-key tapping terms (e.g. TAPPING_TERM-120/-134),
    which makes single taps behave like missed/hold events for normal typing speed.
    Clamp per-key reductions in get_tapping_term to a safer ceiling.
    """
    body, has_fn = _get_function_body(content, "get_tapping_term")
    if not has_fn:
        return content, 0

    changes = 0

    def _clamp(match: re.Match[str]) -> str:
        nonlocal changes
        original_subtract = int(match.group(1))
        clamped_subtract = min(original_subtract, MAX_TAPPING_TERM_SUBTRACT)
        if clamped_subtract != original_subtract:
            changes += 1
            return f"return TAPPING_TERM - {clamped_subtract};"
        return match.group(0)

    body_new = re.sub(r"return\s+TAPPING_TERM\s*-\s*(\d+)\s*;", _clamp, body)
    if changes == 0:
        return content, 0

    return _replace_function_body(content, "get_tapping_term", body_new), changes


def _patch_f18_language_dance(content: str) -> tuple[str, bool]:
    """
    Fix the F18-based language tap-dance (Bug 3) WITHOUT switching to the
    LALT(KC_LEFT_SHIFT) firmware mechanism (language switching is owned by the
    Windhawk host bridge via F18).

    The Oryx-generated language dance maps:
        SINGLE_TAP        -> KC_F18   (Windhawk: switch language)
        SINGLE_HOLD       -> KC_LEFT_CTRL
        DOUBLE_TAP        -> KC_F22   (wrong-language fixer -- NOT what the user wants)
        DOUBLE_SINGLE_TAP -> KC_F22

    Two problems are fixed here:
      1) Hold did not feel like a normal mod-tap. With HOLD_ON_OTHER_KEY_PRESS,
         pressing another key while holding interrupts the dance, and the stock
         dance_step() returns SINGLE_TAP -> it fired F18 instead of Ctrl. We force
         an interrupted single press to resolve to SINGLE_HOLD (Ctrl), matching
         every normal mod-tap key on the board.
      2) Double-tap fired the transliteration fixer (F22). The user expects a
         double tap to switch language, so we remap DOUBLE_TAP / DOUBLE_SINGLE_TAP
         to KC_F18 as well (a second language switch).

    Detection: the language dance is the one whose *_finished body taps/registers
    KC_F18 in its SINGLE_TAP case.
    """
    dance_indices = _discover_dance_indices(content)
    patched_any = False

    for idx in dance_indices:
        finished_name = f"dance_{idx}_finished"
        reset_name = f"dance_{idx}_reset"

        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished:
            continue

        # Identify the language dance by its F18 single-tap signature.
        if "KC_F18" not in finished_body:
            continue
        if "SINGLE_TAP" not in finished_body:
            continue

        finished_new = finished_body

        # (1) Hold preference: interrupted single press -> SINGLE_HOLD (Ctrl).
        if LANGUAGE_F18_HOLD_MARKER not in finished_new:
            step_assign_pat = re.compile(
                rf"dance_state\s*\[\s*{idx}\s*\]\.step\s*=\s*dance_step\s*\(\s*state\s*\)\s*;"
            )
            step_replacement = (
                "if (state->count == 1 && state->interrupted) {\n"
                f"        dance_state[{idx}].step = SINGLE_HOLD; /* {LANGUAGE_F18_HOLD_MARKER} */\n"
                "    } else {\n"
                f"        dance_state[{idx}].step = dance_step(state);\n"
                "    }"
            )
            finished_new, n = step_assign_pat.subn(step_replacement, finished_new, count=1)
            if n:
                patched_any = True

        # (2) Double tap -> language switch (F18), not the F22 fixer.
        finished_new, dt = _replace_case_block(
            finished_new,
            "DOUBLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_TAP: register_code16(KC_F18); "
                f"break; /* {LANGUAGE_F18_DOUBLETAP_MARKER} */"
            ),
        )
        finished_new, dst = _replace_case_block(
            finished_new,
            "DOUBLE_SINGLE_TAP",
            lambda indent: (
                f"{indent}case DOUBLE_SINGLE_TAP: register_code16(KC_F18); "
                f"break; /* {LANGUAGE_F18_DOUBLETAP_MARKER} */"
            ),
        )
        if dt or dst:
            patched_any = True

        content = _replace_function_body(content, finished_name, finished_new)

        # Mirror the keycode change in the matching reset handler (unregister F18).
        reset_body, has_reset = _get_function_body(content, reset_name)
        if has_reset:
            reset_new = reset_body
            reset_new, _ = _replace_case_block(
                reset_new,
                "DOUBLE_TAP",
                lambda indent: (
                    f"{indent}case DOUBLE_TAP: unregister_code16(KC_F18); "
                    f"break; /* {LANGUAGE_F18_DOUBLETAP_MARKER} */"
                ),
            )
            reset_new, _ = _replace_case_block(
                reset_new,
                "DOUBLE_SINGLE_TAP",
                lambda indent: (
                    f"{indent}case DOUBLE_SINGLE_TAP: unregister_code16(KC_F18); "
                    f"break; /* {LANGUAGE_F18_DOUBLETAP_MARKER} */"
                ),
            )
            content = _replace_function_body(content, reset_name, reset_new)

        # Only one language dance exists; stop after patching it.
        return content, patched_any

    return content, patched_any


def _find_oryx_keycode_enum_base(content: str) -> str:
    """
    Determine the keycode value our custom enum must start at so it does NOT
    collide with Oryx's own `enum custom_keycodes`.

    Oryx emits e.g. `enum custom_keycodes { RGB_SLD = ZSA_SAFE_RANGE, HSV_..., ST_MACRO_17 };`
    where ZSA_SAFE_RANGE == SAFE_RANGE. If we also anchor at SAFE_RANGE, our
    MIDI_BASS_SHIFT_* keycodes alias Oryx's first members (RGB_SLD, HSV_0_0_0),
    which would let our handler swallow those keys. So we base our enum at the
    LAST member of the Oryx enum + 1.

    Returns a C expression string to use as the base value.
    """
    enum_pat = re.compile(r"\benum\s+custom_keycodes\s*\{")
    m = enum_pat.search(content)
    if not m:
        # No Oryx custom keycode enum present; SAFE_RANGE is safe to use.
        return "SAFE_RANGE"

    open_brace_idx = content.find("{", m.start())
    if open_brace_idx == -1:
        return "SAFE_RANGE"
    close_brace_idx = _find_matching_brace(content, open_brace_idx)
    if close_brace_idx == -1:
        return "SAFE_RANGE"

    body = content[open_brace_idx + 1 : close_brace_idx]
    # Collect identifiers in declaration order, ignoring any "= value" parts.
    members = []
    for raw in body.split(","):
        token = raw.strip()
        if not token:
            continue
        name = token.split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            members.append(name)

    if not members:
        return "SAFE_RANGE"

    return f"({members[-1]} + 1)"


def _patch_keyboard_post_init_midi_octave(content: str) -> tuple[str, bool]:
    """
    Inject MIDI octave setting into the existing keyboard_post_init_user function.
    QMK's default MIDI octave (4) makes MI_C2 sound as C5 instead of C2.
    Setting octave=1 aligns keycode octaves with sounding octaves.
    """
    if "midi_config.octave = 1" in content:
        return content, True  # Already patched

    # Find the keyboard_post_init_user function
    func_pattern = r'void\s+keyboard_post_init_user\s*\(\s*void\s*\)\s*\{([^}]*)\}'
    match = re.search(func_pattern, content)
    if not match:
        print("Warning: Could not find keyboard_post_init_user function")
        return content, False

    # Add MIDI octave setting inside the function
    original_body = match.group(1)
    midi_init_code = "\n#ifdef MIDI_ENABLE\n  midi_config.octave = 1;\n#endif\n"
    new_body = original_body + midi_init_code

    # Replace the function
    new_func = f"void keyboard_post_init_user(void) {{{new_body}}}"
    content = content[:match.start()] + new_func + content[match.end():]

    return content, True


def _inject_midi_keycode_enum(content: str) -> tuple[str, bool]:
    """
    Inject `enum user_custom_keycodes` near the TOP of keymap.c (after the
    #include lines, before keymaps[]). keymaps[2] references MIDI_BASS_SHIFT_*,
    which are our custom keycodes, so they must be declared before keymaps[].

    Kept in sync (identical names) with custom_qmk/custom_code.c. The base value
    is placed AFTER Oryx's own custom_keycodes enum to avoid keycode collisions.
    Wrapped in #ifdef MIDI_ENABLE so a non-MIDI build still compiles.
    """
    if MIDI_ENUM_MARKER in content:
        return content, True

    enum_base = _find_oryx_keycode_enum_base(content)

    enum_block = (
        "\n"
        f"/* {MIDI_ENUM_MARKER} */\n"
        "// Custom MIDI bass-shifter keycodes. Declared here (above keymaps[]) so\n"
        "// the MIDI layer can reference them. Kept in sync with custom_code.c.\n"
        "// Based AFTER Oryx's enum custom_keycodes to avoid keycode collisions.\n"
        "#ifdef MIDI_ENABLE\n"
        "enum user_custom_keycodes {\n"
        f"    MIDI_BASS_SHIFT_UP = {enum_base},\n"
        "    MIDI_BASS_SHIFT_DOWN,\n"
        "    USER_CUSTOM_KEYCODES_SAFE_RANGE,\n"
        "};\n"
        "#endif  // MIDI_ENABLE\n"
        "\n"
    )

    # Insert just before the keymaps[] definition so the enum precedes its use.
    keymaps_pat = re.compile(r"const\s+uint16_t\s+PROGMEM\s+keymaps\s*\[")
    m = keymaps_pat.search(content)
    if m:
        insert_idx = m.start()
        return content[:insert_idx] + enum_block + content[insert_idx:], True

    # Fallback: after the last include.
    include_matches = list(re.finditer(r"^\s*#include[^\n]*\n", content, flags=re.MULTILINE))
    if include_matches:
        insert_idx = include_matches[-1].end()
        return content[:insert_idx] + enum_block + content[insert_idx:], True

    return content, False


def _split_top_level_args(arg_text: str) -> list[str]:
    """
    Split a LAYOUT_moonlander(...) argument list on top-level commas only,
    keeping nested parens intact (e.g. MT(MOD_RALT, KC_TAB), LT(9, KC_F23)).
    Comments are stripped first.
    """
    # Strip block and line comments.
    arg_text = re.sub(r"/\*.*?\*/", "", arg_text, flags=re.DOTALL)
    arg_text = re.sub(r"//[^\n]*", "", arg_text)

    args = []
    depth = 0
    current = []
    for ch in arg_text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _build_midi_layer_body(original_args: list[str] | None = None) -> str:
    """
    Construct the LAYOUT_moonlander(...) argument list for the MIDI layer.

    If ``original_args`` (the flat 72-arg list parsed from the Oryx-generated
    layer 2) is provided, the k45 "big red thumb" position is preserved from it
    so a user-configured "back to layer 0" key survives the overwrite.

    Layout (confirmed in the plan / against the Oryx screenshot):
      Row 0 (k00..k0d): disabled top row (KC_NO x14)
      Row 1 (k10..k1d): sharps, biased right
      Row 2 (k20..k2d): naturals C3..B3 (left) / C4..B4 (right)
      Row 3 (k30..k3b): bass C2..F2 (left BASS1-6) / KC_NO x6 (right)
      Row 4 (k40..k4b): bass G2..B2 (left BASS7-11) + KC_NO,
                        then KC_NO (was LSFT(KC_ENTER) at k46) + KC_NO x5
      Row 5 (k50..k55): KC_NO, MIDI_BASS_SHIFT_UP (k51), MIDI_BASS_SHIFT_DOWN (k52),
                        KC_TRANSPARENT x3 (right thumb, unused on this layer)

    Note: enharmonic flat aliases (MI_Db4 etc.) keep the right-hand sharp labels
    matching the Oryx legends.
    """
    rows = [
        # Row 0: disabled top row
        ["KC_NO"] * 14,
        # Row 1: sharps (biased right; gaps stay KC_NO)
        ["KC_NO", "MI_Cs3", "MI_Ds3", "KC_NO", "MI_Fs3", "MI_Gs3", "MI_As3",
         "KC_NO", "MI_Db4", "MI_Eb4", "KC_NO", "MI_Gb4", "MI_Ab4", "MI_Bb4"],
        # Row 2: naturals C3..B3 (left) / C4..B4 (right)
        ["MI_C3", "MI_D3", "MI_E3", "MI_F3", "MI_G3", "MI_A3", "MI_B3",
         "MI_C4", "MI_D4", "MI_E4", "MI_F4", "MI_G4", "MI_A4", "MI_B4"],
        # Row 3: bass BASS1-6 (C2..F2) left, right disabled
        ["MI_C2", "MI_Cs2", "MI_D2", "MI_Ds2", "MI_E2", "MI_F2",
         "KC_NO", "KC_NO", "KC_NO", "KC_NO", "KC_NO", "KC_NO"],
        # Row 4: bass BASS7-11 (G2..B2) + k45 = the big red left thumb key (its
        # Oryx keycode is preserved below so the user's "back to layer 0" key
        # survives); k46 (right-hand stray LSFT(KC_ENTER)) neutralized to KC_NO.
        ["MI_G2", "MI_Gs2", "MI_A2", "MI_As2", "MI_B2", "KC45_PRESERVE",
         "KC_NO", "KC_NO", "KC_NO", "KC_NO", "KC_NO", "KC_NO"],
        # Row 5: thumb cluster. Purple-lit left thumbs k51/k52 = shifters.
        ["KC_NO", "MIDI_BASS_SHIFT_UP", "MIDI_BASS_SHIFT_DOWN",
         "KC_TRANSPARENT", "KC_TRANSPARENT", "KC_TRANSPARENT"],
    ]

    # k45 (the big red left thumb key) is the 6th key of row 4 -> flat index 59.
    # Preserve whatever the user mapped there in Oryx (e.g. TO(0) to leave the
    # MIDI layer). Fall back to KC_TRANSPARENT only if we cannot read it.
    K45_FLAT_INDEX = 59
    preserved_k45 = "KC_TRANSPARENT"
    if original_args is not None and len(original_args) > K45_FLAT_INDEX:
        candidate = original_args[K45_FLAT_INDEX].strip()
        if candidate:
            preserved_k45 = candidate

    lines = []
    for row in rows:
        rendered = [preserved_k45 if tok == "KC45_PRESERVE" else tok for tok in row]
        lines.append("    " + ", ".join(rendered) + ",")
    # Drop the trailing comma on the very last argument.
    body = "\n".join(lines)
    body = body.rstrip()
    if body.endswith(","):
        body = body[:-1]
    return "\n" + body + "\n  "


def _inject_midi_layer(content: str) -> tuple[str, bool]:
    """
    Overwrite the layer-2 keymap body in place with real MIDI keycodes.

    The Oryx export leaves layer 2 as KC_TRANSPARENT / KC_NO placeholders; this
    rewrites the argument list of `[2] = LAYOUT_moonlander( ... )`. The ledmap
    for layer 2 is already correct from Oryx and is intentionally left untouched.
    """
    if MIDI_LAYER_MARKER in content:
        return content, True

    layer_pat = re.compile(
        rf"\[\s*{MIDI_LAYER_INDEX}\s*\]\s*=\s*LAYOUT(?:_moonlander)?\s*\("
    )
    m = layer_pat.search(content)
    if not m:
        return content, False

    open_paren_idx = content.find("(", m.start())
    if open_paren_idx == -1:
        return content, False

    close_paren_idx = _find_matching_paren(content, open_paren_idx)
    if close_paren_idx == -1:
        return content, False

    # Parse the original (Oryx) layer-2 argument list so we can preserve specific
    # user-configured keys (e.g. the big red thumb "back to layer 0" key at k45).
    inner = content[open_paren_idx + 1 : close_paren_idx]
    original_args = _split_top_level_args(inner)

    new_body = _build_midi_layer_body(original_args if len(original_args) == 72 else None)
    marker = f"  /* {MIDI_LAYER_MARKER} */"
    replacement = (
        content[: open_paren_idx + 1]
        + marker
        + new_body
        + content[close_paren_idx:]
    )
    return replacement, True


def patch_config_h_midi(layout_dir: str) -> None:
    """
    Enable ADVANCED MIDI in config.h (paired with MIDI_ENABLE=yes in rules.mk).

    We use MIDI_ADVANCED (not MIDI_BASIC) because:
      - Only MIDI_ADVANCED routes note keycodes through process_midi(), which
        decodes the note BY KEYCODE VALUE (midi_compute_note) and tracks
        note-on/off. This is what lets the per-key bass shifter forward a
        transposed note keycode and have it sound correctly.
      - MIDI_BASIC instead routes notes through process_music(), which requires
        MIDI mode to be toggled on (MI_ON) and computes notes from MATRIX
        POSITION, ignoring the note keycode entirely.
      - MIDI_ADVANCED is a strict superset of MIDI_BASIC (all note keycodes plus
        octave/transpose/velocity/channel), so it is the future-proof choice.
    """
    config_path = os.path.join(layout_dir, "config.h")
    if not os.path.exists(config_path):
        print(f"Warning: {config_path} not found; cannot inject MIDI_ADVANCED.")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Migrate any previously-injected MIDI_BASIC define to MIDI_ADVANCED.
    basic_pat = re.compile(r"^[ \t]*#define[ \t]+MIDI_BASIC\b.*$", flags=re.MULTILINE)
    if basic_pat.search(content):
        content = basic_pat.sub("#define MIDI_ADVANCED", content)
        # Also fix the stale "Basic MIDI support" comment if present.
        content = content.replace(
            "// Basic MIDI support (paired with MIDI_ENABLE=yes in rules.mk).",
            "// Advanced MIDI support (paired with MIDI_ENABLE=yes in rules.mk).",
        )
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Migrated config.h MIDI_BASIC -> MIDI_ADVANCED")
        return

    if re.search(r"^\s*#define\s+MIDI_ADVANCED\b", content, flags=re.MULTILINE):
        print("config.h already defines MIDI_ADVANCED; skipping.")
        return

    addition = "\n// Advanced MIDI support (paired with MIDI_ENABLE=yes in rules.mk).\n#define MIDI_ADVANCED\n"
    if not content.endswith("\n"):
        content += "\n"
    content += addition

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Injected #define MIDI_ADVANCED into config.h")


def patch_rules_mk_midi(layout_dir: str) -> None:
    """
    Ensure MIDI_ENABLE = yes in rules.mk. Replace any existing MIDI_ENABLE line
    (regardless of its value) or append one if missing.
    """
    rules_path = os.path.join(layout_dir, "rules.mk")
    if not os.path.exists(rules_path):
        print(f"Warning: {rules_path} not found; cannot enable MIDI.")
        return

    with open(rules_path, "r", encoding="utf-8") as f:
        content = f.read()

    midi_line_pat = re.compile(r"^\s*MIDI_ENABLE\s*=.*$", flags=re.MULTILINE)
    if midi_line_pat.search(content):
        new_content = midi_line_pat.sub("MIDI_ENABLE = yes", content, count=1)
        if new_content != content:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("Set existing MIDI_ENABLE line to yes in rules.mk")
        else:
            print("MIDI_ENABLE already set to yes in rules.mk")
        return

    if not content.endswith("\n"):
        content += "\n"
    content += "MIDI_ENABLE = yes\n"
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Appended MIDI_ENABLE = yes to rules.mk")


def patch_config_h_low_latency(layout_dir: str) -> None:
    """
    Inject global low-latency settings into config.h for snappier MIDI (and
    typing) response. These are keyboard-wide and do NOT change any keycode
    behavior on any layer, so they are safe for the whole layout:

      - DEBOUNCE 1: QMK default is 5 ms; the debounce delay is added to every
        key event before it is reported. 1 ms is safe for modern switches and
        removes ~4 ms of latency per note-on/note-off.
      - USB_POLLING_INTERVAL_MS 1: forces 1000 Hz USB reporting (1 ms) so note
        events are delivered to the host as fast as USB Full Speed allows.

    Idempotent: existing definitions are replaced (or added if missing).
    """
    config_path = os.path.join(layout_dir, "config.h")
    if not os.path.exists(config_path):
        print(f"Warning: {config_path} not found; cannot inject low-latency settings.")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    settings = [
        ("DEBOUNCE", "1"),
        ("USB_POLLING_INTERVAL_MS", "1"),
    ]

    additions = []
    for name, value in settings:
        define_pat = re.compile(rf"^[ \t]*#define[ \t]+{name}\b.*$", flags=re.MULTILINE)
        new_line = f"#define {name} {value}"
        if define_pat.search(content):
            new_content = define_pat.sub(new_line, content, count=1)
            if new_content != content:
                content = new_content
                print(f"Updated existing #define {name} -> {value} in config.h")
            else:
                print(f"config.h already defines {name} {value}; skipping.")
        else:
            additions.append(new_line)

    if additions:
        block = (
            "\n// Low-latency settings (global). Faster MIDI/typing response; "
            "safe for all layers.\n" + "\n".join(additions) + "\n"
        )
        if not content.endswith("\n"):
            content += "\n"
        content += block
        print(f"Injected low-latency settings into config.h: {', '.join(a.split()[1] for a in additions)}")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)


def patch_keymap(layout_dir: str) -> None:
    keymap_path = os.path.join(layout_dir, "keymap.c")
    if not os.path.exists(keymap_path):
        print(f"Error: {keymap_path} not found")
        print(f"Contents of {layout_dir}:")
        for f in os.listdir(layout_dir):
            print(f)
        sys.exit(1)

    with open(keymap_path, "r", encoding="utf-8") as f:
        content = f.read()

    print("Found keymap.c, length:", len(content))
    dance_indices = _discover_dance_indices(content)
    print(f"Discovered tap-dance indices: {dance_indices}")

    # 1) Keep key semantics Oryx-managed, but allow RGB hook injection so
    # custom language indicator state can be driven from host RAW HID updates.
    enable_language_injection = False
    enable_language_rgb_hook_injection = True
    if enable_language_injection or enable_language_rgb_hook_injection:
        # Add forward declarations for custom language hooks.
        content, _ = _inject_custom_language_prototypes(content)
    else:
        print("Skipping language prototype injection (Oryx-managed language behavior).")

    # 2) Replace FN24 behavior only in the corresponding tap-dance function.
    content, replaced = _replace_fn24_in_space_tap_dance(content, dance_indices)
    if replaced:
        print("Replaced KC_F24 tap-dance behavior with KP_DOT+SPACE on double tap")
    elif "KC_F24" in content:
        print("Warning: KC_F24 found, but no matching dance_<n>_finished/reset patch target was found.")
    else:
        print("KC_F24 not present in keymap.c; no FN24 tap-dance replacement needed.")

    # 3) Optional language switch/resync injection.
    if enable_language_injection:
        content, lang_toggle_patched, lang_resync_patched = _patch_language_switch_tap_dance(content, dance_indices)
        if lang_toggle_patched:
            print("Patched language key single-tap toggle behavior")
        else:
            print("Warning: Did not patch language key single-tap toggle behavior.")

        if lang_resync_patched:
            print("Patched language key double-tap resync behavior")
        else:
            print("Warning: Did not patch language key resync behavior.")

    else:
        print("Skipping language tap-dance patching (Oryx-managed language behavior).")

    # 4) Optional RGB indicator hook injection.
    if enable_language_rgb_hook_injection:
        content, rgb_patched = _patch_rgb_indicator_hook(content)
        if rgb_patched:
            print("Patched rgb_matrix_indicators_user with custom language indicator hook")
        else:
            print("Warning: rgb_matrix_indicators_user not found; language RGB indicator hook not applied.")
    else:
        print("Skipping language RGB indicator hook patching (Oryx-managed language behavior).")

    # 4b) Fix the F18-based language dance hold feel + double-tap (Bug 3).
    content, f18_lang_patched = _patch_f18_language_dance(content)
    if f18_lang_patched:
        print("Patched F18 language dance: hold-preference (Ctrl) + double-tap language switch")
    else:
        print("No F18 language dance found to patch (skipping).")

    # 5) For the SPACE/SHIFT dance, prefer hold when interrupted by another key.
    content, spaceshift_hold_pref_patched = _prefer_hold_for_space_shift_dance(content, dance_indices)
    if spaceshift_hold_pref_patched:
        print("Patched SPACE/SHIFT dance to prefer hold on interrupt")
    else:
        print("Warning: Could not patch SPACE/SHIFT hold-preference behavior.")

    # 6) For dances without explicit hold behavior, treat SINGLE_HOLD as SINGLE_TAP.
    content, hold_fallback_count = _normalize_tap_dance_hold_resolution(content, dance_indices)
    if hold_fallback_count > 0:
        print(f"Added SINGLE_HOLD->SINGLE_TAP fallback to {hold_fallback_count} tap-dance handlers")
    else:
        print("No tap-dance SINGLE_HOLD fallback patching required.")

    # 7) For dances without explicit double-hold behavior, treat DOUBLE_SINGLE_TAP
    # as DOUBLE_TAP so interrupted doubles still trigger the double function.
    content, doubletap_fallback_count = _normalize_tap_dance_double_tap_resolution(content, dance_indices)
    if doubletap_fallback_count > 0:
        print(f"Added DOUBLE_SINGLE_TAP->DOUBLE_TAP fallback to {doubletap_fallback_count} tap-dance handlers")
    else:
        print("No tap-dance DOUBLE_SINGLE_TAP fallback patching required.")

    # 8) Keep tapping terms entirely Oryx-managed for now.
    print("Skipping script-level tapping-term overrides (using Oryx tap terms).")
    # Tap-term overrides are intentionally disabled for now.
    # To re-enable, uncomment the block below:
    # content, space_dot_term_patched = _increase_space_dot_tapping_term(content, dance_indices)
    # if space_dot_term_patched:
    #     print("Raised dot+space dance tapping term by ~20%")
    # else:
    #     print("Warning: Could not raise dot+space dance tapping term.")
    #
    # content, language_term_patched = _set_language_switch_tapping_term(content, dance_indices)
    # if language_term_patched:
    #     print(f"Set language switch tapping term to {LANGUAGE_SWITCH_TAPPING_TERM_MS}ms")
    # else:
    #     print("Warning: Could not set language switch tapping term.")
    #
    # if RELAX_AGGRESSIVE_TAPPING_TERMS:
    #     content, tapping_term_changes = _relax_aggressive_tapping_terms(content)
    #     if tapping_term_changes > 0:
    #         print(
    #             f"Relaxed {tapping_term_changes} aggressive per-key tapping-term reductions "
    #             f"(max subtract: {MAX_TAPPING_TERM_SUBTRACT})"
    #         )
    #     else:
    #         print("No aggressive per-key tapping-term reductions required patching.")
    # else:
    #     print("Keeping Oryx per-key tapping terms unchanged.")

    # 8.5) MIDI injection: declare custom bass-shift keycodes (top of file) and
    # overwrite the layer-2 placeholders with real MIDI keycodes.
    content, midi_enum_injected = _inject_midi_keycode_enum(content)
    if midi_enum_injected:
        print("Injected MIDI custom-keycode enum near top of keymap.c")
    else:
        print("Warning: Could not inject MIDI custom-keycode enum.")

    content, midi_layer_injected = _inject_midi_layer(content)
    if midi_layer_injected:
        print(f"Overwrote layer {MIDI_LAYER_INDEX} with MIDI keycodes")
    else:
        print(f"Warning: Could not find layer {MIDI_LAYER_INDEX} to inject MIDI keycodes.")

    # 8.6) Patch keyboard_post_init_user to set MIDI octave=1
    content, midi_octave_patched = _patch_keyboard_post_init_midi_octave(content)
    if midi_octave_patched:
        print("Patched keyboard_post_init_user to set MIDI octave=1")
    else:
        print("Warning: Could not patch keyboard_post_init_user for MIDI octave.")

    # 9) Hook process_record_user
    wrapper_marker = "INJECTED BY ORYX-CUSTOM-MOONLANDER WORKFLOW"
    if wrapper_marker in content and '#include "custom_code.c"' in content:
        print("process_record_user wrapper already injected; skipping reinjection.")
    else:
        pattern = r"bool\s+process_record_user\s*\("
        if not re.search(pattern, content):
            print("Error: Could not find process_record_user in keymap.c")
            print("File start:", content[:500])
            sys.exit(1)

        content = re.sub(pattern, "bool process_record_user_oryx(", content, count=1)

        wrapper_code = (
            "\n\n// ============================================================\n"
            "// INJECTED BY ORYX-CUSTOM-MOONLANDER WORKFLOW\n"
            "// ============================================================\n"
            "bool process_record_user_oryx(uint16_t keycode, keyrecord_t *record);\n"
            '#include "custom_code.c"\n'
            + "\n"
            "bool process_record_user(uint16_t keycode, keyrecord_t *record) {\n"
            "    if (!process_record_user_custom(keycode, record)) {\n"
            "        return false;\n"
            "    }\n"
            "    return process_record_user_oryx(keycode, record);\n"
            "}\n"
        )

        content += wrapper_code

    with open(keymap_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Successfully patched keymap.c")

    # 10) Enable MIDI in the build (config.h + rules.mk).
    patch_config_h_midi(layout_dir)
    patch_rules_mk_midi(layout_dir)

    # 11) Global low-latency tuning (DEBOUNCE, USB polling) for MIDI responsiveness.
    patch_config_h_low_latency(layout_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: patch_keymap.py <layout_dir>")
        sys.exit(1)
    patch_keymap(sys.argv[1])
