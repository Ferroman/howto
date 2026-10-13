"""The helper's names of keys, and the path its pointer takes."""
import pytest

from howto.desktop.helper.keys import BadKey, chord
from howto.desktop.helper.pointer import path, script


@pytest.mark.parametrize(
    "written, expected",
    [
        ("Enter", "Return"),
        ("Escape", "Escape"),
        ("ArrowDown", "Down"),
        ("PageDown", "Next"),
        ("Backspace", "BackSpace"),
        ("F5", "F5"),
        ("a", "a"),
        ("A", "A"),
        ("7", "7"),
        (" ", "space"),
        ("Control+S", "ctrl+s"),
        ("Control+Shift+S", "ctrl+shift+s"),
        ("Alt+F4", "alt+F4"),
        ("Meta+L", "super+l"),
        ("Control+ArrowRight", "ctrl+Right"),
        ("Control++", "ctrl+plus"),
        ("+", "plus"),
        ("Control+,", "ctrl+comma"),
        ("é", "U00E9"),
    ],
)
def test_a_key_gets_the_name_that_x_has_for_it(written, expected):
    assert chord(written) == expected


def test_a_letter_with_control_is_not_typed_as_a_capital():
    # xdotool holds Shift for a capital, and Control+Shift+S is another command than Control+S.
    assert chord("Control+S") == "ctrl+s"


@pytest.mark.parametrize("written", ["Entre", "Control+Enter+S", "S+Control", "", "Control+"])
def test_what_is_not_a_key_is_refused_with_its_name(written):
    with pytest.raises(BadKey):
        chord(written)


def test_the_message_of_a_wrong_key_offers_the_names():
    with pytest.raises(BadKey, match="`Entre` is not a key: use a name such as Enter"):
        chord("Entre")


def test_the_pointer_ends_exactly_on_its_target():
    points = path((0, 0), (600, 300), 0.5)
    assert len(points) == 30
    assert points[-1] == (600, 300)


def test_the_pointer_is_slow_at_both_ends_and_quick_in_the_middle():
    points = [(0, 0), *path((0, 0), (600, 0), 0.5)]
    steps = [b[0] - a[0] for a, b in zip(points, points[1:])]
    assert steps[0] < steps[len(steps) // 2] > steps[-1]
    assert all(step >= 0 for step in steps)


def test_no_time_means_a_jump():
    assert path((10, 10), (600, 300), 0) == [(600, 300)]
    assert script([(600, 300)], 0) == "mousemove 600 300\n"


def test_the_script_pauses_between_the_points():
    assert script([(1, 2), (3, 4)], 0.5) == "mousemove 1 2\nsleep 0.2500\nmousemove 3 4\nsleep 0.2500\n"
