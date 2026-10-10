"""Reads and validates a storyboard: the YAML file that describes one video.

Every problem is a StoryboardError whose message names the step and the
field, because the reader of that message is usually a model that has to fix
the file without seeing this code.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

from .errors import StoryboardError

LOCATOR_FORMS = ("role", "label", "placeholder", "text", "testid", "css")
LOCATOR_EXTRAS = ("name", "exact", "nth", "within")
LOCATOR_ACTIONS = ("click", "hover", "scroll_to", "wait_for")
VALUE_ACTIONS = {"fill": "value", "select": "option"}
STRING_ACTIONS = ("goto", "press")
TOP_FIELDS = ("title", "url", "steps", "profile", "viewport", "setup", "cleanup", "pace", "zoom")
STEP_FIELDS = ("say", "do", "chapter", "note", "pause", "zoom")
# How far the picture may be enlarged. At 4 a 1920-pixel page shows 480 pixels.
MAX_ZOOM = 4.0
PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
VIEWPORT_RE = re.compile(r"^([1-9]\d{2,4})x([1-9]\d{2,4})$")
# A sentence ends at ., ! or ? followed by white space. "2.5" has no white
# space after its dot, so it stays whole.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class _TextLoader(yaml.SafeLoader):
    """Reads every value as the text that was written.

    YAML's own rules read 02134 as the octal number 1116, 12:30 as 750, Yes as
    true and 2026-10-10 as a date. A storyboard holds text that is typed into a
    form and names that are matched on a page, so each value must arrive as it
    stands in the file. Only an empty value and `null` keep their YAML meaning.
    """


_TextLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag == "tag:yaml.org,2002:null"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_yaml(text: str) -> object:
    """Parses YAML with every value kept as written. Raises yaml.YAMLError."""
    return yaml.load(text, Loader=_TextLoader)


@dataclass(frozen=True)
class Locator:
    role: str | None = None
    name: str | None = None
    label: str | None = None
    placeholder: str | None = None
    text: str | None = None
    testid: str | None = None
    css: str | None = None
    exact: bool = False
    nth: int | None = None
    within: "Locator | None" = None

    def describe(self) -> str:
        parts = []
        for key in ("role", "name", "label", "placeholder", "text", "testid", "css"):
            value = getattr(self, key)
            if value is not None:
                parts.append(f"{key}={value}" if key == "role" else f'{key}="{value}"')
        if self.exact:
            parts.append("exact")
        if self.nth is not None:
            parts.append(f"nth={self.nth}")
        if self.within is not None:
            parts.append(f"within({self.within.describe()})")
        return " ".join(parts)


@dataclass(frozen=True)
class Action:
    kind: str
    locator: Locator | None = None
    value: str | None = None

    def describe(self) -> str:
        if self.locator is None:
            return f"{self.kind} {self.value}"
        text = f"{self.kind} {self.locator.describe()}"
        if self.kind in VALUE_ACTIONS:
            text += f' {VALUE_ACTIONS[self.kind]}="{self.value}"'
        return text


@dataclass(frozen=True)
class Step:
    index: int
    say: tuple[str, ...] = ()
    do: tuple[Action, ...] = ()
    chapter: str | None = None
    note: str | None = None
    pause: float = 0.0
    # None: the storyboard's own `zoom` applies.
    zoom: float | None = None


@dataclass(frozen=True)
class Pace:
    lead: float = 0.5
    gap: float = 0.4
    sentence_gap: float = 0.15
    typing: float = 25.0
    chapter_hold: float = 2.0
    # Seconds the picture stays enlarged after the last action of a step.
    zoom_hold: float = 0.9


@dataclass(frozen=True)
class Storyboard:
    path: Path
    title: str
    url: str
    steps: tuple[Step, ...]
    profile: str | None = None
    viewport: tuple[int, int] = (1920, 1080)
    setup: tuple[Action, ...] = ()
    cleanup: tuple[Action, ...] = ()
    pace: Pace = Pace()
    # How much the picture is enlarged around the target of an action. 1 is not at all.
    zoom: float = 1.0

    @property
    def name(self) -> str:
        return self.path.stem


def split_sentences(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in SENTENCE_END.split(text.strip()) if part.strip())


def _text(value: object, where: str) -> str:
    """Non-empty text. A storyboard built in code may hold a number here; it is turned into text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise StoryboardError(f"{where}: must be non-empty text")
    return value


