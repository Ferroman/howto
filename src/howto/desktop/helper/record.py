"""The recording: ffmpeg films the monitor, and says when its first frame was taken."""
from __future__ import annotations

import collections
import re
import signal
import subprocess
import threading
import time

from .session import DISPLAY, RUNTIME

RECORDING = f"{RUNTIME}/take.mkv"
RATE = 25
START = re.compile(r"start: (\d+\.\d+)")
# A time on the wall clock is far larger than any time since the machine started.
WALL_CLOCK_FROM = 3e8


def command(width: int, height: int, out: str = RECORDING) -> list[str]:
    """The ffmpeg that films the whole monitor, with the pointer. As spike/desktop/grab.py measured it."""
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-y",
        "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(RATE), "-video_size", f"{width}x{height}", "-i", DISPLAY,
        # Quick to write and close to lossless: the assembly encodes the picture once more.
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", "-g", str(RATE), out,
    ]


def first_frame(start: float, wall: float, steady: float) -> float:
    """When the first frame was taken, on the steady clock that howto times a take with.

    ffmpeg prints the time of its first frame as `start:`. It stamps frames
    with the wall clock in some releases and with the steady clock in others.
    `wall` and `steady` are the two clocks read at one moment.
    """
    return start - (wall - steady) if start > WALL_CLOCK_FROM else start


class Recorder:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._said: collections.deque[str] = collections.deque(maxlen=12)

    def start(self, width: int, height: int) -> float:
        """Starts ffmpeg, and returns the time of its first frame."""
        wall, steady = time.time(), time.monotonic()
        process = subprocess.Popen(command(width, height), stderr=subprocess.PIPE, text=True, errors="replace")
        self._process = process
        found = None
        for line in process.stderr:
            self._said.append(line.rstrip())
            found = START.search(line)
            if found:
                break
        if found is None:
            raise RuntimeError("ffmpeg did not start recording:\n" + "\n".join(self._said))
        # Whatever ffmpeg says from now on is read, so that its pipe never fills, and kept for an error.
        threading.Thread(target=lambda: self._said.extend(line.rstrip() for line in process.stderr), daemon=True).start()
        return first_frame(float(found.group(1)), wall, steady)

    def stop(self) -> str:
        """Ends ffmpeg so that it finishes its file, and returns the path of the recording."""
        process, self._process = self._process, None
        if process is None:
            raise RuntimeError("nothing is being recorded")
        process.send_signal(signal.SIGINT)
        try:
            code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError("ffmpeg did not end the recording") from None
        # Told to stop, ffmpeg writes a whole file and ends with 255.
        if code not in (0, 255):
            raise RuntimeError(f"ffmpeg failed while recording (exit {code}):\n" + "\n".join(self._said))
        return RECORDING

    def abandon(self) -> None:
        """Ends a recording that nobody will fetch."""
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._process = None
