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


def test_the_picture_stays_wide_unless_zoom_is_asked_for():
    sb = parse(board(), Path("demo.yaml"))
    assert sb.zoom == 1.0
    assert [step.zoom for step in sb.steps] == [None, None, None]


def test_zoom_for_the_whole_video_and_for_one_step():
    steps = [{"say": "One.", "do": [{"click": {"label": "x"}}]}, {"say": "Two.", "zoom": "1"}, {"say": "Three.", "zoom": 3}]
    sb = parse(board(zoom="2.5", steps=steps), Path("demo.yaml"))
    assert sb.zoom == 2.5
    assert [step.zoom for step in sb.steps] == [None, 1.0, 3.0]


def test_the_picture_is_the_whole_window_unless_crop_is_asked_for():
    assert parse(board(), Path("demo.yaml")).crop is None


def test_crop_names_the_part_of_the_page_that_a_picture_is_cut_to():
    sb = parse(board(crop={"role": "complementary", "name": "Layers", "nth": "0"}), Path("demo.yaml"))
    assert sb.crop.describe() == 'role=complementary name="Layers" nth=0'


def test_a_step_may_still_say_that_it_does_not_zoom_under_a_crop():
    sb = parse(board(crop={"label": "x"}, zoom="1", steps=[{"say": "Hi.", "zoom": 1}]), Path("demo.yaml"))
    assert (sb.zoom, sb.steps[0].zoom) == (1.0, 1.0)


def test_pace_carries_the_time_a_zoom_is_held():
    assert Pace().zoom_hold == 0.9
    assert parse(board(pace={"zoom_hold": "0.3"}), Path("demo.yaml")).pace.zoom_hold == 0.3


@pytest.mark.parametrize("kind", ["box", "circle", "underline", "spotlight", "arrow"])
def test_a_mark_names_its_element_as_a_click_does(kind):
    do = [{kind: {"role": "button", "name": "Invite", "within": {"role": "dialog"}}}]
    (action,) = parse(one_step({"do": do}), Path("demo.yaml")).steps[0].do
    assert (action.kind, action.value) == (kind, None)
    assert action.locator.name == "Invite"
    assert action.describe() == f'{kind} role=button name="Invite" within(role=dialog)'


def test_an_arrow_can_carry_a_few_words():
    # `text` is already a way to name the element, so the words have a key of their own.
    do = [{"arrow": {"text": "Invitations", "note": "Everyone you invited"}}]
    (action,) = parse(one_step({"do": do}), Path("demo.yaml")).steps[0].do
    assert (action.locator.text, action.value) == ("Invitations", "Everyone you invited")
    assert action.describe() == 'arrow text="Invitations" note="Everyone you invited"'


def test_pace_carries_the_time_a_mark_is_held():
    assert Pace().mark_hold == 0.6
    assert parse(board(pace={"mark_hold": "1.5"}), Path("demo.yaml")).pace.mark_hold == 1.5


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
        (board(voice="../escape"), "`voice`: use letters, digits, `-` and `_` only"),
        (board(voice=""), "`voice`: must be non-empty text"),
        (board(pace={"led": 1}), "`pace`: unknown value `led`"),
        (board(pace={"typing": 0}), "`pace`: `typing` must be more than 0"),
        (board(pace={"gap": -1}), "`pace`: `gap` must be 0 or more"),
        (board(setup=[{"clik": {"label": "x"}}]), "`setup[1]`: unknown action `clik`"),
        (board(cleanup="click"), "`cleanup` must be a list of actions"),
        (board(zoom="0.5"), "`zoom` must be a number from 1 to 4"),
        (board(zoom="5"), "`zoom` must be a number from 1 to 4"),
        (board(zoom="big"), "`zoom` must be a number from 1 to 4"),
        (board(zoom=True), "`zoom` must be a number from 1 to 4"),
        (one_step({"say": "Hi.", "zoom": "0"}), "step 1: `zoom` must be a number from 1 to 4"),
        (one_step({"say": "Hi.", "zoom": {"factor": 2}}), "step 1: `zoom` must be a number from 1 to 4"),
        (one_step({"do": [{"circle": {"name": "Save"}}]}), "step 1: `do[1]`: `circle`: a locator needs exactly one of"),
        (one_step({"do": [{"arrow": "Save"}]}), "step 1: `do[1]`: `arrow`: a locator must be a mapping"),
        (one_step({"do": [{"box": {"label": "x", "note": "Here"}}]}), "step 1: `do[1]`: `box`: only `arrow` takes a `note`"),
        (one_step({"do": [{"arrow": {"label": "x", "note": " "}}]}), "step 1: `do[1]`: `arrow`: `note`: must be non-empty text"),
        (board(setup=[{"circle": {"label": "x"}}]), "`setup[1]`: `circle` draws on the picture, and `setup` is not recorded"),
        (board(cleanup=[{"arrow": {"label": "x"}}]), "`cleanup[1]`: `arrow` draws on the picture, and `cleanup` is not recorded"),
        (board(crop="the sidebar"), "`crop`: a locator must be a mapping"),
        (board(crop={"label": "x", "note": "Here"}), "`crop`: unknown locator key `note`"),
        (board(crop={"label": "x"}, zoom="2"), "`zoom` and `crop` do not go together"),
        (board(crop={"label": "x"}, steps=[{"say": "Hi."}, {"say": "Hi.", "zoom": 2}]), "step 2: `zoom` and `crop` do not go together"),
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


