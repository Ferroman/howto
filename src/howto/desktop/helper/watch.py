"""A window on the monitor for a person: a VNC server on the display, and noVNC to reach it from a browser.

Neither runs unless it is asked for. A probe and a take show their monitor
to nobody.
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import time

from .session import DISPLAY, RUNTIME

VNC_PORT = 5900
WEB_PORT = 6080
NOVNC = "/usr/share/novnc"
PASSWORD_FILE = f"{RUNTIME}/vnc-password"


def vnc_command(view_only: bool) -> list[str]:
    """The VNC server on the helper's monitor. Only noVNC, in the same container, reaches it."""
    command = [
        "x11vnc", "-display", DISPLAY, "-rfbport", str(VNC_PORT), "-localhost", "-forever", "-shared",
        "-passwdfile", PASSWORD_FILE, "-quiet",
    ]
    # With -viewonly the server drops every key and every click, whatever a client sends.
    return [*command, "-viewonly"] if view_only else command


def web_command() -> list[str]:
    """noVNC: a page that a browser loads, and the bridge from its WebSocket to the VNC server."""
    return ["websockify", "--web", NOVNC, str(WEB_PORT), f"localhost:{VNC_PORT}"]


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


class Watch:
    def __init__(self) -> None:
        self._started: list[subprocess.Popen] = []
        self.password = ""

    def start(self, view_only: bool) -> str:
        """Starts the two servers, and returns the password of this run. A second call returns the same."""
        if self._started:
            return self.password
        # A VNC password counts for its first eight characters, so it has eight.
        self.password = secrets.token_hex(4)
        descriptor = os.open(PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(self.password + "\n")
        for command, port, what in ((vnc_command(view_only), VNC_PORT, "x11vnc"), (web_command(), WEB_PORT, "noVNC")):
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._started.append(process)
            end = time.monotonic() + 15
            while not listening(port):
                if time.monotonic() >= end or process.poll() is not None:
                    raise RuntimeError(f"{what} did not start")
                time.sleep(0.1)
        return self.password

    def stop(self) -> None:
        for process in reversed(self._started):
            if process.poll() is None:
                process.terminate()
        self._started = []
