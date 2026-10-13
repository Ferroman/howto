import json
import struct
import wave

import pytest

from howto.assemble import assemble, desktop_command, length_of, mux_command, narration_track, srt, video_duration, vtt
from howto.errors import RunError
from howto.desktop.picture import Layer
from howto.desktop.takelog import TakeLog
from howto.timeline import ClipTime, StepTime


def write_wav(path, seconds, value, rate=48000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack("<h", value) * round(seconds * rate))
    return path


def samples(path):
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        data = wav.readframes(wav.getnframes())
    return struct.unpack(f"<{len(data) // 2}h", data)


def two_steps(tmp_path):
    a = write_wav(tmp_path / "a.wav", 0.5, 1000)
    b = write_wav(tmp_path / "b.wav", 0.25, 2000)
    return (
        StepTime(1, 0.0, 2.0, (ClipTime("Open the menu.", str(a), 0.5, 1.0),)),
        StepTime(2, 2.0, 3.0, (ClipTime("Pick Settings.", str(b), 2.0, 2.25),)),
    )


def test_each_clip_lands_at_its_start_time(tmp_path):
    out = tmp_path / "track.wav"
    narration_track(two_steps(tmp_path), 3.0, out)
    track = samples(out)
    assert len(track) == 3 * 48000
    assert (track[23999], track[24000], track[47999], track[48000]) == (0, 1000, 1000, 0)
    assert (track[95999], track[96000], track[107999], track[108000]) == (0, 2000, 2000, 0)


def test_the_track_grows_when_narration_outlasts_the_video(tmp_path):
    late = write_wav(tmp_path / "late.wav", 1.0, 3000)
    steps = (StepTime(1, 2.0, 3.0, (ClipTime("Late.", str(late), 2.5, 3.5),)),)
    out = tmp_path / "track.wav"
    narration_track(steps, 3.0, out)
    track = samples(out)
    assert len(track) == round(3.5 * 48000)
    assert track[-1] == 3000


def test_no_narration_gives_silence_of_the_video_length(tmp_path):
    out = tmp_path / "track.wav"
    narration_track((StepTime(1, 0.0, 2.0),), 2.0, out)
    track = samples(out)
    assert len(track) == 2 * 48000 and set(track) == {0}


def test_a_clip_in_another_format_is_refused(tmp_path):
    odd = write_wav(tmp_path / "odd.wav", 0.5, 1000, rate=22050)
    steps = (StepTime(1, 0.0, 1.0, (ClipTime("Odd.", str(odd), 0.0, 0.5),)),)
    with pytest.raises(RunError, match="expected 48000 Hz, mono, 16-bit"):
        narration_track(steps, 1.0, tmp_path / "track.wav")


def test_srt_and_vtt(tmp_path):
    steps = (
        StepTime(1, 0.0, 2.0, (ClipTime("Open the menu.", "a.wav", 0.5, 1.0),)),
        StepTime(2, 3661.0, 3663.0, (ClipTime("Pick Settings.", "b.wav", 3661.25, 3662.5),)),
    )
    assert srt(steps) == (
        "1\n00:00:00,500 --> 00:00:01,000\nOpen the menu.\n\n"
        "2\n01:01:01,250 --> 01:01:02,500\nPick Settings.\n\n"
    )
    assert vtt(steps) == (
        "WEBVTT\n\n"
        "00:00:00.500 --> 00:00:01.000\nOpen the menu.\n\n"
        "01:01:01.250 --> 01:01:02.500\nPick Settings.\n\n"
    )


def test_no_narration_gives_empty_subtitle_files():
    silent = (StepTime(1, 0.0, 2.0),)
    assert srt(silent) == ""
    assert vtt(silent) == "WEBVTT\n\n"


def test_mux_command(tmp_path):
    command = mux_command(
        "ffmpeg", tmp_path / "capture.webm", tmp_path / "narration.wav", "Invite a teammate", tmp_path / "out.part", 12.5
    )
    assert command[0] == "ffmpeg" and command[-1] == str(tmp_path / "out.part")
    joined = " ".join(command)
    for piece in ("-c:v libx264", "-crf 18", "-pix_fmt yuv420p", "-r 25", "-c:a aac", "-b:a 160k", "-f mp4", "-movflags +faststart"):
        assert piece in joined
    assert command[command.index("-metadata") + 1] == "title=Invite a teammate"
    assert command.count("-i") == 2
    assert command[command.index("-t") + 1] == "12.500"


def test_video_duration_reads_ffprobe(fakes, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "12.5")
    assert video_duration(fakes.ffprobe, tmp_path / "capture.webm") == 12.5
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "N/A")
    with pytest.raises(RunError, match="no duration"):
        video_duration(fakes.ffprobe, tmp_path / "capture.webm")


def run_assemble(fakes, tmp_path):
    video = tmp_path / "capture.webm"
    video.write_bytes(b"fake webm")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return assemble(
        video=video, steps=two_steps(tmp_path), title="Demo", name="demo",
        out_dir=tmp_path / "out", work=work, ffmpeg=fakes.ffmpeg, ffprobe=fakes.ffprobe,
    )


