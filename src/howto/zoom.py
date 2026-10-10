"""The arithmetic of a zoom and of a crop: which part of the page the viewer sees.

Two sets of pixels appear here. The *page* is the browser's viewport at its
own size. The *screen* is what the viewer sees, which is a part of the page,
enlarged. This module knows nothing about a browser, so it is tested without
one; `capture` measures the boxes and applies the result.

A crop is simpler: one fixed part of the window, at its own size.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Page pixels kept around a target, so that it never touches the edge of the picture.
MARGIN = 40.0
# An enlargement smaller than this is movement for nothing, and the picture stays wide.
MIN_FACTOR = 1.1
# Pixels kept around the element that a picture is cut to, so that its edge and a mark around it are in the picture.
CROP_MARGIN = 12


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Window:
    """The part of the page that fills the screen: its top left corner on the page, and the enlargement."""

    left: float
    top: float
    factor: float

    def to_screen(self, box: Box) -> Box:
        return Box(
            (box.x - self.left) * self.factor,
            (box.y - self.top) * self.factor,
            box.width * self.factor,
            box.height * self.factor,
        )

    def to_page(self, box: Box) -> Box:
        """A box that was measured on the zoomed screen, in the page's own pixels."""
        return Box(
            self.left + box.x / self.factor,
            self.top + box.y / self.factor,
            box.width / self.factor,
            box.height / self.factor,
        )


def on_screen(box: Box, viewport: tuple[int, int]) -> bool:
    """Whether the whole box lies inside a page of this size."""
    width, height = viewport
    return box.x >= 0 and box.y >= 0 and box.x + box.width <= width and box.y + box.height <= height


def frame(box: Box, viewport: tuple[int, int], factor: float) -> Window | None:
    """The window that shows `box` enlarged, or None when the picture should stay wide.

    The window is centred on the box and then moved back inside the page, so
    a control in a corner is shown with what is next to it and no empty space
    comes into the picture. The enlargement is lowered until the box fits with
    a margin, because a zoom that cuts its own target helps nobody.
    """
    width, height = viewport
    fit = min(factor, width / (box.width + 2 * MARGIN), height / (box.height + 2 * MARGIN))
    if fit < MIN_FACTOR:
        return None
    centre_x, centre_y = box.x + box.width / 2, box.y + box.height / 2
    left = min(max(centre_x - width / (2 * fit), 0.0), width - width / fit)
    top = min(max(centre_y - height / (2 * fit), 0.0), height - height / fit)
    return Window(left=left, top=top, factor=fit)


def inside(box: Box, outer: Box) -> bool:
    """Whether the whole box lies inside another."""
    return (
        box.x >= outer.x
        and box.y >= outer.y
        and box.x + box.width <= outer.x + outer.width
        and box.y + box.height <= outer.y + outer.height
    )


def _even_down(value: float) -> int:
    return 2 * math.floor(value / 2)


def _even_up(value: float) -> int:
    return 2 * math.ceil(value / 2)


def crop(box: Box, viewport: tuple[int, int]) -> Box | None:
    """The part of the window that a picture of this element is cut to.

    Its corner and its size are even numbers of pixels. The recording keeps
    colour for every second pixel only, and ffmpeg moves a cut that does not
    fall on those pixels to the next one that does.

    None for an element that has no size or lies outside the window: a margin
    alone is not a picture.
    """
    width, height = viewport
    if box.width <= 0 or box.height <= 0:
        return None
    if box.x >= width or box.y >= height or box.x + box.width <= 0 or box.y + box.height <= 0:
        return None
    left = max(0, _even_down(box.x - CROP_MARGIN))
    top = max(0, _even_down(box.y - CROP_MARGIN))
    right = min(width, _even_up(box.x + box.width + CROP_MARGIN))
    bottom = min(height, _even_up(box.y + box.height + CROP_MARGIN))
    return Box(left, top, right - left, bottom - top)


def strip(crop: Box, height: float, viewport: tuple[int, int]) -> tuple[Box, bool]:
    """Where the notes of a cropped picture go: a strip as wide as the crop, and whether it lies outside the crop.

    A note that lay on the crop would cover what it explains, and a crop is
    often small. So the strip goes under the crop, and the picture grows by
    it. At the bottom of the window it goes above. A crop as tall as the
    window leaves no room, and there the strip is the lowest part of the crop.
    """
    tall = min(_even_up(height), crop.height)
    below = crop.y + crop.height
    if below + tall <= viewport[1]:
        return Box(crop.x, below, crop.width, tall), True
    if crop.y - tall >= 0:
        return Box(crop.x, crop.y - tall, crop.width, tall), True
    return Box(crop.x, below - tall, crop.width, tall), False


def union(a: Box, b: Box) -> Box:
    """The smallest box that holds both."""
    left, top = min(a.x, b.x), min(a.y, b.y)
    right, bottom = max(a.x + a.width, b.x + b.width), max(a.y + a.height, b.y + b.height)
    return Box(left, top, right - left, bottom - top)
