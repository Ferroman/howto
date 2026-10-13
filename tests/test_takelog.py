"""The log of a desktop take: written by the stage, read by the assembly."""
from pathlib import Path

import pytest

from howto.desktop import takelog
from howto.desktop.takelog import Shown, TakeLog
from howto.errors import RunError

LOG = TakeLog(
    viewport=(1280, 720),
    head=0.84,
    shown=(
        Shown("card", 0.0, 2.3, "<div>Add a name</div>", grow=0.3, fade=0.3),
        Shown("note", 2.5, 6.0, "<div>Use a work address.</div>"),
        Shown("click", 3.1, 3.55, "<div></div>", grow=0.45),
    ),
)


def test_the_log_lies_beside_the_recording():
    assert takelog.beside(Path("/work/add-x1/capture.mkv")) == Path("/work/add-x1/take.json")


def test_a_log_comes_back_as_it_was_written(tmp_path):
    takelog.write(LOG, tmp_path / "take.json")
    assert takelog.read(tmp_path / "take.json") == LOG


def test_a_take_that_shows_nothing_has_an_empty_log(tmp_path):
    takelog.write(TakeLog(viewport=(1920, 1080)), tmp_path / "take.json")
    assert takelog.read(tmp_path / "take.json") == TakeLog(viewport=(1920, 1080), head=0.0, shown=())


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"viewport": [1280, 720]}', '{"viewport": 5, "head": 0, "shown": []}'])
def test_a_file_that_is_no_log_is_named(tmp_path, content):
    path = tmp_path / "take.json"
    path.write_text(content)
    with pytest.raises(RunError, match="take.json: not the log of a take"):
        takelog.read(path)


def test_a_missing_log_is_named(tmp_path):
    with pytest.raises(RunError, match="take.json: not the log of a take"):
        takelog.read(tmp_path / "take.json")
