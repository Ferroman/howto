"""DesktopStage against a scripted helper: the requests it sends for each action, and what it makes of the replies."""
from pathlib import Path

import pytest

from fakes import FakeClock, ScriptedLink
from howto.desktop import takelog
from howto.desktop.takelog import Move
from howto.desktop.link import HelperError
from howto.desktop.stage import DesktopStage, PRESS, ZOOM, scale_of, wire
from howto import marks, notes
from howto.zoom import Box
from howto.errors import RunError
from howto.runner import Interrupt, StepFailed
from howto.storyboard import Action, Pace, parse, parse_locator

ADD = {"role": "button", "name": "Add"}
FIND_ADD = ("find", {"locator": {"role": "button", "name": "Add"}, "timeout": 10})


def board(steps=None, **extra):
    data = {
        "title": "Demo",
        "app": {"image": "howto-fixture", "run": "fixture --demo"},
        "steps": steps or [{"say": "Hi."}],
        **extra,
    }
    return parse(data, Path("demo.yaml"))


def action(written):
    return board([{"do": [written]}]).steps[0].do[0]


def found(x=100, y=40, width=80, height=30, window="Fixture"):
    return {"count": 1, "box": [x, y, width, height], "layer": "tree", "window": window}


def stage(*script, **options):
    link = ScriptedLink(*script)
    return DesktopStage(link, board(), timeout=10, first="Fixture", **options), link


def failure(desk, written):
    with pytest.raises(StepFailed) as caught:
        desk.perform(action(written), Pace())
    return str(caught.value)


def test_a_click_finds_the_element_points_at_its_middle_and_presses():
    desk, link = stage(("find", found()), ("pointer", {}), ("click", {}))
    desk.perform(action({"click": ADD}), Pace())
    assert link.asked == [
        FIND_ADD,
        ("pointer", {"x": 140.0, "y": 55.0, "seconds": 0}),
        ("click", {"hold": 0, "window": "Fixture"}),
    ]


def test_finding_gets_the_time_an_element_has_and_a_little_more():
    desk, link = stage(("find", found()))
    desk.perform(action({"wait_for": ADD}), Pace())
    assert link.limits == [25.0]


def test_a_hover_stops_at_the_pointer():
    desk, link = stage(("find", found()), ("pointer", {}))
    desk.perform(action({"hover": ADD}), Pace())
    assert [name for name, _ in link.asked] == ["find", "pointer"]


def test_a_fill_clicks_selects_what_is_there_and_types():
    desk, link = stage(("find", found()), ("pointer", {}), ("click", {}), ("key", {}), ("type", {}))
    desk.perform(action({"fill": {"label": "Name", "value": "sam"}}), Pace())
    assert link.asked[0] == ("find", {"locator": {"label": "Name"}, "timeout": 10})
    assert link.asked[3:] == [("key", {"keys": "Control+A"}), ("type", {"text": "sam", "rate": 0})]


def test_a_select_clicks_the_control_and_then_the_item_of_the_list():
    item = found(x=300, y=200, window="")
    desk, link = stage(("find", found()), ("pointer", {}), ("click", {}), ("find", item), ("pointer", {}), ("click", {}))
    desk.perform(action({"select": {"label": "Role", "option": "Admin"}}), Pace())
    assert link.asked[3] == ("find", {"locator": {"option": "Admin"}, "timeout": 10})
    assert link.asked[4:] == [("pointer", {"x": 340.0, "y": 215.0, "seconds": 0}), ("click", {"hold": 0, "window": ""})]


def test_a_select_of_what_the_list_lacks_says_so():
    none = {"count": 0, "tried": ["tree"], "nearest": ["Admins"]}
    desk, _ = stage(("find", found()), ("pointer", {}), ("click", {}), ("find", none))
    assert failure(desk, {"select": {"label": "Role", "option": "Admin"}}) == (
        'select label="Role" option="Admin": the list that opened has no item "Admin". The nearest names: "Admins"'
    )


def test_a_press_and_a_type_go_to_the_keyboard():
    desk, link = stage(("key", {}), ("type", {}))
    desk.perform(action({"press": "Control+S"}), Pace())
    desk.perform(action({"type": "héllo"}), Pace())
    assert link.asked == [("key", {"keys": "Control+S"}), ("type", {"text": "héllo", "rate": 0})]


def test_typing_gets_time_for_the_whole_text():
    """xdotool types the word at once, so the request must allow the whole typing, not the time for one key."""
    desk, link = stage(("type", {}))
    desk.perform(action({"type": "a" * 200}), Pace())
    assert link.limits[-1] > 15.0


def test_a_place_is_pointed_at_without_asking_where_it_is():
    desk, link = stage(("pointer", {}), ("click", {}), ("pointer", {}))
    desk.perform(action({"click": {"at": "960x540"}}), Pace())
    desk.perform(action({"hover": {"at": "900x500", "size": "120x40"}}), Pace())
    assert link.asked == [
        ("pointer", {"x": 960.0, "y": 540.0, "seconds": 0}),
        ("click", {"hold": 0, "window": ""}),
        ("pointer", {"x": 960.0, "y": 520.0, "seconds": 0}),
    ]


def test_what_is_not_found_says_where_it_was_looked_for_and_offers_the_nearest_names():
    desk, _ = stage(("find", {"count": 0, "tried": ["tree"], "nearest": ["Add", "Address"]}))
    assert failure(desk, {"click": {"role": "button", "name": "Addd"}}) == (
        'click role=button name="Addd": not in the tree. The nearest names: "Add", "Address"'
    )


def test_what_is_not_found_and_has_nothing_near_it_says_only_that():
    desk, _ = stage(("find", {"count": 0, "tried": ["tree"], "nearest": []}))
    assert failure(desk, {"click": ADD}) == 'click role=button name="Add": not in the tree'


