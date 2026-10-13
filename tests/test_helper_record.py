"""The helper's recording: the ffmpeg command, and the time of the first frame."""
from howto.desktop.helper.record import command, first_frame


def test_ffmpeg_films_the_whole_monitor_with_the_pointer_at_25_frames():
    built = command(1920, 1080)
    joined = " ".join(built)
    assert built[0] == "ffmpeg" and built[-1] == "/tmp/howto/take.mkv"
    for piece in ("-f x11grab", "-draw_mouse 1", "-framerate 25", "-video_size 1920x1080", "-i :99", "-nostdin"):
        assert piece in joined
    # One key frame a second, so that the assembly can start at any moment of the recording.
    assert "-g 25" in joined


def test_a_first_frame_on_the_wall_clock_is_moved_to_the_steady_clock():
    # The wall clock said 1 760 000 000 when the steady clock said 5 000.
    assert first_frame(1_760_000_002.5, wall=1_760_000_000.0, steady=5_000.0) == 5_002.5


def test_a_first_frame_on_the_steady_clock_is_taken_as_it_is():
    assert first_frame(5_002.5, wall=1_760_000_000.0, steady=5_000.0) == 5_002.5
