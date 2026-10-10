import time

import pytest

from pictures import brightness, redness, region
from howto.capture import MARK_BUSY, open_stage
from howto.errors import RunError
from howto.runner import StepFailed, run_probe
from howto.storyboard import Action, Pace, parse
from howto.zoom import Box, frame, inside

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


def test_an_app_that_fills_the_window_is_zoomed_with_its_pinned_parts(chromium, site_url, tmp_path):
    sb, (corner,) = zoom_stage(tmp_path, site_url, "zoom.html", "Corner")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        status = stage.page.get_by_role("status")
        before = Box(**status.bounding_box())
        stage.zoom_to(corner, 2, False)
        after = Box(**status.bounding_box())
        notices = stage.report(None, 1000).notices
    # The message in the top right corner is enlarged with the page: it did not jump, and nothing was refused.
    assert close_to(after, frame(Box(1140, 660, 120, 40), VIEWPORT, 2).to_screen(before))
    assert notices == ()


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


SAVE = {"role": "button", "name": "Save"}
# Where each kind of mark puts its stroke for the Save button of marks.html,
# which is 160 by 40 pixels at (560, 340): a small region that the stroke crosses.
STROKES = {
    "box": dict(x=580, y=328, width=120, height=8),  # the top edge, 8 pixels above the button
    "circle": dict(x=508, y=350, width=20, height=20),  # where the loop passes on the left
    "underline": dict(x=580, y=380, width=120, height=14),
    "arrow": dict(x=760, y=352, width=100, height=30),  # the shaft, which comes from the right
}


def marks_take(tmp_path, site_url, page, do, *, note=None, after=None):
    """A take in which marks are drawn, shown for a moment and taken away. Returns the video."""
    sb = board(tmp_path, f"{site_url}/{page}", [{"do": do}], viewport="1280x720")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        if note:
            stage.show_note(note)
        time.sleep(0.5)
        for action in sb.steps[0].do:
            stage.mark(action, True)
        time.sleep(0.5)
        if after:
            after(stage)
        stage.clear_marks(True)
        time.sleep(0.5)
        stage.stop_recording()
    return video


@pytest.mark.parametrize("kind", ["box", "circle", "underline", "arrow"])
def test_a_mark_is_drawn_at_its_target_and_goes_again(chromium, site_url, tmp_path, kind):
    video = marks_take(tmp_path, site_url, "marks.html", [{kind: SAVE}])
    stroke = redness(video, **STROKES[kind])
    assert stroke[0] < 5, "the take starts with the mark"
    assert max(stroke) > 20, "the mark is not in the picture"
    assert stroke[-1] < 5, "the mark is still in the last frame"
    # The mark is beside the control, never on it.
    assert max(redness(video, x=600, y=350, width=80, height=20)) < 5


def test_a_stroke_is_drawn_and_does_not_just_appear(chromium, site_url, tmp_path):
    video = marks_take(tmp_path, site_url, "marks.html", [{"box": SAVE}])
    stroke = redness(video, **STROKES["box"])
    full = max(stroke)
    drawn = stroke[: stroke.index(full)]
    assert any(5 < level < 0.8 * full for level in drawn), "the stroke is a cut, not a movement"


def test_a_spotlight_darkens_everything_but_its_target(chromium, site_url, tmp_path):
    video = marks_take(tmp_path, site_url, "marks.html", [{"spotlight": SAVE}])
    elsewhere = brightness(video, x=900, y=560, width=60, height=60)  # white page
    target = brightness(video, x=600, y=350, width=80, height=20)  # the face of the button
    assert elsewhere[0] > 240 and elsewhere[-1] > 240
    assert min(elsewhere) < 140, "the page did not go dark"
    assert min(target) > target[0] - 10, "the target went dark with the page"


