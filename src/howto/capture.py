"""The Playwright side: a browser that performs actions, records itself and describes its page.

This is the only module that imports Playwright.
"""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import marks, zoom
from .notes import STRIP_HEIGHTS, STRIP_STYLE, note_html, strip_html
from .errors import RunError
from .probe import cut_outline
from .runner import POINTER_ACTIONS, Interrupt, PageReport, StepFailed
from .storyboard import MARK_ACTIONS, Action, Locator, Pace, Storyboard
from .tools import KEY_NAMES, action_timeout
# A probe describes the page a moment after the last action. The browser
# reports a new tab only some 0.1 to 0.2 s after the click that opened it, and
# there is no event that says "no tab is coming", so the wait is a fixed one.
SETTLE_MS = 300
# show_actions also writes each action's locator on the picture, for example
# `Click get_by_role("button", name="Save")`, and has no option that turns it
# off. An overlay may carry a style element, and this rule hides the element
# that holds the label. The element's name is Playwright's own: check it when
# the pinned version changes.
HIDE_ACTION_LABEL = "<style>x-pw-title{display:none!important}</style>"

# A zoom is the page enlarging itself: a transform on <body>, which the browser
# animates and then draws again at the new size, so the text stays sharp. The
# recorder cannot give more pixels than the page has, so cutting a part out of
# the recording afterwards would only blur it.
#
# Playwright's pointer, its highlight and the note are children of <html>, not
# of <body>, so they keep their size and their place.
#
# A transform has one side effect: the body becomes the box that its pinned
# descendants are placed in (`position: fixed`, and `absolute` with no
# positioned parent). On a page whose body is the window, which is how most
# apps are built, nothing changes. On a page that scrolls as a whole, a pinned
# header or a dialog would jump. ZOOM_APPLY therefore measures every element
# before and after a transform that enlarges nothing, and refuses when one of
# them moved.
ZOOM_MS = 800
# After the movement the browser draws the text again at the new size. A take waits for that.
ZOOM_SETTLE_MS = 300
ZOOM_STATE = """() => {
  const state = window.__howtoZoom;
  return state ? {left: state.left, top: state.top, factor: state.factor} : null;
}"""
# Shows the window [left, top] of the page, enlarged by `factor`, moving there
# in `ms` milliseconds. Returns "zoomed", "same" when the picture is already
# there, or "moved" when the page cannot be zoomed and was left as it was.
ZOOM_APPLY = """([left, top, factor, ms]) => {
  const body = document.body, root = document.documentElement;
  let state = window.__howtoZoom;
  if (!state) {
    const boxes = () => Array.from(body.querySelectorAll('*'), (element) => {
      const box = element.getBoundingClientRect();
      return [box.left, box.top, box.width, box.height];
    }).flat();
    const saved = [body.style.transform, body.style.transformOrigin, body.style.transition, root.style.overflow];
    const before = boxes();
    root.style.overflow = 'hidden';
    body.style.transformOrigin = '0 0';
    body.style.transition = 'none';
    body.style.transform = 'scale(1) translate(0px, 0px)';
    const after = boxes();
    if (before.length !== after.length || before.some((value, i) => Math.abs(value - after[i]) > 0.5)) {
      [body.style.transform, body.style.transformOrigin, body.style.transition, root.style.overflow] = saved;
      return 'moved';
    }
    state = window.__howtoZoom = {saved, left: 0, top: 0, factor: 1, transform: ''};
  }
  // Where the body's corner is on the page at its own size, worked out from
  // where it is now, so that a page that scrolled while zoomed is still right.
  const box = body.getBoundingClientRect();
  const x = box.left / state.factor + state.left, y = box.top / state.factor + state.top;
  const tx = -left + x * (factor - 1) / factor, ty = -top + y * (factor - 1) / factor;
  const transform = `scale(${factor}) translate(${tx}px, ${ty}px)`;
  if (transform === state.transform) return 'same';
  body.style.transition = ms ? `transform ${ms}ms cubic-bezier(.45,0,.2,1)` : 'none';
  body.style.transform = transform;
  Object.assign(state, {left, top, factor, transform});
  return 'zoomed';
}"""
# Starts the way back. Returns whether this page was zoomed at all: a page
# that loaded after the zoom knows nothing of it and is at its own size.
ZOOM_OUT = """(ms) => {
  if (!window.__howtoZoom) return false;
  document.body.style.transition = ms ? `transform ${ms}ms cubic-bezier(.45,0,.2,1)` : 'none';
  document.body.style.transform = 'scale(1) translate(0px, 0px)';
  return true;
}"""
# Ends it: the page gets back the styles it had, so nothing stays pinned to the body.
ZOOM_END = """() => {
  const state = window.__howtoZoom;
  if (!state) return;
  const body = document.body, root = document.documentElement;
  [body.style.transform, body.style.transformOrigin, body.style.transition, root.style.overflow] = state.saved;
  delete window.__howtoZoom;
}"""

