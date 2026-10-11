"""Stages the documentation for the site, in `_build/docs`, for Zensical to render.

The documents stay where they read well on GitHub: the README at the root, the
guides in docs/, the storyboard format in skill/. On the site each has another
name, so their links are rewritten here, and each still lands where it did.

It uses the standard library only, and knows nothing about the generator.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPOSITORY = "https://github.com/Ferroman/howto"
BRANCH = "main"

# A document in the repository, and its name on the site.
PAGES = {
    "README.md": "index.md",
    "docs/guide.md": "guide.md",
    "docs/speech.md": "speech.md",
    "docs/internals.md": "internals.md",
    "skill/SKILL.md": "storyboard.md",
}
# A folder in the repository, and its place on the site. The gallery of
# diagrams reaches its thumbnails as ../static/NAME.png, so html/ and static/
# stay side by side.
FOLDERS = {
    "docs/media": "media",
    ".diagrams/html": "diagrams/html",
    ".diagrams/static": "diagrams/static",
}
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
# The end of an inline link or image: `](target)`, or `](target "title")`.
TARGET = re.compile(r"""\]\(([^()\s]+)(\s+"[^"]*")?\)""")
DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S")
SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|//)")


def staged(path: str) -> str | None:
    """Where a path of the repository is on the site, or None when it is not staged."""
    if path in PAGES:
        return PAGES[path]
    for folder, place in FOLDERS.items():
        if path.startswith(folder + "/"):
            return place + path[len(folder):]
    return None


class _Document:
    """One document being rewritten, and the problems found in it."""

    def __init__(self, source: str, root: Path) -> None:
        self.source = source
        self.root = root
        self.problems: list[str] = []

    def problem(self, number: int, message: str) -> None:
        self.problems.append(f"{self.source}:{number}: {message}")

    def target(self, target: str, number: int) -> str:
        """The target of a link as the site needs it."""
        if SCHEME.match(target) or target.startswith("#"):
            return target
        path, mark, heading = target.partition("#")
        found = posixpath.normpath(posixpath.join(posixpath.dirname(self.source), path))
        if found == ".." or found.startswith("../") or path.startswith("/"):
            self.problem(number, f"the link `{target}` leaves the repository")
            return target
        if not (self.root / found).exists():
            self.problem(number, f"the link `{target}` names nothing: {found} does not exist")
            return target
        place = staged(found)
        if place is None:
            kind = "tree" if (self.root / found).is_dir() else "blob"
            return f"{REPOSITORY}/{kind}/{BRANCH}/{found}{mark}{heading}"
        return f"{place}{mark}{heading}"

    def line(self, text: str, number: int) -> str:
        """A line outside a code block, with its links rewritten. What is inside a code span stays."""
        spans: list[str] = []

        def keep(match: re.Match[str]) -> str:
            spans.append(match.group(0))
            return f"\x00{len(spans) - 1}\x00"

        text = CODE_SPAN.sub(keep, text)
        text = TARGET.sub(lambda m: f"]({self.target(m.group(1), number)}{m.group(2) or ''})", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def rewrite(text: str, source: str, root: Path) -> tuple[str, list[str]]:
    """The text of a document as the site needs it, and what is wrong with its links."""
    document = _Document(source, root)
    out: list[str] = []
    fence: str | None = None
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        opened = FENCE.match(line)
        if fence is not None:
            # A block ends at a fence of the same character that is at least as long.
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
                fence = None
            out.append(line)
            continue
        if opened:
            fence = opened.group(1)
            out.append(line)
            continue
        if DEFINITION.match(line):
            document.problem(number, "a link definition is not checked: write the link inline, as `[text](target)`")
        out.append(document.line(line, number))
    return "\n".join(out) + "\n", document.problems