def test_several_matches_fail_with_their_count():
    desk, _ = stage(("find", {"count": 2}))
    assert failure(desk, {"click": ADD}) == 'click role=button name="Add": 2 elements match'


def test_a_covering_window_fails_the_step_and_is_named():
    covered = HelperError("covered", 'another window covers it: "Open"')
    desk, _ = stage(("find", found()), ("pointer", {}), ("click", covered))
    assert failure(desk, {"click": ADD}) == 'click role=button name="Add": another window covers it: "Open"'


def test_an_app_that_ended_fails_the_step():
    desk, _ = stage(("find", HelperError("app_exited", "the app ended with exit code 1:\nSegmentation fault")))
    assert failure(desk, {"click": ADD}) == (
        'click role=button name="Add": the app ended with exit code 1:\nSegmentation fault'
    )


def test_a_wrong_key_fails_the_step():
    desk, _ = stage(("key", HelperError("bad_key", "`Entre` is not a key: use a name such as Enter")))
    assert failure(desk, {"press": "Entre"}) == "press Entre: `Entre` is not a key: use a name such as Enter"


def test_what_the_helper_itself_gets_wrong_ends_the_command():
    desk, _ = stage(("find", HelperError("internal", "KeyError: 'box'")))
    with pytest.raises(RunError, match="the desktop failed: KeyError: 'box'"):
        desk.perform(action({"click": ADD}), Pace())


def test_a_command_gets_three_times_the_time_of_an_action():
    desk, link = stage(("run", {"code": 0, "output": ""}))
    desk.perform(action({"run": "cp /files/a.svg /home/howto/"}), Pace())
    assert link.asked == [("run", {"command": "cp /files/a.svg /home/howto/", "timeout": 30})]
    assert link.limits == [45.0]


def test_a_command_that_fails_fails_the_step_with_its_code_and_its_words():
    desk, _ = stage(("run", {"code": 3, "output": "gone wrong"}))
    assert failure(desk, {"run": "make-notes"}) == "run make-notes: it ended with exit code 3: gone wrong"


def test_a_command_that_does_not_end_fails_the_step():
    desk, _ = stage(("run", {"timed_out": True}))
    assert failure(desk, {"run": "sleep 99"}) == "run sleep 99: it did not end in 30 seconds"


def test_scroll_to_gives_the_locator_to_the_helper():
    desk, link = stage(("scroll_to", {"count": 1}))
    desk.perform(action({"scroll_to": ADD}), Pace())
    assert link.asked == [("scroll_to", {"locator": {"role": "button", "name": "Add"}, "timeout": 10})]


def test_scroll_to_fails_as_a_find_does():
    desk, _ = stage(("scroll_to", {"count": 0}))
    assert failure(desk, {"scroll_to": ADD}) == 'scroll_to role=button name="Add": not in the tree'
    desk, _ = stage(("scroll_to", {"count": 3}))
    assert failure(desk, {"scroll_to": ADD}) == 'scroll_to role=button name="Add": 3 elements match'


def test_an_app_that_cannot_scroll_fails_the_step_and_offers_a_key():
    desk, _ = stage(("scroll_to", HelperError("cannot_scroll", "the app cannot bring it into view: use `press: PageDown`")))
    assert failure(desk, {"scroll_to": ADD}).endswith("the app cannot bring it into view: use `press: PageDown`")


def test_a_locator_goes_to_the_helper_with_what_narrows_it():
    locator = parse_locator({"role": "button", "name": "Remove", "exact": True, "nth": 1, "within": {"text": "Layer 2"}}, "x")
    assert wire(locator) == {"role": "button", "name": "Remove", "exact": True, "nth": 1, "within": {"text": "Layer 2"}}
    assert wire(parse_locator({"label": "Name"}, "x")) == {"label": "Name"}


def outlined(**more):
    return {"outline": '- frame "Fixture" [active]:\n  - button "Add"', "title": "Fixture",
            "windows": ["Fixture"], "first": "Fixture", "ended": None, **more}


def test_the_report_names_the_app_and_the_window_that_has_the_keyboard():
    desk, link = stage(("outline", outlined()))
    page = desk.report(None, 20_000)
    assert (page.url, page.title) == ("app fixture --demo", "Fixture")
    assert page.outline == '- frame "Fixture" [active]:\n  - button "Add"'
    assert (page.omitted, page.notices) == (0, ())
    assert link.asked == [("outline", {"within": None})]


def test_the_report_can_be_limited_to_one_element_and_cut():
    desk, link = stage(("outline", outlined()))
    page = desk.report(parse_locator({"role": "dialog"}, "x"), 30)
    assert link.asked == [("outline", {"within": {"role": "dialog"}})]
    assert page.outline == '- frame "Fixture" [active]:' and page.omitted == 17


def test_the_report_notes_a_window_that_no_step_touched():
    desk, _ = stage(("find", found(window="Fixture")), ("outline", outlined(windows=["Fixture", "Print"])))
    desk.perform(action({"wait_for": ADD}), Pace())
    assert desk.report(None, 20_000).notices == ('a window opened that no step touched: "Print"',)


def test_a_window_that_a_step_found_something_in_is_not_noted():
    desk, _ = stage(("find", found(window="Print")), ("outline", outlined(windows=["Fixture", "Print"])))
    desk.perform(action({"wait_for": ADD}), Pace())
    assert desk.report(None, 20_000).notices == ()


def test_the_first_window_is_not_noted_when_the_app_gives_it_another_title():
    desk, _ = stage(("outline", outlined(windows=["notes.txt - Fixture"], first="notes.txt - Fixture")))
    assert desk.report(None, 20_000).notices == ()


def test_the_report_notes_an_app_that_ended():
    desk, _ = stage(("outline", outlined(outline="(nothing is showing)", title="", windows=[], ended=1)))
    page = desk.report(None, 20_000)
    assert page.notices == ("the app ended with exit code 1",)
    assert page.outline == "(nothing is showing)"


