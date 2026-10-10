"""Voices for the narration: a short clip of a speaker, and the words in it.

A voice is made once, from a description, and every sentence of a video is
then spoken as a clone of that clip. The speech model cannot be asked for the
description again for each sentence: it invents a new speaker every time, so
a video would change its narrator from sentence to sentence.

A voice NAME is two files in the voices directory: NAME.wav, and NAME.yaml
with the `text` spoken in the clip and the `description` it was made from.
A clip recorded elsewhere works as well, with its words in `text`.
"""
from __future__ import annotations

import hashlib
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import RunError
from .narrate import LANGUAGE, wav_duration
from .storyboard import read_yaml
from .tools import run

# What a new voice says when no words are given. Two plain sentences: a clip
# of a few seconds is enough to clone from, and this is how a video sounds.
SAMPLE = "This is the voice of the how-to videos. I will show each step slowly, so that it is easy to follow."


@dataclass(frozen=True)
class Voice:
    name: str
    clip: Path
    text: str
    description: str = ""

    @property
    def key(self) -> str:
        """Changes when the clip or its words change, and with nothing else. Part of a spoken clip's cache name."""
        digest = hashlib.sha256(self.clip.read_bytes())
        digest.update(b"\x1f" + self.text.encode("utf-8"))
        return digest.hexdigest()


def _files(directory: Path, name: str) -> tuple[Path, Path]:
    return directory / f"{name}.wav", directory / f"{name}.yaml"


def exists(directory: Path, name: str) -> bool:
    return all(path.is_file() for path in _files(directory, name))


def load(directory: Path, name: str) -> Voice:
    clip, note = _files(directory, name)
    if not exists(directory, name):
        raise RunError(f'voice `{name}` is not made yet. Make it with: howto voice {name} "a description of the voice"')
    try:
        data = read_yaml(note.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise RunError(f"{note}: cannot be read: {exc}") from None
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise RunError(f"{note}: `text` must hold the words spoken in {clip.name}")
    description = data.get("description")
    if wav_duration(clip) <= 0:
        raise RunError(f"{clip}: the clip is empty")
    return Voice(name=name, clip=clip, text=text, description=description if isinstance(description, str) else "")


def listing(directory: Path) -> list[Voice]:
    """Every voice in the directory, by name."""
    if not directory.is_dir():
        return []
    names = sorted(path.stem for path in directory.glob("*.yaml") if not path.name.startswith("."))
    return [load(directory, name) for name in names if exists(directory, name)]


def design(
    name: str, description: str, *, directory: Path, command: str, text: str = SAMPLE, replace: bool = False
) -> Voice:
    """Has the speech command make a voice from a description. An earlier voice of that name stays unless `replace`."""
    clip, note = _files(directory, name)
    if exists(directory, name) and not replace:
        raise RunError(
            f"voice `{name}` exists. `--replace` makes it anew, and every video that names it then speaks differently"
        )
    directory.mkdir(parents=True, exist_ok=True)
    new_clip = directory / f".{name}.part.wav"
    new_note = directory / f".{name}.part.yaml"
    try:
        run([*shlex.split(command), "-l", LANGUAGE, "-o", str(new_clip), "--design", description, text], "tts")
        if not new_clip.exists() or new_clip.stat().st_size == 0:
            raise RunError(f"tts wrote no audio for the voice `{name}`")
        if wav_duration(new_clip) <= 0:
            raise RunError(f"tts produced an empty clip for the voice `{name}`")
        new_note.write_text(
            yaml.safe_dump({"description": description, "text": text}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(new_clip, clip)
        os.replace(new_note, note)
    finally:
        new_clip.unlink(missing_ok=True)
        new_note.unlink(missing_ok=True)
    return load(directory, name)
