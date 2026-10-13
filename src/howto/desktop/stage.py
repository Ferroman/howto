"""The desktop stage: performs a storyboard on an app in a container, through the helper there.

`runner` drives it as it drives the browser stage. Each action becomes a few
requests to the helper: find the element, move the pointer, click, type.
"""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .. import notes, zoom
from ..errors import RunError
from ..probe import cut_outline
from ..runner import Interrupt, PageReport, StepFailed
from ..storyboard import Action, Locator, Pace, Storyboard
from ..tools import action_timeout, docker_command
from . import images, takelog
from .link import HelperError, open_link
from .takelog import Shown, TakeLog

# Seconds that a request which does one quick thing may take.
QUICK = 15.0
# What the helper refuses because of the storyboard or the app. Whatever else it refuses is howto's own failure.
STEP_KINDS = ("covered", "cannot_scroll", "app_exited", "bad_key")
# Seconds the button stays down in a take, so that the viewer sees the press.
PRESS = 0.06
# How fast the pointer travels in a take, in pixels of the picture a second, and its shortest and longest way.
POINTER_SPEED = 1500.0
POINTER_QUICKEST, POINTER_SLOWEST = 0.25, 0.9


@dataclass(frozen=True)
class Found:
    """Where a locator found its element, in pixels of the picture, and the window it is in."""

    box: zoom.Box
    window: str = ""

    @property
    def middle(self) -> tuple[float, float]:
        return self.box.x + self.box.width / 2, self.box.y + self.box.height / 2


def wire(locator: Locator) -> dict:
    """A locator of the tree as the helper reads it."""
    sent: dict = {
        key: getattr(locator, key) for key in ("role", "name", "label", "text") if getattr(locator, key) is not None
    }
    if locator.exact:
        sent["exact"] = True
    if locator.nth is not None:
        sent["nth"] = locator.nth
    if locator.within is not None:
        sent["within"] = wire(locator.within)
    return sent


def _missing(reply: dict) -> str:
    """Why nothing was found: where the helper looked, and the nearest words it has."""
    screen = "screen" in reply.get("tried", ())
    text = "not in the tree, and no such words on the screen" if screen else "not in the tree"
    nearest = reply.get("nearest") or []
    if nearest:
        text += f". The nearest {'words' if screen else 'names'}: " + ", ".join(f'"{words}"' for words in nearest)
    return text


def _later(what: str) -> RunError:
    return RunError(f"{what} of a desktop app is not built yet: `howto probe` is")


