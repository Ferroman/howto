"""Finds ffmpeg and ffprobe, and runs external programs.

A Homebrew ffmpeg on Linux is preferred to the one on PATH. On a machine with
firejail, /usr/local/bin/ffprobe can be a sandbox wrapper that exits with 127
when another program runs it, so PATH is the last place to look, not the
first. On a machine without Homebrew this changes nothing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import RunError

LINUXBREW_BIN = Path("/home/linuxbrew/.linuxbrew/bin")
DEFAULT_TIMEOUT = 10.0

# The key names that both stages accept: the same names Playwright presses and
# `xdotool key` accepts. The helper keeps its own copy of this list, because it
# imports nothing of howto, and a test compares the two.
KEY_NAMES = (
    "Enter",
    "Tab",
    "Escape",
    "Backspace",
    "space",
    "Control+a",
    "Control+c",
    "Control+v",
)


def action_timeout() -> float:
    """Seconds an element gets to appear."""
    try:
        seconds = float(os.environ.get("HOWTO_ACTION_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def run_tool(name: str, *args: str, timeout: float | None = None) -> str:
    """Runs a program, returning what it printed. A non-zero exit or a timeout is a failure."""
    try:
        done = subprocess.run([name, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RunError(f"`{name}` took more than {timeout:g} s") from None
    except FileNotFoundError:
        raise RunError(f"`{name}` is not installed") from None
    if done.returncode != 0:
        raise RunError(f"`{name}` exited with {done.returncode}: {done.stderr.strip() or 'no output'}")
    return done.stdout


def find_tool(name: str, env_var: str, *, brew_bin: Path = LINUXBREW_BIN) -> str:
    override = os.environ.get(env_var)
    if override:
        return override
    brewed = brew_bin / name
    if brewed.is_file() and os.access(brewed, os.X_OK):
        return str(brewed)
    found = shutil.which(name)
    if found:
        return found
    raise RunError(f"{name} not found: set {env_var} or install {name}")


def run(cmd: list[str], what: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=cwd)
    except FileNotFoundError:
        raise RunError(f"{what}: command not found: {cmd[0]}") from None
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise RunError(f"{what} failed (exit {proc.returncode}):\n{tail}")
    return proc
