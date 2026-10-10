"""The timing arithmetic of a take, and the timeline a take produces.

Within a step the first clip starts at the start of the step, and the step
ends after both the narration and the actions, plus a gap and any pause.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .narrate import Clip


@dataclass(frozen=True)
class ClipTime:
    text: str
    path: str
    start: float
    end: float


@dataclass(frozen=True)
class StepTime:
    index: int
    start: float
    end: float
    clips: tuple[ClipTime, ...] = ()


def clip_offsets(durations: Sequence[float], sentence_gap: float) -> list[tuple[float, float]]:
    """Start and end of each clip, relative to the start of its step."""
    offsets, at = [], 0.0
    for duration in durations:
        offsets.append((at, at + duration))
        at += duration + sentence_gap
    return offsets


def narration_length(durations: Sequence[float], sentence_gap: float) -> float:
    offsets = clip_offsets(durations, sentence_gap)
    return offsets[-1][1] if offsets else 0.0


def step_hold(*, elapsed: float, narration: float, gap: float, pause: float) -> float:
    """Seconds still to wait at the end of a step.

    `elapsed` is the time since the step started, which already includes the
    lead and the actions. The step lasts max(elapsed, narration) + gap + pause.
    """
    return max(elapsed, narration) + gap + pause - elapsed


def place_clips(step_start: float, clips: Sequence[Clip], sentence_gap: float) -> tuple[ClipTime, ...]:
    offsets = clip_offsets([clip.duration for clip in clips], sentence_gap)
    return tuple(
        ClipTime(text=clip.text, path=str(clip.path), start=step_start + start, end=step_start + end)
        for clip, (start, end) in zip(clips, offsets)
    )


def narration_only(
    clips: Mapping[int, Sequence[Clip]], sentence_gap: float, gap: float
) -> tuple[tuple[StepTime, ...], float]:
    """A timeline with no browser: each step lasts its narration plus the gap."""
    steps, at = [], 0.0
    for index in sorted(clips):
        placed = place_clips(at, clips[index], sentence_gap)
        end = (placed[-1].end if placed else at) + gap
        steps.append(StepTime(index=index, start=at, end=end, clips=placed))
        at = end
    return tuple(steps), at


def to_json(steps: Sequence[StepTime], video_duration: float) -> dict:
    # Built by hand: dataclasses.asdict keeps the clips as a tuple, and the
    # file is meant to be plain JSON lists and mappings.
    return {
        "video_duration": video_duration,
        "steps": [
            {"index": step.index, "start": step.start, "end": step.end, "clips": [asdict(clip) for clip in step.clips]}
            for step in steps
        ],
    }
