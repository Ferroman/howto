# howto

`howto` turns a storyboard, a YAML file of steps and narration, into a narrated how-to video of a web app: an MP4 with SRT and WebVTT subtitles. An AI agent writes the storyboard by following `skill/SKILL.md`. The tool itself calls no model.

The design, and the research behind it, are in the dotfiles repository: `~/p/.dotfiles/docs/superpowers/specs/2026-10-10-howto-video-design.md`.

## Requirements

- `uv`
- `ffmpeg` and `ffprobe`
- A `tts` command that accepts `-l en -o FILE TEXT`. `HOWTO_TTS` names another command with the same arguments.

## Install

```bash
bash install.sh
```

The installer builds `~/.local/share/howto/venv`, downloads Playwright's Chromium, links `~/.local/bin/howto`, and links the skill into `~/.claude/skills`. It is safe to run again.

pi loads the skill from the same folder when its settings list it: `"skills": ["~/.claude/skills"]` in `~/.pi/agent/settings.json`. Do not also link the skill into `~/.pi/agent/skills`, because pi would then find it twice.

## Commands

| Command | What it does |
|---|---|
| `howto login PROFILE URL` | Opens a browser window for a person to sign in. The session stays in the profile |
| `howto probe STORYBOARD` | Runs the steps with no recording and prints an outline of the page |
| `howto narrate STORYBOARD` | Speaks the narration only |
| `howto render STORYBOARD` | Writes the video and the subtitles next to the storyboard |

`skill/SKILL.md` is the reference for the storyboard format.

## Zoom

`zoom: 2` in a storyboard enlarges the picture around each control as it is used, and goes back to the whole page at the end of the step. `skill/SKILL.md` says how to write it.

- **The page enlarges itself.** The zoom is a transform on `<body>` that the browser animates and then draws again at the new size, so the text stays sharp. The recorder gives no more pixels than the page has, so cutting a part out of the recording afterwards would only blur it.
- **The pointer, the highlight and the note keep their size.** Playwright draws them outside `<body>`.
- **A page with parts pinned to the window is not zoomed.** A transform makes the body the box that `position: fixed` elements are placed in. On a page whose body is the window, which is how most apps are built, nothing moves. On a page that scrolls as a whole, a pinned header or a dialog would jump. The tool measures every element before it enlarges anything, keeps the picture wide when one of them would move, and says so in a `note:` line of the probe.
- **A probe zooms as well**, at once and with no waiting, so that it meets the page as the take will.

## Stopping a run

Ctrl+C stops a probe or a render, runs the storyboard's `cleanup`, and exits with 130. The signal is acted on between browser calls, so the stop can take as long as one action's timeout.

A termination signal (SIGTERM) does the same when it is sent to `howto` alone. Sent to the whole process group, as a shell's time limit often does, it also reaches Playwright, which closes the browser at once: the run still ends with 130 and leaves no files behind, but `cleanup` cannot run. Run `howto probe` on the storyboard afterwards, because a probe ends with `cleanup`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOWTO_TTS` | `tts` | The speech command |
| `HOWTO_FFMPEG`, `HOWTO_FFPROBE` | linuxbrew, then `PATH` | The ffmpeg programs |
| `HOWTO_ACTION_TIMEOUT` | `10` | Seconds an element gets to appear |
| `HOWTO_DATA_DIR` | `~/.local/share/howto` | Browser profiles |
| `HOWTO_CACHE_DIR` | `~/.cache/howto` | Spoken clips and intermediate files |

## Tests

```bash
uv run --extra test pytest        # unit tests, and browser tests when Chromium is installed
bash install.test.sh              # the installer, in a sandbox
```

The browser tests need `uv run playwright install chromium` once. Without Chromium they are skipped, which is not a pass.

## Layout

| Path | Content |
|---|---|
| `src/howto/storyboard.py` | The storyboard format and its validation |
| `src/howto/narrate.py` | One cached clip per sentence |
| `src/howto/timeline.py` | The timing arithmetic |
| `src/howto/runner.py` | Setup, steps and cleanup, for a probe or a take |
| `src/howto/capture.py` | The Playwright browser. The only module that imports Playwright |
| `src/howto/zoom.py` | Which part of the page a zoom shows |
| `src/howto/probe.py` | The probe report |
| `src/howto/assemble.py` | The narration track, ffmpeg and the subtitles |
| `src/howto/cli.py` | The commands |
| `spike/` | The measurements made before the build |
