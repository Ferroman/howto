"""What a test needs to know about a recording, a GIF or a WebP: its colours, its size and its timing."""
from __future__ import annotations

import struct
import subprocess

import pytest

from howto.errors import RunError
from howto.tools import find_tool


def region(video, *, x, y, width, height):
    """The mean colour (r, g, b) of one region of the picture, for every frame of a video."""
    try:
        ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    except RunError:
        pytest.skip("ffmpeg is not installed")
    raw = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", str(video),
         "-vf", f"crop={width}:{height}:{x}:{y},scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]


def brightness(video, **where):
    return [sum(colour) / 3 for colour in region(video, **where)]


def redness(video, **where):
    return [red - green for red, green, _ in region(video, **where)]


def gif_frames(ffprobe, path):
    """The start and the length of each frame of a GIF, in seconds."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return [tuple(float(value) for value in line.split(",")[:2]) for line in out.split()]


def dimensions(ffprobe, path):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return tuple(int(value) for value in out.strip().split(",")[:2])


def webp(path):
    """The canvas size of an animated WebP, the milliseconds of each frame, and how often it loops (0: for ever)."""
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    at, canvas, times, loops = 12, None, [], None
    while at + 8 <= len(data):
        kind, length = data[at:at + 4], struct.unpack("<I", data[at + 4:at + 8])[0]
        body = data[at + 8:at + 8 + length]
        if kind == b"VP8X":
            canvas = (int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1)
        elif kind == b"ANIM":
            loops = int.from_bytes(body[4:6], "little")
        elif kind == b"ANMF":
            times.append(int.from_bytes(body[12:15], "little"))
        at += 8 + length + (length & 1)
    return canvas, times, loops
