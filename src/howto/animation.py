"""Turns the recording of a silent take into a picture that loops: a GIF, a WebP, or both.

Both are built from the same frames. ffmpeg writes a frame only when the
picture changed, each under the number it has among all frames, so the time a
frame is shown is the distance to the next number. A still picture then
costs almost nothing. Each frame's time is handed to the encoders, because an
encoder that drops repeated frames itself does not know how long the last
one was shown, and the pause at the end of the loop would be lost.
"""
from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .desktop import picture
from .errors import RunError
from .tools import run
from .zoom import Box

# Frames a second: half of what the recorder gives. Twice as many would
# double the file for movement that is hardly smoother.
FPS = 12.5
FORMATS = ("gif", "webp")
# Seconds at the start of the recording that the picture leaves out. The
# recorder's first frame is taken before its overlays are drawn, so the strip
# for the notes is missing from it, and the picture would flash at every loop.
# A take begins with half a second in which nothing happens, so nothing is lost.
HEAD = 0.2
# One palette for the whole picture, made from what changes between frames.
# No dither: its noise differs from frame to frame, so that no frame repeats,
# and a GIF was a quarter smaller without it. An interface has few colours, so
# the bands that dither hides are rare.
PALETTE = "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle"
# The palette of a desktop picture is made from whole frames. `stats_mode=diff` counts, where a frame differs
# from the one before, the colours that the frame before had there. The recording of a browser has noise in
# every frame, so every colour is counted sooner or later. The recording of a desktop has none. What appears
# and stays to the end, a dialog or a last row in a list, would never be counted, and would be drawn in the
# nearest colour that something else has.
PALETTE_WHOLE = "split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=none:diff_mode=rectangle"


@dataclass(frozen=True)
class Picture:
    files: dict[str, Path]
    width: int
    height: int
    seconds: float


def size(crop: Box | None, viewport: tuple[int, int], width: int) -> tuple[int, int]:
    """The size of the picture: the crop or the window, scaled down to `width` when it is wider."""
    own = (int(crop.width), int(crop.height)) if crop is not None else viewport
    if own[0] <= width:
        return own
    return width, max(1, round(own[1] * width / own[0]))


def filters(crop: Box | None, viewport: tuple[int, int], width: int) -> str:
    """The ffmpeg filters that turn the recording into the frames of the picture."""
    chain = []
    if crop is not None:
        chain.append(f"crop={int(crop.width)}:{int(crop.height)}:{int(crop.x)}:{int(crop.y)}")
    chain.append(f"fps={FPS:g}")
    scaled = size(crop, viewport, width)
    if scaled != ((int(crop.width), int(crop.height)) if crop is not None else viewport):
        chain.append(f"scale={scaled[0]}:{scaled[1]}:flags=lanczos")
    # Last, so that it compares what the viewer will see. It drops a frame
    # that differs from the one before only by the recorder's noise.
    chain.append("mpdecimate")
    return ",".join(chain)


def frames_command(ffmpeg: str, video: Path, start: float, length: float, chain: str) -> list[str]:
    """Writes the frames that differ as PNG files into the current directory, named by their number."""
    return [
        ffmpeg, "-y", "-loglevel", "error",
        # Before the input: the recorder runs on after the take, and the picture ends with the take.
        "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(video), "-an",
        "-vf", chain,
        # vfr keeps the gaps that the dropped frames left, and frame_pts names each file by its place in time.
        "-fps_mode", "vfr", "-frame_pts", "1",
        "%06d.png",
    ]


def frame_count(length: float) -> int:
    """How many frame times a take of this length has. A part of one counts as a whole: the picture never ends early."""
    return math.ceil(length * FPS - 1e-6)


def shown(numbers: Sequence[int], total: int) -> list[int]:
    """For how many frame times each kept frame is shown: until the next one, and the last one to the end."""
    first = numbers[0]
    places = [number - first for number in numbers]
    end = max(total, places[-1] + 1)
    return [following - place for place, following in zip(places, (*places[1:], end))]


def listing(names: Sequence[str], counts: Sequence[int]) -> str:
    """The list from which ffmpeg reads the frames, each with the time it is shown."""
    lines = ["ffconcat version 1.0"]
    for name, count in zip(names, counts):
        lines.append(f"file '{name}'\nduration {count / FPS:.2f}")
    return "\n".join(lines) + "\n"


