"""howto-tts-kokoro: speaks with Kokoro, through the kokoro-tts program.

Kokoro is small and quick on a processor alone, and it has preset voices
only. It cannot design a voice or clone one, so it does not serve a
storyboard's `voice:`. The voice is an option of this command:

    HOWTO_TTS="howto-tts-kokoro --voice am_michael"

It is an option and not a variable because howto names a spoken clip after
the command that spoke it. Another voice is then another clip, and nothing
stale is played. `kokoro-tts --help-voices` lists the voices.

Set up once. kokoro-tts needs the PortAudio library, which a desktop system
usually has, and a server or a container usually lacks:

    sudo apt install libportaudio2        # Debian and Ubuntu, when it is missing
    uv tool install --python 3.12 kokoro-tts
    curl -L --create-dirs -o ~/.local/share/howto/kokoro/kokoro-v1.0.onnx \\
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
    curl -L --create-dirs -o ~/.local/share/howto/kokoro/voices-v1.0.bin \\
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

Environment:

    KOKORO_DIR    the folder with the two model files (default: `kokoro` in howto's data folder)
    KOKORO_TTS    the program (default kokoro-tts)
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from . import Request, SpeechError, command, parser, run_engine

PROG = "howto-tts-kokoro"
VOICE = "af_heart"
MODEL, VOICES = "kokoro-v1.0.onnx", "voices-v1.0.bin"
FILES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
# kokoro-tts has its own names for languages. A code that is not here is passed on as it is.
LANGUAGES = {"en": "en-us"}


def folder(env: Mapping[str, str]) -> Path:
    if env.get("KOKORO_DIR"):
        return Path(env["KOKORO_DIR"]).expanduser()
    data = Path(env["HOWTO_DATA_DIR"]).expanduser() if env.get("HOWTO_DATA_DIR") else Path.home() / ".local/share/howto"
    return data / "kokoro"


def build(request: Request, voice: str, env: Mapping[str, str], text_file: Path) -> list[str]:
    """The call of kokoro-tts for one request. It reads the text from a file."""
    if request.design or request.clone:
        raise SpeechError(
            "Kokoro has preset voices only. Choose one with `--voice`, as in "
            f'HOWTO_TTS="{PROG} --voice am_michael". A storyboard\'s `voice:` needs a speech command '
            "that can clone, such as howto-tts-audiocpp",
            2,
        )
    name = env.get("KOKORO_TTS") or "kokoro-tts"
    program = shutil.which(name, path=env.get("PATH"))
    if program is None:
        raise SpeechError(f"`{name}` is not installed. Install it with: uv tool install --python 3.12 kokoro-tts")
    models = folder(env)
    for file in (MODEL, VOICES):
        if not (models / file).is_file():
            raise SpeechError(
                f"{models / file} is missing. Download it with: "
                f"curl -L --create-dirs -o {models / file} {FILES_URL}/{file}"
            )
    return [
        program, str(text_file), str(request.out),
        "--lang", LANGUAGES.get(request.language, request.language),
        "--voice", voice, "--format", "wav",
        "--model", str(models / MODEL), "--voices", str(models / VOICES),
    ]


def speak(request: Request, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="howto-kokoro-") as work:
        text_file = Path(work) / "text.txt"
        argv = build(request, args.voice, env, text_file)
        text_file.write_text(request.text, encoding="utf-8")
        try:
            run_engine(argv, request.out)
        except SpeechError as exc:
            # kokoro-tts loads the library that plays sound as it starts, although it only writes a file here.
            if "PortAudio library not found" in str(exc):
                raise SpeechError(
                    "kokoro-tts needs the PortAudio library, which this system lacks. "
                    "On Debian or Ubuntu, install it with: sudo apt install libportaudio2",
                    exc.code,
                ) from None
            raise


def main(argv: Sequence[str] | None = None) -> int:
    made = parser(PROG, __doc__)
    made.add_argument("--voice", default=VOICE, metavar="NAME", help=f"a Kokoro voice (default {VOICE})")
    return command(made, speak, argv)


if __name__ == "__main__":
    raise SystemExit(main())
