import json
import subprocess

import pytest
import yaml

from pictures import dimensions, gif_frames, redness, webp

from howto import cli
from howto.errors import RunError
from howto.tools import find_tool

pytestmark = pytest.mark.browser


@pytest.fixture
def real_ffmpeg(monkeypatch):
    monkeypatch.delenv("HOWTO_FFMPEG", raising=False)
    monkeypatch.delenv("HOWTO_FFPROBE", raising=False)
    try:
        return find_tool("ffmpeg", "HOWTO_FFMPEG"), find_tool("ffprobe", "HOWTO_FFPROBE")
    except RunError:
        pytest.skip("ffmpeg is not installed")


def write_board(tmp_path, site_url, *, settings="Settings", last="The invitation is on its way.", zoom=None):
    data = {
        "title": "Invite a teammate",
        "url": f"{site_url}/index.html",
        "setup": [{"wait_for": {"role": "heading", "name": "Home"}}],
        "steps": [
            {"chapter": "Invite a teammate"},
            {"say": "Open Settings.", "do": [{"click": {"role": "button", "name": settings}}]},
            {
                "say": "Type the email. Then press Invite.",
                "note": "Use a work address.",
                "do": [
                    {"fill": {"label": "Email address", "value": "sam@example.com"}},
                    {"click": {"role": "button", "name": "Invite"}},
                ],
            },
            {"say": last, "do": [{"wait_for": {"role": "heading", "name": "Invitation sent"}}]},
        ],
    }
    if zoom is not None:
        data["zoom"] = zoom
    path = tmp_path / "videos" / "demo.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_a_probe_of_a_correct_storyboard(chromium, site_url, fake_tts, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, site_url))]) == 0
    out = capsys.readouterr().out
    assert "step 4 ok" in out
    assert 'heading "Invitation sent"' in out


def test_a_probe_names_the_step_with_the_wrong_locator(chromium, site_url, fake_tts, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")
    assert cli.main(["probe", str(write_board(tmp_path, site_url, settings="Preferences"))]) == 1
    out = capsys.readouterr().out
    assert 'step 2 FAILED  click role=button name="Preferences": 0 elements match' in out
    assert 'button "Settings"' in out


def test_a_render_gives_a_narrated_video(chromium, site_url, fake_tts, real_ffmpeg, sandbox, tmp_path):
    _, ffprobe = real_ffmpeg
    path = write_board(tmp_path, site_url)
    assert cli.main(["render", str(path), "--keep-work"]) == 0

    video = path.parent / "demo.mp4"
    shown = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(shown.stdout)
    streams = {stream["codec_type"]: stream for stream in info["streams"]}
    assert (streams["video"]["codec_name"], streams["video"]["width"], streams["video"]["height"]) == ("h264", 1920, 1080)
    assert streams["audio"]["codec_name"] == "aac"

    (work,) = sandbox.work.iterdir()
    timeline = json.loads((work / "timeline.json").read_text())
    assert abs(float(info["format"]["duration"]) - timeline["steps"][-1]["end"]) <= 0.5

    # Four sentences: one, two and one.
    assert (path.parent / "demo.srt").read_text().count(" --> ") == 4
    assert (path.parent / "demo.vtt").read_text().startswith("WEBVTT")


def test_a_second_render_speaks_only_the_changed_sentence(chromium, site_url, fake_tts, real_ffmpeg, tmp_path):
    assert cli.main(["render", str(write_board(tmp_path, site_url))]) == 0
    before = len(fake_tts.spoken())
    assert cli.main(["render", str(write_board(tmp_path, site_url, last="Sam gets an email."))]) == 0
    assert fake_tts.spoken()[before:] == ["Sam gets an email."]


def test_a_failed_render_keeps_the_earlier_video(chromium, site_url, fake_tts, real_ffmpeg, tmp_path, monkeypatch):
    path = write_board(tmp_path, site_url)
    assert cli.main(["render", str(path)]) == 0
    earlier = (path.parent / "demo.mp4").read_bytes()
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "1")
    assert cli.main(["render", str(write_board(tmp_path, site_url, settings="Preferences"))]) == 1
    assert (path.parent / "demo.mp4").read_bytes() == earlier


def test_a_video_ends_with_its_timeline(chromium, site_url, fake_tts, real_ffmpeg, sandbox, tmp_path):
    # The last step changes the picture and then takes its note away. Playwright's
    # recorder runs on after such an end, by a second or more.
    _, ffprobe = real_ffmpeg
    data = {
        "title": "Invite a teammate",
        "url": f"{site_url}/settings.html",
        "steps": [
            {
                "say": "Type the email. Then press Invite.",
                "note": "Use a work address.",
                "do": [
                    {"fill": {"label": "Email address", "value": "sam@example.com"}},
                    {"click": {"role": "button", "name": "Invite"}},
                ],
            },
        ],
    }
    path = tmp_path / "videos" / "demo.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert cli.main(["render", str(path), "--keep-work"]) == 0

    shown = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path.parent / "demo.mp4")],
        capture_output=True, text=True, check=True,
    )
    (work,) = sandbox.work.iterdir()
    timeline = json.loads((work / "timeline.json").read_text())
    assert abs(float(json.loads(shown.stdout)["format"]["duration"]) - timeline["steps"][-1]["end"]) <= 0.5


