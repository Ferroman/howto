"""`howto probe` on a desktop storyboard, from the command to the report. These tests need Docker and the base image."""
import json

import pytest
import yaml

from pictures import brightness, dimensions
from howto import cli
from howto.assemble import video_duration
from howto.desktop import takelog
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


import json

from pictures import brightness, dimensions

from howto.assemble import video_duration
from howto.desktop import takelog
from howto.desktop.stage import PRESS
from howto.errors import RunError
from howto.tools import find_tool


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
