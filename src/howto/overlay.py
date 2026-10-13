"""Draws what lies over the recording of a desktop take: the notes, the title cards and the rings of the clicks.

Nothing is drawn on the monitor during a desktop take. A note there would be
read by the OCR, would take the keyboard from the app, and would need a web
engine in the image. So the stage writes down what lies over the picture and
when, and this module draws it afterwards with the Chromium that howto has:
one PNG picture with transparency for each moment at which the layer
changes. ffmpeg lays the pictures on the recording.

An animation is not left to run. For each picture every animation is set to
its time by hand, so the pictures do not depend on how fast the machine is.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from .desktop.takelog import Shown, TakeLog
from .notes import STRIP_HEIGHTS, STRIP_STYLE
from .errors import RunError

FPS = 25
# For each thing that is shown: its index, the milliseconds since it appeared or None once it has grown, its opacity.
State = tuple[tuple[int, "int | None", float], ...]
PAGE = (
    "<!doctype html><html><head><style>html,body{margin:0;background:transparent;overflow:hidden}"
    ".item{position:absolute;inset:0;display:none}</style></head><body>ITEMS</body></html>"
)
# Shows the things of one state, each with its animations set to its age.
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


def state(shown: Sequence[Shown], at: float) -> State:
    """What lies over the picture at one moment of the take."""
    found = []
    for index, item in enumerate(shown):
        if not item.start <= at < item.end:
            continue
        age = at - item.start
        grown = None if age >= item.grow - 1e-9 else round(age * 1000)
        left = item.end - at
        opacity = 1.0 if item.fade <= 0 or left >= item.fade else round(left / item.fade, 3)
        found.append((index, grown, opacity))
    return tuple(found)


def frame_count(length: float) -> int:
    """How many frames a take of this length has. A part of one counts as a whole."""
    return max(1, math.ceil(length * FPS - 1e-6))


def changes(shown: Sequence[Shown], length: float) -> list[tuple[int, State]]:
    """The number of each frame at which the layer changes, with what it shows from then on."""
    plan: list[tuple[int, State]] = []
    for number in range(frame_count(length)):
        # A hair past the frame's own time, so that 0.2 s is frame 5 whatever the arithmetic makes of 5 / 25.
        now = state(shown, number / FPS + 1e-9)
        if not plan or now != plan[-1][1]:
            plan.append((number, now))
    return plan


def listing(numbers: Sequence[int], total: int) -> str:
    """The list from which ffmpeg reads the pictures, each with the time it is shown."""
    lines = ["ffconcat version 1.0"]
    for number, following in zip(numbers, [*numbers[1:], max(total, numbers[-1] + 1)]):
        lines.append(f"file '{number:06d}.png'\nduration {(following - number) / FPS:.2f}")
    # ffmpeg reads the time of the last picture only when the picture is named once more.
    lines.append(f"file '{numbers[-1]:06d}.png'")
    return "\n".join(lines) + "\n"


def draw(log: TakeLog, length: float, out_dir: Path) -> Path | None:
    """Draws the pictures of a take into `out_dir`, and returns the path of their list.

    None for a take that shows nothing: the assembly then has no layer to lay on.
    """
    if not log.shown:
        return None
    from playwright.sync_api import Error, sync_playwright

    plan = changes(log.shown, length)
    items = "".join(f'<div class="item">{item.html}</div>' for item in log.shown)
    width, height = log.viewport
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.set_content(PAGE.replace("ITEMS", items))
                for number, shown in plan:
                    page.evaluate(SET, [list(one) for one in shown])
                    page.screenshot(path=str(out_dir / f"{number:06d}.png"), omit_background=True)
            finally:
                browser.close()
    except Error as exc:
        lines = str(exc).strip().splitlines()
        raise RunError(f"cannot draw the notes of the take: {lines[0] if lines else type(exc).__name__}") from None
    frames = out_dir / "frames.txt"
    frames.write_text(listing([number for number, _ in plan], frame_count(length)), encoding="utf-8")
    return frames


def strip_heights(texts: Sequence[str], width: float) -> list[float]:
    """How tall each note is in a strip of this width.

    The browser stage measures this in the page it films. A desktop has no
    page, so it is measured in the Chromium that draws the overlay, where the
    words have the size they will have in the picture.
    """
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            # Ctrl+C stays with howto, which acts on it when this has returned.
            browser = playwright.chromium.launch(headless=True, handle_sigint=False)
            try:
                page = browser.new_page(viewport={"width": max(1, round(width)), "height": 600}, device_scale_factor=1)
                return [float(height) for height in page.evaluate(STRIP_HEIGHTS, [list(texts), width, STRIP_STYLE])]
            finally:
                browser.close()
    except Error as exc:
        lines = str(exc).strip().splitlines()
        raise RunError(f"cannot measure the notes of the picture: {lines[0] if lines else type(exc).__name__}") from None
