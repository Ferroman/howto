"""The filters that turn the recording of a desktop take into the picture."""
import subprocess
from pathlib import Path

import pytest

from howto.desktop.picture import Layer, curve, graph, sized
from howto.desktop.takelog import Move, TakeLog
from howto.errors import RunError
from howto.tools import find_tool

LOG = TakeLog(viewport=(1920, 1080), head=0.8)


def test_the_overlay_is_laid_on_the_recording_and_its_last_picture_stays():
    layer = Layer(LOG, Path("/work/overlay/frames.txt"))
    assert graph(layer) == "[0:v]fps=25[base];[base][1:v]overlay=0:0:eof_action=repeat[v]"


def test_a_take_that_shows_nothing_only_gets_its_frame_rate():
    assert graph(Layer(LOG)) == "[0:v]fps=25[v]"


def test_a_value_that_never_changes_is_a_number():
    assert curve(1.0, [], "it") == "1.000000"


def test_a_value_eases_from_one_number_to_the_next():
    assert curve(0.0, [(0.5, 0.8, 480.0)], "it") == (
        "if(lt(it,1.300),if(lt(it,0.500),0.000000,"
        "(0.000000+480.000000*((it-0.500)/0.800)*((it-0.500)/0.800)*(3-2*((it-0.500)/0.800)))),480.000000)"
    )


def test_a_move_without_seconds_is_a_jump_and_divides_by_nothing():
    assert curve(0.5, [(2.0, 0.0, 1.0)], "it") == "if(lt(it,2.000),0.500000,1.000000)"


def test_several_moves_follow_each_other():
    text = curve(1.0, [(0.5, 0.8, 0.5), (3.0, 0.8, 1.0)], "it")
    assert text.startswith("if(lt(it,1.300),if(lt(it,0.500),1.000000,") and text.endswith(",1.000000))")
    assert "if(lt(it,3.800),if(lt(it,3.000),0.500000," in text


ZOOMED = TakeLog(viewport=(1920, 1080), head=0.8, scale=2, moves=(Move(0.5, 0.8, 480.0, 250.0, 2.0), Move(3.0, 0.8, 0.0, 0.0, 1.0)))


def test_a_take_at_the_picture_s_own_size_is_not_resized():
    assert sized(LOG) == ""


def test_a_larger_recording_in_which_nothing_moved_is_brought_to_the_size_of_the_picture():
    assert sized(TakeLog(viewport=(1920, 1080), scale=2)) == ",scale=1920:1080:flags=area"


def test_the_moves_become_one_filter_that_cuts_the_part_that_is_shown():
    text = sized(ZOOMED)
    assert text.startswith(",zoompan=z='1/(if(lt(it,1.300),if(lt(it,0.500),1.000000,")
    # The corner is in pixels of the picture, and the filter counts in pixels of the recording.
    assert ":x='2*(if(lt(it,1.300),if(lt(it,0.500),0.000000,(0.000000+480.000000*" in text
    assert ":y='2*(if(lt(it,1.300),if(lt(it,0.500),0.000000,(0.000000+250.000000*" in text
    assert text.endswith(":d=1:s=1920x1080:fps=25")


def test_the_zoom_comes_before_the_overlay_and_before_what_follows():
    layer = Layer(TakeLog(viewport=(1920, 1080), scale=2), Path("/work/overlay/frames.txt"))
    assert graph(layer, "fps=12.5") == (
        "[0:v]fps=25,scale=1920:1080:flags=area[base];[base][1:v]overlay=0:0:eof_action=repeat,fps=12.5[v]"
    )
    assert graph(Layer(TakeLog(viewport=(1920, 1080), scale=2))) == "[0:v]fps=25,scale=1920:1080:flags=area[v]"


@pytest.fixture
def ffmpeg():
    try:
        return find_tool("ffmpeg", "HOWTO_FFMPEG")
    except RunError as exc:
        pytest.skip(str(exc))


