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
    if result.crop is not None:
        cut = result.crop
        lines.append(f"crop: {cut.width:g} x {cut.height:g} pixels at {cut.x:g}, {cut.y:g}")
    for step in result.steps:
        label = "setup " if step.index == 0 else f"step {step.index}"
        if step.ok:
            lines.append(f"{label} ok      {step.summary}")
        else:
            lines.append(f"{label} FAILED  {step.error}")
    lines.extend(f"warning: {warning}" for warning in result.warnings)
    page = result.page
    if page is not None:
        lines.extend(f"note: {notice}" for notice in page.notices)
        lines.append(f'page: {page.url}  "{page.title}"')
        lines.append("outline:")
        lines.append(page.outline.rstrip("\n"))
        if page.words:
            lines.append("words on the screen that the outline lacks:")
            lines.extend(f"- {words}" for words in page.words)
        if page.omitted and page.words:
            # The outline was printed whole, so what is missing is words.
            lines.append(f"(words cut: {page.omitted} more characters; use --max-chars)")
        elif page.omitted:
            lines.append(f"(outline cut: {page.omitted} more characters; use --within or --max-chars)")
        if page.screenshot:
            lines.append(f"screenshot: {page.screenshot}")
    return "\n".join(lines) + "\n"
