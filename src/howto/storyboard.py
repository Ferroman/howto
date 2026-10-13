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

LOCATOR_FORMS = ("role", "label", "placeholder", "text", "testid", "css", "at")
LOCATOR_EXTRAS = ("name", "exact", "nth", "within", "size")
# The forms that only a web page has, and the one that only a desktop has.
WEB_FORMS = ("placeholder", "testid", "css")
DESKTOP_FORMS = ("at",)
LOCATOR_ACTIONS = ("click", "hover", "scroll_to", "wait_for")
VALUE_ACTIONS = {"fill": "value", "select": "option"}
STRING_ACTIONS = ("goto", "press", "type", "run")
# The actions that only one kind of storyboard has, each with the reason.
WEB_ACTIONS = {"goto": "an app has no addresses"}
DESKTOP_ACTIONS = {"run": "it runs a command in the container of the app"}
# Marks: drawn on the picture around an element, or beside it. They touch nothing on the page.
MARK_ACTIONS = ("box", "circle", "underline", "spotlight", "arrow")
# The marks that can show a few words. `text` already names an element, so the key is `note`.
NOTED_MARKS = ("arrow",)
TOP_FIELDS = ("title", "url", "app", "steps", "profile", "viewport", "setup", "cleanup", "pace", "zoom", "crop", "voice")
STEP_FIELDS = ("say", "do", "chapter", "note", "pause", "zoom")
# How far the picture may be enlarged. At 4 a 1920-pixel page shows 480 pixels.
MAX_ZOOM = 4.0
PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# The name of a Docker image. It goes on a command line, so it must not look like an option.
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:-]*$")
# A place or a size on the picture of a desktop: 960x540.
PLACE_RE = re.compile(r"^(\d{1,5})x(\d{1,5})$")
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
    # A place on the picture of a desktop, in its pixels: a point, or with `size` an area whose top left corner it is.
    at: tuple[int, int] | None = None
    size: tuple[int, int] | None = None

    @property
    def area(self) -> bool:
        """Whether the locator gives something with a size. A point alone does not."""
        return self.at is None or self.size is not None

    def describe(self) -> str:
        parts = []
        for key in ("role", "name", "label", "placeholder", "text", "testid", "css"):
            value = getattr(self, key)
            if value is not None:
                parts.append(f"{key}={value}" if key == "role" else f'{key}="{value}"')
        for key in ("at", "size"):
            value = getattr(self, key)
            if value is not None:
                parts.append(f"{key}={value[0]}x{value[1]}")
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
        elif self.kind in MARK_ACTIONS and self.value is not None:
            text += f' note="{self.value}"'
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
    # Seconds a finished mark is shown before the next action that is not a mark.
    mark_hold: float = 0.6


@dataclass(frozen=True)
class App:
    """The desktop app that a storyboard films: the image it is in, and the line of shell that starts it."""

    image: str
    run: str


@dataclass(frozen=True)
class Storyboard:
    path: Path
    title: str
    # The start page of a web storyboard. None for a desktop storyboard, which has `app`.
    url: str | None
    steps: tuple[Step, ...]
    profile: str | None = None
    viewport: tuple[int, int] = (1920, 1080)
    setup: tuple[Action, ...] = ()
    cleanup: tuple[Action, ...] = ()
    pace: Pace = Pace()
    # How much the picture is enlarged around the target of an action. 1 is not at all.
    zoom: float = 1.0
    # The part of the page that an animated picture is cut to. None is the whole window.
    crop: Locator | None = None
    # The name of the voice that speaks the narration. None is the speech command's own voice.
    voice: str | None = None
    app: App | None = None

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def desktop(self) -> bool:
        return self.app is not None

    @property
    def zooms(self) -> bool:
        """Whether any step enlarges the picture."""
        return self.zoom > 1 or any((step.zoom or 1) > 1 for step in self.steps)

    @property
    def origin(self) -> str:
        """What `howto login` is given after the profile: the address of a web page, or the storyboard of a desktop app."""
        return self.url if self.app is None else str(self.path)


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


def _place(value: object, where: str, example: str) -> tuple[int, int]:
    match = PLACE_RE.match(value.strip()) if isinstance(value, str) else None
    if not match:
        raise StoryboardError(f"{where}: write it as XxY, for example {example}")
    return int(match.group(1)), int(match.group(2))


