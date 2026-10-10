import pytest

from howto import voices
from howto.errors import RunError
from howto.narrate import wav_duration

CALM = "A calm man in his thirties"
WORDS = "This is how the narrator sounds."


def make(fakes, name="narrator", description=CALM, **options):
    options.setdefault("text", WORDS)
    return voices.design(name, description, directory=fakes.sandbox.voices, command=fakes.tts.program, **options)


def test_a_designed_voice_is_a_clip_and_the_words_in_it(fakes):
    voice = make(fakes)
    assert voice.clip == fakes.sandbox.voices / "narrator.wav"
    assert wav_duration(voice.clip) == pytest.approx(0.06 * len(WORDS), abs=0.01)
    assert (voice.name, voice.text, voice.description) == ("narrator", WORDS, CALM)
    assert sorted(p.name for p in fakes.sandbox.voices.iterdir()) == ["narrator.wav", "narrator.yaml"]


def test_the_speech_command_is_asked_to_design_it(fakes):
    make(fakes)
    (call,) = fakes.tts.calls()
    assert call[:2] == ["-l", "en"] and call[-1] == WORDS
    assert call[call.index("--design") + 1] == CALM
    assert "--clone" not in call


def test_the_sample_sentence_is_spoken_when_no_words_are_given(fakes):
    voice = voices.design("narrator", CALM, directory=fakes.sandbox.voices, command=fakes.tts.program)
    assert voice.text == voices.SAMPLE
    assert fakes.tts.spoken() == [voices.SAMPLE]


def test_a_voice_is_read_back_as_it_was_made(fakes):
    made = make(fakes)
    assert voices.load(fakes.sandbox.voices, "narrator") == made


def test_a_description_is_kept_as_it_was_written(fakes):
    # YAML would read these two as a number and as true.
    make(fakes, description="007", text="Yes")
    voice = voices.load(fakes.sandbox.voices, "narrator")
    assert (voice.description, voice.text) == ("007", "Yes")


def test_a_voice_that_is_not_made_says_how_to_make_it(fakes):
    with pytest.raises(RunError, match='voice `narrator` is not made yet.*howto voice narrator "'):
        voices.load(fakes.sandbox.voices, "narrator")


def test_an_existing_voice_is_not_replaced_unasked(fakes):
    first = make(fakes)
    before = first.clip.read_bytes()
    with pytest.raises(RunError, match="`narrator` exists.*--replace"):
        make(fakes, description="A bright young woman")
    assert first.clip.read_bytes() == before
    assert len(fakes.tts.calls()) == 1, "the speech command ran for a voice that was refused"


def test_replace_makes_the_voice_anew(fakes):
    # The key is read from the clip, so it is taken before the clip is replaced.
    first = make(fakes).key
    second = make(fakes, description="A bright young woman", replace=True)
    assert second.description == "A bright young woman"
    assert second.key != first
    assert voices.load(fakes.sandbox.voices, "narrator") == second


def test_the_key_follows_the_clip_and_its_words(fakes):
    voice = make(fakes)
    key = voice.key
    assert voices.load(fakes.sandbox.voices, "narrator").key == key
    # The same clip with other words is cloned differently, so it is another voice.
    note = fakes.sandbox.voices / "narrator.yaml"
    note.write_text(note.read_text().replace("narrator sounds", "narrator speaks"))
    assert voices.load(fakes.sandbox.voices, "narrator").key != key


def test_a_failed_design_leaves_nothing(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_FAIL", "1")
    with pytest.raises(RunError, match="told to fail"):
        make(fakes)
    assert list(fakes.sandbox.voices.iterdir()) == []


def test_a_failed_replacement_keeps_the_earlier_voice(fakes, monkeypatch):
    first = make(fakes)
    monkeypatch.setenv("FAKE_TTS_FAIL", "1")
    with pytest.raises(RunError):
        make(fakes, description="A bright young woman", replace=True)
    assert voices.load(fakes.sandbox.voices, "narrator") == first
    assert sorted(p.name for p in fakes.sandbox.voices.iterdir()) == ["narrator.wav", "narrator.yaml"]


def test_a_speech_command_that_writes_nothing_is_an_error(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_SILENT", "1")
    with pytest.raises(RunError, match="wrote no audio"):
        make(fakes)
    assert list(fakes.sandbox.voices.iterdir()) == []


def test_a_note_without_its_words_is_named(fakes):
    make(fakes)
    note = fakes.sandbox.voices / "narrator.yaml"
    note.write_text("description: A calm man\n")
    with pytest.raises(RunError, match="narrator.yaml.*`text`"):
        voices.load(fakes.sandbox.voices, "narrator")


def test_a_clip_that_is_not_audio_is_named(fakes):
    make(fakes)
    (fakes.sandbox.voices / "narrator.wav").write_bytes(b"not audio")
    with pytest.raises(RunError, match="narrator.wav"):
        voices.load(fakes.sandbox.voices, "narrator")


def test_the_voices_are_listed_by_name(fakes):
    assert voices.listing(fakes.sandbox.voices) == []
    make(fakes, name="zoe", description="A bright young woman")
    make(fakes, name="adam")
    # A clip without its note is not a voice: its words are not known.
    (fakes.sandbox.voices / "stray.wav").write_bytes(b"x")
    assert [(voice.name, voice.description) for voice in voices.listing(fakes.sandbox.voices)] == [
        ("adam", CALM),
        ("zoe", "A bright young woman"),
    ]


def test_a_clip_brought_from_elsewhere_needs_no_description(fakes):
    # A recording of a real speaker, put there by hand with the words in it.
    made = make(fakes)
    (fakes.sandbox.voices / "narrator.yaml").write_text(f"text: {WORDS}\n")
    voice = voices.load(fakes.sandbox.voices, "narrator")
    assert (voice.text, voice.description, voice.clip) == (WORDS, "", made.clip)
