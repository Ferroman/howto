"""The Playwright side: a browser that performs actions, records itself and describes its page.

This is the only module that imports Playwright.
"""
from __future__ import annotations

import html
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .errors import RunError
from .probe import cut_outline
from .runner import PageReport, StepFailed
from .storyboard import Action, Locator, Pace, Storyboard

DEFAULT_TIMEOUT = 10.0
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


class PlaywrightStage:
    def __init__(self, page: Page, viewport: tuple[int, int], timeout: float) -> None:
        self.page = page
        self.viewport = viewport
        self.timeout_ms = timeout * 1000
        self._label_rule = None
        self._note = None

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
            raise StepFailed(f"{action.describe()}: {_first_line(exc)}") from None

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
        scope = resolve(self.page, within) if within is not None else self.page.locator("body")
        try:
            outline = scope.first.aria_snapshot(timeout=self.timeout_ms)
        except PlaywrightError as exc:
            outline = f"(no outline: {_first_line(exc)})"
        kept, omitted = cut_outline(outline, max_chars)
        return PageReport(url=self.page.url, title=self.page.title(), outline=kept, omitted=omitted)


@contextmanager
def open_stage(storyboard: Storyboard, *, profiles_dir: Path, headless: bool = True) -> Iterator[PlaywrightStage]:
    """A browser with the storyboard's profile and viewport, and its start page open."""
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
                )
            except PlaywrightError as exc:
                raise RunError(f"cannot start Chromium: {_first_line(exc)}") from None
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(storyboard.url, timeout=timeout * 3000)
                except PlaywrightError as exc:
                    raise RunError(f"cannot open {storyboard.url}: {_first_line(exc)}") from None
                yield PlaywrightStage(page, storyboard.viewport, timeout)
            finally:
                context.close()


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
