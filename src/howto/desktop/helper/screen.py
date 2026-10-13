"""The monitor as a picture: a screenshot, and the words that tesseract reads on it.

The tree gives names where an app publishes one. The screen serves what the
tree does not have: a canvas, a widget of the app's own, an app that
publishes nothing.
"""
from __future__ import annotations

import collections
import subprocess
from dataclasses import dataclass
from typing import Sequence

from .session import DISPLAY, RUNTIME
from .tree import Box, Node, below, on_picture, tidy

SHOT = f"{RUNTIME}/screen.png"
LARGE = f"{RUNTIME}/screen-large.png"
# How much a screenshot is enlarged before it is read, and tesseract's way to look for text
# (11: scattered text). Both as spike/desktop/ocr.py measured them.
ENLARGE = 2
MODE = "11"
# tesseract's confidence, from 0 to 100. A word under this is taken for noise.
SURE = 40.0


@dataclass(frozen=True)
class Line:
    """One line of words that was read, each word with its box in pixels of the picture."""

    words: tuple[tuple[str, Box], ...]

    @property
    def text(self) -> str:
        return " ".join(word for word, _ in self.words)

    @property
    def box(self) -> Box:
        return _around([box for _, box in self.words])


def _around(boxes: list[Box]) -> Box:
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (left, top, right - left, bottom - top)


def lines_of(table: str, shrink: float = 1.0) -> list[Line]:
    """The lines of tesseract's table, its `tsv` output. `shrink` is how much the picture was enlarged before."""
    found: dict[tuple[str, ...], list[tuple[str, Box]]] = {}
    for row in table.splitlines()[1:]:
        cells = row.split("\t")
        # A row of level 5 is a word. The four numbers before the word's own say which line it is in.
        if len(cells) != 12 or cells[0] != "5":
            continue
        word = cells[11].strip()
        try:
            sure = float(cells[10])
            left, top, width, height = (int(cells[index]) / shrink for index in (6, 7, 8, 9))
        except ValueError:
            continue
        if sure < SURE or not any(character.isalnum() for character in word):
            continue
        found.setdefault(tuple(cells[1:5]), []).append((word, (left, top, width, height)))
    return [Line(tuple(words)) for words in found.values()]


def spot(lines: list[Line], wanted: str, exact: bool = False) -> list[Box]:
    """Where on the screen the words are: one box for each place, around those words and no others."""
    wanted = tidy(wanted)
    if not wanted:
        return []
    places = []
    for line in lines:
        if exact:
            if line.text == wanted:
                places.append(line.box)
            continue
        # Where each word starts in the text of its line.
        starts, at = [], 0
        for word, _ in line.words:
            starts.append(at)
            at += len(word) + 1
        text, sought, since = line.text.lower(), wanted.lower(), 0
        while (index := text.find(sought, since)) >= 0:
            end = index + len(sought)
            hit = [box for (word, box), start in zip(line.words, starts) if start < end and start + len(word) > index]
            places.append(_around(hit))
            since = end
    return places


def _inside(point: tuple[float, float], box: Box) -> bool:
    return box[0] <= point[0] <= box[0] + box[2] and box[1] <= point[1] <= box[1] + box[3]


def _bare(word: str) -> str:
    """A word as it is compared: in small letters, without the signs around it."""
    return word.lower().strip(".,:;!?…()[]\"'")


def lacking(lines: list[Line], windows: list[Node], picture: tuple[int, int]) -> list[Line]:
    """The words that the tree does not have: no element at their place has them in its name or in what it holds.

    A word that the tree has is left out by itself, because the screen often
    reads two elements that lie side by side as one line.
    """
    # Not the windows themselves: a window that fills the monitor shows no title, and holds every word.
    known = [
        (node.box, {_bare(word) for word in f"{node.name} {node.text}".split()})
        for window in windows
        for node in below(window)
        if node.showing and on_picture(node.box, picture)
    ]
    kept: list[Line] = []
    for line in lines:
        run: list[tuple[str, Box]] = []
        for word, box in line.words:
            middle = (box[0] + box[2] / 2, box[1] + box[3] / 2)
            if any(_inside(middle, where) and _bare(word) in said for where, said in known):
                if run:
                    kept.append(Line(tuple(run)))
                run = []
            else:
                run.append((word, box))
        if run:
            kept.append(Line(tuple(run)))
    return kept


def shot(width: int, height: int, out: str = SHOT) -> str:
    """Writes a PNG of the monitor, without the pointer, and returns its path."""
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "0",
         "-video_size", f"{width}x{height}", "-i", DISPLAY, "-frames:v", "1", out],
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cannot take a screenshot: {proc.stderr.strip()[-300:]}")
    return out


def read(path: str) -> list[Line]:
    """The words on a screenshot."""
    source = path
    if ENLARGE > 1:
        from PIL import Image

        picture = Image.open(path)
        picture.resize((picture.width * ENLARGE, picture.height * ENLARGE), Image.LANCZOS).save(LARGE)
        source = LARGE
    proc = subprocess.run(
        ["tesseract", source, "stdout", "--psm", MODE, "-l", "eng", "tsv"],
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed (exit {proc.returncode}): {proc.stderr.strip()[-300:]}")
    return lines_of(proc.stdout, ENLARGE)


# A pixel is something when it differs from the most common colour of its area by more than this, in red,
# green or blue. A gradient and the noise of a picture stay under it.
NEAR = 24


def share(colours: Sequence[tuple[int, int, int]]) -> float:
    """The part of an area that is something: the pixels that are not near its most common colour."""
    if not colours:
        return 0.0
    ground = collections.Counter(colours).most_common(1)[0][0]
    other = sum(1 for colour in colours if max(abs(a - b) for a, b in zip(colour, ground)) > NEAR)
    return other / len(colours)


def busy(path: str, areas: list) -> list[float]:
    """For each area of a screenshot, the part of it that is something. An area off the monitor is all something."""
    from PIL import Image

    picture = Image.open(path).convert("RGB")
    found = []
    for x, y, width, height in areas:
        left, top = max(0, round(x)), max(0, round(y))
        right, bottom = min(picture.width, round(x + width)), min(picture.height, round(y + height))
        if right <= left or bottom <= top:
            found.append(1.0)
            continue
        found.append(round(share(list(picture.crop((left, top, right, bottom)).getdata())), 3))
    return found
