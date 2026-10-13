# How howto works

This page is for someone who changes `howto`, or who wants to know why it behaves as it does. [The README](../README.md) says how to use it, and [the guide](guide.md) how to make a video.

## The parts

![The parts of howto. storyboard.py hands the sentences to narrate.py and the steps to runner.py. runner.py drives capture.py for a web page, or desktop/stage.py for a desktop app, then hands its result to probe.py, assemble.py or animation.py, one for each command.](../.diagrams/static/parts.png)

An arrow is what one part hands to the next. `cli.py` calls the parts in this order and passes each result on. Along these arrows, only `runner.py` calls the next part itself: it drives a stage through the `Stage` protocol. `capture.py` is the stage of a web page, `desktop/stage.py` the stage of a desktop app, and the tests put `FakeStage` in their place.

The picture leaves out the helpers that several parts share: `timeline.py`, `zoom.py`, `marks.py`, `notes.py`, and `tools.py`, which runs the other programs.

`howto probe`, `howto render` and `howto animate` share most of the picture. A label that starts with the name of one of them marks a path that only that one takes. `howto narrate` goes as far as `narrate.py`, and then has `assemble.py` write the narration track alone.

The picture leaves out the helpers that several parts share: `timeline.py`, `zoom.py`, `marks.py`, and `tools.py`, which runs the other programs.

- **A storyboard is read as written.** `storyboard.py` validates it, and switches YAML's own reading of values off: `value: 02134` types 02134, and a button named `Yes` stays a name.
- **The narration is spoken first**, one clip for each sentence, by the speech command. A clip is named after a hash of the command, the language, the sentence and the voice, and kept in `~/.cache/howto/clips`. A speech failure therefore stops a render before the browser starts.
- **The browser is Playwright's Chromium**, and the recording is Playwright's own. `runner.py` performs the steps and waits for each sentence to end, so the picture and the narration are timed against one clock.
- **ffmpeg puts the two together**, and the subtitles are written from the same timeline.
- **A take has a work folder of its own** under `~/.cache/howto/work`, named after the storyboard. It holds the recording, and with it the narration track and the timeline of a video, or the frames of a picture. The folder is removed when the command ends. `--keep-work` keeps it, and a failed assembly keeps it as well and prints its path.
- **`playwright` is pinned to one release**, 1.63.0. Its recorder writes 25 frames a second with no option to change it. `capture.py` uses three details of that release that no option covers: it hides the label the recorder writes on every action, through an internal element name (`x-pw-title`); it removes an overlay by leaving its `with` block, because `close()` does nothing in that release's synchronous API; and the marks depend on its overlay stylesheet, as described below. Raise the pin on purpose and run the browser tests.

## Desktop apps

A storyboard with `app` in place of `url` films a Linux desktop app. `runner.py`, the narration and the timeline are the same: the desktop is a second stage. [The page for a person](desktop.md) says how to use it, and [spike/desktop/README.md](../spike/desktop/README.md) has the measurements that the build rests on.

