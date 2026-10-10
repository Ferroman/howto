import wave
from pathlib import Path

import pytest

from howto.errors import RunError
from howto.narrate import clip_key, narrate, speak, tts_command, wav_duration
from howto.storyboard import parse
from howto.voices import design


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


def test_a_missing_speech_command_says_how_to_get_one(fakes):
    with pytest.raises(RunError, match=r"`/nonexistent/tts`.*HOWTO_TTS.*howto-tts-kokoro.*README"):
        speak("Hello.", cache_dir=fakes.sandbox.clips, command="/nonexistent/tts", ffmpeg=fakes.ffmpeg)
    assert not fakes.sandbox.clips.exists() or list(fakes.sandbox.clips.iterdir()) == []


def test_a_speech_command_that_cannot_be_read_is_reported(fakes):
    # An opening quote with no end: the shell rules that split the command refuse it.
    with pytest.raises(RunError, match="HOWTO_TTS.*quotation"):
        speak("Hello.", cache_dir=fakes.sandbox.clips, command='tts --voice "amy', ffmpeg=fakes.ffmpeg)


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


def voice(fakes, description="A calm man"):
    return design("narrator", description, directory=fakes.sandbox.voices, command=fakes.tts.program, text="Hello there.", replace=True)


def test_a_voice_is_cloned_for_each_sentence(fakes, tmp_path):
    narrator = voice(fakes)
    sb = board(tmp_path, [{"say": "Open the menu. Pick Settings."}])
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg, voice=narrator)
    spoken = fakes.tts.calls()[1:]  # the first call made the voice
    assert [call[-1] for call in spoken] == ["Open the menu.", "Pick Settings."]
    for call in spoken:
        assert call[call.index("--clone") + 1] == str(narrator.clip)
        assert call[call.index("--clone-text") + 1] == "Hello there."
        assert "--design" not in call, "a voice designed again for a sentence is another speaker"


def test_narration_without_a_voice_asks_for_none(fakes, tmp_path):
    narrate(board(tmp_path, [{"say": "Open the menu."}]), cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    (call,) = fakes.tts.calls()
    assert "--clone" not in call and "--clone-text" not in call and "--design" not in call


def test_another_voice_speaks_every_sentence_again(fakes, tmp_path):
    sb = board(tmp_path, [{"say": "Open the menu."}])
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg, voice=voice(fakes))
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg, voice=voice(fakes, "A bright young woman"))
    assert fakes.tts.spoken().count("Open the menu.") == 3


def test_going_back_to_a_voice_speaks_nothing_again(fakes, tmp_path):
    sb = board(tmp_path, [{"say": "Open the menu."}])
    narrator = voice(fakes)
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg, voice=narrator)
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg, voice=narrator)
    narrate(sb, cache_dir=fakes.sandbox.clips, ffmpeg=fakes.ffmpeg)
    assert fakes.tts.spoken().count("Open the menu.") == 2


def test_the_key_of_a_clip_without_a_voice_is_what_it_was():
    # Clips spoken before voices existed stay valid.
    assert clip_key("tts", "en", "Hello.") == "a477af180cb61b31ab201e2ff3d19332d4f69bfe50fee180d98f944915137f65"


def test_the_key_covers_the_voice():
    assert len({clip_key("tts", "en", "Hello."), clip_key("tts", "en", "Hello.", "a"), clip_key("tts", "en", "Hello.", "b")}) == 3
