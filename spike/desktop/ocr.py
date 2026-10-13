"""Measurement: does tesseract read the text of an interface?

For each of the four apps, the words in the names of its tree are the words
that should be read. A word counts when tesseract reads the same word inside
the box of its element. Four settings are compared: the screenshot at its
own size and enlarged twice, each as scattered text (11) and as one block (6).

Run:  uv run python spike/desktop/ocr.py
"""
from __future__ import annotations

import json

import box


def main() -> int:
    totals: dict[tuple[int, str], list[float]] = {}
    for app in ("gtk3", "gtk4", "qt", "electron"):
        found = json.loads(box.inside("desk.py", "ocr.py", args=[app]))
        for result in found["results"]:
            key = (result["enlarge"], result["psm"])
            total = totals.setdefault(key, [0, 0, 0.0])
            total[0] += result["read"]
            total[1] += result["wanted"]
            total[2] = max(total[2], result["seconds"])
            share = result["read"] / result["wanted"] if result["wanted"] else 0.0
            print(f'      {app:9} enlarged x{result["enlarge"]}, mode {result["psm"]}: '
                  f'{result["read"]} of {result["wanted"]} words ({share * 100:.0f} %), {result["seconds"]} s')
    good = []
    for (enlarge, mode), (read, wanted, slowest) in sorted(totals.items()):
        share = read / wanted if wanted else 0.0
        ok = share >= 0.9 and slowest <= 2
        if ok:
            good.append((enlarge, mode))
        print(f'{"PASS" if ok else "FAIL"}  enlarged x{enlarge}, mode {mode}: {share * 100:.1f} % of the words, {slowest} s at most')
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
