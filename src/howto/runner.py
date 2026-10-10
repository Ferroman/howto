"""Runs setup, the steps and cleanup against a stage, for a probe or a take.

A stage is whatever performs the actions: the Playwright browser in real use,
a fake in the tests. This module knows nothing about Playwright.

Cleanup runs whenever setup completed, including after a failed step and
after Ctrl+C, because the steps may already have changed data.
"""
from __future__ import annotations

import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Protocol, Sequence

from .narrate import Clip
from .storyboard import MARK_ACTIONS, Action, Locator, Pace, Step, Storyboard
from .timeline import StepTime, narration_length, place_clips, step_hold
from .zoom import Box


class StepFailed(Exception):
    """An action could not be performed. The message names the action and the reason."""


@dataclass(frozen=True)
class PageReport:
    url: str
    title: str
    outline: str
    omitted: int = 0
    # What happened in the browser that the steps did not handle: a dialog
    # that was dismissed, a tab that opened.
    notices: tuple[str, ...] = ()


# The actions that put the pointer on an element. A zoom aims at that element.
POINTER_ACTIONS = ("click", "hover", "fill", "select")
# The actions that change which part of the page is in view. The picture goes
# wide before them, because the zoomed part would be somewhere else afterwards.
MOVING_ACTIONS = ("goto", "scroll_to")
# The actions that may change the page under a mark. The marks go as such an
# action lands, so that none is left on a page that no longer has its target.
CLEARING_ACTIONS = ("click", "press", "select")


class Stage(Protocol):
    def perform(self, action: Action, pace: Pace) -> None: ...
    def zoom_to(self, action: Action, factor: float, animate: bool) -> None: ...
    def zoom_out(self, animate: bool) -> None: ...
    def mark(self, action: Action, draw: bool) -> None: ...
    def clear_marks(self, animate: bool) -> None: ...
    def crop_to(self, action: Action, notes: Sequence[str]) -> Box: ...
    def start_recording(self, path: Path) -> None: ...
    def stop_recording(self) -> None: ...
    def show_chapter(self, title: str, seconds: float) -> None: ...
    def show_note(self, text: str) -> None: ...
    def hide_note(self) -> None: ...
    def report(self, within: Locator | None, max_chars: int) -> PageReport: ...


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class Interrupt:
    """A request to stop: Ctrl+C, or the signal a shell sends when a time limit ends.

    Python's own handling raises KeyboardInterrupt wherever the program
    happens to be. In the middle of a browser call that is inside Playwright's
    event loop, which does not survive it: every later call, including the
    ones that stop the recording and run cleanup, then waits forever. So
    while a browser is open the signal only leaves a mark here, and `check`
    raises KeyboardInterrupt at a point between browser calls.
    """

    def __init__(self) -> None:
        self._requested = False
        self.stopped = False  # True once `check` has raised

    def request(self, *_: object) -> None:
        self._requested = True

    def check(self) -> None:
        if self._requested:
            self._requested = False
            self.stopped = True
            raise KeyboardInterrupt

    @contextmanager
    def listening(self) -> Iterator["Interrupt"]:
        """Routes SIGINT and SIGTERM to this object for the length of the block."""
        if threading.current_thread() is not threading.main_thread():
            # Only the main thread may set a signal handler, and only it gets Ctrl+C.
            yield self
            return
        previous = {signum: signal.signal(signum, self.request) for signum in (signal.SIGINT, signal.SIGTERM)}
        try:
            yield self
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        # A signal that arrived during the last browser call has not been checked yet.
        self.check()


class RealClock:
    def __init__(self, interrupt: Interrupt | None = None) -> None:
        self._interrupt = interrupt or Interrupt()

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        # In slices, so that a request to stop ends a long pause at once.
        end = time.monotonic() + seconds
        while True:
            self._interrupt.check()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.1))


@dataclass(frozen=True)
class StepResult:
    index: int  # 0 is `setup`
    ok: bool
    summary: str
    error: str | None = None


@dataclass(frozen=True)
class RunResult:
    steps: tuple[StepResult, ...]
    warnings: tuple[str, ...] = ()
    timeline: tuple[StepTime, ...] = ()
    page: PageReport | None = None
    # The part of the window that the picture is cut to. None is the whole window.
    crop: Box | None = None

    @property
    def failed(self) -> StepResult | None:
        return next((step for step in self.steps if not step.ok), None)


