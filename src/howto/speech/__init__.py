"""Speech commands that come with howto, and what the two share.

howto speaks through a command of its own choosing: `tts`, or the one that
HOWTO_TTS names. It calls that command in three ways:

    COMMAND -l en -o FILE TEXT                                     a sentence
    COMMAND -l en -o FILE --clone WAV --clone-text WORDS TEXT      a sentence in the voice of a clip
    COMMAND -l en -o FILE --design DESCRIPTION TEXT                a new voice, from a description

The command writes a WAV file and exits with 0. Any program that does this
can be the speech command. The two here do it for engines that run on the
machine itself:

    howto-tts-kokoro      Kokoro, through the kokoro-tts program. Preset voices.
    howto-tts-audiocpp    audio.cpp. Designs voices and clones them, with Qwen3-TTS.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


class SpeechError(Exception):
    """Ends a speech command. A wrong call is 2, as argparse has it, and anything else is 1."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Request:
    """What howto asks for in one call."""

    language: str
    out: Path
    text: str
    design: str | None = None
    clone: Path | None = None
    clone_text: str | None = None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SpeechError(message, 2)


def parser(prog: str, description: str) -> argparse.ArgumentParser:
    """The arguments that every speech command takes. An engine adds its own before parsing."""
    # The description is the module's own text, with a setup and a list of variables: it keeps its lines.
    made = _Parser(prog=prog, description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    made.add_argument("-l", "--lang", default="en", metavar="CODE", help="the language of the text (default en)")
    made.add_argument("-o", "--out", required=True, metavar="FILE", help="the WAV file to write")
    made.add_argument("--design", metavar="DESCRIPTION", help="make a new voice from a description of it")
    made.add_argument("--clone", metavar="WAV", help="speak in the voice of this clip")
    made.add_argument("--clone-text", metavar="WORDS", help="the words spoken in the clip")
    made.add_argument("text", nargs="+", metavar="TEXT", help="what to say")
    return made


def parse(made: argparse.ArgumentParser, argv: Sequence[str] | None) -> tuple[Request, argparse.Namespace]:
    args = made.parse_args(argv)
    if args.design and args.clone:
        raise SpeechError("--design makes a voice and --clone uses one: give one of them", 2)
    if args.clone_text and not args.clone:
        raise SpeechError("--clone-text needs --clone", 2)
    text = " ".join(args.text)
    if not text.strip():
        raise SpeechError("no text given", 2)
    request = Request(
        language=args.lang,
        out=Path(args.out),
        text=text,
        design=args.design,
        clone=Path(args.clone) if args.clone else None,
        clone_text=args.clone_text,
    )
    return request, args


def run_engine(argv: Sequence[str], out: Path, *, noise: tuple[str, ...] = ()) -> None:
    """Runs the engine, which must write `out`. Its own output is shown only when it fails.

    `noise` names the starts of lines that the engine prints on every run,
    so that they do not bury the line that says what went wrong.
    """
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise SpeechError(f"{argv[0]} cannot be run: {exc}") from None
    if done.returncode != 0:
        lines = [line for line in (done.stderr or done.stdout).splitlines() if not line.startswith(noise)]
        raise SpeechError("\n".join(lines[-20:]) or f"{argv[0]} failed", done.returncode)
    if not out.is_file() or out.stat().st_size == 0:
        raise SpeechError(f"{Path(argv[0]).name} wrote no audio to {out}")


def command(
    made: argparse.ArgumentParser,
    speak: Callable[[Request, argparse.Namespace, Mapping[str, str]], None],
    argv: Sequence[str] | None,
) -> int:
    """The body of a speech command: parse, speak, and turn an error into a message and an exit code."""
    try:
        request, args = parse(made, argv)
        speak(request, args, os.environ)
    except SpeechError as exc:
        print(f"{made.prog}: {exc}", file=sys.stderr)
        return exc.code
    return 0
