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
PANEL = {"role": "complementary", "name": "Panel"}
CROP = 'crop role=complementary name="Panel"'


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


def picture(tmp_path, steps, stage_options=None, **extra):
    """A take for an animated picture: nothing is spoken."""
    clock = FakeClock()
    stage = FakeStage(clock, **(stage_options or {}))
    result = run_take(board(tmp_path, steps, **extra), stage, {}, clock, tmp_path / "capture.webm", animated=True)
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


ZOOM_A = f"zoom 2 {CLICK_A}"
ZOOM_B = f"zoom 2 {CLICK_B}"
DONE = {"wait_for": {"role": "heading", "name": "Done"}}
WAIT_DONE = 'wait_for role=heading name="Done"'


def test_a_take_zooms_in_before_the_action_and_out_after_it(tmp_path):
    result, stage, clock = take(tmp_path, [{"do": [click("A")]}], stage_options={"zoom_seconds": 1.1}, zoom=2)
    assert stage.calls == ["start_recording", ZOOM_A, CLICK_A, "zoom_out", "stop_recording"]
    # The lead, the hold between the action and the way out, and the gap.
    assert clock.sleeps == [0.5, 0.9, 0.4]
    # lead 0.5 + zoom in 1.1 + hold 0.9 + zoom out 1.1 + gap 0.4
    assert result.timeline[0].end == pytest.approx(4.0)


def test_each_pointer_action_is_aimed_at_and_the_step_ends_wide(tmp_path):
    fill = {"fill": {"label": "Email", "value": "sam@example.com"}}
    described = 'fill label="Email" value="sam@example.com"'
    _, stage, _ = take(tmp_path, [{"do": [click("A"), fill, {"press": "Enter"}, DONE]}], zoom=2)
    assert stage.calls == [
        "start_recording",
        ZOOM_A, CLICK_A,
        f"zoom 2 {described}", described,
        "press Enter",
        WAIT_DONE,
        "zoom_out",
        "stop_recording",
    ]


def test_a_step_without_a_pointer_action_stays_wide(tmp_path):
    _, stage, clock = take(tmp_path, [{"do": [{"press": "Enter"}, DONE]}], zoom=2)
    assert stage.calls == ["start_recording", "press Enter", WAIT_DONE, "stop_recording"]
    assert clock.sleeps == [0.5, 0.4]


@pytest.mark.parametrize(
    "moves, described",
    [
        ({"goto": "http://demo.test/next"}, "goto http://demo.test/next"),
        ({"scroll_to": {"role": "heading", "name": "Done"}}, 'scroll_to role=heading name="Done"'),
    ],
)
def test_the_picture_goes_wide_before_the_page_moves(tmp_path, moves, described):
    _, stage, _ = take(tmp_path, [{"do": [click("A"), moves, click("B")]}], zoom=2)
    assert stage.calls == [
        "start_recording", ZOOM_A, CLICK_A, "zoom_out", described, ZOOM_B, CLICK_B, "zoom_out", "stop_recording",
    ]


def test_a_step_sets_its_own_zoom(tmp_path):
    steps = [{"do": [click("A")], "zoom": 1}, {"do": [click("B")]}, {"do": [click("C")], "zoom": 3}]
    _, stage, _ = take(tmp_path, steps, zoom=2)
    assert stage.calls == [
        "start_recording", CLICK_A, ZOOM_B, CLICK_B, "zoom_out", f"zoom 3 {CLICK_C}", CLICK_C, "zoom_out", "stop_recording",
    ]


def test_one_step_can_zoom_in_a_video_that_stays_wide(tmp_path):
    _, stage, _ = take(tmp_path, [{"do": [click("A")]}, {"do": [click("B")], "zoom": 2}])
    assert stage.calls == ["start_recording", CLICK_A, ZOOM_B, CLICK_B, "zoom_out", "stop_recording"]


def test_setup_and_cleanup_never_zoom(tmp_path):
    _, stage, _ = take(tmp_path, [{"say": "Only words."}], setup=[click("A")], cleanup=[click("Undo")], zoom=2)
    assert stage.calls == [CLICK_A, "start_recording", "stop_recording", CLEANUP]


def test_a_target_that_is_missing_fails_the_step_and_leaves_the_page_wide(tmp_path):
    options = {"fail_on": {CLICK_B: "0 elements match"}}
    result, stage, _ = take(tmp_path, [{"do": [click("A"), click("B")]}], stage_options=options, cleanup=[click("Undo")], zoom=2)
    assert result.failed.error == f"{CLICK_B}: 0 elements match"
    assert stage.calls == ["start_recording", ZOOM_A, CLICK_A, ZOOM_B, "zoom_out at once", "stop_recording", CLEANUP]


