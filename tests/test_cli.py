import contextlib
from types import SimpleNamespace

import pytest
import yaml

from fakes import FakeClock, FakeStage
from howto import cli
from howto.narrate import wav_duration

CLICK_A = 'click role=button name="A"'
CLICK_B = 'click role=button name="B"'
CLEANUP = 'click role=button name="Undo"'
SETUP = 'wait_for role=heading name="Home"'


def click(name):
    return {"click": {"role": "button", "name": name}}


def write_board(tmp_path, second="Press Save.", **extra):
    data = {
        "title": "Demo",
        "url": "http://demo.test",
        "steps": [
            {"say": "Open the menu. Pick Settings.", "do": [click("A")]},
            {"say": second, "do": [click("B")]},
        ],
        "cleanup": [click("Undo")],
        **extra,
    }
    path = tmp_path / "videos" / "demo.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def browser(monkeypatch, fakes):
    """Replaces Chromium with a FakeStage and real time with a FakeClock."""
    state = SimpleNamespace(clock=FakeClock(), stage=None, opened=0, headless=None, options={})

    @contextlib.contextmanager
    def fake_open(storyboard, *, headless):
        state.opened += 1
        state.headless = headless
        state.stage = FakeStage(state.clock, **state.options)
        yield state.stage

    monkeypatch.setattr(cli, "open_stage", fake_open)
    monkeypatch.setattr(cli, "RealClock", lambda: state.clock)
    return state


def test_probe_prints_the_report(browser, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"step 1 ok      {CLICK_A}\n")
    assert 'page: http://demo.test/end  "End"' in out and "outline:" in out
    assert browser.headless is True


def test_probe_show_uses_a_window(browser, tmp_path):
    assert cli.main(["probe", str(write_board(tmp_path)), "--show"]) == 0
    assert browser.headless is False


def test_a_failed_probe_exits_1(browser, tmp_path, capsys):
    browser.options = {"fail_on": {CLICK_B: "0 elements match"}}
    assert cli.main(["probe", str(write_board(tmp_path))]) == 1
    assert f"step 2 FAILED  {CLICK_B}: 0 elements match" in capsys.readouterr().out


def test_probe_options_reach_the_stage(browser, tmp_path):
    arguments = ["probe", str(write_board(tmp_path)), "--until", "1", "--within", "{role: dialog}", "--max-chars", "500"]
    assert cli.main(arguments) == 0
    within, max_chars = browser.stage.report_args
    assert (within.role, max_chars) == ("dialog", 500)
    assert CLICK_B not in browser.stage.calls


@pytest.mark.parametrize(
    "arguments",
    [["--until", "0"], ["--max-chars", "0"], ["--within", "{rol: dialog}"], ["--within", "[unclosed"]],
)
def test_bad_probe_options_exit_2(browser, tmp_path, arguments):
    assert cli.main(["probe", str(write_board(tmp_path)), *arguments]) == 2
    assert browser.opened == 0


