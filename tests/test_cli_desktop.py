"""`howto probe` on a desktop storyboard, from the command to the report. These tests need Docker and the base image."""
import json
import subprocess
import uuid

import pytest
import yaml

from pictures import brightness, dimensions, psnr, redness, still
from howto import cli
from howto.assemble import video_duration
from howto.desktop import profiles, stage, takelog, viewer
from howto.desktop.link import open_link
from howto.desktop.stage import PRESS
from howto.errors import RunError
from howto.tools import find_tool

pytestmark = pytest.mark.desktop

STEPS = [
    {"do": [{"fill": {"label": "Name", "value": "sam"}}, {"select": {"label": "Role", "option": "Admin"}}]},
    {"do": [{"click": {"role": "button", "name": "Add"}}, {"wait_for": {"text": "Added sam"}}]},
    {"do": [{"click": {"role": "menu", "name": "File"}}, {"click": {"role": "menuitem", "name": "About"}}]},
    {"do": [{"click": {"role": "button", "name": "Close"}}]},
]


def write_board(tmp_path, desktop, steps, **extra):
    data = {
        "title": "Add a name",
        "app": {"image": desktop.image, "run": desktop.run},
        "viewport": "1280x720",
        "steps": steps,
        **extra,
    }
    path = tmp_path / "videos" / "add.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_a_probe_of_a_correct_storyboard(desktop, sandbox, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, desktop, STEPS))]) == 0
    out = capsys.readouterr().out
    assert "step 4 ok      click role=button name=\"Close\"" in out
    assert f'page: app {desktop.run}  "Fixture"' in out
    assert '- frame "Fixture" [active]:' in out
    assert '- label "sam, Admin"' in out and '- label "Added sam"' in out
    assert "note:" not in out