def summarize(step: Step) -> str:
    parts = [f'chapter "{step.chapter}"'] if step.chapter else []
    parts.extend(action.describe() for action in step.do)
    return "; ".join(parts) or "narration only"


def _setup(storyboard: Storyboard, stage: Stage) -> StepResult | None:
    for action in storyboard.setup:
        try:
            stage.perform(action, storyboard.pace)
        except StepFailed as exc:
            return StepResult(0, False, action.describe(), str(exc))
    return None


def _cleanup(storyboard: Storyboard, stage: Stage) -> tuple[str, ...]:
    warnings = []
    for number, action in enumerate(storyboard.cleanup, 1):
        try:
            stage.perform(action, storyboard.pace)
        except StepFailed as exc:
            warnings.append(f"cleanup[{number}]: {exc}")
    return tuple(warnings)


def _crop(storyboard: Storyboard, stage: Stage) -> tuple[Box | None, StepResult | None]:
    """Has the stage measure the storyboard's `crop`, on the page as setup left it.

    A crop that cannot be found is reported as a failed setup: no step has run yet.
    """
    if storyboard.crop is None:
        return None, None
    action = Action(kind="crop", locator=storyboard.crop)
    # The stage makes room for the notes next to the crop, so it needs to know them now.
    notes = tuple(step.note for step in storyboard.steps if step.note)
    try:
        return stage.crop_to(action, notes), None
    except StepFailed as exc:
        return None, StepResult(0, False, action.describe(), str(exc))


def _factor(step: Step, storyboard: Storyboard) -> float:
    return storyboard.zoom if step.zoom is None else step.zoom


class _Picture:
    """What the actions of a step have done to the picture: enlarged it, drawn on it, or both.

    Each flag is set before the stage is asked, so that a call which fails or
    is interrupted halfway is still undone by `restore`.
    """

    def __init__(self, stage: Stage) -> None:
        self._stage = stage
        self.zoomed = False
        self.marked = False

    def zoom_to(self, action: Action, factor: float, animate: bool) -> None:
        self.zoomed = True
        self._stage.zoom_to(action, factor, animate)

    def mark(self, action: Action, draw: bool) -> None:
        self.marked = self.marked or draw
        self._stage.mark(action, draw)

    def clear(self, animate: bool) -> None:
        if self.marked:
            self._stage.clear_marks(animate)
            self.marked = False

    def widen(self, animate: bool) -> None:
        if self.zoomed:
            self._stage.zoom_out(animate)
            self.zoomed = False

    def restore(self, animate: bool) -> None:
        """A clean picture at the page's own size. The marks go first: they are placed for the enlarged picture."""
        self.clear(animate)
        self.widen(animate)


def _act(step: Step, stage: Stage, picture: _Picture, pace: Pace, factor: float, clock: Clock | None = None) -> None:
    """Performs a step's actions, and draws its marks.

    With a `factor` above 1 the picture goes in before a pointer action or a
    mark, and moves on to the next target. A moment after the last action it
    goes wide again, so that the viewer sees what the action changed.

    A mark stays until an action that may change the page under it. Marks
    that are still there when the actions end are left, with the enlargement
    under them, for the caller: they belong to what is being said.

    Without a clock nothing is drawn or animated and nothing waits. That is a
    probe, which zooms and looks for the element of each mark only so that it
    meets the page as the take will.
    """
    animate = clock is not None
    for action, following in zip(step.do, (*step.do[1:], None)):
        if action.kind in MOVING_ACTIONS:
            picture.restore(animate)
        elif factor > 1 and action.kind in POINTER_ACTIONS + MARK_ACTIONS:
            picture.zoom_to(action, factor, animate)
        if action.kind in MARK_ACTIONS:
            picture.mark(action, animate)
            if clock is not None and (following is None or following.kind not in MARK_ACTIONS):
                clock.sleep(pace.mark_hold)
            continue
        stage.perform(action, pace)
        if action.kind in CLEARING_ACTIONS:
            picture.clear(animate)
    if picture.zoomed and not picture.marked:
        if clock is not None:
            clock.sleep(pace.zoom_hold)
        picture.widen(animate)


