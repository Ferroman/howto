"""Reads the accessibility bus into plain nodes. The only module that imports the AT-SPI bindings."""
from __future__ import annotations

from typing import Callable

from .roles import web_role
from .tree import CONTROLS, Box, Node

# A tree larger than this is cut. The rest is of no use to an outline, and reading it takes minutes.
MOST_NODES = 6000
MOST_CHILDREN = 400
DEEPEST = 60
LONGEST_TEXT = 500


def _bindings():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi


def _labels(Atspi, accessible) -> list[str]:
    """The words of the labels that name a control."""
    found = []
    for relation in accessible.get_relation_set() or []:
        if relation.get_relation_type() == Atspi.RelationType.LABELLED_BY:
            for index in range(relation.get_n_targets()):
                words = relation.get_target(index).get_name() or ""
                if words.strip():
                    found.append(words)
    return found


def snapshot(to_picture: Callable[[int, Box], Box], hidden: bool = False) -> list[Node]:
    """Every window, as plain data.

    Without `hidden`, what is not showing is left out with all that is in it.
    `to_picture` turns a box, as the app with this pid reports it, into
    pixels of the picture.
    """
    Atspi = _bindings()
    states = [
        (Atspi.StateType.ENABLED, "enabled"), (Atspi.StateType.ACTIVE, "active"), (Atspi.StateType.CHECKED, "checked"),
        (Atspi.StateType.PRESSED, "pressed"), (Atspi.StateType.EXPANDED, "expanded"),
        (Atspi.StateType.SELECTED, "selected"), (Atspi.StateType.FOCUSED, "focused"),
    ]
    count = 0

    def read(accessible, pid: int, depth: int) -> Node | None:
        nonlocal count
        if count >= MOST_NODES or depth > DEEPEST:
            return None
        try:
            held = accessible.get_state_set()
            showing = held.contains(Atspi.StateType.SHOWING)
            if not showing and not hidden:
                return None
            count += 1
            node = Node(
                role=web_role(accessible.get_role_name() or "unknown"),
                name=accessible.get_name() or "",
                showing=showing,
                states=tuple(name for state, name in states if held.contains(state)),
                pid=pid,
                ref=accessible,
            )
            interfaces = accessible.get_interfaces() or []
            if "Component" in interfaces:
                rect = Atspi.Component.get_extents(accessible, Atspi.CoordType.SCREEN)
                node.box = to_picture(pid, (rect.x, rect.y, rect.width, rect.height))
            if "Text" in interfaces:
                length = min(Atspi.Text.get_character_count(accessible), LONGEST_TEXT)
                node.text = Atspi.Text.get_text(accessible, 0, length) or ""
            if node.role in CONTROLS:
                node.labels = tuple(_labels(Atspi, accessible))
                if not node.name.strip() and node.labels:
                    # A control that only its label names is known by that label.
                    node.name = node.labels[0]
            for index in range(min(accessible.get_child_count(), MOST_CHILDREN)):
                child = read(accessible.get_child_at_index(index), pid, depth + 1)
                if child is not None:
                    node.children.append(child)
            return node
        except Exception:  # noqa: BLE001 - an element that went away while it was read
            return None

    windows = []
    desktop = Atspi.get_desktop(0)
    for a in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(a)
            pid = app.get_process_id()
            tops = [app.get_child_at_index(w) for w in range(app.get_child_count())]
        except Exception:  # noqa: BLE001 - an app that went away
            continue
        for top in tops:
            node = read(top, pid, 0)
            if node is not None:
                windows.append(node)
    return windows


def scroll_into_view(node: Node) -> bool:
    """Asks the app to bring an element into view. False when the app cannot."""
    Atspi = _bindings()
    try:
        return bool(Atspi.Component.scroll_to(node.ref, Atspi.ScrollType.ANYWHERE))
    except Exception:  # noqa: BLE001 - an app that does not know the request
        return False


def words_box(node: Node, to_picture: Callable[[int, Box], Box]) -> Box | None:
    """Where the characters of an element are. None for an element without text, and for an app that does not say."""
    Atspi = _bindings()
    try:
        count = Atspi.Text.get_character_count(node.ref)
        if count <= 0:
            return None
        rect = Atspi.Text.get_range_extents(node.ref, 0, count, Atspi.CoordType.SCREEN)
    except Exception:  # noqa: BLE001 - an element without text, or one that went away
        return None
    return to_picture(node.pid, (rect.x, rect.y, rect.width, rect.height))
