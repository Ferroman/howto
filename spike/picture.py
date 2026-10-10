"""Measurement: is Playwright's own recording good enough at 1920x1080?

Records a 60-second take of a generated page with small text and three
buttons far apart, then reports what ffprobe sees and saves one frame for a
person to look at.

Run:  uv run python spike/picture.py [OUT_DIR]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTH, HEIGHT, SECONDS = 1920, 1080, 60
FFMPEG = "/home/linuxbrew/.linuxbrew/bin/ffmpeg"
FFPROBE = "/home/linuxbrew/.linuxbrew/bin/ffprobe"
# show_actions also labels every action with its locator ("Click
# get_by_role(...)"), and has no option to turn the label off. An overlay may
# carry a style element, and this rule hides the label's element.
HIDE_LABEL = "<style>x-pw-title{display:none!important}</style>"

PAGE = """
<!doctype html><meta charset="utf-8"><title>Picture measurement</title>
<style>
  body { margin: 0; font: 12px/1.4 system-ui, sans-serif; background: #f6f7f9; color: #111; }
  table { border-collapse: collapse; margin: 24px; }
  td { border: 1px solid #ccd; padding: 4px 10px; }
  button { position: absolute; padding: 10px 18px; font-size: 16px; }
</style>
<table id="rows"></table>
<button id="a" style="left: 1500px; top: 120px">Alpha</button>
<button id="b" style="left: 200px; top: 900px">Beta</button>
<button id="c" style="left: 1700px; top: 980px">Gamma</button>
<script>
  const rows = document.getElementById('rows');
  for (let i = 0; i < 30; i++) {
    const tr = rows.insertRow();
    for (let j = 0; j < 8; j++) tr.insertCell().textContent = `The quick brown fox ${i}-${j}`;
  }
</script>
"""


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "picture.webm"
    with tempfile.TemporaryDirectory(prefix="howto-spike-") as profile, sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile, headless=True, viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_content(PAGE)
        page.screencast.start(path=str(video), size={"width": WIDTH, "height": HEIGHT})
        page.screencast.show_actions(cursor="pointer")
        page.screencast.show_overlay(HIDE_LABEL)
        started = time.monotonic()
        names = ["Alpha", "Beta", "Gamma"]
        turn = 0
        while time.monotonic() - started < SECONDS:
            page.get_by_role("button", name=names[turn % 3]).click()
            turn += 1
            time.sleep(1.5)
        page.screencast.hide_actions()
        page.screencast.stop()
        context.close()

    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,nb_read_frames:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    duration = float(info["format"]["duration"])
    frames = int(stream["nb_read_frames"])
    rate = frames / duration
    frame = out_dir / "picture-frame.png"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-ss", "30", "-i", str(video), "-frames:v", "1", str(frame)],
        check=True,
    )

    size_ok = (stream["width"], stream["height"]) == (WIDTH, HEIGHT)
    rate_ok = rate >= 24
    print(f"size:    {stream['width']}x{stream['height']}  {'PASS' if size_ok else 'FAIL'} (want {WIDTH}x{HEIGHT})")
    print(f"frames:  {frames} in {duration:.1f} s = {rate:.1f} a second  {'PASS' if rate_ok else 'FAIL'} (want 24 or more)")
    print(f"video:   {video}")
    print(f"frame:   {frame}")
    return 0 if size_ok and rate_ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spike-out")))