def _parse_place(data: dict, where: str) -> Locator:
    """A point of the picture, or with `size` an area. It names no element, so nothing narrows it."""
    for key in data:
        if key not in ("at", "size"):
            raise StoryboardError(f"{where}: `{key}` does not go with `at`")
    at = _place(data["at"], f"{where}: `at`", "960x540")
    size = None
    if "size" in data:
        size = _place(data["size"], f"{where}: `size`", "120x40")
        if 0 in size:
            raise StoryboardError(f"{where}: `size`: width and height must be more than 0")
    return Locator(at=at, size=size)


def parse_locator(data: object, where: str) -> Locator:
    if not isinstance(data, dict):
        raise StoryboardError(f"{where}: a locator must be a mapping, for example {{role: button, name: Save}}")
    unknown = [key for key in data if key not in LOCATOR_FORMS + LOCATOR_EXTRAS]
    if unknown:
        raise StoryboardError(f"{where}: unknown locator key `{unknown[0]}`")
    forms = [key for key in LOCATOR_FORMS if key in data]
    if len(forms) != 1:
        raise StoryboardError(f"{where}: a locator needs exactly one of " + ", ".join(LOCATOR_FORMS))
    if forms[0] == "at":
        return _parse_place(data, where)
    if "size" in data:
        raise StoryboardError(f"{where}: `size` needs `at`")
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


def _parse_app(value: object) -> App:
    if not isinstance(value, dict):
        raise StoryboardError("`app` must be a mapping with `image` and `run`")
    unknown = [key for key in value if key not in ("image", "run")]
    if unknown:
        raise StoryboardError(f"`app`: unknown field `{unknown[0]}`")
    for key in ("image", "run"):
        if key not in value:
            raise StoryboardError(f"`app`: missing field `{key}`")
    image = _text(value["image"], "`app`: `image`")
    if not IMAGE_RE.match(image):
        raise StoryboardError("`app`: `image`: use the name of a Docker image, in small letters, for example howto-inkscape")
    return App(image=image, run=_text(value["run"], "`app`: `run`"))


def check_locator(locator: Locator, where: str, *, desktop: bool) -> None:
    """Refuses a locator form that this kind of storyboard does not have."""
    refused = WEB_FORMS if desktop else DESKTOP_FORMS
    for form in refused:
        if getattr(locator, form) is not None:
            allowed = ", ".join(name for name in LOCATOR_FORMS if name not in refused)
            if desktop:
                raise StoryboardError(f"{where}: `{form}` is for a web page. A desktop storyboard can use {allowed}")
            raise StoryboardError(f"{where}: `{form}` is for a desktop app. A web storyboard can use {allowed}")
    if locator.within is not None:
        if desktop and locator.within.at is not None:
            raise StoryboardError(f"{where}: `within` takes a locator of the tree: role, label or text")
        check_locator(locator.within, f"{where}: `within`", desktop=desktop)


def _check_place(locator: Locator, where: str, viewport: tuple[int, int]) -> None:
    if locator.at is None:
        return
    width, height = viewport
    (x, y), (wide, tall) = locator.at, locator.size or (0, 0)
    if x >= width or y >= height:
        raise StoryboardError(f"{where}: `at` is outside the picture of {width}x{height}")
    if x + wide > width or y + tall > height:
        raise StoryboardError(f"{where}: `at` and `size` reach outside the picture of {width}x{height}")


