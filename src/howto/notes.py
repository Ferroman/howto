"""The HTML of what lies over a picture: the note of a step, the strip of a cropped picture, a title card, the ring of a click.

The browser stage shows the first two as overlays of the recorder. The
desktop stage has no recorder that draws, so `overlay` draws all four after
the take, from the same HTML.
"""
from __future__ import annotations

import html

from . import zoom

# The note has a z-index because a spotlight would otherwise darken it: the
# marks are shown after it, and what is shown later lies on top.
NOTE_STYLE = (
    "position:fixed;z-index:2;left:50%;bottom:48px;transform:translateX(-50%);max-width:70%;"
    "padding:14px 22px;border-radius:10px;background:rgba(20,20,24,.88);color:#fff;"
    "font:500 22px/1.35 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35)"
)
# In a picture that is cut to a crop, a note is not laid on the page: it is
# written in a strip next to the crop, which `zoom.strip` places. The strip is
# dark for the whole take, so that the page under it never shows.
STRIP_COLOUR = "#17171c"
STRIP_STYLE = (
    f"box-sizing:border-box;padding:10px 14px;background:{STRIP_COLOUR};color:#fff;text-align:center;"
    "font:500 18px/1.35 system-ui,sans-serif"
)
# How tall each note is in a strip of this width. It is measured in the page
# with the page's own styles switched off, because the overlay layer cannot be
# measured from outside.
STRIP_HEIGHTS = """([texts, width, style]) => texts.map((text) => {
  const probe = document.createElement('div');
  probe.style.cssText = `all:initial;display:block;position:fixed;visibility:hidden;left:0;top:0;width:${width}px;${style}`;
  probe.textContent = text;
  document.documentElement.appendChild(probe);
  const height = probe.getBoundingClientRect().height;
  probe.remove();
  return height;
})"""
# The title card of a desktop video fades in and out as the card of the
# browser's recorder does (Playwright 1.63.0, `overlay.chapter`).
CARD_FADE_MS = 300
# How long the ring of a click spreads.
RING_MS = 450


def _placed(box: zoom.Box) -> str:
    return f"position:fixed;left:{box.x:g}px;top:{box.y:g}px;width:{box.width:g}px;height:{box.height:g}px"


def note_html(text: str, strip: zoom.Box | None = None) -> str:
    """The note of a step: a box at the bottom of the window, or the words in the strip of a cropped picture."""
    if strip is None:
        return f'<div style="{NOTE_STYLE}">{html.escape(text)}</div>'
    return (
        f'<div style="{_placed(strip)};z-index:2;display:flex;align-items:center;justify-content:center;{STRIP_STYLE}">'
        f"{html.escape(text)}</div>"
    )


def strip_html(strip: zoom.Box) -> str:
    """The strip with no words in it."""
    return f'<div style="{_placed(strip)};z-index:1;background:{STRIP_COLOUR}"></div>'


def card_html(title: str) -> str:
    """The title card of a chapter, drawn as the browser's recorder draws it, without the blur behind it.

    The recorder blurs the page behind its card. Here the card is laid on the
    recording afterwards, where there is no page to blur.
    """
    return (
        "<style>@keyframes howto-card{from{opacity:0}to{opacity:1}}</style>"
        '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
        f'animation:howto-card {CARD_FADE_MS}ms ease-out forwards">'
        '<div style="background:rgba(0,0,0,.7);border:1px solid rgba(255,255,255,.15);border-radius:16px;'
        'padding:40px 56px;max-width:560px;box-shadow:0 8px 32px rgba(0,0,0,.4)">'
        '<div style="color:#fff;font-family:system-ui,-apple-system,sans-serif;font-size:28px;font-weight:600;'
        f'line-height:1.3;text-align:center;letter-spacing:-.01em">{html.escape(title)}</div></div></div>'
    )


def ring_html(x: float, y: float) -> str:
    """A ring that spreads from the point of a click and fades. The pointer of a desktop shows no click itself."""
    return (
        "<style>@keyframes howto-ring{from{transform:translate(-50%,-50%) scale(.3);opacity:.95}"
        "to{transform:translate(-50%,-50%) scale(1);opacity:0}}</style>"
        f'<div style="position:absolute;left:{x:.1f}px;top:{y:.1f}px;width:56px;height:56px;border-radius:50%;'
        "box-sizing:border-box;border:4px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.45),inset 0 0 0 2px rgba(0,0,0,.45);"
        f'animation:howto-ring {RING_MS}ms ease-out forwards"></div>'
    )
