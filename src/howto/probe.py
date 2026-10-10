"""The text a probe prints: one line per step, then the page it ended on.

The reader is usually a model that is writing the storyboard, so the report
is plain text with the same words a locator uses.
"""
from __future__ import annotations

from .runner import RunResult


def cut_outline(outline: str, max_chars: int) -> tuple[str, int]:
    """The outline, cut at the last line end before `max_chars`, and how much was left out."""
    if len(outline) <= max_chars:
        return outline, 0
    kept = outline[:max_chars]
    if "\n" in kept:
        kept = kept[: kept.rindex("\n")]
    return kept, len(outline) - len(kept)


def format_report(result: RunResult) -> str:
    lines = []
    for step in result.steps:
        label = "setup " if step.index == 0 else f"step {step.index}"
        if step.ok:
            lines.append(f"{label} ok      {step.summary}")
        else:
            lines.append(f"{label} FAILED  {step.error}")
    lines.extend(f"warning: {warning}" for warning in result.warnings)
    page = result.page
    if page is not None:
        lines.append(f'page: {page.url}  "{page.title}"')
        lines.append("outline:")
        lines.append(page.outline.rstrip("\n"))
        if page.omitted:
            lines.append(f"(outline cut: {page.omitted} more characters; use --within or --max-chars)")
    return "\n".join(lines) + "\n"
