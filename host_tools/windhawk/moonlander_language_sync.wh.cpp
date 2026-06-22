// ==WindhawkMod==
// @id              moonlander-language-sync
// @name            Moonlander Language Sync
// @description     Maps F18 to language switching, F22 to wrong-language text fixer, F19 to case cycling, and syncs EN/HE state to QMK RGB via RAW HID.
// @version         1.2.0
// @include         explorer.exe
// @compilerOptions -lsetupapi -lhid
// ==/WindhawkMod==

// ==WindhawkModReadme==
// This mod provides three keyboard shortcuts and language state sync:
//
// 1) F18: Language-switch shortcut (Win+Space by default).
// 2) F22: Wrong-language text fixer. Copies selected text, flips Hebrew/English
//         characters based on physical key positions (kbdhebl3 layout), and pastes.
// 3) F19: Case cycler. Copies selected text, cycles case (lower->UPPER->Title),
//         and pastes.
// 4) Language state sync: Sends current Windows input language state to QMK
//    over RAW HID:
//    - English -> 0
//    - Hebrew  -> 1
//
// Transport:
// Uses Oryx's ORYX_STATUS_LED_CONTROL command (0x0A), where param[0]
// carries the language state (0 English, 1 Hebrew). Firmware reads the
// mirrored bool via rawhid_state.status_led_control.
//
// Recommended keyboard mapping (use F-keys NOT already used in your QMK layout):
// - F18: Tap for language switch, Hold for KC_LEFT_CTRL
// - F22: Wrong-language text fixer
// - F19: Case cycler
// ==/WindhawkModReadme==

// ==WindhawkModSettings==
/*
- enableF18Hotkey: true
  $name: Enable F18 language hotkey
  $description: If enabled, F18 sends the configured language shortcut.
- shortcutMode: 1
  $name: F18 shortcut mode
  $description: 0=None, 1=Win+Space, 2=Alt+Shift, 3=Ctrl+Shift.
- enableF22Hotkey: true
  $name: Enable F22 wrong-language fixer
  $description: If enabled, F22 copies selected text, flips Hebrew/English characters, and pastes.
- enableF19Hotkey: true
  $name: Enable F19 case cycler
  $description: If enabled, F19 copies selected text, cycles case (lower->UPPER->Title), and pastes.
- pollIntervalMs: 120
  $name: Poll interval (ms)
  $description: How often to read current Windows input language.
- onlyMoonlander: true
  $name: Restrict to Moonlander
  $description: If enabled, only devices with product string containing "Moonlander" are targeted.
- debugLogging: false
  $name: Debug logging
  $description: Enable verbose Windhawk log messages.
*/
// ==/WindhawkModSettings==

#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <hidpi.h>

#include <cstdint>
#include <cwctype>
#include <string>
#include <vector>
#include <unordered_map>

