"""Finds ffmpeg and ffprobe, and runs external programs.

On the workstation /usr/local/bin/ffprobe is a firejail wrapper that exits
with 127, so PATH is the last place to look, not the first.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import RunError

LINUXBREW_BIN = Path("/home/linuxbrew/.linuxbrew/bin")


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


def run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError:
        raise RunError(f"{what}: command not found: {cmd[0]}") from None
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise RunError(f"{what} failed (exit {proc.returncode}):\n{tail}")
    return proc
