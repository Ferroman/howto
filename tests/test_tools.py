import stat
import sys

import pytest

from howto.errors import HowtoError, RunError, StoryboardError
from howto.tools import find_tool, run


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
