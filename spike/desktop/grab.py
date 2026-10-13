"""Measurement: does ffmpeg's x11grab hold 25 frames a second, with the pointer, and say when its first frame was?

The monitor is black and turns white for 0.4 s at five known times. The
script finds the white frames in the recording and prints how far each is
from its time. It also counts the frames, and looks for the pointer where it
was put. The larger size runs twice, because a busy machine loses frames.

Run:  uv run python spike/desktop/grab.py
"""
from __future__ import annotations

import json
import subprocess

import box
from howto.tools import find_tool

FFMPEG = find_tool("ffmpeg", "HOWTO_FFMPEG")
FFPROBE = find_tool("ffprobe", "HOWTO_FFPROBE")


def frame_times(video) -> list[float]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    return [float(line.strip(",")) for line in out.split()]


def levels(video, part: str = "") -> list[int]:
    """The mean brightness of each frame, or of one part of it."""
    raw = subprocess.run(
        [FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", f"{part}scale=1:1:flags=area,format=gray",
         "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return list(raw)


def measure(width: int, height: int, run: int) -> bool:
    folder = f"grab-{width}-{run}"
    found = json.loads(box.inside("desk.py", "grab.py", args=[str(width), str(height)], out=folder))
    video = box.OUT / folder / "grab.mkv"
    times, bright = frame_times(video), levels(video)
    times = [t - times[0] for t in times]
    length = times[-1] + 0.04
    lost = 1 - len(times) / (length * 25)
    errors = []
    for flash in found["flashes"]:
        seen = next((t for t, level in zip(times, bright) if level > 128 and t > flash - 0.3), None)
        errors.append(float("inf") if seen is None else seen - flash)
    pointer = max(levels(video, "crop=32:32:196:196,")[-25:])
    ok = lost < 0.01 and all(abs(error) <= 0.1 for error in errors) and pointer >= 3
    print(
        f'{"PASS" if ok else "FAIL"}  {width}x{height} run {run}: {len(times)} frames in {length:.1f} s, '
        f'{lost * 100:.2f} % lost, clock={found["clock"]}, load={found["load"]:.1f}, '
        f'flashes off by {", ".join(f"{error * 1000:+.0f} ms" for error in errors)}, pointer level {pointer}'
    )
    return ok


def main() -> int:
    results = [measure(1920, 1080, 1), measure(3840, 2160, 1), measure(3840, 2160, 2)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
