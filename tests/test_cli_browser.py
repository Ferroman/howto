import json
import subprocess

import pytest
import yaml

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


def write_board(tmp_path, site_url, *, settings="Settings", last="The invitation is on its way."):
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
