"""DesktopStage against a scripted helper: the requests it sends for each action, and what it makes of the replies."""
from pathlib import Path

import pytest

from fakes import ScriptedLink
from howto.desktop.link import HelperError
from howto.desktop.stage import DesktopStage, wire
from howto.errors import RunError
from howto.runner import Interrupt, StepFailed
from howto.storyboard import Pace, parse, parse_locator

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


def test_a_mark_of_a_probe_only_finds_its_element():
    desk, link = stage(("find", found()))
    desk.mark(action({"circle": ADD}), False)
    desk.clear_marks(False)
    assert link.asked == [FIND_ADD]


@pytest.mark.parametrize(
    "call, what",
    [
        (lambda desk: desk.start_recording(Path("capture.mkv")), "a recording"),
        (lambda desk: desk.crop_to(action({"click": ADD}), ()), "`crop`"),
        (lambda desk: desk.mark(action({"circle": ADD}), True), "a mark"),
    ],
)
def test_what_a_take_needs_is_not_built_yet(call, what):
    desk, _ = stage(("find", found()))
    with pytest.raises(RunError, match=f"{what} of a desktop app is not built yet"):
        call(desk)
