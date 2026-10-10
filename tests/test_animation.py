import subprocess

import pytest

from pictures import dimensions, gif_frames, webp
from howto.animation import (
    FPS,
    animate,
    filters,
    frame_count,
    frames_command,
    gif_command,
    listing,
    shown,
    size,
    webp_command,
)
from howto.errors import RunError
from howto.tools import find_tool
from howto.zoom import Box

WINDOW = (1920, 1080)
PANEL = Box(948, 88, 324, 424)


def test_a_picture_of_the_whole_window_is_scaled_down_to_the_width():
    assert size(None, WINDOW, 960) == (960, 540)
    assert filters(None, WINDOW, 960) == "fps=12.5,scale=960:540:flags=lanczos,mpdecimate"


def test_a_crop_that_is_narrower_than_the_width_keeps_its_own_size():
    # Enlarging a picture gives it no more detail, only more bytes.
    assert size(PANEL, WINDOW, 960) == (324, 424)
    assert filters(PANEL, WINDOW, 960) == "crop=324:424:948:88,fps=12.5,mpdecimate"


def test_a_wide_crop_is_cut_first_and_scaled_after():
    assert size(Box(100, 40, 1200, 500), WINDOW, 600) == (600, 250)
    assert filters(Box(100, 40, 1200, 500), WINDOW, 600) == "crop=1200:500:100:40,fps=12.5,scale=600:250:flags=lanczos,mpdecimate"


def test_a_take_is_counted_in_whole_frames():
    # At 12.5 frames a second a frame lasts 0.08 s.
    assert frame_count(8.96) == 112
    assert frame_count(3.0) == 38  # 37.5: the half frame at the end is shown as a whole one
    assert frame_count(0.01) == 1


def test_a_frame_is_shown_until_the_next_one_that_differs():
    # Of 12 frames, the picture changed at 0, 7, 8 and 9. The last one stays to the end.
    assert shown([0, 7, 8, 9], 12) == [7, 1, 1, 3]


def test_the_first_number_need_not_be_zero():
    # A recording whose first time stamp is not 0 numbers its frames from there.
    assert shown([3, 10, 11], 12) == [7, 1, 4]


def test_a_recording_that_ran_a_frame_longer_still_shows_its_last_frame():
    assert shown([0, 5, 12], 12) == [5, 7, 1]


def test_the_listing_gives_each_frame_its_time(tmp_path):
    assert listing(["000000.png", "000007.png"], [7, 5]) == (
        "ffconcat version 1.0\n"
        "file '000000.png'\nduration 0.56\n"
        "file '000007.png'\nduration 0.40\n"
    )


def test_the_frames_command_writes_only_the_frames_that_differ(tmp_path):
    command = frames_command("ffmpeg", tmp_path / "capture.webm", 9.04, "fps=12.5,mpdecimate")
    joined = " ".join(command)
    assert command[0] == "ffmpeg" and command[-1] == "%06d.png"
    assert command[command.index("-t") + 1] == "9.040"
    assert command.index("-t") < command.index("-i"), "the length must limit the recording, not the output"
    assert command[command.index("-vf") + 1] == "fps=12.5,mpdecimate"
    # Without these two every frame is written, or the files are numbered 1, 2, 3.
    assert "-fps_mode vfr" in joined and "-frame_pts 1" in joined


def test_the_gif_command_keeps_the_pause_at_the_end(tmp_path):
    command = gif_command("ffmpeg", tmp_path / "frames.txt", 27, tmp_path / "out.part")
    joined = " ".join(command)
    assert command[-1] == str(tmp_path / "out.part")
    # The last frame has no successor to measure its time from, so it is given here, in 1/100 s.
    assert command[command.index("-final_delay") + 1] == str(27 * 8)
    for piece in ("-f concat", "-loop 0", "-f gif", "-fps_mode vfr", "palettegen", "dither=none"):
        assert piece in joined


def test_the_webp_command_gives_each_frame_its_time(tmp_path):
    frames = [(tmp_path / "000000.png", 7), (tmp_path / "000007.png", 5)]
    command = webp_command("img2webp", frames, tmp_path / "out.part")
    assert command[0] == "img2webp" and command[-2:] == ["-o", str(tmp_path / "out.part")]
    assert command[command.index("-loop") + 1] == "0"
    assert "-lossy" in command
    first = command.index(str(tmp_path / "000000.png"))
    second = command.index(str(tmp_path / "000007.png"))
    assert command[first - 2:first] == ["-d", "560"]
    assert command[second - 2:second] == ["-d", "400"]


