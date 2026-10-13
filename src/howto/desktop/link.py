"""The link to the helper: a Docker container, and one JSON object on each line of its stdin and stdout.

The container lives as long as the pipe. When howto ends, however it ends,
the pipe closes, the helper leaves, and Docker removes the container.

A VM would be a second link: whatever starts a helper and carries these lines.
"""
from __future__ import annotations

import collections
import io
import json
import os
import select
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
from pathlib import Path

from ..errors import RunError

# How many of the helper's last lines on stderr are kept for an error message.
TAIL = 12


class HelperError(Exception):
    """The helper answered that it could not do what was asked. `kind` says what happened."""

    def __init__(self, kind: str, error: str) -> None:
        super().__init__(error)
        self.kind = kind


class Link:
    def __init__(self, process: subprocess.Popen, docker: list[str], name: str) -> None:
        self._process = process
        self._docker = docker
        self.name = name
        self._number = 0
        self._unread = b""
        self._said: collections.deque[str] = collections.deque(maxlen=TAIL)
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()

    def _listen(self) -> None:
        for line in io.BufferedReader(self._process.stderr):
            self._said.append(line.decode("utf-8", "replace").rstrip())

    def _stopped(self) -> RunError:
        # The helper's last lines arrive a moment after its pipe closes.
        self._listener.join(timeout=2)
        said = "\n".join(self._said)
        return RunError("the desktop stopped" + (f":\n{said}" if said else ""))

    def _line(self, deadline: float) -> bytes | None:
        """The next line of the helper's stdout. None when the time is over."""
        out = self._process.stdout
        while b"\n" not in self._unread:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([out], [], [], min(left, 0.5))
            if not ready:
                continue
            chunk = os.read(out.fileno(), 65536)
            if not chunk:
                raise self._stopped()
            self._unread += chunk
        line, _, self._unread = self._unread.partition(b"\n")
        return line

    def request(self, request: str, *, limit: float, **fields) -> dict:
        """Sends one request and waits for its reply, for `limit` seconds at most."""
        self._number += 1
        message = (json.dumps({"id": self._number, "request": request, **fields}) + "\n").encode("utf-8")
        try:
            view = memoryview(message)
            while view:
                view = view[os.write(self._process.stdin.fileno(), view):]
        except (OSError, ValueError):
            raise self._stopped() from None
        deadline = time.monotonic() + limit
        while True:
            line = self._line(deadline)
            if line is None:
                raise RunError(f"the desktop stopped answering: `{request}` got no reply in {limit:g} seconds")
            try:
                reply = json.loads(line)
            except ValueError:
                reply = None
            if not isinstance(reply, dict) or reply.get("id") != self._number:
                # Not the protocol: something else wrote to the pipe. It is kept as something the helper said.
                self._said.append(line.decode("utf-8", "replace"))
                continue
            if reply.get("ok"):
                return reply
            raise HelperError(str(reply.get("kind", "internal")), str(reply.get("error", "it gave no reason")))

    def fetch(self, inside: str, out: Path) -> None:
        """Copies one file out of the container.

        Docker writes it as a tar on its stdout, so it needs no folder of the
        host. The file is written here, under the name that the caller chose.
        """
        proc = subprocess.Popen(
            [*self._docker, "cp", f"{self.name}:{inside}", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        copied = False
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                for member in tar:
                    if member.isfile() and not copied:
                        with open(out, "wb") as target:
                            shutil.copyfileobj(tar.extractfile(member), target)
                        copied = True
        except tarfile.TarError:
            copied = False
        said = proc.stderr.read().decode("utf-8", "replace").strip().splitlines()
        if proc.wait() != 0 or not copied:
            raise RunError(f"cannot fetch {inside} from the desktop: {said[-1] if said else 'Docker sent no file'}")

    def port(self, inside: int) -> int:
        """The port of this machine at which Docker serves a port of the container."""
        proc = subprocess.run(
            [*self._docker, "port", self.name, f"{inside}/tcp"], capture_output=True, text=True, errors="replace"
        )
        lines = proc.stdout.strip().splitlines()
        try:
            # A line is an address and a port, as `127.0.0.1:49153`.
            return int(lines[0].rsplit(":", 1)[1])
        except (IndexError, ValueError):
            said = proc.stderr.strip().splitlines()
            raise RunError(
                f"Docker does not say where port {inside} of the desktop is: {said[-1] if said else 'it gave no port'}"
            ) from None

    def close(self, wait: float = 10.0) -> None:
        """Ends the container. The helper leaves when its stdin closes. A container that stays is removed."""
        process = self._process
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            subprocess.run([*self._docker, "rm", "-f", self.name], capture_output=True)
            process.kill()
            process.wait()
        self._listener.join(timeout=2)
        process.stdout.close()
        process.stderr.close()


def open_link(docker: list[str], image: str, *, volume: str | None = None, publish: int | None = None) -> Link:
    """Starts a container of an image, whose main process is the helper.

    `volume` is the Docker volume of a profile. It becomes the home of the
    app's user. `publish` is a port of the container that Docker serves on
    this machine, at a port that it chooses: `Link.port` tells which.
    """
    name = f"howto-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    command = [*docker, "run", "--rm", "-i", "--init", "--shm-size=1g", "--name", name]
    if volume is not None:
        # A volume that is new gets what the image has in that folder, with its owner.
        command += ["-v", f"{volume}:/home/howto"]
    if publish is not None:
        # On this machine only. No other machine of the network reaches it.
        command += ["-p", f"127.0.0.1::{publish}"]
    command.append(image)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            # A session of its own: Ctrl+C in the terminal reaches howto only, and cleanup still has a desktop.
            start_new_session=True,
        )
    except OSError as exc:
        raise RunError(f"cannot start Docker: {exc.strerror or exc}") from None
    return Link(process, docker, name)
