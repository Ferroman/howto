import stat
import sys

import pytest

from howto.errors import HowtoError, RunError, StoryboardError
from howto.tools import KEY_NAMES, action_timeout, find_tool, run, run_tool


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_error_exit_codes():
    assert HowtoError("x").exit_code == 1
    assert RunError("x").exit_code == 1
    assert StoryboardError("x").exit_code == 2


def test_env_override_wins(monkeypatch, tmp_path):
    _exe(tmp_path / "brew" / "ffmpeg")
    monkeypatch.setenv("HOWTO_FFMPEG", "/opt/custom/ffmpeg")
    assert find_tool("ffmpeg", "HOWTO_FFMPEG", brew_bin=tmp_path / "brew") == "/opt/custom/ffmpeg"


def test_linuxbrew_is_tried_before_path(monkeypatch, tmp_path):
    brewed = _exe(tmp_path / "brew" / "ffprobe")
    _exe(tmp_path / "path" / "ffprobe")
    monkeypatch.delenv("HOWTO_FFPROBE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "path"))
    assert find_tool("ffprobe", "HOWTO_FFPROBE", brew_bin=tmp_path / "brew") == str(brewed)


def test_path_is_the_last_resort(monkeypatch, tmp_path):
    on_path = _exe(tmp_path / "path" / "ffmpeg")
    monkeypatch.delenv("HOWTO_FFMPEG", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "path"))
    assert find_tool("ffmpeg", "HOWTO_FFMPEG", brew_bin=tmp_path / "empty") == str(on_path)


def test_missing_tool_names_the_override(monkeypatch, tmp_path):
    monkeypatch.delenv("HOWTO_FFMPEG", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RunError, match="HOWTO_FFMPEG"):
        find_tool("ffmpeg", "HOWTO_FFMPEG", brew_bin=tmp_path / "empty")


def test_run_failure_carries_the_exit_code_and_stderr():
    with pytest.raises(RunError) as caught:
        run([sys.executable, "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"], "demo")
    assert "demo failed (exit 3)" in str(caught.value)
    assert "boom" in str(caught.value)


def test_run_reports_a_missing_command():
    with pytest.raises(RunError, match="command not found"):
        run(["/nonexistent/howto-test-binary"], "demo")


def test_run_returns_the_output():
    assert run([sys.executable, "-c", "print('hello')"], "demo").stdout.strip() == "hello"


def test_action_timeout_default():
    assert action_timeout() == 10.0


def test_action_timeout_reads_the_environment(monkeypatch):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "3")
    assert action_timeout() == 3.0
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "0")
    assert action_timeout() == 10.0
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "abc")
    assert action_timeout() == 10.0


def test_run_tool_returns_what_the_program_printed(tmp_path):
    script = tmp_path / "echo.sh"
    script.write_text("#!/bin/sh\nprintf 'hello\\n'\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    assert run_tool(str(script)).strip() == "hello"


def test_run_tool_refuses_a_program_that_fails(tmp_path):
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/sh\nprintf 'no such window\\n' >&2\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(RunError, match="exited with 1: no such window"):
        run_tool(str(script))


def test_run_tool_refuses_a_program_that_takes_too_long(tmp_path):
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(RunError, match="took more than 1"):
        run_tool(str(script), timeout=1)


def test_run_tool_refuses_a_program_that_is_not_there():
    with pytest.raises(RunError, match="is not installed"):
        run_tool("howto-no-such-program")


def test_key_names_are_the_same_on_both_sides():
    """The helper keeps its own list because it imports nothing of howto. Every name here works there."""
    from howto.desktop.helper.keys import BadKey, chord

    for name in KEY_NAMES:
        try:
            chord(name)
        except BadKey as exc:
            pytest.fail(f"the helper does not accept `{name}`: {exc}")