# Marks are overlays, like the note: children of <html> in screen pixels. They
# do not move with the page, so whatever moves the picture takes them away
# first. See `marks` for how they are drawn.
#
# For each list of points, the number that lie on something worth seeing: a
# control, a picture, or an element that holds text of its own. An arrow is
# drawn on the side where that number is lowest. Playwright's own layer takes
# no pointer events, so elementFromPoint looks through it at the page.
#
# A point outside the picture counts as well: an arrow must not leave it. The
# picture is the window, or the part that the window is cut to.
MARK_BUSY = """([candidates, [left, top, right, bottom]]) => {
  const busy = (x, y) => {
    if (x < left + 4 || y < top + 4 || x > right - 4 || y > bottom - 4) return true;
    const element = document.elementFromPoint(x, y);
    if (!element || element === document.body || element === document.documentElement) return false;
    if (element.closest('button,a,input,select,textarea,label,img,svg,canvas,video,[role=button],[role=link],[role=tab]')) return true;
    return Array.from(element.childNodes).some((node) => node.nodeType === 3 && node.textContent.trim());
  };
  return candidates.map((points) => points.filter(([x, y]) => busy(x, y)).length);
}"""
# What a mark is drawn around. A locator by text often names a block that is as
# wide as the page while its words are not, and a circle around that block
# would run across the picture. So an element that shows no box of its own (no
# background, border or shadow, and not a control or a picture) is measured by
# what is in it.
MARK_BOX = """(element) => {
  const plain = (box) => ({x: box.x, y: box.y, width: box.width, height: box.height});
  const whole = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  const seen = (colour) => !/^transparent$|, 0\\)$/.test(colour);
  const framed = seen(style.backgroundColor) || style.backgroundImage !== 'none' || style.boxShadow !== 'none'
    || ['Top', 'Right', 'Bottom', 'Left'].some((side) =>
      parseFloat(style[`border${side}Width`]) > 0 && style[`border${side}Style`] !== 'none' && seen(style[`border${side}Color`]));
  if (framed || element.matches('button,input,select,textarea,img,svg,canvas,video,iframe')) return plain(whole);
  const range = document.createRange();
  range.selectNodeContents(element);
  const inner = range.getBoundingClientRect();
  return inner.width && inner.height ? plain(inner) : plain(whole);
}"""
# The marks are in a closed shadow root that the page cannot reach. A custom
# property on <html> is inherited there, and the marks take their opacity from it.
MARK_FADE = "(property) => document.documentElement.style.setProperty(property, '0')"
MARK_FADED = "(property) => document.documentElement.style.removeProperty(property)"


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
        self._marks: list = []
        # The part of the window that a picture is cut to, where marks may be
        # drawn. None is the whole window. Its notes go in the strip, and
        # `_strip_shown` is the strip itself while a take shows it empty.
        self._crop: zoom.Box | None = None
        self._strip: zoom.Box | None = None
        self._strip_outside = False
        self._strip_shown = None
        self._dialogs: list[str] = []
        self._unzoomable: list[str] = []
        self._left_out: list[str] = []
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
        notices = self._dialogs + self._unzoomable + self._left_out
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
            elif action.kind == "type":
                # The same key names work on both stages. A name that both accepts is pressed;
                # anything else is typed character by character, at the pace of the storyboard.
                if action.value in KEY_NAMES:
                    self.page.keyboard.press(action.value)
                else:
                    self.page.keyboard.type(action.value, delay=1000 / pace.typing)
            else:
                target = self._one(action)
                if action.kind in POINTER_ACTIONS:
                    self._check_crop(action, target)
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

    def zoom_to(self, action: Action, factor: float, animate: bool) -> None:
        """Enlarges the page around the element an action names. Without `animate` it is there at once."""
        self._interrupt.check()
        try:
            self._zoom_to(action, factor, animate)
        except PlaywrightError as exc:
            raise StepFailed(f"{action.describe()}: {failure_reason(str(exc))}") from None
        finally:
            self._interrupt.check()

    def zoom_out(self, animate: bool) -> None:
        """Back to the page's own size. Does nothing on a page that is not zoomed."""
        self._interrupt.check()
        try:
            self._clear_marks(animate)
            self._zoom_out(animate)
        finally:
            self._interrupt.check()

    def mark(self, action: Action, draw: bool) -> None:
        """Draws a mark at the element an action names. Without `draw` it only finds the element, as a probe does."""
        self._interrupt.check()
        try:
            self._mark(action, draw)
        except PlaywrightError as exc:
            raise StepFailed(f"{action.describe()}: {failure_reason(str(exc))}") from None
        finally:
            self._interrupt.check()

    def clear_marks(self, animate: bool) -> None:
        """Takes every mark off the picture. Without `animate` they are gone at once."""
        self._interrupt.check()
        try:
            self._clear_marks(animate)
        finally:
            self._interrupt.check()

    def crop_to(self, action: Action, notes: Sequence[str]) -> zoom.Box:
        """Cuts the picture to the element an action names, and returns the part of the window to cut out.

        The recording still shows the whole window, and whoever makes the
        picture cuts it out. What changes here is where things are drawn. An
        arrow stays inside the crop. The notes get a strip next to it, as tall
        as the longest of them needs, and the picture grows by that strip.
        """
        self._interrupt.check()
        try:
            return self._crop_to(action, notes)
        except PlaywrightError as exc:
            raise StepFailed(f"{action.describe()}: {failure_reason(str(exc))}") from None
        finally:
            self._interrupt.check()

    def _crop_to(self, action: Action, notes: Sequence[str]) -> zoom.Box:
        target = self._one(action)
        box = self._box(target)
        if box is not None and not zoom.on_screen(box, self.viewport):
            target.scroll_into_view_if_needed(timeout=self.timeout_ms)
            box = self._box(target)
        crop = zoom.crop(box, self.viewport) if box is not None else None
        if crop is None:
            raise StepFailed(f"{action.describe()}: the element has no size, so there is no picture to cut to it")
        self._crop, self._strip, self._strip_outside = crop, None, False
        if not notes:
            return crop
        heights = self.page.evaluate(STRIP_HEIGHTS, [list(notes), crop.width, STRIP_STYLE])
        self._strip, self._strip_outside = zoom.strip(crop, max(heights), self.viewport)
        return zoom.union(crop, self._strip)

    def _mark(self, action: Action, draw: bool) -> None:
        target = self._one(action)
        box = self._aim(action, target)
        if box is not None and not zoom.on_screen(box, self.viewport):
            # A scroll moves the page under the marks that are already there.
            self._clear_marks(draw)
            target.scroll_into_view_if_needed(timeout=self.timeout_ms)
            box = self._aim(action, target)
        self._check_crop(action, target, box)
        if not draw or box is None:
            return
        if action.kind == "arrow":
            picture = self._crop or zoom.Box(0, 0, *self.viewport)
            candidates = marks.arrows(box, self.viewport, action.value, self._crop)
            busy = self.page.evaluate(
                MARK_BUSY,
                [
                    [[list(point) for point in candidate.points] for candidate in candidates],
                    [picture.x, picture.y, picture.x + picture.width, picture.y + picture.height],
                ],
            )
            drawing = marks.arrow(marks.emptiest(candidates, busy))
        else:
            drawing = marks.SHAPES[action.kind](box, self.viewport)
        self._marks.append(self.page.screencast.show_overlay(marks.layer(drawing, self.viewport)))
        self.page.wait_for_timeout(marks.DRAW_MS)

    def _clear_marks(self, animate: bool) -> None:
        if not self._marks:
            return
        # Each call may meet a page that an action has just replaced. The marks
        # of the old page went with it, and the list must end up empty anyway.
        if animate:
            try:
                self.page.evaluate(MARK_FADE, marks.FADE_PROPERTY)
                self.page.wait_for_timeout(marks.FADE_MS + 30)
            except PlaywrightError:
                pass
        while self._marks:
            try:
                _remove(self._marks.pop())
            except PlaywrightError:
                pass
        try:
            self.page.evaluate(MARK_FADED, marks.FADE_PROPERTY)
        except PlaywrightError:
            pass

    def _check_crop(self, action: Action, target, box: zoom.Box | None = None) -> None:
        """Keeps a note of an action whose element the crop leaves out of the picture.

        The author of a storyboard is often a model that cannot look at the
        picture, and a probe is where it learns that nothing would be seen.
        """
        if self._crop is None:
            return
        box = box or self._box(target)
        if box is None or zoom.inside(box, self._crop):
            return
        notice = f"{action.describe()}: the element is not inside the crop"
        if notice not in self._left_out:
            self._left_out.append(notice)

    def _box(self, target) -> zoom.Box | None:
        """Where an element is on the screen. None for an element that is not drawn."""
        measured = target.bounding_box(timeout=self.timeout_ms)
        return zoom.Box(**measured) if measured else None

    def _aim(self, action: Action, target) -> zoom.Box | None:
        """The box that an action is about: the element for a pointer, and what the viewer sees of it for a mark."""
        box = self._box(target)
        if box is None or action.kind not in MARK_ACTIONS:
            return box
        return zoom.Box(**target.evaluate(MARK_BOX, timeout=self.timeout_ms))

    def _zoom_to(self, action: Action, factor: float, animate: bool) -> None:
        target = self._one(action)
        box = self._aim(action, target)
        if self._marks and box is not None and zoom.on_screen(box, self.viewport):
            # The picture holds still while something is drawn on it, as long
            # as the next target is in it.
            return
        # From here on the picture may move, and a mark would stay behind.
        self._clear_marks(animate)
        state = self.page.evaluate(ZOOM_STATE)
        if box is not None and state is not None:
            box = zoom.Window(**state).to_page(box)
        if box is not None and not zoom.on_screen(box, self.viewport):
            # The action would scroll to it, and a scroll moves what a zoomed
            # picture shows. So the scroll comes first, at the page's own size.
            self._zoom_out(animate)
            target.scroll_into_view_if_needed(timeout=self.timeout_ms)
            box = self._aim(action, target)
        window = zoom.frame(box, self.viewport, factor) if box is not None else None
        if window is None:
            # Nothing to aim at, or a target too large to enlarge.
            self._zoom_out(animate)
            return
        duration = ZOOM_MS if animate else 0
        outcome = self.page.evaluate(ZOOM_APPLY, [window.left, window.top, window.factor, duration])
        if outcome == "moved":
            notice = (
                f"zoom is skipped on {self.page.url}: "
                "it would move parts of the page that are pinned to the window"
            )
            if notice not in self._unzoomable:
                self._unzoomable.append(notice)
        elif outcome == "zoomed" and animate:
            self.page.wait_for_timeout(ZOOM_MS + ZOOM_SETTLE_MS)

    def _zoom_out(self, animate: bool) -> None:
        try:
            if not self.page.evaluate(ZOOM_OUT, ZOOM_MS if animate else 0):
                return
            if animate:
                self.page.wait_for_timeout(ZOOM_MS + ZOOM_SETTLE_MS)
            self.page.evaluate(ZOOM_END)
        except PlaywrightError:
            # The zoomed page is gone: an action replaced it while this ran. Its
            # successor starts at its own size. If it is the browser that is
            # gone, the next call says so.
            pass

    def start_recording(self, path: Path) -> None:
        width, height = self.viewport
        if self._strip is not None and self._strip_outside:
            # A strip outside the crop lies on a part of the page that is not
            # the picture's subject, so it is there for the whole take, with
            # a note or without. The recorder's first frame still comes before
            # it is drawn, which is why a picture leaves out the head of the
            # recording (`animation.HEAD`). A strip inside the crop is shown
            # with its note only.
            self._strip_shown = self.page.screencast.show_overlay(strip_html(self._strip))
        self.page.screencast.start(path=str(path), size={"width": width, "height": height})
        self.page.screencast.show_actions(cursor="pointer")
        self._label_rule = self.page.screencast.show_overlay(HIDE_ACTION_LABEL)

    def stop_recording(self) -> None:
        if self._label_rule is not None:
            # Cleanup runs after this, and it should not wait for a pointer to be drawn.
            self.page.screencast.hide_actions()
            _remove(self._label_rule)
            self._label_rule = None
        if self._strip_shown is not None:
            _remove(self._strip_shown)
            self._strip_shown = None
        self.page.screencast.stop()

    def show_chapter(self, title: str, seconds: float) -> None:
        self.page.screencast.show_chapter(title, duration=seconds * 1000)

    def show_note(self, text: str) -> None:
        self._note = self.page.screencast.show_overlay(note_html(text, self._strip))

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
