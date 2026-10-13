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


def curve(first: float, changes, clock: str) -> str:
    """An ffmpeg expression for a value that eases from `first` to each `to` of [(start, seconds, to)].

    Between two changes the value stays. A change without seconds is a jump.
    As spike/desktop/README.md measured it.
    """
    parts, before = [], first
    for start, seconds, to in changes:
        parts.append((start, seconds, before, to))
        before = to
    text = f"{before:.6f}"
    for start, seconds, origin, to in reversed(parts):
        if seconds <= 0:
            text = f"if(lt({clock},{start:.3f}),{origin:.6f},{text})"
            continue
        part = f"(({clock}-{start:.3f})/{seconds:.3f})"
        eased = f"({origin:.6f}+{to - origin:.6f}*{part}*{part}*(3-2*{part}))"
        text = f"if(lt({clock},{start + seconds:.3f}),if(lt({clock},{start:.3f}),{origin:.6f},{eased}),{text})"
    return text


def sized(log: TakeLog) -> str:
    """The filters that bring the recording to the size of the picture, with the moves of its zooms.

    Empty for a recording of the picture's own size. Else it starts with a
    comma, to follow the filter before it.

    What moves evenly is the part of the picture that is shown, 1 / factor,
    and its corner. `zoompan` cuts that part out of the recording: at a
    factor of 2 it is a cut at the recording's own size, so the text is as
    sharp as the app drew it. `it` is the time of the frame that goes in,
    which starts at 0 with the take, because the head is left out before.
    """
    width, height = log.viewport
    if log.scale == 1:
        return ""
    if not log.moves:
        return f",scale={width}:{height}:flags=area"
    share = curve(1.0, [(move.start, move.seconds, 1 / move.factor) for move in log.moves], "it")
    left = curve(0.0, [(move.start, move.seconds, move.left) for move in log.moves], "it")
    top = curve(0.0, [(move.start, move.seconds, move.top) for move in log.moves], "it")
    return (
        f",zoompan=z='1/({share})':x='{log.scale}*({left})':y='{log.scale}*({top})'"
        f":d=1:s={width}x{height}:fps={RATE}"
    )


def graph(layer: Layer, then: str | None = None) -> str:
    """The filter graph of a desktop take. Input 0 is the recording, input 1 the pictures of the overlay. The result is `[v]`.

    `then` is a chain of filters that the picture goes through after the
    overlay: the cut and the scaling of an animated picture.
    """
    after = f",{then}" if then else ""
    base = f"[0:v]fps={RATE}{sized(layer.log)}"
    if layer.frames is None:
        return f"{base}{after}[v]"
    # The last picture stays to the end of the take: it is what the layer shows from its time on.
    return f"{base}[base];[base][1:v]overlay=0:0:eof_action=repeat{after}[v]"
