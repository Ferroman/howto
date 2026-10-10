import contextlib
from types import SimpleNamespace

import pytest
import yaml

from fakes import FakeClock, FakeStage
from howto import cli
from howto.errors import RunError
from howto.narrate import wav_duration

CLICK_A = 'click role=button name="A"'
CLICK_B = 'click role=button name="B"'
CLEANUP = 'click role=button name="Undo"'
SETUP = 'wait_for role=heading name="Home"'
PANEL = {"role": "complementary", "name": "Panel"}
CROP = 'crop role=complementary name="Panel"'


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
    state = SimpleNamespace(
        clock=FakeClock(), stage=None, opened=0, headless=None, options={}, interrupt=None, on_close=lambda: None
    )

    @contextlib.contextmanager
    def fake_open(storyboard, *, headless, interrupt=None):
        state.opened += 1
        state.headless = headless
        state.interrupt = interrupt
        state.stage = FakeStage(state.clock, **state.options)
        yield state.stage
        state.on_close()

    monkeypatch.setattr(cli, "open_stage", fake_open)
    monkeypatch.setattr(cli, "RealClock", lambda interrupt=None: state.clock)
    return state


def test_probe_prints_the_report(browser, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"step 1 ok      {CLICK_A}\n")
    assert 'page: http://demo.test/end  "End"' in out and "outline:" in out
    assert browser.headless is True


def test_probe_names_the_crop_first(browser, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, crop=PANEL))]) == 0
    assert capsys.readouterr().out.startswith(f"crop: 340 x 250 pixels at 100, 50\nstep 1 ok      {CLICK_A}\n")
    assert browser.stage.calls[0] == CROP


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


def test_within_keeps_a_name_as_it_is_written(browser, tmp_path):
    # YAML would read Yes as true.
    assert cli.main(["probe", str(write_board(tmp_path)), "--within", "{role: button, name: Yes}"]) == 0
    within, _ = browser.stage.report_args
    assert (within.role, within.name) == ("button", "Yes")


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


@pytest.mark.parametrize("command", ["render", "probe", "animate"])
def test_a_stop_request_during_the_last_browser_call_exits_130(browser, fakes, tmp_path, command):
    # Nothing checks for a request after the last call, so leaving the browser must.
    browser.on_close = lambda: browser.interrupt.request()
    path = write_board(tmp_path)
    assert cli.main([command, str(path)]) == 130
    assert [p.name for p in path.parent.iterdir()] == ["demo.yaml"]
    assert list(fakes.sandbox.work.iterdir()) == [] if command != "probe" else True


def test_the_signal_handlers_are_put_back_after_a_render(browser, tmp_path):
    import signal

    before = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    assert cli.main(["render", str(write_board(tmp_path))]) == 0
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_animate_writes_both_pictures_next_to_the_storyboard(browser, fakes, tmp_path, capsys):
    path = write_board(tmp_path)
    assert cli.main(["animate", str(path)]) == 0
    folder = path.parent
    assert sorted(p.name for p in folder.iterdir()) == ["demo.gif", "demo.webp", "demo.yaml"]
    # Two steps of lead 0.5 + gap 0.4 are 1.8 s, which is 23 frames of 0.08 s.
    assert capsys.readouterr().out.splitlines() == [
        f"{folder / 'demo.gif'}  960x540  1.8 s  1 KB",
        f"{folder / 'demo.webp'}  960x540  1.8 s  1 KB",
    ]
    assert browser.headless is True
    assert browser.stage.calls == ["start_recording", CLICK_A, CLICK_B, "stop_recording", CLEANUP]
    assert list(fakes.sandbox.work.iterdir()) == []


