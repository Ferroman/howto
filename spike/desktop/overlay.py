"""Measurement: can Chromium draw the notes and the marks as pictures with transparency, and ffmpeg lay them on a video?

A take of 60 seconds is made up: eight notes, eight marks that draw
themselves and fade, and twelve rings of clicks. Chromium draws a picture for
each moment at which the layer changes, with every animation set to its time
by hand. ffmpeg lays the pictures on a plain video. The script times the
drawing, checks that the first picture is empty and see-through, and checks
that a red mark is in the video when it should be and not before.

Run:  uv run python spike/desktop/overlay.py [FFMPEG ...]
      The default is howto's ffmpeg, and /usr/bin/ffmpeg when it is another one.
"""
from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import box
from howto import marks
from howto.capture import note_html
from howto.tools import find_tool
from howto.zoom import Box

OUT = box.OUT / "overlay"
W, H, FPS, LENGTH = 1920, 1080, 25, 60.0
VIEW = (W, H)
PAGE = (
    "<!doctype html><html><head><style>html,body{margin:0;background:transparent;overflow:hidden}"
    ".item{position:absolute;inset:0;display:none}</style></head><body>ITEMS</body></html>"
)
RING = (
    "<style>@keyframes ring{from{transform:translate(-50%,-50%) scale(.3);opacity:.95}"
    "to{transform:translate(-50%,-50%) scale(1);opacity:0}}</style>"
    '<div style="position:absolute;left:LEFTpx;top:TOPpx;width:56px;height:56px;border-radius:50%;'
    'box-sizing:border-box;border:4px solid #fff;animation:ring 450ms ease-out forwards"></div>'
)
# Shows the items of one moment: [index, milliseconds since it appeared or null when it is done, opacity].
SET = """(states) => {
  const on = new Map(states.map(([index, grown, opacity]) => [index, [grown, opacity]]));
  document.querySelectorAll('.item').forEach((item, index) => {
    const now = on.get(index);
    item.style.display = now ? 'block' : 'none';
    if (!now) return;
    item.style.opacity = now[1];
    for (const animation of item.getAnimations({subtree: true})) {
      animation.pause();
      animation.currentTime = now[0] === null ? 1e7 : now[0];
    }
  });
}"""


def scenario() -> list[tuple[float, float, str, float, float]]:
    """(start, end, html, seconds it takes to appear, seconds it takes to fade)."""
    shown = []
    shapes = [marks.box, marks.circle, marks.underline, marks.spotlight]
    for i in range(8):
        at = 2 + i * 7
        target = Box(300 + 150 * i, 200 + 60 * i, 160, 44)
        if i % 5 == 0:
            drawing = marks.arrow(marks.arrows(target, VIEW, "Look here")[0])
        else:
            drawing = shapes[i % 4](target, VIEW)
        shown.append((at, at + 3.25, marks.layer(drawing, VIEW), marks.DRAW_MS / 1000, marks.FADE_MS / 1000))
        shown.append((at - 1, at + 4, note_html(f"Note number {i + 1}"), 0.0, 0.0))
    for i in range(12):
        ring = RING.replace("LEFT", str(400 + 90 * i)).replace("TOP", "500")
        shown.append((1.5 + i * 4.8, 1.95 + i * 4.8, ring, 0.45, 0.0))
    return shown


def state(shown, at: float) -> tuple:
    """What the layer shows at one moment."""
    found = []
    for index, (start, end, _, grow, fade) in enumerate(shown):
        if not start <= at < end:
            continue
        age = at - start
        grown = None if age >= grow else round(age * 1000)
        left = end - at
        opacity = 1.0 if fade <= 0 or left >= fade else round(left / fade, 3)
        found.append((index, grown, opacity))
    return tuple(found)


def frame_count(length: float) -> int:
    return max(1, math.ceil(length * FPS - 1e-6))