def dot_in_each_frame(ffmpeg, video):
    """The middle of what is not black in each frame of a video, from ffmpeg's own box around it."""
    printed = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", str(video), "-vf", "bbox=min_val=128,metadata=mode=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    middles, edges = [], {}
    for line in printed.splitlines():
        key, _, number = line.partition("=")
        if key.startswith("lavfi.bbox."):
            edges[key.rsplit(".", 1)[1]] = float(number)
        # `h` is the last of the six values that the filter prints for a frame.
        if key == "lavfi.bbox.h":
            middles.append(((edges["x1"] + edges["x2"] + 1) / 2, (edges["y1"] + edges["y2"] + 1) / 2))
    return middles


def test_the_picture_goes_in_on_a_dot_and_out_again_without_a_shake(ffmpeg, tmp_path):
    # A recording of twice the picture's size, with 0.4 s before the take. The dot is 16 pixels of the monitor,
    # so its middle is at 354, 204 of a picture of 640 by 360.
    recording, zoomed = tmp_path / "capture.mkv", tmp_path / "zoomed.mkv"
    encode = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p"]
    source = "color=black:s=1280x720:r=25:d=4.4,drawbox=x=700:y=400:w=16:h=16:color=white:t=fill"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, *encode, str(recording)], check=True)
    # In at 0.5 s to the part around the dot, which then lies in the middle of the picture. Out at 2.5 s.
    log = TakeLog(viewport=(640, 360), head=0.4, scale=2, moves=(Move(0.5, 0.8, 194.0, 114.0, 2.0), Move(2.5, 0.8, 0.0, 0.0, 1.0)))
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{log.head:.3f}", "-i", str(recording),
         "-filter_complex", graph(Layer(log)), "-map", "[v]", *encode, str(zoomed)],
        check=True,
    )
    middles = dot_in_each_frame(ffmpeg, zoomed)
    assert len(middles) == 100
    assert middles[5] == (354.0, 204.0) and middles[45] == (320.0, 180.0) and middles[95] == (354.0, 204.0)

    def eased(first, changes, at):
        """What `curve` writes as an expression, worked out here."""
        now = first
        for start, seconds, to in changes:
            if at < start:
                return now
            if at < start + seconds:
                part = (at - start) / seconds
                return now + (to - now) * part * part * (3 - 2 * part)
            now = to
        return now

    for frame, (x, y) in enumerate(middles):
        at = frame / 25
        share = eased(1.0, [(move.start, move.seconds, 1 / move.factor) for move in log.moves], at)
        left = eased(0.0, [(move.start, move.seconds, move.left) for move in log.moves], at)
        top = eased(0.0, [(move.start, move.seconds, move.top) for move in log.moves], at)
        wanted = ((354 - left) / share, (204 - top) / share)
        moving = any(move.start - 0.05 <= at <= move.start + move.seconds + 0.05 for move in log.moves)
        # While nothing moves, the dot is exactly in its place. During a move ffmpeg cuts at whole pixels, and
        # the dot may be 2.5 pixels from where the arithmetic puts it: nobody sees that while the picture moves.
        allowed = 2.5 if moving else 0.0
        assert abs(x - wanted[0]) <= allowed and abs(y - wanted[1]) <= allowed, (frame, (x, y), wanted)


def test_what_follows_the_overlay_is_one_chain_with_it():
    layer = Layer(LOG, Path("/work/overlay/frames.txt"))
    assert graph(layer, "crop=324:424:948:88,fps=12.5,mpdecimate") == (
        "[0:v]fps=25[base];[base][1:v]overlay=0:0:eof_action=repeat,crop=324:424:948:88,fps=12.5,mpdecimate[v]"
    )


def test_what_follows_a_take_that_shows_nothing_follows_its_frame_rate():
    assert graph(Layer(LOG), "fps=12.5,mpdecimate") == "[0:v]fps=25,fps=12.5,mpdecimate[v]"