def test_an_action_that_fails_while_zoomed_leaves_the_page_wide_for_cleanup(tmp_path):
    options = {"fail_on": {WAIT_DONE: "0 elements match"}}
    result, stage, _ = take(tmp_path, [{"do": [click("A"), DONE]}], stage_options=options, cleanup=[click("Undo")], zoom=2)
    assert result.failed.index == 1
    assert stage.calls == ["start_recording", ZOOM_A, CLICK_A, WAIT_DONE, "zoom_out at once", "stop_recording", CLEANUP]


def test_an_interrupt_while_zoomed_leaves_the_page_wide_for_cleanup(tmp_path):
    clock = FakeClock()
    stage = FakeStage(clock, interrupt_on={CLICK_A})
    sb = board(tmp_path, [{"do": [click("A")]}], cleanup=[click("Undo")], zoom=2)
    with pytest.raises(KeyboardInterrupt):
        run_take(sb, stage, {}, clock, tmp_path / "capture.webm")
    assert stage.calls == ["start_recording", ZOOM_A, CLICK_A, "zoom_out at once", "stop_recording", CLEANUP]


def test_a_probe_zooms_at_once(tmp_path):
    stage = FakeStage()
    result = run_probe(board(tmp_path, [{"do": [click("A")]}], cleanup=[click("Undo")], zoom=2), stage)
    assert stage.calls == [f"{ZOOM_A} at once", CLICK_A, "zoom_out at once", "report", CLEANUP]
    assert result.failed is None


def test_a_failed_probe_describes_a_page_at_its_own_size(tmp_path):
    stage = FakeStage(fail_on={WAIT_DONE: "0 elements match"})
    result = run_probe(board(tmp_path, [{"do": [click("A"), DONE]}], zoom=2), stage)
    assert stage.calls == [f"{ZOOM_A} at once", CLICK_A, WAIT_DONE, "zoom_out at once", "report"]
    assert result.failed.index == 1


CIRCLE_A = 'circle role=button name="A"'
MARK_A = f"mark {CIRCLE_A}"
MARK_B = 'mark circle role=button name="B"'
ZOOM_ON_MARK_A = f"zoom 2 {CIRCLE_A}"
# What the fake stage spends on drawing a mark, on fading marks out and on a zoom.
SLOW = {"mark_seconds": 0.6, "clear_seconds": 0.25, "zoom_seconds": 1.1}


def circle(name):
    return {"circle": {"role": "button", "name": name}}


def test_a_mark_is_drawn_and_held_and_it_goes_as_the_click_lands(tmp_path):
    result, stage, clock = take(tmp_path, [{"do": [circle("A"), click("A")]}], stage_options=SLOW)
    assert stage.calls == ["start_recording", MARK_A, CLICK_A, "clear_marks", "stop_recording"]
    # The lead, the hold on the finished mark, and the gap.
    assert clock.sleeps == [0.5, 0.6, 0.4]
    # lead 0.5 + drawing 0.6 + hold 0.6 + fading 0.25 + gap 0.4
    assert result.timeline[0].end == pytest.approx(2.35)


def test_marks_in_a_row_are_held_once(tmp_path):
    _, stage, clock = take(tmp_path, [{"do": [circle("A"), circle("B"), click("B")]}])
    assert stage.calls == ["start_recording", MARK_A, MARK_B, CLICK_B, "clear_marks", "stop_recording"]
    assert clock.sleeps == [0.5, 0.6, 0.4]


@pytest.mark.parametrize(
    "action, described",
    [
        ({"press": "Enter"}, "press Enter"),
        # Picking an option is there to change the page, as a click is.
        ({"select": {"label": "Role", "option": "Admin"}}, 'select label="Role" option="Admin"'),
    ],
)
def test_an_action_that_may_change_the_page_takes_the_marks_away(tmp_path, action, described):
    _, stage, _ = take(tmp_path, [{"do": [circle("A"), action, click("B")]}])
    assert stage.calls == ["start_recording", MARK_A, described, "clear_marks", CLICK_B, "stop_recording"]


@pytest.mark.parametrize(
    "action, described",
    [
        ({"hover": {"role": "button", "name": "A"}}, 'hover role=button name="A"'),
        ({"fill": {"label": "Email", "value": "sam@example.com"}}, 'fill label="Email" value="sam@example.com"'),
        (DONE, WAIT_DONE),
    ],
)
def test_an_action_that_leaves_the_page_as_it_is_keeps_the_marks(tmp_path, action, described):
    _, stage, _ = take(tmp_path, [{"do": [circle("A"), action, click("B")]}])
    assert stage.calls == ["start_recording", MARK_A, described, CLICK_B, "clear_marks", "stop_recording"]


