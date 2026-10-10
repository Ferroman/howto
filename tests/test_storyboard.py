from pathlib import Path

import pytest
import yaml

from howto.errors import StoryboardError
from howto.storyboard import Pace, load, parse, parse_locator, split_sentences

EXAMPLE = """
title: Invite a teammate
url: https://app.example.com
profile: demo
setup:
  - wait_for: {role: button, name: Settings}
steps:
  - say: Open Settings from the menu in the top right.
    do:
      - click: {role: button, name: Settings}
  - chapter: Invite
  - say: Type your teammate's email, then press Invite. The invitation is valid for seven days.
    note: The invitation is valid for seven days.
    pause: 1
    do:
      - fill: {label: Email, value: sam@example.com}
      - select: {label: Role, option: Admin}
      - press: Enter
cleanup:
  - click: {role: button, name: Revoke invitation}
"""


def board(**changes):
    data = yaml.safe_load(EXAMPLE)
    data.update(changes)
    return data


def one_step(step):
    return board(steps=[step])


def error(data) -> str:
    with pytest.raises(StoryboardError) as caught:
        parse(data, Path("demo.yaml"))
    return str(caught.value)


def test_example_parses():
    sb = parse(board(), Path("videos/invite.yaml"))
    assert sb.name == "invite"
    assert (sb.title, sb.url, sb.profile) == ("Invite a teammate", "https://app.example.com", "demo")
    assert sb.viewport == (1920, 1080)
    assert sb.pace == Pace()
    assert [s.index for s in sb.steps] == [1, 2, 3]
    assert sb.steps[0].say == ("Open Settings from the menu in the top right.",)
    assert sb.steps[1].chapter == "Invite" and sb.steps[1].do == ()
    third = sb.steps[2]
    assert third.say == (
        "Type your teammate's email, then press Invite.",
        "The invitation is valid for seven days.",
    )
    assert third.note == "The invitation is valid for seven days."
    assert third.pause == 1.0
    assert [a.kind for a in third.do] == ["fill", "select", "press"]
    assert third.do[0].value == "sam@example.com" and third.do[0].locator.label == "Email"
    assert third.do[1].value == "Admin"
    assert third.do[2].value == "Enter" and third.do[2].locator is None
    assert sb.setup[0].kind == "wait_for"
    assert sb.cleanup[0].locator.name == "Revoke invitation"


def test_describe_reads_like_the_storyboard():
    sb = parse(board(), Path("demo.yaml"))
    assert sb.steps[0].do[0].describe() == 'click role=button name="Settings"'
    assert sb.steps[2].do[0].describe() == 'fill label="Email" value="sam@example.com"'
    assert sb.steps[2].do[1].describe() == 'select label="Role" option="Admin"'
    assert sb.steps[2].do[2].describe() == "press Enter"


def test_locator_extras():
    locator = parse_locator(
        {"role": "button", "name": "Remove", "exact": True, "nth": 1, "within": {"text": "bob@example.com"}},
        "here",
    )
    assert (locator.exact, locator.nth, locator.within.text) == (True, 1, "bob@example.com")
    assert locator.describe() == 'role=button name="Remove" exact nth=1 within(text="bob@example.com")'


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Open Settings.", ("Open Settings.",)),
        ("Open Settings. Then press Invite!  Done?", ("Open Settings.", "Then press Invite!", "Done?")),
        ("Set the size to 2.5 GB. Save it.", ("Set the size to 2.5 GB.", "Save it.")),
        ("  No full stop at the end  ", ("No full stop at the end",)),
    ],
)
def test_split_sentences(text, expected):
    assert split_sentences(text) == expected


def test_a_say_list_is_never_split():
    sb = parse(one_step({"say": ["Use a test account, e.g. the demo one.", "Save it."]}), Path("demo.yaml"))
    assert sb.steps[0].say == ("Use a test account, e.g. the demo one.", "Save it.")


def test_numbers_become_text():
    data = board(title=2026)
    data["steps"] = [{"say": 42, "do": [{"fill": {"label": "Code", "value": 12345}}, {"click": {"role": "button", "name": 7}}]}]
    sb = parse(data, Path("demo.yaml"))
    assert sb.title == "2026"
    assert sb.steps[0].say == ("42",)
    assert sb.steps[0].do[0].value == "12345"
    assert sb.steps[0].do[1].locator.name == "7"


def test_viewport_is_read():
    assert parse(board(viewport="1280x720"), Path("demo.yaml")).viewport == (1280, 720)