def run_probe(
    storyboard: Storyboard,
    stage: Stage,
    *,
    until: int | None = None,
    within: Locator | None = None,
    max_chars: int = 20_000,
) -> RunResult:
    """Performs the actions with no recording and no waiting, then describes the page.

    The page is described before cleanup runs, because the reader wants the
    page the steps ended on.
    """
    failure = _setup(storyboard, stage)
    if failure:
        return RunResult(steps=(failure,), page=stage.report(within, max_chars))
    results: list[StepResult] = []
    page = None
    warnings: tuple[str, ...] = ()
    crop = None
    try:
        crop, failure = _crop(storyboard, stage)
        steps = storyboard.steps[:until]
        if failure:
            # No step runs on a page whose crop is missing. The page is still described.
            results.append(failure)
            steps = ()
        for step in steps:
            picture = _Picture(stage)
            try:
                _act(step, stage, picture, storyboard.pace, _factor(step, storyboard))
            except StepFailed as exc:
                results.append(StepResult(step.index, False, summarize(step), str(exc)))
                break
            finally:
                # Also after a failed or interrupted step: the page report and
                # cleanup must meet the page at its own size.
                picture.restore(False)
            results.append(StepResult(step.index, True, summarize(step)))
        page = stage.report(within, max_chars)
    finally:
        warnings = _cleanup(storyboard, stage)
    return RunResult(steps=tuple(results), warnings=warnings, page=page, crop=crop)


def _play(
    step: Step, stage: Stage, picture: _Picture, clock: Clock, pace: Pace, factor: float, cards: bool
) -> None:
    if step.note:
        stage.show_note(step.note)
    if step.chapter and cards:
        shown = clock.now()
        stage.show_chapter(step.chapter, pace.chapter_hold)
        # show_chapter may or may not wait for the card itself; hold for the rest.
        clock.sleep(pace.chapter_hold - (clock.now() - shown))
    if step.do:
        clock.sleep(pace.lead)
        _act(step, stage, picture, pace, factor, clock)


def run_take(
    storyboard: Storyboard,
    stage: Stage,
    clips: Mapping[int, Sequence[Clip]],
    clock: Clock,
    video: Path,
    *,
    animated: bool = False,
) -> RunResult:
    """Records the steps, paced by the narration, and returns the timeline.

    An `animated` take is for a picture that loops without sound. The caller
    gives it no clips, so each step lasts as long as its actions and its
    pause. No title card is shown, and the stage is told which part of the
    window the storyboard's `crop` names, because the notes and the arrows
    must be placed inside it. A narrated take films the whole window.
    """
    failure = _setup(storyboard, stage)
    if failure:
        return RunResult(steps=(failure,))
    pace = storyboard.pace
    results: list[StepResult] = []
    times: list[StepTime] = []
    warnings: tuple[str, ...] = ()
    recording = False
    crop = None
    try:
        if animated:
            crop, failure = _crop(storyboard, stage)
        steps = storyboard.steps
        if failure:
            # Nothing is recorded. Setup completed, so cleanup still runs.
            results.append(failure)
            steps = ()
        else:
            stage.start_recording(video)
            recording = True
        zero = clock.now()
        for step in steps:
            start = clock.now() - zero
            step_clips = tuple(clips.get(step.index, ()))
            picture = _Picture(stage)
            try:
                _play(step, stage, picture, clock, pace, _factor(step, storyboard), cards=not animated)
                narration = narration_length([clip.duration for clip in step_clips], pace.sentence_gap)
                elapsed = clock.now() - zero - start
                hold = step_hold(elapsed=elapsed, narration=narration, gap=pace.gap, pause=step.pause)
                if picture.marked:
                    # The marks stay while the step is spoken. Taking them away
                    # is the gap before the next step, or longer than the gap.
                    clock.sleep(hold - pace.gap)
                    began = clock.now()
                    picture.restore(True)
                    clock.sleep(pace.gap - (clock.now() - began))
                else:
                    clock.sleep(hold)
            except StepFailed as exc:
                results.append(StepResult(step.index, False, summarize(step), str(exc)))
                break
            finally:
                # After a failed or interrupted step, what follows, the end of
                # the recording and cleanup, must meet a clean page at its own size.
                picture.restore(False)
            if step.note:
                stage.hide_note()
            times.append(StepTime(step.index, start, clock.now() - zero, place_clips(start, step_clips, pace.sentence_gap)))
            results.append(StepResult(step.index, True, summarize(step)))
    finally:
        # Cleanup has its own `finally`: a recording that cannot be stopped
        # must not leave the data as the steps changed it.
        try:
            if recording:
                stage.stop_recording()
        finally:
            warnings = _cleanup(storyboard, stage)
    return RunResult(steps=tuple(results), warnings=warnings, timeline=tuple(times), crop=crop)
