"""howto-tts-audiocpp: speaks with audio.cpp (https://github.com/0xShug0/audio.cpp).

A sentence is spoken by the plain model, Supertonic 3 unless another is
named. A voice is designed and cloned by Qwen3-TTS, which is why this command
can serve a storyboard's `voice:`.

The folder that AUDIOCPP_DIR names holds `audiocpp_cli` and a `models`
folder, laid out as the model repository has it:

    models/Supertonic-3-GGUF/supertonic-3-q8_0.gguf                                      a sentence
    models/Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf           --clone
    models/Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf  --design

Environment:

    AUDIOCPP_DIR           the folder above
    AUDIOCPP_BACKEND       cpu, cuda, vulkan, metal or best (default best: the engine chooses)
    AUDIOCPP_DEVICE        which graphics card, when there are several
    AUDIOCPP_THREADS       threads on the processor (the engine's default is 4)
    AUDIOCPP_FAMILY        the family of the plain model (default supertonic)
    AUDIOCPP_MODEL         the plain model, when it is another file
    AUDIOCPP_CLONE_MODEL   the Qwen3-TTS Base model, when it is another file
    AUDIOCPP_DESIGN_MODEL  the Qwen3-TTS VoiceDesign model, when it is another file
    AUDIOCPP_CLI           the program, when it is not AUDIOCPP_DIR/audiocpp_cli
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Mapping, Sequence

from . import Request, SpeechError, command, parser, run_engine

PROG = "howto-tts-audiocpp"
MODELS_URL = "https://huggingface.co/audio-cpp/audio.cpp-gguf"
PLAIN_MODEL = "models/Supertonic-3-GGUF/supertonic-3-q8_0.gguf"
CLONE_MODEL = "models/Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf"
DESIGN_MODEL = "models/Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf"
# Qwen3-TTS takes the language as a word. It refuses the code: `--language en`
# ends with "unsupported language".
QWEN_LANGUAGES = {
    "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
    "fr": "French", "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian",
}
# audio.cpp prints these on every run, also on one that works.
NOISE = ("ggml_vulkan:", "load_backend:")


def build(request: Request, env: Mapping[str, str]) -> list[str]:
    """The call of audiocpp_cli for one request."""

    def located(variable: str, default: str) -> Path:
        if env.get(variable):
            return Path(env[variable]).expanduser()
        if not env.get("AUDIOCPP_DIR"):
            raise SpeechError("AUDIOCPP_DIR is not set. It names the folder that holds audiocpp_cli and its models")
        return Path(env["AUDIOCPP_DIR"]).expanduser() / default

    if request.design or request.clone:
        # A voice changes the task, the model and the spelling of the language.
        language = QWEN_LANGUAGES.get(request.language)
        if language is None:
            known = ", ".join(QWEN_LANGUAGES)
            raise SpeechError(f"a Qwen voice speaks {known}, not `{request.language}`", 2)
        family = "qwen3_tts"
        if request.design:
            task, model = "vdes", located("AUDIOCPP_DESIGN_MODEL", DESIGN_MODEL)
        else:
            if not request.clone.is_file():
                raise SpeechError(f"clip not found: {request.clone}")
            task, model = "tts", located("AUDIOCPP_CLONE_MODEL", CLONE_MODEL)
    else:
        task, family, language = "tts", env.get("AUDIOCPP_FAMILY") or "supertonic", request.language
        model = located("AUDIOCPP_MODEL", PLAIN_MODEL)
    cli = located("AUDIOCPP_CLI", "audiocpp_cli")
    if not (cli.is_file() and os.access(cli, os.X_OK)):
        raise SpeechError(f"audiocpp_cli not found or not executable: {cli}")
    if not model.is_file():
        raise SpeechError(f"model not found: {model}. The models are at {MODELS_URL}")

    argv = [
        str(cli), "--task", task, "--family", family, "--model", str(model),
        "--backend", env.get("AUDIOCPP_BACKEND") or "best",
        "--language", language, "--text", request.text, "--out", str(request.out),
    ]
    for variable, flag in (("AUDIOCPP_DEVICE", "--device"), ("AUDIOCPP_THREADS", "--threads")):
        if env.get(variable):
            argv += [flag, env[variable]]
    if request.design:
        argv += ["--instruct", request.design]
    if request.clone:
        argv += ["--voice-ref", str(request.clone)]
    if request.clone_text:
        argv += ["--reference-text", request.clone_text]
    return argv


def speak(request: Request, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    run_engine(build(request, env), request.out, noise=NOISE)


def main(argv: Sequence[str] | None = None) -> int:
    return command(parser(PROG, __doc__), speak, argv)


if __name__ == "__main__":
    raise SystemExit(main())
