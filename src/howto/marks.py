"""Marks drawn on the picture: where they go, and the SVG that draws them.

A mark is aimed at a box in screen pixels, which is what the browser reports
for an element, zoomed or not. This module knows nothing about a browser, so
it is tested without one; `capture` measures the box and shows the result.

The recorder removes every script from what it is given, so nothing here
moves by script. A stroke appears as if a hand drew it because a CSS
animation shortens the gap of its dash pattern.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass
from typing import Callable, Sequence

from .zoom import Box

Point = tuple[float, float]

ACCENT = "#ff3b30"
STROKE = 5
# Screen pixels between a target and the box or the line drawn around it.
PAD = 8.0
# The longest that a mark takes to appear. A take waits this long before it goes on.
DRAW_MS = 600
# How long marks take to leave.
FADE_MS = 250
# Set to 0 on <html>, this fades every mark out. The page cannot reach into the
# recorder's layer to do it, but a custom property is inherited there.
FADE_PROPERTY = "--howto-marks"

ARROW_LENGTH = 150.0
ARROW_GAP = 14.0
ARROW_HEAD = 22.0
WORDS_FONT = 22
WORDS_GAP = 8.0

STYLE = (
    "<style>"
    "@keyframes howto-draw{to{stroke-dashoffset:0}}"
    "@keyframes howto-appear{to{opacity:1}}"
    f".howto-stroke{{fill:none;stroke:{ACCENT};stroke-width:{STROKE};stroke-linecap:round;stroke-linejoin:round;"
    "stroke-dasharray:1;stroke-dashoffset:1;animation:howto-draw var(--ms) ease-out forwards}"
    ".howto-appear{opacity:0;animation:howto-appear var(--ms) ease-out var(--wait,0ms) forwards}"
    "</style>"
)


@dataclass(frozen=True)
class Drawing:
    """One mark: what goes into the SVG, and any HTML that lies on top of it."""

    svg: str
    html: str = ""


@dataclass(frozen=True)
class Arrow:
    """One way to draw an arrow at a target: from `tail`, bent towards `bend`, to `tip`."""

    tail: Point
    bend: Point
    tip: Point
    note: str | None = None
    # Roughly where the words are. The browser sizes them; this is for the check below.
    words: Box | None = None
    # Which way the words lie from the tail: -1, 0 or 1 for each axis.
    lies: tuple[int, int] = (0, 0)

    @property
    def points(self) -> tuple[Point, ...]:
        """Points along the shaft and across the words. The emptiest candidate is the one where few of them lie on something."""
        (x0, y0), (x1, y1), (x2, y2) = self.tail, self.bend, self.tip
        found = []
        for i in range(11):
            t = i / 10
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            found.append((a * x0 + b * x1 + c * x2, a * y0 + b * y1 + c * y2))
        if self.words is not None:
            for column in range(5):
                for row in range(3):
                    found.append(
                        (self.words.x + self.words.width * column / 4, self.words.y + self.words.height * row / 2)
                    )
        return tuple(found)


def _stroke(d: str, ms: int) -> str:
    # pathLength makes the dash pattern count in parts of the whole path, so no length is measured.
    return f'<path class="howto-stroke" pathLength="1" style="--ms:{ms}ms" d="{d}"/>'


def _rounded(box: Box, radius: float) -> str:
    """The path of a rectangle with round corners."""
    x, y, w, h = box.x, box.y, box.width, box.height
    r = min(radius, w / 2, h / 2)
    return (
        f"M{x + r:.1f} {y:.1f}H{x + w - r:.1f}Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}"
        f"V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}"
        f"H{x + r:.1f}Q{x:.1f} {y + h:.1f} {x:.1f} {y + h - r:.1f}"
        f"V{y + r:.1f}Q{x:.1f} {y:.1f} {x + r:.1f} {y:.1f}Z"
    )


def _around(target: Box, pad: float) -> Box:
    return Box(target.x - pad, target.y - pad, target.width + 2 * pad, target.height + 2 * pad)


def box(target: Box, viewport: tuple[int, int]) -> Drawing:
    return Drawing(_stroke(_rounded(_around(target, PAD), 10), 600))


def loop(target: Box) -> tuple[Point, ...]:
    """The points of a circle as a hand draws it: it leans a little, and it overlaps where it closes.

    An ellipse through the corners of a box is 1.41 times the box. This one
    starts wider and ends narrower than its middle, and never comes inside.
    """
    cx, cy = target.x + target.width / 2, target.y + target.height / 2
    rx, ry = target.width / 2 * 1.5 + 6, target.height / 2 * 1.5 + 6
    # Less for a long, flat target: there the same lean would carry the ends into it.
    longer = max(target.width, target.height)
    lean = math.radians(-4) * (min(target.width, target.height) / longer if longer else 1.0)
    steps = 72
    points = []
    for i in range(steps + 1):
        t = i / steps
        angle = math.radians(-205 + 400 * t)
        size = 1.04 - 0.08 * t
        px, py = rx * size * math.cos(angle), ry * size * math.sin(angle)
        points.append(
            (cx + px * math.cos(lean) - py * math.sin(lean), cy + px * math.sin(lean) + py * math.cos(lean))
        )
    return tuple(points)


def circle(target: Box, viewport: tuple[int, int]) -> Drawing:
    return Drawing(_stroke("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in loop(target)), 600))


def underline(target: Box, viewport: tuple[int, int]) -> Drawing:
    left, right, y = target.x - 2, target.x + target.width + 2, target.y + target.height + 5
    # Not quite straight, as a pen is not.
    return Drawing(_stroke(f"M{left:.1f} {y:.1f}Q{(left + right) / 2:.1f} {y + 5:.1f} {right:.1f} {y - 1:.1f}", 400))


def spotlight(target: Box, viewport: tuple[int, int]) -> Drawing:
    """Everything but the target goes dark: the whole picture, with a hole in it."""
    width, height = viewport
    hole = _rounded(_around(target, PAD + 2), 12)
    return Drawing(
        f'<path class="howto-appear" style="--ms:300ms" fill="rgba(8,10,16,.62)" fill-rule="evenodd" '
        f'd="M0 0H{width}V{height}H0Z{hole}"/>'
    )


# The marks that need nothing but their target. An arrow also asks the page which side is free.
SHAPES: dict[str, Callable[[Box, tuple[int, int]], Drawing]] = {
    "box": box,
    "circle": circle,
    "underline": underline,
    "spotlight": spotlight,
}


def arrows(target: Box, viewport: tuple[int, int], note: str | None = None) -> tuple[Arrow, ...]:
    """Eight ways to draw an arrow at a target, one from each side.

    The one whose tail lies towards the middle of the picture comes first,
    because there is usually room there, and its neighbours follow.
    """
    width, height = viewport
    cx, cy = target.x + target.width / 2, target.y + target.height / 2
    middle = math.atan2(height / 2 - cy, width / 2 - cx)
    angles = sorted(
        (k * math.pi / 4 for k in range(8)),
        key=lambda angle: round(abs(math.remainder(angle - middle, math.tau)), 9),
    )
    found = []
    for angle in angles:
        ux, uy = math.cos(angle), math.sin(angle)
        # Where a ray from the centre leaves the target, and a gap further.
        reach = min(
            (target.width / 2 + ARROW_GAP) / abs(ux) if abs(ux) > 1e-6 else math.inf,
            (target.height / 2 + ARROW_GAP) / abs(uy) if abs(uy) > 1e-6 else math.inf,
        )
        tip = (cx + ux * reach, cy + uy * reach)
        tail = (tip[0] + ux * ARROW_LENGTH, tip[1] + uy * ARROW_LENGTH)
        sideways = 0.16 * ARROW_LENGTH
        bend = ((tip[0] + tail[0]) / 2 - uy * sideways, (tip[1] + tail[1]) / 2 + ux * sideways)
        lies = (round(ux), round(uy))
        words = None
        if note is not None:
            w, h = 0.58 * WORDS_FONT * len(note) + 28, WORDS_FONT * 1.35 + 12
            ax, ay = tail[0] + lies[0] * WORDS_GAP, tail[1] + lies[1] * WORDS_GAP
            words = Box(ax - w / 2 + lies[0] * w / 2, ay - h / 2 + lies[1] * h / 2, w, h)
        found.append(Arrow(tail=tail, bend=bend, tip=tip, note=note, words=words, lies=lies))
    return tuple(found)


def emptiest(candidates: Sequence[Arrow], busy: Sequence[int]) -> Arrow:
    """The candidate with the fewest points on something. Of two that are as empty, the earlier one."""
    return candidates[min(range(len(candidates)), key=lambda i: busy[i])]


def arrow(chosen: Arrow) -> Drawing:
    (x0, y0), (x1, y1), (x2, y2) = chosen.tail, chosen.bend, chosen.tip
    shaft = _stroke(f"M{x0:.1f} {y0:.1f}Q{x1:.1f} {y1:.1f} {x2:.1f} {y2:.1f}", 450)
    # The head points the way the shaft arrives, which is not the way it set out.
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    hx, hy = (x2 - x1) / length, (y2 - y1) / length
    wings = []
    for turn in (math.radians(152), math.radians(-152)):
        wx = hx * math.cos(turn) - hy * math.sin(turn)
        wy = hx * math.sin(turn) + hy * math.cos(turn)
        wings.append((x2 + wx * ARROW_HEAD, y2 + wy * ARROW_HEAD))
    head = (
        f'<path class="howto-appear" style="--ms:150ms;--wait:400ms" fill="none" stroke="{ACCENT}" '
        f'stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round" '
        f'd="M{wings[0][0]:.1f} {wings[0][1]:.1f}L{x2:.1f} {y2:.1f}L{wings[1][0]:.1f} {wings[1][1]:.1f}"/>'
    )
    words = ""
    if chosen.note is not None:
        sx, sy = chosen.lies
        # Hung on the tail by the edge that faces it, so the browser may make the box as wide as the words need.
        words = (
            f'<div class="howto-appear" style="--ms:300ms;position:absolute;'
            f"left:{x0 + sx * WORDS_GAP:.1f}px;top:{y0 + sy * WORDS_GAP:.1f}px;"
            f"transform:translate({-50 + 50 * sx}%,{-50 + 50 * sy}%);"
            f"padding:6px 14px;border-radius:9px;background:{ACCENT};color:#fff;white-space:nowrap;"
            f"font:600 {WORDS_FONT}px/1.35 system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.35)"
            f'">{html.escape(chosen.note)}</div>'
        )
    return Drawing(shaft + head, words)


def layer(drawing: Drawing, viewport: tuple[int, int]) -> str:
    """The overlay that shows one mark over a picture of this size.

    Playwright's own stylesheet sets every `svg` to a height of 0, and an
    attribute does not outrank a stylesheet, so the size is an inline style.
    """
    width, height = viewport
    return (
        f'{STYLE}<div style="position:absolute;inset:0;opacity:var({FADE_PROPERTY},1);'
        f'transition:opacity {FADE_MS}ms ease-in">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="position:absolute;left:0;top:0;width:{width}px;height:{height}px;overflow:visible;'
        f'filter:drop-shadow(0 2px 3px rgba(0,0,0,.5))">{drawing.svg}</svg>{drawing.html}</div>'
    )
