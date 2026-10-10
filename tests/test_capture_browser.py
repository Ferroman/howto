import subprocess
import time

import pytest

from howto.capture import open_stage
from howto.errors import RunError
from howto.runner import run_probe
from howto.storyboard import Pace, parse
from howto.tools import find_tool

pytestmark = pytest.mark.browser

SETTINGS = {"click": {"role": "button", "name": "Settings"}}


def board(tmp_path, url, steps, **extra):
    return parse({"title": "Demo", "url": url, "steps": steps, **extra}, tmp_path / "demo.yaml")


def probe(tmp_path, site_url, steps, **extra):
    sb = board(tmp_path, f"{site_url}/index.html", steps, **extra)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        return run_probe(sb, stage)


def test_a_probe_reaches_the_last_page(chromium, site_url, tmp_path):
    result = probe(tmp_path, site_url, [
        {"do": [SETTINGS]},
        {"do": [
            {"fill": {"label": "Email address", "value": "sam@example.com"}},
            {"select": {"label": "Role", "option": "Admin"}},
            {"click": {"role": "button", "name": "Invite"}},
        ]},
        {"do": [{"wait_for": {"role": "heading", "name": "Invitation sent"}}]},
    ])
    assert result.failed is None
    assert 'heading "Invitation sent"' in result.page.outline
    assert "sam@example.com" in result.page.outline
    assert result.page.url.endswith("/done.html?email=sam%40example.com&role=Admin")
    assert result.page.title == "Demo - Done"


def test_a_missing_element_names_the_action(chromium, site_url, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")
    result = probe(tmp_path, site_url, [
        {"do": [SETTINGS]},
        {"do": [{"fill": {"label": "Email", "exact": True, "value": "sam@example.com"}}]},
    ])
    assert result.failed.index == 2
    assert result.failed.error == 'fill label="Email" exact value="sam@example.com": 0 elements match'
    assert 'textbox "Email address"' in result.page.outline


def test_an_ambiguous_locator_is_an_error(chromium, site_url, tmp_path):
    result = probe(tmp_path, site_url, [{"do": [SETTINGS, {"click": {"role": "button", "name": "Remove"}}]}])
    assert result.failed.error == 'click role=button name="Remove": 2 elements match'


def test_nth_and_within_pick_one_of_several(chromium, site_url, tmp_path):
    result = probe(tmp_path, site_url, [
        {"do": [SETTINGS, {"click": {"role": "button", "name": "Remove", "within": {"role": "listitem", "nth": 1}}}]},
        {"do": [{"click": {"role": "button", "name": "Remove", "nth": 0}}]},
    ])
    assert result.failed is None
    assert "bob@example.com" not in result.page.outline
    assert "ann@example.com" not in result.page.outline


def test_an_unknown_key_is_a_step_failure(chromium, site_url, tmp_path):
    result = probe(tmp_path, site_url, [{"do": [{"press": "NotAKey"}]}])
    assert result.failed.error.startswith("press NotAKey: ")


def test_recording_writes_a_video(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}], viewport="1280x720")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        stage.show_chapter("Invite a teammate", 0.3)
        stage.show_note('Use a <b>"work"</b> address')
        stage.perform(sb.steps[0].do[0], Pace())
        stage.hide_note()
        stage.stop_recording()
    assert video.stat().st_size > 1000


def test_a_missing_profile_is_explained(site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}], profile="nobody")
    with pytest.raises(RunError, match=f"howto login nobody {site_url}/index.html"):
        with open_stage(sb, profiles_dir=tmp_path / "profiles"):
            pass


def test_an_unreachable_start_page_is_explained(chromium, tmp_path):
    sb = board(tmp_path, "http://127.0.0.1:9/", [{"do": [SETTINGS]}])
    with pytest.raises(RunError, match="cannot open http://127.0.0.1:9/"):
        with open_stage(sb, profiles_dir=tmp_path / "profiles"):
            pass


def region(video, *, x, y, width, height):
    """The mean colour (r, g, b) of one region of the picture, for every frame of a video."""
    try:
        ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    except RunError:
        pytest.skip("ffmpeg is not installed")
    raw = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", str(video),
         "-vf", f"crop={width}:{height}:{x}:{y},scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]


def brightness(video, **where):
    return [sum(colour) / 3 for colour in region(video, **where)]


def test_a_hidden_note_leaves_the_picture(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}], viewport="1280x720")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        stage.show_note("Valid for seven days")
        time.sleep(0.8)
        stage.hide_note()
        time.sleep(0.8)
        stage.stop_recording()
    # The note is a dark box at the bottom centre, and the page is white there.
    levels = brightness(video, x=580, y=630, width=120, height=24)
    assert min(levels) < 120, "the note was never drawn"
    assert levels[-1] > 240, "the note is still in the last frame"


def record_a_click(site_url, tmp_path):
    """A take of one click on the Settings button. Returns the video and the point of the click."""
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}], viewport="1280x720")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        box = stage.page.get_by_role("button", name="Settings").bounding_box()
        stage.start_recording(video)
        stage.perform(sb.steps[0].do[0], Pace())
        time.sleep(0.5)
        stage.stop_recording()
    return video, (round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2))


def test_a_click_is_marked_on_the_picture(chromium, site_url, tmp_path):
    video, (x, y) = record_a_click(site_url, tmp_path)
    # Playwright marks the point of a click with a red dot. Nothing else on the page is red.
    around = region(video, x=x - 14, y=y - 14, width=28, height=28)
    assert max(red - green for red, green, _ in around) > 40


def test_an_action_draws_no_locator_label(chromium, site_url, tmp_path):
    video, _ = record_a_click(site_url, tmp_path)
    # Playwright would write `Click get_by_role("button", name="Settings")` in a
    # dark box in the top right corner. The page is white there.
    assert min(brightness(video, x=1060, y=14, width=200, height=28)) > 240


@pytest.mark.parametrize(
    "button, reason",
    [("Save", "element is not enabled"), ("Publish", "intercepts pointer events")],
)
def test_a_blocked_element_says_what_blocks_it(chromium, site_url, tmp_path, monkeypatch, button, reason):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")
    sb = board(tmp_path, f"{site_url}/blocked.html", [{"do": [{"click": {"role": "button", "name": button}}]}])
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert result.failed.error.startswith(f'click role=button name="{button}": Locator.click: Timeout 1000ms exceeded: ')
    assert result.failed.error.endswith(reason)


def test_a_dismissed_dialog_is_noted(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/popups.html", [{"do": [{"click": {"role": "button", "name": "Delete"}}]}])
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert result.failed is None
    assert result.page.notices == ('a confirm dialog was dismissed: "Delete this invitation?"',)
    # Dismissed means that nothing was deleted.
    assert 'heading "Popups"' in result.page.outline


def test_a_new_tab_is_noted(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/popups.html", [{"do": [{"click": {"role": "link", "name": "Open the report"}}]}])
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert result.failed is None
    assert result.page.notices == (f"a new tab opened and the steps stay in the first one: {site_url}/done.html",)
    assert result.page.url == f"{site_url}/popups.html"


def test_a_browser_that_goes_away_is_explained(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}])
    with pytest.raises(RunError, match="the browser stopped: "):
        with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
            stage.page.context.close()
            stage.start_recording(tmp_path / "take.webm")


def test_the_report_survives_a_page_that_is_gone(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS]}])
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.page.close()
        report = stage.report(None, 1000)
    assert report.outline.startswith("(no outline: ")
    assert report.title == ""