namespace {

constexpr UINT kHotkeyIdF18 = 0xA701;
constexpr UINT kHotkeyIdF22 = 0xA702;
constexpr UINT kHotkeyIdF19 = 0xA703;
constexpr uint16_t kRawHidUsagePage = 0xFF60;
constexpr uint16_t kRawHidUsage = 0x0061;
constexpr uint8_t kOryxStatusLedControlCommand = 0x0A;
constexpr uint8_t kLanguageSyncEnglish = 0x00;
constexpr uint8_t kLanguageSyncHebrew = 0x01;
constexpr DWORD kRetryWhenNotSentMs = 5000;
constexpr DWORD kClipboardDelayMs = 100;

enum ShortcutMode : int {
    ShortcutNone = 0,
    ShortcutWinSpace = 1,
    ShortcutAltShift = 2,
    ShortcutCtrlShift = 3,
};

struct Settings {
    bool enable_f18_hotkey = true;
    int shortcut_mode = ShortcutWinSpace;
    bool enable_f22_hotkey = true;
    bool enable_f19_hotkey = true;
    int poll_interval_ms = 120;
    bool only_moonlander = true;
    bool debug_logging = false;
};

Settings g_settings;
HANDLE g_stop_event = nullptr;
HANDLE g_worker_thread = nullptr;

// Re-entrancy guard: set to true while a clipboard-transform transaction is
// in flight (send_ctrl_c + read/transform/write/send_ctrl_v/reselect). The
// worker-thread hotkey dispatch raises this across the entire transaction so
// the hotkey cannot fire a second time in the gap between send_ctrl_c and
// send_ctrl_v, which previously produced a duplicate paste of the original
// text adjacent to the transformed text.
static bool g_is_synthesizing = false;

// Forward declarations: send_key_event() and friends are defined later in the
// file, but the clipboard helpers (send_ctrl_c/send_ctrl_v) call them first.
void send_key_event(WORD virtual_key, bool pressed);
void send_modifier_chord(WORD mod1, WORD mod2);

// Hebrew/English character maps based on kbdhebl3 (Hebrew Standard) layout.
// Maps based on PHYSICAL KEY POSITION: each English character maps to the Hebrew
// character produced by the same physical key in Hebrew mode, and vice versa.
// The whole file is kept ASCII-only; Hebrew is expressed via \u escapes below.

// Hebrew letters are written as explicit \u escapes (not literal glyphs) so the
// mapping is independent of source-file encoding and editor/compiler charset
// assumptions. Reference (kbdhebl3 unshifted):
//   qof=\u05E7 resh=\u05E8 alef=\u05D0 tet=\u05D8 vav=\u05D5 nun_final=\u05DF
//   mem_final=\u05DD pe=\u05E4 shin=\u05E9 dalet=\u05D3 gimel=\u05D2 kaf=\u05DB
//   ayin=\u05E2 yod=\u05D9 het=\u05D7 lamed=\u05DC kaf_final=\u05DA pe_final=\u05E3
//   comma->tav=\u05EA zayin=\u05D6 samekh=\u05E1 bet=\u05D1 he=\u05D4 nun=\u05E0
//   mem=\u05DE tsadi=\u05E6 tsadi_final=\u05E5

// English -> Hebrew mapping (physical key position)
static const std::unordered_map<wchar_t, wchar_t> kEnglishToHebrew = {
    {'Q', L'/'}, {'W', L'\''}, {'E', L'\u05E7'}, {'R', L'\u05E8'}, {'T', L'\u05D0'}, {'Y', L'\u05D8'},
    {'U', L'\u05D5'}, {'I', L'\u05DF'}, {'O', L'\u05DD'}, {'P', L'\u05E4'}, {'[', L'}'}, {']', L'{'}, {'\\', L'|'},
    {'A', L'\u05E9'}, {'S', L'\u05D3'}, {'D', L'\u05D2'}, {'F', L'\u05DB'}, {'G', L'\u05E2'}, {'H', L'\u05D9'},
    {'J', L'\u05D7'}, {'K', L'\u05DC'}, {'L', L'\u05DA'}, {';', L'\u05E3'}, {'\'', L','},
    {'Z', L'\u05D6'}, {'X', L'\u05E1'}, {'C', L'\u05D1'}, {'V', L'\u05D4'}, {'B', L'\u05E0'},
    {'N', L'\u05DE'}, {'M', L'\u05E6'}, {',', L'\u05EA'}, {'.', L'\u05E5'}, {'/', L'.'},
    // Lowercase
    {'q', L'/'}, {'w', L'\''}, {'e', L'\u05E7'}, {'r', L'\u05E8'}, {'t', L'\u05D0'}, {'y', L'\u05D8'},
    {'u', L'\u05D5'}, {'i', L'\u05DF'}, {'o', L'\u05DD'}, {'p', L'\u05E4'},
    {'a', L'\u05E9'}, {'s', L'\u05D3'}, {'d', L'\u05D2'}, {'f', L'\u05DB'}, {'g', L'\u05E2'}, {'h', L'\u05D9'},
    {'j', L'\u05D7'}, {'k', L'\u05DC'}, {'l', L'\u05DA'},
    {'z', L'\u05D6'}, {'x', L'\u05E1'}, {'c', L'\u05D1'}, {'v', L'\u05D4'}, {'b', L'\u05E0'},
    {'n', L'\u05DE'}, {'m', L'\u05E6'}
};

// Hebrew -> English mapping (reverse of above).
// English values are LOWERCASE: Hebrew has no case, so transcribing to English
// should default to lowercase (the user can then use the F19 case cycler).
static const std::unordered_map<wchar_t, wchar_t> kHebrewToEnglish = {
    {L'/', 'q'}, {L'\'', 'w'}, {L'\u05E7', 'e'}, {L'\u05E8', 'r'}, {L'\u05D0', 't'}, {L'\u05D8', 'y'},
    {L'\u05D5', 'u'}, {L'\u05DF', 'i'}, {L'\u05DD', 'o'}, {L'\u05E4', 'p'}, {L'}', '['}, {L'{', ']'}, {L'|', '\\'},
    {L'\u05E9', 'a'}, {L'\u05D3', 's'}, {L'\u05D2', 'd'}, {L'\u05DB', 'f'}, {L'\u05E2', 'g'}, {L'\u05D9', 'h'},
    {L'\u05D7', 'j'}, {L'\u05DC', 'k'}, {L'\u05DA', 'l'}, {L'\u05E3', ';'}, {L',', '\''},
    {L'\u05D6', 'z'}, {L'\u05E1', 'x'}, {L'\u05D1', 'c'}, {L'\u05D4', 'v'}, {L'\u05E0', 'b'},
    {L'\u05DE', 'n'}, {L'\u05E6', 'm'}, {L'\u05EA', ','}, {L'\u05E5', '.'}, {L'.', '/'}
};

// Clipboard helpers
bool get_clipboard_text(std::wstring &text) {
    if (!OpenClipboard(nullptr)) {
        return false;
    }
    HANDLE h_data = GetClipboardData(CF_UNICODETEXT);
    if (!h_data) {
        CloseClipboard();
        return false;
    }
    wchar_t *p_data = static_cast<wchar_t *>(GlobalLock(h_data));
    if (!p_data) {
        CloseClipboard();
        return false;
    }
    text = p_data;
    GlobalUnlock(h_data);
    CloseClipboard();
    return true;
}

bool set_clipboard_text(const std::wstring &text) {
    if (!OpenClipboard(nullptr)) {
        return false;
    }
    EmptyClipboard();
    size_t size = (text.size() + 1) * sizeof(wchar_t);
    HANDLE h_data = GlobalAlloc(GMEM_MOVEABLE, size);
    if (!h_data) {
        CloseClipboard();
        return false;
    }
    wchar_t *p_data = static_cast<wchar_t *>(GlobalLock(h_data));
    if (!p_data) {
        GlobalFree(h_data);
        CloseClipboard();
        return false;
    }
    wcscpy_s(p_data, text.size() + 1, text.c_str());
    GlobalUnlock(h_data);
    SetClipboardData(CF_UNICODETEXT, h_data);
    CloseClipboard();
    return true;
}

// Release any physically-held modifiers so our synthetic Ctrl chord is clean
// (e.g. a held Shift must not turn Ctrl+C into Ctrl+Shift+C). We only release;
// the physical key-up events from the user will be no-ops afterwards.
void clear_held_modifiers() {
    const WORD mods[] = {VK_LSHIFT, VK_RSHIFT, VK_LMENU, VK_RMENU,
                         VK_LWIN,   VK_RWIN,   VK_LCONTROL, VK_RCONTROL};
    for (WORD vk : mods) {
        if (GetAsyncKeyState(vk) & 0x8000) {
            send_key_event(vk, false);
        }
    }
}

void send_ctrl_c() {
    clear_held_modifiers();
    send_key_event(VK_LCONTROL, true);
    send_key_event('C', true);
    send_key_event('C', false);
    send_key_event(VK_LCONTROL, false);
    Sleep(kClipboardDelayMs);
}

void send_ctrl_v() {
    clear_held_modifiers();
    send_key_event(VK_LCONTROL, true);
    send_key_event('V', true);
    send_key_event('V', false);
    send_key_event(VK_LCONTROL, false);
    Sleep(kClipboardDelayMs);
}

// After a paste, the selection is lost and the caret sits at the end of the
// pasted text. Re-select the pasted run by holding Shift and pressing Left
// `count` times. This keeps the text highlighted so the user can trigger the
// transform again (e.g. cycle case repeatedly) without re-selecting manually.
void reselect_after_paste(size_t count) {
    if (count == 0) {
        return;
    }
    clear_held_modifiers();
    send_key_event(VK_LSHIFT, true);
    for (size_t i = 0; i < count; i++) {
        send_key_event(VK_LEFT, true);
        send_key_event(VK_LEFT, false);
    }
    send_key_event(VK_LSHIFT, false);
}

// Returns true if ch is a Hebrew letter (final + non-final forms live in the
// Unicode block U+05D0..U+05EA).
static inline bool is_hebrew_letter(wchar_t ch) {
    return ch >= 0x05D0 && ch <= 0x05EA;
}

// Text transformation functions
std::wstring fix_wrong_language(const std::wstring &text) {
    // Detect direction using LETTERS only. Punctuation keys (',', '.', '/', etc.)
    // appear in both maps and would skew a naive count, so we ignore them here.
    int hebrew_count = 0;
    int english_count = 0;
    for (wchar_t ch : text) {
        if (is_hebrew_letter(ch)) {
            hebrew_count++;
        } else if ((ch >= L'A' && ch <= L'Z') || (ch >= L'a' && ch <= L'z')) {
            english_count++;
        }
    }
    
    // Use the appropriate map based on which language is predominant
    const std::unordered_map<wchar_t, wchar_t> *map = nullptr;
    if (hebrew_count > english_count) {
        map = &kHebrewToEnglish;
    } else if (english_count > hebrew_count) {
        map = &kEnglishToHebrew;
    } else {
        // Equal or no recognizable letters, return as-is
        return text;
    }
    
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t ch : text) {
        auto it = map->find(ch);
        if (it != map->end()) {
            result += it->second;
        } else {
            result += ch;  // Keep characters not in the map as-is
        }
    }
    return result;
}

