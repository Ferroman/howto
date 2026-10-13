"""A window on the monitor of the container: the helper's noVNC page, in the Chromium that howto has."""
from __future__ import annotations

import tempfile
from urllib.parse import urlencode

from ..errors import RunError

# The port of the container at which the helper serves noVNC. `helper/watch.py` has the same number.
PORT = 6080


def address(port: int, password: str, *, view_only: bool) -> str:
    """The page that shows the monitor. `port` is the port of this machine that Docker chose."""
    options = {"autoconnect": "1", "resize": "scale", "reconnect": "0", "password": password}
    if view_only:
        # The server refuses input already. This keeps the page from offering it.
        options["view_only"] = "1"
    return f"http://127.0.0.1:{port}/vnc.html?{urlencode(options)}"


class Viewer:
    """A window of Chromium on one page. `wait` returns when the person closes it."""

    def __init__(self, url: str, *, headless: bool = False) -> None:
        from playwright.sync_api import Error, sync_playwright

        self._error = Error
        self._scratch = tempfile.TemporaryDirectory(prefix="howto-viewer-")
        self._playwright = sync_playwright().start()
        self._context = None
        try:
            # Ctrl+C stays with howto, which still has a container to end.
            self._context = self._playwright.chromium.launch_persistent_context(
                self._scratch.name, headless=headless, no_viewport=not headless, handle_sigint=False
            )
            self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self.page.goto(url)
        except Error as exc:
            self.close()
            lines = str(exc).strip().splitlines()
            raise RunError(f"cannot open the window: {lines[0] if lines else type(exc).__name__}") from None

    def wait(self) -> None:
        """Returns when the person has closed the window."""
        try:
            self._context.wait_for_event("close", timeout=0)
        except self._error:
            pass  # the window is already gone

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except self._error:
                pass  # the person closed it
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._scratch.cleanup()
