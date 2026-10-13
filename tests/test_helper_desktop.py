"""The helper itself, in a container, on the fixture app. These tests need Docker and the base image."""
import subprocess
import time

import pytest

from howto.assemble import video_duration
from howto.errors import RunError
from howto.tools import find_tool
from howto.desktop import images
from howto.desktop.link import HelperError, open_link
from pictures import dimensions

pytestmark = pytest.mark.desktop
SIZE = {"width": 1280, "height": 720}


@pytest.fixture
def helper(desktop):
    link = open_link(desktop.docker, desktop.image)
    try:
        link.request("start", limit=90, run=desktop.run, timeout=60, **SIZE)
        yield link
    finally:
        link.close()


def find(link, **locator):
    return link.request("find", limit=20, locator=locator, timeout=10)


def press(link, **locator):
    found = find(link, **locator)
    assert found["count"] == 1, found
    x, y, width, height = found["box"]
    link.request("pointer", limit=10, x=x + width / 2, y=y + height / 2, seconds=0)
    link.request("click", limit=10, hold=0, window=found["window"])
    return found


def outline(link):
    return link.request("outline", limit=30)["outline"]


def test_start_gives_the_build_and_the_first_window(desktop):
    link = open_link(desktop.docker, desktop.image)
    try:
        reply = link.request("start", limit=90, run=desktop.run, timeout=60, **SIZE)
    finally:
        link.close()
    assert reply["title"] == "Fixture"
    assert reply["build"] == images.build_id()


def test_the_outline_lists_the_window_and_what_is_in_it(helper):
    text = outline(helper)
    assert text.startswith('- frame "Fixture" [active]:'), text
    for line in ('- menu "File"', '- textbox "Name"', '- combobox "Member"', '- button "Add"', '- label "Nothing added yet"'):
        assert line in text, text


def test_the_first_window_fills_the_monitor(helper):
    assert find(helper, role="frame", name="Fixture")["box"] == [0, 0, 1280, 720]


def test_a_box_is_where_the_element_is(helper):
    found = find(helper, role="button", name="Add")
    x, y, width, height = found["box"]
    assert (found["count"], found["layer"], found["window"]) == (1, "tree", "Fixture")
    assert 0 <= x and 0 <= y and x + width <= 1280 and y + height <= 720 and width > 20 and height > 10


def test_a_click_and_typing_change_the_app(helper):
    press(helper, label="Name")
    helper.request("type", limit=10, text="sam é", rate=0)
    press(helper, role="button", name="Add")
    assert find(helper, text="Added sam é")["count"] == 1


def test_a_key_reaches_the_field_that_has_the_keyboard(helper):
    press(helper, label="Name")
    helper.request("type", limit=10, text="sam", rate=0)
    helper.request("key", limit=10, keys="Control+A")
    helper.request("key", limit=10, keys="Backspace")
    helper.request("type", limit=10, text="kim", rate=0)
    press(helper, role="button", name="Add")
    assert find(helper, text="Added kim")["count"] == 1


def test_a_list_opens_and_an_option_is_one_of_its_items(helper):
    press(helper, label="Role")
    press(helper, option="Admin")
    press(helper, role="button", name="Add")
    assert find(helper, text=", Admin")["count"] == 1


def test_a_dialog_is_a_second_window(helper):
    press(helper, role="menu", name="File")
    press(helper, role="menuitem", name="About")
    assert find(helper, role="dialog", name="About Fixture")["count"] == 1
    reply = helper.request("outline", limit=30)
    assert '- dialog "About Fixture"' in reply["outline"] and '- frame "Fixture"' in reply["outline"]
    assert sorted(reply["windows"]) == ["About Fixture", "Fixture"] and reply["first"] == "Fixture"
    press(helper, role="button", name="Close")


def test_what_does_not_exist_is_not_found_and_the_nearest_name_is_offered(helper):
    reply = helper.request("find", limit=20, locator={"role": "button", "name": "Addd"}, timeout=1)
    assert (reply["count"], reply["tried"], reply["nearest"]) == (0, ["tree"], ["Add"])


def test_a_window_that_covers_an_element_is_named(helper):
    found = find(helper, role="button", name="Add")
    helper.request("run", limit=20, command="python3 /opt/fixture/cover.py >/dev/null 2>&1 &", timeout=10)
    assert find(helper, role="frame", name="Cover")["count"] == 1
    x, y, width, height = found["box"]
    helper.request("pointer", limit=10, x=x + width / 2, y=y + height / 2, seconds=0)
    with pytest.raises(HelperError) as caught:
        helper.request("click", limit=10, hold=0, window="Fixture")
    assert caught.value.kind == "covered" and '"Cover"' in str(caught.value)


def test_a_command_runs_as_the_user_of_the_app(helper):
    reply = helper.request("run", limit=20, command="id -un && echo $HOME", timeout=10)
    assert (reply["code"], reply["output"]) == (0, "howto\n/home/howto")


def test_a_command_that_fails_gives_its_code_and_its_last_lines(helper):
    reply = helper.request("run", limit=20, command="echo gone wrong >&2; exit 3", timeout=10)
    assert (reply["code"], reply["output"]) == (3, "gone wrong")


def test_a_command_that_does_not_end_is_cut_off(helper):
    assert helper.request("run", limit=20, command="sleep 30", timeout=1).get("timed_out") is True


def test_a_wrong_key_is_refused_with_the_names_of_keys(helper):
    with pytest.raises(HelperError) as caught:
        helper.request("key", limit=10, keys="Entre")
    assert caught.value.kind == "bad_key" and "use a name such as Enter" in str(caught.value)


