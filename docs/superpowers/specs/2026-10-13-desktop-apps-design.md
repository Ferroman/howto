# Desktop apps: design

> **Status: built.** This document is the design as it was approved, with the changes that the [measurements](#measurements-to-make-first) made. [docs/internals.md](../../internals.md#desktop-apps) describes what the code does now.

## What the measurements changed

The numbers are in [spike/desktop/README.md](../../spike/desktop/README.md). Three claims of this document changed.

1. **A zoom built from a 4K recording is not reliable on every machine.** The measured 4K recording lost 1.45 % and 1.69 % of its frames against a mark of 1 %, and its first frames were 200-240 ms late against a mark of 0.1 s. The code still records the monitor at twice the size, and the plan's warning that a small machine can fail to hold 25 frames a second is now a measured fact rather than a guess.
2. **The screen reading is not trusted as a locator.** Tesseract read 4.3 % of the words at best against a mark of 90 %, so a `{text: ...}` locator that the tree does not have names only a large plain piece of text. The probe report prints the words it did read, and a step that needs a word the screen did not give still fails.
3. **Marks keep their animation, but a long take costs more than the mark.** The pictures show a mark drawing itself and a ring spreading, so the animation stays. Chromium drew the 321 pictures of a 60 s take in 13.0 s against a mark of 10 s.

Two more claims changed as the numbers came in:

- **A mark is drawn from the tree only for a toolkit whose boxes are in monitor coordinates.** GTK 3 passes; GTK 4 names plenty of controls but every box starts at the window origin, so a mark on a GTK 4 app lands in the top-left corner. Qt publishes no tree at all.
- **A title bar does not grow with the scale.** openbox gave 22 px and metacity 37 px at both scale 1 and scale 2, so a picture of a scaled app mixes one height of decoration with doubled content. openbox was chosen for the window manager.

## Goal

`howto` films a Linux desktop app as it films a web app: from a storyboard, with `howto probe`, `howto render` and `howto animate`, and with the same narration.

The app runs on a virtual monitor inside a container. `howto` records that monitor and sends it clicks and keys, so one mechanism serves every app. No code is written for one toolkit or one app.

The work is done when all of these are true:

- `howto probe`, `howto render` and `howto animate` work on a desktop storyboard, and the tests prove it on a fixture app in CI.
- A model that reads text only writes a six-step storyboard for a packaged GTK app from the skill and the probe report, and nobody corrects a step.
- The narration and the picture of a desktop video are within 0.1 seconds of each other.
- The browser stage behaves as before, and its tests pass unchanged.

## What does not change

- **The storyboard is still the only input**, and `howto` still calls no model. The OCR is tesseract, a program in the container.
- **A model without image input can still write a storyboard.** The probe report stays plain text.
- **`runner.py`, the narration and the timeline stay as they are.** The desktop is a second implementation of the `Stage` protocol in `runner.py`.
- **The host needs one new program: Docker.** The display, the recorder and the OCR are in an image.

## Decisions

| Decision | Reason |
|---|---|
| A container, not a hidden display on the host | The host needs Docker only. The app sees a home of its own, not the user's files. A hidden display needs Xvfb, a window manager, tesseract and the AT-SPI bindings as system packages |
| A container, not a VM | A container starts in about a second and shares the host's clock. A VM boots in tens of seconds and needs disk images of several gigabytes. A Linux app does not need one |
| A helper inside the container | The accessibility tree is on a bus inside the container. A helper there reads it, and the host needs no bindings. A VM is later another way to reach the same helper |
| Locators in three layers | The tree gives names, as on a web page. OCR serves an app that publishes no tree. Coordinates serve what has no words |
| Notes, cards and marks are laid over the recording afterwards | See [Why nothing is drawn on the monitor](#why-nothing-is-drawn-on-the-monitor) |
| A zoom is made in the assembly, from a monitor of twice the size | An app cannot enlarge itself as a page can. See [Zoom](#zoom) |
| No bind mounts | Docker from a snap limits what it mounts. Files leave the container with `docker cp`, which also works with a remote Docker |

## The parts

| Part | Where it runs | What it does |
|---|---|---|
| `DesktopStage` | Host | Implements `Stage`. Turns each action into requests to the helper, and writes down what the picture must show |
| The link | Host | Starts the container and carries the requests: one JSON object on each line, over Docker's stdin and stdout |
| The helper | Container | Starts the monitor and the app. Finds elements, moves the pointer, types, records, reads the screen |
| The image | Container | `howto-desktop`: the monitor, a window manager, the AT-SPI bus, ffmpeg, tesseract, xdotool, a VNC server and the helper |
| `overlay.py` | Host | After the take, draws the notes, the cards and the marks as pictures with transparency |
| `assemble.py`, `animation.py` | Host | As now, and they also make the zoom and lay the overlay on the recording |

`cli.open_stage` picks the stage: `DesktopStage` for a storyboard with `app`, the Playwright stage for one with `url`.

## The image

- **`howto image` builds the base image**, `howto-desktop`, with `docker build`. The Dockerfile and the helper are files of the package, so the image always matches the installed `howto`.
- **The base is Ubuntu 24.04.** It holds Xvfb, a window manager, D-Bus, `at-spi2-core`, Python with the AT-SPI bindings, xdotool, ffmpeg, tesseract with English, x11vnc, noVNC, and the fonts and the icon theme that make an app look as it does on a desktop.
- **The image is tagged with the version of `howto`**, and as `latest`. The helper says its version when it starts. An image from another version stops the command with a message: `the image howto-inkscape was built by howto 0.1.0, and this is howto 0.2.0: run "howto image", then build howto-inkscape again`.
- **The app runs as a user without root rights**, named `howto`, with the home `/home/howto`.
- **The container has Docker's default network.** The app reaches the internet, and the host cannot reach the app. The one port that Docker publishes is the window of [Profiles and a visible window](#profiles-and-a-visible-window).
- **`HOWTO_DOCKER` names the Docker command.** The default is `docker`.

The author adds the app with a Dockerfile of their own:

```dockerfile
FROM howto-desktop
RUN apt-get update && apt-get install -y inkscape
COPY logo.svg /files/
```

## The helper and the link

The helper is the main process of the container. `howto` starts it with `docker run --rm -i IMAGE`.

- **The life of the container is the life of the pipe.** When `howto` ends, or is killed, the pipe closes. The helper then exits, and Docker removes the container. Nothing stays behind after a crash.
- **The Docker command runs in a session of its own.** Ctrl+C in the terminal then reaches `howto` only, so `cleanup` still has a desktop to run on. A termination signal that a shell sends to the whole process group does not reach the container either.
- **Stdout carries the protocol and nothing else.** The helper's own messages and the output of the app go to stderr. `howto` keeps the last lines, for an error message.
- **Each request has a number, and its reply carries the same number.** A reply is `{"id": 7, "ok": true, ...}` or `{"id": 7, "ok": false, "kind": "...", "error": "..."}`.
- **Each request has a time limit.** A helper that does not answer in time ends the command with `the desktop stopped answering`.
- **The helper is plain Python on the image's own packages.** Its parts that do not touch the bus or the display are tested on the host.

The requests:

| Request | What the helper does | What it answers |
|---|---|---|
| `start` | Starts Xvfb at the given size and scale, the session bus, the AT-SPI bus, the window manager and the app. Waits for the app's first window | Its version, and the title of the window |
| `find` | Looks for a locator until it is found or the time limit ends | The box in picture pixels, the layer that found it, and the count of matches |
| `pointer` | Moves the pointer to a point along an eased path, in a given time | Nothing |
| `click` | Presses and releases the first button where the pointer is. Refuses when another window covers the point | Nothing, or the title of the window that covers it |
| `type` | Types text, at a given number of characters a second | Nothing |
| `key` | Presses a key or a chord | Nothing |
| `scroll_to` | Asks the app to bring an element of the tree into view | Nothing |
| `run` | Runs a shell command as the app's user and waits for it | The exit code and the last lines of output |
| `outline` | Reads the tree of every window that is showing | The outline as text |
| `words` | Reads the screen with tesseract | Each line of words with its box |
| `screenshot` | Writes a PNG of the monitor in the container | Its path |
| `busy` | Counts, for each of several areas of a screenshot, the share of pixels that are not the area's most common colour | One share for each area |
| `record_start` | Starts ffmpeg | The time of the first frame |
| `record_stop` | Ends ffmpeg | The path of the recording |
| `show` | Starts the VNC server and noVNC | The password of this run |

`start` sets what makes each toolkit publish its tree: the `org.a11y.Status` flags on the bus, and `QT_LINUX_ACCESSIBILITY_ALWAYS_ON` for Qt. The app is started with `sh -c`, so `app.run` can be a line of shell.

## The storyboard

```yaml
title: Export a drawing as PNG
app:
  image: howto-inkscape            # built FROM howto-desktop
  run: inkscape /files/logo.svg    # what starts the app
viewport: 1920x1080                # the size of the picture
steps:
  - say: Open the File menu and choose Export.
    do:
      - click: {role: menuitem, name: File}
      - click: {role: menuitem, name: Export…}
  - say: Click the drawing, then press Export.
    do:
      - click: {at: 960x540}       # the canvas publishes no names
      - click: {text: Export}      # looked up in the tree, then read off the screen
```

- **A storyboard has `url` or `app`, never both.** `app` has two fields, and both are required: `image` and `run`.
- **`viewport` is the size of the picture.** The monitor has that size, or twice that size when the storyboard zooms.
- **`profile`, `setup`, `cleanup`, `pace`, `zoom`, `crop` and `voice` keep their meaning.**
- **Every position in a storyboard is in picture pixels**, with or without a zoom.

### Locators

| Form | Where it looks | Notes |
|---|---|---|
| `{role: button, name: Save}` | The tree | `name` is optional. It matches a part of the name without regard to case, and the whole name with `exact: true`, as on a web page |
| `{label: Email address}` | The tree | The control that a label with these words names |
| `{text: Export}` | The tree first, then the screen | The tree: an element whose name or text has these words. The screen: a line that tesseract reads with these words |
| `{at: 960x540}` | Nowhere: it is a point | For a click, a hover and a wait |
| `{at: 900x500, size: 120x40}` | Nowhere: it is an area | `at` is the top left corner. An action goes to the middle. A mark and a `crop` need an area |

- **`nth`, `exact` and `within` work as on a web page.** `within` takes a locator of the tree.
- **`placeholder`, `testid` and `css` are refused** in a desktop storyboard. `at` and the action `run` are refused in a web storyboard. The message names the step and the field, and says what the storyboard can use.
- **Only what is showing matches.** An element counts when the tree says that it is showing and its box is on the monitor.
- **More than one match fails**, with the count, as on a web page: `2 elements match`. The author adds `exact`, `nth` or `within`.
- **Roles have the names that a web outline uses.** AT-SPI says `push button`, `menu item`, `check box` and `text`. The helper maps them to `button`, `menuitem`, `checkbox` and `textbox`, so one skill teaches both kinds of storyboard. A role with no web name keeps its AT-SPI name.

### Actions

| Action | On a desktop |
|---|---|
| `click` | Finds the element, moves the pointer to its middle, and clicks |
| `hover` | Finds the element and moves the pointer to it |
| `fill` | Clicks the element, selects what is in it with Control+A, and types the value |
| `select` | Clicks the control, then clicks the element of the tree whose name is the option. It needs the tree. For a list that only the screen shows, the author writes two clicks |
| `press` | A key or a chord, with the names a web storyboard uses: `Enter`, `Control+S`, `ArrowDown`. The helper maps them to the names of X |
| `type` | New. Types text to whatever has the keyboard, at `pace.typing`. It serves a canvas, a terminal and a field where Control+A does not select. It also works on a web page |
| `scroll_to` | Asks the app to bring an element of the tree into view. An app that cannot do it fails the step, with a message that offers `press: PageDown` |
| `wait_for` | Waits until the locator finds its element |
| `run` | New. Runs a shell command in the container and waits for it, for three times the action's time limit at most. A command that ends with another code than 0, or does not end in time, fails the step. For `setup` and `cleanup` most of all: to copy a document in, and to remove what the steps made. A longer job belongs in the image |
| `goto` | Refused: an app has no addresses |

The marks, `box`, `circle`, `underline`, `arrow` and `spotlight`, take any locator that gives an area.

A probe performs the same actions without the show: the pointer jumps, and the keys come with no delay.

## The probe report

```
step 1 ok      click role=menuitem name="File"
step 2 FAILED  click text="Exprot": not in the tree, and no such words on the screen. The nearest words: "Export"
page: app inkscape /files/logo.svg  "logo.svg - Inkscape"
outline:
- frame "logo.svg - Inkscape" [active]:
  - menubar:
    - menuitem "File"
    - menuitem "Edit"
words on the screen that the outline lacks:
- "Layer 1" {at: 1620x200, size: 62x24}
- "Export" {at: 1658x952, size: 88x24}
screenshot: /home/sam/.cache/howto/probe/export.png
```

- **The outline is the tree of every window that is showing**, written as a web outline is. The window that has the keyboard is marked `[active]`. A dialog is one more window in the list.
- **The words are what tesseract reads and the tree does not have.** A line is left out when it lies inside an element of the tree that has the same words. Each line is printed as a locator that the author can copy.
- **The screenshot is always saved**, for a person or for a model that can look. Each probe of a storyboard replaces the last one.
- **`--until`, `--within` and `--max-chars` work as before.** `--max-chars` cuts the outline and the words together.
- **`note:` lines report what the steps did not handle**: the app exited, or a window opened that no step touched.

`PageReport` in `runner.py` gets two fields for this, `words` and `screenshot`. Both are empty for a web page.

## The picture

- **The recording is ffmpeg's `x11grab` in the container**: the whole monitor, 25 frames a second, as the browser's recorder gives. `howto` fetches it with `docker cp` when the take ends.
- **The pointer in the picture is the real pointer of the monitor.** It moves along an eased path, and it changes its shape over a text field as a viewer expects.
- **One clock times the picture and the narration.** A container shares the monotonic clock of the host. The helper reports the time of the first frame on that clock, so `DesktopStage` knows how much of the recording lies before the timeline starts. The assembly leaves that head out.
- **The window manager fills the monitor with the first window that the app shows.** A window that opens later, a dialog for example, keeps its own size and its title bar.

### The log of the take

During a take `DesktopStage` writes down what the finished picture must show, in a file next to the recording:

- the head of the recording that lies before the timeline;
- each zoom: when it starts, which part of the picture it shows, and how long the move takes;
- each note, chapter card, mark and click: when it appears, when it goes, and its HTML or SVG.

The assembly reads this file. `runner.py` and its `RunResult` do not change.

### Why nothing is drawn on the monitor

The browser stage draws notes and marks in the page's own window. On a desktop that would be a transparent window on top of the app, and it has four costs:

- **The OCR reads the note** as words on the screen, in the probe and in every `text` locator.
- **A window that is always on top competes with the app** for the keyboard and with its menus for the top place, and it appears in the tree.
- **The image needs a compositor and a web engine** to draw it.
- **A VM guest would later need all of that too.**

So the monitor shows the app only. After the take, `overlay.py` draws the layer of notes, cards and marks with the Chromium that `howto` already has.

- **The HTML and the SVG are the ones the browser stage uses**, from `marks.py` and from the note's style, so a mark looks the same in both kinds of video.
- **The layer is a list of PNG pictures with transparency**, each with the time it is shown. A picture is made only when the layer changes, which is how `animation.py` keeps the frames of a GIF.
- **A mark, a ring and a title card appear at once.** Measured: Chromium drew the 321 pictures of a 60 s take in 13.1 s, over the 10 s mark, so the layer is one picture for each moment at which something changes and nothing is stepped frame by frame. `overlay.py` can still stop the page's animations and set their time for each frame, so that the frames do not depend on how fast the machine is, and it does so for whatever animates.
- **ffmpeg lays the layer on the recording** in the same command that makes the zoom.
- **The chapter card is `howto`'s own.** The browser's recorder draws the card of a web video, and nothing can call it here. The card of a desktop video is drawn to match it.
- **Each click shows a ring** that spreads from the pointer, because the real pointer shows no click.

A mark does not follow the app if the app moves under it. A web page has the same rule.

**An arrow comes from the emptiest side**, as on a web page. The browser stage asks the page what lies at each candidate place. The helper counts in a screenshot how busy each place is, which also works for a canvas.

## Zoom

A page enlarges itself and draws its text again at the new size. An app cannot. A cut from a recording of the picture's own size only blurs.

- **The monitor has twice the size when the storyboard zooms.** For a picture of 1920x1080 the monitor is 3840x2160. The helper tells the toolkits to draw at twice the scale with three settings: `GDK_SCALE` for GTK and Firefox, `QT_SCALE_FACTOR` for Qt, and `Xft.dpi` for Chromium, Electron and most of the rest. The author sets nothing for one app.
- **The wide picture is the recording at half its size. A zoom of 2 is a cut of the recording at its own size**, so its text is as sharp as on a web page. Above 2 the cut is enlarged and softens. The limit stays at 4.
- **ffmpeg makes the move.** `zoom.py` says which part of the picture a zoom shows, with the arithmetic it has now. The assembly turns the zooms of the log into one `zoompan` expression. A move takes as long as on a web page.
- **Notes and marks are laid on after the zoom**, in picture pixels, as the browser stage has them. A mark keeps the width of its stroke and goes around the enlarged control. `runner.py` already takes the marks away before the picture moves, so no new rule is needed.
- **A storyboard without a zoom keeps a monitor of the picture's own size.** A recording of 3840x2160 costs four times the work, and a small machine can fail to hold 25 frames a second.
- **A probe uses the monitor that the take will use.**

Three things differ from a web page:

| | Web page | Desktop |
|---|---|---|
| The pointer in a zoom | Keeps its size | Is enlarged with the picture, as under a magnifier |
| An app that ignores all three scale settings | Does not exist | Is drawn at half size on the larger monitor. The screenshot of the probe shows it |
| Parts pinned to the window, which stop a zoom | The picture stays wide, with a `note:` | No such case |

`zoom` and `crop` do not go together, as now.

## Crop and animated pictures

- **`howto animate` on a desktop storyboard is a silent take**, as on a web page.
- **`crop` takes a locator that gives an area.** The cut is made by ffmpeg from the recording, with the 12 pixels around the element and the even numbers that `zoom.py` gives now.
- **The strip for the notes is part of the overlay layer.** It lies where the browser stage draws it, so the cut is the same.
- **A probe reports the crop**, and names each action whose element is outside it, as now.

## Profiles and a visible window

- **A profile of a desktop storyboard is a Docker volume**, `howto-profile-NAME`, mounted as the home of the app's user. It keeps a sign-in and what a first-run wizard asks.
- **Without a profile, the home is new for every run**, so a take is repeatable.
- **`howto login NAME STORYBOARD` makes the profile.** When the second argument is a storyboard file with `app`, `howto` starts that app on the profile and shows the monitor in a window. The command returns when the person closes the window.
- **A storyboard that names a profile that does not exist stops** with the `howto login` command that makes it, as now.
- **The window is noVNC in the Chromium that `howto` has.** The helper starts x11vnc and noVNC on request. Docker publishes the port on 127.0.0.1 only, and each run has a password of its own.
- **`howto probe --show` uses the same window**, without the mouse and the keyboard, so that the person watching cannot disturb the steps.

## Errors

| What happens | What `howto` does |
|---|---|
| Docker is not installed, or its daemon does not answer | Exit 1, and the message says so |
| The image of the storyboard does not exist | Exit 1, with the `docker build` line to run. For the base image, `howto image` |
| The image is from another version of `howto` | Exit 1, with the two commands that build both images again |
| The app shows no window in three times the action's time limit | Exit 1, with the last lines of the app's output |
| The app exits during a step | The step fails with the exit code and the last lines of output. The report is still printed |
| A locator finds nothing | The step fails. The message says which layers were tried, and offers the nearest words |
| Another window covers the element | The step fails, and the message names that window |
| A locator form or an action that a desktop does not have | Exit 2 when the storyboard is read. The message names the step and the field |
| Ctrl+C | `cleanup` runs, and the exit code is 130. The request in progress ends first, so the stop can take as long as one action's time limit |
| The helper stops answering, or the container is gone | Exit 1: `the desktop stopped` |

`HOWTO_ACTION_TIMEOUT` is the time an element gets to appear, as now.

## Changes to the existing code

| File | Change |
|---|---|
| `storyboard.py` | `app` with `image` and `run`. `url` or `app`. The locator form `at` with `size`. The actions `type` and `run`. The checks that depend on the kind of storyboard |
| `runner.py` | `PageReport` gets `words` and `screenshot` |
| `probe.py` | Prints the words and the path of the screenshot |
| `capture.py` | The action `type`. The HTML of a note and of the strip moves to a module that `overlay.py` shares |
| `assemble.py` | Reads the log of the take: leaves the head out, makes the zoom, lays the overlay on |
| `animation.py` | The same three, for the frames of a picture |
| `cli.py` | Picks the stage. `howto image`. `howto login` with a storyboard |
| `tools.py` | Finds Docker |

New files:

| File | Content |
|---|---|
| `src/howto/desktop/stage.py` | `DesktopStage`, and the log of the take |
| `src/howto/desktop/link.py` | The Docker process and the JSON lines. A VM is later a second link |
| `src/howto/desktop/helper/` | The helper. It runs in the container |
| `src/howto/desktop/image/Dockerfile` | The base image |
| `src/howto/overlay.py` | Draws the overlay layer with Chromium |

## Tests

- **Unit tests run `DesktopStage` against a scripted helper**: a list of the requests it expects and the replies it gives.
- **The helper's pure parts are tested on the host**: the role names, the outline, a match over a tree that is given as data, the output of tesseract, the key names and the path of the pointer.
- **The ffmpeg expressions are tested as text**: the zoom, the overlay and the head.
- **The storyboard tests cover** `app`, `at`, `type`, `run` and each refusal.
- **Tests marked `desktop` need Docker and the base image.** They film a small GTK program in `tests/fixtures`. It has a button, a field, a list, a menu, a dialog, and a painted area with words for the OCR.
- **CI builds the image and runs them.** `HOWTO_REQUIRE_DESKTOP=1` makes a skipped desktop test a failure, as `HOWTO_REQUIRE_BROWSER` does for the browser.

## Measurements to make first

The design rests on seven things that nobody has run. Each is measured before the build, and the code that measures goes in `spike/`, where the browser's measurements are.

The four apps of the measurements are one of each kind: GTK 3, GTK 4, Qt and Electron.

| What is measured | It passes when | If it fails |
|---|---|---|
| The tree in a bare container, for the four apps | Each app publishes its controls with roles and names, and each box is within 2 pixels of the control in a screenshot | That toolkit gets screen locators only, and the documents say so |
| `x11grab` at 1920x1080 and at 3840x2160 | 25 frames a second with under 1 % of the frames lost, the pointer in the picture, and the reported first frame within 0.1 s of the real one | The larger size: the zoom records at a lower rate, or cuts from the smaller size and softens |
| The three scale settings on the four apps, and the window manager at twice the scale | Each app is drawn at twice the size with sharp text, and a title bar has the right size | That toolkit is listed as one that a zoom draws small. Another window manager is tried |
| `zoompan` from a recording of twice the size | A move in and out shows no shake from frame to frame, and the text at 2 equals the cut of the recording | The zoom is built from `crop` and `scale` in pieces |
| tesseract on the text of an interface | At least 90 % of the words on a screenshot of the picture's own size are read right, in 2 seconds or less | The screenshot is enlarged before it is read |
| The overlay layer | Chromium gives the frames of a mark with transparency, ffmpeg lays a list of them on a video, and a take of 60 seconds needs 10 seconds or less for it | The marks are drawn without their animation |
| Docker from a snap | A request and its reply take 20 ms or less, `docker cp` fetches a file of 200 MB in 5 seconds or less, and Ctrl+C leaves no container | The recording leaves through a volume |

## The order of the work

Each slice ends with a command that works.

| Slice | Content | It ends with |
|---|---|---|
| Measurements | The seven above | Numbers, and this document changed where one failed |
| The stage | The image, `howto image`, the helper, the link, the locators of the tree, the pointer and the keys | `howto probe` on a desktop storyboard |
| The take | The recording, the pace of the pointer, the log of the take, the notes and the chapter cards | `howto render` with narration |
| The screen | OCR, `at`, the words and the screenshot of the report | A probe of an app that has no tree |
| The marks | The five marks, the ring of a click, `crop` | `howto animate` |
| The zoom | The larger monitor and the move | `zoom: 2` |
| Profiles | The volume, `howto login`, `--show` | An app that needs a sign-in |
| The documents | The skill, the guide, the internals, the README, the diagrams, an example with its Dockerfile | Documents that agree with the code |

## Not in this version

- **A double-click, a click of the second button and a drag.** The browser stage has none of them either. A file manager needs them, so they are the next thing a desktop asks for.
- **Scrolling with the wheel.** `scroll_to` and `press: PageDown` serve until then.
- **The sound of the app.** The recording has the picture only.
- **An app that runs on Wayland only**, and an app that needs a graphics card.
- **A VM, and guests with another system.** The link and the overlay are made so that neither blocks them: a VM needs a second link, and the overlay needs nothing in the guest.
- **A base image that is published.** `howto image` builds it on the user's machine.
