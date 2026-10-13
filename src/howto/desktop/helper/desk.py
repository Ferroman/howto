"""What the helper does for each request: the monitor, the tree, the pointer and the keys, put together."""
from __future__ import annotations

import os
import subprocess
import time

from . import atspi, keys, pointer, tree, xinput
from .protocol import Refusal
from .session import Session

# Seconds between two looks at the tree while `find` waits.
LOOK_EVERY = 0.25
# Milliseconds between two keys when nothing is being shown. With no pause at all xdotool loses keys.
QUICK_KEY_MS = 1
REQUESTS = ("start", "find", "pointer", "click", "type", "key", "scroll_to", "run", "outline")


def _with(why: str, said: str) -> str:
    return f"{why}:\n{said}" if said else why


class Desk:
    def __init__(self) -> None:
        self.session: Session | None = None
        self.picture = (0, 0)

    def handlers(self) -> dict:
        return {name: getattr(self, name) for name in REQUESTS}

    def stop(self) -> None:
        if self.session is not None:
            self.session.stop()

    def start(self, q: dict) -> dict:
        self.picture = (q["width"], q["height"])
        self.session = Session(q["width"], q["height"])
        self.session.start()
        self.session.launch(q["run"])
        window = self.session.first_window(q["timeout"])
        if window is None:
            code = self.session.exit_code()
            if code is None:
                why = f"the app showed no window in {q['timeout']:g} seconds"
            else:
                why = f"the app ended with exit code {code}"
            raise Refusal("no_window", _with(why, self.session.said()))
        self.session.fill(window)
        # The pointer waits in a corner, off whatever the app shows first.
        xinput.move(f"mousemove {q['width'] - 24} {q['height'] - 24}\n")
        return {"build": os.environ.get("HOWTO_BUILD", ""), "title": self.session.title()}

    def _windows(self, hidden: bool = False) -> list[tree.Node]:
        return atspi.snapshot(lambda pid, box: tuple(float(value) for value in box), hidden)

    def _gone(self) -> None:
        """Refuses when the app has ended: nothing more can be found in it."""
        code = self.session.ended()
        if code is not None:
            raise Refusal("app_exited", _with(f"the app ended with exit code {code}", self.session.said()))

    def _look(self, locator: dict, seconds: float, hidden: bool) -> tuple[list, list]:
        """Looks for a locator until it names something or the time is over. Returns the matches and the windows."""
        end = time.monotonic() + seconds
        while True:
            windows = self._windows(hidden)
            found = tree.match(windows, locator, self.picture, hidden)
            if found or time.monotonic() >= end:
                return found, windows
            self._gone()
            time.sleep(LOOK_EVERY)

    def find(self, q: dict) -> dict:
        locator = q["locator"]
        found, windows = self._look(locator, q["timeout"], bool(q.get("hidden")))
        if len(found) == 1:
            element, window = found[0]
            return {
                "count": 1, "box": list(element.box or (0.0, 0.0, 0.0, 0.0)), "layer": "tree",
                "window": tree.tidy(window.name),
            }
        if found:
            return {"count": len(found)}
        self._gone()
        wanted = locator.get("name") or locator.get("label") or locator.get("text") or locator.get("option") or ""
        heard = tree.names(windows, locator, self.picture)
        return {"count": 0, "tried": ["tree"], "nearest": tree.nearest(wanted, heard) if wanted else []}

    def pointer(self, q: dict) -> dict:
        target = (round(q["x"]), round(q["y"]))
        seconds = q.get("seconds", 0)
        xinput.move(pointer.script(pointer.path(xinput.position(), target, seconds), seconds))
        return {}

    def click(self, q: dict) -> dict:
        title = q.get("window") or ""
        if title:
            managed = self.session.windows()
            mine = {int(window.id, 16) for window in managed if window.title == title}
            under = xinput.window_under_pointer()
            covering = next((window for window in managed if int(window.id, 16) == under), None)
            # A menu or a list that hangs over the window is not in the window manager's list, and covers nothing.
            if mine and covering is not None and under not in mine:
                raise Refusal("covered", f'another window covers it: "{covering.title}"')
        xinput.press(q.get("hold", 0))
        return {}

    def type(self, q: dict) -> dict:
        rate = q.get("rate", 0)
        delay = max(QUICK_KEY_MS, round(1000 / rate)) if rate > 0 else QUICK_KEY_MS
        xinput.type_text(q["text"], delay)
        return {}

    def key(self, q: dict) -> dict:
        try:
            names = keys.chord(q["keys"])
        except keys.BadKey as exc:
            raise Refusal("bad_key", str(exc)) from None
        xinput.key(names)
        return {}

    def scroll_to(self, q: dict) -> dict:
        found, _ = self._look(q["locator"], q["timeout"], True)
        if len(found) != 1:
            return {"count": len(found)}
        element, _ = found[0]
        if element.showing and tree.on_picture(element.box, self.picture):
            return {"count": 1}
        if not atspi.scroll_into_view(element):
            raise Refusal("cannot_scroll", "the app cannot bring it into view: use `press: PageDown`, or click what scrolls")
        return {"count": 1}

    def run(self, q: dict) -> dict:
        try:
            proc = subprocess.run(
                ["sh", "-c", q["command"]], env=self.session.env, cwd=self.session.env.get("HOME", "/"),
                capture_output=True, text=True, errors="replace", timeout=q["timeout"],
            )
        except subprocess.TimeoutExpired:
            return {"timed_out": True}
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        return {"code": proc.returncode, "output": "\n".join(lines[-8:])}

    def outline(self, q: dict) -> dict:
        windows = self._windows()
        shown = windows
        if q.get("within") is not None:
            shown = [element for element, _ in tree.match(windows, q["within"], self.picture)]
        active = next((window for window in windows if "active" in window.states), windows[0] if windows else None)
        return {
            "outline": tree.outline(shown, self.picture) or "(nothing is showing)",
            "title": tree.tidy(active.name) if active is not None else "",
            "windows": [tree.tidy(window.name) for window in windows],
            "first": self.session.title(),
            "ended": self.session.ended(),
        }
