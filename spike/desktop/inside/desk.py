"""A desktop in a container: a monitor, the buses, a window manager, an app, and the tree.

box.inside puts this file in front of each measurement, so its names are just there.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

RUNTIME = "/tmp/howto"
MONITOR = [0, 0]
APPS = {
    "gtk3": "gedit",
    "gtk4": "gnome-calculator",
    "qt": "featherpad",
    "electron": "/usr/share/code/code --no-sandbox --disable-gpu --user-data-dir=/tmp/code",
}
# What is expected to make each toolkit publish its tree.
A11Y_ENV = {
    "GTK_MODULES": "gail:atk-bridge",
    "QT_ACCESSIBILITY": "1",
    "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1",
    "ACCESSIBILITY_ENABLED": "1",
    "GNOME_ACCESSIBILITY": "1",
}
# What is expected to make each toolkit draw at twice the size.
SCALE_ENV = {"GDK_SCALE": "2", "GDK_DPI_SCALE": "0.5", "QT_SCALE_FACTOR": "2", "QT_FONT_DPI": "96", "XCURSOR_SIZE": "48"}


def sh(*command, **options):
    return subprocess.run(command, capture_output=True, text=True, **options)


def wait(test, seconds, what):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return
        time.sleep(0.1)
    said = open("/tmp/app.log").read()[-1500:] if os.path.exists("/tmp/app.log") else ""
    raise SystemExit(f"timed out waiting for {what}\n{said}")


def desk(width=1920, height=1080, scale=1, wm="openbox"):
    """Starts the monitor, the session bus, the accessibility bus and a window manager."""
    MONITOR[:] = [width * scale, height * scale]
    os.makedirs(RUNTIME, mode=0o700, exist_ok=True)
    os.environ.update(
        DISPLAY=":99", XDG_RUNTIME_DIR=RUNTIME, DBUS_SESSION_BUS_ADDRESS=f"unix:path={RUNTIME}/bus",
        XCURSOR_THEME="Adwaita", **A11Y_ENV,
    )
    if scale > 1:
        os.environ.update(SCALE_ENV)
    quiet = subprocess.DEVNULL
    subprocess.Popen(["Xvfb", ":99", "-screen", "0", f"{MONITOR[0]}x{MONITOR[1]}x24", "-nolisten", "tcp"], stderr=quiet)
    wait(lambda: os.path.exists("/tmp/.X11-unix/X99"), 10, "Xvfb")
    subprocess.Popen(["dbus-daemon", "--session", f"--address=unix:path={RUNTIME}/bus", "--nofork"], stderr=quiet)
    wait(lambda: os.path.exists(f"{RUNTIME}/bus"), 10, "the session bus")
    subprocess.Popen(["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"], stderr=quiet)
    owner = ("dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
             "org.freedesktop.DBus.NameHasOwner", "string:org.a11y.Bus")
    wait(lambda: "true" in sh(*owner).stdout, 10, "the accessibility bus")
    for flag in ("IsEnabled", "ScreenReaderEnabled"):
        sh("dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus", "/org/a11y/bus",
           "org.freedesktop.DBus.Properties.Set", "string:org.a11y.Status", f"string:{flag}", "variant:boolean:true")
    if scale > 1:
        # Without -nocpp, xrdb hands its input to the C preprocessor, which this image does not have, and merges nothing.
        subprocess.run(["xrdb", "-nocpp", "-merge"], input=f"Xft.dpi: {96 * scale}\n", text=True, check=True)
    sh("xsetroot", "-solid", "#30343c", "-cursor_name", "left_ptr")
    if wm:
        subprocess.Popen(["openbox", "--sm-disable"] if wm == "openbox" else [wm], stderr=quiet)
        wait(lambda: "window id" in sh("xprop", "-root", "_NET_SUPPORTING_WM_CHECK").stdout, 10, "the window manager")


def launch(command):
    """Starts an app as a line of shell. Its output goes to /tmp/app.log."""
    log = open("/tmp/app.log", "ab")
    return subprocess.Popen(["sh", "-c", command], stdout=log, stderr=log, start_new_session=True)


def windows():
    """The windows that the window manager has, each with its id, pid, place, size and title."""
    found = []
    for line in sh("wmctrl", "-lGp").stdout.splitlines():
        parts = line.split(None, 8)
        if len(parts) >= 8:
            found.append({"id": parts[0], "pid": int(parts[2]), "x": int(parts[3]), "y": int(parts[4]),
                          "w": int(parts[5]), "h": int(parts[6]), "title": parts[8] if len(parts) > 8 else ""})
    return found


def first_window(seconds=60):
    wait(windows, seconds, "the first window of the app")
    return windows()[0]


def fill(window):
    """Makes a window fill the monitor.

    The hints that take the title bar off work only when openbox first maps a
    window, so they are set before the window is mapped here and not after: a
    window that is maximized first keeps no frame of its own, and then a move
    and a size put it on the whole monitor.
    """
    sh("wmctrl", "-i", "-r", window["id"], "-b", "add,maximized_vert,maximized_horz")
    time.sleep(1)  # openbox ignores a move of a window that is still settling
    sh("wmctrl", "-i", "-r", window["id"], "-e", f"0,0,{MONITOR[0]},{MONITOR[1]}")
    end = time.monotonic() + 10
    while time.monotonic() < end:
        for w in windows():
            if w["id"] == window["id"] and [w["w"], w["h"]] == MONITOR:
                return
        time.sleep(0.1)
    # A window that keeps a frame of its own is measured as it stands: the number is written down.
    for w in windows():
        if w["id"] == window["id"]:
            print(f"note: {w['title']!r} is {w['w']}x{w['h']} at {w['x']},{w['y']} instead of the monitor",
                  file=sys.stderr)
            return
    print("note: the window left the window manager", file=sys.stderr)


def shot(path):
    """A PNG of the monitor, without the pointer."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "0",
                    "-video_size", f"{MONITOR[0]}x{MONITOR[1]}", "-i", ":99", "-frames:v", "1", path], check=True)


def walk(limit=5000):
    """Every window that is showing, read from the accessibility bus: a flat list in the order of the tree."""
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    found = []

    def visit(node, depth, toolkit):
        if len(found) >= limit or depth > 60:
            return
        try:
            showing = node.get_state_set().contains(Atspi.StateType.SHOWING)
            try:
                rect = Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN)
                where = [rect.x, rect.y, rect.width, rect.height]
            except Exception:
                where = [0, 0, 0, 0]
            found.append({"role": node.get_role_name(), "name": node.get_name() or "", "box": where,
                          "showing": showing, "depth": depth, "toolkit": toolkit})
            if showing:
                for index in range(min(node.get_child_count(), 300)):
                    visit(node.get_child_at_index(index), depth + 1, toolkit)
        except Exception as exc:
            found.append({"role": "error", "name": str(exc)[:80], "box": [0, 0, 0, 0],
                          "showing": False, "depth": depth, "toolkit": toolkit})

    desktop = Atspi.get_desktop(0)
    for a in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(a)
        for w in range(app.get_child_count()):
            visit(app.get_child_at_index(w), 0, app.get_toolkit_name() or "")
    return found
