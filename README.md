# howto

[![tests](https://github.com/Ferroman/howto/actions/workflows/test.yml/badge.svg)](https://github.com/Ferroman/howto/actions/workflows/test.yml)

`howto` turns a storyboard, a YAML file of steps and narration, into a narrated how-to video of a web app: an MP4 with SRT and WebVTT subtitles. From the same kind of file it makes a short animated picture, a GIF and a WebP, to illustrate documentation.

![Inviting a teammate: an animated picture made by howto](docs/media/invite-picture.gif)

`howto animate` made that picture from [examples/invite-picture.yaml](examples/invite-picture.yaml). `howto render` made [this narrated video](docs/media/invite.mp4) from [examples/invite.yaml](examples/invite.yaml). On [the site](https://ferroman.github.io/howto/) the video plays in the page.

- **A storyboard is the only input.** It names each control as a person would, `{role: button, name: Invite}`, and says what to tell the viewer at each step. `howto` performs it in a browser of its own, records it and speaks the narration.
- **An AI agent can write the storyboard.** [skill/SKILL.md](skill/SKILL.md) teaches an agent the format. The agent explores your app with `howto probe`, which prints a text outline of the page, so a model without image input is enough. `howto` itself calls no model.
- **Everything runs on your machine.** The browser is Playwright's Chromium. The speech comes from a command that you choose, and two come with `howto`.
- **A change is cheap.** Each sentence is spoken once and kept, so a changed sentence costs one sentence, and a render is repeatable.

## Status

This is version 0.1.

- **Linux only so far.** It is developed on an Ubuntu 24.04 system, and the tests run on Ubuntu. macOS and Windows are untried.
- **Narration is in English.**
- **Web apps only.** Whatever runs in a browser tab can be filmed. Desktop programs cannot.

## How it fits together

![howto reads a storyboard that you or an agent wrote. On your machine it runs Chromium, a speech command, ffmpeg and img2webp, and they give a narrated video or an animated picture.](.diagrams/static/context.png)

`howto` does its work through other programs, and all of them run on your machine.

- **Chromium** performs the storyboard on your web app and records it.
- **The speech command** speaks each sentence of the narration. An animated picture needs none.
- **ffmpeg**, with `ffprobe`, joins the recording and the narration into the video, and builds the GIF.
- **`img2webp`** encodes the WebP, and nothing else needs it.

The agent is optional: a person writes a storyboard in the same way, with `howto probe`. [docs/internals.md](docs/internals.md#the-parts) shows the parts inside `howto`.

## Requirements

- [`uv`](https://docs.astral.sh/uv/), which builds the Python environment
- `ffmpeg` and `ffprobe`
- `img2webp`, from the `webp` package, for the WebP of an animated picture. Without it, `howto animate --format gif` still works
- A speech command, for narration. See [Speech](#speech). An animated picture needs none

## Install

```bash
git clone https://github.com/Ferroman/howto.git
cd howto
bash install.sh
```

The installer builds `~/.local/share/howto/venv`, downloads Playwright's Chromium (about 300 MB), and links three commands into `~/.local/bin`: `howto`, `howto-tts-kokoro` and `howto-tts-audiocpp`. When Claude Code is installed, it also links the skill into `~/.claude/skills`. It is safe to run again.

`~/.local/bin` has to be on your `PATH`. On a system that lacks the libraries Chromium needs, run `~/.local/share/howto/venv/bin/playwright install-deps chromium` once.

## Quick start

The repository has a small demo page and two storyboards for it. Serve the page in one terminal:

```bash
python3 -m http.server 8000 --directory examples/site
```

In another, make the animated picture. It needs no speech:

```bash
howto animate examples/invite-picture.yaml
```

```
examples/invite-picture.gif  820x472  9.4 s  564 KB
examples/invite-picture.webp  820x472  9.4 s  240 KB
```

For the narrated video, set up a speech command first. The quickest is Kokoro, described [below](#kokoro):

```bash
export HOWTO_TTS=howto-tts-kokoro
howto render examples/invite.yaml
```

```
examples/invite.mp4
examples/invite.srt
examples/invite.vtt
```

## A storyboard

```yaml
title: Invite a teammate
url: http://localhost:8000/
steps:
  - chapter: Invite a teammate
  - say: Open Settings, where the members of the workspace are managed.
    do:
      - click: {role: button, name: Settings}
  - say: Type your teammate's email address, and choose a role.
    do:
      - fill: {label: Email address, value: sam@example.com}
      - select: {label: Role, option: Admin}
  - say: Then press Invite. Your teammate appears in the list of members.
    do:
      - arrow: {role: button, name: Invite, note: Sends the invitation}
      - click: {role: button, name: Invite}
```

- **`say`** is the narration of a step, and **`do`** is what happens on the page while it is spoken.
- **`howto probe FILE`** runs the steps without recording and reports the first one that fails, with an outline of the page as it is then. That is how a storyboard is written, by a person or by an agent: probe, correct, probe again.
- **Marks** point at things: `box`, `circle`, `underline`, `arrow` and `spotlight`.
- **`zoom: 2`** enlarges the page around each control as it is used.
- **`crop`** cuts an animated picture to one part of the page.

[skill/SKILL.md](skill/SKILL.md) is the full reference of the format. [docs/guide.md](docs/guide.md) is the guide for a person.

## Let an agent write it

The skill in `skill/` is written for an AI coding agent. The installer links it for Claude Code. Give any other agent the file `skill/SKILL.md`. Then ask in one sentence:

> Make a how-to video: invite a teammate. Start at https://app.example.com, profile demo.

The agent writes the storyboard, probes it until every step works, and renders it.

**Every probe and every take performs its actions for real**, and an agent probes many times. Point it at a demo workspace or a test account, never at real data. For an app that needs a sign-in, run `howto login NAME URL` once: a browser window opens, you sign in, and the session stays in a profile that a storyboard names with `profile: NAME`.

## Speech

`howto` speaks through a command, and `HOWTO_TTS` names it. Two commands come with `howto`:

| Command | Engine | Voices | Needs |
|---|---|---|---|
| `howto-tts-kokoro` | [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), through [kokoro-tts](https://github.com/nazdridoy/kokoro-tts) | Preset voices, chosen with `--voice` | A processor, and 350 MB of models |
| `howto-tts-audiocpp` | [audio.cpp](https://github.com/0xShug0/audio.cpp) | One plain voice, and voices that you design | A graphics card helps. 0.4 GB of models, and 5.3 GB more for voices |

### Kokoro

Kokoro is the quickest to set up:

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

[docs/speech.md](docs/speech.md) has the rest:

- [Kokoro](docs/speech.md#kokoro): how to have another of its voices, and how fast it speaks.
- [audio.cpp](docs/speech.md#audiocpp): how to set it up, and which models to download.
- [Voices](docs/speech.md#voices): how to make a narrator from a description.
- [The speech command](docs/speech.md#the-speech-command): how `howto` calls it, so that a program of your own can speak.
- [The licences of the models](docs/speech.md#the-models-have-licences-of-their-own).

## Commands

| Command | What it does |
|---|---|
| `howto probe STORYBOARD` | Runs the steps with no recording and prints an outline of the page |
| `howto render STORYBOARD` | Writes `NAME.mp4`, `NAME.srt` and `NAME.vtt` next to the storyboard |
| `howto animate STORYBOARD` | Writes `NAME.gif` and `NAME.webp` next to the storyboard. They loop without sound |
| `howto narrate STORYBOARD` | Speaks the narration only and writes `NAME.narration.wav` next to the storyboard |
| `howto voice NAME DESCRIPTION` | Makes a voice from a description. `howto voice` lists the voices, and `howto voice NAME` shows one |
| `howto login PROFILE URL` | Opens a browser window for a person to sign in. The session stays in the profile |

The options:

| Option | Command | Meaning |
|---|---|---|
| `--until N` | `probe` | Stops after step N, so that the outline is of an earlier page |
| `--within LOCATOR` | `probe` | Limits the outline to one element, for example `--within '{role: dialog}'` |
| `--max-chars N` | `probe` | Cuts the outline off at N characters. The default is 20000 |
| `--show` | `probe` | Uses a visible browser window |
| `--out DIR` | `render`, `animate`, `narrate` | Where the files go. The default is next to the storyboard |
| `--keep-work` | `render`, `animate` | Keeps the intermediate files of the take, in a folder under `~/.cache/howto/work` |
| `--format gif`, `--format webp` | `animate` | Writes one of the two. The default is both |
| `--width N` | `animate` | Scales a picture wider than N pixels down to N. The default is 960 |
| `--text WORDS` | `voice` | What the voice says in its clip. The default is two sentences of a video |
| `--replace` | `voice` | Makes an existing voice anew |

The exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | A step, the narration or the assembly failed, or a program or a voice that the command needs is missing |
| 2 | The storyboard or the command line is wrong. The message names the step and the field |
| 130 | The run was stopped with Ctrl+C or a termination signal |

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOWTO_TTS` | `tts` | The speech command, with its options |
| `HOWTO_FFMPEG`, `HOWTO_FFPROBE` | Homebrew on Linux, then `PATH` | The ffmpeg programs |
| `HOWTO_IMG2WEBP` | Homebrew on Linux, then `PATH` | The program that writes an animated WebP |
| `HOWTO_ACTION_TIMEOUT` | `10` | Seconds an element gets to appear |
| `HOWTO_DATA_DIR` | `~/.local/share/howto` | Browser profiles, voices and Kokoro's models |
| `HOWTO_CACHE_DIR` | `~/.cache/howto` | Spoken clips and intermediate files |

## More

- [docs/guide.md](docs/guide.md): how to make a video and a picture, how to choose a voice, and the things that surprise.
- [docs/speech.md](docs/speech.md): how to set up a speech command, and how to make a voice.
- [docs/internals.md](docs/internals.md): how the zoom, the marks, the pictures and the voices work, and why.
- [skill/SKILL.md](skill/SKILL.md): the storyboard format, written for an agent.

## Tests

```bash
uv run --extra test playwright install chromium   # once
uv run --extra test pytest                        # unit tests and browser tests
bash install.test.sh                              # the installer, in a sandbox
```

Without Chromium the browser tests are skipped, which is not a pass.

## Licence

[MIT](LICENSE). `howto` contains no model, and the speech models have [licences of their own](docs/speech.md#the-models-have-licences-of-their-own).