// A word boundary is anything that is not a "word character". We treat only
// letters as word characters here (digits/punct/space all start a new word),
// which keeps Title-case detection and generation consistent.
static inline bool is_word_char(wchar_t ch) {
    return iswalpha(ch) != 0;
}

std::wstring to_upper_all(const std::wstring &text) {
    std::wstring r = text;
    for (wchar_t &ch : r) ch = towupper(ch);
    return r;
}

std::wstring to_lower_all(const std::wstring &text) {
    std::wstring r = text;
    for (wchar_t &ch : r) ch = towlower(ch);
    return r;
}

std::wstring to_title(const std::wstring &text) {
    std::wstring r;
    r.reserve(text.size());
    bool at_word_start = true;
    for (wchar_t ch : text) {
        if (is_word_char(ch)) {
            r += at_word_start ? towupper(ch) : towlower(ch);
            at_word_start = false;
        } else {
            r += ch;
            at_word_start = true;  // next letter begins a new word
        }
    }
    return r;
}

std::wstring cycle_case(const std::wstring &text) {
    if (text.empty()) {
        return text;
    }

    // Classify the current state by comparing against canonical forms.
    // Only consider strings that actually contain cased letters.
    bool has_alpha = false;
    for (wchar_t ch : text) {
        if (iswalpha(ch)) {
            has_alpha = true;
            break;
        }
    }
    if (!has_alpha) {
        return text;  // nothing to cycle
    }

    std::wstring lower = to_lower_all(text);
    std::wstring upper = to_upper_all(text);
    std::wstring title = to_title(text);

    // Cycle order: lower -> UPPER -> Title -> lower.
    // Use canonical comparison so ambiguous inputs fall through sensibly.
    if (text == lower) {
        return upper;
    } else if (text == upper) {
        // If Title == UPPER (e.g. single-letter words), skip to lower to avoid
        // a no-op that would feel like the key did nothing.
        return (title != upper) ? title : lower;
    } else if (text == title) {
        return lower;
    }

    // Mixed/unknown case: normalize to lowercase as a predictable starting point.
    return lower;
}

