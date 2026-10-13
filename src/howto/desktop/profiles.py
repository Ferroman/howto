"""The profile of a desktop storyboard: a Docker volume that is the home of the app's user.

It keeps a sign-in, and what a first-run wizard asks. `howto login NAME
STORYBOARD` makes it. A storyboard without a profile gets a home that is new
for every run, so a take is repeatable.
"""
from __future__ import annotations

import subprocess

from ..errors import RunError

PREFIX = "howto-profile-"
# Where the volume is mounted: the home of the user `howto` of the base image.
HOME = "/home/howto"


def volume(profile: str) -> str:
    return f"{PREFIX}{profile}"


def _docker(docker: list[str], *arguments: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([*docker, *arguments], capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise RunError(f"cannot start Docker: {exc.strerror or exc}") from None


def _last(said: str) -> str:
    lines = said.strip().splitlines()
    return lines[-1] if lines else "it said nothing"


def exists(docker: list[str], profile: str) -> bool:
    """Whether the profile was made. Stops when Docker does not answer: that is not a missing profile."""
    proc = _docker(docker, "volume", "inspect", volume(profile))
    if proc.returncode == 0:
        return True
    if "no such volume" in proc.stderr.lower():
        return False
    raise RunError(f"Docker does not answer: {_last(proc.stderr)}")


def create(docker: list[str], profile: str) -> None:
    """Makes the volume of a profile. One that is there already is left as it is."""
    proc = _docker(docker, "volume", "create", volume(profile))
    if proc.returncode != 0:
        raise RunError(f"cannot make the profile {profile}: {_last(proc.stderr)}")
