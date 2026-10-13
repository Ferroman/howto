"""The `howto` command: login, probe, narrate, render, animate, voice."""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from . import assemble as assembling
from . import voices
from .animation import FORMATS, animate
from .errors import HowtoError, RunError, StoryboardError
from .narrate import narrate, tts_command
from .probe import format_report
from .runner import Interrupt, RealClock, RunResult, run_probe, run_take
from .storyboard import PROFILE_RE, Storyboard, load, parse_locator, read_yaml
from .timeline import narration_only
from .tools import docker_command, find_tool


def data_dir() -> Path:
    return Path(os.environ.get("HOWTO_DATA_DIR") or Path.home() / ".local/share/howto")


def cache_dir() -> Path:
    return Path(os.environ.get("HOWTO_CACHE_DIR") or Path.home() / ".cache/howto")


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def voices_dir() -> Path:
    return data_dir() / "voices"


def _voice(storyboard: Storyboard) -> voices.Voice | None:
    """The voice that the storyboard names. One that is not made yet is an error, before anything is spoken."""
    return voices.load(voices_dir(), storyboard.voice) if storyboard.voice else None


# Playwright and Docker are reached only when a stage is needed. `howto --help`
# and `howto narrate` then start without either, and the tests replace these
# two names.
def open_stage(storyboard: Storyboard, *, headless: bool, interrupt: Interrupt | None = None):
    """The stage of a storyboard: a container for one with `app`, the browser for one with `url`."""
    if storyboard.desktop:
        if not headless:
            raise RunError("`--show` of a desktop app is not built yet")
        from .desktop.stage import open_stage as desktop

        return desktop(storyboard, interrupt=interrupt)
    from .capture import open_stage as browser

    return browser(storyboard, profiles_dir=profiles_dir(), headless=headless, interrupt=interrupt)


def login(profile_dir: Path, url: str) -> None:
    from .capture import login as real

    real(profile_dir, url)


@contextlib.contextmanager
def _browser(storyboard: Storyboard, *, headless: bool):
    """The browser of a probe or a take, and the Interrupt that holds Ctrl+C until a safe point."""
    interrupt = Interrupt()
    try:
        with interrupt.listening(), open_stage(storyboard, headless=headless, interrupt=interrupt) as stage:
            yield stage, interrupt
    except RunError:
        # A termination signal sent to the whole process group also reaches
        # Playwright, which closes the browser on it. What fails after that is
        # a consequence: the run was stopped, and the exit says so.
        if interrupt.stopped:
            raise KeyboardInterrupt from None
        raise


def _out_dir(args: argparse.Namespace, storyboard: Storyboard) -> Path:
    return Path(args.out) if args.out else storyboard.path.parent


def _explain_failure(storyboard: Storyboard, result: RunResult) -> str:
    """The message for a failed run. A failed setup with a profile usually means a signed-out session."""
    failed = result.failed
    label = "setup" if failed.index == 0 else f"step {failed.index}"
    if failed.index == 0 and storyboard.profile:
        print(
            f"howto: if the profile is signed out, run `howto login {storyboard.profile} {storyboard.origin}`",
            file=sys.stderr,
        )
    return f"{label}: {failed.error}"


def _close_to_others(profile_dir: Path) -> None:
    """A profile holds a signed-in session, so its folder is made for its owner alone, before the browser writes to it."""
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_dir.chmod(0o700)
    except OSError as exc:
        raise RunError(f"cannot keep the profile {profile_dir} to yourself: {exc.strerror or exc}") from None


def cmd_login(args: argparse.Namespace) -> int:
    if not PROFILE_RE.match(args.profile):
        raise StoryboardError("profile: use letters, digits, `-` and `_` only")
    target = profiles_dir() / args.profile
    _close_to_others(target)
    print(f"Sign in, then close the browser window. Profile: {target}")
    login(target, args.url)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    if args.until is not None and args.until < 1:
        raise StoryboardError("--until must be 1 or more")
    if args.max_chars < 1:
        raise StoryboardError("--max-chars must be 1 or more")
    within = None
    if args.within:
        try:
            within = parse_locator(read_yaml(args.within), "--within")
        except yaml.YAMLError as exc:
            raise StoryboardError(f"--within: not valid YAML: {exc}") from None
    with _browser(storyboard, headless=not args.show) as (stage, _):
        result = run_probe(storyboard, stage, until=args.until, within=within, max_chars=args.max_chars)
    sys.stdout.write(format_report(result))
    if result.failed:
        _explain_failure(storyboard, result)
        return 1
    return 0