@pytest.mark.parametrize(
    "moves, described",
    [
        ({"goto": "http://demo.test/next"}, "goto http://demo.test/next"),
        ({"scroll_to": {"role": "heading", "name": "Done"}}, 'scroll_to role=heading name="Done"'),
    ],
)
def test_the_marks_go_before_the_page_moves(tmp_path, moves, described):
    _, stage, _ = take(tmp_path, [{"do": [circle("A"), moves, click("B")]}])
    assert stage.calls == ["start_recording", MARK_A, "clear_marks", described, CLICK_B, "stop_recording"]


def test_a_mark_that_ends_a_step_stays_while_the_step_is_spoken(tmp_path):
    steps = [{"say": "One.", "note": "A note", "do": [circle("A")]}]
    result, stage, clock = take(tmp_path, steps, {1: [clip(4.0)]}, SLOW)
    assert stage.calls == ["start_recording", "note A note", MARK_A, "clear_marks", "hide_note", "stop_recording"]
    # The lead, the hold on the mark, the rest of the four seconds, and what the fading leaves of the gap.
    assert clock.sleeps == [0.5, 0.6, 2.3, 0.15]
    # The narration and the gap: the marks fade within the gap.
    assert result.timeline[0].end == pytest.approx(4.4)


def test_a_mark_is_shown_for_its_hold_even_when_nothing_is_said(tmp_path):
    result, stage, clock = take(tmp_path, [{"do": [circle("A")]}], stage_options=SLOW)
    assert stage.calls == ["start_recording", MARK_A, "clear_marks", "stop_recording"]
    assert clock.sleeps == [0.5, 0.6, 0.15]


def test_the_picture_moves_in_for_a_mark_and_stays_in_while_it_is_shown(tmp_path):
    result, stage, clock = take(tmp_path, [{"say": "One.", "do": [circle("A")]}], {1: [clip(4.0)]}, SLOW, zoom=2)
    # The marks are placed for the enlarged picture, so they go before it widens.
    assert stage.calls == ["start_recording", ZOOM_ON_MARK_A, MARK_A, "clear_marks", "zoom_out", "stop_recording"]
    # No hold of 0.9 s before the way out: the mark holds the picture until the narration ends.
    assert clock.sleeps == [0.5, 0.6, 1.2]
    # The fading and the way out take longer than the gap, so the step ends when they do.
    assert result.timeline[0].end == pytest.approx(4.0 + 0.25 + 1.1)


def test_a_click_after_a_mark_ends_the_step_as_any_zoomed_click_does(tmp_path):
    _, stage, clock = take(tmp_path, [{"do": [circle("A"), click("A")]}], zoom=2)
    assert stage.calls == [
        "start_recording", ZOOM_ON_MARK_A, MARK_A, ZOOM_A, CLICK_A, "clear_marks", "zoom_out", "stop_recording",
    ]
    # The lead, the hold on the mark, the hold before the way out, and the gap.
    assert clock.sleeps == [0.5, 0.6, 0.9, 0.4]


def test_marks_and_the_zoom_both_go_before_the_page_moves(tmp_path):
    _, stage, _ = take(tmp_path, [{"do": [circle("A"), {"goto": "http://demo.test/next"}]}], zoom=2)
    assert stage.calls == [
        "start_recording", ZOOM_ON_MARK_A, MARK_A, "clear_marks", "zoom_out", "goto http://demo.test/next", "stop_recording",
    ]


def test_a_step_that_fails_leaves_no_marks_for_cleanup(tmp_path):
    options = {"fail_on": {CLICK_B: "0 elements match"}}
    result, stage, _ = take(tmp_path, [{"do": [circle("A"), click("B")]}], stage_options=options, cleanup=[click("Undo")])
    assert result.failed.error == f"{CLICK_B}: 0 elements match"
    assert stage.calls == ["start_recording", MARK_A, CLICK_B, "clear_marks at once", "stop_recording", CLEANUP]


def test_a_mark_whose_element_is_missing_fails_the_step(tmp_path):
    options = {"fail_on": {CIRCLE_A: "0 elements match"}}
    result, stage, _ = take(tmp_path, [{"do": [circle("A"), click("B")]}], stage_options=options, cleanup=[click("Undo")])
    assert (result.failed.index, result.failed.error) == (1, f"{CIRCLE_A}: 0 elements match")
    assert CLICK_B not in stage.calls
    assert stage.calls[-2:] == ["stop_recording", CLEANUP]


def test_an_interrupt_leaves_no_marks_for_cleanup(tmp_path):
    clock = FakeClock()
    stage = FakeStage(clock, interrupt_on={CLICK_A})
    sb = board(tmp_path, [{"do": [circle("A"), click("A")]}], cleanup=[click("Undo")], zoom=2)
    with pytest.raises(KeyboardInterrupt):
        run_take(sb, stage, {}, clock, tmp_path / "capture.webm")
    assert stage.calls == [
        "start_recording", ZOOM_ON_MARK_A, MARK_A, ZOOM_A, CLICK_A,
        "clear_marks at once", "zoom_out at once", "stop_recording", CLEANUP,
    ]


