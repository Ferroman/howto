from pathlib import Path

import pytest

from howto.narrate import Clip
from howto.timeline import (
    ClipTime,
    StepTime,
    clip_offsets,
    narration_length,
    narration_only,
    place_clips,
    step_hold,
    to_json,
)


def clip(seconds, text="x"):
    return Clip(text=text, path=Path(f"/clips/{text}.wav"), duration=seconds)


def test_clip_offsets_leave_a_gap_between_sentences():
    assert clip_offsets([1.0, 2.0], 0.15) == [(0.0, 1.0), (1.15, 3.15)]


def test_narration_length():
    assert narration_length([1.0, 2.0], 0.15) == pytest.approx(3.15)
    assert narration_length([], 0.15) == 0.0


def test_hold_waits_for_the_narration():
    # 0.8 s gone (lead and actions), 3.15 s of narration: the step lasts 3.15 + 0.4.
    assert step_hold(elapsed=0.8, narration=3.15, gap=0.4, pause=0.0) == pytest.approx(2.75)


def test_hold_is_only_the_gap_when_the_actions_took_longer():
    assert step_hold(elapsed=5.5, narration=1.0, gap=0.4, pause=0.0) == pytest.approx(0.4)


def test_hold_adds_the_pause():
    assert step_hold(elapsed=1.0, narration=1.0, gap=0.4, pause=2.0) == pytest.approx(2.4)


def test_place_clips_uses_video_time():
    placed = place_clips(10.0, [clip(1.0, "a"), clip(2.0, "b")], 0.15)
    assert placed == (
        ClipTime(text="a", path="/clips/a.wav", start=10.0, end=11.0),
        ClipTime(text="b", path="/clips/b.wav", start=11.15, end=13.15),
    )


def test_narration_only_puts_steps_back_to_back():
    steps, length = narration_only({1: [clip(1.0, "a"), clip(2.0, "b")], 3: [clip(0.5, "c")]}, 0.15, 0.4)
    assert [(s.index, s.start, pytest.approx(s.end)) for s in steps] == [(1, 0.0, 3.55), (3, pytest.approx(3.55), 4.45)]
    assert steps[1].clips[0].start == pytest.approx(3.55)
    assert length == pytest.approx(4.45)


def test_to_json():
    steps = (StepTime(1, 0.0, 2.0, (ClipTime("a", "/clips/a.wav", 0.0, 1.0),)),)
    assert to_json(steps, 2.5) == {
        "video_duration": 2.5,
        "steps": [
            {"index": 1, "start": 0.0, "end": 2.0, "clips": [{"text": "a", "path": "/clips/a.wav", "start": 0.0, "end": 1.0}]}
        ],
    }
