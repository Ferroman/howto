"""The storyboards in examples/ stay true to the demo page that they film."""
import argparse
import functools
import http.server
import re
import threading
from pathlib import Path

import pytest

from howto import cli
from howto.storyboard import load, parse, read_yaml

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
DOCUMENTS = ("README.md", "docs/guide.md", "skill/SKILL.md")
BOARDS = sorted(EXAMPLES.glob("*.yaml"))
# Where the README's quick start serves the demo page.
ADDRESS = "http://localhost:8000"


def test_the_examples_are_the_ones_the_readme_names():
    assert [path.name for path in BOARDS] == ["invite-picture.yaml", "invite.yaml"]


@pytest.mark.parametrize("path", BOARDS, ids=lambda path: path.name)
def test_an_example_is_a_storyboard_for_a_new_machine(path):
    storyboard = load(path)
    assert storyboard.url.startswith(ADDRESS)
    # Nothing that a person has to make first: no signed-in profile and no voice.
    assert storyboard.profile is None and storyboard.voice is None


def storyboards_in(document):
    """The YAML blocks of a document that are whole storyboards, each with the line it starts on."""
    lines = (ROOT / document).read_text(encoding="utf-8").splitlines()
    start = None
    for number, line in enumerate(lines, 1):
        if start is None and line.strip() == "```yaml":
            start = number
        elif start is not None and line.strip() == "```":
            # A block inside a list is indented, and YAML reads that as it is.
            block = "\n".join(lines[start: number - 1])
            if "title:" in block and "steps:" in block:
                yield start, block
            start = None


@pytest.mark.parametrize("document", DOCUMENTS)
def test_a_storyboard_shown_in_a_document_is_valid(document, tmp_path):
    found = list(storyboards_in(document))
    assert found, f"{document} shows no storyboard"
    for line, block in found:
        try:
            parse(read_yaml(block), tmp_path / "shown.yaml")
        except Exception as exc:
            pytest.fail(f"{document}, the storyboard at line {line}: {exc}")


def test_the_guide_shows_the_example_as_it_is():
    (_, shown), = [found for found in storyboards_in("docs/guide.md") if "crop:" in found[1]]
    assert read_yaml(shown) == read_yaml((EXAMPLES / "invite-picture.yaml").read_text(encoding="utf-8"))


def first_block_under(document, heading):
    """The first code block under a heading of a document."""
    _, found, rest = (ROOT / document).read_text(encoding="utf-8").partition(f"\n{heading}\n")
    assert found, f"{document} has no heading {heading!r}"
    return rest.split("```")[1]


def test_the_readme_sets_kokoro_up_as_the_speech_page_does():
    # The setup is shown twice, so that neither reader has to go to the other page for it.
    assert first_block_under("README.md", "### Kokoro") == first_block_under("docs/speech.md", "## Kokoro")


def options_of_the_commands():
    """Each option of each command, as its `--help` has it."""
    commands, = (action for action in cli.build_parser()._actions if isinstance(action, argparse._SubParsersAction))
    return {
        (name, option)
        for name, parser in commands.choices.items()
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }


def options_in_the_readme():
    """Each option of the README's table of options, with each command that its row names."""
    found = set()
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| `--"):
            options, commands, _ = line.strip("|").split("|")
            found |= {
                (command, option)
                for option in re.findall(r"`(--[a-z-]+)", options)
                for command in re.findall(r"`(\w+)`", commands)
            }
    return found


def test_the_readme_lists_every_option_of_every_command():
    missing = options_of_the_commands() - options_in_the_readme()
    assert not missing, f"the README's table of options lacks {sorted(missing)}"


def test_the_readme_lists_no_option_that_a_command_lacks():
    stale = options_in_the_readme() - options_of_the_commands()
    assert not stale, f"the README's table of options has {sorted(stale)}, which `--help` does not"


def exit_codes_in(document):
    """The rows of a document's table of exit codes."""
    lines = (ROOT / document).read_text(encoding="utf-8").splitlines()
    return [line for line in lines if re.match(r"\| \d+ \|", line)]


def test_the_readme_gives_the_exit_codes_as_the_skill_does():
    codes = exit_codes_in("skill/SKILL.md")
    assert codes and exit_codes_in("README.md") == codes


@pytest.fixture(scope="module")
def example_site():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(EXAMPLES / "site"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.browser
@pytest.mark.parametrize("path", BOARDS, ids=lambda path: path.name)
def test_an_example_runs_on_the_demo_page(path, chromium, example_site, sandbox, tmp_path, capsys):
    copy = tmp_path / path.name
    copy.write_text(path.read_text(encoding="utf-8").replace(ADDRESS, example_site), encoding="utf-8")
    assert cli.main(["probe", str(copy)]) == 0
    out = capsys.readouterr().out
    # A note would mean a dialog that was dismissed, a zoom that was skipped, or an element outside the crop.
    assert "note:" not in out
    assert "Invitation sent to sam@example.com" in out
