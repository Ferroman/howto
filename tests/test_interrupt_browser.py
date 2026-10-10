"""Ctrl+C and a termination request, sent as real signals to a running `howto`.

A terminal sends SIGINT to the whole foreground process group: howto, the
Playwright driver and the browser. An agent's shell sends SIGTERM when its
time limit ends. The unit tests raise KeyboardInterrupt from a fake, which
says nothing about either.
"""
import os
import signal
import subprocess
import sys
import time

import pytest
import yaml

pytestmark = pytest.mark.browser

PAUSE = [{"do": [{"click": {"role": "button", "name": "Settings"}}], "pause": 60}]
BROWSER_CALL = [{"do": [{"wait_for": {"role": "heading", "name": "No such heading"}}]}]


def stopped(command, steps, signum, *, tmp_path, site_url, site_requests, wait, whole_group=True):
    """Runs howto as a terminal would, signals it once the steps are under way,
    and returns the exit code and what it wrote to stderr."""
    data = {
        "title": "Demo",
        "url": f"{site_url}/index.html",
        "setup": [{"goto": f"{site_url}/index.html?started"}],
        "steps": steps,
        "cleanup": [{"goto": f"{site_url}/done.html?cleaned"}],
    }
    path = tmp_path / "videos" / "demo.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "howto", command, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while "/index.html?started" not in site_requests:
            assert process.poll() is None and time.monotonic() < deadline, "the steps never started"
            time.sleep(0.05)
        time.sleep(wait)
        if whole_group:
            os.killpg(process.pid, signum)
        else:
            os.kill(process.pid, signum)
        _, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
    return process.returncode, stderr


@pytest.mark.parametrize(
    "command, steps, signum, wait, whole_group",
    [
        pytest.param("render", PAUSE, signal.SIGINT, 3.0, True, id="ctrl-c-in-a-pause"),
        pytest.param("render", BROWSER_CALL, signal.SIGINT, 1.5, True, id="ctrl-c-in-a-browser-call"),
        pytest.param("probe", BROWSER_CALL, signal.SIGINT, 1.0, True, id="ctrl-c-in-a-probe"),
        pytest.param("render", PAUSE, signal.SIGTERM, 3.0, False, id="terminated"),
    ],
)
def test_a_stopped_run_cleans_up_and_exits_130(
    chromium, site_url, site_requests, fakes, tmp_path, monkeypatch, command, steps, signum, wait, whole_group
):
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "5")
    code, stderr = stopped(
        command, steps, signum,
        tmp_path=tmp_path, site_url=site_url, site_requests=site_requests, wait=wait, whole_group=whole_group,
    )
    assert (code, stderr.strip().splitlines()[-1:]) == (130, ["howto: interrupted"])
    assert "/done.html?cleaned" in site_requests
    assert not (tmp_path / "videos" / "demo.mp4").exists()
    if command == "render":
        assert list(fakes.sandbox.work.iterdir()) == []


def test_a_run_terminated_with_its_whole_group_still_ends(chromium, site_url, site_requests, fakes, tmp_path):
    # SIGTERM to the group also reaches Playwright, which closes the browser on
    # it, so cleanup cannot run. The run must still end, say that it was
    # stopped, and leave nothing behind.
    code, stderr = stopped(
        "render", PAUSE, signal.SIGTERM, tmp_path=tmp_path, site_url=site_url, site_requests=site_requests, wait=3.0
    )
    assert (code, stderr.strip().splitlines()[-1:]) == (130, ["howto: interrupted"])
    assert not (tmp_path / "videos" / "demo.mp4").exists()
    assert list(fakes.sandbox.work.iterdir()) == []
