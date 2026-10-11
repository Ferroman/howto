# Setting up speech for howto

This page is for the person who wants narration. A narrated video needs a speech command. An animated picture and a probe need none. [The README](../README.md) says how to install `howto`, and [the guide](guide.md) how to make a video.

## The speech command

`howto` speaks through a command. It runs `tts` when `HOWTO_TTS` is not set, and it calls the command in three ways:

```
COMMAND -l en -o FILE TEXT                                    a sentence
COMMAND -l en -o FILE --clone WAV --clone-text WORDS TEXT     a sentence in the voice of a clip
COMMAND -l en -o FILE --design DESCRIPTION TEXT               a new voice, from a description
```

The command writes a WAV file and exits with 0. Any program that does this can be the speech command, and the first form alone is enough for a video without a `voice:`. Two commands come with `howto`:

| Command | Engine | Voices | Needs |
|---|---|---|---|
| `howto-tts-kokoro` | [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), through [kokoro-tts](https://github.com/nazdridoy/kokoro-tts) | Preset voices, chosen with `--voice` | A processor, and 350 MB of models |
| `howto-tts-audiocpp` | [audio.cpp](https://github.com/0xShug0/audio.cpp) | One plain voice, and voices that you design | A graphics card helps. 0.4 GB of models, and 5.3 GB more for voices |

## Kokoro

```bash
sudo apt install libportaudio2        # Debian and Ubuntu, when it is missing
uv tool install --python 3.12 kokoro-tts
curl -L --create-dirs -o ~/.local/share/howto/kokoro/kokoro-v1.0.onnx \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L --create-dirs -o ~/.local/share/howto/kokoro/voices-v1.0.bin \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
export HOWTO_TTS=howto-tts-kokoro
```

`kokoro-tts` needs the PortAudio library. A desktop system usually has it, and a server or a container usually lacks it.

To have another voice, name it in the command: `HOWTO_TTS="howto-tts-kokoro --voice am_michael"`. `kokoro-tts --help-voices` lists them. The voice is an option because `howto` names each spoken clip after the command that spoke it, so another voice is spoken anew and nothing stale is played.

On a 16-core processor a sentence takes about two seconds, nearly all of it the start of the program: 20 seconds of speech took five.

## audio.cpp

Download a release of [audio.cpp](https://github.com/0xShug0/audio.cpp/releases) for your machine and the models from [its model repository](https://huggingface.co/audio-cpp/audio.cpp-gguf), into one folder:

| File under the folder | Used for | Size |
|---|---|---|
| `audiocpp_cli` | Everything | |
| `models/Supertonic-3-GGUF/supertonic-3-q8_0.gguf` | A sentence without a `voice:` | 0.4 GB |
| `models/Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf` | A sentence in a voice | 2.6 GB |
| `models/Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf` | `howto voice`, which makes a voice | 2.7 GB |

```bash
export AUDIOCPP_DIR=~/audio.cpp
export HOWTO_TTS=howto-tts-audiocpp
```

The engine chooses between the processor and a graphics card by itself. `AUDIOCPP_BACKEND=cpu AUDIOCPP_THREADS=16` keeps it on the processor, which is faster than a weak graphics card: a cloned voice took two to three seconds for a second of speech on 16 cores, and four on integrated graphics. `howto-tts-audiocpp --help` lists the other variables.

## Voices

With a speech command that can design and clone, which `howto-tts-audiocpp` can, you describe a narrator in plain words:

```bash
howto voice narrator "A calm, friendly man in his thirties with a clear American accent"
```

Listen to `~/.local/share/howto/voices/narrator.wav`, and run it again with `--replace` and other words until it is right. Then put `voice: narrator` at the top of a storyboard. [This video of a diagram editor](media/diagc-explore.mp4) is narrated in such a voice.

The voice is designed once, as a short clip, and every sentence is then a clone of that clip. Sending the description with each sentence does not work: the model invents a new speaker every time. A recording of a real speaker works as well: put a few seconds in `NAME.wav` and its words in `NAME.yaml` as `text: ...`.

[The guide](guide.md#choose-a-voice) says how to name a voice in a storyboard, and what its first render costs.

## The models have licences of their own

`howto` is MIT, and it contains no model. Kokoro and Qwen3-TTS are Apache-2.0. Supertonic 3 is under an OpenRAIL-M licence with use restrictions. Read the licence of the model you choose.