def test_a_request_to_stop_is_acted_on_before_a_request_and_not_during_it():
    interrupt = Interrupt()
    desk, link = stage(("find", found()), interrupt=interrupt)
    interrupt.request()
    with pytest.raises(KeyboardInterrupt):
        desk.perform(action({"click": ADD}), Pace())
    assert link.asked == []


def test_a_request_to_stop_that_comes_during_a_request_is_acted_on_after_it():
    interrupt = Interrupt()

    def stopped_meanwhile(fields):
        interrupt.request()
        return found()

    desk, link = stage(("find", stopped_meanwhile), ("pointer", {}), interrupt=interrupt)
    with pytest.raises(KeyboardInterrupt):
        desk.perform(action({"click": ADD}), Pace())
    assert [name for name, _ in link.asked] == ["find"]


def test_a_zoom_of_a_probe_only_finds_its_target():
    desk, link = stage(("find", found()), ("find", {"count": 0, "tried": ["tree"], "nearest": []}))
    desk.zoom_to(action({"click": ADD}), 2.0, False)
    desk.zoom_out(False)
    assert link.asked == [FIND_ADD]
    with pytest.raises(StepFailed, match='click role=button name="Add": not in the tree'):
        desk.zoom_to(action({"click": ADD}), 2.0, False)


FIND_ADD_FOR_A_MARK = ("find", {"locator": {"role": "button", "name": "Add"}, "timeout": 10, "tight": True})


def test_a_mark_of_a_probe_only_finds_its_element():
    desk, link = stage(("find", found()))
    desk.mark(action({"circle": ADD}), False)
    desk.clear_marks(False)
    # `tight`: a mark goes around the words of a label, not around the room that the app gave it.
    assert link.asked == [FIND_ADD_FOR_A_MARK]


def recording(tmp_path, *script, first_frame=99.2, **options):
    """A stage that has started recording. The clock says 100 when the take begins, and waiting moves it."""
    clock = FakeClock()
    options.setdefault("sleep", clock.sleep)
    desk, link = stage(("record_start", {"first_frame": first_frame}), *script, now=clock.now, **options)
    desk.start_recording(tmp_path / "capture.mkv")
    return desk, link, clock


def stopped(desk, tmp_path):
    desk.stop_recording()
    return takelog.read(tmp_path / "take.json")


def test_the_head_is_the_part_of_the_recording_before_the_take(tmp_path):
    desk, link, _ = recording(tmp_path, ("record_stop", {"path": "/tmp/howto/take.mkv"}))
    log = stopped(desk, tmp_path)
    assert log.head == pytest.approx(0.8)
    assert log.viewport == (1920, 1080) and log.shown == ()
    assert link.fetched == [("/tmp/howto/take.mkv", tmp_path / "capture.mkv")]


def test_a_first_frame_after_the_start_of_the_take_gives_no_head(tmp_path):
    desk, _, _ = recording(tmp_path, ("record_stop", {"path": "/tmp/howto/take.mkv"}), first_frame=100.4)
    assert stopped(desk, tmp_path).head == 0.0


def test_in_a_take_the_pointer_travels_and_the_button_stays_down(tmp_path):
    desk, link, clock = recording(tmp_path, ("find", found(x=100, y=40)), ("pointer", {}), ("click", {}))
    clock.t += 2.0
    desk.perform(action({"click": ADD}), Pace())
    pointer, click = link.asked[2], link.asked[3]
    # From the corner where the helper parks it, 1896 x 1056, to 140 x 55: a long way, so the longest time.
    assert pointer == ("pointer", {"x": 140.0, "y": 55.0, "seconds": 0.9})
    assert click == ("click", {"hold": PRESS, "window": "Fixture"})


def test_a_short_way_still_takes_a_quarter_of_a_second(tmp_path):
    script = [("find", found(x=100, y=40)), ("pointer", {}), ("find", found(x=130, y=40)), ("pointer", {})]
    desk, link, _ = recording(tmp_path, *script)
    desk.perform(action({"hover": ADD}), Pace())
    desk.perform(action({"hover": ADD}), Pace())
    assert link.asked[-1] == ("pointer", {"x": 170.0, "y": 55.0, "seconds": 0.25})


def test_a_click_leaves_a_ring_in_the_log_at_the_time_of_the_press(tmp_path):
    script = [("find", found(x=100, y=40)), ("pointer", {}), ("click", {}), ("record_stop", {"path": "/x.mkv"})]
    desk, _, clock = recording(tmp_path, *script)
    clock.t += 2.0
    desk.perform(action({"click": ADD}), Pace())
    (ring,) = stopped(desk, tmp_path).shown
    assert (ring.kind, ring.start, ring.end, ring.grow) == ("click", 2.0, 2.45, 0.0)
    assert "left:140.0px;top:55.0px" in ring.html


def test_in_a_take_text_is_typed_at_the_pace_of_the_storyboard(tmp_path):
    desk, link, _ = recording(tmp_path, ("type", {}))
    desk.perform(action({"type": "hello"}), Pace(typing=20.0))
    assert link.asked[-1] == ("type", {"text": "hello", "rate": 20.0})


def test_a_probe_keeps_jumping_and_typing_at_once():
    desk, link = stage(("find", found()), ("pointer", {}), ("click", {}), ("type", {}))
    desk.perform(action({"click": ADD}), Pace())
    desk.perform(action({"type": "hello"}), Pace())
    assert link.asked[1][1]["seconds"] == 0 and link.asked[2][1]["hold"] == 0 and link.asked[3][1]["rate"] == 0


def test_a_note_is_in_the_log_from_when_it_is_shown_to_when_it_is_hidden(tmp_path):
    desk, _, clock = recording(tmp_path, ("record_stop", {"path": "/x.mkv"}))
    clock.t += 1.0
    desk.show_note("Use a <work> address.")
    clock.t += 3.5
    desk.hide_note()
    (note,) = stopped(desk, tmp_path).shown
    assert (note.kind, note.start, note.end, note.grow, note.fade) == ("note", 1.0, 4.5, 0.0, 0.0)
    assert "Use a &lt;work&gt; address." in note.html