- **The app runs in a container, on a monitor of its own.** The host needs Docker and nothing else: the monitor (Xvfb), the window manager, the recorder and the program that reads the screen are in the image. A hidden display on the host would need all of them as system packages, and would show the app the user's files. A virtual machine boots in tens of seconds, and a Linux app does not need one.
- **A helper in the container does the work.** The accessibility tree is on a bus inside the container, so a program there reads it, and the host needs no bindings. `howto` starts the helper with `docker run -i`, and the two exchange one JSON object on each line of Docker's stdin and stdout. Each request has a number and a time limit, and its reply carries the same number.
- **The life of the container is the life of the pipe.** When `howto` ends, however it ends, the pipe closes, the helper leaves, and Docker removes the container. The Docker command runs in a session of its own, so Ctrl+C in the terminal reaches `howto` alone, and `cleanup` still has a desktop to run on.
- **No folder of the host is mounted.** Docker from a snap cannot read a hidden folder such as `~/.cache`. The build of the image goes in as a tar on stdin, and a recording comes out as a tar on stdout, through `docker build -` and `docker cp`. That also works with a Docker on another machine.
- **The image carries its build.** The base image holds the helper, and the helper changes between two releases. So the image is labelled with the version of `howto` and a digest of the files it was built from, the helper says the same when it starts, and an image from another build is refused with the commands that build it again.
- **A locator has three layers.** The tree gives roles and names, as a web page does, and its roles are written with the names that a web outline has. The screen, read by tesseract, serves an app that publishes no tree, and the text of a canvas. A place in pixels serves what has no words. `howto` still calls no model: the reading of the screen is a program in the image.
- **Every request is in pixels of the picture.** The helper turns them into pixels of its monitor, and the boxes of the tree back.
- **Nothing is drawn on the monitor.** A note in a window on top of the app would be read off the screen by the probe, would compete with the app for the keyboard, and would need a web engine in the image. So `desktop/stage.py` writes a log of the take: each note, title card, mark and click with its time and its HTML. After the take, `overlay.py` draws them with the Chromium that `howto` has, as PNG pictures with transparency, one for each moment at which something changes, and ffmpeg lays them on the recording.
- **A mark, a ring and a title card appear at once.** Measured: Chromium drew the 321 pictures of a 60 s take in 13.1 s, over the 10 s mark, so nothing here is stepped frame by frame. When something does animate, `overlay.py` stops the animations of the page and sets them to the time of that picture, so the pictures do not depend on how fast the machine is. The HTML of a mark is the one the browser stage uses, so a mark looks the same in both kinds of video.
- **One clock times the picture and the narration.** A container shares the steady clock of its host. The helper says when ffmpeg took its first frame, the stage works out how much of the recording lies before the take, and the assembly leaves that head out.
- **A zoom is a cut of a larger recording.** An app cannot enlarge itself as a page can, and a cut from a recording of the picture's size would only blur. So the monitor of a storyboard that zooms has twice the size, the toolkits are told to draw at twice the scale, and `zoompan` cuts the part that is shown. The stage gives the corner of that part in whole pixels of the picture, which are even pixels of the recording: ffmpeg cuts there without a remainder, and a mark lies where its control is.
- **An arrow asks a screenshot where the screen is empty.** The browser stage asks the page what lies at each point of each candidate. The helper looks at a small area around each point: one whose pixels are all near its most common colour is empty. A gradient is empty too, and a canvas is not a special case.
- **A mark goes around the words of a label.** A label is often as wide as its window. The helper asks the app for the box of the label's characters, and takes it when it lies inside the label.
- **The palette of a desktop GIF is made from whole frames.** The palette of a web picture counts, where a frame differs from the one before, the colours that the frame before had there. The recording of a browser has noise in every frame, so every colour is counted sooner or later. The recording of a desktop has none, and what appears and stays to the end would be drawn in the nearest colour of the rest.
- **A profile is a Docker volume**, mounted as the home of the app's user. `howto login NAME STORYBOARD` starts the app on it and shows the monitor through noVNC, in howto's Chromium. Docker publishes that one port on 127.0.0.1, each run has a password of its own, and the window of `howto probe --show` goes to a server that takes no input.
- **The helper ends the app before the monitor**, and gives it five seconds, because an app writes its session down when it is told to end. For a desktop app the signal is acted on between two requests to the helper.

## Zoom

`zoom: 2` in a storyboard enlarges the picture around each control as it is used, and goes back to the whole page at the end of the step. [the skill](../skill/SKILL.md) says how to write it.

- **The page enlarges itself.** The zoom is a transform on `<body>` that the browser animates and then draws again at the new size, so the text stays sharp. The recorder gives no more pixels than the page has, so cutting a part out of the recording afterwards would only blur it.
- **The pointer, the highlight and the note keep their size.** Playwright draws them outside `<body>`.
- **A page with parts pinned to the window is not zoomed.** A transform makes the body the box that `position: fixed` elements are placed in. On a page whose body is the window, which is how most apps are built, nothing moves. On a page that scrolls as a whole, a pinned header or a dialog would jump. The tool measures every element before it enlarges anything, keeps the picture wide when one of them would move, and says so in a `note:` line of the probe.
- **A probe zooms as well**, at once and with no waiting, so that it meets the page as the take will.

## Marks

Five actions draw on the picture instead of acting on the page: `box`, `circle`, `underline`, `arrow` and `spotlight`. Each names an element as `click` does. [the skill](../skill/SKILL.md) says how to write them.

