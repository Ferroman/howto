"""The windows of an app as plain data: which element a locator names, and the outline a probe prints.

Nothing here touches the accessibility bus, so it is tested on the host.
`atspi` reads the bus and fills the nodes.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Iterator

Box = tuple[float, float, float, float]

# What a label names: the roles that take a value from the user.
CONTROLS = frozenset({"textbox", "combobox", "checkbox", "radio", "spinbutton", "slider", "listbox", "switch"})
# What `select` chooses from: the roles of an item in a list that opened.
OPTIONS = frozenset({"menuitem", "menuitemcheckbox", "menuitemradio", "listitem", "option", "treeitem", "cell"})
# What can be disabled. A label that is not enabled is still only a label.
PRESSABLE = CONTROLS | OPTIONS | {"button", "tab", "link", "menu"}
# Roles that only hold other elements. Without a name, such an element gives way to what is in it.
PLAIN = frozenset({
    "filler", "group", "section", "scroll pane", "viewport", "split pane", "layered pane", "root pane",
    "glass pane", "redundant object", "unknown", "invalid",
})
SHOWN_STATES = ("active", "checked", "pressed", "expanded", "selected", "focused")


@dataclass
class Node:
    # The role, by its web name where it has one.
    role: str
    name: str = ""
    # What a field or a label holds.
    text: str = ""
    # In pixels of the picture. None for an element that has no place.
    box: Box | None = None
    showing: bool = True
    states: tuple[str, ...] = ()
    # The words of the labels that name this control.
    labels: tuple[str, ...] = ()
    children: list["Node"] = field(default_factory=list)
    pid: int = 0
    # The accessible itself. Nothing in this module touches it.
    ref: object = None


def tidy(words: str) -> str:
    """Words with every run of white space as one space."""
    return " ".join(words.split())


def on_picture(box: Box | None, picture: tuple[int, int]) -> bool:
    """Whether a box has a size and at least a part of it lies in the picture."""
    if box is None:
        return False
    x, y, width, height = box
    return width > 0 and height > 0 and x < picture[0] and y < picture[1] and x + width > 0 and y + height > 0


def says(wanted: str, got: str, exact: bool) -> bool:
    """Whether `got` has the words: all of them and nothing else when `exact`, else as a part, in any case."""
    wanted, got = tidy(wanted), tidy(got)
    if exact:
        return wanted == got
    return bool(wanted) and wanted.casefold() in got.casefold()


def fits(node: Node, locator: dict) -> bool:
    exact = bool(locator.get("exact"))
    if "role" in locator:
        return node.role == locator["role"] and ("name" not in locator or says(locator["name"], node.name, exact))
    if "label" in locator:
        return node.role in CONTROLS and any(says(locator["label"], words, exact) for words in (node.name, *node.labels))
    if "text" in locator:
        return says(locator["text"], node.name, exact) or says(locator["text"], node.text, exact)
    if "option" in locator:
        return node.role in OPTIONS and tidy(node.name) == tidy(locator["option"])
    return False


def below(node: Node) -> Iterator[Node]:
    """Every node under this one, in the order of the tree."""
    for child in node.children:
        yield child
        yield from below(child)


def match(
    windows: list[Node], locator: dict, picture: tuple[int, int], hidden: bool = False
) -> list[tuple[Node, Node]]:
    """The elements that a locator names, each with its window, in the order of the tree.

    Without `hidden`, only an element that is showing and has a place in the
    picture counts.
    """
    if locator.get("within") is not None:
        scopes = [(below(scope), window) for scope, window in match(windows, locator["within"], picture, hidden)]
    else:
        scopes = [(iter((window, *below(window))), window) for window in windows]
    seen_keys: list[object] = []
    found: list[tuple[Node, Node]] = []
    for candidates, window in scopes:
        for node in candidates:
            if not fits(node, locator):
                continue
            # The same element can be reached twice: an open menu is a child of the control that owns it
            # and at the same time a window of its own on the bus.
            key = node.ref if node.ref is not None else node
            if any(key is seen for seen in seen_keys):
                continue
            if hidden or (node.showing and on_picture(node.box, picture)):
                seen_keys.append(key)
                found.append((node, window))
    if "text" in locator:
        # The smallest element that has the words, as on a web page, and not the ones around it.
        found = [
            (node, window) for node, window in found
            if not any(other is inner for inner in below(node) for other, _ in found)
        ]
    nth = locator.get("nth")
    return found if nth is None else found[nth:nth + 1]


def _quoted(words: str) -> str:
    return '"' + tidy(words).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _line(node: Node) -> str:
    line = f"- {node.role}"
    if tidy(node.name):
        line += f" {_quoted(node.name)}"
    marks = [state for state in SHOWN_STATES if state in node.states]
    if node.role in PRESSABLE and "enabled" not in node.states:
        marks.append("disabled")
    return line + "".join(f" [{mark}]" for mark in marks)


def _lines(nodes: list[Node], picture: tuple[int, int], depth: int) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        if not node.showing:
            continue
        if (node.role in PLAIN and not tidy(node.name)) or not on_picture(node.box, picture):
            # Nothing to name here. What is in it takes its place.
            lines += _lines(node.children, picture, depth)
            continue
        inner = _lines(node.children, picture, depth + 1)
        line = "  " * depth + _line(node)
        held = tidy(node.text)
        if inner:
            lines.append(line + ":")
            lines += inner
        elif held and held != tidy(node.name):
            lines.append(f"{line}: {held[:200]}")
        else:
            lines.append(line)
    return lines


def outline(windows: list[Node], picture: tuple[int, int]) -> str:
    """The windows as a web outline is written: one line for each element, with its role and its name."""
    return "\n".join(_lines(windows, picture, 0))


def names(windows: list[Node], locator: dict, picture: tuple[int, int]) -> list[str]:
    """What a locator could have meant: the names and the texts of the elements it could have matched."""
    heard: list[str] = []
    for window in windows:
        for node in (window, *below(window)):
            if not node.showing or not on_picture(node.box, picture):
                continue
            if "role" in locator and node.role != locator["role"]:
                continue
            if "label" in locator and node.role not in CONTROLS:
                continue
            heard += [tidy(words) for words in (node.name, node.text) if tidy(words)]
    return heard


def nearest(wanted: str, heard: list[str], most: int = 3) -> list[str]:
    """The words closest to the ones that were asked for, the closest first, as they are written."""
    written = {}
    for words in heard:
        written.setdefault(tidy(words).casefold(), tidy(words))
    close = difflib.get_close_matches(tidy(wanted).casefold(), list(written), n=most, cutoff=0.6)
    return [written[key] for key in close]


# The roles that show nothing but their words. A mark goes around the words, not around the room that the app
# gave them: a label is often as wide as its window.
WORDS_ONLY = frozenset({"label", "heading", "paragraph", "link", "caption"})


def tighter(box: Box, words: Box | None) -> Box:
    """The box of an element's words, when the app gave one that lies in the element. Else the element's own box."""
    if words is None or words[2] <= 0 or words[3] <= 0:
        return box
    # A pixel of slack: a toolkit rounds the two boxes apart.
    inside = (
        words[0] >= box[0] - 1 and words[1] >= box[1] - 1
        and words[0] + words[2] <= box[0] + box[2] + 1 and words[1] + words[3] <= box[1] + box[3] + 1
    )
    return words if inside else box


def unit(frame: tuple[float, float], window: tuple[float, float], scale: int) -> int | None:
    """How many pixels of the monitor one unit of an app's boxes is: 1, or the scale.

    A toolkit that draws at twice its size counts either in pixels of the
    monitor or in its own, which are twice as large. One window tells which:
    `frame` is its size as the tree has it, and `window` its size on the
    monitor. None when the two agree in neither unit, and so are not one
    window. A tenth of slack is for a title bar.
    """
    if frame[0] <= 0 or frame[1] <= 0:
        return None
    for candidate in (scale, 1):
        wide, tall = frame[0] * candidate, frame[1] * candidate
        if abs(wide - window[0]) <= 0.1 * window[0] and abs(tall - window[1]) <= 0.1 * window[1]:
            return candidate
    return None


def learn(units: dict[int, int], windows: list[Node], listed: list[tuple[int, float, float]], scale: int) -> None:
    """Adds to `units` the unit of each app that one of its windows tells, by the app's pid.

    `listed` is the pid, the width and the height of each window that the
    window manager lists, in pixels of the monitor. A menu that hangs over a
    window is not listed, and teaches nothing.
    """
    for window in windows:
        if window.pid in units or window.box is None:
            continue
        for pid, wide, tall in listed:
            found = unit(window.box[2:], (wide, tall), scale) if pid == window.pid else None
            if found is not None:
                units[window.pid] = found
                break


def rescale(node: Node, factor: float) -> None:
    """Multiplies the boxes of a node, and of everything under it."""
    for one in (node, *below(node)):
        if one.box is not None:
            one.box = tuple(value * factor for value in one.box)