def test_a_note_stays_bright_under_a_spotlight(chromium, site_url, tmp_path):
    video = marks_take(tmp_path, site_url, "marks.html", [{"spotlight": SAVE}], note="Valid for seven days")
    # The note is a dark box at the bottom centre. Next to it the page is white.
    page = brightness(video, x=100, y=630, width=120, height=24)
    note = brightness(video, x=580, y=630, width=120, height=24)
    assert min(page) < 140, "the page did not go dark"
    shown = [level for level in note if level < 200]  # the frames in which the note is there
    # The note lets a little of the page through, so it darkens a little with
    # it, to about 0.8 of what it was. Under the spotlight it would be at 0.45.
    assert min(shown) > 0.7 * shown[0], "the spotlight lies on top of the note"


def test_an_arrow_comes_from_a_side_that_is_free(chromium, site_url, tmp_path):
    # The Lonely button is at the left edge, so the arrow would come from the
    # right, where a block of text is. Below it is another button.
    video = marks_take(tmp_path, site_url, "marks.html", [{"arrow": {"role": "button", "name": "Lonely"}}])
    assert max(redness(video, x=155, y=190, width=25, height=120)) > 15, "no arrow from above"
    assert max(redness(video, x=250, y=345, width=130, height=30)) < 5, "the arrow lies across the text"


def test_the_words_of_an_arrow_are_in_the_picture(chromium, site_url, tmp_path):
    video = marks_take(tmp_path, site_url, "marks.html", [{"arrow": {**SAVE, "note": "Keeps your changes"}}])
    # The tail is at (884, 360), and the words hang on it in a red box.
    words = redness(video, x=900, y=352, width=30, height=16)
    assert max(words) > 100 and words[-1] < 5