def test_a_probe_names_the_step_with_the_wrong_name_and_offers_the_right_one(desktop, sandbox, tmp_path, capsys, monkeypatch):
    # Three seconds for an element, and so nine for the app's first window.
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "3")
    steps = [STEPS[0], {"do": [{"click": {"role": "button", "name": "Addd"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 1
    out = capsys.readouterr().out
    assert "step 1 ok" in out
    assert 'step 2 FAILED  click role=button name="Addd": not in the tree. The nearest names: "Add"' in out
    assert '- button "Add"' in out


def test_a_probe_stops_where_until_says_and_shows_a_dialog_as_a_second_window(desktop, sandbox, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, desktop, STEPS)), "--until", "3"]) == 0
    out = capsys.readouterr().out
    assert '- dialog "About Fixture"' in out and '- frame "Fixture"' in out
    assert "step 4" not in out


def test_within_limits_the_outline_to_one_element(desktop, sandbox, tmp_path, capsys):
    arguments = ["probe", str(write_board(tmp_path, desktop, STEPS)), "--until", "3", "--within", "{role: dialog}"]
    assert cli.main(arguments) == 0
    out = capsys.readouterr().out
    assert '- dialog "About Fixture"' in out and '- frame "Fixture"' not in out


def test_setup_and_cleanup_run_commands_in_the_container(desktop, sandbox, tmp_path, capsys):
    path = write_board(
        tmp_path, desktop, [{"do": [{"wait_for": {"role": "button", "name": "Add"}}]}],
        setup=[{"run": "echo made > /home/howto/note.txt"}],
        cleanup=[{"run": "test -f /home/howto/note.txt && rm /home/howto/note.txt"}, {"run": "test -f /home/howto/note.txt"}],
    )
    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    # The first cleanup found the file that setup made and removed it. The second then found none.
    assert "warning: cleanup[2]: run test -f /home/howto/note.txt: it ended with exit code 1" in out
    assert "cleanup[1]" not in out


def test_an_app_that_does_not_start_exits_1_with_what_it_said(desktop, sandbox, tmp_path, capsys):
    path = write_board(tmp_path, desktop, STEPS[:1])
    path.write_text(path.read_text().replace(desktop.run, "no-such-app --now"), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 1
    err = capsys.readouterr().err
    assert "howto: the app ended with exit code 127" in err and "no-such-app" in err


def test_an_image_that_does_not_exist_exits_1_with_the_command_that_builds_it(desktop, sandbox, tmp_path, capsys):
    path = write_board(tmp_path, desktop, STEPS[:1])
    path.write_text(path.read_text().replace(desktop.image, "howto-no-such-image"), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 1
    assert "the image howto-no-such-image does not exist: run `docker build -t howto-no-such-image DIR`" in capsys.readouterr().err


@pytest.fixture
def real_ffmpeg(monkeypatch):
    monkeypatch.delenv("HOWTO_FFMPEG", raising=False)
    monkeypatch.delenv("HOWTO_FFPROBE", raising=False)
    try:
        return find_tool("ffmpeg", "HOWTO_FFMPEG"), find_tool("ffprobe", "HOWTO_FFPROBE")
    except RunError:
        pytest.skip("ffmpeg is not installed")


def whole(video):
    """The brightness of the whole picture of 1280x720, for every frame."""
    return brightness(video, x=0, y=0, width=1280, height=720)


def test_a_render_gives_a_narrated_video_of_the_app(desktop, chromium, fake_tts, real_ffmpeg, sandbox, tmp_path):
    _, ffprobe = real_ffmpeg
    steps = [
        {"chapter": "Add a name"},
        {"say": "Type a name.", "note": "Any name will do, as long as it is a short one.",
         "do": [{"fill": {"label": "Name", "value": "sam"}}]},
        {"say": "Then press Add.", "do": [{"click": {"role": "button", "name": "Add"}}]},
    ]
    path = write_board(tmp_path, desktop, steps)
    assert cli.main(["render", str(path), "--keep-work"]) == 0
    video = path.parent / "add.mp4"
    assert dimensions(ffprobe, video) == (1280, 720)
    (work,) = sandbox.work.iterdir()
    timeline = json.loads((work / "timeline.json").read_text())
    assert video_duration(ffprobe, video) == pytest.approx(timeline["video_duration"], abs=0.1)
    assert (path.parent / "add.srt").read_text().count(" --> ") == 2
    log = takelog.read(work / "take.json")
    assert [shown.kind for shown in log.shown] == ["card", "click", "note", "click"]
    assert 0.0 < log.head < 5.0
    # The app paints that part of its window white. The title card is dark, with white words, in the middle of it.
    middle = brightness(video, x=560, y=335, width=160, height=50)
    assert middle[25] < 180 and middle[-1] > 200
    # The note lies at the bottom while its step lasts, and is gone at the end.
    second = timeline["steps"][1]
    bottom = brightness(video, x=560, y=625, width=160, height=40)
    assert bottom[round((second["start"] + 1.0) * 25)] < 180 and bottom[-1] > 200


def test_the_picture_of_a_desktop_video_is_within_a_tenth_of_a_second_of_its_timeline(
    desktop, chromium, fake_tts, real_ffmpeg, sandbox, tmp_path
):
    steps = [{"say": "Press Flash.", "do": [{"click": {"role": "button", "name": "Flash"}}], "pause": 1}]
    path = write_board(tmp_path, desktop, steps)
    assert cli.main(["render", str(path), "--keep-work"]) == 0
    (work,) = sandbox.work.iterdir()
    (ring,) = takelog.read(work / "take.json").shown
    # The painted part of the window turns from white to black when the button is let go.
    levels = whole(path.parent / "add.mp4")
    turned = next(index for index, level in enumerate(levels) if level < levels[0] - 40) / 25
    assert turned == pytest.approx(ring.start + PRESS, abs=0.1)


def test_a_failed_step_of_a_desktop_take_writes_no_video(desktop, chromium, fake_tts, real_ffmpeg, sandbox, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "3")
    steps = [{"say": "Press Remove.", "do": [{"click": {"role": "button", "name": "Remove"}}]}]
    path = write_board(tmp_path, desktop, steps)
    assert cli.main(["render", str(path)]) == 1
    assert 'howto: step 1: click role=button name="Remove": not in the tree' in capsys.readouterr().err
    assert not (path.parent / "add.mp4").exists()
    assert list(sandbox.work.iterdir()) == []


def test_a_probe_prints_the_words_that_the_outline_lacks_and_saves_a_screenshot(desktop, sandbox, tmp_path, capsys):
    steps = [{"do": [{"wait_for": {"role": "button", "name": "Add"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 0
    out = capsys.readouterr().out
    assert "words on the screen that the outline lacks:\n" in out
    (line,) = [line for line in out.splitlines() if line.startswith('- "Painted words" {at: ')]
    assert " size: " in line and line.endswith("}")
    shot = sandbox.cache / "probe" / "add.png"
    assert out.rstrip().endswith(f"screenshot: {shot}")
    assert shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_locator_that_the_probe_printed_names_the_same_place(desktop, sandbox, tmp_path, capsys):
    steps = [{"do": [{"wait_for": {"role": "button", "name": "Add"}}]}]
    path = write_board(tmp_path, desktop, steps)
    assert cli.main(["probe", str(path)]) == 0
    (line,) = [line for line in capsys.readouterr().out.splitlines() if line.startswith('- "Painted words" ')]
    # The author copies the locator as it stands: {at: XxY, size: WxH}.
    place = yaml.safe_load(line.split('" ', 1)[1])
    steps.append({"do": [{"click": place}, {"wait_for": {"text": "Pressed once"}}]})
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 0
    assert '- "Pressed once" {at: ' in capsys.readouterr().out


def test_words_on_the_screen_are_named_as_text(desktop, sandbox, tmp_path, capsys):
    steps = [{"do": [{"click": {"text": "Painted words"}}, {"wait_for": {"text": "Pressed once"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 0
    assert "step 1 ok" in capsys.readouterr().out


def test_words_that_are_nowhere_fail_the_step_with_the_nearest_words(desktop, sandbox, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "3")
    steps = [{"do": [{"click": {"text": "Paintd wrds"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 1
    out = capsys.readouterr().out
    assert 'step 1 FAILED  click text="Paintd wrds": not in the tree, and no such words on the screen. The nearest words: ' in out
    assert '"Painted words"' in out.split("The nearest words: ")[1].splitlines()[0]


def test_an_app_that_publishes_no_tree_is_probed_through_its_screen(desktop, sandbox, tmp_path, capsys):
    # NO_AT_BRIDGE keeps a GTK 3 app from publishing its tree, as an app with a toolkit of its own would not.
    steps = [{"do": [{"click": {"text": "Painted words"}}, {"wait_for": {"text": "Pressed once"}}]}]
    path = write_board(tmp_path, desktop, steps)
    path.write_text(path.read_text().replace(desktop.run, f"NO_AT_BRIDGE=1 {desktop.run}"), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    assert "step 1 ok" in out
    assert "outline:\n(nothing is showing)\n" in out
    assert '- "Pressed once" {at: ' in out



def test_a_zoom_shows_a_cut_of_the_larger_recording_and_goes_wide_again(
    desktop, chromium, fake_tts, real_ffmpeg, sandbox, tmp_path
):
    ffmpeg, ffprobe = real_ffmpeg
    steps = [{"say": "Press Flash.", "do": [{"click": {"role": "button", "name": "Flash"}}], "pause": 1}]
    path = write_board(tmp_path, desktop, steps, zoom=2)
    assert cli.main(["render", str(path), "--keep-work"]) == 0
    video = path.parent / "add.mp4"
    (work,) = sandbox.work.iterdir()
    log = takelog.read(work / "take.json")
    assert dimensions(ffprobe, video) == (1280, 720) and dimensions(ffprobe, work / "capture.mkv") == (2560, 1440)
    assert log.scale == 2
    into, out = log.moves
    assert into.factor == 2.0 and (out.left, out.top, out.factor) == (0.0, 0.0, 1.0)

    def compare(at, cut):
        ours = still(ffmpeg, video, at, tmp_path / "ours.png")
        theirs = still(ffmpeg, work / "capture.mkv", log.head + at, tmp_path / "theirs.png", cut)
        return psnr(ffmpeg, ours, theirs)

    # Before the move the picture is the whole recording at half its size.
    whole = "scale=1280:720:flags=bicubic"
    assert compare(into.start - 0.2, whole) > 30
    # Enlarged, it is a part of the recording at the recording's own size. `zoompan` cuts at even pixels.
    # The ring of the click has gone by then.
    left, top = (int(value * 2) // 2 * 2 for value in (into.left, into.top))
    assert compare(out.start - 0.1, f"crop=1280:720:{left}:{top}") > 30
    assert compare(out.start - 0.1, whole) < 25
    # And wide again at the end.
    assert compare(out.start + out.seconds + 0.3, whole) > 30


def test_a_probe_names_what_the_crop_leaves_out(desktop, sandbox, tmp_path, capsys):
    steps = [{"do": [{"click": {"role": "button", "name": "Flash"}}, {"circle": {"text": "Painted words"}}]}]
    path = write_board(tmp_path, desktop, steps, crop={"role": "textbox", "name": "Name"})
    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    assert 'note: click role=button name="Flash": the element is not inside the crop' in out
    assert 'note: circle text="Painted words": the element is not inside the crop' in out


def test_an_animated_picture_is_cut_to_its_crop_with_a_strip_for_the_note(
    desktop, chromium, real_ffmpeg, sandbox, tmp_path, capsys
):
    _, ffprobe = real_ffmpeg
    steps = [{
        "note": "Type a name, then press Add.",
        "do": [{"fill": {"label": "Name", "value": "sam"}}, {"arrow": {"role": "button", "name": "Add", "note": "Press this one"}}],
        "pause": 1,
    }]
    # The top left quarter of the window: the form, and a part of what is painted under it.
    path = write_board(tmp_path, desktop, steps, crop={"at": "0x0", "size": "640x360"})
    assert cli.main(["animate", str(path), "--format", "gif", "--keep-work"]) == 0
    gif = path.parent / "add.gif"
    # 652 wide: 640 plus 12 pixels that are not the edge of the window; 418 tall: 360 plus a strip of 46 for the note.
    assert f"{gif}  652x418" in capsys.readouterr().out
    assert dimensions(ffprobe, gif) == (652, 418)
    (work,) = sandbox.work.iterdir()
    assert [shown.kind for shown in takelog.read(work / "take.json").shown] == ["strip", "click", "mark", "note"]
    # The strip is dark from the first frame on, where the note's words are not.
    assert max(brightness(gif, x=8, y=380, width=40, height=30)) < 60
    # The arrow and its words are red, and nothing else in the fixture is.
    reds = redness(gif, x=0, y=0, width=652, height=372)
    assert max(reds) > reds[0] + 3


def test_a_mark_is_drawn_in_a_video_and_goes_before_the_next_step(desktop, chromium, fake_tts, real_ffmpeg, sandbox, tmp_path):
    steps = [
        {"say": "This is the button.", "do": [{"spotlight": {"role": "button", "name": "Add"}}]},
        {"say": "That was it.", "pause": 1},
    ]
    path = write_board(tmp_path, desktop, steps)
    assert cli.main(["render", str(path), "--keep-work"]) == 0
    (work,) = sandbox.work.iterdir()
    (mark,) = takelog.read(work / "take.json").shown
    assert mark.kind == "mark" and mark.fade == 0.25
    # The app paints that part of its window white, far from the button. A spotlight darkens all but its target.
    levels = brightness(path.parent / "add.mp4", x=560, y=625, width=160, height=40)
    assert levels[round((mark.start + 0.5) * 25)] < 130
    assert levels[round((mark.end + 0.2) * 25)] > 200


@pytest.fixture
def profile(desktop):
    """The name of a profile that no other test has, removed with its volume after the test."""
    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    subprocess.run([*desktop.docker, "volume", "rm", "-f", profiles.volume(name)], capture_output=True)


WAIT = [{"do": [{"wait_for": {"role": "button", "name": "Add"}}]}]


def test_a_profile_that_was_never_made_stops_with_the_command_that_makes_it(desktop, sandbox, tmp_path, capsys, profile):
    path = write_board(tmp_path, desktop, WAIT, profile=profile)
    assert cli.main(["probe", str(path)]) == 1
    assert f"howto: profile `{profile}` does not exist: run `howto login {profile} {path}`" in capsys.readouterr().err
    # Docker makes a volume that a container names. The command stopped before any container did.
    assert profiles.exists(desktop.docker, profile) is False


def test_a_profile_keeps_the_home_of_the_app_and_a_run_without_one_starts_anew(desktop, sandbox, tmp_path, capsys, profile):
    profiles.create(desktop.docker, profile)
    wrote = write_board(tmp_path, desktop, WAIT, profile=profile, setup=[{"run": "echo kept > $HOME/kept.txt"}])
    assert cli.main(["probe", str(wrote)]) == 0
    again = write_board(tmp_path, desktop, WAIT, profile=profile, setup=[{"run": "test -f $HOME/kept.txt"}])
    assert cli.main(["probe", str(again)]) == 0
    capsys.readouterr()
    fresh = write_board(tmp_path, desktop, WAIT, setup=[{"run": "test -f $HOME/kept.txt"}])
    assert cli.main(["probe", str(fresh)]) == 1
    assert "run test -f $HOME/kept.txt: it ended with exit code 1" in capsys.readouterr().out


def test_an_app_gets_the_time_to_write_down_what_it_holds_when_the_run_ends(desktop, sandbox, tmp_path, profile):
    profiles.create(desktop.docker, profile)
    # A line of shell that stands for an app which saves its session when it is told to end.
    saving = f"trap 'echo saved > $HOME/saved.txt' TERM; {desktop.run} & wait"
    path = write_board(tmp_path, desktop, WAIT, profile=profile)
    path.write_text(path.read_text().replace(desktop.run, saving), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 0
    after = write_board(tmp_path, desktop, WAIT, profile=profile, setup=[{"run": "test -f $HOME/saved.txt"}])
    assert cli.main(["probe", str(after)]) == 0


def connected(window):
    """Waits until the page shows the monitor: noVNC then gives its canvas the size of the monitor."""
    window.page.wait_for_function("(() => { const c = document.querySelector('canvas'); return c && c.width === 1280; })()", timeout=30_000)


def press_on_the_monitor(window, x, y):
    """A click of the person at a place of the monitor, through the page."""
    box = window.page.locator("canvas").bounding_box()
    window.page.mouse.click(box["x"] + box["width"] * x / 1280, box["y"] + box["height"] * y / 720)


def painted_words(link):
    reply = link.request("find", limit=30, locator={"text": "Painted words"}, timeout=5)
    return reply["box"] if reply["count"] == 1 else None


@pytest.mark.browser
@pytest.mark.parametrize("view_only, pressed", [(False, True), (True, False)])
def test_the_window_shows_the_monitor_and_only_a_sign_in_can_use_it(desktop, chromium, view_only, pressed):
    link = open_link(desktop.docker, desktop.image, publish=viewer.PORT)
    try:
        link.request("start", limit=90, run=desktop.run, width=1280, height=720, timeout=60)
        shown = link.request("show", limit=60, view_only=view_only)
        window = viewer.Viewer(viewer.address(link.port(viewer.PORT), shown["password"], view_only=view_only), headless=True)
        try:
            connected(window)
            x, y, width, height = painted_words(link)
            # The painted part of the fixture changes its words when it is pressed.
            press_on_the_monitor(window, x + width / 2, y + height / 2)
            window.page.wait_for_timeout(1500)
            assert (painted_words(link) is None) is pressed
        finally:
            window.close()
    finally:
        link.close()


@pytest.mark.browser
def test_login_makes_the_profile_and_shows_the_app_until_the_window_closes(desktop, chromium, sandbox, tmp_path, profile):
    seen = []

    class Visitor(viewer.Viewer):
        """A person who looks at the app, presses its painted part, and closes the window."""

        def __init__(self, url):
            super().__init__(url, headless=True)

        def wait(self):
            connected(self)
            seen.append(self.page.locator("canvas").bounding_box()["width"] > 100)

    path = write_board(tmp_path, desktop, WAIT)
    stage.login(cli.load(path), profile, open_viewer=Visitor)
    assert seen == [True]
    assert profiles.exists(desktop.docker, profile) is True
    # The storyboard now starts on the profile that the login made.
    assert cli.main(["probe", str(write_board(tmp_path, desktop, WAIT, profile=profile))]) == 0


def test_a_probe_of_a_storyboard_that_zooms_reports_in_pixels_of_the_picture(desktop, sandbox, tmp_path, capsys):
    steps = [{"do": [{"click": {"role": "button", "name": "Flash"}}, {"circle": {"text": "Painted words"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps, zoom=2))]) == 0
    out = capsys.readouterr().out
    assert "step 1 ok" in out and '- frame "Fixture" [active]:' in out
    data = (sandbox.cache / "probe" / "add.png").read_bytes()
    assert (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) == (1280, 720)
