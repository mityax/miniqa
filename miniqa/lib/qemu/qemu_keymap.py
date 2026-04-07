from typing import Literal


QCODES = {
    # Taken from https://qemu-project.gitlab.io/qemu/interop/qemu-qmp-ref.html#enum-QMP-ui.QKeyCode
    "unmapped", "pause", "ro", "kp_comma", "kp_equals", "power", "hiragana", "henkan", "yen", "sleep", "wake",
    "audionext", "audioprev", "audiostop", "audioplay", "audiomute", "volumeup", "volumedown", "mediaselect",
    "mail", "calculator", "computer", "ac_home", "ac_back", "ac_forward", "ac_refresh", "ac_bookmarks", "muhenkan",
    "katakanahiragana", "lang1", "lang2", "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20", "f21", "f22",
    "f23", "f24", "shift", "shift_r", "alt", "alt_r", "ctrl", "ctrl_r", "menu", "esc", "1", "2", "3", "4", "5", "6",
    "7", "8", "9", "0", "minus", "equal", "backspace", "tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
    "bracket_left", "bracket_right", "ret", "a", "s", "d", "f", "g", "h", "j", "k", "l", "semicolon", "apostrophe",
    "grave_accent", "backslash", "z", "x", "c", "v", "b", "n", "m", "comma", "dot", "slash", "asterisk", "spc",
    "caps_lock", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "num_lock", "scroll_lock", "kp_divide",
    "kp_multiply", "kp_subtract", "kp_add", "kp_enter", "kp_decimal", "sysrq", "kp_0", "kp_1", "kp_2", "kp_3", "kp_4",
    "kp_5", "kp_6", "kp_7", "kp_8", "kp_9", "less", "f11", "f12", "print", "home", "pgup", "pgdn", "end", "left",
    "up", "down", "right", "insert", "delete", "stop", "again", "props", "undo", "front", "copy", "open", "paste",
    "find", "cut", "lf", "help", "meta_l", "meta_r", "compose",
}

SCANCODE_MAP = {
    # Letters
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C,

    # Numbers
    '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09,
    '9': 0x0A, '0': 0x0B,

    # Symbols
    '-': 0x0C, '=': 0x0D,
    '[': 0x1A, ']': 0x1B,
    ';': 0x27, "'": 0x28,
    '`': 0x29,
    '\\': 0x2B,
    ',': 0x33, '.': 0x34, '/': 0x35,

    # Control
    ' ': 0x39,
    '\n': 0x1C,  # Enter
    '\t': 0x0F,
}

SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4',
    '%': '5', '^': '6', '&': '7', '*': '8',
    '(': '9', ')': '0',

    '_': '-', '+': '=',
    '{': '[', '}': ']',
    ':': ';', '"': "'",
    '~': '`',
    '|': '\\',
    '<': ',', '>': '.', '?': '/',
}

SHIFT = 0x2A


def char_to_qemu_key_invocations(ch: str) -> list[tuple[Literal['up', 'down'], int]]:
    events = []

    # Uppercase letters → Shift + key
    if ch.isalpha() and ch.isupper():
        base = ch.lower()
        code = SCANCODE_MAP.get(base)
        if code is None:
            return []

        events.append(("down", SHIFT))
        events.append(("down", code))
        events.append(("up", code))
        events.append(("up", SHIFT))
        return events

    # Symbols requiring Shift
    if ch in SHIFT_MAP:
        base = SHIFT_MAP[ch]
        code = SCANCODE_MAP.get(base)
        if code is None:
            return []

        events.append(("down", SHIFT))
        events.append(("down", code))
        events.append(("up", code))
        events.append(("up", SHIFT))
        return events

    # Normal characters
    code = SCANCODE_MAP.get(ch)
    if code is not None:
        return [("down", code), ("up", code)]

    return []


def string_to_qemu_key_invocations(text: str) -> list[tuple[Literal['up', 'down'], int]]:
    result = []
    for ch in text:
        result.extend(char_to_qemu_key_invocations(ch))
    return result

