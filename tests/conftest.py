"""Shared fixtures: a sandbox for howto's state, and fake tts, ffmpeg, ffprobe and img2webp programs."""
from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

FAKE_TTS = '''
    """Stands in for `tts`: writes a tone of 0.06 s per character and logs each call.

    A designed voice is a tone of another pitch for each description, so that
    two voices are two different files.
    """
    import json, math, os, struct, sys, wave

    args = sys.argv[1:]
    out = args[args.index("-o") + 1]
    text = args[-1]
    log = os.environ.get("FAKE_TTS_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(text + "\\n")
        with open(log + ".args", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\\n")
    if os.environ.get("FAKE_TTS_FAIL"):
        sys.stderr.write("fake-tts: told to fail\\n")
        sys.exit(3)
    if os.environ.get("FAKE_TTS_SILENT"):
        sys.exit(0)
    rate = 22_050
    frames = int(rate * 0.06 * len(text))
    pitch = 8 + len(args[args.index("--design") + 1]) % 7 if "--design" in args else 8
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / pitch))) for i in range(frames)))
'''

FAKE_FFMPEG = '''
    """Stands in for ffmpeg in the four ways howto calls it.

    One input: a clip conversion. Writes silence of the same length at 48 kHz, mono, 16-bit.
    Two inputs or more: the assembly. Writes a marker file, or fails when FAKE_FFMPEG_FAIL=mux.
    With -frame_pts: the frames of an animated picture. Writes three files into
    the current directory, numbered 0, 5 and 6, or fails when FAKE_FFMPEG_FAIL=frames.
    With -final_delay: the GIF. Writes a marker file, or fails when FAKE_FFMPEG_FAIL=gif.
    """
    import os, sys, wave

    args = sys.argv[1:]
    log = os.environ.get("FAKE_FFMPEG_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    inputs = [args[i + 1] for i, arg in enumerate(args) if arg == "-i"]
    out = args[-1]
    for flag, kind in (("-frame_pts", "frames"), ("-final_delay", "gif")):
        if flag in args:
            if os.environ.get("FAKE_FFMPEG_FAIL") == kind:
                sys.stderr.write(f"fake-ffmpeg: told to fail the {kind}\\n")
                sys.exit(1)
            for name in ([out % number for number in (0, 5, 6)] if kind == "frames" else [out]):
                with open(name, "wb") as handle:
                    handle.write(f"fake {kind}".encode())
            sys.exit(0)
    if len(inputs) >= 2:
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

FAKE_IMG2WEBP = '''
    """Stands in for img2webp: writes a marker file, or fails when FAKE_IMG2WEBP_FAIL is set."""
    import os, sys

    args = sys.argv[1:]
    log = os.environ.get("FAKE_IMG2WEBP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    if os.environ.get("FAKE_IMG2WEBP_FAIL"):
        sys.stderr.write("fake-img2webp: told to fail\\n")
        sys.exit(1)
    with open(args[args.index("-o") + 1], "wb") as handle:
        handle.write(b"fake webp")
'''

FAKE_DOCKER = '''
    """Stands in for docker: logs each call, and plays the helper for `run`.

    build: reads the tar on stdin and writes down the names in it. Fails when FAKE_DOCKER_FAIL=build.
    image inspect: fails for an image named in FAKE_DOCKER_MISSING. Otherwise prints the labels,
        with FAKE_DOCKER_BUILD as the build of howto when it is set.
    run: answers requests as a helper would. `refuse` is refused, `noise` writes a line that is
        no reply first, `hang` never answers, `die` ends with a message, and anything else gets
        its fields back.
    cp: writes a tar with one file, whose content is FAKE_DOCKER_FILE.
    volume: `inspect` fails for a volume named in FAKE_DOCKER_NO_VOLUME. `create` prints the name.
    port: prints 127.0.0.1:49153.
    Every call fails when FAKE_DOCKER_DOWN is set, as with a daemon that is not running.
    """
    import io, json, os, sys, tarfile, time

    args = sys.argv[1:]
    log = os.environ["FAKE_DOCKER_LOG"]
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
    if os.environ.get("FAKE_DOCKER_DOWN"):
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\\n")
        sys.exit(1)
    command = args[0]
    if command == "build":
        with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as tar:
            names = sorted(tar.getnames())
        with open(log + ".context", "w", encoding="utf-8") as handle:
            json.dump(names, handle)
        sys.exit(1 if os.environ.get("FAKE_DOCKER_FAIL") == "build" else 0)
    if command == "image":
        image = args[-1]
        if image in os.environ.get("FAKE_DOCKER_MISSING", "").split():
            sys.stderr.write(f"Error response from daemon: No such image: {image}\\n")
            sys.exit(1)
        build = os.environ.get("FAKE_DOCKER_BUILD")
        print(json.dumps({"howto.build": build} if build else None))
        sys.exit(0)
    if command == "volume":
        name = args[-1]
        if args[1] == "inspect" and name in os.environ.get("FAKE_DOCKER_NO_VOLUME", "").split():
            sys.stderr.write(f"Error response from daemon: get {name}: no such volume\\n")
            sys.exit(1)
        print(name)
        sys.exit(0)
    if command == "port":
        print("127.0.0.1:49153")
        sys.exit(0)
    if command == "cp":
        data = os.environ.get("FAKE_DOCKER_FILE", "the file").encode()
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
            info = tarfile.TarInfo("fetched")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        sys.exit(0)
    if command == "run":
        for line in sys.stdin:
            request = json.loads(line)
            name = request["request"]
            if name == "hang":
                time.sleep(60)
            if name == "die":
                sys.stderr.write("the helper fell over\\n")
                sys.exit(3)
            if name == "noise":
                print("a line that is no reply", flush=True)
            if name == "refuse":
                reply = {"id": request["id"], "ok": False, "kind": "covered", "error": "another window covers it"}
            else:
                fields = {key: value for key, value in request.items() if key not in ("id", "request")}
                reply = {"id": request["id"], "ok": True, "fields": fields}
            print(json.dumps(reply), flush=True)
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
    return SimpleNamespace(cache=cache, data=data, clips=cache / "clips", work=cache / "work", voices=data / "voices")


@pytest.fixture
def fake_tts(tmp_path, monkeypatch, sandbox):
    """A fake `tts` on HOWTO_TTS. `spoken()` lists the sentences it was asked to speak."""
    program = _script(tmp_path / "fake-tts", FAKE_TTS)
    log = tmp_path / "tts.log"
    monkeypatch.setenv("HOWTO_TTS", str(program))
    monkeypatch.setenv("FAKE_TTS_LOG", str(log))
    monkeypatch.delenv("FAKE_TTS_FAIL", raising=False)
    monkeypatch.delenv("FAKE_TTS_SILENT", raising=False)
    arguments = Path(f"{log}.args")

    def spoken() -> list[str]:
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def calls() -> list[list[str]]:
        """The arguments of every call."""
        if not arguments.exists():
            return []
        return [json.loads(line) for line in arguments.read_text(encoding="utf-8").splitlines()]

    return SimpleNamespace(program=str(program), spoken=spoken, calls=calls)


@pytest.fixture
def fakes(tmp_path, monkeypatch, sandbox, fake_tts):
    """Fake tts, ffmpeg, ffprobe and img2webp together, for tests that must not run the real programs."""
    ffmpeg = _script(tmp_path / "fake-ffmpeg", FAKE_FFMPEG)
    ffprobe = _script(tmp_path / "fake-ffprobe", FAKE_FFPROBE)
    img2webp = _script(tmp_path / "fake-img2webp", FAKE_IMG2WEBP)
    monkeypatch.setenv("HOWTO_FFMPEG", str(ffmpeg))
    monkeypatch.setenv("HOWTO_FFPROBE", str(ffprobe))
    monkeypatch.setenv("HOWTO_IMG2WEBP", str(img2webp))
    for name in ("FAKE_FFMPEG_FAIL", "FAKE_FFPROBE_DURATION", "FAKE_IMG2WEBP_FAIL"):
        monkeypatch.delenv(name, raising=False)
    return SimpleNamespace(
        tts=fake_tts, ffmpeg=str(ffmpeg), ffprobe=str(ffprobe), img2webp=str(img2webp), sandbox=sandbox
    )


SITE = Path(__file__).parent / "fixtures" / "site"
SITE_REQUESTS: list[str] = []


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    """A fake `docker` on HOWTO_DOCKER. `calls()` lists the arguments of every call."""
    program = _script(tmp_path / "fake-docker", FAKE_DOCKER)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("HOWTO_DOCKER", str(program))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    for name in ("FAKE_DOCKER_DOWN", "FAKE_DOCKER_FAIL", "FAKE_DOCKER_MISSING", "FAKE_DOCKER_BUILD", "FAKE_DOCKER_FILE", "FAKE_DOCKER_NO_VOLUME"):
        monkeypatch.delenv(name, raising=False)

    def calls() -> list[list[str]]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def context() -> list[str]:
        """The names in the tar that the last build was given."""
        return json.loads(Path(f"{log}.context").read_text(encoding="utf-8"))

    return SimpleNamespace(program=str(program), calls=calls, context=context)

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
    """Skips a browser test on a machine without Playwright's Chromium.

    A skipped browser test is not a pass. Where the browser tests have to
    run, HOWTO_REQUIRE_BROWSER=1 turns the skip into a failure.
    """
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Error as exc:
        reason = f"Playwright's Chromium is not installed: {str(exc).splitlines()[0]}"
        if os.environ.get("HOWTO_REQUIRE_BROWSER"):
            pytest.fail(reason)
        pytest.skip(reason)

FIXTURE_IMAGE = "howto-test-fixture"


@pytest.fixture(scope="session")
def desktop():
    """Skips a desktop test on a machine without Docker or without the base image of this build.

    A skipped desktop test is not a pass. Where the desktop tests have to
    run, HOWTO_REQUIRE_DESKTOP=1 turns the skip into a failure. The image of
    the fixture app is built here, from tests/fixtures/desktop.
    """
    from howto.desktop import images
    from howto.errors import RunError
    from howto.tools import docker_command

    try:
        docker = docker_command()
        images.check(docker, images.BASE)
    except RunError as exc:
        if os.environ.get("HOWTO_REQUIRE_DESKTOP"):
            pytest.fail(str(exc))
        pytest.skip(str(exc))
    # The build goes in as a tar on stdin, as the base image's does.
    data = io.BytesIO()
    # GNU_FORMAT: pax writes a ././@PaxHeader member for a fractional mtime, and BuildKit reads it as the Dockerfile.
    with tarfile.open(fileobj=data, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path in sorted((Path(__file__).parent / "fixtures" / "desktop").iterdir()):
            tar.add(path, arcname=path.name)
    built = subprocess.run([*docker, "build", "-q", "-t", FIXTURE_IMAGE, "-"], input=data.getvalue(), capture_output=True)
    assert built.returncode == 0, built.stderr.decode("utf-8", "replace")[-2000:]
    return SimpleNamespace(docker=docker, image=FIXTURE_IMAGE, run="python3 /opt/fixture/app.py")
