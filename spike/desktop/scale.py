"""Measurement: do the scale settings make each app draw at twice the size, and is a title bar right?

Each app runs on a monitor of 1920x1080, and again on one of 3840x2160 with
the settings of SCALE_ENV and Xft.dpi at 192. It passes when at least nine in
ten of its named controls are in the same place of the picture at both
scales, within 3 pixels. The title bar of a second window passes when it is
at least 1.7 times as tall at twice the scale.

Run:  uv run python spike/desktop/scale.py [WINDOW-MANAGER ...]
      The default is openbox. `metacity` is the second one to try.
"""
from __future__ import annotations

import json
import sys

import box


def run(app: str, scale: int, wm: str) -> dict:
    return json.loads(box.inside("desk.py", "scale.py", args=[app, str(scale), wm], out="scale"))


def compare(app: str, wm: str) -> bool:
    one, two = run(app, 1, wm), run(app, 2, wm)
    shared = sorted(set(one["controls"]) & set(two["controls"]))
    close = [
        key for key in shared
        if all(abs(a - b) <= 3 for a, b in zip(one["controls"][key], two["controls"][key]))
    ]
    share = len(close) / len(shared) if shared else 0.0
    bar = two["title_bar"] / one["title_bar"] if one["title_bar"] else 0.0
    ok = share >= 0.9 and bar >= 1.7
    print(
        f'{"PASS" if ok else "FAIL"}  {app:9} wm={wm}: unit of the boxes at twice the scale: {two["unit"]}, '
        f"in the same place: {len(close)} of {len(shared)} controls, "
        f'title bar {one["title_bar"]} -> {two["title_bar"]} px (x{bar:.1f})'
    )
    return ok


def main() -> int:
    ok = True
    for wm in sys.argv[1:] or ["openbox"]:
        for app in ("gtk3", "gtk4", "qt", "electron"):
            ok &= compare(app, wm)
    print(f"Look at {box.OUT / 'scale'}/APP-2.png at its own size: the text must be sharp, not doubled pixels.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