def _number(value: object) -> float | None:
    """A finite number, written as a number or as text. None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _whole(value: object) -> int | None:
    """A whole number, written as a number or as text. None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return value if isinstance(value, int) else None


def _flag(value: object) -> bool | None:
    """true or false, written as a YAML flag or as text. None for anything else."""
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value if isinstance(value, bool) else None


def parse_locator(data: object, where: str) -> Locator:
    if not isinstance(data, dict):
        raise StoryboardError(f"{where}: a locator must be a mapping, for example {{role: button, name: Save}}")
    unknown = [key for key in data if key not in LOCATOR_FORMS + LOCATOR_EXTRAS]
    if unknown:
        raise StoryboardError(f"{where}: unknown locator key `{unknown[0]}`")
    forms = [key for key in LOCATOR_FORMS if key in data]
    if len(forms) != 1:
        raise StoryboardError(f"{where}: a locator needs exactly one of " + ", ".join(LOCATOR_FORMS))
    if "name" in data and "role" not in data:
        raise StoryboardError(f"{where}: `name` needs `role`")
    values = {forms[0]: _text(data[forms[0]], f"{where}: `{forms[0]}`")}
    if "name" in data:
        values["name"] = _text(data["name"], f"{where}: `name`")
    exact = _flag(data.get("exact", False))
    if exact is None:
        raise StoryboardError(f"{where}: `exact` must be true or false")
    nth = None
    if data.get("nth") is not None:
        nth = _whole(data["nth"])
        if nth is None or nth < 0:
            raise StoryboardError(f"{where}: `nth` must be a whole number, 0 or more")
    within = data.get("within")
    return Locator(
        **values,
        exact=exact,
        nth=nth,
        within=parse_locator(within, f"{where}: `within`") if within is not None else None,
    )


def parse_action(data: object, where: str) -> Action:
    if not isinstance(data, dict) or len(data) != 1:
        raise StoryboardError(
            f"{where}: an action must be a mapping with one key, for example {{click: {{role: button, name: Save}}}}"
        )
    kind, argument = next(iter(data.items()))
    if kind in STRING_ACTIONS:
        return Action(kind=kind, value=_text(argument, f"{where}: `{kind}`"))
    if kind in LOCATOR_ACTIONS:
        return Action(kind=kind, locator=parse_locator(argument, f"{where}: `{kind}`"))
    if kind in VALUE_ACTIONS:
        key = VALUE_ACTIONS[kind]
        if not isinstance(argument, dict) or key not in argument:
            raise StoryboardError(f"{where}: `{kind}`: needs a locator and `{key}`")
        rest = {k: v for k, v in argument.items() if k != key}
        return Action(
            kind=kind,
            locator=parse_locator(rest, f"{where}: `{kind}`"),
            value=_text(argument[key], f"{where}: `{kind}`: `{key}`"),
        )
    raise StoryboardError(f"{where}: unknown action `{kind}`")


