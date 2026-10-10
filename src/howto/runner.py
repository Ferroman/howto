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
from .storyboard import Action, Locator, Pace, Step, Storyboard
from .timeline import StepTime, narration_length, place_clips, step_hold


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


class Stage(Protocol):
    def perform(self, action: Action, pace: Pace) -> None: ...
    def zoom_to(self, action: Action, factor: float, animate: bool) -> None: ...
    def zoom_out(self, animate: bool) -> None: ...
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


def _factor(step: Step, storyboard: Storyboard) -> float:
    return storyboard.zoom if step.zoom is None else step.zoom


def _act(step: Step, stage: Stage, pace: Pace, factor: float, clock: Clock | None = None) -> None:
    """Performs a step's actions. With a `factor` above 1 the picture zooms in on each target.

    The picture goes in before a pointer action, moves on to the next target,
    and goes wide again a moment after the last action, so that the viewer
    sees what the action changed. Without a clock nothing is animated and
    nothing waits: that is a probe, which zooms only so that it meets the page
    as the take will.
    """
    animate = clock is not None
    zoomed = False
    try:
        for action in step.do:
            if zoomed and action.kind in MOVING_ACTIONS:
                stage.zoom_out(animate)
                zoomed = False
            elif factor > 1 and action.kind in POINTER_ACTIONS:
                # Marked first: a zoom that fails halfway is undone below.
                zoomed = True
                stage.zoom_to(action, factor, animate)
            stage.perform(action, pace)
        if zoomed:
            if clock is not None:
                clock.sleep(pace.zoom_hold)
            stage.zoom_out(animate)
            zoomed = False
    finally:
        if zoomed:
            # A failed or interrupted step. What follows, the page report and
            # cleanup, must meet the page at its own size.
            stage.zoom_out(False)


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
    try:
        for step in storyboard.steps[:until]:
            try:
                _act(step, stage, storyboard.pace, _factor(step, storyboard))
            except StepFailed as exc:
                results.append(StepResult(step.index, False, summarize(step), str(exc)))
                break
            results.append(StepResult(step.index, True, summarize(step)))
        page = stage.report(within, max_chars)
    finally:
        warnings = _cleanup(storyboard, stage)
    return RunResult(steps=tuple(results), warnings=warnings, page=page)


def _play(step: Step, stage: Stage, clock: Clock, pace: Pace, factor: float) -> None:
    if step.note:
        stage.show_note(step.note)
    if step.chapter:
        shown = clock.now()
        stage.show_chapter(step.chapter, pace.chapter_hold)
        # show_chapter may or may not wait for the card itself; hold for the rest.
        clock.sleep(pace.chapter_hold - (clock.now() - shown))
    if step.do:
        clock.sleep(pace.lead)
        _act(step, stage, pace, factor, clock)


def run_take(
    storyboard: Storyboard,
    stage: Stage,
    clips: Mapping[int, Sequence[Clip]],
    clock: Clock,
    video: Path,
) -> RunResult:
    """Records the steps, paced by the narration, and returns the timeline."""
    failure = _setup(storyboard, stage)
    if failure:
        return RunResult(steps=(failure,))
    pace = storyboard.pace
    results: list[StepResult] = []
    times: list[StepTime] = []
    warnings: tuple[str, ...] = ()
    recording = False
    try:
        stage.start_recording(video)
        recording = True
        zero = clock.now()
        for step in storyboard.steps:
            start = clock.now() - zero
            step_clips = tuple(clips.get(step.index, ()))
            try:
                _play(step, stage, clock, pace, _factor(step, storyboard))
            except StepFailed as exc:
                results.append(StepResult(step.index, False, summarize(step), str(exc)))
                break
            narration = narration_length([clip.duration for clip in step_clips], pace.sentence_gap)
            elapsed = clock.now() - zero - start
            clock.sleep(step_hold(elapsed=elapsed, narration=narration, gap=pace.gap, pause=step.pause))
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
    return RunResult(steps=tuple(results), warnings=warnings, timeline=tuple(times))
