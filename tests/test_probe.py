from howto.probe import cut_outline, format_report
from howto.runner import PageReport, RunResult, StepResult
from howto.zoom import Box

PAGE = PageReport(
    url="https://app.example.com/settings",
    title="Settings - Example",
    outline='- heading "Settings" [level=1]\n- textbox "Email address"\n- button "Invite"\n',
)


def test_the_report_of_a_clean_probe():
    result = RunResult(
        steps=(StepResult(1, True, 'click role=button name="Settings"'), StepResult(2, True, 'chapter "Invite"')),
        page=PAGE,
    )
    assert format_report(result) == (
        'step 1 ok      click role=button name="Settings"\n'
        'step 2 ok      chapter "Invite"\n'
        'page: https://app.example.com/settings  "Settings - Example"\n'
        "outline:\n"
        '- heading "Settings" [level=1]\n'
        '- textbox "Email address"\n'
        '- button "Invite"\n'
    )


def test_a_failed_step_shows_the_reason():
    reason = 'fill label="Email" value="sam@example.com": 0 elements match'
    result = RunResult(
        steps=(StepResult(1, True, "press Enter"), StepResult(2, False, 'fill label="Email" value="sam@example.com"', reason)),
        page=PAGE,
    )
    assert f"step 2 FAILED  {reason}\n" in format_report(result)


def test_a_failed_setup_is_labelled():
    reason = 'wait_for role=button name="Settings": 0 elements match'
    result = RunResult(steps=(StepResult(0, False, 'wait_for role=button name="Settings"', reason),), page=PAGE)
    assert format_report(result).startswith(f"setup  FAILED  {reason}\n")


def test_warnings_and_a_cut_outline_are_shown():
    page = PageReport(url="http://demo.test/", title="Demo", outline="- main", omitted=1234)
    result = RunResult(
        steps=(StepResult(1, True, "press Enter"),),
        warnings=('cleanup[1]: click role=button name="Undo": 0 elements match',),
        page=page,
    )
    text = format_report(result)
    assert 'warning: cleanup[1]: click role=button name="Undo": 0 elements match\n' in text
    assert text.endswith("- main\n(outline cut: 1234 more characters; use --within or --max-chars)\n")


def test_no_page_means_no_outline():
    assert format_report(RunResult(steps=(StepResult(1, True, "press Enter"),))) == "step 1 ok      press Enter\n"


def test_a_short_outline_is_kept_whole():
    assert cut_outline("- main\n- button", 100) == ("- main\n- button", 0)


def test_a_long_outline_is_cut_at_a_line_end():
    outline = "- heading\n- button one\n- button two\n"
    kept, omitted = cut_outline(outline, 25)
    assert kept == "- heading\n- button one"
    assert omitted == len(outline) - len(kept)


def test_one_enormous_line_is_still_cut():
    kept, omitted = cut_outline("x" * 5000, 100)
    assert (len(kept), omitted) == (100, 4900)


def test_notes_about_what_the_steps_did_not_handle_come_before_the_page():
    page = PageReport(
        url="http://demo.test/", title="Demo", outline="- main",
        notices=('a confirm dialog was dismissed: "Delete this invitation?"',),
    )
    assert format_report(RunResult(steps=(StepResult(1, True, "press Enter"),), page=page)) == (
        "step 1 ok      press Enter\n"
        'note: a confirm dialog was dismissed: "Delete this invitation?"\n'
        'page: http://demo.test/  "Demo"\n'
        "outline:\n"
        "- main\n"
    )


def test_the_crop_comes_first_with_its_size_and_its_place():
    result = RunResult(steps=(StepResult(1, True, "press Enter"),), crop=Box(1588, 68, 332, 243), page=PAGE)
    assert format_report(result).startswith("crop: 332 x 243 pixels at 1588, 68\nstep 1 ok      press Enter\n")


DESK = PageReport(
    url="app inkscape /files/logo.svg",
    title="logo.svg - Inkscape",
    outline='- frame "logo.svg - Inkscape" [active]:\n  - menubar',
    words=('"Layer 1" {at: 1620x200, size: 62x24}', '"Export" {at: 1658x952, size: 88x24}'),
    screenshot="/home/sam/.cache/howto/probe/export.png",
)


def test_the_report_of_a_desktop_lists_the_words_that_the_outline_lacks_and_the_screenshot():
    assert format_report(RunResult(steps=(StepResult(1, True, "press Enter"),), page=DESK)) == (
        "step 1 ok      press Enter\n"
        'page: app inkscape /files/logo.svg  "logo.svg - Inkscape"\n'
        "outline:\n"
        '- frame "logo.svg - Inkscape" [active]:\n'
        "  - menubar\n"
        "words on the screen that the outline lacks:\n"
        '- "Layer 1" {at: 1620x200, size: 62x24}\n'
        '- "Export" {at: 1658x952, size: 88x24}\n'
        "screenshot: /home/sam/.cache/howto/probe/export.png\n"
    )


def test_a_screen_without_such_words_has_no_list_of_them():
    page = PageReport(url="app gedit", title="gedit", outline="- frame", screenshot="/tmp/x.png")
    assert format_report(RunResult(steps=(), page=page)) == 'page: app gedit  "gedit"\noutline:\n- frame\nscreenshot: /tmp/x.png\n'


def test_words_that_were_cut_say_so_after_the_words():
    page = PageReport(url="app gedit", title="gedit", outline="- frame", omitted=120, words=('"Layer 1" {at: 1x2, size: 3x4}',))
    assert format_report(RunResult(steps=(), page=page)).endswith(
        '- "Layer 1" {at: 1x2, size: 3x4}\n(words cut: 120 more characters; use --max-chars)\n'
    )


DESK = PageReport(
    url="app inkscape /files/logo.svg",
    title="logo.svg - Inkscape",
    outline='- frame "logo.svg - Inkscape" [active]:\n  - menubar',
    words=('"Layer 1" {at: 1620x200, size: 62x24}', '"Export" {at: 1658x952, size: 88x24}'),
    screenshot="/home/sam/.cache/howto/probe/export.png",
)


def test_the_report_of_a_desktop_lists_the_words_that_the_outline_lacks_and_the_screenshot():
    assert format_report(RunResult(steps=(StepResult(1, True, "press Enter"),), page=DESK)) == (
        "step 1 ok      press Enter\n"
        'page: app inkscape /files/logo.svg  "logo.svg - Inkscape"\n'
        "outline:\n"
        '- frame "logo.svg - Inkscape" [active]:\n'
        "  - menubar\n"
        "words on the screen that the outline lacks:\n"
        '- "Layer 1" {at: 1620x200, size: 62x24}\n'
        '- "Export" {at: 1658x952, size: 88x24}\n'
        "screenshot: /home/sam/.cache/howto/probe/export.png\n"
    )


def test_a_screen_without_such_words_has_no_list_of_them():
    page = PageReport(url="app gedit", title="gedit", outline="- frame", screenshot="/tmp/x.png")
    assert format_report(RunResult(steps=(), page=page)) == 'page: app gedit  "gedit"\noutline:\n- frame\nscreenshot: /tmp/x.png\n'


def test_words_that_were_cut_say_so_after_the_words():
    page = PageReport(url="app gedit", title="gedit", outline="- frame", omitted=120, words=('"Layer 1" {at: 1x2, size: 3x4}',))
    assert format_report(RunResult(steps=(), page=page)).endswith(
        '- "Layer 1" {at: 1x2, size: 3x4}\n(words cut: 120 more characters; use --max-chars)\n'
    )
