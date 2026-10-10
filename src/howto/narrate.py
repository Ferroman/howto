"""Turns narration into clips: one WAV per sentence, spoken by `tts` and cached.

A clip's cache name is a hash of the command, the language and the sentence,
so changing one sentence speaks only that sentence again.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import wave
from dataclasses import dataclass
from pathlib import Path

from .errors import RunError
from .storyboard import Storyboard
from .tools import run

LANGUAGE = "en"
# Every cached clip has this format, so the narration track can be built by
# copying samples, with no resampling.
RATE, CHANNELS, WIDTH = 48_000, 1, 2


@dataclass(frozen=True)
class Clip:
    text: str
    path: Path
    duration: float


def tts_command() -> str:
    return os.environ.get("HOWTO_TTS") or "tts"


def clip_key(command: str, language: str, text: str) -> str:
    return hashlib.sha256("\x1f".join((command, language, text)).encode("utf-8")).hexdigest()


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError, OSError) as exc:
        raise RunError(f"{path}: not a readable WAV file: {exc}") from None


def speak(text: str, *, cache_dir: Path, command: str, ffmpeg: str) -> Clip:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = clip_key(command, LANGUAGE, text)
    final = cache_dir / f"{key}.wav"
    if not final.exists():
        raw = cache_dir / f".{key}.raw.wav"
        part = cache_dir / f".{key}.part.wav"
        try:
            run([*shlex.split(command), "-l", LANGUAGE, "-o", str(raw), text], "tts")
            if not raw.exists() or raw.stat().st_size == 0:
                raise RunError(f"tts wrote no audio for: {text!r}")
            run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw),
                 "-ar", str(RATE), "-ac", str(CHANNELS), "-c:a", "pcm_s16le", str(part)],
                "ffmpeg (clip conversion)",
            )
            os.replace(part, final)
        finally:
            raw.unlink(missing_ok=True)
            part.unlink(missing_ok=True)
    duration = wav_duration(final)
    if duration <= 0:
        final.unlink(missing_ok=True)
        raise RunError(f"tts produced an empty clip for: {text!r}")
    return Clip(text=text, path=final, duration=duration)


def narrate(
    storyboard: Storyboard, *, cache_dir: Path, ffmpeg: str, command: str | None = None
) -> dict[int, tuple[Clip, ...]]:
    """The clips of every step that has narration, keyed by step index."""
    command = command or tts_command()
    return {
        step.index: tuple(speak(sentence, cache_dir=cache_dir, command=command, ffmpeg=ffmpeg) for sentence in step.say)
        for step in storyboard.steps
        if step.say
    }