def test_a_note_that_is_still_shown_ends_with_the_take(tmp_path):
    desk, _, clock = recording(tmp_path, ("record_stop", {"path": "/x.mkv"}))
    desk.show_note("Still here")
    clock.t += 2.0
    (note,) = stopped(desk, tmp_path).shown
    assert (note.start, note.end) == (0.0, 2.0)


def test_a_title_card_appears_at_once_and_fades_out(tmp_path):
    desk, _, clock = recording(tmp_path, ("record_stop", {"path": "/x.mkv"}))
    desk.show_chapter("Add a name", 2.0)
    clock.t += 3.0
    (card,) = stopped(desk, tmp_path).shown
    assert (card.kind, card.start, card.end, card.grow, card.fade) == ("card", 0.0, 2.3, 0.0, 0.3)
    assert "Add a name" in card.html


def test_a_take_that_was_stopped_ends_its_recording_and_fetches_nothing(tmp_path):
    interrupt = Interrupt()
    desk, link, _ = recording(tmp_path, ("record_stop", {"path": "/x.mkv"}), interrupt=interrupt)
    interrupt.request()
    with pytest.raises(KeyboardInterrupt):
        desk.perform(action({"press": "Enter"}), Pace())
    desk.stop_recording()
    assert link.asked[-1] == ("record_stop", {})
    assert link.fetched == [] and not (tmp_path / "take.json").exists()


def test_stopping_twice_or_without_a_recording_does_nothing(tmp_path):
    desk, link = stage()
    desk.stop_recording()
    assert link.asked == []


def test_a_recording_that_cannot_be_ended_ends_the_command(tmp_path):
    desk, _, _ = recording(tmp_path, ("record_stop", HelperError("internal", "RuntimeError: ffmpeg failed while recording")))
    with pytest.raises(RunError, match="the desktop failed: RuntimeError: ffmpeg failed while recording"):
        desk.stop_recording()


def read(*lines):
    return {"lines": [{"text": text, "box": list(box)} for text, box in lines]}


def reporting(tmp_path, *script):
    """A stage that saves the screenshot of its report."""
    shots = tmp_path / "cache" / "probe" / "demo.png"
    return *stage(*script, shots=shots), shots


def test_the_report_has_the_words_that_the_outline_lacks_as_locators_to_copy(tmp_path):
    lines = read(("Layer 1", (1620.4, 200.2, 61.5, 23.6)), ("Painted words", (40, 180, 250.0, 36.0)))
    desk, link, shots = reporting(tmp_path, ("outline", outlined()), ("screenshot", {"path": "/tmp/howto/screen.png"}), ("words", lines))
    page = desk.report(None, 20_000)
    assert page.words == ('"Layer 1" {at: 1620x200, size: 62x24}', '"Painted words" {at: 40x180, size: 250x36}')
    assert page.screenshot == str(shots) and shots.read_bytes() == b"fetched"
    assert link.asked[1:] == [
        ("screenshot", {}),
        ("words", {"lacking": True, "within": None, "shot": "/tmp/howto/screen.png"}),
    ]
    assert link.fetched == [("/tmp/howto/screen.png", shots)]


def test_the_words_of_a_report_are_limited_as_its_outline_is(tmp_path):
    script = [("outline", outlined()), ("screenshot", {"path": "/s.png"}), ("words", read())]
    desk, link, _ = reporting(tmp_path, *script)
    desk.report(parse_locator({"role": "dialog"}, "x"), 20_000)
    assert link.asked[2][1]["within"] == {"role": "dialog"}


def test_the_words_get_what_the_outline_leaves_of_the_limit(tmp_path):
    lines = read(("One", (0, 0, 10, 10)), ("Two", (0, 20, 10, 10)), ("Three", (0, 40, 10, 10)))
    script = [("outline", outlined(outline="- frame")), ("screenshot", {"path": "/s.png"}), ("words", lines)]
    desk, _, _ = reporting(tmp_path, *script)
    # The outline has 7 characters, so 63 are left. A line of words costs about 30 with its line break: two fit.
    page = desk.report(None, 70)
    assert page.words == ('"One" {at: 0x0, size: 10x10}', '"Two" {at: 0x20, size: 10x10}')
    assert page.omitted == len('"Three" {at: 0x40, size: 10x10}')


def test_an_outline_that_was_cut_leaves_no_room_for_words(tmp_path):
    lines = read(("One", (0, 0, 10, 10)))
    desk, _, _ = reporting(tmp_path, ("outline", outlined()), ("screenshot", {"path": "/s.png"}), ("words", lines))
    page = desk.report(None, 30)
    assert page.words == () and page.omitted == 17 + len('"One" {at: 0x0, size: 10x10}')
    assert page.screenshot


def test_a_report_without_a_place_for_its_screenshot_asks_for_none(tmp_path):
    desk, link = stage(("outline", outlined()))
    page = desk.report(None, 20_000)
    assert (page.words, page.screenshot) == ((), "")
    assert [name for name, _ in link.asked] == ["outline"]


def test_words_on_the_screen_are_pressed_without_asking_what_covers_them():
    on_screen = {"count": 1, "box": [40, 180, 250, 36], "layer": "screen", "window": ""}
    desk, link = stage(("find", on_screen), ("pointer", {}), ("click", {}))
    desk.perform(action({"click": {"text": "Painted words"}}), Pace())
    assert link.asked[1:] == [("pointer", {"x": 165.0, "y": 198.0, "seconds": 0.0}), ("click", {"hold": 0, "window": ""})]


def test_words_that_are_nowhere_say_that_both_were_looked_at():
    desk, _ = stage(("find", {"count": 0, "tried": ["tree", "screen"], "nearest": ["Export"]}))
    assert failure(desk, {"click": {"text": "Exprot"}}) == (
        'click text="Exprot": not in the tree, and no such words on the screen. The nearest words: "Export"'
    )


