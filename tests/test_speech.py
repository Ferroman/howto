"""The two speech commands that come with howto, each against a fake engine."""
import json
import stat
import sys
import textwrap
import wave
from pathlib import Path

import pytest

from howto import speech
from howto.narrate import speak, wav_duration
from howto.speech import SpeechError, audiocpp, kokoro

ENGINE = '''
    """Stands in for audiocpp_cli and for kokoro-tts: logs its arguments and writes a short WAV.

    audiocpp_cli is given the file after --out, and kokoro-tts as its second
    argument, after a text file whose content is logged as well.
    """
    import json, os, sys, wave

    args = sys.argv[1:]
    record = {"args": args}
    if "--out" in args:
        out = args[args.index("--out") + 1]
    else:
        out = args[1]
        record["text"] = open(args[0], encoding="utf-8").read()
        record["stdin"] = sys.stdin.read()
    with open(os.environ["FAKE_ENGINE_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\\n")
    if os.environ.get("FAKE_ENGINE_FAIL") == "portaudio":
        # What kokoro-tts prints on a system without the library that plays sound.
        sys.stderr.write("Traceback (most recent call last):\\n  File \\"sounddevice.py\\", line 73\\nOSError: PortAudio library not found\\n")
        sys.exit(1)
    if os.environ.get("FAKE_ENGINE_FAIL"):
        sys.stderr.write("ggml_vulkan: Found 1 Vulkan devices\\nload_backend: loaded\\nthe model is broken\\n")
        sys.exit(7)
    if os.environ.get("FAKE_ENGINE_SILENT"):
        sys.exit(0)
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(2 * 12000))
'''
PLAIN = "models/Supertonic-3-GGUF/supertonic-3-q8_0.gguf"
DESIGN = "models/Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf"
CLONE = "models/Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf"