void fix_wrong_language_clipboard() {
    std::wstring text;
    if (!get_clipboard_text(text)) {
        if (g_settings.debug_logging) {
            Wh_Log(L"Failed to read clipboard for F22");
        }
        return;
    }
    
    std::wstring transformed = fix_wrong_language(text);
    if (transformed != text) {
        if (set_clipboard_text(transformed)) {
            send_ctrl_v();
            reselect_after_paste(transformed.size());
            if (g_settings.debug_logging) {
                Wh_Log(L"F22: Flipped %zu characters", transformed.size());
            }
        } else if (g_settings.debug_logging) {
            Wh_Log(L"F22: Failed to write clipboard");
        }
    } else if (g_settings.debug_logging) {
        Wh_Log(L"F22: No transformation needed");
    }
}

void cycle_case_clipboard() {
    std::wstring text;
    if (!get_clipboard_text(text)) {
        if (g_settings.debug_logging) {
            Wh_Log(L"Failed to read clipboard for F19");
        }
        return;
    }
    
    std::wstring transformed = cycle_case(text);
    if (transformed != text) {
        if (set_clipboard_text(transformed)) {
            send_ctrl_v();
            reselect_after_paste(transformed.size());
            if (g_settings.debug_logging) {
                Wh_Log(L"F19: Cycled case");
            }
        } else if (g_settings.debug_logging) {
            Wh_Log(L"F19: Failed to write clipboard");
        }
    } else if (g_settings.debug_logging) {
        Wh_Log(L"F19: No transformation needed");
    }
}

