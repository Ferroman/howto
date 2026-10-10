import pytest

from howto.zoom import MARGIN, Box, Window, frame, on_screen

VIEWPORT = (1280, 720)


def test_the_window_is_centred_on_the_target():
    window = frame(Box(580, 340, 120, 40), VIEWPORT, 2)
    # Twice as large shows 640 by 360 pixels of the page, around the point (640, 360).
    assert window == Window(left=320, top=180, factor=2)


@pytest.mark.parametrize(
    "box, corner",
    [
        (Box(1140, 660, 120, 40), (640, 360)),  # bottom right
        (Box(10, 10, 120, 40), (0, 0)),  # top left
        (Box(1140, 10, 120, 40), (640, 0)),  # top right
        (Box(10, 660, 120, 40), (0, 360)),  # bottom left
    ],
)
def test_the_window_stays_inside_the_page(box, corner):
    window = frame(box, VIEWPORT, 2)
    assert (window.left, window.top) == corner


def test_a_wide_target_lowers_the_zoom_until_it_fits():
    box = Box(100, 300, 700, 40)
    window = frame(box, VIEWPORT, 3)
    assert window.factor == pytest.approx(1280 / (700 + 2 * MARGIN))
    shown = window.to_screen(box)
    assert shown.x >= 0 and shown.x + shown.width <= 1280


def test_a_tall_target_lowers_the_zoom_as_well():
    window = frame(Box(100, 100, 200, 400), VIEWPORT, 3)
    assert window.factor == pytest.approx(720 / (400 + 2 * MARGIN))


def test_a_target_that_fills_the_page_keeps_the_picture_wide():
    assert frame(Box(20, 20, 1200, 600), VIEWPORT, 2) is None


def test_a_zoom_of_one_keeps_the_picture_wide():
    assert frame(Box(580, 340, 120, 40), VIEWPORT, 1) is None


def test_the_target_is_on_the_zoomed_screen():
    box = Box(1140, 660, 120, 40)
    shown = frame(box, VIEWPORT, 2).to_screen(box)
    assert shown == Box(1000, 600, 240, 80)


def test_a_box_measured_on_the_zoomed_screen_is_mapped_back_to_the_page():
    window = Window(left=640, top=360, factor=2)
    assert window.to_page(Box(1000, 600, 240, 80)) == Box(1140, 660, 120, 40)


@pytest.mark.parametrize(
    "box, expected",
    [
        (Box(580, 340, 120, 40), True),
        (Box(0, 0, 1280, 720), True),
        (Box(40, 1500, 120, 40), False),  # below the fold
        (Box(1200, 340, 120, 40), False),  # cut by the right edge
        (Box(-10, 340, 120, 40), False),
    ],
)
def test_on_screen_means_wholly_inside_the_viewport(box, expected):
    assert on_screen(box, VIEWPORT) is expected