@pytest.fixture
def tools(monkeypatch):
    """The real ffmpeg, ffprobe and img2webp."""
    for name in ("HOWTO_FFMPEG", "HOWTO_FFPROBE", "HOWTO_IMG2WEBP"):
        monkeypatch.delenv(name, raising=False)
    try:
        return tuple(find_tool(name, f"HOWTO_{name.upper()}") for name in ("ffmpeg", "ffprobe", "img2webp"))
    except RunError as exc:
        pytest.skip(str(exc))


def recording(ffmpeg, path, *, size="320x240"):
    """Three seconds of video: a red square crosses a white picture in the first second, then nothing moves."""
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c=white:s={size}:r=25:d=3",
         "-f", "lavfi", "-i", "color=c=red:s=40x40:r=25:d=3",
         "-filter_complex", "[0][1]overlay=x='if(lt(t,1),t*200,200)':y=100",
         "-c:v", "libvpx", "-b:v", "1M", str(path)],
        check=True,
    )
    return path


def make(tools, tmp_path, **changes):
    ffmpeg, _, img2webp = tools
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    options = dict(
        video=recording(ffmpeg, tmp_path / "capture.webm"), length=3.0, crop=None, viewport=(320, 240), width=160,
        formats=("gif", "webp"), name="demo", out_dir=tmp_path / "out", work=work, ffmpeg=ffmpeg, img2webp=img2webp,
    )
    options.update(changes)
    return animate(**options)


def test_both_pictures_are_written_and_nothing_else(tools, tmp_path):
    picture = make(tools, tmp_path)
    out = tmp_path / "out"
    assert picture.files == {"gif": out / "demo.gif", "webp": out / "demo.webp"}
    assert sorted(p.name for p in out.iterdir()) == ["demo.gif", "demo.webp"]
    assert (picture.width, picture.height) == (160, 120)
    # Three seconds are 37.5 frames, and the picture has 38.
    assert picture.seconds == pytest.approx(3.04)


def test_the_gif_lasts_as_long_as_the_take_with_its_still_end(tools, tmp_path):
    picture = make(tools, tmp_path)
    frames = gif_frames(tools[1], picture.files["gif"])
    assert dimensions(tools[1], picture.files["gif"]) == (160, 120)
    # Nothing moves after the first second, so few frames are kept, and the last one is held to the end.
    assert len(frames) < 3 * FPS / 2
    start, length = frames[-1]
    assert start + length == pytest.approx(3.04)
    assert length > 1.5


def test_the_webp_lasts_as_long_and_loops_for_ever(tools, tmp_path):
    picture = make(tools, tmp_path)
    canvas, times, loops = webp(picture.files["webp"])
    assert canvas == (160, 120)
    assert sum(times) == 3040  # 38 frames of 80 ms
    assert times[-1] > 1500 and loops == 0


def test_the_picture_is_cut_to_the_crop(tools, tmp_path):
    picture = make(tools, tmp_path, crop=Box(180, 80, 100, 80))
    assert (picture.width, picture.height) == (100, 80)
    assert dimensions(tools[1], picture.files["gif"]) == (100, 80)
    assert webp(picture.files["webp"])[0] == (100, 80)


def test_one_format_alone_needs_only_its_own_tool(tools, tmp_path):
    picture = make(tools, tmp_path, formats=("gif",), img2webp=None)
    assert list(picture.files) == ["gif"]
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["demo.gif"]


def test_a_failed_picture_keeps_the_earlier_ones(tools, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "demo.gif").write_bytes(b"earlier gif")
    with pytest.raises(RunError, match="img2webp"):
        make(tools, tmp_path, img2webp="/nonexistent/img2webp")
    # The GIF was made before the WebP failed, and still the earlier one stays.
    assert (out / "demo.gif").read_bytes() == b"earlier gif"
    assert [p.name for p in out.iterdir()] == ["demo.gif"]


def test_a_recording_that_cannot_be_read_is_an_error(tools, tmp_path):
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"not a video")
    with pytest.raises(RunError, match="ffmpeg"):
        make(tools, tmp_path, video=broken)
    assert not (tmp_path / "out" / "demo.gif").exists()


def test_a_name_with_a_percent_sign_is_not_read_as_a_pattern(tools, tmp_path):
    work = tmp_path / "50%d-work"
    work.mkdir()
    picture = make(tools, tmp_path, work=work, name="50%d")
    assert picture.files["gif"].name == "50%d.gif" and picture.files["gif"].stat().st_size > 100