std::wstring to_lower_copy(const wchar_t *text) {
    if (!text) {
        return L"";
    }
    std::wstring lowered(text);
    for (wchar_t &ch : lowered) {
        ch = static_cast<wchar_t>(towlower(ch));
    }
    return lowered;
}

bool contains_case_insensitive(const wchar_t *haystack, const wchar_t *needle) {
    if (!needle || needle[0] == L'\0') {
        return true;
    }
    std::wstring hay = to_lower_copy(haystack);
    std::wstring ndl = to_lower_copy(needle);
    return hay.find(ndl) != std::wstring::npos;
}

void load_settings() {
    g_settings.enable_f18_hotkey = Wh_GetIntSetting(L"enableF18Hotkey") != 0;

    int shortcut_mode = Wh_GetIntSetting(L"shortcutMode");
    if (shortcut_mode < ShortcutNone || shortcut_mode > ShortcutCtrlShift) {
        shortcut_mode = ShortcutWinSpace;
    }
    g_settings.shortcut_mode = shortcut_mode;

    g_settings.enable_f22_hotkey = Wh_GetIntSetting(L"enableF22Hotkey") != 0;
    g_settings.enable_f19_hotkey = Wh_GetIntSetting(L"enableF19Hotkey") != 0;

    int poll_interval_ms = Wh_GetIntSetting(L"pollIntervalMs");
    if (poll_interval_ms < 20 || poll_interval_ms > 2000) {
        poll_interval_ms = 120;
    }
    g_settings.poll_interval_ms = poll_interval_ms;

    g_settings.only_moonlander = Wh_GetIntSetting(L"onlyMoonlander") != 0;
    g_settings.debug_logging = Wh_GetIntSetting(L"debugLogging") != 0;
}

void send_key_event(WORD virtual_key, bool pressed) {
    INPUT input = {};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = virtual_key;
    if (!pressed) {
        input.ki.dwFlags = KEYEVENTF_KEYUP;
    }
    SendInput(1, &input, sizeof(INPUT));
}

void send_win_space() {
    send_key_event(VK_LWIN, true);
    send_key_event(VK_SPACE, true);
    send_key_event(VK_SPACE, false);
    send_key_event(VK_LWIN, false);
}

void send_modifier_chord(WORD mod1, WORD mod2) {
    send_key_event(mod1, true);
    send_key_event(mod2, true);
    send_key_event(mod2, false);
    send_key_event(mod1, false);
}

void trigger_language_shortcut() {
    switch (g_settings.shortcut_mode) {
        case ShortcutWinSpace:
            send_win_space();
            break;
        case ShortcutAltShift:
            send_modifier_chord(VK_LMENU, VK_LSHIFT);
            break;
        case ShortcutCtrlShift:
            send_modifier_chord(VK_LCONTROL, VK_LSHIFT);
            break;
        case ShortcutNone:
        default:
            break;
    }
}

bool get_active_language_is_hebrew(bool *is_hebrew) {
    if (!is_hebrew) {
        return false;
    }

    HWND foreground_window = GetForegroundWindow();
    DWORD thread_id = foreground_window ? GetWindowThreadProcessId(foreground_window, nullptr) : 0;
    HKL keyboard_layout = GetKeyboardLayout(thread_id);
    LANGID lang_id = LOWORD((UINT_PTR)keyboard_layout);
    *is_hebrew = (PRIMARYLANGID(lang_id) == LANG_HEBREW);
    return true;
}

bool device_matches_filters(HANDLE device_handle) {
    wchar_t manufacturer[128] = {};
    wchar_t product[128] = {};
    HidD_GetManufacturerString(device_handle, manufacturer, sizeof(manufacturer));
    HidD_GetProductString(device_handle, product, sizeof(product));

    if (!contains_case_insensitive(manufacturer, L"zsa")) {
        return false;
    }

    if (g_settings.only_moonlander && !contains_case_insensitive(product, L"moonlander")) {
        return false;
    }

    return true;
}

