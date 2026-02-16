import os
import re
import sys

PATCH_MARKER = "ORYX_FN24_NUMDOT_SPACE_PATCH"


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


def _replace_fn24_in_space_tap_dance(content: str) -> tuple[str, bool]:
    """
    Replace FN24 in the generated right-thumb tap dance with:
      DOUBLE_TAP => num-dot then space.
    Target only dance_<n>_finished/reset function bodies.
    """
    for dance_idx in range(0, 24):
        finished_name = f"dance_{dance_idx}_finished"
        reset_name = f"dance_{dance_idx}_reset"

        finished_body, has_finished = _get_function_body(content, finished_name)
        if not has_finished or "KC_F24" not in finished_body:
            continue

        finished_body_new, finished_n = re.subn(
            r"case\s+DOUBLE_TAP\s*:\s*(?:register_code16|tap_code16)\s*\(\s*KC_F24\s*\)\s*;\s*break\s*;",
            f"case DOUBLE_TAP: tap_code16(KC_KP_DOT); register_code16(KC_SPACE); break; /* {PATCH_MARKER} */",
            finished_body,
            count=1,
        )
        if finished_n == 0:
            continue
        content = _replace_function_body(content, finished_name, finished_body_new)

        reset_body, has_reset = _get_function_body(content, reset_name)
        if has_reset:
            reset_body_new, reset_n = re.subn(
                r"case\s+DOUBLE_TAP\s*:\s*(?:unregister_code16|tap_code16)\s*\(\s*KC_F24\s*\)\s*;\s*break\s*;",
                f"case DOUBLE_TAP: unregister_code16(KC_SPACE); break; /* {PATCH_MARKER} */",
                reset_body,
                count=1,
            )
            if reset_n > 0:
                content = _replace_function_body(content, reset_name, reset_body_new)

        return content, True

    return content, False



def patch_keymap(layout_dir: str, custom_code_path: str) -> None:
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

    # 1) Replace FN24 behavior only in the corresponding tap-dance function.
    content, replaced = _replace_fn24_in_space_tap_dance(content)
    if replaced:
        print("Replaced KC_F24 tap-dance behavior with KP_DOT+SPACE on double tap")
    elif "KC_F24" in content:
        print("Warning: KC_F24 found, but no matching dance_<n>_finished/reset patch target was found.")
    else:
        print("KC_F24 not present in keymap.c; no FN24 tap-dance replacement needed.")

    # 2) Hook process_record_user
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


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: patch_keymap.py <layout_dir> <custom_code_path>")
        sys.exit(1)
    patch_keymap(sys.argv[1], sys.argv[2])
