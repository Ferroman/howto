"""Measurement: can ffmpeg make the move of a zoom from a recording of twice the size?

A white dot on a black recording of 3840x2160 is zoomed in on and out again.
ffmpeg itself finds the dot in every frame of the result, and the script
compares that with where the arithmetic puts it. A second recording, of a
screenshot with text, is compared at a zoom of 2 with the same part cut
straight from the recording.

Three ways to make the move are tried, each with every ffmpeg that is given:

  zoompan               the filter the spec names
  zoompan after 4:4:4   the same, on a picture that keeps colour for every pixel
  scale and overlay     the recording scaled frame by frame and laid on a canvas

Run:  uv run python spike/desktop/zoom.py [FFMPEG ...]
      The default is howto's ffmpeg, and /usr/bin/ffmpeg when it is another one.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import box
from howto.tools import find_tool

OUT = box.OUT / "zoom"
W, H, SCALE = 1920, 1080, 2
# The middle, in pixels of the picture, of a dot of 16 monitor pixels at 2000, 1200.
DOT = (1004.0, 604.0)
# (start, seconds, left, top, factor): in to twice the size at 0.5 s, back out at 2.5 s.
MOVES = [(0.5, 0.8, 700.0, 350.0, 2.0), (2.5, 0.8, 0.0, 0.0, 1.0)]
# What moves evenly is the part of the picture that is shown, 1 / factor, and its corner.
SHARE = [(start, seconds, 1 / factor) for start, seconds, _, _, factor in MOVES]
LEFT = [(start, seconds, left) for start, seconds, left, _, _ in MOVES]
TOP = [(start, seconds, top) for start, seconds, _, top, _ in MOVES]
# The pass marks. While nothing moves the dot must not move at all. During a move it may be this far from
# where the arithmetic puts it, in pixels of the picture, and it must never step back.
STILL, ON_THE_WAY = 0.0, 2.5
SHARP = 38.0


def curve(first: float, changes, clock: str) -> str:
    """An ffmpeg expression for a value that eases from `first` to each `to` of [(start, seconds, to)]."""
    parts, before = [], first
    for start, seconds, to in changes:
        parts.append((start, seconds, before, to))
        before = to
    text = f"{before:.6f}"
    for start, seconds, origin, to in reversed(parts):
        part = f"(({clock}-{start:.3f})/{seconds:.3f})"
        eased = f"({origin:.6f}+{to - origin:.6f}*{part}*{part}*(3-2*{part}))"
        text = f"if(lt({clock},{start + seconds:.3f}),if(lt({clock},{start:.3f}),{origin:.6f},{eased}),{text})"
    return text


def value(first: float, changes, at: float) -> float:
    """The same value, worked out here."""
    now = first
    for start, seconds, to in changes:
        if at < start:
            return now
        if at < start + seconds:
            part = (at - start) / seconds
            return now + (to - now) * part * part * (3 - 2 * part)
        now = to
    return now


def zoompan() -> str:
    return (
        f"zoompan=z='1/({curve(1, SHARE, 'it')})':x='{SCALE}*({curve(0, LEFT, 'it')})'"
        f":y='{SCALE}*({curve(0, TOP, 'it')})':d=1:s={W}x{H}:fps=25"
    )


def scale_overlay() -> str:
    factor = f"(1/({curve(1, SHARE, 't')}))"
    return (
        f"[0:v]fps=25,scale=w='2*trunc({W}*{factor}/2)':h='2*trunc({H}*{factor}/2)':eval=frame:flags=bicubic[big];"
        f"color=black:s={W}x{H}:r=25[canvas];"
        f"[canvas][big]overlay=x='-({curve(0, LEFT, 't')})*{factor}':y='-({curve(0, TOP, 't')})*{factor}'"
        ":eval=frame:format=yuv444:shortest=1[v]"
    )


# In the order in which they are preferred: the first that passes with every ffmpeg is the way.
WAYS = {
    "zoompan": lambda: f"[0:v]fps=25,{zoompan()}[v]",
    "zoompan after 4:4:4": lambda: f"[0:v]fps=25,format=yuv444p,{zoompan()}[v]",
    "scale and overlay": scale_overlay,
}
ENCODE = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p"]


def make(ffmpeg: str, source: list[str], out: Path) -> None:
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *source, *ENCODE, "-t", "4", str(out)], check=True)


def apply(ffmpeg: str, source: Path, graph: str, out: Path) -> float:
    began = time.perf_counter()
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-filter_complex", graph, "-map", "[v]", *ENCODE, str(out)],
        check=True,
    )
    return time.perf_counter() - began


def track(ffmpeg: str, video: Path) -> list[tuple[float, float]]:
    """The middle of the dot in each frame, from ffmpeg's own box around what is not black.

    Not `cropdetect`: it looks at the mean of a whole row, and a dot does not change that.
    """
    printed = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", str(video), "-vf", "bbox=min_val=128,metadata=mode=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    middles, edges = [], {}
    for line in printed.splitlines():
        key, _, number = line.partition("=")
        if key.startswith("lavfi.bbox."):
            edges[key.rsplit(".", 1)[1]] = float(number)
        # `h` is the last of the six values that the filter prints for a frame.
        if key == "lavfi.bbox.h":
            middles.append(((edges["x1"] + edges["x2"] + 1) / 2, (edges["y1"] + edges["y2"] + 1) / 2))
    return middles


def expected(frame: int) -> tuple[float, float]:
    at = frame / 25
    factor = 1 / value(1, SHARE, at)
    return (DOT[0] - value(0, LEFT, at)) * factor, (DOT[1] - value(0, TOP, at)) * factor


def moving(frame: int) -> bool:
    """Whether a frame lies in a move, or right at its edge."""
    return any(start - 0.05 <= frame / 25 <= start + seconds + 0.05 for start, seconds, *_ in MOVES)


def movement(middles) -> tuple[float, float, int]:
    """How far the dot is from its place while nothing moves, how far during a move, and how often it steps back."""
    errors = [
        max(abs(x - expected(frame)[0]), abs(y - expected(frame)[1])) for frame, (x, y) in enumerate(middles)
    ]
    still = max((error for frame, error in enumerate(errors) if not moving(frame)), default=0.0)
    on_the_way = max((error for frame, error in enumerate(errors) if moving(frame)), default=0.0)
    back = 0
    for frame in range(1, len(middles)):
        if not moving(frame):
            continue
        # The way the arithmetic goes between these two frames, and the way the dot went.
        wanted = expected(frame)[0] - expected(frame - 1)[0]
        went = middles[frame][0] - middles[frame - 1][0]
        if abs(wanted) > 1.0 and wanted * went < 0:
            back += 1
    return still, on_the_way, back


def still_of(ffmpeg: str, video: Path, at: float, out: Path, cut: str | None = None) -> Path:
    """One frame of a video as a PNG, cut to a part of it when `cut` is given."""
    command = [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{at}", "-i", str(video)]
    if cut:
        command += ["-vf", cut]
    subprocess.run([*command, "-frames:v", "1", str(out)], check=True)
    return out


def sharpness(ffmpeg: str, zoomed: Path, source: Path) -> float:
    """PSNR, at a zoom of 2, between the result and the same part cut straight from the recording.

    Two frames are written out and then compared. A comparison of the two
    videos in one command pairs the wrong frames with ffmpeg 6.
    """
    one = still_of(ffmpeg, zoomed, 2.0, OUT / "zoomed.png")
    other = still_of(ffmpeg, source, 2.0, OUT / "cut.png", f"crop={W}:{H}:{int(700 * SCALE)}:{int(350 * SCALE)}")
    said = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(one), "-i", str(other), "-filter_complex", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    found = re.search(r"average:([\d.]+|inf)", said)
    return float(found.group(1)) if found else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    screenshot = box.OUT / "scale" / "gtk3-2.png"
    if not screenshot.exists():
        raise SystemExit(f"{screenshot} is missing: run spike/desktop/scale.py first")
    own = find_tool("ffmpeg", "HOWTO_FFMPEG")
    ffmpegs = sys.argv[1:] or [own] + [p for p in ["/usr/bin/ffmpeg"] if Path(p).exists() and Path(p).resolve() != Path(own).resolve()]
    passed = {}
    for ffmpeg in ffmpegs:
        version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout.split()[2]
        dot, text = OUT / "dot.mkv", OUT / "text.mkv"
        make(ffmpeg, ["-f", "lavfi", "-i",
                      f"color=black:s={W * SCALE}x{H * SCALE}:r=25,drawbox=x=2000:y=1200:w=16:h=16:color=white:t=fill"], dot)
        make(ffmpeg, ["-loop", "1", "-framerate", "25", "-i", str(screenshot)], text)
        for name, graph in WAYS.items():
            try:
                seconds = apply(ffmpeg, dot, graph(), OUT / "dot-zoomed.mkv")
                apply(ffmpeg, text, graph(), OUT / "text-zoomed.mkv")
                still, on_the_way, back = movement(track(ffmpeg, OUT / "dot-zoomed.mkv"))
                sharp = sharpness(ffmpeg, OUT / "text-zoomed.mkv", text)
            except subprocess.CalledProcessError as exc:
                print(f"FAIL  ffmpeg {version}, {name}: ffmpeg refused it (exit {exc.returncode})")
                passed.setdefault(name, []).append(False)
                continue
            ok = still <= STILL and on_the_way <= ON_THE_WAY and back == 0 and sharp >= SHARP
            passed.setdefault(name, []).append(ok)
            print(
                f'{"PASS" if ok else "FAIL"}  ffmpeg {version}, {name}: the dot is off by {still:.2f} px while nothing moves '
                f"and by {on_the_way:.2f} px at most during a move, steps back {back} times, "
                f"PSNR at a zoom of 2: {sharp:.1f} dB, {seconds:.1f} s for 4 s of video"
            )
    good = [name for name, results in passed.items() if all(results)]
    print("Ways that pass with every ffmpeg, the preferred one first:", ", ".join(good) or "none")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