- **A mark is an overlay of the recorder**, like the note: an SVG in screen pixels, outside `<body>`. A stroke appears as if drawn because a CSS animation uncovers it. The recorder removes scripts from an overlay, so nothing in a mark runs one.
- **A mark goes around what the viewer sees of an element.** A locator by text often names a block as wide as the page while its words are not. An element that shows no box of its own (no background, border or shadow, and not a control or a picture) is therefore measured by what is in it.
- **A mark does not move with the page.** Whatever moves the picture takes the marks away first: a scroll, and a zoom that has to go somewhere else. While a mark is shown and the next target is already in the picture, the picture holds still.
- **A mark goes as a click, a key press or a choice from a list lands**, so that none is left on a page that no longer has its target, or in front of what the action changed. Marks that are still there at the end of a step's actions stay until the narration of the step ends.
- **An arrow comes from the emptiest side.** There are eight candidates, the one that faces the middle of the picture first. The page is asked how many points of each lie on a control, a picture or text, and the lowest count wins.
- **Marks fade through a custom property.** They are in a closed shadow root that the page cannot reach, but `--howto-marks` on `<html>` is inherited there, and the marks take their opacity from it.
- **A probe draws nothing.** It looks for the element of each mark and scrolls to it, as the take will.

Two details depend on the pinned Playwright release. Its stylesheet sets every `svg` in the overlay layer to a height of 0, so the marks carry their size as an inline style. And it wraps an overlay in an element that its own stylesheet does not position, so each mark brings a positioned box of its own.

## Animated pictures

`howto animate` performs a storyboard without narration and writes `NAME.gif` and `NAME.webp`. `--format` chooses one of them, and `--width` (960 by default) scales a wider picture down. [the skill](../skill/SKILL.md) says how to write the storyboard.

- **The take is silent.** No speech command is needed and no title card is shown. A step lasts as long as its actions and its `pause`, and a note and the marks explain what happens.
- **`crop` cuts the picture to one element.** A window of 1920 pixels scaled down to the width of a document has text of five pixels. A part of the window at its own size stays readable, which matters more than the file format. `howto render` ignores `crop`.
- **The cut is known during the take, not made afterwards.** The recorder films the whole window and ffmpeg cuts the part out. The browser is told the part first, so that an arrow does not leave it and the notes go where the picture has them. A cut made later loses the note, which lies at the bottom of the window.
- **The notes get a strip of their own.** A note laid on a small crop covers what it explains. So the notes are written in a dark strip under the crop, as tall as the longest of them needs, and the picture is the crop and the strip together. At the bottom of the window the strip goes above the crop. A crop as tall as the window leaves no room, and there the strip is the lowest part of the crop, shown only while a note is.
- **An arrow is shorter in a small picture**: four tenths of the picture's shorter side, and 150 pixels at most.
- **The crop is one fixed part of the window**, measured once after `setup`, with 12 pixels around the element. Its corner and its size are even numbers, because ffmpeg cuts a recording at even pixels only. A zoom moves the page under it, so a storyboard with both is refused.
- **A probe reports the crop**, and names each action or mark whose element is outside it. The author is often a model that cannot look at the picture.
- **Only the frames that differ are kept.** ffmpeg samples 12.5 frames a second and writes a frame when the picture changed, named by its number. The distance to the next number is the time the frame is shown, and both encoders are given that time. A GIF encoder that drops repeated frames itself loses the pause at the end of the loop, because its last frame has no successor to take a time from.
- **The GIF has one palette and no dither.** Dither noise differs from frame to frame, so no frame repeats: a GIF of 2.6 MB was 1.9 MB without it, and 1.3 MB with the repeated frames dropped as well. The WebP is lossy, and two to four times smaller: between 2.4 and 3.8 times in six pictures.
- **ffmpeg runs inside the folder of the frames**, and names the frames and their list without a path. It reads a `%` in the path of a frame as the place of a number, and release 6 puts the folder of the list in front of every frame in it. A work folder with a `%` in its name then broke the GIF on Ubuntu 24.04, while release 9 built it.
- **The first 0.2 seconds of the recording are left out.** The recorder takes its first frame before its overlays are drawn, so the strip is missing from it, and the picture would flash at every loop.

The pause was measured on a take of 9 seconds: with ffmpeg dropping the repeated frames, the GIF played for 6.9 seconds.

## Voices

A storyboard with `voice: NAME` is narrated in that voice. Without it, the speech command speaks in its own.