def test_an_interrupt_in_the_middle_of_a_mark_still_clears_it(tmp_path):
    clock = FakeClock()
    stage = FakeStage(clock, interrupt_on={CIRCLE_A})
    with pytest.raises(KeyboardInterrupt):
        run_take(board(tmp_path, [{"do": [circle("A")]}]), stage, {}, clock, tmp_path / "capture.webm")
    assert stage.calls == ["start_recording", MARK_A, "clear_marks at once", "stop_recording"]


def test_a_probe_finds_the_element_of_a_mark_and_draws_nothing(tmp_path):
    stage = FakeStage()
    result = run_probe(board(tmp_path, [{"do": [circle("A"), click("A")]}]), stage)
    assert stage.calls == [f"{MARK_A} unseen", CLICK_A, "report"]
    assert result.steps[0].summary == f"{CIRCLE_A}; {CLICK_A}"


def test_a_probe_aims_the_zoom_at_a_mark_as_the_take_will(tmp_path):
    stage = FakeStage()
    run_probe(board(tmp_path, [{"do": [circle("A")]}], zoom=2), stage)
    assert stage.calls == [f"{ZOOM_ON_MARK_A} at once", f"{MARK_A} unseen", "zoom_out at once", "report"]


def test_a_probe_names_a_mark_whose_element_is_missing(tmp_path):
    stage = FakeStage(fail_on={CIRCLE_A: "2 elements match"})
    result = run_probe(board(tmp_path, [{"do": [circle("A"), click("A")]}]), stage)
    assert (result.failed.index, result.failed.error) == (1, f"{CIRCLE_A}: 2 elements match")


def test_an_animated_take_shows_no_title_card(tmp_path):
    result, stage, _ = picture(tmp_path, [{"chapter": "Invite", "say": "Words.", "do": [click("A")]}])
    assert stage.calls == ["start_recording", CLICK_A, "stop_recording"]
    # Lead 0.5 + gap 0.4. The two seconds of the card are not waited for either.
    assert result.timeline[0].end == pytest.approx(0.9)


def test_an_animated_take_is_cut_to_the_crop_as_setup_leaves_the_page(tmp_path):
    extra = {"setup": [{"wait_for": {"role": "heading", "name": "Home"}}], "crop": PANEL}
    result, stage, _ = picture(tmp_path, [{"do": [click("A")]}], **extra)
    assert stage.calls == [SETUP, CROP, "start_recording", CLICK_A, "stop_recording"]
    assert result.crop == FakeStage.CROP_BOX


def test_an_animated_take_without_a_crop_shows_the_whole_window(tmp_path):
    result, stage, _ = picture(tmp_path, [{"do": [click("A")]}])
    assert stage.calls == ["start_recording", CLICK_A, "stop_recording"]
    assert result.crop is None


def test_a_narrated_take_films_the_whole_window_whatever_crop_says(tmp_path):
    result, stage, _ = take(tmp_path, [{"do": [click("A")]}], crop=PANEL)
    assert stage.calls == ["start_recording", CLICK_A, "stop_recording"]
    assert result.crop is None


def test_a_crop_that_is_not_found_fails_before_the_recording_and_still_cleans_up(tmp_path):
    options = {"fail_on": {CROP: "0 elements match"}}
    result, stage, _ = picture(tmp_path, [{"do": [click("A")]}], options, crop=PANEL, cleanup=[click("Undo")])
    # Setup completed, so whatever it changed is undone.
    assert stage.calls == [CROP, CLEANUP]
    assert (result.failed.index, result.failed.error) == (0, f"{CROP}: 0 elements match")
    assert result.timeline == ()


def test_a_probe_measures_the_crop_before_the_steps(tmp_path):
    stage = FakeStage()
    result = run_probe(board(tmp_path, [{"do": [click("A")]}], crop=PANEL), stage)
    assert stage.calls == [CROP, CLICK_A, "report"]
    assert result.crop == FakeStage.CROP_BOX


def test_a_probe_with_a_crop_that_is_not_found_runs_no_step_and_reports_the_page(tmp_path):
    stage = FakeStage(fail_on={CROP: "2 elements match"})
    result = run_probe(board(tmp_path, [{"do": [click("A")]}], crop=PANEL, cleanup=[click("Undo")]), stage)
    assert stage.calls == [CROP, "report", CLEANUP]
    assert (result.failed.index, result.failed.error) == (0, f"{CROP}: 2 elements match")
    assert result.crop is None
