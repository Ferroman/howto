"""Measurement: how far is the recorded video from the wall clock?

The page is black. At known times after recording starts it turns white for
0.4 s. The script then finds the white frames in the video and prints how far
each one is from its planned time.

Run:  uv run python spike/sync.py [OUT_DIR]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from howto.tools import find_tool

WIDTH, HEIGHT = 1920, 1080
SECONDS = 120
FLASHES = [5, 20, 40, 60, 80, 100, 115]
FLASH_LENGTH = 0.4
RATE = 25
LIMIT = 0.25
FFMPEG = find_tool("ffmpeg", "HOWTO_FFMPEG")


def record(video: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="howto-spike-") as profile, sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile, headless=True, viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_content("<body style='margin:0;background:#000'></body>")
        page.screencast.start(path=str(video), size={"width": WIDTH, "height": HEIGHT})
        zero = time.monotonic()
        for at in FLASHES:
            time.sleep(max(0.0, at - (time.monotonic() - zero)))
            page.evaluate("document.body.style.background = '#fff'")
            time.sleep(FLASH_LENGTH)
            page.evaluate("document.body.style.background = '#000'")
        time.sleep(max(0.0, SECONDS - (time.monotonic() - zero)))
        page.screencast.stop()
        context.close()


def flashes_in(video: Path) -> list[float]:
    """Times at which the picture turns from dark to bright."""
    raw = subprocess.run(
        [FFMPEG, "-loglevel", "error", "-i", str(video),
         "-vf", f"fps={RATE},scale=8:8,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    bright = [sum(raw[i:i + 64]) / 64 > 128 for i in range(0, len(raw) - 63, 64)]
    return [i / RATE for i in range(len(bright)) if bright[i] and (i == 0 or not bright[i - 1])]


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "sync.webm"
    record(video)
    found = flashes_in(video)
    if len(found) != len(FLASHES):
        print(f"FAIL: planned {len(FLASHES)} flashes, found {len(found)} at {found}")
        return 1
    worst = 0.0
    for planned, seen in zip(FLASHES, found):
        offset = seen - planned
        worst = max(worst, abs(offset))
        print(f"flash at {planned:>3} s: seen at {seen:7.2f} s, offset {offset:+.2f} s")
    ok = worst <= LIMIT
    print(f"worst offset: {worst:.2f} s  {'PASS' if ok else 'FAIL'} (limit {LIMIT} s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spike-out")))
