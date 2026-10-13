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

from .. import marks, notes, overlay, zoom
from ..errors import RunError
from ..probe import cut_outline
from ..runner import Interrupt, PageReport, StepFailed
from ..storyboard import MARK_ACTIONS, Action, Locator, Pace, Storyboard
from ..tools import action_timeout, docker_command
from . import images, profiles, takelog, viewer
from .link import HelperError, open_link
from .takelog import Move, Shown, TakeLog

# Seconds that a request which does one quick thing may take.
QUICK = 15.0
# What the helper refuses because of the storyboard or the app. Whatever else it refuses is howto's own failure.
STEP_KINDS = ("covered", "cannot_scroll", "app_exited", "bad_key")
# Seconds the button stays down in a take, so that the viewer sees the press.
PRESS = 0.06
# How fast the pointer travels in a take, in pixels of the picture a second, and its shortest and longest way.
POINTER_SPEED = 1500.0
POINTER_QUICKEST, POINTER_SLOWEST = 0.25, 0.9
# For an arrow: how wide the area around each of its points is that the helper looks at, in pixels of the
# picture, and from which part on that area counts as something.
PATCH = 12.0
# Seconds that the picture takes to move to another part of itself, as on a web page (`capture.ZOOM_MS`).
ZOOM = 0.8
BUSY_FROM = 0.1
# Pixels at the edge of the picture where an arrow does not go, as on a web page.
EDGE = 4.0
# Seconds that a mark, a ring or a card takes to appear. Measured: Chromium drew the 321 pictures of a
# 60 s take in 13.1 s, over the 10 s mark, so nothing is stepped frame by frame here. Each appears at once.
GROW = 0.0


@dataclass(frozen=True)
class Found:
    """Where a locator found its element, in pixels of the picture, and the window it is in."""

    box: zoom.Box
    window: str = ""

    @property
    def middle(self) -> tuple[float, float]:
        return self.box.x + self.box.width / 2, self.box.y + self.box.height / 2