def test_an_invalid_storyboard_exits_2_and_names_the_problem(browser, tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("title: T\nurl: http://demo.test\nsteps:\n  - sya: Hi.\n", encoding="utf-8")
    assert cli.main(["render", str(path)]) == 2
    assert "step 1: unknown field `sya`" in capsys.readouterr().err
    assert browser.opened == 0


def test_a_missing_storyboard_exits_2(browser, tmp_path):
    assert cli.main(["probe", str(tmp_path / "absent.yaml")]) == 2


def test_a_usage_error_exits_2(browser):
    with pytest.raises(SystemExit) as caught:
        cli.main(["render"])
    assert caught.value.code == 2


def test_render_writes_the_outputs_next_to_the_storyboard(browser, fakes, tmp_path, capsys):
    path = write_board(tmp_path)
    assert cli.main(["render", str(path)]) == 0
    folder = path.parent
    assert sorted(p.name for p in folder.iterdir()) == ["demo.mp4", "demo.srt", "demo.vtt", "demo.yaml"]
    assert (folder / "demo.srt").read_text().count(" --> ") == 3
    assert capsys.readouterr().out.splitlines() == [str(folder / f"demo.{kind}") for kind in ("mp4", "srt", "vtt")]
    assert browser.headless is True
    assert browser.stage.calls == ["start_recording", CLICK_A, CLICK_B, "stop_recording", CLEANUP]
    assert list(fakes.sandbox.work.iterdir()) == []


def test_render_out_and_keep_work(browser, fakes, tmp_path):
    arguments = ["render", str(write_board(tmp_path)), "--out", str(tmp_path / "published"), "--keep-work"]
    assert cli.main(arguments) == 0
    assert (tmp_path / "published" / "demo.mp4").exists()
    (work,) = fakes.sandbox.work.iterdir()
    assert sorted(p.name for p in work.iterdir()) == ["capture.webm", "narration.wav", "timeline.json"]


def test_a_storyboard_without_narration_still_renders(browser, tmp_path):
    path = write_board(tmp_path)
    path.write_text(yaml.safe_dump({"title": "Demo", "url": "http://demo.test", "steps": [{"do": [click("A")]}]}))
    assert cli.main(["render", str(path)]) == 0
    assert (path.parent / "demo.mp4").exists()
    assert (path.parent / "demo.srt").read_text() == ""
    assert (path.parent / "demo.vtt").read_text() == "WEBVTT\n\n"


def test_a_second_render_speaks_only_the_changed_sentence(browser, fakes, tmp_path):
    assert cli.main(["render", str(write_board(tmp_path))]) == 0
    assert len(fakes.tts.spoken()) == 3
    assert cli.main(["render", str(write_board(tmp_path, second="Press Publish."))]) == 0
    assert fakes.tts.spoken()[3:] == ["Press Publish."]


def test_a_failed_step_writes_nothing_and_keeps_the_earlier_video(browser, fakes, tmp_path, capsys):
    path = write_board(tmp_path)
    (path.parent / "demo.mp4").write_bytes(b"earlier video")
    browser.options = {"fail_on": {CLICK_B: "0 elements match"}}
    assert cli.main(["render", str(path)]) == 1
    assert (path.parent / "demo.mp4").read_bytes() == b"earlier video"
    assert not (path.parent / "demo.srt").exists()
    assert f"howto: step 2: {CLICK_B}: 0 elements match" in capsys.readouterr().err
    assert CLEANUP in browser.stage.calls
    assert list(fakes.sandbox.work.iterdir()) == []


def test_a_failed_assembly_keeps_the_work_directory(browser, fakes, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_FAIL", "mux")
    path = write_board(tmp_path)
    (path.parent / "demo.mp4").write_bytes(b"earlier video")
    assert cli.main(["render", str(path)]) == 1
    (work,) = fakes.sandbox.work.iterdir()
    err = capsys.readouterr().err
    assert f"work directory kept: {work}" in err
    assert "told to fail the assembly" in err
    assert (path.parent / "demo.mp4").read_bytes() == b"earlier video"


def test_a_tts_failure_stops_before_the_browser(browser, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_TTS_FAIL", "1")
    assert cli.main(["render", str(write_board(tmp_path))]) == 1
    assert browser.opened == 0
    assert "told to fail" in capsys.readouterr().err


def test_a_failed_setup_suggests_signing_in(browser, tmp_path, capsys):
    path = write_board(tmp_path, profile="demo", setup=[{"wait_for": {"role": "heading", "name": "Home"}}])
    browser.options = {"fail_on": {SETUP: "0 elements match"}}
    assert cli.main(["render", str(path)]) == 1
    err = capsys.readouterr().err
    assert f"howto: setup: {SETUP}: 0 elements match" in err
    assert "howto login demo http://demo.test" in err


def test_cleanup_warnings_go_to_stderr(browser, tmp_path, capsys):
    browser.options = {"fail_on": {CLEANUP: "0 elements match"}}
    assert cli.main(["render", str(write_board(tmp_path))]) == 0
    assert f"howto: warning: cleanup[1]: {CLEANUP}: 0 elements match" in capsys.readouterr().err


def test_an_interrupt_exits_130_and_writes_nothing(browser, fakes, tmp_path):
    browser.options = {"interrupt_on": {CLICK_B}}
    path = write_board(tmp_path)
    assert cli.main(["render", str(path)]) == 130
    assert not (path.parent / "demo.mp4").exists()
    assert CLEANUP in browser.stage.calls
    assert list(fakes.sandbox.work.iterdir()) == []


def test_narrate_writes_a_listening_track(browser, tmp_path, capsys):
    path = write_board(tmp_path)
    assert cli.main(["narrate", str(path)]) == 0
    out = path.parent / "demo.narration.wav"
    assert capsys.readouterr().out.strip() == str(out)
    spoken = sum(0.06 * len(s) for s in ("Open the menu.", "Pick Settings.", "Press Save."))
    assert wav_duration(out) == pytest.approx(spoken + 0.15 + 0.4 + 0.4, abs=0.02)
    assert browser.opened == 0


def test_narrate_needs_narration(browser, tmp_path):
    path = write_board(tmp_path)
    path.write_text(yaml.safe_dump({"title": "Demo", "url": "http://demo.test", "steps": [{"do": [click("A")]}]}))
    assert cli.main(["narrate", str(path)]) == 2


def test_login_refuses_an_unsafe_profile_name(fakes):
    assert cli.main(["login", "../escape", "http://demo.test"]) == 2


def test_login_opens_the_profile_directory(fakes, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "login", lambda directory, url: seen.update(directory=directory, url=url))
    assert cli.main(["login", "demo", "http://demo.test"]) == 0
    assert seen == {"directory": fakes.sandbox.data / "profiles" / "demo", "url": "http://demo.test"}