def cmd_narrate(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    clips = narrate(storyboard, cache_dir=cache_dir() / "clips", ffmpeg=ffmpeg, voice=_voice(storyboard))
    if not clips:
        raise StoryboardError(f"{storyboard.path}: no step has `say`")
    steps, length = narration_only(clips, storyboard.pace.sentence_gap, storyboard.pace.gap)
    out_dir = _out_dir(args, storyboard)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{storyboard.name}.narration.wav"
    part = out_dir / f".{storyboard.name}.narration.wav.part"
    try:
        assembling.narration_track(steps, length, part)
        os.replace(part, out)
    finally:
        part.unlink(missing_ok=True)
    print(out)
    return 0


def _work_dir(storyboard: Storyboard) -> Path:
    """A new folder for the intermediate files of one take."""
    work_root = cache_dir() / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{storyboard.name}-", dir=work_root))


def _record(storyboard: Storyboard, clips, video: Path, *, animated: bool = False) -> RunResult:
    """One take in a headless browser. A warning of cleanup goes to stderr, and a failed step is a RunError."""
    with _browser(storyboard, headless=True) as (stage, interrupt):
        result = run_take(storyboard, stage, clips, RealClock(interrupt), video, animated=animated)
    for warning in result.warnings:
        print(f"howto: warning: {warning}", file=sys.stderr)
    if result.failed:
        raise RunError(_explain_failure(storyboard, result))
    return result


def cmd_render(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    ffprobe = find_tool("ffprobe", "HOWTO_FFPROBE")
    # Narration first: a `tts` failure must stop the render before the browser starts.
    clips = narrate(storyboard, cache_dir=cache_dir() / "clips", ffmpeg=ffmpeg, voice=_voice(storyboard))
    work = _work_dir(storyboard)
    keep = args.keep_work
    try:
        video = work / "capture.webm"
        result = _record(storyboard, clips, video)
        try:
            outputs = assembling.assemble(
                video=video,
                steps=result.timeline,
                title=storyboard.title,
                name=storyboard.name,
                out_dir=_out_dir(args, storyboard),
                work=work,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
        except RunError:
            keep = True
            print(f"howto: work directory kept: {work}", file=sys.stderr)
            raise
        for path in outputs.values():
            print(path)
        return 0
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _file_size(path: Path) -> str:
    size = path.stat().st_size
    return f"{size / 1_000_000:.1f} MB" if size >= 1_000_000 else f"{max(1, round(size / 1000))} KB"


def cmd_animate(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    if args.width < 1:
        raise StoryboardError("--width must be 1 or more")
    formats = FORMATS if args.format == "both" else (args.format,)
    ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    img2webp = None
    if "webp" in formats:
        # Before the browser starts: a take that cannot become a picture is a take for nothing.
        try:
            img2webp = find_tool("img2webp", "HOWTO_IMG2WEBP")
        except RunError as exc:
            raise RunError(f"{exc}. It comes with the `webp` package. `--format gif` needs only ffmpeg.") from None
    work = _work_dir(storyboard)
    keep = args.keep_work
    try:
        video = work / "capture.webm"
        # Nothing is spoken, so there are no clips and no `tts`.
        result = _record(storyboard, {}, video, animated=True)
        try:
            picture = animate(
                video=video,
                length=result.timeline[-1].end,
                crop=result.crop,
                viewport=storyboard.viewport,
                width=args.width,
                formats=formats,
                name=storyboard.name,
                out_dir=_out_dir(args, storyboard),
                work=work,
                ffmpeg=ffmpeg,
                img2webp=img2webp,
            )
        except RunError:
            keep = True
            print(f"howto: work directory kept: {work}", file=sys.stderr)
            raise
        # The size in bytes is what decides whether a picture fits where it is going.
        for path in picture.files.values():
            print(f"{path}  {picture.width}x{picture.height}  {picture.seconds:.1f} s  {_file_size(path)}")
        return 0
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def cmd_voice(args: argparse.Namespace) -> int:
    directory = voices_dir()
    designing = args.name is not None and args.description is not None
    if not designing and (args.text is not None or args.replace):
        raise StoryboardError("`--text` and `--replace` go with a name and a description")
    if args.name is None:
        found = voices.listing(directory)
        for voice in found:
            print(f"{voice.name}  {voice.description or '(a clip that was not designed)'}")
        if not found:
            print('howto: no voice is made yet. Make one with: howto voice NAME "a description of the voice"', file=sys.stderr)
        return 0
    if not PROFILE_RE.match(args.name):
        raise StoryboardError("voice: use letters, digits, `-` and `_` only")
    if not designing:
        voice = voices.load(directory, args.name)
        print(voice.clip)
        print(f"description: {voice.description}")
        print(f"text: {voice.text}")
        return 0
    if not args.description.strip():
        raise StoryboardError("voice: the description is empty")
    if args.text is not None and not args.text.strip():
        raise StoryboardError("--text is empty")
    voice = voices.design(
        args.name,
        args.description,
        directory=directory,
        command=tts_command(),
        text=args.text or voices.SAMPLE,
        replace=args.replace,
    )
    print(voice.clip)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="howto", description="Narrated how-to videos and animated pictures of a web app, from a storyboard."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    p_login = commands.add_parser("login", help="open a browser window to sign in to a profile")
    p_login.add_argument("profile")
    p_login.add_argument("url")
    p_login.set_defaults(func=cmd_login)
    p_image = commands.add_parser("image", help="build the base image that the app of a desktop storyboard runs in")
    p_image.set_defaults(func=cmd_image)

    p_probe = commands.add_parser("probe", help="run the steps without recording and describe the page")
    p_probe.add_argument("storyboard")
    p_probe.add_argument("--until", type=int, metavar="N", help="stop after step N")
    p_probe.add_argument("--within", metavar="LOCATOR", help="limit the outline to one element, for example '{role: dialog}'")
    p_probe.add_argument("--max-chars", type=int, default=20_000, metavar="N", help="length limit of the outline (default 20000)")
    p_probe.add_argument("--show", action="store_true", help="use a visible browser window")
    p_probe.set_defaults(func=cmd_probe)

    p_narrate = commands.add_parser("narrate", help="speak the narration only")
    p_narrate.add_argument("storyboard")
    p_narrate.add_argument("--out", metavar="DIR", help="folder for the result (default: next to the storyboard)")
    p_narrate.set_defaults(func=cmd_narrate)

    p_render = commands.add_parser("render", help="narrate, capture and assemble the video")
    p_render.add_argument("storyboard")
    p_render.add_argument("--out", metavar="DIR", help="folder for the results (default: next to the storyboard)")
    p_render.add_argument("--keep-work", action="store_true", help="keep the intermediate files")
    p_render.set_defaults(func=cmd_render)

    p_animate = commands.add_parser("animate", help="capture the steps without sound as a picture that loops")
    p_animate.add_argument("storyboard")
    p_animate.add_argument("--out", metavar="DIR", help="folder for the results (default: next to the storyboard)")
    p_animate.add_argument("--width", type=int, default=960, metavar="N", help="scale a wider picture down to N pixels (default 960)")
    p_animate.add_argument("--format", choices=("gif", "webp", "both"), default="both", help="which files to write (default both)")
    p_animate.add_argument("--keep-work", action="store_true", help="keep the intermediate files")
    p_animate.set_defaults(func=cmd_animate)

    p_voice = commands.add_parser(
        "voice", help="make a voice for the narration from a description, or list the voices",
        description="With a name and a description: make that voice. With a name: show it. With nothing: list the voices.",
    )
    p_voice.add_argument("name", nargs="?")
    p_voice.add_argument("description", nargs="?", help="what the voice is like, in plain words")
    p_voice.add_argument("--text", metavar="WORDS", help="what the voice says in its clip (default: two sentences of a video)")
    p_voice.add_argument("--replace", action="store_true", help="make an existing voice anew")
    p_voice.set_defaults(func=cmd_voice)
    return parser


def cmd_image(args: argparse.Namespace) -> int:
    from .desktop import images

    for tag in images.build(docker_command()):
        print(tag)
    return 0

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HowtoError as exc:
        print(f"howto: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("howto: interrupted", file=sys.stderr)
        return 130