def _parse_actions(value: object, prefix: str, field: str) -> tuple[Action, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise StoryboardError(f"{prefix}`{field}` must be a list of actions")
    return tuple(parse_action(item, f"{prefix}`{field}[{n}]`") for n, item in enumerate(value, 1))


def _parse_say(value: object, where: str) -> tuple[str, ...]:
    if isinstance(value, list):
        if not value:
            raise StoryboardError(f"{where}: `say` must not be empty")
        return tuple(_text(item, f"{where}: `say[{n}]`").strip() for n, item in enumerate(value, 1))
    return split_sentences(_text(value, f"{where}: `say`"))


def _parse_zoom(value: object, prefix: str) -> float:
    number = _number(value)
    if number is None or not 1 <= number <= MAX_ZOOM:
        raise StoryboardError(f"{prefix}`zoom` must be a number from 1 to {MAX_ZOOM:g}")
    return number


def parse_step(data: object, index: int) -> Step:
    where = f"step {index}"
    if not isinstance(data, dict):
        raise StoryboardError(f"{where}: a step must be a mapping")
    unknown = [key for key in data if key not in STEP_FIELDS]
    if unknown:
        raise StoryboardError(f"{where}: unknown field `{unknown[0]}`")
    if not any(key in data for key in ("say", "do", "chapter")):
        raise StoryboardError(f"{where}: a step needs at least one of `say`, `do` and `chapter`")
    pause = _number(data.get("pause", 0))
    if pause is None or pause < 0:
        raise StoryboardError(f"{where}: `pause` must be a number, 0 or more")
    return Step(
        index=index,
        say=_parse_say(data["say"], where) if "say" in data else (),
        do=_parse_actions(data.get("do"), f"{where}: ", "do"),
        chapter=_text(data["chapter"], f"{where}: `chapter`") if "chapter" in data else None,
        note=_text(data["note"], f"{where}: `note`") if "note" in data else None,
        pause=pause,
        zoom=_parse_zoom(data["zoom"], f"{where}: ") if "zoom" in data else None,
    )


def _parse_viewport(value: object) -> tuple[int, int]:
    if value is None:
        return (1920, 1080)
    match = VIEWPORT_RE.match(value) if isinstance(value, str) else None
    if not match:
        raise StoryboardError("`viewport`: write it as WIDTHxHEIGHT, for example 1920x1080")
    width, height = int(match.group(1)), int(match.group(2))
    if width % 2 or height % 2:
        raise StoryboardError("`viewport`: width and height must be even numbers, because H.264 requires it")
    return (width, height)


def _parse_pace(value: object) -> Pace:
    if value is None:
        return Pace()
    if not isinstance(value, dict):
        raise StoryboardError("`pace` must be a mapping")
    names = [f.name for f in fields(Pace)]
    numbers: dict[str, float] = {}
    for key, written in value.items():
        if key not in names:
            raise StoryboardError(f"`pace`: unknown value `{key}`")
        number = _number(written)
        if number is None:
            raise StoryboardError(f"`pace`: `{key}` must be a number")
        if key == "typing" and number <= 0:
            raise StoryboardError("`pace`: `typing` must be more than 0")
        if number < 0:
            raise StoryboardError(f"`pace`: `{key}` must be 0 or more")
        numbers[key] = number
    return Pace(**numbers)


def parse(data: object, path: Path) -> Storyboard:
    if not isinstance(data, dict):
        raise StoryboardError("the storyboard must be a mapping with `title`, `url` and `steps`")
    unknown = [key for key in data if key not in TOP_FIELDS]
    if unknown:
        raise StoryboardError(f"unknown field `{unknown[0]}`")
    for key in ("title", "url", "steps"):
        if key not in data:
            raise StoryboardError(f"missing field `{key}`")
    steps = data["steps"]
    if not isinstance(steps, list) or not steps:
        raise StoryboardError("`steps` must be a list with at least one step")
    profile = data.get("profile")
    if profile is not None:
        profile = _text(profile, "`profile`")
        if not PROFILE_RE.match(profile):
            raise StoryboardError("`profile`: use letters, digits, `-` and `_` only")
    return Storyboard(
        path=path,
        title=_text(data["title"], "`title`"),
        url=_text(data["url"], "`url`"),
        steps=tuple(parse_step(step, n) for n, step in enumerate(steps, 1)),
        profile=profile,
        viewport=_parse_viewport(data.get("viewport")),
        setup=_parse_actions(data.get("setup"), "", "setup"),
        cleanup=_parse_actions(data.get("cleanup"), "", "cleanup"),
        pace=_parse_pace(data.get("pace")),
        zoom=_parse_zoom(data["zoom"], "") if "zoom" in data else 1.0,
    )


def load(path: Path) -> Storyboard:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StoryboardError(f"{path}: no such file") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise StoryboardError(f"{path}: cannot read: {exc}") from None
    try:
        data = read_yaml(text)
    except yaml.YAMLError as exc:
        raise StoryboardError(f"{path}: not valid YAML: {exc}") from None
    try:
        return parse(data, path)
    except StoryboardError as exc:
        raise StoryboardError(f"{path}: {exc}") from None