def changes(shown, length: float) -> list[tuple[int, tuple]]:
    """The number of each frame at which the layer changes, with what it shows from then on."""
    plan, last = [], None
    for number in range(frame_count(length)):
        now = state(shown, number / FPS)
        if now != last:
            plan.append((number, now))
            last = now
    return plan


def listing(numbers: list[int], total: int) -> str:
    """The list from which ffmpeg reads the pictures, each with the time it is shown."""
    lines = ["ffconcat version 1.0"]
    for number, following in zip(numbers, [*numbers[1:], max(total, numbers[-1] + 1)]):
        lines.append(f"file '{number:06d}.png'\nduration {(following - number) / FPS:.2f}")
    # ffmpeg reads the time of the last picture only when the picture is named once more.
    lines.append(f"file '{numbers[-1]:06d}.png'")
    return "\n".join(lines) + "\n"


def draw(shown, out: Path) -> tuple[int, float]:
    """Draws the pictures. Returns how many, and the seconds it took."""
    plan = changes(shown, LENGTH)
    items = "".join(f'<div class="item">{html}</div>' for _, _, html, _, _ in shown)
    began = time.perf_counter()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.set_content(PAGE.replace("ITEMS", items))
        for number, states in plan:
            page.evaluate(SET, [list(one) for one in states])
            page.screenshot(path=str(out / f"{number:06d}.png"), omit_background=True)
        browser.close()
    (out / "frames.txt").write_text(listing([number for number, _ in plan], frame_count(LENGTH)), encoding="utf-8")
    return len(plan), time.perf_counter() - began


def redness(ffmpeg: str, video: Path, at: float) -> float:
    """Red minus green, in the part of the picture where the second mark is drawn."""
    raw = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1",
         "-vf", "crop=320:160:370:200,scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return raw[0] - raw[1]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    pictures, seconds = draw(scenario(), OUT)
    own = find_tool("ffmpeg", "HOWTO_FFMPEG")
    ffmpegs = sys.argv[1:] or [own] + [p for p in ["/usr/bin/ffmpeg"] if Path(p).exists() and Path(p).resolve() != Path(own).resolve()]
    ok = seconds <= 10
    print(f'{"PASS" if ok else "FAIL"}  Chromium drew {pictures} pictures in {seconds:.1f} s (10 or less)')
    for ffmpeg in ffmpegs:
        version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout.split()[2]
        alpha = subprocess.run(
            [ffmpeg, "-loglevel", "error", "-i", "000000.png", "-vf", "alphaextract,scale=1:1:flags=area,format=gray",
             "-f", "rawvideo", "-"], capture_output=True, check=True, cwd=OUT,
        ).stdout
        laid = (OUT / "laid.mp4").resolve()
        began = time.perf_counter()
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x404850:s={W}x{H}:r=25:d={LENGTH}",
             "-f", "concat", "-safe", "0", "-i", "frames.txt",
             "-filter_complex", "[0:v][1:v]overlay=0:0:eof_action=repeat[v]", "-map", "[v]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-t", f"{LENGTH}", "-f", "mp4", str(laid)],
            check=True, cwd=OUT,
        )
        laying = time.perf_counter() - began
        # The second mark is a circle that starts at 9.0 s. At 8.5 s only the note is there.
        before, during = redness(ffmpeg, laid, 8.5), redness(ffmpeg, laid, 10.5)
        # One byte: the mean of the alpha of every pixel. A backslash may not stand in an f-string before Python 3.12.
        good = alpha == bytes(1) and before < 2 and during > 4
        ok &= good
        print(
            f'{"PASS" if good else "FAIL"}  ffmpeg {version}: the first picture is see-through: {alpha == bytes(1)}, '
            f"red before the mark {before}, with the mark {during}, laid on in {laying:.1f} s"
        )
    print(f"Look at {OUT / 'laid.mp4'}: the marks draw themselves, the rings spread, the notes are sharp.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