@pytest.mark.parametrize("viewport", ["1281x721", "1280x721"])
def test_an_odd_viewport_is_refused(viewport):
    assert "even" in error(board(viewport=viewport))


@pytest.mark.parametrize("viewport", ["0x0", "1920 x 1080", 1920, "wide"])
def test_a_malformed_viewport_is_refused(viewport):
    assert "WIDTHxHEIGHT" in error(board(viewport=viewport))


def test_pace_overrides():
    sb = parse(board(pace={"lead": 1, "typing": 40}), Path("demo.yaml"))
    assert sb.pace == Pace(lead=1.0, typing=40.0)


@pytest.mark.parametrize(
    "data, fragment",
    [
        (["not", "a", "mapping"], "must be a mapping"),
        ({"url": "x", "steps": [{"say": "Hi."}]}, "missing field `title`"),
        (board(titel="x"), "unknown field `titel`"),
        (board(steps=[]), "`steps` must be a list with at least one step"),
        (board(steps=["click"]), "step 1: a step must be a mapping"),
        (one_step({"sya": "Hi."}), "step 1: unknown field `sya`"),
        (one_step({"note": "Only a note"}), "step 1: a step needs at least one of"),
        (one_step({"say": "   "}), "step 1: `say`: must be non-empty text"),
        (one_step({"say": []}), "step 1: `say` must not be empty"),
        (one_step({"do": {"click": {"label": "x"}}}), "step 1: `do` must be a list of actions"),
        (one_step({"do": [{"clik": {"label": "x"}}]}), "step 1: `do[1]`: unknown action `clik`"),
        (one_step({"do": [{"click": {"label": "x"}, "hover": {"label": "y"}}]}), "step 1: `do[1]`: an action must be a mapping with one key"),
        (one_step({"do": [{"click": {"label": "x", "text": "y"}}]}), "step 1: `do[1]`: `click`: a locator needs exactly one of"),
        (one_step({"do": [{"click": {"name": "Save"}}]}), "a locator needs exactly one of"),
        (one_step({"do": [{"click": {"label": "x", "name": "y"}}]}), "`name` needs `role`"),
        (one_step({"do": [{"click": {"rol": "button"}}]}), "unknown locator key `rol`"),
        (one_step({"do": [{"click": "Save"}]}), "a locator must be a mapping"),
        (one_step({"do": [{"fill": {"label": "Email"}}]}), "step 1: `do[1]`: `fill`: needs a locator and `value`"),
        (one_step({"do": [{"select": {"label": "Role"}}]}), "step 1: `do[1]`: `select`: needs a locator and `option`"),
        (one_step({"do": [{"goto": ""}]}), "`goto`: must be non-empty text"),
        (one_step({"do": [{"click": {"label": "x", "nth": -1}}]}), "`nth` must be a whole number, 0 or more"),
        (one_step({"do": [{"click": {"label": "x", "exact": "yes"}}]}), "`exact` must be true or false"),
        (one_step({"say": "Hi.", "pause": -1}), "step 1: `pause` must be a number, 0 or more"),
        (board(profile="../escape"), "`profile`: use letters, digits, `-` and `_` only"),
        (board(pace={"led": 1}), "`pace`: unknown value `led`"),
        (board(pace={"typing": 0}), "`pace`: `typing` must be more than 0"),
        (board(pace={"gap": -1}), "`pace`: `gap` must be 0 or more"),
        (board(setup=[{"clik": {"label": "x"}}]), "`setup[1]`: unknown action `clik`"),
        (board(cleanup="click"), "`cleanup` must be a list of actions"),
    ],
)
def test_invalid_storyboards_name_the_problem(data, fragment):
    assert fragment in error(data)


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "invite.yaml"
    path.write_text(EXAMPLE, encoding="utf-8")
    sb = load(path)
    assert sb.path == path and sb.name == "invite" and len(sb.steps) == 3


def test_load_reports_a_missing_file(tmp_path):
    with pytest.raises(StoryboardError, match="no such file"):
        load(tmp_path / "absent.yaml")


def test_load_reports_bad_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("title: [unclosed\n", encoding="utf-8")
    with pytest.raises(StoryboardError, match="not valid YAML"):
        load(path)


def test_load_puts_the_path_in_front_of_the_problem(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("title: T\nurl: http://x.test\nsteps: []\n", encoding="utf-8")
    with pytest.raises(StoryboardError) as caught:
        load(path)
    assert str(caught.value).startswith(f"{path}: `steps` must be a list")
