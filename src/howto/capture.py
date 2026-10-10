"""The Playwright side: a browser that performs actions, records itself and describes its page.

This is the only module that imports Playwright.
"""
from __future__ import annotations

import html
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .errors import RunError
from .probe import cut_outline
from .runner import Interrupt, PageReport, StepFailed
from .storyboard import Action, Locator, Pace, Storyboard

DEFAULT_TIMEOUT = 10.0
# A probe describes the page a moment after the last action. The browser
# reports a new tab only some 0.1 to 0.2 s after the click that opened it, and
# there is no event that says "no tab is coming", so the wait is a fixed one.
SETTLE_MS = 300
NOTE_STYLE = (
    "position:fixed;left:50%;bottom:48px;transform:translateX(-50%);max-width:70%;"
    "padding:14px 22px;border-radius:10px;background:rgba(20,20,24,.88);color:#fff;"
    "font:500 22px/1.35 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35)"
)
# show_actions also writes each action's locator on the picture, for example
# `Click get_by_role("button", name="Save")`, and has no option that turns it
# off. An overlay may carry a style element, and this rule hides the element
# that holds the label. The element's name is Playwright's own: check it when
# the pinned version changes.
HIDE_ACTION_LABEL = "<style>x-pw-title{display:none!important}</style>"