def test_a_storyboard_with_zoom_probes_and_renders(chromium, site_url, fake_tts, real_ffmpeg, sandbox, tmp_path, capsys):
    _, ffprobe = real_ffmpeg
    path = write_board(tmp_path, site_url, zoom=2)
    assert cli.main(["probe", str(path)]) == 0
    assert "step 4 ok" in capsys.readouterr().out
    assert cli.main(["render", str(path), "--keep-work"]) == 0

    shown = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path.parent / "demo.mp4")],
        capture_output=True, text=True, check=True,
    )
    (work,) = sandbox.work.iterdir()
    steps = json.loads((work / "timeline.json").read_text())["steps"]
    assert abs(float(shown.stdout) - steps[-1]["end"]) <= 0.5
    # The second step holds one click: the way in, the hold and the way out make it longer than its narration.
    assert steps[1]["end"] - steps[1]["start"] > 2.5


def test_a_storyboard_with_marks_probes_and_renders(chromium, site_url, fake_tts, real_ffmpeg, sandbox, tmp_path, capsys):
    data = {
        "title": "Invite a teammate",
        "url": f"{site_url}/settings.html",
        "zoom": 2,
        "steps": [
            {
                "say": "Pending invitations are listed here.",
                "do": [{"spotlight": {"role": "region", "name": "Pending invitations"}}],
            },
            {
                "say": "Type the email. Then press Invite.",
                "do": [
                    {"box": {"label": "Email address"}},
                    {"fill": {"label": "Email address", "value": "sam@example.com"}},
                    {"arrow": {"role": "button", "name": "Invite", "note": "Sends the email"}},
                    {"click": {"role": "button", "name": "Invite"}},
                ],
            },
            {"say": "The invitation is on its way.", "do": [{"circle": {"role": "heading", "name": "Invitation sent"}}]},
        ],
    }
    path = tmp_path / "videos" / "demo.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    assert 'step 2 ok      box label="Email address"; fill' in out
    assert 'arrow role=button name="Invite" note="Sends the email"' in out
    assert 'heading "Invitation sent"' in out

    assert cli.main(["render", str(path), "--keep-work"]) == 0
    (work,) = sandbox.work.iterdir()
    steps = json.loads((work / "timeline.json").read_text())["steps"]
    shown = subprocess.run(
        [real_ffmpeg[1], "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path.parent / "demo.mp4")],
        capture_output=True, text=True, check=True,
    )
    assert abs(float(shown.stdout) - steps[-1]["end"]) <= 0.5


def test_a_storyboard_with_a_crop_probes_and_animates(chromium, site_url, real_ffmpeg, sandbox, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("HOWTO_IMG2WEBP", raising=False)
    try:
        find_tool("img2webp", "HOWTO_IMG2WEBP")
    except RunError:
        pytest.skip("img2webp is not installed")
    # An animated picture has no voice. A speech command that is asked for anything fails the test.
    monkeypatch.setenv("HOWTO_TTS", "/nonexistent/tts")
    apply = {"role": "button", "name": "Apply"}
    data = {
        "title": "Pick a style",
        "url": f"{site_url}/panel.html",
        "viewport": "1280x720",
        "crop": {"role": "complementary", "name": "Style"},
        "steps": [
            {
                "chapter": "Style",
                "say": "These words are for the video.",
                "note": "Press Apply",
                "do": [{"arrow": {"role": "button", "name": "Edge"}}, {"box": apply}, {"click": apply}],
                "pause": 1,
            },
        ],
    }
    path = tmp_path / "docs" / "style.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    # The panel is 300 by 400 pixels at (960, 100), and a crop keeps 12 pixels around it.
    assert out.startswith('crop: 324 x 424 pixels at 948, 88\nstep 1 ok      chapter "Style"; arrow role=button name="Edge"; box')
    assert "note:" not in out

    assert cli.main(["animate", str(path)]) == 0
    gif, picture = path.parent / "style.gif", path.parent / "style.webp"
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[:2] for line in lines] == [[str(gif), "324x424"], [str(picture), "324x424"]]
    assert sorted(p.name for p in path.parent.iterdir()) == ["style.gif", "style.webp", "style.yaml"]
    assert list(sandbox.work.iterdir()) == []

    assert dimensions(real_ffmpeg[1], gif) == (324, 424)
    frames = gif_frames(real_ffmpeg[1], gif)
    seconds = frames[-1][0] + frames[-1][1]
    # Lead, two marks, their hold, the click and the gap come to some 3 s, and then the pause of 1 s.
    assert 3.0 < seconds < 8.0
    assert f"  {seconds:.1f} s  " in lines[0]
    canvas, times, loops = webp(picture)
    assert (canvas, loops) == ((324, 424), 0)
    assert sum(times) == round(seconds * 1000)
    # The box around Apply, 8 pixels above the button at (980, 120). In the
    # picture that is (32, 24): the cut is where the crop said.
    stroke = redness(gif, x=52, y=20, width=60, height=8)
    assert max(stroke) > 20, "the mark is not in the picture"
    assert stroke[-1] < 5, "the picture ends with the mark still on it"