def test_a_mark_lands_on_its_target_while_the_page_is_zoomed(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/zoom.html", [{"do": [{"box": {"role": "button", "name": "Corner"}}]}], viewport="1280x720")
    (box,) = sb.steps[0].do
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        stage.zoom_to(box, 2, True)
        stage.mark(box, True)
        time.sleep(0.4)
        stage.clear_marks(True)
        stage.zoom_out(True)
        stage.stop_recording()
    # Enlarged, the Corner button is 240 by 80 pixels at (1000, 600). The top edge of its box is 8 pixels above.
    assert max(redness(video, x=1040, y=588, width=160, height=8)) > 20
    # At the page's own size the button is at (1140, 660), and nothing was drawn there.
    assert max(redness(video, x=1150, y=648, width=80, height=8)) < 5


def test_the_picture_holds_still_under_a_mark_while_the_next_target_is_in_it(chromium, site_url, tmp_path):
    sb = board(
        tmp_path,
        f"{site_url}/zoom.html",
        [{"do": [{"box": {"role": "button", "name": "Centre"}}, {"click": {"css": "#red"}}, button("Corner")]}],
        viewport="1280x720",
    )
    box, near, far = sb.steps[0].do
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        stage.start_recording(video)
        stage.zoom_to(box, 2, False)
        stage.mark(box, True)
        # The red block is in the picture already. Moving to it would leave the box behind.
        stage.zoom_to(near, 2, False)
        assert close_to(box_of(stage, "Centre"), Box(520, 320, 240, 80))
        time.sleep(0.3)
        # The Corner button is not, so the picture has to move, and the box cannot come along.
        stage.zoom_to(far, 2, True)
        assert close_to(box_of(stage, "Corner"), Box(1000, 600, 240, 80))
        time.sleep(0.3)
        stage.stop_recording()
    # The top edge of the box around the enlarged Centre button.
    edge = redness(video, x=560, y=308, width=160, height=8)
    assert max(edge) > 20, "the box was never drawn"
    assert edge[-1] < 5, "the box stayed where it was while the picture moved"


def test_marks_do_not_outlive_the_page_they_were_drawn_on(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/index.html", [{"do": [{"box": {"role": "button", "name": "Settings"}}, SETTINGS]}], viewport="1280x720")
    box, click = sb.steps[0].do
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        at = box_of(stage, "Settings")
        stage.start_recording(video)
        stage.mark(box, True)
        time.sleep(0.3)
        stage.perform(click, Pace())
        stage.clear_marks(True)
        stage.page.wait_for_url("**/settings.html")
        time.sleep(0.5)
        stage.stop_recording()
    edge = redness(video, x=round(at.x), y=round(at.y) - 12, width=round(at.width), height=8)
    assert max(edge) > 20, "the box was never drawn"
    assert edge[-1] < 5, "the box is drawn on the next page"


def test_a_mark_brings_its_target_into_view(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/marks.html", [{"do": [{"circle": {"role": "button", "name": "Far"}}]}], viewport="1280x720")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        assert box_of(stage, "Far").y > 720
        stage.mark(sb.steps[0].do[0], False)
        after = box_of(stage, "Far")
    assert 0 <= after.y and after.y + after.height <= 720


def test_taking_the_marks_away_leaves_the_page_as_it_was(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/zoom.html", [{"do": [{"circle": {"role": "button", "name": "Centre"}}]}], viewport="1280x720")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        styles = stage.page.evaluate(STYLES)
        stage.start_recording(tmp_path / "take.webm")
        stage.mark(sb.steps[0].do[0], True)
        stage.clear_marks(True)
        stage.stop_recording()
        assert stage.page.evaluate(STYLES) == styles


def test_a_probe_looks_for_the_element_of_each_mark(chromium, site_url, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")

    def outcome(mark):
        sb = board(tmp_path, f"{site_url}/settings.html", [{"do": [mark]}])
        with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
            return run_probe(sb, stage).failed

    assert outcome({"arrow": {"role": "button", "name": "Invite", "note": "Sends the email"}}) is None
    assert outcome({"circle": {"role": "button", "name": "Remove"}}).error == 'circle role=button name="Remove": 2 elements match'
    assert outcome({"box": {"role": "button", "name": "Nope"}}).error == 'box role=button name="Nope": 0 elements match'


ANN = {"text": "ann@example.com"}


def test_a_mark_on_a_line_of_text_keeps_to_the_text(chromium, site_url, tmp_path):
    # The list item with Ann's address is as wide as the page, and its text is not.
    sb = board(tmp_path, f"{site_url}/settings.html", [{"do": [{"circle": ANN}]}], viewport="1280x720")
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        row = Box(**stage.page.get_by_text("ann@example.com").bounding_box())
        assert row.width > 1000
        stage.start_recording(video)
        stage.mark(sb.steps[0].do[0], True)
        time.sleep(0.4)
        stage.stop_recording()
    band = dict(y=round(row.y) - 40, height=round(row.height) + 80)
    assert max(redness(video, x=0, width=320, **band)) > 5, "no circle at the text"
    assert max(redness(video, x=640, width=600, **band)) < 5, "the circle runs across the page"


def test_a_block_with_a_colour_of_its_own_is_marked_as_a_whole(chromium, site_url, tmp_path):
    # The block of text on marks.html is 260 by 420 pixels at (240, 150), and its one line of text is at the top.
    video = marks_take(tmp_path, site_url, "marks.html", [{"box": {"text": "Notes about the team."}}])
    assert max(redness(video, x=228, y=300, width=8, height=200)) > 20, "the box does not follow the block's edge"


def test_the_zoom_is_aimed_at_the_text_of_a_mark(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/settings.html", [{"do": [{"circle": ANN}]}], viewport="1280x720")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        before = box_of(stage, "Invite")
        # A row as wide as the page cannot be enlarged. Its text can.
        stage.zoom_to(sb.steps[0].do[0], 2, False)
        assert box_of(stage, "Invite").width == pytest.approx(2 * before.width, abs=1)


PANEL = {"role": "complementary", "name": "Style"}
# The panel of panel.html is 300 by 400 pixels at (960, 100). With the margin
# of a crop, the picture ends 8 pixels from the right edge of the window.
PANEL_CROP = Box(948, 88, 324, 424)
EDGE = {"role": "button", "name": "Edge"}
OUTSIDE = {"role": "button", "name": "Outside"}


def crop_action(sb):
    return Action(kind="crop", locator=sb.crop)


def panel_take(tmp_path, site_url, do, *, crop=PANEL, note=None):
    """A take of panel.html with a note and marks, cut to the panel or not. Returns the video.

    The note is shown a moment after the take begins, so the first frames are without it.
    """
    extra = {"crop": crop} if crop else {}
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": do}], viewport="1280x720", **extra)
    video = tmp_path / "take.webm"
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        if crop:
            stage.crop_to(crop_action(sb), (note,) if note else ())
        stage.start_recording(video)
        time.sleep(0.4)
        if note:
            stage.show_note(note)
        for action in sb.steps[0].do:
            stage.mark(action, True)
        time.sleep(0.6)
        stage.stop_recording()
    return video


def test_a_crop_is_its_element_with_a_margin(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"click": EDGE}]}], viewport="1280x720", crop=PANEL)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        assert stage.crop_to(crop_action(sb), ()) == PANEL_CROP


def test_a_crop_with_notes_grows_by_a_strip_under_it(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"click": EDGE}]}], viewport="1280x720", crop=PANEL)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        cut = stage.crop_to(crop_action(sb), ("Valid for seven days",))
        # One line of 18 pixels with its padding. The crop itself is as before.
        assert (cut.x, cut.y, cut.width) == (PANEL_CROP.x, PANEL_CROP.y, PANEL_CROP.width)
        assert 40 <= cut.height - PANEL_CROP.height <= 50
        long = stage.crop_to(crop_action(sb), ("Short", "A note of many words that cannot fit on one line of a narrow panel " * 2))
        assert long.height - PANEL_CROP.height > 90, "the strip is not as tall as its longest note"