def scale_of(storyboard: Storyboard) -> int:
    """How many pixels of the monitor one pixel of the picture is: 2 for a storyboard that zooms.

    An app cannot enlarge itself as a page can. So the monitor of a
    storyboard that zooms has twice the size, and a zoom is a cut of the
    recording. A storyboard without a zoom keeps a monitor of the picture's
    size: four times the pixels are four times the work.
    """
    return 2 if storyboard.zooms else 1


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
        sleep=time.sleep,
        shots: Path | None = None,
        heights=overlay.strip_heights,
    ) -> None:
        self._link = link
        self._board = storyboard
        self.viewport = storyboard.viewport
        # Where the screenshot of a report goes. None: the report has neither a screenshot nor words.
        self._shots = shots
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
        self._sleep = sleep
        # The marks that are on the picture now: when each was drawn, and its HTML.
        self._marks: list[tuple[float, str]] = []
        self._scale = scale_of(storyboard)
        # The part of the picture that the viewer sees enlarged. None is the whole picture.
        self._window: zoom.Window | None = None
        self._moves: list[Move] = []
        # The part of the picture that an animated picture is cut to. None is the whole picture. See `crop_to`.
        self._crop: zoom.Box | None = None
        # The strip for the notes of a cropped picture, and whether it lies outside the crop. See `crop_to`.
        self._strip: zoom.Box | None = None
        self._strip_outside = False
        self._heights = heights
        # The actions whose element the crop leaves out of the picture.
        self._left_out: list[str] = []

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
        fields = {"locator": wire(locator), "timeout": self.timeout}
        if action.kind in MARK_ACTIONS:
            # A mark goes around the words of a label, not around the room that the app gave it.
            fields["tight"] = True
        reply = self._ask("find", limit=self.timeout + QUICK, **fields)
        self._counted(action, reply)
        self._touched.add(reply.get("window", ""))
        return Found(zoom.Box(*reply["box"]), reply.get("window", ""))

    def _time(self) -> float:
        """Seconds since the take began."""
        return self._now() - self._zero

    def _wait(self, seconds: float) -> None:
        """Lets a part of the take pass. In slices, so that a request to stop ends the wait at once."""
        end = self._now() + seconds
        while True:
            self._interrupt.check()
            left = end - self._now()
            if left <= 1e-6:
                return
            self._sleep(min(left, 0.1))

    def _seen(self, box: zoom.Box) -> zoom.Box:
        """Where a part of the picture is in what the viewer sees: its own place, or its place in the enlarged picture."""
        return box if self._window is None else self._window.to_screen(box)

    def _move(self, window: zoom.Window | None, animate: bool) -> None:
        """Shows another part of the picture, or the whole of it for None. In a take the move goes into the log."""
        if window == self._window:
            return
        self._window = window
        if self._video is None:
            return
        seconds = ZOOM if animate else 0.0
        to = window or zoom.Window(0.0, 0.0, 1.0)
        self._moves.append(Move(self._time(), seconds, to.left, to.top, to.factor))
        self._wait(seconds)

    def _check_crop(self, action: Action, box: zoom.Box) -> None:
        """Keeps a note of an action whose element the crop leaves out of the picture.

        The author of a storyboard is often a model that cannot look at the
        picture, and a probe is where it learns that nothing would be seen.
        """
        if self._crop is None or zoom.inside(box, self._crop):
            return
        notice = f"{action.describe()}: the element is not inside the crop"
        if notice not in self._left_out:
            self._left_out.append(notice)

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
        seen = self._seen(zoom.Box(*found.middle, 0, 0))
        self._shown.append(Shown("click", at, at + ring, notes.ring_html(seen.x, seen.y), grow=GROW))
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
        else:
            found = self._find(action)
            self._check_crop(action, found.box)
            if kind == "hover":
                self._point(found)
                return
            self._press(found)
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
        """Enlarges the picture around the element that an action names. Without `animate` it is there at once.

        Nothing happens on the monitor. The move goes into the log, and the
        assembly cuts the enlarged part out of the recording.
        """
        try:
            found = self._find(action)
        except HelperError as exc:
            raise self._refused(action, exc) from None
        if self._marks and zoom.on_screen(self._seen(found.box), self.viewport):
            # The picture holds still while something is drawn on it, as long as the next target is in it.
            return
        # From here on the picture may move, and a mark would stay behind.
        self.clear_marks(animate)
        window = zoom.frame(found.box, self.viewport, factor)
        if window is not None:
            # Its corner at whole pixels of the picture, which are even pixels of the recording. ffmpeg cuts
            # there without a remainder, so a mark lies exactly where its control is.
            window = zoom.Window(float(math.floor(window.left)), float(math.floor(window.top)), window.factor)
        self._move(window, animate)

    def zoom_out(self, animate: bool) -> None:
        """Back to the whole picture. Does nothing when the picture is wide."""
        self.clear_marks(animate)
        self._move(None, animate)

    def _busy(self, candidates: Sequence[marks.Arrow], picture: zoom.Box) -> list[int]:
        """For each way to draw an arrow, how many of its points lie on something, or outside the picture.

        The browser stage asks the page what lies at each point. Here the
        helper looks at a screenshot: a small area around a point that is
        not of one colour has something in it. That also serves a canvas.
        """
        counts = [0] * len(candidates)
        asked: list[tuple[int, list[float]]] = []
        right, bottom = picture.x + picture.width - EDGE, picture.y + picture.height - EDGE
        for index, candidate in enumerate(candidates):
            for x, y in candidate.points:
                if x < picture.x + EDGE or y < picture.y + EDGE or x > right or y > bottom:
                    # An arrow must not leave the picture.
                    counts[index] += 1
                else:
                    patch = zoom.Box(x - PATCH / 2, y - PATCH / 2, PATCH, PATCH)
                    if self._window is not None:
                        # The arrow lies on the enlarged picture, and the helper looks at the picture at its own size.
                        patch = self._window.to_page(patch)
                    asked.append((index, [patch.x, patch.y, patch.width, patch.height]))
        if asked:
            shares = self._ask("busy", limit=2 * QUICK, areas=[area for _, area in asked])["shares"]
            for (index, _), share in zip(asked, shares):
                counts[index] += share > BUSY_FROM
        return counts

    def mark(self, action: Action, draw: bool) -> None:
        """Finds the element of a mark. With `draw` the mark goes into the log, and the take waits for the time a mark is on screen."""
        try:
            found = self._find(action)
            self._check_crop(action, found.box)
            if not draw:
                return
            target = self._seen(found.box)
            if action.kind == "arrow":
                picture = self._crop or zoom.Box(0, 0, *self.viewport)
                candidates = marks.arrows(target, self.viewport, action.value, self._crop)
                drawing = marks.arrow(marks.emptiest(candidates, self._busy(candidates, picture)))
            else:
                drawing = marks.SHAPES[action.kind](target, self.viewport)
        except HelperError as exc:
            raise self._refused(action, exc) from None
        self._marks.append((self._time(), marks.layer(drawing, self.viewport)))
        self._wait(marks.DRAW_MS / 1000)

    def clear_marks(self, animate: bool) -> None:
        """Takes every mark off the picture. With `animate` they fade, and the take waits for that."""
        if not self._marks:
            return
        fade = marks.FADE_MS / 1000 if animate else 0.0
        end = self._time() + fade
        for start, html in self._marks:
            self._shown.append(Shown("mark", start, end, html, grow=GROW, fade=fade))
        self._marks = []
        self._wait(fade)

    def crop_to(self, action: Action, notes_: Sequence[str]) -> zoom.Box:
        """Measures the part of the picture that an animated picture is cut to, and returns it.

        The recording still shows the whole monitor, and whoever makes the
        picture cuts it out. What changes here is where things are drawn. An
        arrow stays inside the crop. The notes get a strip next to it, as tall
        as the longest of them needs, and the picture grows by that strip.
        """
        try:
            found = self._find(action)
        except HelperError as exc:
            raise self._refused(action, exc) from None
        cut = zoom.crop(found.box, self.viewport)
        if cut is None:
            raise StepFailed(f"{action.describe()}: the element has no size, so there is no picture to cut to it")
        self._crop, self._strip, self._strip_outside = cut, None, False
        if not notes_:
            return cut
        # Chromium measures, and nothing stops it halfway: a request to stop is acted on before it and after it.
        self._interrupt.check()
        try:
            tallest = max(self._heights(list(notes_), cut.width))
        finally:
            self._interrupt.check()
        self._strip, self._strip_outside = zoom.strip(cut, tallest, self.viewport)
        return zoom.union(cut, self._strip)

    def start_recording(self, path: Path) -> None:
        reply = self._ask("record_start", limit=2 * QUICK)
        self._video = Path(path)
        self._zero = self._now()
        # The recording began before the take. A first frame that came later would be a clock that jumped.
        self._head = max(0.0, self._zero - reply["first_frame"])
        self._shown = []
        self._note = None
        self._marks = []
        self._window = None
        self._moves = []

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
        for start, html in self._marks:
            self._shown.append(Shown("mark", start, end, html, grow=GROW))
        self._marks = []
        if self._strip is not None and self._strip_outside:
            # A strip outside the crop lies on a part of the monitor that is not the picture's subject,
            # so it is there for the whole take, with a note or without.
            self._shown.insert(0, Shown("strip", 0.0, end, notes.strip_html(self._strip)))
        if self._note is not None:
            self._shown.append(Shown("note", self._note[0], end, self._note[1]))
            self._note = None
        log = TakeLog(
            viewport=self.viewport, head=self._head, shown=tuple(self._shown), scale=self._scale, moves=tuple(self._moves)
        )
        takelog.write(log, takelog.beside(video))

    def show_chapter(self, title: str, seconds: float) -> None:
        fade = notes.CARD_FADE_MS / 1000
        at = self._time()
        self._shown.append(Shown("card", at, at + seconds + fade, notes.card_html(title), grow=GROW, fade=fade))

    def show_note(self, text: str) -> None:
        self._note = (self._time(), notes.note_html(text, self._strip))

    def hide_note(self) -> None:
        if self._note is not None:
            start, html = self._note
            self._note = None
            self._shown.append(Shown("note", start, self._time(), html))

    def report(self, within: Locator | None, max_chars: int) -> PageReport:
        inside = wire(within) if within is not None else None
        try:
            reply = self._ask("outline", limit=2 * QUICK, within=inside)
            kept, omitted = cut_outline(reply["outline"], max_chars)
            words, screenshot = self._screen(inside, max_chars - len(kept) if not omitted else 0)
        except HelperError as exc:
            raise RunError(f"the desktop failed: {exc}") from None
        notices = []
        if reply.get("ended") is not None:
            notices.append(f"the app ended with exit code {reply['ended']}")
        # The first window is the app itself, whatever title it has by now.
        known = self._touched | {reply.get("first", "")}
        for title in reply.get("windows", ()):
            if title and title not in known:
                notices.append(f'a window opened that no step touched: "{title}"')
        notices += self._left_out
        return PageReport(
            url=f"app {self._board.app.run}", title=reply.get("title", ""), outline=kept,
            omitted=omitted + words[1], notices=tuple(notices), words=words[0], screenshot=screenshot,
        )

    def _screen(self, inside: dict | None, room: int) -> tuple[tuple[tuple[str, ...], int], str]:
        """The words that the outline lacks, as many as `room` characters hold, with how many were left out, and the screenshot."""
        if self._shots is None:
            return ((), 0), ""
        shot = self._ask("screenshot", limit=2 * QUICK)["path"]
        read = self._ask("words", limit=4 * QUICK, lacking=True, within=inside, shot=shot)
        kept, left_out = [], 0
        for line in map(_copyable, read["lines"]):
            # A line costs its characters and a line break.
            if left_out == 0 and len(line) + 1 <= room:
                kept.append(line)
                room -= len(line) + 1
            else:
                left_out += len(line)
        self._link.fetch(shot, self._shots)
        return (tuple(kept), left_out), str(self._shots)


