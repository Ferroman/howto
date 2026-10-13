"""Measurement: does an app in a bare container publish its tree, and are its boxes right?

Each of the four apps is started on a monitor of 1920x1080 and made to fill
it. It passes when at least ten controls that are showing have a role and a
name, and the box of its window is the monitor, within 2 pixels. The second
half is for a person: the boxes are drawn in red on a screenshot.

Run:  uv run python spike/desktop/tree.py
"""
from __future__ import annotations

import json

import box

MONITOR = [0, 0, 1920, 1080]


def main() -> int:
    failed = False
    for app in ("gtk3", "gtk4", "qt", "electron"):
        found = json.loads(box.inside("desk.py", "tree.py", args=[app], out="tree"))
        frame = found["frame"] or [0, 0, 0, 0]
        off = max(abs(a - b) for a, b in zip(frame, MONITOR))
        ok = found["named"] >= 10 and off <= 2
        failed |= not ok
        print(
            f'{"PASS" if ok else "FAIL"}  {app:9} toolkit={found["toolkit"]!r} nodes={found["nodes"]} '
            f'named={found["named"]} read in {found["seconds"]} s settled={found["settled"]} '
            f"window={frame} (off by {off})"
        )
        print("      roles:", ", ".join(found["roles"]))
        for role, name, where in found["sample"]:
            print(f"      {role} {name!r} {where}")
    print(f"Look at {box.OUT / 'tree'}/APP-boxes.png: each red frame must lie on its control, within 2 pixels.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