def desktop_frames_command(
    ffmpeg: str, video: Path, head: float, length: float, graph: str, overlay: str | None
) -> list[str]:
    """The same frames from the recording of a desktop take.

    The part of the recording before the take is left out, and the overlay
    is laid on before the picture is cut. `overlay` is the list of the
    overlay's pictures, as ffmpeg finds it from the folder it runs in.
    """
    command = [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{head:.3f}", "-t", f"{length:.3f}", "-i", str(video)]
    if overlay is not None:
        command += ["-f", "concat", "-safe", "0", "-i", overlay]
    return command + [
        "-an", "-filter_complex", graph, "-map", "[v]",
        "-fps_mode", "vfr", "-frame_pts", "1",
        "%06d.png",
    ]


def gif_command(ffmpeg: str, frames: Path, last: int, out: Path, palette: str = PALETTE) -> list[str]:
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "concat", "-i", str(frames),
        "-vf", palette,
        "-fps_mode", "vfr",
        # A GIF frame is shown until the next one, and the last has none. Its time is given in 1/100 s.
        "-final_delay", str(round(last * 100 / FPS)),
        "-loop", "0",
        # The temporary name does not end in .gif, so the format is named here.
        "-f", "gif", str(out),
    ]


def webp_command(img2webp: str, frames: Sequence[tuple[Path, int]], out: Path) -> list[str]:
    command = [img2webp, "-loop", "0", "-lossy", "-q", "80", "-m", "4"]
    for path, count in frames:
        command += ["-d", str(round(count * 1000 / FPS)), str(path)]
    return command + ["-o", str(out)]


def animate(
    *,
    video: Path,
    length: float,
    crop: Box | None,
    viewport: tuple[int, int],
    width: int,
    formats: Sequence[str],
    name: str,
    out_dir: Path,
    work: Path,
    ffmpeg: str,
    img2webp: str | None,
    layer: "picture.Layer | None" = None,
) -> Picture:
    """Writes NAME.gif, NAME.webp or both. A failure leaves earlier pictures of that name as they were."""
    frames_dir = work / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    # ffmpeg reads a % in the name of a frame as a place for its number, and
    # the path of the work directory may hold one. So it runs inside the
    # directory, and the list below names the frames without a path. The list
    # itself is named without one too: ffmpeg 6 puts the folder of the list in
    # front of every frame in it.
    if layer is None:
        # A take that is hardly longer than the head is kept whole: a flash is better than no picture.
        start = HEAD if length > 2 * HEAD else 0.0
        length -= start
        command = frames_command(ffmpeg, video.resolve(), start, length, filters(crop, viewport, width))
    else:
        # A desktop take has no such head, because its overlay is laid on here, and so on its first frame too.
        # What it leaves out is the part of the recording before the take. The list of the overlay's pictures
        # is named from the folder of the frames, which keeps the name of the work folder out of the path.
        listed = os.path.relpath(layer.frames, frames_dir) if layer.frames is not None else None
        command = desktop_frames_command(
            ffmpeg, video.resolve(), layer.log.head, length, picture.graph(layer, filters(crop, viewport, width)), listed
        )
    run(command, "ffmpeg (frames)", cwd=frames_dir)
    names = sorted(path.name for path in frames_dir.glob("*.png"))
    if not names:
        raise RunError(f"ffmpeg (frames): no picture in {video}")
    counts = shown([int(Path(name_).stem) for name_ in names], frame_count(length))
    frames = frames_dir / "frames.txt"
    frames.write_text(listing(names, counts), encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    final = {kind: out_dir / f"{name}.{kind}" for kind in FORMATS if kind in formats}
    part = {kind: out_dir / f".{name}.{kind}.part" for kind in final}
    try:
        if "gif" in final:
            palette = PALETTE if layer is None else PALETTE_WHOLE
            command = gif_command(ffmpeg, Path(frames.name), counts[-1], part["gif"].resolve(), palette)
            run(command, "ffmpeg (gif)", cwd=frames_dir)
        if "webp" in final:
            if img2webp is None:
                raise RunError("img2webp: no program was given for the WebP")
            pairs = [(frames_dir / name_, count) for name_, count in zip(names, counts)]
            run(webp_command(img2webp, pairs, part["webp"]), "img2webp")
        for kind in final:
            os.replace(part[kind], final[kind])
    finally:
        for path in part.values():
            path.unlink(missing_ok=True)
    scaled = size(crop, viewport, width)
    return Picture(files=final, width=scaled[0], height=scaled[1], seconds=sum(counts) / FPS)
