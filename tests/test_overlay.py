"""The overlay of a desktop take: which pictures are drawn, how long each is shown, and what they hold."""
import pytest

from pictures import alpha
from howto.desktop.takelog import Shown, TakeLog
from howto.errors import RunError
from howto.notes import note_html, ring_html
from howto.overlay import changes, draw, frame_count, listing, state
from howto.tools import find_tool

NOTE = Shown("note", 0.2, 0.6, "<div>Hi</div>")
RING = Shown("click", 1.0, 1.2, "<div></div>", grow=0.2)
CARD = Shown("card", 2.0, 3.0, "<div>Title</div>", grow=0.3, fade=0.3)


def test_nothing_is_shown_before_and_after():
    assert state((NOTE,), 0.1) == ()
    assert state((NOTE,), 0.6) == ()


def test_a_note_is_simply_there():
    assert state((NOTE,), 0.2) == ((0, None, 1.0),)
    assert state((NOTE,), 0.5) == ((0, None, 1.0),)


def test_what_grows_has_its_age_in_milliseconds_until_it_has_grown():
    assert state((RING,), 1.0) == ((0, 0, 1.0),)
    assert state((RING,), 1.12) == ((0, 120, 1.0),)
    assert state((CARD,), 2.4) == ((0, None, 1.0),)


def test_what_fades_loses_its_opacity_at_the_end():
    assert state((CARD,), 2.85) == ((0, None, 0.5),)
    assert state((CARD,), 2.7) == ((0, None, 1.0),)


def test_two_things_at_once_are_both_in_the_state():
    assert state((NOTE, Shown("click", 0.4, 0.8, "", grow=0.4)), 0.5) == ((0, None, 1.0), (1, 100, 1.0))


def test_a_take_is_counted_in_whole_frames():
    assert frame_count(2.0) == 50
    assert frame_count(2.01) == 51
    assert frame_count(0.0) == 1


def test_a_picture_is_drawn_only_when_the_layer_changes():
    plan = changes((NOTE,), 1.0)
    assert [number for number, _ in plan] == [0, 5, 15]
    assert [shown for _, shown in plan] == [(), ((0, None, 1.0),), ()]


def test_what_grows_is_drawn_frame_by_frame():
    numbers = [number for number, _ in changes((RING,), 2.0)]
    # Empty, five frames of the ring from 1.00 s to 1.16 s, and empty again at 1.20 s.
    assert numbers == [0, 25, 26, 27, 28, 29, 30]


def test_a_take_that_shows_nothing_has_one_empty_state():
    assert changes((), 3.0) == [(0, ())]


def test_each_picture_of_the_list_is_shown_until_the_next():
    assert listing([0, 5, 15], 25) == (
        "ffconcat version 1.0\n"
        "file '000000.png'\nduration 0.20\n"
        "file '000005.png'\nduration 0.40\n"
        "file '000015.png'\nduration 0.40\n"
        # ffmpeg reads the time of the last picture only when it is named once more.
        "file '000015.png'\n"
    )


def test_nothing_is_drawn_for_a_take_that_shows_nothing(tmp_path):
    assert draw(TakeLog(viewport=(640, 360)), 2.0, tmp_path / "overlay") is None
    assert not (tmp_path / "overlay").exists()


@pytest.fixture
def ffmpeg(monkeypatch):
    monkeypatch.delenv("HOWTO_FFMPEG", raising=False)
    try:
        return find_tool("ffmpeg", "HOWTO_FFMPEG")
    except RunError:
        pytest.skip("ffmpeg is not installed")


@pytest.mark.browser
def test_the_pictures_are_see_through_except_where_something_is_shown(chromium, ffmpeg, tmp_path):
    log = TakeLog(viewport=(640, 360), shown=(
        Shown("note", 0.2, 0.6, note_html("Use a work address.")),
        Shown("click", 0.4, 0.8, ring_html(100.0, 100.0), grow=0.4),
    ))
    frames = draw(log, 1.0, tmp_path / "overlay")
    assert frames == tmp_path / "overlay" / "frames.txt"
    names = sorted(path.name for path in frames.parent.glob("*.png"))
    assert names[0] == "000000.png" and "000005.png" in names and "000020.png" in names
    assert frames.read_text().startswith("ffconcat version 1.0\nfile '000000.png'\nduration 0.20\n")
    middle_of_the_note = {"x": 270, "y": 280, "width": 100, "height": 20}
    assert alpha(ffmpeg, frames.parent / "000000.png", **middle_of_the_note) == 0
    assert alpha(ffmpeg, frames.parent / "000005.png", **middle_of_the_note) > 200
    assert alpha(ffmpeg, frames.parent / "000020.png", **middle_of_the_note) == 0


@pytest.mark.browser
def test_a_ring_is_drawn_larger_as_it_spreads(chromium, ffmpeg, tmp_path):
    log = TakeLog(viewport=(640, 360), shown=(Shown("click", 0.0, 0.44, ring_html(100.0, 100.0), grow=0.44),))
    frames = draw(log, 0.6, tmp_path / "overlay")
    # At 26 pixels from the middle there is nothing while the ring is small, and its line once it has spread.
    edge = {"x": 122, "y": 96, "width": 8, "height": 8}
    assert alpha(ffmpeg, frames.parent / "000001.png", **edge) == 0
    assert alpha(ffmpeg, frames.parent / "000008.png", **edge) > 0
