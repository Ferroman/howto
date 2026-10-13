"""The one part of the helper's desktop that needs no monitor: reading the window manager's list."""
from howto.desktop.helper.session import Window, parse_windows

LISTING = (
    "0x01200003  0 4242   0    0    1920 1080 a1b2c3d4e5f6 logo.svg - Inkscape\n"
    "0x01400007  0 4242   660  390  600  300  a1b2c3d4e5f6 Open\n"
    "0x01600001 -1 0      0    0    10   10   N/A\n"
    "a line that is no window\n"
)


def test_each_line_of_the_list_is_a_window():
    assert parse_windows(LISTING) == [
        Window("0x01200003", 4242, 0, 0, 1920, 1080, "logo.svg - Inkscape"),
        Window("0x01400007", 4242, 660, 390, 600, 300, "Open"),
        Window("0x01600001", 0, 0, 0, 10, 10, ""),
    ]


def test_no_window_gives_an_empty_list():
    assert parse_windows("") == []
