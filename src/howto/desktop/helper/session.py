"""The desktop inside the container: a monitor, the buses, a window manager, and the app.

Every program here is one of the image. Nothing is asked of the host.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

DISPLAY = ":99"
RUNTIME = "/tmp/howto"
APP_LOG = f"{RUNTIME}/app.log"
# What makes each toolkit publish its tree, as spike/desktop/tree.py measured it.
A11Y_ENV = {
    "GTK_MODULES": "gail:atk-bridge",
    "QT_ACCESSIBILITY": "1",
    "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1",
    "ACCESSIBILITY_ENABLED": "1",
    "GNOME_ACCESSIBILITY": "1",
}
WINDOW_MANAGER = ["openbox", "--sm-disable"]
# The kinds of window that are an app's own first window. A splash screen is not one.
OWN_WINDOWS = ("_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG")
BUS_HAS_OWNER = (
    "dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
    "org.freedesktop.DBus.NameHasOwner", "string:org.a11y.Bus",
)


@dataclass(frozen=True)
class Window:
    id: str
    pid: int
    x: int
    y: int
    width: int
    height: int
    title: str


def parse_windows(listing: str) -> list[Window]:
    """The windows of `wmctrl -lGp`: an id, a desktop, a pid, a place, a size, a machine and a title on each line."""
    windows = []
    for line in listing.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        try:
            pid, x, y, width, height = (int(part) for part in parts[2:7])
        except ValueError:
            continue
        windows.append(Window(parts[0], pid, x, y, width, height, parts[8] if len(parts) > 8 else ""))
    return windows


def quiet(*command: str, **options) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, errors="replace", **options)


def until(test, seconds: float) -> bool:
    """Whether `test` came true within the time."""
    end = time.monotonic() + seconds
    while True:
        if test():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.1)


class Session:
    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.env = dict(os.environ)
        self.first: Window | None = None
        self._started: list[subprocess.Popen] = []
        self._app: subprocess.Popen | None = None

    def _spawn(self, command: list[str]) -> None:
        self._started.append(
            subprocess.Popen(command, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        )

    def _need(self, test, what: str) -> None:
        if not until(test, 15):
            raise RuntimeError(f"{what} did not start")

    def start(self) -> None:
        """The monitor, the session bus, the accessibility bus and the window manager, in that order."""
        os.makedirs(RUNTIME, mode=0o700, exist_ok=True)
        self.env.update(
            DISPLAY=DISPLAY, XDG_RUNTIME_DIR=RUNTIME, DBUS_SESSION_BUS_ADDRESS=f"unix:path={RUNTIME}/bus",
            XCURSOR_THEME="Adwaita", **A11Y_ENV,
        )
        # Whatever the helper itself runs or asks later must find the same monitor and the same bus.
        os.environ.update(self.env)
        self._spawn(["Xvfb", DISPLAY, "-screen", "0", f"{self.width}x{self.height}x24", "-nolisten", "tcp"])
        self._need(lambda: os.path.exists("/tmp/.X11-unix/X99"), "the monitor")
        self._spawn(["dbus-daemon", "--session", f"--address=unix:path={RUNTIME}/bus", "--nofork"])
        self._need(lambda: os.path.exists(f"{RUNTIME}/bus"), "the session bus")
        self._spawn(["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"])
        self._need(lambda: "true" in quiet(*BUS_HAS_OWNER).stdout, "the accessibility bus")
        for flag in ("IsEnabled", "ScreenReaderEnabled"):
            quiet(
                "dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus", "/org/a11y/bus",
                "org.freedesktop.DBus.Properties.Set", "string:org.a11y.Status", f"string:{flag}", "variant:boolean:true",
            )
        quiet("xsetroot", "-solid", "#30343c", "-cursor_name", "left_ptr")
        self._spawn(WINDOW_MANAGER)
        self._need(lambda: "window id" in quiet("xprop", "-root", "_NET_SUPPORTING_WM_CHECK").stdout, "the window manager")

    def launch(self, command: str) -> None:
        """Starts the app as a line of shell. What it prints goes to a file, for an error message."""
        log = open(APP_LOG, "ab")
        self._app = subprocess.Popen(
            ["sh", "-c", command], env=self.env, cwd=self.env.get("HOME", "/"), stdout=log, stderr=log,
            start_new_session=True,
        )

    def windows(self) -> list[Window]:
        return parse_windows(quiet("wmctrl", "-lGp").stdout)

    def said(self) -> str:
        """The last lines that the app printed."""
        try:
            with open(APP_LOG, encoding="utf-8", errors="replace") as log:
                return "\n".join(log.read().strip().splitlines()[-8:])
        except OSError:
            return ""

    def exit_code(self) -> int | None:
        """The exit code of the app's command. None while it runs."""
        return self._app.poll() if self._app is not None else None

    def ended(self) -> int | None:
        """The app's exit code, once its command has ended and no window is left. None while there is an app.

        A command that only starts the app and ends leaves windows behind, and that app has not ended.
        """
        code = self.exit_code()
        return None if code is None or self.windows() else code

    def first_window(self, seconds: float) -> Window | None:
        """Waits for the first window of the app. None when the time is over, or when the app failed without one."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for window in self.windows():
                kind = quiet("xprop", "-id", window.id, "_NET_WM_WINDOW_TYPE").stdout
                if "=" not in kind or any(own in kind for own in OWN_WINDOWS):
                    self.first = window
                    return window
            if self.exit_code() not in (None, 0):
                return None
            time.sleep(0.2)
        return None

    def fill(self, window: Window) -> None:
        """Takes the title bar off a window and makes it fill the monitor."""
        quiet("xprop", "-id", window.id, "-f", "_MOTIF_WM_HINTS", "32c", "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0")
        quiet("wmctrl", "-i", "-r", window.id, "-b", "add,maximized_vert,maximized_horz")
        # A window that refuses is left as it is: a dialog of a fixed size is still an app.
        until(lambda: any(w.id == window.id and (w.width, w.height) == (self.width, self.height) for w in self.windows()), 5)
        # The app lays itself out again for the new size.
        time.sleep(0.5)

    def title(self) -> str:
        """The title that the first window has now. An app changes it as it works."""
        if self.first is None:
            return ""
        return next((window.title for window in self.windows() if window.id == self.first.id), "")

    def stop(self) -> None:
        for process in [self._app, *reversed(self._started)]:
            if process is not None and process.poll() is None:
                process.terminate()
