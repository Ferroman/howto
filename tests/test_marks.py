import math

import pytest

from howto import marks
from howto.storyboard import MARK_ACTIONS
from howto.zoom import Box

VIEWPORT = (1280, 720)
BUTTON = Box(580, 340, 120, 40)


def inside(point, box, slack=0.0):
    x, y = point
    return box.x - slack <= x <= box.x + box.width + slack and box.y - slack <= y <= box.y + box.height + slack


def away(point, box):
    """How far a point is from a box. 0 when it is inside."""
    x, y = point
    dx = max(box.x - x, 0, x - (box.x + box.width))
    dy = max(box.y - y, 0, y - (box.y + box.height))
    return math.hypot(dx, dy)


def overlap(a, b):
    return a.x < b.x + b.width and b.x < a.x + a.width and a.y < b.y + b.height and b.y < a.y + a.height


def side(arrow):
    """Where the tail lies as seen from the tip: (-1, 1) is to the left and below."""
    sign = lambda value: (value > 1) - (value < -1)  # noqa: E731
    return sign(arrow.tail[0] - arrow.tip[0]), sign(arrow.tail[1] - arrow.tip[1])


def test_every_mark_of_the_storyboard_has_a_drawing():
    assert set(marks.SHAPES) | {"arrow"} == set(MARK_ACTIONS)


@pytest.mark.parametrize("target", [Box(600, 300, 24, 24), Box(400, 300, 400, 40), Box(300, 200, 300, 200)])
def test_a_loop_goes_round_its_target_without_crossing_it(target):
    points = marks.loop(target)
    assert not any(inside(point, target) for point in points)
    # A hand closes a circle by going a little past where it began.
    cx, cy = target.x + target.width / 2, target.y + target.height / 2
    angles = [math.atan2(y - cy, x - cx) for x, y in points]
    turned = sum(math.remainder(b - a, math.tau) for a, b in zip(angles, angles[1:]))
    assert 360 < abs(math.degrees(turned)) < 450


def test_a_loop_stays_close_to_its_target():
    reach = Box(BUTTON.x - 80, BUTTON.y - 40, BUTTON.width + 160, BUTTON.height + 80)
    assert all(inside(point, reach) for point in marks.loop(BUTTON))


def test_an_arrow_has_a_candidate_on_each_of_eight_sides():
    candidates = marks.arrows(BUTTON, VIEWPORT)
    assert len(candidates) == 8
    assert len({side(candidate) for candidate in candidates}) == 8


@pytest.mark.parametrize(
    "target, expected",
    [
        (Box(1100, 40, 120, 40), (-1, 1)),  # top right: from the left and below
        (Box(40, 640, 120, 40), (1, -1)),  # bottom left: from the right and above
        (Box(580, 40, 120, 40), (0, 1)),  # top centre: from below
        (Box(40, 340, 120, 40), (1, 0)),  # left edge: from the right
    ],
)
def test_the_first_candidate_faces_the_middle_of_the_picture(target, expected):
    assert side(marks.arrows(target, VIEWPORT)[0]) == expected


def test_an_arrow_stops_short_of_its_target():
    for candidate in marks.arrows(BUTTON, VIEWPORT):
        assert 10 <= away(candidate.tip, BUTTON) <= 25
        assert away(candidate.tail, BUTTON) > 100


def test_the_words_of_an_arrow_lie_beyond_its_tail():
    for candidate in marks.arrows(BUTTON, VIEWPORT, "Pick a plane"):
        assert candidate.note == "Pick a plane"
        assert not overlap(candidate.words, BUTTON)
        assert away(candidate.tail, candidate.words) <= 12
        assert away(candidate.tip, candidate.words) > 100


def test_an_arrow_without_words_has_no_place_for_them():
    assert all(candidate.words is None and candidate.note is None for candidate in marks.arrows(BUTTON, VIEWPORT))


def test_the_points_to_check_follow_the_shaft_and_cover_the_words():
    bare = marks.arrows(BUTTON, VIEWPORT)[0]
    worded = marks.arrows(BUTTON, VIEWPORT, "Pick a plane")[0]
    assert bare.points[0] == pytest.approx(bare.tail) and bare.points[-1] == pytest.approx(bare.tip)
    extra = worded.points[len(bare.points):]
    assert len(extra) >= 9
    assert all(inside(point, worded.words, slack=0.5) for point in extra)


def test_the_emptiest_side_wins_and_the_earlier_one_wins_a_tie():
    candidates = marks.arrows(BUTTON, VIEWPORT)
    assert marks.emptiest(candidates, [3, 1, 4, 1, 5, 9, 2, 6]) is candidates[1]
    assert marks.emptiest(candidates, [0] * 8) is candidates[0]


def test_the_words_are_shown_as_text_not_as_markup():
    drawing = marks.arrow(marks.arrows(BUTTON, VIEWPORT, 'Use <b>"this"</b>')[0])
    assert "&lt;b&gt;" in drawing.html and "<b>" not in drawing.html


def test_a_layer_gives_its_drawing_a_size_of_its_own():
    # Playwright's stylesheet sets every svg to a height of 0. Only an inline size is stronger.
    assert "width:1280px;height:720px" in marks.layer(marks.SHAPES["box"](BUTTON, VIEWPORT), VIEWPORT)


def test_a_layer_can_be_faded_from_outside():
    # The page cannot reach into the recorder's layer, but a custom property is inherited there.
    assert f"opacity:var({marks.FADE_PROPERTY},1)" in marks.layer(marks.SHAPES["circle"](BUTTON, VIEWPORT), VIEWPORT)


def test_a_target_with_no_height_still_gets_a_loop():
    assert len(marks.loop(Box(100, 100, 80, 0))) > 10
