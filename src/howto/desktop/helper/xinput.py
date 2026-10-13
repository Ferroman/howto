"""The pointer and the keyboard of the monitor, through xdotool."""
from __future__ import annotations

import subprocess


def _xdotool(*arguments: str, text: str | None = None) -> str:
    proc = subprocess.run(["xdotool", *arguments], input=text, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"xdotool {arguments[0]}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def _xwininfo(*arguments: str) -> str:
    proc = subprocess.run(["xwininfo", *arguments], capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"xwininfo {arguments[0]}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def _location() -> dict[str, str]:
    return dict(line.split("=", 1) for line in _xdotool("getmouselocation", "--shell").split())


def position() -> tuple[int, int]:
    """Where the pointer is, in pixels of the monitor."""
    values = _location()
    return int(values["X"]), int(values["Y"])


def window_under_pointer() -> int:
    """The id of the window that the pointer is on. A menu that hangs over a window is a window of its own."""
    return int(_location().get("WINDOW", "0"))


def related(window: int) -> set[int]:
    """The ids of this window, of the windows above it and of the windows under it.

    The window the window manager lists is not always the window the pointer is on: GTK keeps a window
    of its own above the client window, so the client window is a child of the window under the pointer.
    """
    if window == 0:
        # The pointer is on the root window, and `xwininfo -id 0` asks for the pointer instead of a window.
        return {0}
    ids = set()
    current = window
    for _ in range(6):
        out = _xwininfo("-id", str(current), "-tree")
        ids.update(int(word, 16) for word in out.split() if word.startswith("0x"))
        line = next((line for line in out.splitlines() if "Parent window id" in line), "")
        word = next((part for part in line.split() if part.startswith("0x")), "")
        parent = int(word, 16) if word else 0
        if not parent or parent in ids:
            break
        current = parent
    return ids


def move(script: str) -> None:
    """Moves the pointer along a path that `pointer.script` wrote."""
    _xdotool("-", text=script)


def press(hold: float) -> None:
    """A click of the first button. With `hold`, the button stays down that long, so that a viewer sees it."""
    if hold > 0:
        _xdotool("-", text=f"mousedown 1\nsleep {hold:.3f}\nmouseup 1\n")
    else:
        _xdotool("click", "1")


def type_text(text: str, delay_ms: int) -> None:
    """Types text to whatever has the keyboard. The text goes in through stdin, so it may hold anything."""
    _xdotool("type", "--clearmodifiers", "--delay", str(delay_ms), "--file", "-", text=text)


def key(names: str) -> None:
    _xdotool("key", "--clearmodifiers", names)
