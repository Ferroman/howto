"""The filters that turn the recording of a desktop take into the picture."""
from pathlib import Path

from howto.desktop.picture import Layer, graph
from howto.desktop.takelog import TakeLog

LOG = TakeLog(viewport=(1920, 1080), head=0.8)


def test_the_overlay_is_laid_on_the_recording_and_its_last_picture_stays():
    layer = Layer(LOG, Path("/work/overlay/frames.txt"))
    assert graph(layer) == "[0:v]fps=25[base];[base][1:v]overlay=0:0:eof_action=repeat[v]"


def test_a_take_that_shows_nothing_only_gets_its_frame_rate():
    assert graph(Layer(LOG)) == "[0:v]fps=25[v]"