def action_timeout() -> float:
    """Seconds an element gets to appear."""
    try:
        seconds = float(os.environ.get("HOWTO_ACTION_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def note_html(text: str) -> str:
    return f'<div style="{NOTE_STYLE}">{html.escape(text)}</div>'


def resolve(scope, locator: Locator):
    """The Playwright locator for a storyboard locator. `scope` is a page or a locator."""
    if locator.within is not None:
        scope = resolve(scope, locator.within)
    exact = locator.exact or None
    if locator.role is not None:
        found = scope.get_by_role(locator.role, name=locator.name, exact=exact)
    elif locator.label is not None:
        found = scope.get_by_label(locator.label, exact=exact)
    elif locator.placeholder is not None:
        found = scope.get_by_placeholder(locator.placeholder, exact=exact)
    elif locator.text is not None:
        found = scope.get_by_text(locator.text, exact=exact)
    elif locator.testid is not None:
        found = scope.get_by_test_id(locator.testid)
    else:
        found = scope.locator(locator.css)
    return found.nth(locator.nth) if locator.nth is not None else found


def _remove(overlay) -> None:
    """Takes an overlay off the page.

    In this release's synchronous API the overlay's close() returns a
    coroutine that nobody runs, so it removes nothing. Leaving a `with` block
    is what removes it, and this is that call.
    """
    overlay.__exit__(None, None, None)


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


# What Playwright's call log says about an element that it found but could not use.
BLOCKED = re.compile(r"intercepts pointer events|element is not \w+|outside of the viewport")


def failure_reason(message: str) -> str:
    """One line that says why an action failed.

    A timeout's first line says only that time ran out. The call log below it
    says why: the element is disabled, or another element covers it. The
    reader, usually a model, needs that to fix the storyboard, so the last
    such line is added.
    """
    lines = message.strip().splitlines()
    if not lines:
        return "unknown error"
    first = lines[0].strip()
    why = [line.strip(" -") for line in lines[1:] if BLOCKED.search(line)]
    return f"{first.rstrip('.')}: {why[-1]}" if why else first


class PlaywrightStage:
    def __init__(
        self, page: Page, viewport: tuple[int, int], timeout: float, interrupt: Interrupt | None = None
    ) -> None:
        self.page = page
        self.viewport = viewport
        self.timeout_ms = timeout * 1000
        self._interrupt = interrupt or Interrupt()
        self._label_rule = None
        self._note = None
        self._dialogs: list[str] = []
        self._tabs: list[Page] = []
        page.on("dialog", self._on_dialog)
        page.context.on("page", self._on_tab)

    def _on_dialog(self, dialog) -> None:
        """Answers a browser dialog as Playwright would without a listener, and keeps a note of it.

        A dismissed confirm means that the action behind it did not happen,
        while the click that opened it succeeded. Without the note a probe
        would report the step as ok and say nothing.
        """
        if dialog.type == "beforeunload":
            dialog.accept()
            return
        self._dialogs.append(f'a {dialog.type} dialog was dismissed: "{dialog.message}"')
        dialog.dismiss()

    def _on_tab(self, tab: Page) -> None:
        self._tabs.append(tab)

    def _notices(self) -> tuple[str, ...]:
        notices = list(self._dialogs)
        for tab in self._tabs:
            try:
                tab.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
                address = tab.url
            except PlaywrightError:
                address = "(closed)"
            notices.append(f"a new tab opened and the steps stay in the first one: {address}")
        return tuple(notices)

    def _one(self, action: Action):
        """The single element an action names. None or several is an error: the tool does not guess."""
        target = resolve(self.page, action.locator)
        try:
            target.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightTimeout:
            raise StepFailed(f"{action.describe()}: 0 elements match") from None
        count = target.count()
        if count != 1:
            raise StepFailed(f"{action.describe()}: {count} elements match")
        return target

    def perform(self, action: Action, pace: Pace) -> None:
        self._interrupt.check()
        try:
            self._act(action, pace)
        finally:
            # Before and after the browser call, never during it: see Interrupt.
            # A request to stop outranks the outcome of the action.
            self._interrupt.check()

    def _act(self, action: Action, pace: Pace) -> None:
        try:
            if action.kind == "goto":
                self.page.goto(action.value, timeout=self.timeout_ms * 3)
            elif action.kind == "press":
                self.page.keyboard.press(action.value)
            else:
                target = self._one(action)
                if action.kind == "click":
                    target.click(timeout=self.timeout_ms)
                elif action.kind == "fill":
                    # Typed key by key, so the viewer sees the text appear.
                    target.click(timeout=self.timeout_ms)
                    target.fill("", timeout=self.timeout_ms)
                    target.press_sequentially(action.value, delay=1000 / pace.typing)
                elif action.kind == "select":
                    target.select_option(label=action.value, timeout=self.timeout_ms)
                elif action.kind == "hover":
                    target.hover(timeout=self.timeout_ms)
                elif action.kind == "scroll_to":
                    target.scroll_into_view_if_needed(timeout=self.timeout_ms)
                # wait_for needs nothing more: `_one` already waited for the element.
        except PlaywrightError as exc:
            raise StepFailed(f"{action.describe()}: {failure_reason(str(exc))}") from None

    def start_recording(self, path: Path) -> None:
        width, height = self.viewport
        self.page.screencast.start(path=str(path), size={"width": width, "height": height})
        self.page.screencast.show_actions(cursor="pointer")
        self._label_rule = self.page.screencast.show_overlay(HIDE_ACTION_LABEL)

    def stop_recording(self) -> None:
        if self._label_rule is not None:
            # Cleanup runs after this, and it should not wait for a pointer to be drawn.
            self.page.screencast.hide_actions()
            _remove(self._label_rule)
            self._label_rule = None
        self.page.screencast.stop()

    def show_chapter(self, title: str, seconds: float) -> None:
        self.page.screencast.show_chapter(title, duration=seconds * 1000)

    def show_note(self, text: str) -> None:
        self._note = self.page.screencast.show_overlay(note_html(text))

    def hide_note(self) -> None:
        if self._note is not None:
            _remove(self._note)
            self._note = None

    def report(self, within: Locator | None, max_chars: int) -> PageReport:
        # A page that crashed or was closed still gets a report, so that a
        # probe can print which steps ran before it went away.
        scope = resolve(self.page, within) if within is not None else self.page.locator("body")
        try:
            self.page.wait_for_timeout(SETTLE_MS)
            outline = scope.first.aria_snapshot(timeout=self.timeout_ms)
        except PlaywrightError as exc:
            outline = f"(no outline: {_first_line(exc)})"
        try:
            title = self.page.title()
        except PlaywrightError:
            title = ""
        kept, omitted = cut_outline(outline, max_chars)
        return PageReport(url=self.page.url, title=title, outline=kept, omitted=omitted, notices=self._notices())


@contextmanager
def open_stage(
    storyboard: Storyboard, *, profiles_dir: Path, headless: bool = True, interrupt: Interrupt | None = None
) -> Iterator[PlaywrightStage]:
    """A browser with the storyboard's profile and viewport, and its start page open.

    With an `interrupt`, the caller handles Ctrl+C itself, and Playwright must
    not close the browser on it, because cleanup still needs the browser.
    SIGTERM stays with Playwright: its driver is a process of its own, and
    without a handler it exits on SIGTERM, after which every browser call
    waits forever. With the handler it closes the browser and stays.
    """
    width, height = storyboard.viewport
    timeout = action_timeout()
    with tempfile.TemporaryDirectory(prefix="howto-profile-") as scratch:
        if storyboard.profile:
            user_data = profiles_dir / storyboard.profile
            if not user_data.is_dir():
                raise RunError(
                    f"profile `{storyboard.profile}` does not exist: "
                    f"run `howto login {storyboard.profile} {storyboard.url}`"
                )
        else:
            user_data = Path(scratch)
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(user_data),
                    headless=headless,
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    handle_sigint=interrupt is None,
                )
            except PlaywrightError as exc:
                raise RunError(f"cannot start Chromium: {_first_line(exc)}") from None
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(storyboard.url, timeout=timeout * 3000)
                except PlaywrightError as exc:
                    raise RunError(f"cannot open {storyboard.url}: {_first_line(exc)}") from None
                try:
                    yield PlaywrightStage(page, storyboard.viewport, timeout, interrupt)
                except PlaywrightError as exc:
                    # An action that fails is a StepFailed. What arrives here is
                    # the browser itself failing: it crashed, or it was closed.
                    raise RunError(f"the browser stopped: {_first_line(exc)}") from None
            finally:
                try:
                    context.close()
                except PlaywrightError:
                    pass  # it is already gone


def login(profile_dir: Path, url: str) -> None:
    """A visible window on the profile. Returns when the user closes it."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=False, no_viewport=True)
        except PlaywrightError as exc:
            raise RunError(f"cannot start Chromium: {_first_line(exc)}") from None
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url)
        except PlaywrightError:
            pass  # the user can type the address in the window
        try:
            context.wait_for_event("close", timeout=0)
        except PlaywrightError:
            pass  # the window is already gone