STOP = ("record_stop", {"path": "/x.mkv"})


def test_a_mark_is_in_the_log_from_when_it_is_drawn_until_it_has_faded(tmp_path):
    desk, link, clock = recording(tmp_path, ("find", found(x=100, y=40)), STOP)
    clock.t += 1.0
    desk.mark(action({"box": ADD}), True)
    # The take still gives the mark its time on screen, even though it appears at once.
    assert clock.t == pytest.approx(101.6)
    clock.t += 2.0
    desk.clear_marks(True)
    assert clock.t == pytest.approx(103.85)
    (mark,) = stopped(desk, tmp_path).shown
    assert (mark.kind, mark.start, mark.grow, mark.fade) == ("mark", 1.0, 0.0, 0.25)
    assert mark.end == pytest.approx(3.85)
    assert mark.html == marks.layer(marks.box(Box(100, 40, 80, 30), (1920, 1080)), (1920, 1080))
    assert link.asked[1] == FIND_ADD_FOR_A_MARK


@pytest.mark.parametrize("kind", ["circle", "underline", "spotlight"])
def test_each_shape_is_the_one_that_a_web_page_gets(tmp_path, kind):
    desk, _, _ = recording(tmp_path, ("find", found(x=100, y=40)), STOP)
    desk.mark(action({kind: ADD}), True)
    (mark,) = stopped(desk, tmp_path).shown
    assert mark.html == marks.layer(marks.SHAPES[kind](Box(100, 40, 80, 30), (1920, 1080)), (1920, 1080))


def test_marks_that_go_at_once_do_not_fade(tmp_path):
    desk, _, clock = recording(tmp_path, ("find", found()), STOP)
    desk.mark(action({"underline": ADD}), True)
    desk.clear_marks(False)
    assert clock.t == pytest.approx(100.6)
    (mark,) = stopped(desk, tmp_path).shown
    assert (mark.end, mark.fade) == (pytest.approx(0.6), 0.0)


def test_a_mark_that_is_still_shown_ends_with_the_take(tmp_path):
    desk, _, clock = recording(tmp_path, ("find", found()), STOP)
    desk.mark(action({"spotlight": ADD}), True)
    clock.t += 1.0
    (mark,) = stopped(desk, tmp_path).shown
    assert (mark.start, mark.end, mark.fade) == (0.0, pytest.approx(1.6), 0.0)


def test_two_marks_go_together(tmp_path):
    desk, _, clock = recording(tmp_path, ("find", found()), ("find", found(x=300)), STOP)
    desk.mark(action({"box": ADD}), True)
    desk.mark(action({"underline": ADD}), True)
    desk.clear_marks(True)
    first, second = stopped(desk, tmp_path).shown
    assert (first.start, second.start) == (0.0, pytest.approx(0.6))
    assert first.end == second.end == pytest.approx(1.45)


def test_clearing_without_a_mark_does_nothing(tmp_path):
    desk, link, clock = recording(tmp_path)
    desk.clear_marks(True)
    assert clock.t == 100.0 and [name for name, _ in link.asked] == ["record_start"]


def test_a_request_to_stop_ends_the_wait_for_a_mark_at_once(tmp_path):
    interrupt, waited = Interrupt(), []

    def sleep(seconds):
        waited.append(seconds)
        interrupt.request()

    desk, _, _ = recording(tmp_path, ("find", found()), interrupt=interrupt, sleep=sleep)
    with pytest.raises(KeyboardInterrupt):
        desk.mark(action({"circle": ADD}), True)
    assert len(waited) == 1


def quiet_around(candidate):
    """A reply to `busy`: nothing around the points of one way to draw an arrow, and something everywhere else."""
    quiet = {(round(x, 3), round(y, 3)) for x, y in candidate.points}

    def reply(fields):
        return {"shares": [0.0 if (round(x + 6, 3), round(y + 6, 3)) in quiet else 0.5 for x, y, _, _ in fields["areas"]]}

    return reply


def test_an_arrow_comes_from_the_side_where_the_screen_has_the_least(tmp_path):
    candidates = marks.arrows(Box(900, 500, 120, 40), (1920, 1080), "Here")
    script = [("find", found(x=900, y=500, width=120, height=40)), ("busy", quiet_around(candidates[2])), STOP]
    desk, link, _ = recording(tmp_path, *script)
    desk.mark(action({"arrow": {**ADD, "note": "Here"}}), True)
    (mark,) = stopped(desk, tmp_path).shown
    assert mark.html == marks.layer(marks.arrow(candidates[2]), (1920, 1080))
    areas = link.asked[2][1]["areas"]
    # Every point of the eight ways is asked about, with a small area around it.
    assert len(areas) == sum(len(candidate.points) for candidate in candidates)
    assert all(area[2:] == [12.0, 12.0] for area in areas)


def test_a_point_outside_the_picture_counts_without_a_question(tmp_path):
    # A target in the corner. Nothing is on the screen, so only the points outside the picture count.
    candidates = marks.arrows(Box(4, 4, 60, 30), (1920, 1080))
    script = [("find", found(x=4, y=4, width=60, height=30)), ("busy", lambda fields: {"shares": [0.0] * len(fields["areas"])}), STOP]
    desk, link, _ = recording(tmp_path, *script)
    desk.mark(action({"arrow": ADD}), True)
    (mark,) = stopped(desk, tmp_path).shown
    # The first way points to the middle of the picture and lies wholly inside. Of the ways that are as empty, it is taken.
    assert mark.html == marks.layer(marks.arrow(candidates[0]), (1920, 1080))
    assert len(link.asked[2][1]["areas"]) < sum(len(candidate.points) for candidate in candidates)


