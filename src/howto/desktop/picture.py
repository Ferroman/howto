"""The ffmpeg filters that turn the recording of a desktop take into the picture.

The recording is the monitor as it was. The picture is the recording with
what the stage wrote into the log of the take laid over it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .takelog import TakeLog

RATE = 25


@dataclass(frozen=True)
class Layer:
    """What the assembly needs of a desktop take besides its recording."""

    log: TakeLog
    # The list of the pictures that lie over the recording. None when nothing does.
    frames: Path | None = None


def graph(layer: Layer) -> str:
    """The filter graph of a desktop take. Input 0 is the recording, input 1 the pictures of the overlay. The result is `[v]`."""
    base = f"[0:v]fps={RATE}"
    if layer.frames is None:
        return f"{base}[v]"
    # The last picture stays to the end of the take: it is what the layer shows from its time on.
    return f"{base}[base];[base][1:v]overlay=0:0:eof_action=repeat[v]"
