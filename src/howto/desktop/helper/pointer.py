"""The path of the pointer: from where it is to a target, slow at both ends and quick in the middle."""
from __future__ import annotations

HZ = 60


def ease(part: float) -> float:
    return part * part * (3 - 2 * part)


def path(start: tuple[int, int], end: tuple[int, int], seconds: float, hz: int = HZ) -> list[tuple[int, int]]:
    """The points the pointer passes, one for each 1/hz of a second. The last one is the target itself."""
    steps = max(1, round(seconds * hz))
    (x0, y0), (x1, y1) = start, end
    return [
        (round(x0 + (x1 - x0) * ease(step / steps)), round(y0 + (y1 - y0) * ease(step / steps)))
        for step in range(1, steps + 1)
    ]


def script(points: list[tuple[int, int]], seconds: float) -> str:
    """The same path as the commands that `xdotool -` reads."""
    pause = seconds / len(points) if seconds > 0 else 0.0
    lines = []
    for x, y in points:
        lines.append(f"mousemove {x} {y}")
        if pause:
            lines.append(f"sleep {pause:.4f}")
    return "\n".join(lines) + "\n"
