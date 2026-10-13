"""The log of a desktop take: what the finished picture must show that the recording does not have.

Nothing is drawn on the monitor during a take. The stage writes down what
lies over the picture and when, and how much of the recording lies before
the take. The assembly reads it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..errors import RunError


@dataclass(frozen=True)
class Shown:
    """One thing that lies over the picture from `start` to `end`: a note, a title card, the ring of a click.

    The times are seconds since the take began.
    """

    kind: str
    start: float
    end: float
    html: str
    # Seconds its appearing takes. Its animations run that long.
    grow: float = 0.0
    # Seconds its leaving takes, before `end`.
    fade: float = 0.0


@dataclass(frozen=True)
class Move:
    """One move of the picture: from `start`, for `seconds`, to the part whose corner is `left`, `top`, enlarged by `factor`.

    The corner is in pixels of the picture. A factor of 1 with a corner of
    0, 0 is the whole picture again. The times are seconds since the take began.
    """

    start: float
    seconds: float
    left: float
    top: float
    factor: float


@dataclass(frozen=True)
class TakeLog:
    # The size of the picture.
    viewport: tuple[int, int]
    # Seconds of the recording that lie before the take.
    head: float = 0.0
    shown: tuple[Shown, ...] = ()
    # How many pixels of the recording one pixel of the picture is: 2 for a storyboard that zooms.
    scale: int = 1
    moves: tuple[Move, ...] = ()


def beside(video: Path) -> Path:
    """Where the log of a take lies: next to its recording."""
    return video.with_name("take.json")


def write(log: TakeLog, path: Path) -> None:
    path.write_text(json.dumps(asdict(log), indent=2), encoding="utf-8")


def read(path: Path) -> TakeLog:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        width, height = data["viewport"]
        return TakeLog(
            viewport=(int(width), int(height)),
            head=float(data["head"]),
            shown=tuple(Shown(**item) for item in data["shown"]),
            scale=int(data.get("scale", 1)),
            moves=tuple(Move(**item) for item in data.get("moves", ())),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RunError(f"{path}: not the log of a take: {exc}") from None
