# What the measurements found

Run on this machine with the machine otherwise idle, with ffmpeg 9.0.2 and
6.1.1-3ubuntu5. Each number is as it came, with the pass mark of the plan
under it. The pictures are in `spike-out/desktop/`.

## Docker from a snap

Docker here is the snap (29.8.0), which is what the plan assumed.

| Check | Mark | Result |
|---|---|---|
| Round trip of one request | 20 ms or less | **pass**, 0.0 ms |
| `docker cp` of 200 MB | 5 s or less | **pass**, 0.2 s |
| A file in a hidden folder | arrives | **pass**, `~/.cache/howto/spike-fetch` |
| Ctrl+C leaves no container | no container left | **pass** |

One machine-only note: containers on Docker's default bridge have no outbound
connection here (`docker0` has no address), so a build that runs `apt-get`
fails with a DNS error. Builds and runs go through `--network=host` or a
user-defined bridge, which is why `HOWTO_DOCKER` is set to a wrapper on this
machine. A user-defined bridge can publish a port; the default bridge cannot.

## Window manager

openbox was chosen: it is smaller, and the hints that take the title bar off
work when they are set before the window is mapped.

The plan expected a title bar of twice the height at scale 2. It does not
happen with either window manager:

| Window manager | title bar at scale 1 | at scale 2 |
|---|---|---|
| openbox | 22 px | 22 px |
| metacity | 37 px | 37 px |

So a title bar does not grow with the app, and the picture of a scaled app
has a title bar of one height while everything inside it is doubled.

## Accessibility tree

| App | toolkit | nodes | named controls | read time | boxes on the monitor |
|---|---|---|---|---|---|
| gedit (GTK 3) | gtk | 45 | 8 | 0.02 s | yes, within 2 px |
| gnome-calculator (GTK 4) | GTK | 98 | 58 | 0.05 s | no: every box starts at the window origin |
| featherpad (Qt) | (none) | 0 | 0 | 0.02 s | no tree at all |
| Visual Studio Code (Electron) | Chromium | 2 | 0 | 0.01 s | window only, no named control |

The pass mark was ten named controls with boxes on the monitor within 2 pixels.
Only GTK 3 passes. GTK 4 names plenty of controls but its boxes are not in
monitor coordinates, so a mark drawn from them lands in the top-left corner
(`spike-out/desktop/tree/gtk4-boxes.png`). Qt publishes nothing even with
`QT_ACCESSIBILITY=1`, and Electron publishes a Chromium tree with no named
control until the app has finished starting.

The plan's fallback stands: read the screen when the tree has nothing. But the
screen reading itself does not reach its mark (see below), so a locator that
the tree does not have is a guess, not a measurement.

## Recording

| Size | frames | lost | clock | first frame off |
|---|---|---|---|---|
| 1920x1080 | 412 in 16.5 s | 0.00 % | wall | +40 ms |
| 3840x2160 run 1 | 406 in 16.5 s | 1.69 % | wall | +240 ms, then +80 ms |
| 3840x2160 run 2 | 407 in 16.5 s | 1.45 % | wall | +200 ms, then +80 ms |

1080p passes. 4K loses more than the 1 % mark and its first frames are more
than 0.1 s late, so the zoom cannot be built from a 4K recording on this
machine. The clock is the wall clock, as the plan expected.

## Scale

The settings that work are the ones the plan named: `GDK_SCALE=2` with
`GDK_DPI_SCALE=0.5`, `QT_SCALE_FACTOR=2` with `QT_FONT_DPI=96`, and
`Xft.dpi: 192` in the X resources.

| App | unit of the boxes at scale 2 | controls in the same place as at scale 1 | picture |
|---|---|---|---|
| gedit (GTK 3) | 2 | 4 of 7 | sharp text |
| gnome-calculator (GTK 4) | 2 | 58 of 58 | sharp text |
| featherpad (Qt) | 0 (no controls) | 0 of 0 | drawn at half size |
| Visual Studio Code (Electron) | 2 | 0 of 0 | doubled pixels |

Qt draws its window at half the size it should be at `QT_SCALE_FACTOR=2` with
`QT_FONT_DPI=96` (`spike-out/desktop/scale/qt-2.png`), and Electron draws
doubled pixels rather than larger text. Only GTK apps scale as the plan
expected, and only when their boxes are read in monitor coordinates.

## Zoom

All three ways pass with both ffmpeg releases: the picture stays still at rest
(0.00 px off), moves by at most 2.5 px during a move, and never steps back.

| Way | off at rest | off at most during a move | steps back | PSNR at zoom 2 | 4 s of video |
|---|---|---|---|---|---|
| zoompan | 0.00 px | 2.09 px | 0 | inf dB | 0.6 s |
| zoompan after 4:4:4 | 0.00 px | 1.65 px | 0 | inf dB | 1.0 s |
| scale and overlay | 0.00 px | 0.93 px | 0 | inf dB | 0.8 s |

The preferred way is `zoompan`, which passes with both releases and is the
shortest filter.

## Reading the screen

Tesseract reads 4.3 % of the words at best, against a mark of 90 %.

| Enlargement | mode | words read | time |
|---|---|---|---|
| x1 | 11 | 4.3 % | 0.14 s |
| x1 | 6 | 0.0 % | 0.14 s |
| x2 | 11 | 4.3 % | 0.32 s |
| x2 | 6 | 4.3 % | 0.30 s |

The time is well under 2 s, but the words are not there. The pictures in
`spike-out/desktop/ocr/` show why: the apps draw their text with the theme's
anti-aliasing on a light background, and tesseract reads only the largest
piece of text on the screen. So the screen reading can name a word that is
large and plain, and cannot be relied on for a locator.

## Overlay layer

Chromium drew 321 pictures of a 60 s take in 13.0 s, over the mark of 10 s.
Both ffmpeg releases lay the pictures on correctly: the first picture is
see-through, and a mark appears where it should.

The animation itself works: the pictures show a mark drawing itself, a ring
spreading and a note staying sharp
(`spike-out/desktop/overlay/laid.mp4`), so the plan's paragraph about marks
that need animation stands.

## What the plan changes because of these numbers

- The zoom is built from a recording of 1920x1080, not 4K.
- A mark is drawn from the tree only for a toolkit whose boxes are in monitor
  coordinates (GTK 3). For GTK 4 the boxes are wrong, so a mark on a GTK 4 app
  lands in the corner.
- The screen reading is a fallback that names large plain words only, not a
  reliable locator.
- A title bar does not scale, so a picture of a scaled app mixes one height of
  decoration with doubled content.
- The overlay of a long take takes about 13 s, so a take with many marks is
  slower than the plan's 10 s.
