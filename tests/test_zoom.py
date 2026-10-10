import pytest

from howto.zoom import CROP_MARGIN, MARGIN, Box, Window, crop, frame, inside, on_screen

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


def test_a_crop_is_the_element_and_a_little_around_it():
    cut = crop(Box(400, 200, 320, 218), VIEWPORT)
    assert cut == Box(400 - CROP_MARGIN, 200 - CROP_MARGIN, 320 + 2 * CROP_MARGIN, 218 + 2 * CROP_MARGIN)


def test_a_crop_is_in_whole_pixels_and_loses_nothing_of_the_element():
    cut = crop(Box(400.4, 200.8, 320.3, 218.1), VIEWPORT)
    assert all(value == int(value) for value in (cut.x, cut.y, cut.width, cut.height))
    assert inside(Box(400.4, 200.8, 320.3, 218.1), cut)


@pytest.mark.parametrize(
    "box, expected",
    [
        (Box(960, 0, 320, 218), Box(960 - CROP_MARGIN, 0, 320 + CROP_MARGIN, 218 + CROP_MARGIN)),  # top right corner
        (Box(-50, -50, 2000, 2000), Box(0, 0, 1280, 720)),  # larger than the window
    ],
)
def test_a_crop_ends_at_the_edge_of_the_window(box, expected):
    assert crop(box, VIEWPORT) == expected


@pytest.mark.parametrize("box", [Box(400, 200, 0, 40), Box(400, 200, 40, 0), Box(400, 900, 100, 40), Box(-300, 200, 100, 40)])
def test_an_element_with_nothing_to_show_has_no_crop(box):
    # No size, or wholly outside the window: a margin alone is not a picture.
    assert crop(box, VIEWPORT) is None


def test_inside_means_the_whole_box():
    cut = Box(100, 100, 400, 300)
    assert inside(Box(100, 100, 400, 300), cut)
    assert inside(Box(200, 200, 50, 50), cut)
    assert not inside(Box(480, 200, 50, 50), cut)  # its right edge is beyond
    assert not inside(Box(600, 200, 50, 50), cut)
