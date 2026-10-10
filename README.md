# howto

`howto` turns a storyboard, a YAML file of steps and narration, into a narrated how-to video of a web app: an MP4 with SRT and WebVTT subtitles. From the same kind of file it makes a short animated picture, a GIF and a WebP, for documentation. An AI agent writes the storyboard by following `skill/SKILL.md`. The tool itself calls no model.

The design, and the research behind it, are in the dotfiles repository: `~/p/.dotfiles/docs/superpowers/specs/2026-10-10-howto-video-design.md`.

## Requirements

- `uv`
- `ffmpeg` and `ffprobe`
- A `tts` command that accepts `-l en -o FILE TEXT`. `HOWTO_TTS` names another command with the same arguments.
- `img2webp`, from the `webp` package, for the WebP of an animated picture. Without it, `howto animate --format gif` still works.

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
| `howto animate STORYBOARD` | Writes a GIF and a WebP that loop without sound, next to the storyboard |

`skill/SKILL.md` is the reference for the storyboard format.

## Zoom

`zoom: 2` in a storyboard enlarges the picture around each control as it is used, and goes back to the whole page at the end of the step. `skill/SKILL.md` says how to write it.

- **The page enlarges itself.** The zoom is a transform on `<body>` that the browser animates and then draws again at the new size, so the text stays sharp. The recorder gives no more pixels than the page has, so cutting a part out of the recording afterwards would only blur it.
- **The pointer, the highlight and the note keep their size.** Playwright draws them outside `<body>`.
- **A page with parts pinned to the window is not zoomed.** A transform makes the body the box that `position: fixed` elements are placed in. On a page whose body is the window, which is how most apps are built, nothing moves. On a page that scrolls as a whole, a pinned header or a dialog would jump. The tool measures every element before it enlarges anything, keeps the picture wide when one of them would move, and says so in a `note:` line of the probe.
- **A probe zooms as well**, at once and with no waiting, so that it meets the page as the take will.

## Marks

Five actions draw on the picture instead of acting on the page: `box`, `circle`, `underline`, `arrow` and `spotlight`. Each names an element as `click` does. `skill/SKILL.md` says how to write them.

- **A mark is an overlay of the recorder**, like the note: an SVG in screen pixels, outside `<body>`. A stroke appears as if drawn because a CSS animation uncovers it. The recorder removes scripts from an overlay, so nothing in a mark runs one.
- **A mark goes around what the viewer sees of an element.** A locator by text often names a block as wide as the page while its words are not. An element that shows no box of its own (no background, border or shadow, and not a control or a picture) is therefore measured by what is in it.
- **A mark does not move with the page.** Whatever moves the picture takes the marks away first: a scroll, and a zoom that has to go somewhere else. While a mark is shown and the next target is already in the picture, the picture holds still.
- **A mark goes as a click, a key press or a choice from a list lands**, so that none is left on a page that no longer has its target, or in front of what the action changed. Marks that are still there at the end of a step's actions stay until the narration of the step ends.
- **An arrow comes from the emptiest side.** There are eight candidates, the one that faces the middle of the picture first. The page is asked how many points of each lie on a control, a picture or text, and the lowest count wins.
- **Marks fade through a custom property.** They are in a closed shadow root that the page cannot reach, but `--howto-marks` on `<html>` is inherited there, and the marks take their opacity from it.
- **A probe draws nothing.** It looks for the element of each mark and scrolls to it, as the take will.

Two details depend on the pinned Playwright release. Its stylesheet sets every `svg` in the overlay layer to a height of 0, so the marks carry their size as an inline style. And it wraps an overlay in an element that its own stylesheet does not position, so each mark brings a positioned box of its own.

## Animated pictures

`howto animate` performs a storyboard without narration and writes `NAME.gif` and `NAME.webp`. `--format` chooses one of them, and `--width` (960 by default) scales a wider picture down. `skill/SKILL.md` says how to write the storyboard.

- **The take is silent.** No `tts` is needed and no title card is shown. A step lasts as long as its actions and its `pause`, and a note and the marks explain what happens.
- **`crop` cuts the picture to one element.** A window of 1920 pixels scaled down to the width of a document has text of five pixels. A part of the window at its own size stays readable, which matters more than the file format. `howto render` ignores `crop`.
- **The cut is known during the take, not made afterwards.** The recorder films the whole window and ffmpeg cuts the part out. The browser is told the part first, so that an arrow does not leave it and the notes go where the picture has them. A cut made later loses the note, which lies at the bottom of the window.
- **The notes get a strip of their own.** A note laid on a small crop covers what it explains. So the notes are written in a dark strip under the crop, as tall as the longest of them needs, and the picture is the crop and the strip together. At the bottom of the window the strip goes above the crop. A crop as tall as the window leaves no room, and there the strip is the lowest part of the crop, shown only while a note is.
- **An arrow is shorter in a small picture**: four tenths of the picture's shorter side, and 150 pixels at most.
- **The crop is one fixed part of the window**, measured once after `setup`, with 12 pixels around the element. Its corner and its size are even numbers, because ffmpeg cuts a recording at even pixels only. A zoom moves the page under it, so a storyboard with both is refused.
- **A probe reports the crop**, and names each action or mark whose element is outside it. The author is often a model that cannot look at the picture.
- **Only the frames that differ are kept.** ffmpeg samples 12.5 frames a second and writes a frame when the picture changed, named by its number. The distance to the next number is the time the frame is shown, and both encoders are given that time. A GIF encoder that drops repeated frames itself loses the pause at the end of the loop, because its last frame has no successor to take a time from.
- **The GIF has one palette and no dither.** Dither noise differs from frame to frame, so no frame repeats: a GIF of 2.6 MB was 1.9 MB without it, and 1.3 MB with the repeated frames dropped as well. The WebP is lossy and about three times smaller.
- **The first 0.2 seconds of the recording are left out.** The recorder takes its first frame before its overlays are drawn, so the strip is missing from it, and the picture would flash at every loop.

The pause was measured on a take of 9 seconds: with ffmpeg dropping the repeated frames, the GIF played for 6.9 seconds.

## Stopping a run

Ctrl+C stops a probe, a render or an animation, runs the storyboard's `cleanup`, and exits with 130. The signal is acted on between browser calls, so the stop can take as long as one action's timeout.

A termination signal (SIGTERM) does the same when it is sent to `howto` alone. Sent to the whole process group, as a shell's time limit often does, it also reaches Playwright, which closes the browser at once: the run still ends with 130 and leaves no files behind, but `cleanup` cannot run. Run `howto probe` on the storyboard afterwards, because a probe ends with `cleanup`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOWTO_TTS` | `tts` | The speech command |
| `HOWTO_FFMPEG`, `HOWTO_FFPROBE` | linuxbrew, then `PATH` | The ffmpeg programs |
| `HOWTO_IMG2WEBP` | linuxbrew, then `PATH` | The program that writes an animated WebP |
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
| `src/howto/zoom.py` | Which part of the page a zoom shows, and which part a crop cuts out |
| `src/howto/marks.py` | Where each mark is drawn, and its SVG |
| `src/howto/probe.py` | The probe report |
| `src/howto/assemble.py` | The narration track, ffmpeg and the subtitles |
| `src/howto/animation.py` | The GIF and the WebP of an animated picture |
| `src/howto/cli.py` | The commands |
| `spike/` | The measurements made before the build |