def test_the_strip_goes_above_a_crop_at_the_bottom_of_the_window(chromium, site_url, tmp_path):
    low = {"role": "button", "name": "Low"}  # 100 by 40 pixels at (100, 660)
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"click": low}]}], viewport="1280x720", crop=low)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        cut = stage.crop_to(crop_action(sb), ("Hi",))
        assert (cut.x, cut.width, cut.y + cut.height) == (88, 124, 712)
        assert 40 <= 648 - cut.y <= 50


def test_a_crop_that_is_out_of_sight_is_scrolled_to(chromium, site_url, tmp_path):
    far = {"role": "button", "name": "Far"}  # 1500 pixels down the page
    sb = board(tmp_path, f"{site_url}/marks.html", [{"do": [{"click": far}]}], viewport="1280x720", crop=far)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        cut = stage.crop_to(crop_action(sb), ())
        assert inside(cut, Box(0, 0, 1280, 720))
        assert inside(Box(**stage.page.get_by_role("button", name="Far").bounding_box()), cut)


@pytest.mark.parametrize(
    "crop, reason",
    [
        ({"role": "button", "name": "Nope"}, "0 elements match"),
        ({"role": "button"}, "4 elements match"),
    ],
)
def test_a_crop_names_one_element(chromium, site_url, tmp_path, monkeypatch, crop, reason):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"click": EDGE}]}], crop=crop)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        with pytest.raises(StepFailed) as caught:
            stage.crop_to(crop_action(sb), ("A note",))
    assert str(caught.value) == f"{crop_action(sb).describe()}: {reason}"


def test_a_note_is_written_in_the_strip_and_leaves_the_crop_clear(chromium, site_url, tmp_path):
    video = panel_take(tmp_path, site_url, [], note="Valid for seven days")
    # The strip is the 46 pixels under the crop, which ends at y = 512. It is
    # dark before any note is shown, so that the page under it never shows.
    # Only the recorder's first frames, 0.2 s that a picture leaves out, come
    # before the strip is drawn.
    edge = brightness(video, x=952, y=520, width=16, height=30)
    assert max(edge[5:]) < 60, "the strip is not there for the whole take"
    words = brightness(video, x=1040, y=522, width=140, height=26)
    assert words[5] < 60 and max(words) > words[5] + 10, "no words in the strip"
    # The panel itself, down to its lower edge, is never covered.
    assert min(brightness(video, x=1000, y=440, width=200, height=56)) > 225
    # Where a note lies in a picture of the whole window, the page stays white.
    assert min(brightness(video, x=580, y=630, width=120, height=24)) > 240


