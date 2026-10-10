"""Shared fixtures: a sandbox for howto's state, and fake tts, ffmpeg and ffprobe programs."""
from __future__ import annotations

import stat
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

FAKE_TTS = '''
    """Stands in for `tts`: writes a tone of 0.06 s per character and logs each call."""
    import math, os, struct, sys, wave

    args = sys.argv[1:]
    out = args[args.index("-o") + 1]
    text = args[-1]
    log = os.environ.get("FAKE_TTS_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(text + "\\n")
    if os.environ.get("FAKE_TTS_FAIL"):
        sys.stderr.write("fake-tts: told to fail\\n")
        sys.exit(3)
    rate = 22_050
    frames = int(rate * 0.06 * len(text))
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(frames)))
'''

FAKE_FFMPEG = '''
    """Stands in for ffmpeg in the two ways howto calls it.

    One input: a clip conversion. Writes silence of the same length at 48 kHz, mono, 16-bit.
    Two inputs: the assembly. Writes a marker file, or fails when FAKE_FFMPEG_FAIL=mux.
    """
    import os, sys, wave

    args = sys.argv[1:]
    log = os.environ.get("FAKE_FFMPEG_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    inputs = [args[i + 1] for i, arg in enumerate(args) if arg == "-i"]
    out = args[-1]
    if len(inputs) == 2:
        if os.environ.get("FAKE_FFMPEG_FAIL") == "mux":
            sys.stderr.write("fake-ffmpeg: told to fail the assembly\\n")
            sys.exit(1)
        with open(out, "wb") as handle:
            handle.write(b"fake mp4")
        sys.exit(0)
    with wave.open(inputs[0], "rb") as source:
        seconds = source.getnframes() / source.getframerate()
    with wave.open(out, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48000)
        target.writeframes(bytes(2 * round(seconds * 48000)))
'''

FAKE_FFPROBE = '''
    """Stands in for ffprobe: prints the duration it was told to report."""
    import os

    print(os.environ.get("FAKE_FFPROBE_DURATION", "10.0"))
'''


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{textwrap.dedent(body).lstrip()}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """howto's state directories, redirected into the test's temporary directory."""
    cache = tmp_path / "cache"
    data = tmp_path / "data"
    monkeypatch.setenv("HOWTO_CACHE_DIR", str(cache))
    monkeypatch.setenv("HOWTO_DATA_DIR", str(data))
    monkeypatch.delenv("HOWTO_ACTION_TIMEOUT", raising=False)
    return SimpleNamespace(cache=cache, data=data, clips=cache / "clips", work=cache / "work")


@pytest.fixture
def fake_tts(tmp_path, monkeypatch, sandbox):
    """A fake `tts` on HOWTO_TTS. `spoken()` lists the sentences it was asked to speak."""
    program = _script(tmp_path / "fake-tts", FAKE_TTS)
    log = tmp_path / "tts.log"
    monkeypatch.setenv("HOWTO_TTS", str(program))
    monkeypatch.setenv("FAKE_TTS_LOG", str(log))
    monkeypatch.delenv("FAKE_TTS_FAIL", raising=False)

    def spoken() -> list[str]:
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    return SimpleNamespace(program=str(program), spoken=spoken)


@pytest.fixture
def fakes(tmp_path, monkeypatch, sandbox, fake_tts):
    """Fake tts, ffmpeg and ffprobe together, for tests that must not run the real programs."""
    ffmpeg = _script(tmp_path / "fake-ffmpeg", FAKE_FFMPEG)
    ffprobe = _script(tmp_path / "fake-ffprobe", FAKE_FFPROBE)
    monkeypatch.setenv("HOWTO_FFMPEG", str(ffmpeg))
    monkeypatch.setenv("HOWTO_FFPROBE", str(ffprobe))
    monkeypatch.delenv("FAKE_FFMPEG_FAIL", raising=False)
    monkeypatch.delenv("FAKE_FFPROBE_DURATION", raising=False)
    return SimpleNamespace(tts=fake_tts, ffmpeg=str(ffmpeg), ffprobe=str(ffprobe), sandbox=sandbox)


SITE = Path(__file__).parent / "fixtures" / "site"
SITE_REQUESTS: list[str] = []


@pytest.fixture(scope="session")
def site_url():
    """The three static pages of tests/fixtures/site, served on a free local port."""
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            SITE_REQUESTS.append(self.path)
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def site_requests(site_url):
    """The paths the fixture site was asked for since this test began."""
    SITE_REQUESTS.clear()
    return SITE_REQUESTS


@pytest.fixture(scope="session")
def chromium():
    """Skips a browser test on a machine without Playwright's Chromium."""
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Error as exc:
        pytest.skip(f"Playwright's Chromium is not installed: {str(exc).splitlines()[0]}")