def test_assemble_writes_the_three_outputs(fakes, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "3.0")
    outputs = run_assemble(fakes, tmp_path)
    out = tmp_path / "out"
    assert outputs == {"mp4": out / "demo.mp4", "srt": out / "demo.srt", "vtt": out / "demo.vtt"}
    assert outputs["mp4"].read_bytes() == b"fake mp4"
    assert outputs["srt"].read_text().count(" --> ") == 2
    assert outputs["vtt"].read_text().startswith("WEBVTT")
    assert sorted(p.name for p in out.iterdir()) == ["demo.mp4", "demo.srt", "demo.vtt"]
    assert len(samples(tmp_path / "work" / "narration.wav")) == 3 * 48000
    timeline = json.loads((tmp_path / "work" / "timeline.json").read_text())
    assert timeline["video_duration"] == 3.0 and len(timeline["steps"]) == 2


def test_the_output_ends_with_the_timeline_not_with_the_recording(fakes, monkeypatch, tmp_path):
    # The recorder ran on for two seconds after the last step ended at 3.0 s.
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "5.0")
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    run_assemble(fakes, tmp_path)
    assert " -t 3.000 " in log.read_text()
    assert len(samples(tmp_path / "work" / "narration.wav")) == 3 * 48000
    assert json.loads((tmp_path / "work" / "timeline.json").read_text())["video_duration"] == 3.0


def test_a_failed_assembly_keeps_the_earlier_outputs(fakes, monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "demo.mp4").write_bytes(b"earlier video")
    (out / "demo.srt").write_text("earlier subtitles")
    monkeypatch.setenv("FAKE_FFMPEG_FAIL", "mux")
    with pytest.raises(RunError, match="told to fail the assembly"):
        run_assemble(fakes, tmp_path)
    assert (out / "demo.mp4").read_bytes() == b"earlier video"
    assert (out / "demo.srt").read_text() == "earlier subtitles"
    assert sorted(p.name for p in out.iterdir()) == ["demo.mp4", "demo.srt"]


def test_a_take_ends_with_its_last_step_or_its_last_clip(tmp_path):
    steps = two_steps(tmp_path)
    assert length_of(steps) == 3.0
    late = (StepTime(1, 0.0, 2.0, (ClipTime("Late.", "late.wav", 1.5, 2.5),)),)
    assert length_of(late) == 2.5
    assert length_of((), fallback=7.0) == 7.0


def test_the_command_of_a_desktop_take_leaves_the_head_out_and_lays_the_overlay_on(tmp_path):
    command = desktop_command(
        "ffmpeg", tmp_path / "capture.mkv", tmp_path / "narration.wav", "Add a name", tmp_path / "out.part", 12.5,
        head=0.84, graph="[0:v]fps=25[base];[base][1:v]overlay=0:0:eof_action=repeat[v]", overlay="frames.txt",
    )
    joined = " ".join(command)
    # The head is left out before the recording is read, so the picture starts where the take does.
    assert joined.index("-ss 0.840") < joined.index(f"-i {tmp_path / 'capture.mkv'}")
    assert "-f concat -safe 0 -i frames.txt" in joined
    assert command.count("-i") == 3
    assert "-map [v] -map 2:a:0" in joined
    for piece in ("-c:v libx264", "-crf 18", "-pix_fmt yuv420p", "-r 25", "-c:a aac", "-f mp4", "-t 12.500"):
        assert piece in joined
    assert command[-1] == str(tmp_path / "out.part")


def test_a_desktop_take_that_shows_nothing_has_two_inputs(tmp_path):
    command = desktop_command(
        "ffmpeg", tmp_path / "capture.mkv", tmp_path / "narration.wav", "Add a name", tmp_path / "out.part", 5.0,
        head=0.0, graph="[0:v]fps=25[v]", overlay=None,
    )
    joined = " ".join(command)
    assert command.count("-i") == 2 and "concat" not in joined
    assert "-map [v] -map 1:a:0" in joined and "-ss 0.000" in joined


def run_desktop_assemble(fakes, tmp_path, monkeypatch, work_name="work", frames=True):
    """Assembles a desktop take with the fake ffmpeg, and returns the line with which the fake was called."""
    work = tmp_path / work_name
    (work / "overlay").mkdir(parents=True)
    video = work / "capture.mkv"
    video.write_bytes(b"fake mkv")
    listing = work / "overlay" / "frames.txt"
    listing.write_text("ffconcat version 1.0\n")
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    outputs = assemble(
        video=video, steps=two_steps(tmp_path), title="Add a name", name="add", out_dir=tmp_path / "out", work=work,
        ffmpeg=fakes.ffmpeg, ffprobe=fakes.ffprobe,
        layer=Layer(TakeLog(viewport=(1280, 720), head=0.84), listing if frames else None),
    )
    return outputs, log.read_text().splitlines()[-1]


def test_assemble_lays_the_overlay_of_a_desktop_take_on_its_recording(fakes, monkeypatch, tmp_path):
    outputs, called = run_desktop_assemble(fakes, tmp_path, monkeypatch)
    assert outputs["mp4"].read_bytes() == b"fake mp4"
    assert "-ss 0.840" in called and "overlay=0:0:eof_action=repeat" in called
    assert outputs["srt"].read_text().count(" --> ") == 2


def test_the_list_of_pictures_is_named_without_its_folder(fakes, monkeypatch, tmp_path):
    # ffmpeg reads a % in the path of a picture as the place of a number.
    outputs, called = run_desktop_assemble(fakes, tmp_path, monkeypatch, work_name="50%-off")
    assert "-i frames.txt " in called
    assert outputs["mp4"].exists()


def test_a_desktop_take_that_shows_nothing_is_assembled_without_a_layer(fakes, monkeypatch, tmp_path):
    outputs, called = run_desktop_assemble(fakes, tmp_path, monkeypatch, frames=False)
    assert "[0:v]fps=25[v]" in called and "concat" not in called
    assert outputs["mp4"].exists()