def test_animate_speaks_nothing_and_needs_no_speech_command(browser, fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_FAIL", "1")
    assert cli.main(["animate", str(write_board(tmp_path))]) == 0
    assert fakes.tts.spoken() == []


def test_animate_shows_no_title_card(browser, fakes, tmp_path):
    path = write_board(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["steps"].insert(0, {"chapter": "Settings"})
    path.write_text(yaml.safe_dump(data))
    assert cli.main(["animate", str(path)]) == 0
    assert "chapter Settings" not in browser.stage.calls


def test_animate_cuts_the_picture_to_the_crop(browser, fakes, tmp_path, monkeypatch, capsys):
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    assert cli.main(["animate", str(write_board(tmp_path, crop=PANEL))]) == 0
    assert browser.stage.calls[:2] == [CROP, "start_recording"]
    assert " crop=340:250:100:50,fps=12.5,mpdecimate " in log.read_text()
    assert "  340x250  " in capsys.readouterr().out


def test_render_films_the_whole_window_of_a_storyboard_with_a_crop(browser, fakes, tmp_path, monkeypatch):
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    assert cli.main(["render", str(write_board(tmp_path, crop=PANEL))]) == 0
    assert CROP not in browser.stage.calls
    assert "crop=" not in log.read_text()


def test_animate_width_scales_a_wider_picture_down(browser, fakes, tmp_path, monkeypatch, capsys):
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    assert cli.main(["animate", str(write_board(tmp_path)), "--width", "480"]) == 0
    assert " fps=12.5,scale=480:270:flags=lanczos,mpdecimate " in log.read_text()
    assert "  480x270  " in capsys.readouterr().out


@pytest.mark.parametrize("kind, other", [("gif", "HOWTO_IMG2WEBP"), ("webp", None)])
def test_animate_format_writes_one_picture(browser, fakes, tmp_path, monkeypatch, capsys, kind, other):
    if other:
        # A GIF alone must not ask for the program that only the WebP needs.
        monkeypatch.setenv(other, "/nonexistent/program")
    path = write_board(tmp_path)
    assert cli.main(["animate", str(path), "--format", kind]) == 0
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([f"demo.{kind}", "demo.yaml"])
    assert len(capsys.readouterr().out.splitlines()) == 1


def test_a_missing_webp_program_stops_before_the_browser(browser, fakes, tmp_path, monkeypatch, capsys):
    real = cli.find_tool

    def find(name, env_var):
        if name == "img2webp":
            raise RunError("img2webp not found: set HOWTO_IMG2WEBP or install img2webp")
        return real(name, env_var)

    monkeypatch.setattr(cli, "find_tool", find)
    assert cli.main(["animate", str(write_board(tmp_path))]) == 1
    assert browser.opened == 0
    err = capsys.readouterr().err
    assert "img2webp not found" in err and "--format gif" in err


@pytest.mark.parametrize("arguments", [["--width", "0"], ["--width", "-960"]])
def test_bad_animate_options_exit_2(browser, tmp_path, arguments):
    assert cli.main(["animate", str(write_board(tmp_path)), *arguments]) == 2
    assert browser.opened == 0


def test_an_unknown_format_is_a_usage_error(browser, tmp_path):
    with pytest.raises(SystemExit) as caught:
        cli.main(["animate", str(write_board(tmp_path)), "--format", "apng"])
    assert caught.value.code == 2


def test_animate_out_and_keep_work(browser, fakes, tmp_path):
    arguments = ["animate", str(write_board(tmp_path)), "--out", str(tmp_path / "published"), "--keep-work"]
    assert cli.main(arguments) == 0
    assert sorted(p.name for p in (tmp_path / "published").iterdir()) == ["demo.gif", "demo.webp"]
    (work,) = fakes.sandbox.work.iterdir()
    assert sorted(p.name for p in work.iterdir()) == ["capture.webm", "frames"]


def test_a_failed_step_writes_no_picture_and_keeps_the_earlier_one(browser, fakes, tmp_path, capsys):
    path = write_board(tmp_path)
    (path.parent / "demo.gif").write_bytes(b"earlier gif")
    browser.options = {"fail_on": {CLICK_B: "0 elements match"}}
    assert cli.main(["animate", str(path)]) == 1
    assert (path.parent / "demo.gif").read_bytes() == b"earlier gif"
    assert not (path.parent / "demo.webp").exists()
    assert f"howto: step 2: {CLICK_B}: 0 elements match" in capsys.readouterr().err
    assert CLEANUP in browser.stage.calls
    assert list(fakes.sandbox.work.iterdir()) == []


def test_a_crop_that_is_not_found_is_named(browser, fakes, tmp_path, capsys):
    browser.options = {"fail_on": {CROP: "0 elements match"}}
    path = write_board(tmp_path, crop=PANEL)
    assert cli.main(["animate", str(path)]) == 1
    assert f"howto: setup: {CROP}: 0 elements match" in capsys.readouterr().err
    assert browser.stage.calls == [CROP, CLEANUP]
    assert [p.name for p in path.parent.iterdir()] == ["demo.yaml"]


@pytest.mark.parametrize(
    "variable, value, said",
    [("FAKE_FFMPEG_FAIL", "gif", "told to fail the gif"), ("FAKE_IMG2WEBP_FAIL", "1", "fake-img2webp: told to fail")],
)
def test_a_failed_picture_keeps_the_work_directory(browser, fakes, tmp_path, capsys, monkeypatch, variable, value, said):
    monkeypatch.setenv(variable, value)
    path = write_board(tmp_path)
    (path.parent / "demo.gif").write_bytes(b"earlier gif")
    assert cli.main(["animate", str(path)]) == 1
    (work,) = fakes.sandbox.work.iterdir()
    err = capsys.readouterr().err
    assert f"work directory kept: {work}" in err and said in err
    assert (path.parent / "demo.gif").read_bytes() == b"earlier gif"
    assert sorted(p.name for p in path.parent.iterdir()) == ["demo.gif", "demo.yaml"]


def test_cleanup_warnings_of_an_animated_take_go_to_stderr(browser, fakes, tmp_path, capsys):
    browser.options = {"fail_on": {CLEANUP: "0 elements match"}}
    assert cli.main(["animate", str(write_board(tmp_path))]) == 0
    assert f"howto: warning: cleanup[1]: {CLEANUP}: 0 elements match" in capsys.readouterr().err