def test_a_mark_whose_element_is_not_found_fails_as_an_action_does(tmp_path):
    desk, _, _ = recording(tmp_path, ("find", {"count": 0, "tried": ["tree"], "nearest": ["Add"]}))
    with pytest.raises(StepFailed, match='circle role=button name="Addd": not in the tree. The nearest names: "Add"'):
        desk.mark(action({"circle": {"role": "button", "name": "Addd"}}), True)


PANEL = found(x=101, y=51, width=338, height=248)
# The element, with 12 pixels around it, at even numbers.
CUT = Box(88, 38, 364, 274)


def crop(written=ADD):
    return Action(kind="crop", locator=parse_locator(written, "crop"))


def no_notes(texts, width):
    raise AssertionError("there is nothing to measure")


def test_a_crop_is_the_element_with_a_margin_at_even_numbers():
    desk, link = stage(("find", PANEL), heights=no_notes)
    assert desk.crop_to(crop(), ()) == CUT
    assert link.asked == [FIND_ADD]


def test_a_crop_takes_an_area_that_the_storyboard_gives():
    desk, link = stage(heights=no_notes)
    assert desk.crop_to(crop({"at": "100x60", "size": "300x200"}), ()) == Box(88, 48, 324, 224)
    assert link.asked == []


def test_the_notes_get_a_strip_under_the_crop_and_the_picture_grows_by_it():
    asked = []

    def heights(texts, width):
        asked.append((texts, width))
        return [44.3, 68.6]

    desk, _ = stage(("find", PANEL), heights=heights)
    assert desk.crop_to(crop(), ("Short.", "A longer note.")) == Box(88, 38, 364, 344)
    # As tall as the longest note needs, at an even number: 70.
    assert asked == [(["Short.", "A longer note."], 364)]


def test_a_crop_whose_element_has_no_size_has_no_picture():
    desk, _ = stage(("find", found(width=0, height=0)))
    with pytest.raises(StepFailed) as caught:
        desk.crop_to(crop(), ())
    assert str(caught.value) == 'crop role=button name="Add": the element has no size, so there is no picture to cut to it'


def test_a_crop_that_is_not_found_fails_as_an_action_does():
    desk, _ = stage(("find", {"count": 0, "tried": ["tree"], "nearest": []}))
    with pytest.raises(StepFailed, match='crop role=button name="Add": not in the tree'):
        desk.crop_to(crop(), ())


def cropped(tmp_path, panel, *script, height=44.3):
    """A stage that measured its crop for one note, and has started recording."""
    clock = FakeClock()
    desk, link = stage(
        ("find", panel), ("record_start", {"first_frame": 99.5}), *script, STOP,
        now=clock.now, sleep=clock.sleep, heights=lambda texts, width: [height] * len(texts),
    )
    desk.crop_to(crop(), ("Pick a role.",))
    desk.start_recording(tmp_path / "capture.mkv")
    return desk, link, clock


def test_the_strip_is_there_for_the_whole_take_and_a_note_is_written_in_it(tmp_path):
    desk, _, clock = cropped(tmp_path, PANEL)
    clock.t += 0.5
    desk.show_note("Pick a role.")
    clock.t += 2.0
    desk.hide_note()
    clock.t += 1.0
    strip, note = stopped(desk, tmp_path).shown
    where = Box(88, 312, 364, 46)
    assert (strip.kind, strip.start, strip.end, strip.html) == ("strip", 0.0, 3.5, notes.strip_html(where))
    assert (note.kind, note.start, note.end, note.html) == ("note", 0.5, 2.5, notes.note_html("Pick a role.", where))


def test_a_strip_inside_the_crop_is_shown_with_its_note_only(tmp_path):
    # A crop as tall as the window leaves no room under it or above it.
    desk, _, clock = cropped(tmp_path, found(x=0, y=0, width=1920, height=1080))
    desk.show_note("Pick a role.")
    clock.t += 1.0
    (note,) = stopped(desk, tmp_path).shown
    assert note.html == notes.note_html("Pick a role.", Box(0, 1034, 1920, 46))


def test_an_arrow_of_a_cropped_take_stays_inside_the_crop(tmp_path):
    target = Box(380, 60, 60, 30)
    nothing = ("busy", lambda fields: {"shares": [0.0] * len(fields["areas"])})
    desk, _, _ = cropped(tmp_path, PANEL, ("find", found(x=380, y=60, width=60, height=30)), nothing)
    desk.mark(action({"arrow": ADD}), True)
    candidates = marks.arrows(target, (1920, 1080), None, CUT)

    def outside(point):
        return point[0] < 92 or point[1] < 42 or point[0] > 448 or point[1] > 308

    expected = marks.emptiest(candidates, [sum(map(outside, candidate.points)) for candidate in candidates])
    mark = next(shown for shown in stopped(desk, tmp_path).shown if shown.kind == "mark")
    assert mark.html == marks.layer(marks.arrow(expected), (1920, 1080))
    assert not any(map(outside, expected.points))


def test_a_probe_names_each_action_whose_element_the_crop_leaves_out():
    near, far = found(x=120, y=60), found(x=900, y=600)
    press, point = [("pointer", {}), ("click", {})], [("pointer", {})]
    script = [
        ("find", PANEL), ("find", near), *press, ("find", far), *press, ("find", far), ("find", far),
        ("find", far), *point, ("find", far), *point, ("outline", outlined()),
    ]
    desk, _ = stage(*script, heights=no_notes)
    desk.crop_to(crop(), ())
    away = {"role": "button", "name": "Far"}
    desk.perform(action({"click": ADD}), Pace())
    desk.perform(action({"click": away}), Pace())
    desk.mark(action({"circle": away}), False)
    # A wait shows nothing, so it is not named. The same action twice is named once.
    desk.perform(action({"wait_for": away}), Pace())
    desk.perform(action({"hover": away}), Pace())
    desk.perform(action({"hover": away}), Pace())
    assert desk.report(None, 20_000).notices == (
        'click role=button name="Far": the element is not inside the crop',
        'circle role=button name="Far": the element is not inside the crop',
        'hover role=button name="Far": the element is not inside the crop',
    )