def _copyable(line: dict) -> str:
    """A line of words as a probe prints it: the words, and a locator that names their place."""
    x, y, width, height = line["box"]
    return f'"{line["text"]}" {{at: {int(x)}x{int(y)}, size: {max(1, round(width))}x{max(1, round(height))}}}'


@contextmanager
def _container(storyboard: Storyboard, *, scale: int, profile: str | None, publish: int | None) -> Iterator[tuple]:
    """A container with the storyboard's app started, and its first window filling the monitor.

    Yields the link, what `start` answered, and the time limit of an action. `profile` names the
    volume that is the app's home, and `publish` a port of the container that Docker serves on this machine.
    """
    docker = docker_command()
    images.check(docker, storyboard.app.image)
    timeout = action_timeout()
    width, height = storyboard.viewport
    link = open_link(docker, storyboard.app.image, volume=profiles.volume(profile) if profile else None, publish=publish)
    try:
        try:
            started = link.request(
                "start", limit=3 * timeout + 2 * QUICK, run=storyboard.app.run, width=width, height=height,
                scale=scale, timeout=3 * timeout,
            )
        except HelperError as exc:
            raise RunError(str(exc)) from None
        # What runs is what counts: the label of the image said the same a moment ago, unless the image was replaced.
        images.check(docker, storyboard.app.image, built=started.get("build", ""))
        yield link, started, timeout
    finally:
        link.close()


