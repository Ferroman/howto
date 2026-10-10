import wave
from pathlib import Path

import pytest

from howto.errors import RunError
from howto.narrate import clip_key, narrate, speak, tts_command, wav_duration
from howto.storyboard import parse


def board(tmp_path, steps):
    return parse({"title": "Demo", "url": "http://demo.test", "steps": steps}, tmp_path / "demo.yaml")


def test_one_clip_per_sentence(fakes, tmp_path):
    sb = board(tmp_path, [{"say": "Open the menu. Pick Settings."}, {"chapter": "Next"}, {"say": "Done."}])
    clips = narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    assert sorted(clips) == [1, 3]
    assert [clip.text for clip in clips[1]] == ["Open the menu.", "Pick Settings."]
    assert clips[1][0].duration == pytest.approx(0.06 * len("Open the menu."), abs=0.01)
    assert fakes.tts.spoken() == ["Open the menu.", "Pick Settings.", "Done."]


def test_clips_share_one_format(fakes, tmp_path):
    sb = board(tmp_path, [{"say": "Open the menu."}])
    clip = narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)[1][0]
    with wave.open(str(clip.path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
    assert wav_duration(clip.path) == clip.duration


def test_only_a_changed_sentence_is_spoken_again(fakes, tmp_path):
    narrate(board(tmp_path, [{"say": "Open the menu. Pick Settings."}]), cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    narrate(board(tmp_path, [{"say": "Open the menu. Pick Billing."}]), cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    assert fakes.tts.spoken() == ["Open the menu.", "Pick Settings.", "Pick Billing."]


def test_the_key_covers_command_language_and_text():
    base = clip_key("tts", "en", "Hello.")
    assert base == clip_key("tts", "en", "Hello.")
    assert len({base, clip_key("tts -v amy", "en", "Hello."), clip_key("tts", "uk", "Hello."), clip_key("tts", "en", "Hello!")}) == 4


def test_a_command_with_arguments_is_split(fakes, tmp_path):
    clip = speak("Hello.", cache_dir=fakes.sandbox.clips, command=f"{fakes.tts.program} --voice amy", ffmpeg=fakes.ffmpeg)
    assert clip.duration > 0
    assert fakes.tts.spoken() == ["Hello."]


def test_a_tts_failure_carries_its_output_and_leaves_no_files(fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_FAIL", "1")
    with pytest.raises(RunError, match="told to fail"):
        speak("Hello.", cache_dir=fakes.sandbox.clips, command=fakes.tts.program, ffmpeg=fakes.ffmpeg)
    assert list(fakes.sandbox.clips.iterdir()) == []


def test_a_tts_that_writes_nothing_is_an_error(fakes):
    with pytest.raises(RunError, match="wrote no audio"):
        speak("Hello.", cache_dir=fakes.sandbox.clips, command="true", ffmpeg=fakes.ffmpeg)


def test_a_missing_tts_is_reported(fakes):
    with pytest.raises(RunError, match="command not found"):
        speak("Hello.", cache_dir=fakes.sandbox.clips, command="/nonexistent/tts", ffmpeg=fakes.ffmpeg)


def test_tts_command_default_and_override(monkeypatch):
    monkeypatch.delenv("HOWTO_TTS", raising=False)
    assert tts_command() == "tts"
    monkeypatch.setenv("HOWTO_TTS", "")
    assert tts_command() == "tts"
    monkeypatch.setenv("HOWTO_TTS", "/opt/voice/speak")
    assert tts_command() == "/opt/voice/speak"


def test_wav_duration_rejects_a_file_that_is_not_wav(tmp_path):
    path = tmp_path / "not.wav"
    path.write_bytes(b"this is not audio")
    with pytest.raises(RunError, match="not a readable WAV"):
        wav_duration(path)