def program(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{textwrap.dedent(ENGINE).lstrip()}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def option(argv, name):
    return argv[argv.index(name) + 1]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A log for the fake engine, and `calls()` to read it."""
    log = tmp_path / "engine.log"
    monkeypatch.setenv("FAKE_ENGINE_LOG", str(log))
    for name in ("FAKE_ENGINE_FAIL", "FAKE_ENGINE_SILENT"):
        monkeypatch.delenv(name, raising=False)
    return lambda: [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@pytest.fixture
def audio_dir(tmp_path, monkeypatch, engine):
    """A folder laid out like an audio.cpp release, with a fake audiocpp_cli and empty model files."""
    folder = tmp_path / "audio.cpp"
    program(folder / "audiocpp_cli")
    for model in (PLAIN, DESIGN, CLONE):
        (folder / model).parent.mkdir(parents=True)
        (folder / model).write_bytes(b"gguf")
    for name in list(__import__("os").environ):
        if name.startswith("AUDIOCPP_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("AUDIOCPP_DIR", str(folder))
    return folder


@pytest.fixture
def kokoro_dir(tmp_path, monkeypatch, engine):
    """Kokoro's two model files, and a fake kokoro-tts that KOKORO_TTS names."""
    folder = tmp_path / "kokoro"
    folder.mkdir()
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        (folder / name).write_bytes(b"model")
    monkeypatch.setenv("KOKORO_DIR", str(folder))
    monkeypatch.setenv("KOKORO_TTS", str(program(tmp_path / "bin" / "kokoro-tts")))
    return folder


# --- what howto sends ---------------------------------------------------------


def test_a_sentence_as_howto_sends_it():
    request, _ = speech.parse(speech.parser("demo", "x"), ["-l", "en", "-o", "/tmp/a.wav", "Open the menu."])
    assert (request.language, request.out, request.text) == ("en", Path("/tmp/a.wav"), "Open the menu.")
    assert (request.design, request.clone, request.clone_text) == (None, None, None)


def test_a_cloned_sentence_as_howto_sends_it():
    argv = ["-l", "en", "-o", "a.wav", "--clone", "v.wav", "--clone-text", "Its words.", "Open the menu."]
    request, _ = speech.parse(speech.parser("demo", "x"), argv)
    assert (request.clone, request.clone_text, request.text) == (Path("v.wav"), "Its words.", "Open the menu.")


def test_a_designed_voice_as_howto_sends_it():
    argv = ["-l", "en", "-o", "a.wav", "--design", "A calm man", "This is the voice."]
    request, _ = speech.parse(speech.parser("demo", "x"), argv)
    assert (request.design, request.text) == ("A calm man", "This is the voice.")


@pytest.mark.parametrize(
    "argv, message",
    [
        (["-o", "a.wav", "--design", "A calm man", "--clone", "v.wav", "Hi."], "give one of them"),
        (["-o", "a.wav", "--clone-text", "Its words.", "Hi."], "--clone-text needs --clone"),
        (["-o", "a.wav", "   "], "no text"),
        (["-o", "a.wav"], "TEXT"),
        (["Hi."], "-o"),
        (["-o", "a.wav", "--loud", "Hi."], "--loud"),
    ],
)
def test_a_wrong_call_is_a_usage_error(argv, message):
    with pytest.raises(SpeechError, match=message) as caught:
        speech.parse(speech.parser("demo", "x"), argv)
    assert caught.value.code == 2


# --- audio.cpp ----------------------------------------------------------------


def say(text="Open the menu.", **fields):
    return speech.Request(language=fields.pop("language", "en"), out=Path("out.wav"), text=text, **fields)


def test_audiocpp_speaks_a_sentence_in_its_plain_voice(audio_dir):
    argv = audiocpp.build(say(), {"AUDIOCPP_DIR": str(audio_dir)})
    assert argv[0] == str(audio_dir / "audiocpp_cli")
    assert (option(argv, "--task"), option(argv, "--family")) == ("tts", "supertonic")
    assert option(argv, "--model") == str(audio_dir / PLAIN)
    assert (option(argv, "--language"), option(argv, "--text"), option(argv, "--out")) == ("en", "Open the menu.", "out.wav")
    # The engine chooses the processor or a graphics card itself, and its own number of threads.
    assert option(argv, "--backend") == "best"
    assert not {"--device", "--threads", "--instruct", "--voice-ref", "--reference-text"} & set(argv)


def test_audiocpp_designs_a_voice_with_the_qwen_model(audio_dir):
    argv = audiocpp.build(say(design="A calm man"), {"AUDIOCPP_DIR": str(audio_dir)})
    assert (option(argv, "--task"), option(argv, "--family")) == ("vdes", "qwen3_tts")
    assert option(argv, "--model") == str(audio_dir / DESIGN)
    assert option(argv, "--instruct") == "A calm man"
    # Qwen takes the language as a word and refuses the code.
    assert option(argv, "--language") == "English"


def test_audiocpp_clones_a_clip_with_the_qwen_model(audio_dir, tmp_path):
    clip = tmp_path / "narrator.wav"
    clip.write_bytes(b"riff")
    argv = audiocpp.build(say(clone=clip, clone_text="Its words."), {"AUDIOCPP_DIR": str(audio_dir)})
    assert (option(argv, "--task"), option(argv, "--family")) == ("tts", "qwen3_tts")
    assert option(argv, "--model") == str(audio_dir / CLONE)
    assert (option(argv, "--voice-ref"), option(argv, "--reference-text")) == (str(clip), "Its words.")
    assert option(argv, "--language") == "English" and "--instruct" not in argv


def test_audiocpp_takes_the_machine_from_the_environment(audio_dir, tmp_path):
    other = tmp_path / "plain.gguf"
    other.write_bytes(b"gguf")
    env = {
        "AUDIOCPP_DIR": str(audio_dir),
        "AUDIOCPP_BACKEND": "cpu",
        "AUDIOCPP_THREADS": "16",
        "AUDIOCPP_DEVICE": "1",
        "AUDIOCPP_FAMILY": "kokoro_tts",
        "AUDIOCPP_MODEL": str(other),
    }
    argv = audiocpp.build(say(), env)
    assert (option(argv, "--backend"), option(argv, "--threads"), option(argv, "--device")) == ("cpu", "16", "1")
    assert (option(argv, "--family"), option(argv, "--model")) == ("kokoro_tts", str(other))


def test_audiocpp_qwen_models_can_be_other_files(audio_dir, tmp_path):
    clip = tmp_path / "narrator.wav"
    clip.write_bytes(b"riff")
    smaller = tmp_path / "base-q4.gguf"
    smaller.write_bytes(b"gguf")
    env = {"AUDIOCPP_DIR": str(audio_dir), "AUDIOCPP_CLONE_MODEL": str(smaller)}
    assert option(audiocpp.build(say(clone=clip, clone_text="Its words."), env), "--model") == str(smaller)


def test_audiocpp_a_qwen_voice_has_ten_languages(audio_dir):
    with pytest.raises(SpeechError, match="not `uk`") as caught:
        audiocpp.build(say(design="A calm man", language="uk"), {"AUDIOCPP_DIR": str(audio_dir)})
    assert caught.value.code == 2
    # The plain voice is given the code as it is: which languages it has depends on its model.
    assert option(audiocpp.build(say(language="uk"), {"AUDIOCPP_DIR": str(audio_dir)}), "--language") == "uk"


def test_audiocpp_without_its_folder_says_which_variable_names_it():
    with pytest.raises(SpeechError, match="AUDIOCPP_DIR") as caught:
        audiocpp.build(say(), {})
    assert caught.value.code == 1


def test_audiocpp_a_missing_program_is_named(audio_dir):
    (audio_dir / "audiocpp_cli").unlink()
    with pytest.raises(SpeechError, match=f"audiocpp_cli not found.*{audio_dir}"):
        audiocpp.build(say(), {"AUDIOCPP_DIR": str(audio_dir)})


def test_audiocpp_a_missing_model_is_named_with_where_to_get_it(audio_dir):
    (audio_dir / CLONE).unlink()
    clip = audio_dir / "narrator.wav"
    clip.write_bytes(b"riff")
    with pytest.raises(SpeechError, match=r"model not found: .*base-q8_0_v2\.gguf.*huggingface\.co"):
        audiocpp.build(say(clone=clip, clone_text="Its words."), {"AUDIOCPP_DIR": str(audio_dir)})
    # The plain voice does not need that model.
    assert audiocpp.build(say(), {"AUDIOCPP_DIR": str(audio_dir)})


def test_audiocpp_a_missing_clip_is_named(audio_dir, tmp_path):
    with pytest.raises(SpeechError, match="clip not found: .*gone.wav"):
        audiocpp.build(say(clone=tmp_path / "gone.wav", clone_text="x"), {"AUDIOCPP_DIR": str(audio_dir)})


def test_audiocpp_command_writes_the_clip(audio_dir, engine, tmp_path, capsys):
    out = tmp_path / "clip.wav"
    assert audiocpp.main(["-l", "en", "-o", str(out), "Open the menu."]) == 0
    assert wav_duration(out) == pytest.approx(0.5)
    (call,) = engine()
    assert option(call["args"], "--text") == "Open the menu."
    assert capsys.readouterr() == ("", "")


def test_audiocpp_command_passes_a_failure_on_without_the_noise(audio_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "1")
    assert audiocpp.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 7
    err = capsys.readouterr().err
    assert "the model is broken" in err
    # audio.cpp prints these two on every run, also on one that works.
    assert "ggml_vulkan" not in err and "load_backend" not in err


def test_audiocpp_command_that_writes_nothing_fails(audio_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_ENGINE_SILENT", "1")
    assert audiocpp.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 1
    assert "wrote no audio" in capsys.readouterr().err


def test_audiocpp_command_reports_a_usage_error_with_its_name(audio_dir, tmp_path, capsys):
    assert audiocpp.main(["-o", str(tmp_path / "clip.wav"), "--clone-text", "x", "Hi."]) == 2
    assert capsys.readouterr().err.startswith("howto-tts-audiocpp: ")


# --- Kokoro -------------------------------------------------------------------


def kokoro_env(folder, tmp_path):
    return {"KOKORO_DIR": str(folder), "KOKORO_TTS": str(tmp_path / "bin" / "kokoro-tts")}


def test_kokoro_speaks_a_sentence_from_a_text_file(kokoro_dir, tmp_path):
    argv = kokoro.build(say(), "af_heart", kokoro_env(kokoro_dir, tmp_path), tmp_path / "text.txt")
    assert argv[:3] == [str(tmp_path / "bin" / "kokoro-tts"), str(tmp_path / "text.txt"), "out.wav"]
    # kokoro-tts names American English en-us.
    assert (option(argv, "--lang"), option(argv, "--voice"), option(argv, "--format")) == ("en-us", "af_heart", "wav")
    assert option(argv, "--model") == str(kokoro_dir / "kokoro-v1.0.onnx")
    assert option(argv, "--voices") == str(kokoro_dir / "voices-v1.0.bin")


def test_kokoro_models_are_in_the_data_folder_of_howto_by_default(kokoro_dir, tmp_path):
    data = tmp_path / "data"
    (data / "kokoro").mkdir(parents=True)
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        (data / "kokoro" / name).write_bytes(b"model")
    env = {"HOWTO_DATA_DIR": str(data), "KOKORO_TTS": str(tmp_path / "bin" / "kokoro-tts")}
    assert option(kokoro.build(say(), "af_heart", env, tmp_path / "t.txt"), "--model") == str(data / "kokoro" / "kokoro-v1.0.onnx")


@pytest.mark.parametrize("fields", [{"design": "A calm man"}, {"clone": Path("v.wav"), "clone_text": "Its words."}])
def test_kokoro_has_preset_voices_only(kokoro_dir, tmp_path, fields):
    with pytest.raises(SpeechError, match=r"preset voices only.*--voice.*howto-tts-audiocpp") as caught:
        kokoro.build(say(**fields), "af_heart", kokoro_env(kokoro_dir, tmp_path), tmp_path / "t.txt")
    assert caught.value.code == 2


def test_kokoro_without_its_program_says_how_to_install_it(kokoro_dir, tmp_path):
    env = {"KOKORO_DIR": str(kokoro_dir), "PATH": str(tmp_path / "empty")}
    with pytest.raises(SpeechError, match="`kokoro-tts` is not installed.*uv tool install") as caught:
        kokoro.build(say(), "af_heart", env, tmp_path / "t.txt")
    assert caught.value.code == 1


def test_kokoro_without_a_model_file_says_how_to_download_it(kokoro_dir, tmp_path):
    (kokoro_dir / "voices-v1.0.bin").unlink()
    with pytest.raises(SpeechError, match=r"voices-v1\.0\.bin is missing.*curl .*voices-v1\.0\.bin"):
        kokoro.build(say(), "af_heart", kokoro_env(kokoro_dir, tmp_path), tmp_path / "t.txt")


def test_kokoro_command_writes_the_clip_and_leaves_no_text_file(kokoro_dir, engine, tmp_path, capsys):
    out = tmp_path / "clip.wav"
    assert kokoro.main(["--voice", "am_michael", "-l", "en", "-o", str(out), "Open the menu."]) == 0
    assert wav_duration(out) == pytest.approx(0.5)
    (call,) = engine()
    assert call["text"] == "Open the menu."
    assert option(call["args"], "--voice") == "am_michael"
    # kokoro-tts asks for a voice on its terminal when it is unsure. It must find nothing to read.
    assert call["stdin"] == ""
    assert not Path(call["args"][0]).exists()
    assert capsys.readouterr() == ("", "")


def test_kokoro_command_speaks_in_its_first_voice_when_none_is_named(kokoro_dir, engine, tmp_path):
    assert kokoro.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 0
    assert option(engine()[0]["args"], "--voice") == "af_heart"


def test_kokoro_command_passes_a_failure_on(kokoro_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "1")
    assert kokoro.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 7
    assert "the model is broken" in capsys.readouterr().err


def test_kokoro_command_says_which_library_a_bare_system_lacks(kokoro_dir, tmp_path, monkeypatch, capsys):
    # kokoro-tts loads a library that plays sound, although it only writes a file here.
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "portaudio")
    assert kokoro.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 1
    err = capsys.readouterr().err
    assert "PortAudio" in err and "apt install libportaudio2" in err
    assert "Traceback" not in err


def test_kokoro_command_that_writes_nothing_fails(kokoro_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_ENGINE_SILENT", "1")
    assert kokoro.main(["-o", str(tmp_path / "clip.wav"), "Open the menu."]) == 1
    assert "wrote no audio" in capsys.readouterr().err


# --- help ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "main, words",
    [
        (audiocpp.main, ["AUDIOCPP_DIR", "AUDIOCPP_BACKEND", "supertonic-3-q8_0.gguf", "--clone WAV"]),
        (kokoro.main, ["KOKORO_DIR", "uv tool install", "--voice NAME", "kokoro-v1.0.onnx"]),
    ],
)
def test_help_says_how_to_set_the_engine_up(main, words, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    for word in words:
        assert word in out
    # The lines of a path or of a command stay whole, so that they can be copied.
    assert "\n    " in out


# --- through howto ------------------------------------------------------------


def test_howto_narrates_through_a_speech_command_of_its_own(kokoro_dir, engine, fakes):
    # The voice is an option of the command, so it is part of a clip's cache name.
    command = f"{sys.executable} -m howto.speech.kokoro --voice am_michael"
    clip = speak("Open the menu.", cache_dir=fakes.sandbox.clips, command=command, ffmpeg=fakes.ffmpeg)
    assert clip.duration == pytest.approx(0.5)
    with wave.open(str(clip.path), "rb") as wav:
        assert wav.getframerate() == 48000
    assert [call["text"] for call in engine()] == ["Open the menu."]
    speak("Open the menu.", cache_dir=fakes.sandbox.clips, command=command.replace("am_michael", "af_heart"), ffmpeg=fakes.ffmpeg)
    assert [option(call["args"], "--voice") for call in engine()] == ["am_michael", "af_heart"]