def _watch(link, *, view_only: bool, open_viewer):
    """Has the helper show its monitor, and opens the window on it."""
    try:
        shown = link.request("show", limit=4 * QUICK, view_only=view_only)
    except HelperError as exc:
        raise RunError(f"the desktop failed: {exc}") from None
    return open_viewer(viewer.address(link.port(viewer.PORT), shown["password"], view_only=view_only))


def login(storyboard: Storyboard, profile: str, *, open_viewer=viewer.Viewer) -> None:
    """Starts the app of a storyboard on a profile, and shows it until the person closes the window.

    The profile is made when it is new. The monitor has the size of the picture, whatever the
    storyboard zooms: a sign-in needs no larger one.
    """
    profiles.create(docker_command(), profile)
    with _container(storyboard, scale=1, profile=profile, publish=viewer.PORT) as (link, _, _):
        window = _watch(link, view_only=False, open_viewer=open_viewer)
        try:
            window.wait()
        finally:
            window.close()


@contextmanager
def open_stage(
    storyboard: Storyboard, *, interrupt: Interrupt | None = None, shots: Path | None = None, show: bool = False,
    open_viewer=viewer.Viewer,
) -> Iterator[DesktopStage]:
    """The stage of a desktop storyboard: its app in a container, on its profile when it names one."""
    if storyboard.profile and not profiles.exists(docker_command(), storyboard.profile):
        # Before the container: Docker makes a volume that a container names, and it would be an empty home.
        raise RunError(
            f"profile `{storyboard.profile}` does not exist: "
            f"run `howto login {storyboard.profile} {storyboard.origin}`"
        )
    publish = viewer.PORT if show else None
    with _container(storyboard, scale=scale_of(storyboard), profile=storyboard.profile, publish=publish) as (
        link, started, timeout,
    ):
        # A watcher cannot disturb the steps: the server of the window takes no input.
        window = _watch(link, view_only=True, open_viewer=open_viewer) if show else None
        try:
            yield DesktopStage(
                link, storyboard, timeout=timeout, first=started.get("title", ""), interrupt=interrupt, shots=shots
            )
        finally:
            if window is not None:
                window.close()