bool send_language_report_to_device(HANDLE device_handle, bool is_hebrew) {
    PHIDP_PREPARSED_DATA preparsed_data = nullptr;
    if (!HidD_GetPreparsedData(device_handle, &preparsed_data) || !preparsed_data) {
        return false;
    }

    HIDP_CAPS caps = {};
    NTSTATUS caps_status = HidP_GetCaps(preparsed_data, &caps);
    HidD_FreePreparsedData(preparsed_data);

    if (caps_status != HIDP_STATUS_SUCCESS) {
        return false;
    }

    if (caps.UsagePage != kRawHidUsagePage || caps.Usage != kRawHidUsage) {
        return false;
    }

    const ULONG report_len = caps.OutputReportByteLength;
    if (report_len < 4) {
        return false;
    }

    std::vector<uint8_t> report(report_len, 0);
    report[0] = 0x00;  // Report ID
    report[1] = kOryxStatusLedControlCommand;
    report[2] = is_hebrew ? kLanguageSyncHebrew : kLanguageSyncEnglish;

    DWORD written = 0;
    BOOL write_ok = WriteFile(
        device_handle,
        report.data(),
        static_cast<DWORD>(report.size()),
        &written,
        nullptr
    );

    if (write_ok && written == report.size()) {
        return true;
    }

    return HidD_SetOutputReport(
        device_handle,
        report.data(),
        static_cast<ULONG>(report.size())
    ) == TRUE;
}

bool send_language_state_to_keyboards(bool is_hebrew) {
    GUID hid_guid = {};
    HidD_GetHidGuid(&hid_guid);

    HDEVINFO device_info = SetupDiGetClassDevsW(
        &hid_guid,
        nullptr,
        nullptr,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    );
    if (device_info == INVALID_HANDLE_VALUE) {
        return false;
    }

    bool any_sent = false;
    SP_DEVICE_INTERFACE_DATA interface_data = {};
    interface_data.cbSize = sizeof(interface_data);

    for (DWORD index = 0;; ++index) {
        if (!SetupDiEnumDeviceInterfaces(device_info, nullptr, &hid_guid, index, &interface_data)) {
            break;
        }

        DWORD required_size = 0;
        SetupDiGetDeviceInterfaceDetailW(
            device_info,
            &interface_data,
            nullptr,
            0,
            &required_size,
            nullptr
        );
        if (required_size == 0) {
            continue;
        }

        std::vector<uint8_t> detail_buffer(required_size, 0);
        PSP_DEVICE_INTERFACE_DETAIL_DATA_W detail_data =
            reinterpret_cast<PSP_DEVICE_INTERFACE_DETAIL_DATA_W>(detail_buffer.data());
        detail_data->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);

        if (!SetupDiGetDeviceInterfaceDetailW(
                device_info,
                &interface_data,
                detail_data,
                required_size,
                nullptr,
                nullptr)) {
            continue;
        }

        HANDLE device_handle = CreateFileW(
            detail_data->DevicePath,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            nullptr,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            nullptr
        );
        if (device_handle == INVALID_HANDLE_VALUE) {
            continue;
        }

        if (device_matches_filters(device_handle) &&
            send_language_report_to_device(device_handle, is_hebrew)) {
            any_sent = true;
        }

        CloseHandle(device_handle);
    }

    SetupDiDestroyDeviceInfoList(device_info);
    return any_sent;
}