def test_scrolling_to_what_is_in_view_changes_nothing(helper):
    assert helper.request("scroll_to", limit=20, locator={"role": "button", "name": "Add"}, timeout=5)["count"] == 1


def test_an_app_that_ends_at_once_is_reported_at_once_with_what_it_said(desktop):
    link = open_link(desktop.docker, desktop.image)
    began = time.monotonic()
    try:
        with pytest.raises(HelperError) as caught:
            link.request("start", limit=90, run="echo no such app >&2; exit 4", timeout=60, **SIZE)
    finally:
        link.close()
    assert caught.value.kind == "no_window"
    assert "exit code 4" in str(caught.value) and "no such app" in str(caught.value)
    assert time.monotonic() - began < 30


def test_an_app_that_ends_later_is_named_by_the_next_find(helper):
    press(helper, role="menu", name="File")
    press(helper, role="menuitem", name="Quit")
    with pytest.raises(HelperError) as caught:
        helper.request("find", limit=20, locator={"role": "button", "name": "Add"}, timeout=5)
    assert caught.value.kind == "app_exited" and "exit code 0" in str(caught.value)


def test_ending_the_link_ends_the_container(desktop):
    link = open_link(desktop.docker, desktop.image)
    link.request("start", limit=90, run=desktop.run, timeout=60, **SIZE)
    link.close()
    listed = subprocess.run(
        [*desktop.docker, "ps", "-aq", "--filter", f"name={link.name}"], capture_output=True, text=True
    ).stdout
    assert listed.strip() == ""


@pytest.fixture
def ffprobe(monkeypatch):
    monkeypatch.delenv("HOWTO_FFPROBE", raising=False)
    try:
        return find_tool("ffprobe", "HOWTO_FFPROBE")
    except RunError:
        pytest.skip("ffprobe is not installed")


def test_a_recording_is_a_video_of_the_monitor_and_its_first_frame_is_timed(helper, ffprobe, tmp_path):
    before = time.monotonic()
    first = helper.request("record_start", limit=30)["first_frame"]
    after = time.monotonic()
    time.sleep(1.5)
    inside = helper.request("record_stop", limit=30)["path"]
    video = tmp_path / "take.mkv"
    helper.fetch(inside, video)
    # The container has the clock of the host: the first frame lies between asking and being told.
    assert before <= first <= after
    assert dimensions(ffprobe, video) == (1280, 720)
    assert video_duration(ffprobe, video) >= 1.4


def test_stopping_a_recording_that_never_started_is_reported(helper):
    with pytest.raises(HelperError, match="nothing is being recorded"):
        helper.request("record_stop", limit=30)


@pytest.fixture
def ffprobe(monkeypatch):
    monkeypatch.delenv("HOWTO_FFPROBE", raising=False)
    try:
        return find_tool("ffprobe", "HOWTO_FFPROBE")
    except RunError:
        pytest.skip("ffprobe is not installed")


def test_a_recording_is_a_video_of_the_monitor_and_its_first_frame_is_timed(helper, ffprobe, tmp_path):
    before = time.monotonic()
    first = helper.request("record_start", limit=30)["first_frame"]
    after = time.monotonic()
    time.sleep(1.5)
    inside = helper.request("record_stop", limit=30)["path"]
    video = tmp_path / "take.mkv"
    helper.fetch(inside, video)
    # The container has the clock of the host: the first frame lies between asking and being told.
    assert before <= first <= after
    assert dimensions(ffprobe, video) == (1280, 720)
    assert video_duration(ffprobe, video) >= 1.4


def test_stopping_a_recording_that_never_started_is_reported(helper):
    with pytest.raises(HelperError, match="nothing is being recorded"):
        helper.request("record_stop", limit=30)


def words(link, lacking=False):
    return link.request("words", limit=60, lacking=lacking, within=None, shot=None)["lines"]


def test_the_words_of_the_screen_have_places_in_the_picture(helper):
    read = {line["text"]: line["box"] for line in words(helper)}
    assert "Painted words" in read, sorted(read)
    x, y, width, height = read["Painted words"]
    assert 0 <= x and 0 <= y and x + width <= 1280 and y + height <= 720 and width > 150 and 20 < height < 80


def test_only_what_the_tree_lacks_is_left_when_that_is_asked(helper):
    all_of_them = [line["text"] for line in words(helper)]
    lacking = [line["text"] for line in words(helper, lacking=True)]
    assert "Painted words" in lacking
    assert len(lacking) < len(all_of_them)
    assert not [text for text in lacking if text in ("Add", "Flash", "Nothing added yet")]


def test_text_that_the_tree_has_is_found_in_the_tree(helper):
    assert find(helper, text="Nothing added yet")["layer"] == "tree"


def test_text_that_only_the_screen_shows_is_found_there_and_can_be_pressed(helper):
    found = find(helper, text="Painted words")
    assert (found["count"], found["layer"], found["window"]) == (1, "screen", "")
    press(helper, text="Painted words")
    assert find(helper, text="Pressed once")["layer"] == "screen"


def test_words_that_are_nowhere_were_looked_for_in_both_places_and_the_nearest_are_offered(helper):
    reply = helper.request("find", limit=30, locator={"text": "Paintd wrds"}, timeout=1)
    assert (reply["count"], reply["tried"]) == (0, ["tree", "screen"])
    assert "Painted words" in reply["nearest"]


def test_a_screenshot_is_a_picture_of_the_monitor(helper, tmp_path):
    inside = helper.request("screenshot", limit=30)["path"]
    picture = tmp_path / "screen.png"
    helper.fetch(inside, picture)
    data = picture.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # The width and the height of a PNG are the two numbers after its first chunk's name.
    assert (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) == (1280, 720)
