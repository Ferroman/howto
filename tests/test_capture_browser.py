import subprocess
import time

import pytest

from howto.capture import open_stage
from howto.errors import RunError
from howto.runner import run_probe
from howto.storyboard import Pace, parse
from howto.tools import find_tool
from howto.zoom import Box, frame

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


VIEWPORT = (1280, 720)


def button(name):
    return {"click": {"role": "button", "name": name}}


def zoom_stage(tmp_path, site_url, page, *names):
    """A storyboard of one step that clicks the named buttons of a page, and its actions."""
    sb = board(tmp_path, f"{site_url}/{page}", [{"do": [button(name) for name in names]}], viewport="1280x720")
    return sb, sb.steps[0].do


def box_of(stage, name):
    return Box(**stage.page.get_by_role("button", name=name).bounding_box())


def close_to(box, expected):
    return (box.x, box.y, box.width, box.height) == pytest.approx(
        (expected.x, expected.y, expected.width, expected.height), abs=1
    )


def test_a_zoom_puts_the_target_where_the_arithmetic_says(chromium, site_url, tmp_path):
    # This page is plain text flow with a margin around the body, so the
    # body's corner is not the corner of the window.
    sb, (invite,) = zoom_stage(tmp_path, site_url, "settings.html", "Invite")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        before = box_of(stage, "Invite")
        stage.zoom_to(invite, 2, False)
        after = box_of(stage, "Invite")
    assert close_to(after, frame(before, VIEWPORT, 2).to_screen(before))
    assert after.width == pytest.approx(2 * before.width, abs=1)


def test_a_target_in_the_corner_stays_in_the_picture(chromium, site_url, tmp_path):
    sb, (corner,) = zoom_stage(tmp_path, site_url, "zoom.html", "Corner")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.zoom_to(corner, 2, False)
        after = box_of(stage, "Corner")
    assert close_to(after, Box(1000, 600, 240, 80))


def test_the_picture_moves_from_one_target_to_the_next(chromium, site_url, tmp_path):
    sb, (centre, corner) = zoom_stage(tmp_path, site_url, "zoom.html", "Centre", "Corner")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.zoom_to(centre, 2, False)
        assert close_to(box_of(stage, "Centre"), Box(520, 320, 240, 80))
        stage.zoom_to(corner, 2, False)
        assert close_to(box_of(stage, "Corner"), Box(1000, 600, 240, 80))


def test_an_action_lands_on_its_target_while_the_page_is_zoomed(chromium, site_url, tmp_path):
    sb, (corner,) = zoom_stage(tmp_path, site_url, "zoom.html", "Corner")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.zoom_to(corner, 2, False)
        stage.perform(corner, Pace())
        assert stage.page.title() == "Corner was clicked"


STYLES = "() => [document.body.style.cssText, document.documentElement.style.cssText, typeof window.__howtoZoom]"


def test_zooming_out_gives_the_page_its_own_styles_back(chromium, site_url, tmp_path):
    sb, (centre,) = zoom_stage(tmp_path, site_url, "zoom.html", "Centre")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        styles, box = stage.page.evaluate(STYLES), box_of(stage, "Centre")
        assert styles == ["color: rgb(34, 34, 34);", "", "undefined"]
        stage.zoom_to(centre, 2, False)
        assert stage.page.evaluate(STYLES) != styles
        stage.zoom_out(False)
        assert stage.page.evaluate(STYLES) == styles
        assert box_of(stage, "Centre") == box


def test_a_target_out_of_sight_is_scrolled_to_before_the_zoom(chromium, site_url, tmp_path):
    sb, (centre, below) = zoom_stage(tmp_path, site_url, "zoom.html", "Centre", "Below")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.zoom_to(centre, 2, False)
        stage.zoom_to(below, 2, False)
        after = box_of(stage, "Below")
        stage.perform(below, Pace())
        assert stage.page.title() == "Below was clicked"
    assert (after.width, after.height) == pytest.approx((240, 80), abs=1)
    assert after.x >= 0 and after.y >= 0 and after.x + after.width <= 1280 and after.y + after.height <= 720


def test_a_page_with_pinned_parts_stays_wide_and_the_probe_says_so(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/pinned.html", [{"do": [button("Save"), button("Help")]}], viewport="1280x720", zoom=2)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        before = box_of(stage, "Help")
        stage.zoom_to(sb.steps[0].do[0], 2, False)
        assert stage.page.evaluate(STYLES) == ["", "", "undefined"]
        assert box_of(stage, "Help") == before
        result = run_probe(sb, stage)
        assert stage.page.title() == "Help was clicked"
    assert result.failed is None
    assert result.page.notices == (
        f"zoom is skipped on {site_url}/pinned.html: it would move parts of the page that are pinned to the window",
    )


def test_a_page_that_replaced_itself_starts_wide(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [SETTINGS, button("Invite")]}], viewport="1280x720")
    settings, invite = sb.steps[0].do
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.zoom_to(settings, 2, True)
        stage.perform(settings, Pace())
        stage.page.wait_for_url("**/settings.html")
        started = time.monotonic()
        stage.zoom_out(True)
        # Nothing is zoomed on the new page, so there is no movement to wait for.
        assert time.monotonic() - started < 0.5
        before = box_of(stage, "Invite")
        stage.zoom_to(invite, 2, False)
        assert box_of(stage, "Invite").width == pytest.approx(2 * before.width, abs=1)


def redness(video, **where):
    return [red - green for red, green, _ in region(video, **where)]


def test_a_take_shows_the_zoom_and_the_way_back(chromium, site_url, tmp_path):
    sb, (centre,) = zoom_stage(tmp_path, site_url, "zoom.html", "Centre")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        time.sleep(0.4)
        stage.zoom_to(centre, 2, True)
        time.sleep(0.4)
        stage.zoom_out(True)
        time.sleep(0.4)
        stage.stop_recording()
    # Twice as large around the Centre button, the red block covers this
    # spot. At the page's own size the spot is white.
    spot = redness(video, x=690, y=250, width=20, height=20)
    assert spot[0] < 20, "the take starts zoomed"
    assert max(spot) > 150, "the zoom is not in the picture"
    assert spot[-1] < 20, "the take ends zoomed"
    # The way in takes time: some frames are neither wide nor fully zoomed.
    assert 0 < spot.index(max(spot)), "the zoom is a cut, not a movement"


def test_a_click_is_marked_where_the_zoomed_target_is(chromium, site_url, tmp_path):
    sb, (corner,) = zoom_stage(tmp_path, site_url, "zoom.html", "Corner")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        stage.zoom_to(corner, 2, True)
        stage.perform(corner, Pace())
        time.sleep(0.5)
        stage.stop_recording()
    # Enlarged, the Corner button is centred on (1120, 640). Playwright's red dot must be there.
    assert max(redness(video, x=1106, y=626, width=28, height=28)) > 40