class DesktopStage:
    def __init__(
        self,
        link,
        storyboard: Storyboard,
        *,
        timeout: float,
        first: str = "",
        interrupt: Interrupt | None = None,
        now=time.monotonic,
    ) -> None:
        self._link = link
        self._board = storyboard
        self.viewport = storyboard.viewport
        self.timeout = timeout
        self._interrupt = interrupt or Interrupt()
        self._now = now
        # The titles of the windows in which a step found something.
        self._touched = {first}
        # Where the pointer is, in pixels of the picture. The helper parks it in this corner.
        self._pointer = (self.viewport[0] - 24.0, self.viewport[1] - 24.0)
        # While a take is recorded: where its video goes, when it began, and what lies over its picture.
        self._video: Path | None = None
        self._zero = 0.0
        self._head = 0.0
        self._shown: list[Shown] = []
        self._note: tuple[float, str] | None = None

    def _ask(self, request: str, *, limit: float = QUICK, **fields) -> dict:
        """One request to the helper. A request to stop is acted on before it and after it, never during it."""
        self._interrupt.check()
        try:
            return self._link.request(request, limit=limit, **fields)
        finally:
            self._interrupt.check()

    def _refused(self, action: Action, exc: HelperError) -> Exception:
        if exc.kind in STEP_KINDS:
            return StepFailed(f"{action.describe()}: {exc}")
        return RunError(f"the desktop failed: {exc}")

    def _counted(self, action: Action, reply: dict) -> None:
        """Fails the step unless a locator named exactly one element: the tool does not guess."""
        if reply["count"] == 0:
            raise StepFailed(f"{action.describe()}: {_missing(reply)}")
        if reply["count"] != 1:
            raise StepFailed(f"{action.describe()}: {reply['count']} elements match")

    def _find(self, action: Action) -> Found:
        """The one element or the one place that an action names."""
        locator = action.locator
        if locator.at is not None:
            wide, tall = locator.size or (0, 0)
            return Found(zoom.Box(locator.at[0], locator.at[1], wide, tall))
        reply = self._ask("find", limit=self.timeout + QUICK, locator=wire(locator), timeout=self.timeout)
        self._counted(action, reply)
        self._touched.add(reply.get("window", ""))
        return Found(zoom.Box(*reply["box"]), reply.get("window", ""))

    def _time(self) -> float:
        """Seconds since the take began."""
        return self._now() - self._zero

    def _point(self, found: Found) -> None:
        """Moves the pointer to the middle of what was found. In a take it travels there, and in a probe it jumps."""
        x, y = found.middle
        seconds = 0.0
        if self._video is not None:
            far = math.hypot(x - self._pointer[0], y - self._pointer[1])
            seconds = min(POINTER_SLOWEST, max(POINTER_QUICKEST, far / POINTER_SPEED))
        self._ask("pointer", limit=QUICK + seconds, x=x, y=y, seconds=seconds)
        self._pointer = (x, y)

    def _press(self, found: Found) -> None:
        self._point(found)
        if self._video is None:
            self._ask("click", hold=0, window=found.window)
            return
        # The pointer of a desktop shows no click, so a ring spreads from it as the button goes down.
        at, ring = self._time(), notes.RING_MS / 1000
        self._shown.append(Shown("click", at, at + ring, notes.ring_html(*found.middle), grow=ring))
        self._ask("click", hold=PRESS, window=found.window)

    def _type(self, text: str, pace: Pace) -> None:
        rate = pace.typing if self._video is not None else 0
        seconds = len(text) / rate if rate else len(text) / 10
        self._ask("type", limit=QUICK + seconds, text=text, rate=rate)

    def _select(self, action: Action) -> None:
        reply = self._ask("find", limit=self.timeout + QUICK, locator={"option": action.value}, timeout=self.timeout)
        if reply["count"] == 0:
            nearest = reply.get("nearest") or []
            offered = ". The nearest names: " + ", ".join(f'"{name}"' for name in nearest) if nearest else ""
            raise StepFailed(f'{action.describe()}: the list that opened has no item "{action.value}"{offered}')
        self._counted(action, reply)
        self._press(Found(zoom.Box(*reply["box"]), reply.get("window", "")))

    def _run(self, action: Action) -> None:
        limit = 3 * self.timeout
        reply = self._ask("run", limit=limit + QUICK, command=action.value, timeout=limit)
        if reply.get("timed_out"):
            raise StepFailed(f"{action.describe()}: it did not end in {limit:g} seconds")
        if reply["code"] != 0:
            said = f": {reply['output']}" if reply.get("output") else ""
            raise StepFailed(f"{action.describe()}: it ended with exit code {reply['code']}{said}")

    def _act(self, action: Action, pace: Pace) -> None:
        kind = action.kind
        if kind == "press":
            self._ask("key", keys=action.value)
        elif kind == "type":
            self._type(action.value, pace)
        elif kind == "run":
            self._run(action)
        elif kind == "scroll_to":
            if action.locator.at is None:
                reply = self._ask(
                    "scroll_to", limit=self.timeout + QUICK, locator=wire(action.locator), timeout=self.timeout
                )
                self._counted(action, {"tried": ["tree"], **reply})
        elif kind == "wait_for":
            self._find(action)
        elif kind == "hover":
            self._point(self._find(action))
        else:
            self._press(self._find(action))
            if kind == "fill":
                self._ask("key", keys="Control+A")
                self._type(action.value, pace)
            elif kind == "select":
                self._select(action)

    def perform(self, action: Action, pace: Pace) -> None:
        try:
            self._act(action, pace)
        except HelperError as exc:
            raise self._refused(action, exc) from None

    def zoom_to(self, action: Action, factor: float, animate: bool) -> None:
        """A zoom is made after the take, from the recording. Here it finds its target, so that a probe fails as a take would."""
        try:
            self._find(action)
        except HelperError as exc:
            raise self._refused(action, exc) from None

    def zoom_out(self, animate: bool) -> None:
        pass

    def mark(self, action: Action, draw: bool) -> None:
        """Finds the element of a mark, as a probe does."""
        if draw:
            raise _later("a mark")
        try:
            self._find(action)
        except HelperError as exc:
            raise self._refused(action, exc) from None

    def clear_marks(self, animate: bool) -> None:
        pass

    def crop_to(self, action: Action, notes: Sequence[str]) -> zoom.Box:
        raise _later("`crop`")

    def start_recording(self, path: Path) -> None:
        reply = self._ask("record_start", limit=2 * QUICK)
        self._video = Path(path)
        self._zero = self._now()
        # The recording began before the take. A first frame that came later would be a clock that jumped.
        self._head = max(0.0, self._zero - reply["first_frame"])
        self._shown = []
        self._note = None

    def stop_recording(self) -> None:
        """Ends the recording, fetches it, and writes the log of the take beside it."""
        video, self._video = self._video, None
        if video is None:
            return
        end = self._time()
        # Not through `_ask`: a second request to stop must not keep ffmpeg from being ended.
        try:
            reply = self._link.request("record_stop", limit=2 * QUICK)
        except HelperError as exc:
            raise RunError(f"the desktop failed: {exc}") from None
        if self._interrupt.stopped:
            # Nothing will be assembled, so there is nothing to fetch.
            return
        self._link.fetch(reply["path"], video)
        if self._note is not None:
            self._shown.append(Shown("note", self._note[0], end, self._note[1]))
            self._note = None
        takelog.write(TakeLog(viewport=self.viewport, head=self._head, shown=tuple(self._shown)), takelog.beside(video))

    def show_chapter(self, title: str, seconds: float) -> None:
        fade = notes.CARD_FADE_MS / 1000
        at = self._time()
        self._shown.append(Shown("card", at, at + seconds + fade, notes.card_html(title), grow=fade, fade=fade))

    def show_note(self, text: str) -> None:
        self._note = (self._time(), notes.note_html(text))

    def hide_note(self) -> None:
        if self._note is not None:
            start, html = self._note
            self._note = None
            self._shown.append(Shown("note", start, self._time(), html))

    def report(self, within: Locator | None, max_chars: int) -> PageReport:
        try:
            reply = self._ask("outline", limit=2 * QUICK, within=wire(within) if within is not None else None)
        except HelperError as exc:
            raise RunError(f"the desktop failed: {exc}") from None
        kept, omitted = cut_outline(reply["outline"], max_chars)
        notices = []
        if reply.get("ended") is not None:
            notices.append(f"the app ended with exit code {reply['ended']}")
        # The first window is the app itself, whatever title it has by now.
        known = self._touched | {reply.get("first", "")}
        for title in reply.get("windows", ()):
            if title and title not in known:
                notices.append(f'a window opened that no step touched: "{title}"')
        return PageReport(
            url=f"app {self._board.app.run}", title=reply.get("title", ""), outline=kept, omitted=omitted,
            notices=tuple(notices),
        )


@contextmanager
def open_stage(storyboard: Storyboard, *, interrupt: Interrupt | None = None) -> Iterator[DesktopStage]:
    """A container with the storyboard's app started, and its first window filling the monitor."""
    if storyboard.profile:
        raise _later("a profile")
    docker = docker_command()
    images.check(docker, storyboard.app.image)
    timeout = action_timeout()
    width, height = storyboard.viewport
    link = open_link(docker, storyboard.app.image)
    try:
        try:
            started = link.request(
                "start", limit=3 * timeout + 2 * QUICK, run=storyboard.app.run, width=width, height=height,
                timeout=3 * timeout,
            )
        except HelperError as exc:
            raise RunError(str(exc)) from None
        # What runs is what counts: the label of the image said the same a moment ago, unless the image was replaced.
        images.check(docker, storyboard.app.image, built=started.get("build", ""))
        yield DesktopStage(link, storyboard, timeout=timeout, first=started.get("title", ""), interrupt=interrupt)
    finally:
        link.close()
