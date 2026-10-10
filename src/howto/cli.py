"""The `howto` command: login, probe, narrate, render."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from . import assemble as assembling
from .errors import HowtoError, RunError, StoryboardError
from .narrate import narrate
from .probe import format_report
from .runner import RealClock, RunResult, run_probe, run_take
from .storyboard import PROFILE_RE, Storyboard, load, parse_locator
from .timeline import narration_only
from .tools import find_tool


def data_dir() -> Path:
    return Path(os.environ.get("HOWTO_DATA_DIR") or Path.home() / ".local/share/howto")


def cache_dir() -> Path:
    return Path(os.environ.get("HOWTO_CACHE_DIR") or Path.home() / ".cache/howto")


def profiles_dir() -> Path:
    return data_dir() / "profiles"


# Playwright is imported only when a browser is needed. `howto --help` and
# `howto narrate` then start without it, and the tests replace these two names.
def open_stage(storyboard: Storyboard, *, headless: bool):
    from .capture import open_stage as real

    return real(storyboard, profiles_dir=profiles_dir(), headless=headless)


def login(profile_dir: Path, url: str) -> None:
    from .capture import login as real

    real(profile_dir, url)


def _out_dir(args: argparse.Namespace, storyboard: Storyboard) -> Path:
    return Path(args.out) if args.out else storyboard.path.parent


def _explain_failure(storyboard: Storyboard, result: RunResult) -> str:
    """The message for a failed run. A failed setup with a profile usually means a signed-out session."""
    failed = result.failed
    label = "setup" if failed.index == 0 else f"step {failed.index}"
    if failed.index == 0 and storyboard.profile:
        print(
            f"howto: if the profile is signed out, run `howto login {storyboard.profile} {storyboard.url}`",
            file=sys.stderr,
        )
    return f"{label}: {failed.error}"


def cmd_login(args: argparse.Namespace) -> int:
    if not PROFILE_RE.match(args.profile):
        raise StoryboardError("profile: use letters, digits, `-` and `_` only")
    target = profiles_dir() / args.profile
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
            within = parse_locator(yaml.safe_load(args.within), "--within")
        except yaml.YAMLError as exc:
            raise StoryboardError(f"--within: not valid YAML: {exc}") from None
    with open_stage(storyboard, headless=not args.show) as stage:
        result = run_probe(storyboard, stage, until=args.until, within=within, max_chars=args.max_chars)
    sys.stdout.write(format_report(result))
    if result.failed:
        _explain_failure(storyboard, result)
        return 1
    return 0


def cmd_narrate(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    clips = narrate(storyboard, cache_dir=cache_dir() / "clips", ffmpeg=ffmpeg)
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


def cmd_render(args: argparse.Namespace) -> int:
    storyboard = load(Path(args.storyboard))
    ffmpeg = find_tool("ffmpeg", "HOWTO_FFMPEG")
    ffprobe = find_tool("ffprobe", "HOWTO_FFPROBE")
    # Narration first: a `tts` failure must stop the render before the browser starts.
    clips = narrate(storyboard, cache_dir=cache_dir() / "clips", ffmpeg=ffmpeg)
    work_root = cache_dir() / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{storyboard.name}-", dir=work_root))
    keep = args.keep_work
    try:
        video = work / "capture.webm"
        with open_stage(storyboard, headless=True) as stage:
            result = run_take(storyboard, stage, clips, RealClock(), video)
        for warning in result.warnings:
            print(f"howto: warning: {warning}", file=sys.stderr)
        if result.failed:
            raise RunError(_explain_failure(storyboard, result))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="howto", description="Narrated how-to videos of a web app, from a storyboard."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    p_login = commands.add_parser("login", help="open a browser window to sign in to a profile")
    p_login.add_argument("profile")
    p_login.add_argument("url")
    p_login.set_defaults(func=cmd_login)

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
    return parser


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