DWORD WINAPI worker_thread_proc(void *) {
    MSG msg = {};
    // Create message queue for WM_HOTKEY.
    PeekMessageW(&msg, nullptr, WM_USER, WM_USER, PM_NOREMOVE);

    bool f18_hotkey_registered = false;
    bool f22_hotkey_registered = false;
    bool f19_hotkey_registered = false;

    if (g_settings.enable_f18_hotkey && g_settings.shortcut_mode != ShortcutNone) {
        f18_hotkey_registered = RegisterHotKey(nullptr, kHotkeyIdF18, MOD_NOREPEAT, VK_F18) == TRUE;
        if (!f18_hotkey_registered && g_settings.debug_logging) {
            Wh_Log(L"RegisterHotKey(VK_F18) failed: %lu", GetLastError());
        }
    }

    if (g_settings.enable_f22_hotkey) {
        f22_hotkey_registered = RegisterHotKey(nullptr, kHotkeyIdF22, MOD_NOREPEAT, VK_F22) == TRUE;
        if (!f22_hotkey_registered && g_settings.debug_logging) {
            Wh_Log(L"RegisterHotKey(VK_F22) failed: %lu", GetLastError());
        }
    }

    if (g_settings.enable_f19_hotkey) {
        f19_hotkey_registered = RegisterHotKey(nullptr, kHotkeyIdF19, MOD_NOREPEAT, VK_F19) == TRUE;
        if (!f19_hotkey_registered && g_settings.debug_logging) {
            Wh_Log(L"RegisterHotKey(VK_F19) failed: %lu", GetLastError());
        }
    }

    bool have_last_state = false;
    bool last_is_hebrew = false;
    bool last_send_succeeded = false;
    DWORD next_unsent_retry_tick = 0;
    DWORD last_poll_tick = 0;

    while (WaitForSingleObject(g_stop_event, 0) == WAIT_TIMEOUT) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_HOTKEY) {
                if (g_is_synthesizing) {
                    continue;  // Ignore hotkeys during synthetic input
                }

                if (msg.wParam == kHotkeyIdF18) {
                    trigger_language_shortcut();
                    have_last_state = false;  // force immediate state refresh
                    last_send_succeeded = false;
                    next_unsent_retry_tick = 0;
                    last_poll_tick = 0;
                } else if (msg.wParam == kHotkeyIdF22) {
                    g_is_synthesizing = true;
                    send_ctrl_c();
                    fix_wrong_language_clipboard();
                    g_is_synthesizing = false;
                } else if (msg.wParam == kHotkeyIdF19) {
                    g_is_synthesizing = true;
                    send_ctrl_c();
                    cycle_case_clipboard();
                    g_is_synthesizing = false;
                }
            }
        }

        DWORD now = GetTickCount();
        if (last_poll_tick == 0 || now - last_poll_tick >= static_cast<DWORD>(g_settings.poll_interval_ms)) {
            last_poll_tick = now;

            bool is_hebrew = false;
            if (get_active_language_is_hebrew(&is_hebrew)) {
                bool state_changed = !have_last_state || is_hebrew != last_is_hebrew;
                bool should_retry_unsent = !state_changed && !last_send_succeeded &&
                                           (next_unsent_retry_tick == 0 || now >= next_unsent_retry_tick);
                if (state_changed || should_retry_unsent) {
                    bool sent = send_language_state_to_keyboards(is_hebrew);
                    last_is_hebrew = is_hebrew;
                    have_last_state = true;
                    last_send_succeeded = sent;
                    next_unsent_retry_tick = sent ? 0 : (now + kRetryWhenNotSentMs);

                    if (g_settings.debug_logging) {
                        if (sent) {
                            Wh_Log(L"Language sync sent: %ls", is_hebrew ? L"Hebrew" : L"English");
                        } else {
                            Wh_Log(L"Language sync not sent; retry scheduled in %lu ms", kRetryWhenNotSentMs);
                        }
                    }
                }
            }
        }

        Sleep(10);
    }

    if (f18_hotkey_registered) {
        UnregisterHotKey(nullptr, kHotkeyIdF18);
    }
    if (f22_hotkey_registered) {
        UnregisterHotKey(nullptr, kHotkeyIdF22);
    }
    if (f19_hotkey_registered) {
        UnregisterHotKey(nullptr, kHotkeyIdF19);
    }

    return 0;
}

bool start_worker() {
    g_stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!g_stop_event) {
        return false;
    }

    g_worker_thread = CreateThread(nullptr, 0, worker_thread_proc, nullptr, 0, nullptr);
    if (!g_worker_thread) {
        CloseHandle(g_stop_event);
        g_stop_event = nullptr;
        return false;
    }

    return true;
}

void stop_worker() {
    if (g_stop_event) {
        SetEvent(g_stop_event);
    }

    if (g_worker_thread) {
        WaitForSingleObject(g_worker_thread, 5000);
        CloseHandle(g_worker_thread);
        g_worker_thread = nullptr;
    }

    if (g_stop_event) {
        CloseHandle(g_stop_event);
        g_stop_event = nullptr;
    }
}

}  // namespace

BOOL Wh_ModInit() {
    load_settings();
    if (!start_worker()) {
        return FALSE;
    }
    return TRUE;
}

void Wh_ModUninit() {
    stop_worker();
}

void Wh_ModSettingsChanged() {
    stop_worker();
    load_settings();
    start_worker();
}