def test_without_a_crop_nothing_is_left_out():
    desk, _ = stage(("find", found(x=900, y=600)), ("pointer", {}), ("click", {}), ("outline", outlined()))
    desk.perform(action({"click": ADD}), Pace())
    assert desk.report(None, 20_000).notices == ()


def read(*lines):
    return {"lines": [{"text": text, "box": list(box)} for text, box in lines]}


def reporting(tmp_path, *script):
    """A stage that saves the screenshot of its report."""
    shots = tmp_path / "cache" / "probe" / "demo.png"
    return *stage(*script, shots=shots), shots


def test_the_report_has_the_words_that_the_outline_lacks_as_locators_to_copy(tmp_path):
    lines = read(("Layer 1", (1620.4, 200.2, 61.5, 23.6)), ("Painted words", (40, 180, 250.0, 36.0)))
    desk, link, shots = reporting(tmp_path, ("outline", outlined()), ("screenshot", {"path": "/tmp/howto/screen.png"}), ("words", lines))
    page = desk.report(None, 20_000)
    assert page.words == ('"Layer 1" {at: 1620x200, size: 62x24}', '"Painted words" {at: 40x180, size: 250x36}')
    assert page.screenshot == str(shots) and shots.read_bytes() == b"fetched"
    assert link.asked[1:] == [
        ("screenshot", {}),
        ("words", {"lacking": True, "within": None, "shot": "/tmp/howto/screen.png"}),
    ]
    assert link.fetched == [("/tmp/howto/screen.png", shots)]


def test_the_words_of_a_report_are_limited_as_its_outline_is(tmp_path):
    script = [("outline", outlined()), ("screenshot", {"path": "/s.png"}), ("words", read())]
    desk, link, _ = reporting(tmp_path, *script)
    desk.report(parse_locator({"role": "dialog"}, "x"), 20_000)
    assert link.asked[2][1]["within"] == {"role": "dialog"}


def test_the_words_get_what_the_outline_leaves_of_the_limit(tmp_path):
    lines = read(("One", (0, 0, 10, 10)), ("Two", (0, 20, 10, 10)), ("Three", (0, 40, 10, 10)))
    script = [("outline", outlined(outline="- frame")), ("screenshot", {"path": "/s.png"}), ("words", lines)]
    desk, _, _ = reporting(tmp_path, *script)
    # The outline has 7 characters, so 63 are left. A line of words costs about 30 with its line break: two fit.
    page = desk.report(None, 70)
    assert page.words == ('"One" {at: 0x0, size: 10x10}', '"Two" {at: 0x20, size: 10x10}')
    assert page.omitted == len('"Three" {at: 0x40, size: 10x10}')


def test_an_outline_that_was_cut_leaves_no_room_for_words(tmp_path):
    lines = read(("One", (0, 0, 10, 10)))
    desk, _, _ = reporting(tmp_path, ("outline", outlined()), ("screenshot", {"path": "/s.png"}), ("words", lines))
    page = desk.report(None, 30)
    assert page.words == () and page.omitted == 17 + len('"One" {at: 0x0, size: 10x10}')
    assert page.screenshot


def test_a_report_without_a_place_for_its_screenshot_asks_for_none(tmp_path):
    desk, link = stage(("outline", outlined()))
    page = desk.report(None, 20_000)
    assert (page.words, page.screenshot) == ((), "")
    assert [name for name, _ in link.asked] == ["outline"]


def test_words_on_the_screen_are_pressed_without_asking_what_covers_them():
    on_screen = {"count": 1, "box": [40, 180, 250, 36], "layer": "screen", "window": ""}
    desk, link = stage(("find", on_screen), ("pointer", {}), ("click", {}))
    desk.perform(action({"click": {"text": "Painted words"}}), Pace())
    assert link.asked[1:] == [("pointer", {"x": 165.0, "y": 198.0, "seconds": 0.0}), ("click", {"hold": 0, "window": ""})]


def test_words_that_are_nowhere_say_that_both_were_looked_at():
    desk, _ = stage(("find", {"count": 0, "tried": ["tree", "screen"], "nearest": ["Export"]}))
    assert failure(desk, {"click": {"text": "Exprot"}}) == (
        'click text="Exprot": not in the tree, and no such words on the screen. The nearest words: "Export"'
    )


TARGET = found(x=900, y=500, width=120, height=40)
# What `zoom.frame` gives for that target in a picture of 1920 by 1080, enlarged twice.
AROUND_TARGET = (480.0, 250.0, 2.0)


def zooming(tmp_path, *script, **options):
    """A stage of a storyboard that zooms, which has started recording."""
    clock = FakeClock()
    link = ScriptedLink(("record_start", {"first_frame": 99.5}), *script)
    desk = DesktopStage(link, board(zoom=2), timeout=10, first="Fixture", now=clock.now, sleep=clock.sleep, **options)
    desk.start_recording(tmp_path / "capture.mkv")
    return desk, link, clock


def test_a_storyboard_that_zooms_gets_a_monitor_of_twice_the_size():
    assert scale_of(board()) == 1
    assert scale_of(board(zoom=2)) == 2
    assert scale_of(board([{"do": [{"click": ADD}], "zoom": 1.5}])) == 2


def test_a_zoom_writes_a_move_and_the_take_waits_for_it(tmp_path):
    desk, _, clock = zooming(tmp_path, ("find", TARGET), STOP)
    clock.t += 1.0
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    assert ZOOM == 0.8 and clock.t == pytest.approx(101.8)
    log = stopped(desk, tmp_path)
    assert log.scale == 2 and log.moves == (Move(1.0, 0.8, *AROUND_TARGET),)