WRITTEN_VALUES = """
title: 2026-10-10
url: http://demo.test
profile:
steps:
  - say: Type the code.
    pause: 1.5
    do:
      - fill: {label: ZIP code, value: 02134}
      - fill: {label: Time, value: 12:30}
      - fill: {label: Phone, value: +15551234567}
      - fill: {label: Price, value: 1.50}
      - fill: {label: Amount, value: 1_000}
      - click: {role: button, name: Yes, exact: true, nth: 0}
      - select: {label: Newsletter, option: No}
      - press: 5
cleanup:
pace: {lead: 1, typing: 40}
"""


def test_a_file_keeps_each_value_as_it_is_written(tmp_path):
    # YAML would read 02134 as the octal number 1116, 12:30 as 750, and Yes as true.
    path = tmp_path / "written.yaml"
    path.write_text(WRITTEN_VALUES, encoding="utf-8")
    sb = load(path)
    do = sb.steps[0].do
    assert sb.title == "2026-10-10"
    assert [action.value for action in do[:5]] == ["02134", "12:30", "+15551234567", "1.50", "1_000"]
    assert (do[5].locator.name, do[5].locator.exact, do[5].locator.nth) == ("Yes", True, 0)
    assert do[6].value == "No"
    assert do[7].value == "5"


def test_a_file_still_reads_its_numbers_and_empty_fields(tmp_path):
    path = tmp_path / "written.yaml"
    path.write_text(WRITTEN_VALUES, encoding="utf-8")
    sb = load(path)
    assert sb.steps[0].pause == 1.5
    assert sb.pace == Pace(lead=1.0, typing=40.0)
    assert sb.profile is None and sb.cleanup == ()


@pytest.mark.parametrize(
    "line, fragment",
    [
        ("pause: soon", "step 1: `pause` must be a number, 0 or more"),
        ("pause: .inf", "step 1: `pause` must be a number, 0 or more"),
        ("pause: nan", "step 1: `pause` must be a number, 0 or more"),
        ("do: [{click: {label: x, nth: first}}]", "`nth` must be a whole number, 0 or more"),
        ("do: [{click: {label: x, nth: 1.5}}]", "`nth` must be a whole number, 0 or more"),
        ("do: [{click: {label: x, exact: maybe}}]", "`exact` must be true or false"),
    ],
)
def test_a_file_with_a_malformed_number_or_flag_is_refused(tmp_path, line, fragment):
    path = tmp_path / "bad.yaml"
    path.write_text(f"title: T\nurl: http://demo.test\nsteps:\n  - say: Hi.\n    {line}\n", encoding="utf-8")
    with pytest.raises(StoryboardError) as caught:
        load(path)
    assert fragment in str(caught.value)