def test_a_crop_as_tall_as_the_window_has_its_note_on_its_lowest_part(chromium, site_url, tmp_path):
    video = panel_take(tmp_path, site_url, [], crop={"css": "#app"}, note="Valid for seven days")
    # No room under the window or above it. The strip is there only while the note is.
    lowest = brightness(video, x=20, y=685, width=40, height=25)
    assert lowest[0] > 240, "the strip covers the page before any note is shown"
    assert min(lowest) < 60, "no strip at the bottom of the crop"


def test_a_note_lies_at_the_bottom_of_the_window_without_a_crop(chromium, site_url, tmp_path):
    video = panel_take(tmp_path, site_url, [], crop=None, note="Valid for seven days")
    assert min(brightness(video, x=580, y=630, width=120, height=24)) < 120
    # No strip under the panel, and none at the left of the window's lower edge.
    assert min(brightness(video, x=952, y=520, width=16, height=30)) > 240
    assert min(brightness(video, x=20, y=685, width=40, height=25)) > 240


def test_an_arrow_stays_inside_the_crop(chromium, site_url, tmp_path):
    video = panel_take(tmp_path, site_url, [{"arrow": EDGE}])
    assert max(redness(video, x=1100, y=300, width=100, height=40)) > 15, "no arrow from inside the panel"
    assert max(redness(video, x=800, y=290, width=140, height=60)) < 5, "the arrow comes from outside the picture"


def test_a_point_outside_the_picture_is_no_place_for_an_arrow(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"click": EDGE}]}], viewport="1280x720")
    open_page, in_panel = [[700, 400]], [[1100, 400]]  # both on an empty background
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        cut = [PANEL_CROP.x, PANEL_CROP.y, PANEL_CROP.x + PANEL_CROP.width, PANEL_CROP.y + PANEL_CROP.height]
        assert stage.page.evaluate(MARK_BUSY, [[open_page, in_panel], cut]) == [1, 0]
        assert stage.page.evaluate(MARK_BUSY, [[open_page, in_panel], [0, 0, 1280, 720]]) == [0, 0]


def test_without_a_crop_the_same_arrow_comes_from_the_open_page(chromium, site_url, tmp_path):
    video = panel_take(tmp_path, site_url, [{"arrow": EDGE}], crop=None)
    assert max(redness(video, x=800, y=290, width=140, height=60)) > 15


def test_a_probe_reports_the_crop_and_what_it_leaves_out(chromium, site_url, tmp_path):
    steps = [{"do": [{"click": EDGE}, {"box": OUTSIDE}, {"click": OUTSIDE}, {"hover": OUTSIDE}, {"click": OUTSIDE}]}]
    sb = board(tmp_path, f"{site_url}/panel.html", steps, viewport="1280x720", crop=PANEL)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert result.failed is None
    assert result.crop == PANEL_CROP
    assert result.page.notices == (
        'box role=button name="Outside": the element is not inside the crop',
        'click role=button name="Outside": the element is not inside the crop',
        'hover role=button name="Outside": the element is not inside the crop',
    )


def test_a_probe_reports_the_picture_with_the_strip_for_its_notes(chromium, site_url, tmp_path):
    steps = [{"note": "Press Edge", "do": [{"click": EDGE}]}]
    sb = board(tmp_path, f"{site_url}/panel.html", steps, viewport="1280x720", crop=PANEL)
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert (result.crop.x, result.crop.y, result.crop.width) == (948, 88, 324)
    assert result.crop.height > PANEL_CROP.height + 40
    # The strip is part of the picture, and no place for an action: the click is still inside the crop.
    assert result.page.notices == ()


def test_a_probe_without_a_crop_leaves_nothing_out(chromium, site_url, tmp_path):
    sb = board(tmp_path, f"{site_url}/panel.html", [{"do": [{"box": OUTSIDE}, {"click": OUTSIDE}]}], viewport="1280x720")
    with open_stage(sb, profiles_dir=tmp_path / "profiles") as stage:
        result = run_probe(sb, stage)
    assert (result.crop, result.page.notices) == (None, ())