def test_the_corner_of_the_enlarged_part_is_at_whole_pixels(tmp_path):
    # The middle of this target is at 961.5, 521.5, so `zoom.frame` gives a corner of 481.5, 251.5.
    desk, _, _ = zooming(tmp_path, ("find", found(x=901, y=501, width=121, height=41)), STOP)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    assert stopped(desk, tmp_path).moves == (Move(0.0, 0.8, 481.0, 251.0, 2.0),)


def test_the_way_back_is_a_move_to_the_whole_picture(tmp_path):
    desk, _, clock = zooming(tmp_path, ("find", TARGET), STOP)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    clock.t += 1.0
    desk.zoom_out(True)
    assert clock.t == pytest.approx(102.6)
    into, out = stopped(desk, tmp_path).moves
    assert out == Move(pytest.approx(1.8), 0.8, 0.0, 0.0, 1.0)


def test_the_same_target_twice_and_a_wide_picture_that_goes_wide_move_nothing(tmp_path):
    desk, _, clock = zooming(tmp_path, ("find", TARGET), ("find", TARGET), STOP)
    desk.zoom_out(True)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    assert clock.t == pytest.approx(100.8)
    assert len(stopped(desk, tmp_path).moves) == 1


def test_a_target_too_large_to_enlarge_leaves_the_picture_wide(tmp_path):
    desk, _, clock = zooming(tmp_path, ("find", found(x=10, y=10, width=1880, height=1000)), STOP)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    assert clock.t == 100.0 and stopped(desk, tmp_path).moves == ()


def test_a_wide_picture_at_once_is_a_move_without_seconds(tmp_path):
    # What `runner` asks for after a step that failed or was stopped.
    desk, _, clock = zooming(tmp_path, ("find", TARGET), STOP)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    desk.zoom_out(False)
    assert clock.t == pytest.approx(100.8)
    assert stopped(desk, tmp_path).moves[1] == Move(pytest.approx(0.8), 0.0, 0.0, 0.0, 1.0)


def test_a_click_in_an_enlarged_picture_shows_its_ring_where_the_viewer_sees_the_control(tmp_path):
    desk, link, _ = zooming(tmp_path, ("find", TARGET), ("find", TARGET), ("pointer", {}), ("click", {}), STOP)
    desk.zoom_to(action({"click": ADD}), 2.0, True)
    desk.perform(action({"click": ADD}), Pace())
    # The pointer goes to the control where the app has it.
    assert link.asked[3][1]["x"] == 960.0 and link.asked[3][1]["y"] == 520.0
    (ring,) = stopped(desk, tmp_path).shown
    # (960 - 480) * 2 and (520 - 250) * 2: the middle of the enlarged picture.
    assert "left:960.0px;top:540.0px" in ring.html


def test_a_mark_in_an_enlarged_picture_goes_around_the_enlarged_control(tmp_path):
    desk, _, _ = zooming(tmp_path, ("find", TARGET), ("find", TARGET), STOP)
    mark = action({"box": ADD})
    desk.zoom_to(mark, 2.0, True)
    desk.mark(mark, True)
    (shown,) = stopped(desk, tmp_path).shown
    assert shown.html == marks.layer(marks.box(Box(840, 500, 240, 80), (1920, 1080)), (1920, 1080))


def test_the_picture_holds_still_under_a_mark_while_the_next_target_is_in_it(tmp_path):
    inside, outside = found(x=1000, y=560, width=80, height=30), found(x=100, y=900, width=80, height=30)
    script = [("find", TARGET), ("find", TARGET), ("find", inside), ("find", inside), ("find", outside), STOP]
    desk, _, clock = zooming(tmp_path, *script)
    mark = action({"underline": ADD})
    desk.zoom_to(mark, 2.0, True)
    desk.mark(mark, True)
    desk.zoom_to(mark, 2.0, True)
    desk.mark(mark, True)
    assert clock.t == pytest.approx(102.0)
    # The third target is not in the picture. The marks fade first, and then the picture moves.
    desk.zoom_to(mark, 2.0, True)
    assert clock.t == pytest.approx(103.05)
    log = stopped(desk, tmp_path)
    assert log.moves == (Move(0.0, 0.8, *AROUND_TARGET), Move(pytest.approx(2.25), 0.8, 0.0, 540.0, 2.0))
    assert [shown.end for shown in log.shown] == [pytest.approx(2.25), pytest.approx(2.25)]


def test_an_arrow_in_an_enlarged_picture_asks_about_places_of_the_picture_s_own_size(tmp_path):
    nothing = ("busy", lambda fields: {"shares": [0.0] * len(fields["areas"])})
    desk, link, _ = zooming(tmp_path, ("find", TARGET), ("find", TARGET), nothing, STOP)
    arrow = action({"arrow": ADD})
    desk.zoom_to(arrow, 2.0, True)
    desk.mark(arrow, True)
    candidates = marks.arrows(Box(840, 500, 240, 80), (1920, 1080))
    areas = link.asked[3][1]["areas"]
    x, y = candidates[0].points[0]
    # A point of the enlarged picture, back in the picture at its own size: half as far from the corner of the part that is shown.
    assert areas[0] == pytest.approx([480 + (x - 6) / 2, 250 + (y - 6) / 2, 6.0, 6.0])
    assert all(area[2:] == [6.0, 6.0] for area in areas)
    (shown,) = stopped(desk, tmp_path).shown
    assert shown.html == marks.layer(marks.arrow(candidates[0]), (1920, 1080))


def test_a_probe_finds_the_target_of_a_zoom_and_writes_nothing():
    link = ScriptedLink(("find", TARGET), ("find", {"count": 0, "tried": ["tree"], "nearest": []}))
    desk = DesktopStage(link, board(zoom=2), timeout=10, first="Fixture")
    desk.zoom_to(action({"click": ADD}), 2.0, False)
    desk.zoom_out(False)
    with pytest.raises(StepFailed, match='click role=button name="Add": not in the tree'):
        desk.zoom_to(action({"click": ADD}), 2.0, False)