def test_a_malformed_pace_number_is_refused(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("title: T\nurl: http://demo.test\npace: {typing: fast}\nsteps:\n  - say: Hi.\n", encoding="utf-8")
    with pytest.raises(StoryboardError, match="`pace`: `typing` must be a number"):
        load(path)


def test_a_storyboard_names_its_voice():
    assert parse(board(voice="narrator"), Path("x.yaml")).voice == "narrator"


def test_a_storyboard_without_a_voice_has_none():
    assert parse(board(), Path("x.yaml")).voice is None


DESKTOP = """
title: Add a name
app:
  image: howto-fixture
  run: python3 /opt/fixture/app.py
steps:
  - say: Type a name and press Add.
    do:
      - fill: {label: Name, value: sam}
      - click: {role: button, name: Add}
      - click: {at: 960x540}
      - type: hello
cleanup:
  - run: rm -f /home/howto/notes.txt
"""


def desk(**changes):
    data = yaml.safe_load(DESKTOP)
    data.update(changes)
    return data


def desk_step(*actions):
    return desk(steps=[{"do": list(actions)}])


def test_a_desktop_storyboard_names_its_app():
    sb = parse(desk(), Path("videos/add.yaml"))
    assert (sb.app.image, sb.app.run) == ("howto-fixture", "python3 /opt/fixture/app.py")
    assert sb.url is None and sb.desktop
    assert sb.origin == "videos/add.yaml"


def test_a_web_storyboard_has_no_app():
    sb = parse(board(), Path("demo.yaml"))
    assert sb.app is None and not sb.desktop
    assert sb.origin == "https://app.example.com"


def test_a_place_is_a_point_and_with_a_size_an_area():
    do = [{"click": {"at": "960x540"}}, {"box": {"at": "900x500", "size": "120x40"}}]
    click, box = parse(desk_step(*do), Path("x.yaml")).steps[0].do
    assert (click.locator.at, click.locator.size, click.locator.area) == ((960, 540), None, False)
    assert (box.locator.at, box.locator.size, box.locator.area) == ((900, 500), (120, 40), True)
    assert click.describe() == "click at=960x540"
    assert box.describe() == "box at=900x500 size=120x40"


def test_a_locator_of_the_tree_gives_an_area():
    assert parse_locator({"role": "button", "name": "Add"}, "here").area


def test_type_and_run_take_text():
    sb = parse(desk(), Path("x.yaml"))
    assert sb.steps[0].do[3].describe() == "type hello"
    assert sb.cleanup[0].describe() == "run rm -f /home/howto/notes.txt"


def test_type_also_goes_in_a_web_storyboard():
    sb = parse(one_step({"do": [{"type": "hello"}]}), Path("x.yaml"))
    assert sb.steps[0].do[0].describe() == "type hello"


def test_a_storyboard_says_whether_it_zooms():
    assert not parse(desk(), Path("x.yaml")).zooms
    assert parse(desk(zoom="2"), Path("x.yaml")).zooms
    assert parse(desk(steps=[{"say": "Hi.", "zoom": 2}]), Path("x.yaml")).zooms
    assert not parse(desk(zoom="1", steps=[{"say": "Hi.", "zoom": 1}]), Path("x.yaml")).zooms


@pytest.mark.parametrize(
    "data, fragment",
    [
        (desk(url="http://demo.test"), "`url` and `app` do not go together"),
        ({"title": "T", "steps": [{"say": "Hi."}]}, "missing field `url`, for a web page, or `app`, for a desktop app"),
        (desk(app="inkscape"), "`app` must be a mapping with `image` and `run`"),
        (desk(app={"image": "howto-fixture"}), "`app`: missing field `run`"),
        (desk(app={"run": "gedit"}), "`app`: missing field `image`"),
        (desk(app={"image": "howto-fixture", "run": "gedit", "user": "root"}), "`app`: unknown field `user`"),
        (desk(app={"image": "--privileged", "run": "gedit"}), "`app`: `image`: use the name of a Docker image"),
        (desk(app={"image": "howto fixture", "run": "gedit"}), "`app`: `image`: use the name of a Docker image"),
        (desk(app={"image": "Howto-Fixture", "run": "gedit"}), "`app`: `image`: use the name of a Docker image"),
        (desk(app={"image": "howto-fixture", "run": " "}), "`app`: `run`: must be non-empty text"),
        (desk_step({"click": {"css": "button"}}),
         "step 1: `do[1]`: `click`: `css` is for a web page. A desktop storyboard can use role, label, text, at"),
        (desk_step({"click": {"placeholder": "Name"}}), "`placeholder` is for a web page"),
        (desk_step({"click": {"testid": "add"}}), "`testid` is for a web page"),
        (desk_step({"click": {"role": "button", "within": {"css": "form"}}}),
         "step 1: `do[1]`: `click`: `within`: `css` is for a web page"),
        (desk_step({"goto": "http://demo.test"}), "step 1: `do[1]`: `goto` is for a web page: an app has no addresses"),
        (desk(crop={"css": "aside"}), "`crop`: `css` is for a web page"),
        (desk_step({"click": {"at": "960"}}), "step 1: `do[1]`: `click`: `at`: write it as XxY, for example 960x540"),
        (desk_step({"click": {"at": 960}}), "`at`: write it as XxY, for example 960x540"),
        (desk_step({"click": {"at": "960x540", "size": "0x40"}}), "`size`: width and height must be more than 0"),
        (desk_step({"click": {"at": "960x540", "size": "wide"}}), "`size`: write it as XxY, for example 120x40"),
        (desk_step({"click": {"role": "button", "size": "120x40"}}), "`size` needs `at`"),
        (desk_step({"click": {"at": "960x540", "nth": 0}}), "`nth` does not go with `at`"),
        (desk_step({"click": {"at": "1920x540"}}), "step 1: `do[1]`: `click`: `at` is outside the picture of 1920x1080"),
        (desk_step({"box": {"at": "1900x500", "size": "120x40"}}), "`at` and `size` reach outside the picture of 1920x1080"),
        (desk_step({"circle": {"at": "960x540"}}), "step 1: `do[1]`: `circle` needs an area: add `size`"),
        (desk(crop={"at": "100x100"}), "`crop` needs an area: add `size`"),
        (desk_step({"click": {"role": "button", "within": {"at": "0x0", "size": "100x100"}}}),
         "`within` takes a locator of the tree: role, label or text"),
        (one_step({"do": [{"click": {"at": "960x540"}}]}),
         "step 1: `do[1]`: `click`: `at` is for a desktop app. A web storyboard can use role, label, placeholder, text, testid, css"),
        (board(setup=[{"run": "true"}]), "`setup[1]`: `run` is for a desktop app: it runs a command in the container of the app"),
        (board(crop={"at": "0x0", "size": "10x10"}), "`crop`: `at` is for a desktop app"),
    ],
)
def test_what_the_other_kind_of_storyboard_has_is_refused(data, fragment):
    assert fragment in error(data)
