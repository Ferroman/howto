import os
import signal
import threading
import time
from pathlib import Path

import pytest

from fakes import FakeClock, FakeStage
from howto.narrate import Clip
from howto.runner import Interrupt, RealClock, run_probe, run_take, summarize
from howto.storyboard import parse, parse_locator

CLICK_A = 'click role=button name="A"'
CLICK_B = 'click role=button name="B"'
CLICK_C = 'click role=button name="C"'
SETUP = 'wait_for role=heading name="Home"'
CLEANUP = 'click role=button name="Undo"'


def click(name):
    return {"click": {"role": "button", "name": name}}


def board(tmp_path, steps, **extra):
    return parse({"title": "Demo", "url": "http://demo.test", "steps": steps, **extra}, tmp_path / "demo.yaml")


def clip(seconds):
    return Clip(text="x", path=Path("/clips/x.wav"), duration=seconds)


def take(tmp_path, steps, clips=None, stage_options=None, **extra):
    clock = FakeClock()
    stage = FakeStage(clock, **(stage_options or {}))
    result = run_take(board(tmp_path, steps, **extra), stage, clips or {}, clock, tmp_path / "capture.webm")
    return result, stage, clock


def test_a_step_lasts_as_long_as_its_narration(tmp_path):
    steps = [{"say": "One. Two.", "do": [click("A")]}, {"do": [click("B")]}]
    result, stage, clock = take(tmp_path, steps, {1: [clip(1.0), clip(2.0)]}, {"action_seconds": 0.3})
    first, second = result.timeline
    # Narration is 1.0 + 0.15 + 2.0 = 3.15 s, longer than lead + action (0.8 s). Plus the 0.4 s gap.
    assert (first.start, first.end) == (0.0, pytest.approx(3.55))
    assert [(c.start, c.end) for c in first.clips] == [(0.0, 1.0), (pytest.approx(1.15), pytest.approx(3.15))]
    # No narration: lead 0.5 + action 0.3 + gap 0.4.
    assert (second.start, second.end) == (pytest.approx(3.55), pytest.approx(4.75))
    assert result.failed is None


def test_a_step_waits_for_slow_actions(tmp_path):
    result, _, _ = take(tmp_path, [{"say": "One.", "do": [click("A")]}], {1: [clip(1.0)]}, {"action_seconds": 5.0})
    assert result.timeline[0].end == pytest.approx(0.5 + 5.0 + 0.4)


def test_the_lead_comes_before_the_first_action(tmp_path):
    _, stage, clock = take(tmp_path, [{"do": [click("A"), click("B")]}])
    assert clock.sleeps[0] == 0.5
    assert stage.calls == ["start_recording", CLICK_A, CLICK_B, "stop_recording"]


def test_a_title_card_is_held(tmp_path):
    result, stage, _ = take(tmp_path, [{"chapter": "Invite"}])
    assert "chapter Invite" in stage.calls
    assert result.timeline[0].end == pytest.approx(2.0 + 0.4)


def test_time_spent_showing_the_card_counts_towards_its_hold(tmp_path):
    result, _, _ = take(tmp_path, [{"chapter": "Invite"}], stage_options={"chapter_seconds": 2.0})
    assert result.timeline[0].end == pytest.approx(2.0 + 0.4)


def test_pause_extends_the_step(tmp_path):
    result, _, _ = take(tmp_path, [{"do": [click("A")], "pause": 3}])
    assert result.timeline[0].end == pytest.approx(0.5 + 0.4 + 3.0)


def test_a_note_is_shown_for_the_step(tmp_path):
    _, stage, _ = take(tmp_path, [{"note": "Valid for seven days", "do": [click("A")]}])
    assert stage.calls == ["start_recording", "note Valid for seven days", CLICK_A, "hide_note", "stop_recording"]


def test_setup_and_cleanup_are_not_recorded(tmp_path):
    extra = {"setup": [{"wait_for": {"role": "heading", "name": "Home"}}], "cleanup": [click("Undo")]}
    result, stage, _ = take(tmp_path, [{"do": [click("A")]}], **extra)
    assert stage.calls == [SETUP, "start_recording", CLICK_A, "stop_recording", CLEANUP]
    assert result.warnings == ()


def test_a_failed_step_stops_the_take_and_cleans_up(tmp_path):
    steps = [{"do": [click("A")]}, {"do": [click("B")]}, {"do": [click("C")]}]
    result, stage, _ = take(tmp_path, steps, stage_options={"fail_on": {CLICK_B: "0 elements match"}}, cleanup=[click("Undo")])
    assert result.failed.index == 2
    assert result.failed.error == f"{CLICK_B}: 0 elements match"
    assert [s.index for s in result.timeline] == [1]
    assert stage.calls == ["start_recording", CLICK_A, CLICK_B, "stop_recording", CLEANUP]


def test_a_failed_setup_skips_recording_and_cleanup(tmp_path):
    extra = {"setup": [{"wait_for": {"role": "heading", "name": "Home"}}], "cleanup": [click("Undo")]}
    result, stage, _ = take(tmp_path, [{"do": [click("A")]}], stage_options={"fail_on": {SETUP: "0 elements match"}}, **extra)
    assert (result.failed.index, result.failed.error) == (0, f"{SETUP}: 0 elements match")
    assert stage.calls == [SETUP]
    assert result.timeline == ()


