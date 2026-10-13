"""The names of keys. A storyboard uses the ones a web storyboard has, and xdotool the ones of X."""
from __future__ import annotations

import re

NAMES = {
    "Enter": "Return",
    "Escape": "Escape",
    "Tab": "Tab",
    "Backspace": "BackSpace",
    "Delete": "Delete",
    "Insert": "Insert",
    "Space": "space",
    "space": "space",
    " ": "space",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "PageUp": "Prior",
    "PageDown": "Next",
    "Home": "Home",
    "End": "End",
    "Control": "ctrl",
    "ControlOrMeta": "ctrl",
    "Shift": "shift",
    "Alt": "alt",
    "Meta": "super",
}
HELD = ("ctrl", "shift", "alt", "super")
SIGNS = {
    "+": "plus", "-": "minus", "=": "equal", ".": "period", ",": "comma", "/": "slash", "\\": "backslash",
    ";": "semicolon", "'": "apostrophe", "`": "grave", "[": "bracketleft", "]": "bracketright",
}
FUNCTION_KEY = re.compile(r"F([1-9]|1[0-2])")


class BadKey(ValueError):
    """What a storyboard wrote is not a key or a chord."""


def _name(part: str) -> str:
    if part in NAMES:
        return NAMES[part]
    if FUNCTION_KEY.fullmatch(part):
        return part
    if len(part) == 1:
        if part in SIGNS:
            return SIGNS[part]
        return part if part.isascii() and part.isalnum() else f"U{ord(part):04X}"
    raise BadKey(f"`{part}` is not a key: use a name such as Enter, Escape, Tab, ArrowDown, PageDown, F5, or one character")


def chord(written: str) -> str:
    """A key or a chord as xdotool takes it: `Control+S` becomes `ctrl+s`."""
    if written.endswith("++"):
        parts = [*written[:-2].split("+"), "+"]
    elif written == "+":
        parts = ["+"]
    else:
        parts = written.split("+")
    if not written or "" in parts:
        raise BadKey(f"`{written}` is not a key: use a name such as Enter, or a chord such as Control+S")
    found = [_name(part) for part in parts]
    held, key = found[:-1], found[-1]
    if key in HELD or any(name not in HELD for name in held):
        raise BadKey(f"`{written}`: a chord is Control, Shift, Alt or Meta, then one key, as in Control+S")
    if held and len(key) == 1 and key.isalpha():
        # xdotool holds Shift for a capital letter by itself, which would make Control+Shift+S of Control+S.
        key = key.lower()
    return "+".join([*held, key])
