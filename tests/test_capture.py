from howto.capture import action_timeout, failure_reason, note_html, resolve
from howto.storyboard import parse_locator


class FakeLocator:
    """Records the chain of Playwright calls that `resolve` makes."""

    def __init__(self, trail=()):
        self.trail = list(trail)

    def _next(self, *entry):
        return FakeLocator([*self.trail, entry])

    def get_by_role(self, role, **options):
        return self._next("role", role, options)

    def get_by_label(self, text, **options):
        return self._next("label", text, options)

    def get_by_placeholder(self, text, **options):
        return self._next("placeholder", text, options)

    def get_by_text(self, text, **options):
        return self._next("text", text, options)

    def get_by_test_id(self, value):
        return self._next("testid", value, {})

    def locator(self, css):
        return self._next("css", css, {})

    def nth(self, index):
        return self._next("nth", index, {})


def trail(data):
    return resolve(FakeLocator(), parse_locator(data, "test")).trail


def test_role_and_name():
    assert trail({"role": "button", "name": "Save"}) == [("role", "button", {"name": "Save", "exact": None})]


def test_exact_is_passed_on():
    assert trail({"label": "Email", "exact": True}) == [("label", "Email", {"exact": True})]


def test_the_other_forms():
    assert trail({"placeholder": "name@example.com"}) == [("placeholder", "name@example.com", {"exact": None})]
    assert trail({"text": "Welcome"}) == [("text", "Welcome", {"exact": None})]
    assert trail({"testid": "save-button"}) == [("testid", "save-button", {})]
    assert trail({"css": "form > button"}) == [("css", "form > button", {})]


def test_within_comes_first_and_nth_last():
    data = {"role": "button", "name": "Remove", "nth": 1, "within": {"text": "bob@example.com"}}
    assert trail(data) == [
        ("text", "bob@example.com", {"exact": None}),
        ("role", "button", {"name": "Remove", "exact": None}),
        ("nth", 1, {}),
    ]


def test_note_html_escapes_the_text():
    html = note_html('Use <b>"work"</b> & co')
    assert "Use &lt;b&gt;&quot;work&quot;&lt;/b&gt; &amp; co" in html
    assert html.startswith("<div style=") and html.endswith("</div>")


def test_action_timeout(monkeypatch):
    monkeypatch.delenv("HOWTO_ACTION_TIMEOUT", raising=False)
    assert action_timeout() == 10.0
    for raw, expected in (("2", 2.0), ("0.5", 0.5), ("abc", 10.0), ("0", 10.0), ("-3", 10.0), ("", 10.0)):
        monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", raw)
        assert action_timeout() == expected


COVERED = """Locator.click: Timeout 1500ms exceeded.
Call log:
  - waiting for get_by_role("button", name="Publish")
    - locator resolved to <button type="button">Publish</button>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="cover">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
"""

DISABLED = """Locator.click: Timeout 1500ms exceeded.
Call log:
  - waiting for get_by_role("button", name="Save")
    - locator resolved to <button disabled type="button">Save</button>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is not enabled
    - retrying click action
"""


def test_a_timeout_says_what_covers_the_element():
    assert failure_reason(COVERED) == (
        'Locator.click: Timeout 1500ms exceeded: <div id="cover">…</div> intercepts pointer events'
    )


def test_a_timeout_says_that_the_element_is_disabled():
    assert failure_reason(DISABLED) == "Locator.click: Timeout 1500ms exceeded: element is not enabled"


def test_an_error_with_nothing_to_add_keeps_its_first_line():
    assert failure_reason('Keyboard.press: Unknown key: "NotAKey"\nCall log:\n  - pressing') == (
        'Keyboard.press: Unknown key: "NotAKey"'
    )
    assert failure_reason("") == "unknown error"
