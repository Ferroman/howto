# Filming a desktop app

`howto` films a Linux desktop app as it films a web app: from a storyboard, with `howto probe`, `howto render` and `howto animate`. This page is for the person who wants the video. [The skill](../skill/SKILL.md#desktop-apps) is the reference of the format, written for the agent that writes the storyboard. [The internals page](internals.md#desktop-apps) says how it works, and why.

## What can be filmed

- **A Linux app that draws on X11**: GTK, Qt, Electron, and most of the rest. One mechanism serves them all, and `howto` has no code for one toolkit or one app.
- **Not an app for macOS or Windows**, not one that runs on Wayland only, and not one that needs a graphics card.
- **A click is a click of the first button.** There is no double-click, no click of the second button, no drag, and no scrolling with the wheel. `scroll_to` and `press: PageDown` scroll.
- **The video has no sound of the app.** The narration is its only sound.

The app runs in a Docker container, on a monitor of its own. It does not see your files, and it does not appear on your screen.

## Set it up once

Install [Docker](https://docs.docker.com/engine/install/), so that `docker run hello-world` works for your user. Then build the base image:

```bash
howto image
```

It prints two tags, `howto-desktop:VERSION` and `howto-desktop:latest`. The image holds the monitor, the recorder, the program that reads the screen, and the helper that `howto` talks to.

When Docker needs other words than `docker`, put them in `HOWTO_DOCKER`: `export HOWTO_DOCKER="sudo docker"`.

## Put the app in an image

Write a Dockerfile that starts from the base image and adds your app, with the documents that the video needs. This is [the one of the example](../examples/desktop/Dockerfile):

```dockerfile
FROM howto-desktop
RUN apt-get update && apt-get install -y --no-install-recommends gedit \
 && rm -rf /var/lib/apt/lists/*
COPY --chown=howto:howto notes.txt /home/howto/notes.txt
```

```bash
docker build -t howto-gedit examples/desktop
```

- **The app runs as the user `howto`**, with the home `/home/howto`. A file that the app has to change belongs to that user: `COPY --chown=howto:howto`.
- **The home is new for every run**, so a take is repeatable: what one run saves, the next does not find. A [profile](#an-app-that-needs-a-sign-in) keeps the home.
- **The app reaches the internet**, as it does on a desktop. Nothing reaches the app from outside.
- **Build both images again after you update `howto`.** The base image holds a part of `howto`, and an image from another build is refused with the two commands to run:

```
the image howto-gedit was built by howto 0.1.0+2cbfd950, and this is howto 0.1.0+3a331aef: run `howto image`, then build howto-gedit again
```

## Write the storyboard

A storyboard of a desktop app has `app` where one of a web page has `url`. This is an illustration, and [examples/desktop/replace.yaml](../examples/desktop/replace.yaml) is one that runs:

```yaml
title: Export a drawing as PNG
app:
  image: howto-inkscape
  run: inkscape /files/logo.svg
viewport: 1280x720
steps:
  - say: Open the File menu, and choose Export.
    do:
      - click: {role: menu, name: File}
      - click: {role: menuitem, name: Export…}
  - say: Click the drawing, then press Export.
    do:
      - click: {at: 640x360}
      - click: {text: Export}
```

- **`image`** is the image that you built, and **`run`** the line that starts the app, as you type it in a terminal.
- **`viewport`** is the size of the picture. The first window of the app fills it. A dialog that opens later keeps its own size and its title bar.
- **Everything else is written as for a web page**: the narration, the notes, the marks, `zoom`, `crop`, `setup` and `cleanup`.

Ask your agent for the video as you do for a web app, and name the image and the command in place of an address: "Make a how-to video: export a drawing as PNG. It is a desktop app: the image is howto-inkscape, and it starts with `inkscape /files/logo.svg`."

`howto probe` is how the storyboard is written, by you or by an agent. It runs the steps and prints what the app shows:

```
step 1 ok      click role=menu name="File"
step 2 FAILED  click text="Exprot": not in the tree, and no such words on the screen. The nearest words: "Export"
page: app inkscape /files/logo.svg  "logo.svg - Inkscape"
outline:
- frame "logo.svg - Inkscape" [active]:
  - menubar:
    - menu "File"
    - menu "Edit"
words on the screen that the outline lacks:
- "Layer 1" {at: 1060x140, size: 62x24}
- "Export" {at: 1098x652, size: 88x24}
screenshot: /home/sam/.cache/howto/probe/export.png
```

- **The outline** is what the app says about itself to a screen reader: each control with its role and its name.
- **The words** are what `howto` reads off the screen and the outline lacks, such as the text of a canvas. Each line has a locator to copy.
- **The screenshot** is the monitor as the probe left it. Each probe of a storyboard replaces the last one. A place on it is a place of the picture, so a point that you read off it is a point that `at` takes.

## Name what a step acts on

| You write | `howto` looks | Use it for |
|---|---|---|
| `{role: button, name: Save}` | In the outline | Whatever the outline lists. This is the form to prefer |
| `{label: Email address}` | In the outline | A field that a label names |
| `{text: Export}` | In the outline, then on the screen | Words that the app draws without a name |
| `{at: 960x540}` | Nowhere: it is a point of the picture | A canvas, or a control with no name and no words |
| `{at: 900x500, size: 120x40}` | Nowhere: it is an area | A mark or a `crop` at such a place |

An app that says nothing to a screen reader has an empty outline, and can still be filmed: by its words, and by places.

## An app that needs a sign-in

```bash
howto login demo videos/export.yaml
```

The second word is the storyboard. `howto` starts its app and shows it in a window. Sign in, answer what the app asks at its first start, and close the window. The storyboard then names the profile:

```yaml
profile: demo
```

- **A profile is a Docker volume**, `howto-profile-demo`, which becomes the home of the app. It holds your signed-in session. `docker volume rm howto-profile-demo` removes it from the machine.
- **Every probe and every take performs its actions for real.** Sign in to a demo account or a test workspace, never to real data.
- **`howto probe FILE --show`** opens the same window while the steps run, for you to watch. It takes no clicks and no keys, so you cannot disturb the steps.

## Make the controls readable

`zoom: 2` enlarges the picture around each control as it is used, as on a web page. An app cannot enlarge itself as a page can. So the app of a storyboard that zooms runs on a monitor of twice the size, drawn at twice the scale, and a zoom shows a part of that larger recording.

- **The text of a zoom is as sharp as the app draws it**, up to a zoom of 2. Above 2 it softens.
- **The pointer is enlarged with the picture**, as under a magnifier.
- **An app that ignores the scale is drawn small**, in a corner of the monitor. The screenshot of a probe shows it. `viewport: 1280x720` without a zoom is then the way to larger controls.
- **A take with a zoom is four times the work to record.** A storyboard without `zoom` keeps a monitor of the picture's size.

## Things that surprise

- **Nothing is drawn on the app's monitor.** The notes, the title cards and the marks are laid on the recording afterwards, so the app and `howto probe` never see them.
- **Each click shows a ring.** The pointer of a desktop shows no click by itself.
- **A click on a control that another window covers fails**, and the message names that window: `another window covers it: "Open"`. Act on the dialog first.
- **A window that opened and that no step touched is reported**: `note: a window opened that no step touched: "Save changes?"`.
- **An app that ends during the steps fails the step**, with its exit code and the last lines that it printed.
- **`select` needs a list that the outline has.** For a list that only the screen shows, write two clicks.
- **`fill` selects what is in the field with Control+A** before it types. In a terminal or on a canvas, write a `click` and then `type`.
- **A mark goes around the words of a label**, not around the room that the app gave the label.
- **Ctrl+C runs `cleanup` and exits with 130**, as for a web page. The container is gone when `howto` ends, however it ends.
- **An element gets 10 seconds to appear**, and the first window of the app three times that. `HOWTO_ACTION_TIMEOUT` changes it for a slow app.