def _check_kind(storyboard: Storyboard) -> None:
    """Refuses what only the other kind of storyboard has, and a place that the picture does not have."""
    desktop = storyboard.app is not None
    listed = [(f"`setup[{n}]`", action) for n, action in enumerate(storyboard.setup, 1)]
    listed += [
        (f"step {step.index}: `do[{n}]`", action) for step in storyboard.steps for n, action in enumerate(step.do, 1)
    ]
    listed += [(f"`cleanup[{n}]`", action) for n, action in enumerate(storyboard.cleanup, 1)]
    refused = WEB_ACTIONS if desktop else DESKTOP_ACTIONS
    for where, action in listed:
        if action.kind in refused:
            kind = "a web page" if desktop else "a desktop app"
            raise StoryboardError(f"{where}: `{action.kind}` is for {kind}: {refused[action.kind]}")
        if action.locator is None:
            continue
        check_locator(action.locator, f"{where}: `{action.kind}`", desktop=desktop)
        _check_place(action.locator, f"{where}: `{action.kind}`", storyboard.viewport)
        if action.kind in MARK_ACTIONS and not action.locator.area:
            raise StoryboardError(
                f"{where}: `{action.kind}` needs an area: add `size`, for example {{at: 900x500, size: 120x40}}"
            )
    if storyboard.crop is not None:
        check_locator(storyboard.crop, "`crop`", desktop=desktop)
        _check_place(storyboard.crop, "`crop`", storyboard.viewport)
        if not storyboard.crop.area:
            raise StoryboardError("`crop` needs an area: add `size`, for example {at: 900x500, size: 120x40}")


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
    if kind in MARK_ACTIONS:
        note = None
        if isinstance(argument, dict) and "note" in argument:
            if kind not in NOTED_MARKS:
                raise StoryboardError(f"{where}: `{kind}`: only `arrow` takes a `note`")
            note = _text(argument["note"], f"{where}: `{kind}`: `note`")
            argument = {k: v for k, v in argument.items() if k != "note"}
        return Action(kind=kind, locator=parse_locator(argument, f"{where}: `{kind}`"), value=note)
    raise StoryboardError(f"{where}: unknown action `{kind}`")


def _parse_actions(value: object, prefix: str, field: str) -> tuple[Action, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise StoryboardError(f"{prefix}`{field}` must be a list of actions")
    actions = tuple(parse_action(item, f"{prefix}`{field}[{n}]`") for n, item in enumerate(value, 1))
    if field != "do":
        for n, action in enumerate(actions, 1):
            if action.kind in MARK_ACTIONS:
                raise StoryboardError(
                    f"{prefix}`{field}[{n}]`: `{action.kind}` draws on the picture, and `{field}` is not recorded"
                )
    return actions


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
    for key in ("title", "steps"):
        if key not in data:
            raise StoryboardError(f"missing field `{key}`")
    if "url" in data and "app" in data:
        raise StoryboardError("`url` and `app` do not go together: a storyboard films a web page or a desktop app")
    if "url" not in data and "app" not in data:
        raise StoryboardError("missing field `url`, for a web page, or `app`, for a desktop app")
    steps = data["steps"]
    if not isinstance(steps, list) or not steps:
        raise StoryboardError("`steps` must be a list with at least one step")
    # Both name a directory entry of howto's own, so neither may leave its directory.
    names = {}
    for field in ("profile", "voice"):
        names[field] = data.get(field)
        if names[field] is not None:
            names[field] = _text(names[field], f"`{field}`")
            if not PROFILE_RE.match(names[field]):
                raise StoryboardError(f"`{field}`: use letters, digits, `-` and `_` only")
    storyboard = Storyboard(
        path=path,
        title=_text(data["title"], "`title`"),
        url=_text(data["url"], "`url`") if "url" in data else None,
        app=_parse_app(data["app"]) if "app" in data else None,
        steps=tuple(parse_step(step, n) for n, step in enumerate(steps, 1)),
        profile=names["profile"],
        viewport=_parse_viewport(data.get("viewport")),
        setup=_parse_actions(data.get("setup"), "", "setup"),
        cleanup=_parse_actions(data.get("cleanup"), "", "cleanup"),
        pace=_parse_pace(data.get("pace")),
        zoom=_parse_zoom(data["zoom"], "") if "zoom" in data else 1.0,
        crop=parse_locator(data["crop"], "`crop`") if data.get("crop") is not None else None,
        voice=names["voice"],
    )
    _check_kind(storyboard)
    if storyboard.crop is not None:
        # A crop is one fixed part of the window, and a zoom moves the page under it.
        zoomed = [""] if storyboard.zoom > 1 else [f"step {step.index}: " for step in storyboard.steps if (step.zoom or 1) > 1]
        if zoomed:
            raise StoryboardError(
                f"{zoomed[0]}`zoom` and `crop` do not go together: "
                "a picture is cut to one part of the page, or enlarged around each control"
            )
    return storyboard


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
