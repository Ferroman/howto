"""Builds the narration track, joins it with the captured video, and writes the subtitles.

The three outputs are written under temporary names and renamed at the end,
so a failed assembly never replaces an earlier good video.
"""
from __future__ import annotations

import json
import math
import os
import wave
from pathlib import Path
from typing import Sequence

from .desktop import picture
from .errors import RunError
from .narrate import CHANNELS, RATE, WIDTH
from .timeline import ClipTime, StepTime, to_json
from .tools import run


def narration_track(steps: Sequence[StepTime], length: float, out: Path) -> None:
    """One WAV of `length` seconds: silence, with every clip written at its start time.

    The track grows when a clip ends after `length`, so narration is never cut off.
    """
    frame = CHANNELS * WIDTH
    track = bytearray(max(0, math.ceil(length * RATE)) * frame)
    for step in steps:
        for clip in step.clips:
            with wave.open(clip.path, "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, CHANNELS, WIDTH):
                    raise RunError(f"{clip.path}: expected {RATE} Hz, mono, 16-bit")
                data = wav.readframes(wav.getnframes())
            at = round(clip.start * RATE) * frame
            if at + len(data) > len(track):
                track.extend(bytes(at + len(data) - len(track)))
            track[at:at + len(data)] = data
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(WIDTH)
        wav.setframerate(RATE)
        wav.writeframes(bytes(track))


def _stamp(seconds: float, separator: str) -> str:
    total = max(0, round(seconds * 1000))
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    whole, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}{separator}{millis:03d}"


def _cues(steps: Sequence[StepTime]) -> list[ClipTime]:
    return [clip for step in steps for clip in step.clips]


def srt(steps: Sequence[StepTime]) -> str:
    return "".join(
        f"{number}\n{_stamp(cue.start, ',')} --> {_stamp(cue.end, ',')}\n{cue.text}\n\n"
        for number, cue in enumerate(_cues(steps), 1)
    )


def vtt(steps: Sequence[StepTime]) -> str:
    return "WEBVTT\n\n" + "".join(
        f"{_stamp(cue.start, '.')} --> {_stamp(cue.end, '.')}\n{cue.text}\n\n" for cue in _cues(steps)
    )


def mux_command(ffmpeg: str, video: Path, audio: Path, title: str, out: Path, length: float) -> list[str]:
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "25",
        "-c:a", "aac", "-b:a", "160k",
        "-metadata", f"title={title}",
        "-movflags", "+faststart",
        "-t", f"{length:.3f}",
        # The temporary name does not end in .mp4, so the format is named here.
        "-f", "mp4", str(out),
    ]


def desktop_command(
    ffmpeg: str, video: Path, audio: Path, title: str, out: Path, length: float, *,
    head: float, graph: str, overlay: str | None,
) -> list[str]:
    """The assembly of a desktop take: the head of the recording is left out, and the overlay is laid on.

    `overlay` is the list of the overlay's pictures, as ffmpeg finds it from the folder it runs in.
    """
    command = [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{head:.3f}", "-i", str(video)]
    if overlay is not None:
        command += ["-f", "concat", "-safe", "0", "-i", overlay]
    return command + [
        "-i", str(audio),
        "-filter_complex", graph, "-map", "[v]", "-map", f"{1 if overlay is None else 2}:a:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "25",
        "-c:a", "aac", "-b:a", "160k",
        "-metadata", f"title={title}",
        "-movflags", "+faststart",
        "-t", f"{length:.3f}",
        "-f", "mp4", str(out),
    ]


def length_of(steps: Sequence[StepTime], fallback: float = 0.0) -> float:
    """Where a take ends: with its last step, or with its last clip when the narration runs longer."""
    return max([step.end for step in steps] + [clip.end for step in steps for clip in step.clips], default=fallback)


def video_duration(ffprobe: str, video: Path) -> float:
    proc = run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        "ffprobe",
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise RunError(f"ffprobe gave no duration for {video}") from None


def assemble(
    *,
    video: Path,
    steps: Sequence[StepTime],
    title: str,
    name: str,
    out_dir: Path,
    work: Path,
    ffmpeg: str,
    ffprobe: str,
    layer: "picture.Layer | None" = None,
) -> dict[str, Path]:
    # Asking for the recording's length is also the check that it is a readable video.
    recorded = video_duration(ffprobe, video)
    # The recording is longer than the take: Playwright's recorder repeats the
    # last frame when it stops, by a second or more when the picture changed
    # at the very end, and the recording of a desktop begins before the take.
    # The output ends where the timeline ends.
    length = length_of(steps, recorded)
    audio = work / "narration.wav"
    narration_track(steps, length, audio)
    (work / "timeline.json").write_text(json.dumps(to_json(steps, length), indent=2), encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    final = {kind: out_dir / f"{name}.{kind}" for kind in ("mp4", "srt", "vtt")}
    part = {kind: out_dir / f".{name}.{kind}.part" for kind in final}
    try:
        if layer is None:
            run(mux_command(ffmpeg, video, audio, title, part["mp4"], length), "ffmpeg (assembly)")
        else:
            # ffmpeg reads a % in the path of a picture as the place of a number, and the work folder
            # may have one in its name. So ffmpeg runs in the folder of the pictures and is given their
            # list without a path, as `animation` does with its frames.
            frames = layer.frames
            command = desktop_command(
                ffmpeg, video.resolve(), audio.resolve(), title, part["mp4"].resolve(), length,
                head=layer.log.head, graph=picture.graph(layer), overlay=frames.name if frames else None,
            )
            run(command, "ffmpeg (assembly)", cwd=frames.parent if frames else None)
        part["srt"].write_text(srt(steps), encoding="utf-8")
        part["vtt"].write_text(vtt(steps), encoding="utf-8")
        for kind in final:
            os.replace(part[kind], final[kind])
    finally:
        for path in part.values():
            path.unlink(missing_ok=True)
    return final
