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


def crop(box: Box, viewport: tuple[int, int]) -> Box | None:
    """The part of the window that a picture of this element is cut to, in whole pixels.

    None for an element that has no size or lies outside the window: a margin
    alone is not a picture.
    """
    width, height = viewport
    if box.width <= 0 or box.height <= 0:
        return None
    if box.x >= width or box.y >= height or box.x + box.width <= 0 or box.y + box.height <= 0:
        return None
    left = max(0, math.floor(box.x) - CROP_MARGIN)
    top = max(0, math.floor(box.y) - CROP_MARGIN)
    right = min(width, math.ceil(box.x + box.width) + CROP_MARGIN)
    bottom = min(height, math.ceil(box.y + box.height) + CROP_MARGIN)
    return Box(left, top, right - left, bottom - top)
