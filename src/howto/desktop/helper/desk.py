"""What the helper does for each request: the monitor, the tree, the pointer and the keys, put together."""
from __future__ import annotations

import os
import subprocess
import time

from . import atspi, keys, pointer, screen, tree, xinput
from .protocol import Refusal
from .record import Recorder
from .session import Session
from .watch import WEB_PORT, Watch

# Seconds between two looks at the tree while `find` waits.
LOOK_EVERY = 0.25
# Milliseconds between two keys when nothing is being shown. With no pause at all xdotool loses keys.
QUICK_KEY_MS = 1
REQUESTS = ("start", "find", "pointer", "click", "type", "key", "scroll_to", "run", "outline",
           "record_start", "record_stop", "screenshot", "words", "busy", "show")


def _with(why: str, said: str) -> str:
    return f"{why}:\n{said}" if said else why


class Desk:
    def __init__(self) -> None:
        self.session: Session | None = None
        # The size of the picture. Every request and every reply is in its pixels.
        self.picture = (0, 0)
        # How many pixels of the monitor one pixel of the picture is, and the size of the monitor.
        self.scale = 1
        self.monitor = (0, 0)
        # For each app, by its pid: how many pixels of the monitor one unit of its boxes is.
        self._units: dict[int, int] = {}
        self.recorder = Recorder()
        self.watch = Watch()

    def handlers(self) -> dict:
        return {name: getattr(self, name) for name in REQUESTS}

    def stop(self) -> None:
        self.recorder.abandon()
        self.watch.stop()
        if self.session is not None:
            self.session.stop()

    def start(self, q: dict) -> dict:
        self.scale = q.get("scale", 1)
        self.picture = (q["width"], q["height"])
        self.monitor = (q["width"] * self.scale, q["height"] * self.scale)
        self.session = Session(*self.monitor, self.scale)
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
        xinput.move(f"mousemove {self.monitor[0] - 24 * self.scale} {self.monitor[1] - 24 * self.scale}\n")
        return {"build": os.environ.get("HOWTO_BUILD", ""), "title": self.session.title()}

    def _to_picture(self, pid: int, box: tuple) -> tree.Box:
        """A box as an app reports it, in pixels of the picture."""
        factor = self._units.get(pid, self.scale) / self.scale
        return tuple(float(value) * factor for value in box)

    def _windows(self, hidden: bool = False) -> list[tree.Node]:
        # The tree is read as the apps report it. Then each window is brought to pixels of the picture.
        windows = atspi.snapshot(lambda pid, box: tuple(float(value) for value in box), hidden)
        if self.scale > 1:
            listed = [(window.pid, window.width, window.height) for window in self.session.windows()]
            tree.learn(self._units, windows, listed, self.scale)
            for window in windows:
                # An app of which no listed window told: most toolkits count in their own pixels.
                tree.rescale(window, self._units.get(window.pid, self.scale) / self.scale)
        return windows

    def _shot(self) -> str:
        """A screenshot of the monitor, at the size of the picture."""
        return screen.shot(*self.monitor, picture=self.picture)

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

    def _places(self, lines: list, locator: dict, windows: list) -> list:
        """Where the words of a `text` locator are on the screen, narrowed as the locator says."""
        places = screen.spot(lines, locator["text"], bool(locator.get("exact")))
        if locator.get("within") is not None:
            inside = [element.box for element, _ in tree.match(windows, locator["within"], self.picture)]
            places = [
                place for place in places
                if any(
                    box is not None
                    and box[0] <= place[0] + place[2] / 2 <= box[0] + box[2]
                    and box[1] <= place[1] + place[3] / 2 <= box[1] + box[3]
                    for box in inside
                )
            ]
        nth = locator.get("nth")
        return places if nth is None else places[nth:nth + 1]

    def _seek(self, locator: dict, seconds: float) -> tuple[list, list, list, list]:
        """Looks in the tree, and for `text` then on the screen, until something is found or the time is over.

        Returns the elements of the tree, the places on the screen, the windows, and the lines that were read.
        """
        end = time.monotonic() + seconds
        while True:
            windows = self._windows()
            found = tree.match(windows, locator, self.picture)
            lines, places = [], []
            if not found and "text" in locator:
                lines = screen.read(self._shot())
                places = self._places(lines, locator, windows)
            if found or places or time.monotonic() >= end:
                return found, places, windows, lines
            self._gone()
            time.sleep(LOOK_EVERY)

    def _hidden(self, locator: dict, seconds: float) -> dict:
        """What `find` answers for an element that need not be showing: the tree only."""
        found, _ = self._look(locator, seconds, True)
        if len(found) != 1:
            return {"count": len(found), "tried": ["tree"], "nearest": []}
        element, window = found[0]
        return {"count": 1, "box": list(element.box or (0.0, 0.0, 0.0, 0.0)), "layer": "tree", "window": tree.tidy(window.name)}

    def find(self, q: dict) -> dict:
        locator = q["locator"]
        if q.get("hidden"):
            return self._hidden(locator, q["timeout"])
        found, places, windows, lines = self._seek(locator, q["timeout"])
        if len(found) == 1:
            element, window = found[0]
            box = element.box or (0.0, 0.0, 0.0, 0.0)
            if q.get("tight") and element.role in tree.WORDS_ONLY:
                # A mark goes around the words of a label, not around the room that the app gave it.
                box = tree.tighter(box, atspi.words_box(element, self._to_picture))
            return {"count": 1, "box": list(box), "layer": "tree", "window": tree.tidy(window.name)}
        if found:
            return {"count": len(found)}
        if len(places) == 1:
            # A place on the screen belongs to no window that the tree knows, so nothing checks what covers it.
            return {"count": 1, "box": list(places[0]), "layer": "screen", "window": ""}
        if places:
            return {"count": len(places)}
        self._gone()
        wanted = locator.get("name") or locator.get("label") or locator.get("text") or locator.get("option") or ""
        heard = tree.names(windows, locator, self.picture)
        tried = ["tree"]
        if "text" in locator:
            tried.append("screen")
            heard += [line.text for line in lines] + [word for line in lines for word, _ in line.words]
        return {"count": 0, "tried": tried, "nearest": tree.nearest(wanted, heard) if wanted else []}

    def pointer(self, q: dict) -> dict:
        target = (round(q["x"] * self.scale), round(q["y"] * self.scale))
        seconds = q.get("seconds", 0)
        xinput.move(pointer.script(pointer.path(xinput.position(), target, seconds), seconds))
        return {}

    def click(self, q: dict) -> dict:
        title = q.get("window") or ""
        if title:
            managed = self.session.windows()
            mine = {int(window.id, 16) for window in managed if window.title == title}
            under = xinput.window_under_pointer()
            related = xinput.related(under)
            covering = next((window for window in managed if int(window.id, 16) in related), None)
            # A menu or a list that hangs over the window is not in the window manager's list, and covers nothing.
            if mine and covering is not None and int(covering.id, 16) not in mine:
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

    def record_start(self, q: dict) -> dict:
        return {"first_frame": self.recorder.start(*self.monitor)}

    def record_stop(self, q: dict) -> dict:
        return {"path": self.recorder.stop()}

    def screenshot(self, q: dict) -> dict:
        return {"path": self._shot()}

    def words(self, q: dict) -> dict:
        """The lines of words on the screen. With `lacking`, only the words that the tree does not have."""
        lines = screen.read(q.get("shot") or self._shot())
        windows = self._windows()
        if q.get("lacking"):
            lines = screen.lacking(lines, windows, self.picture)
        if q.get("within") is not None:
            inside = [element.box for element, _ in tree.match(windows, q["within"], self.picture)]
            lines = [
                line for line in lines
                if any(
                    box is not None
                    and box[0] <= line.box[0] + line.box[2] / 2 <= box[0] + box[2]
                    and box[1] <= line.box[1] + line.box[3] / 2 <= box[1] + box[3]
                    for box in inside
                )
            ]
        return {"lines": [{"text": line.text, "box": list(line.box)} for line in lines]}

    def show(self, q: dict) -> dict:
        """Lets a person watch the monitor in a browser. Without `view_only` the person can also use it."""
        return {"password": self.watch.start(bool(q.get("view_only"))), "port": WEB_PORT}

    def busy(self, q: dict) -> dict:
        """For each area of the picture, the part of it that is something. An arrow is drawn where little is."""
        return {"shares": screen.busy(self._shot(), q["areas"])}

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
