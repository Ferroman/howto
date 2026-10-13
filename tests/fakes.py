"""A clock and a stage that record what the runner asks of them."""
from __future__ import annotations

from pathlib import Path

from howto.runner import PageReport, StepFailed
from howto.zoom import Box


class FakeClock:
    """Time that moves only when something sleeps or a fake action takes time."""

    def __init__(self) -> None:
        self.t = 100.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds
            self.sleeps.append(round(seconds, 6))


class FakeStage:
    """Records every call. `fail_on` maps an action description to a reason."""

    # What `crop_to` measures, whatever element it is asked for.
    CROP_BOX = Box(100, 50, 340, 250)

    def __init__(
        self,
        clock=None,
        *,
        fail_on=None,
        interrupt_on=(),
        action_seconds=0.0,
        chapter_seconds=0.0,
        zoom_seconds=0.0,
        mark_seconds=0.0,
        clear_seconds=0.0,
        stop_error=None,
    ):
        self.clock = clock
        self.fail_on = dict(fail_on or {})
        self.interrupt_on = set(interrupt_on)
        self.action_seconds = action_seconds
        self.chapter_seconds = chapter_seconds
        self.zoom_seconds = zoom_seconds
        self.mark_seconds = mark_seconds
        self.clear_seconds = clear_seconds
        self.stop_error = stop_error
        self.calls: list[str] = []
        self.report_args = None

    def _spend(self, seconds: float) -> None:
        if self.clock is not None:
            self.clock.t += seconds

    def perform(self, action, pace) -> None:
        described = action.describe()
        self.calls.append(described)
        self._spend(self.action_seconds)
        if described in self.interrupt_on:
            raise KeyboardInterrupt
        if described in self.fail_on:
            raise StepFailed(f"{described}: {self.fail_on[described]}")

    def zoom_to(self, action, factor, animate) -> None:
        # Like the real stage, a zoom finds its target first, so a missing
        # element fails here with the words the action itself would use.
        described = action.describe()
        self.calls.append(f"zoom {factor:g} {described}" + ("" if animate else " at once"))
        if described in self.fail_on:
            raise StepFailed(f"{described}: {self.fail_on[described]}")
        if animate:
            self._spend(self.zoom_seconds)

    def zoom_out(self, animate) -> None:
        self.calls.append("zoom_out" if animate else "zoom_out at once")
        if animate:
            self._spend(self.zoom_seconds)

    def mark(self, action, draw) -> None:
        # Like the real stage, a mark finds its element whether or not it is drawn.
        described = action.describe()
        self.calls.append(f"mark {described}" + ("" if draw else " unseen"))
        if described in self.interrupt_on:
            raise KeyboardInterrupt
        if described in self.fail_on:
            raise StepFailed(f"{described}: {self.fail_on[described]}")
        if draw:
            self._spend(self.mark_seconds)

    def clear_marks(self, animate) -> None:
        self.calls.append("clear_marks" if animate else "clear_marks at once")
        if animate:
            self._spend(self.clear_seconds)

    def crop_to(self, action, notes=()) -> Box:
        described = action.describe()
        self.calls.append(described)
        self.crop_notes = tuple(notes)
        if described in self.fail_on:
            raise StepFailed(f"{described}: {self.fail_on[described]}")
        return self.CROP_BOX

    def start_recording(self, path) -> None:
        self.calls.append("start_recording")
        Path(path).write_bytes(b"fake webm")

    def stop_recording(self) -> None:
        self.calls.append("stop_recording")
        if self.stop_error is not None:
            raise self.stop_error

    def show_chapter(self, title, seconds) -> None:
        self.calls.append(f"chapter {title}")
        self._spend(self.chapter_seconds)

    def show_note(self, text) -> None:
        self.calls.append(f"note {text}")

    def hide_note(self) -> None:
        self.calls.append("hide_note")

    def report(self, within, max_chars) -> PageReport:
        self.calls.append("report")
        self.report_args = (within, max_chars)
        return PageReport(url="http://demo.test/end", title="End", outline='- heading "End" [level=1]')

class ScriptedLink:
    """Stands in for the link to the helper: a list of the requests it expects, and the reply to each.

    A reply is the fields of an answer, an exception to raise, or a function
    of the request's fields that returns the fields of an answer.
    """

    def __init__(self, *script):
        self.script = list(script)
        self.asked: list[tuple[str, dict]] = []
        self.limits: list[float] = []
        self.fetched: list[tuple[str, Path]] = []

    def request(self, request, *, limit, **fields):
        self.asked.append((request, fields))
        self.limits.append(limit)
        assert self.script, f"a request that the script does not have: {request} {fields}"
        expected, reply = self.script.pop(0)
        assert request == expected, f"expected `{expected}`, and `{request}` was asked: {fields}"
        if callable(reply):
            reply = reply(fields)
        if isinstance(reply, Exception):
            raise reply
        return {"ok": True, **reply}

    def fetch(self, inside, out):
        self.fetched.append((inside, Path(out)))
        # The link makes the folder of what it fetches, and so does this.
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fetched")