def test_a_failed_cleanup_is_a_warning(tmp_path):
    result, _, _ = take(tmp_path, [{"do": [click("A")]}], stage_options={"fail_on": {CLEANUP: "0 elements match"}}, cleanup=[click("Undo")])
    assert result.failed is None
    assert result.warnings == (f"cleanup[1]: {CLEANUP}: 0 elements match",)


def test_an_interrupt_still_stops_the_recording_and_cleans_up(tmp_path):
    clock = FakeClock()
    stage = FakeStage(clock, interrupt_on={CLICK_A})
    sb = board(tmp_path, [{"do": [click("A")]}], cleanup=[click("Undo")])
    with pytest.raises(KeyboardInterrupt):
        run_take(sb, stage, {}, clock, tmp_path / "capture.webm")
    assert stage.calls == ["start_recording", CLICK_A, "stop_recording", CLEANUP]


def test_a_probe_neither_records_nor_waits(tmp_path):
    steps = [{"say": "One.", "note": "A note", "chapter": "Start", "do": [click("A")]}, {"do": [click("B")]}]
    stage = FakeStage()
    result = run_probe(board(tmp_path, steps, cleanup=[click("Undo")]), stage)
    assert stage.calls == [CLICK_A, CLICK_B, "report", CLEANUP]
    assert [(s.index, s.ok) for s in result.steps] == [(1, True), (2, True)]
    assert result.page.title == "End"
    assert result.timeline == ()


def test_a_probe_can_stop_early(tmp_path):
    stage = FakeStage()
    result = run_probe(board(tmp_path, [{"do": [click("A")]}, {"do": [click("B")]}]), stage, until=1)
    assert stage.calls == [CLICK_A, "report"]
    assert len(result.steps) == 1


def test_a_failed_probe_reports_the_page_before_cleanup(tmp_path):
    stage = FakeStage(fail_on={CLICK_B: "2 elements match"})
    steps = [{"do": [click("A")]}, {"do": [click("B")]}, {"do": [click("C")]}]
    result = run_probe(board(tmp_path, steps, cleanup=[click("Undo")]), stage)
    assert stage.calls == [CLICK_A, CLICK_B, "report", CLEANUP]
    assert (result.failed.index, result.failed.error) == (2, f"{CLICK_B}: 2 elements match")
    assert result.page is not None


def test_a_probe_with_a_failed_setup_still_reports_the_page(tmp_path):
    stage = FakeStage(fail_on={SETUP: "0 elements match"})
    extra = {"setup": [{"wait_for": {"role": "heading", "name": "Home"}}], "cleanup": [click("Undo")]}
    result = run_probe(board(tmp_path, [{"do": [click("A")]}], **extra), stage)
    assert stage.calls == [SETUP, "report"]
    assert result.failed.index == 0 and result.page is not None


def test_a_probe_passes_the_outline_options_on(tmp_path):
    stage = FakeStage()
    within = parse_locator({"role": "dialog"}, "--within")
    run_probe(board(tmp_path, [{"do": [click("A")]}]), stage, within=within, max_chars=500)
    assert stage.report_args == (within, 500)


def test_summaries(tmp_path):
    sb = board(tmp_path, [{"chapter": "Invite", "do": [click("A"), {"press": "Enter"}]}, {"say": "Only words."}])
    assert summarize(sb.steps[0]) == f'chapter "Invite"; {CLICK_A}; press Enter'
    assert summarize(sb.steps[1]) == "narration only"


def test_cleanup_runs_even_when_the_recording_cannot_be_stopped(tmp_path):
    clock = FakeClock()
    stage = FakeStage(clock, stop_error=RuntimeError("the recorder is gone"))
    sb = board(tmp_path, [{"do": [click("A")]}], cleanup=[click("Undo")])
    with pytest.raises(RuntimeError, match="the recorder is gone"):
        run_take(sb, stage, {}, clock, tmp_path / "capture.webm")
    assert stage.calls == ["start_recording", CLICK_A, "stop_recording", CLEANUP]


def test_a_stop_request_is_raised_at_the_next_check_and_only_once():
    interrupt = Interrupt()
    interrupt.check()
    interrupt.request()
    with pytest.raises(KeyboardInterrupt):
        interrupt.check()
    interrupt.check()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_a_signal_waits_for_the_next_check(signum):
    interrupt = Interrupt()
    before = signal.getsignal(signum)
    with interrupt.listening():
        os.kill(os.getpid(), signum)
        time.sleep(0.05)  # Without the handler this line would raise, or end the test run.
        with pytest.raises(KeyboardInterrupt):
            interrupt.check()
    assert signal.getsignal(signum) is before


def test_a_signal_that_nothing_checked_is_raised_on_the_way_out():
    interrupt = Interrupt()
    with pytest.raises(KeyboardInterrupt):
        with interrupt.listening():
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.05)


def test_a_stop_request_ends_a_long_sleep():
    interrupt = Interrupt()
    threading.Timer(0.05, interrupt.request).start()
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        RealClock(interrupt).sleep(30)
    assert time.monotonic() - started < 2


def test_a_sleep_without_a_request_lasts_its_time():
    started = time.monotonic()
    RealClock(Interrupt()).sleep(0.25)
    assert 0.25 <= time.monotonic() - started < 0.6