- **A voice is a clip and the words in it**: `NAME.wav` and `NAME.yaml` in `~/.local/share/howto/voices`. The clip says two sentences of a video, or the words of `--text`.
- **The voice is made once and cloned after that.** The speech command gets `--design DESCRIPTION` for the clip, and `--clone CLIP --clone-text WORDS` for every sentence of a video. Asking for the description again for each sentence does not work: a speech model that takes descriptions invents a speaker each time. Measured with Qwen3-TTS and a speaker-recognition model, where 1.0 is one speaker and two unrelated voices score 0.0 to 0.4: sentences designed one by one scored 0.10 to 0.44 against each other, and sentences cloned from one clip 0.64 to 0.84.
- **The voice is part of a clip's cache name**, as a hash of the clip and its words. A new voice speaks every sentence again, and going back to an earlier one speaks nothing.
- **`--replace` makes a voice anew.** Without it an existing voice stays, because every video that names it would speak differently.
- **A recording works too.** Put a few seconds of someone speaking in `NAME.wav` and the words in `NAME.yaml` as `text: ...`.
- **`howto animate` and `howto probe` do not need the voice.** Nothing is spoken in either.

## Stopping a run

Ctrl+C stops a probe, a render or an animation, runs the storyboard's `cleanup`, and exits with 130. The signal is acted on between browser calls, so the stop can take as long as one action's timeout.

A termination signal (SIGTERM) does the same when it is sent to `howto` alone. Sent to the whole process group, as a shell's time limit often does, it also reaches Playwright, which closes the browser at once: the run still ends with 130 and leaves no files behind, but `cleanup` cannot run. Run `howto probe` on the storyboard afterwards, because a probe ends with `cleanup`.

## Layout

| Path | Content |
|---|---|
| `src/howto/storyboard.py` | The storyboard format and its validation |
| `src/howto/narrate.py` | One cached clip per sentence |
| `src/howto/voices.py` | The voices: a clip to clone and the words in it |
| `src/howto/speech/` | The two speech commands that come with `howto`, for Kokoro and for audio.cpp |
| `src/howto/timeline.py` | The timing arithmetic |
| `src/howto/runner.py` | Setup, steps and cleanup, for a probe or a take |
| `src/howto/capture.py` | The stage of a web page: the Playwright browser |
| `src/howto/desktop/stage.py` | The stage of a desktop app: each action as requests to the helper, and the log of the take |
| `src/howto/desktop/link.py` | The Docker container and the JSON lines to its helper |
| `src/howto/desktop/helper/` | The helper. It runs in the container, and imports nothing of `howto` |
| `src/howto/desktop/image/Dockerfile` | The base image, `howto-desktop` |
| `src/howto/desktop/images.py` | Builds the base image, and tells an image of another build |
| `src/howto/desktop/profiles.py` | The Docker volume of a profile |
| `src/howto/desktop/takelog.py` | The log of a take: what lies over the picture and when, and the moves of its zooms |
| `src/howto/desktop/picture.py` | The ffmpeg filters of a desktop take: the zoom, and the overlay laid on |
| `src/howto/desktop/viewer.py` | The window on the monitor of a container |
| `src/howto/overlay.py` | Draws the notes, the cards and the marks of a desktop take as pictures |
| `src/howto/notes.py` | The HTML of a note, a title card and the ring of a click, for both stages |
| `src/howto/tools.py` | Finds ffmpeg, ffprobe, img2webp and Docker, and runs the other programs |

| `src/howto/zoom.py` | Which part of the page a zoom shows, and which part a crop cuts out |
| `src/howto/marks.py` | Where each mark is drawn, and its SVG |
| `src/howto/probe.py` | The probe report |
| `src/howto/assemble.py` | The narration track, ffmpeg and the subtitles |
| `src/howto/animation.py` | The GIF and the WebP of an animated picture |
| `src/howto/cli.py` | The commands |
| `src/howto/tools.py` | Finds ffmpeg, ffprobe and img2webp, and runs the other programs |
| `src/howto/errors.py` | The errors that end a command, each with its exit code |
| `skill/SKILL.md` | The storyboard format, written for an agent |
| `examples/` | A demo page and two storyboards for it, and in `desktop/` an app in an image with its storyboard |
| `spike/` | The measurements made before the build. `desktop/` has the ones of the desktop |
| `.diagrams/src/` | The diagrams of the README and of this page, as [diagc](https://github.com/Ferroman/diagc) sources. `diagc publish` writes the pictures to `.diagrams/static/` |
| `scripts/build_site.py` | Stages the documents for [the site](https://ferroman.github.io/howto/): their names there, their links, a player for each video and a link to each live diagram |
| `zensical.toml` | The name, the menu and the theme of the site, for Zensical |
