"""The script that stages the documentation for the site: scripts/build_site.py."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
# The script is not part of the package, so it is loaded from its file.
_spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
build_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_site)


@pytest.fixture
def repo(tmp_path):
    """A stand-in repository: the five documents, a video, a picture, and a diagram with its live page."""
    files = {
        "README.md": "# howto\n",
        "LICENSE": "MIT\n",
        "docs/guide.md": "# Guide\n",
        "docs/speech.md": "# Speech\n",
        "docs/internals.md": "# Internals\n",
        "skill/SKILL.md": "# Skill\n",
        "examples/invite.yaml": "title: Invite\n",
        "docs/media/invite.mp4": "",
        "docs/media/picture.gif": "",
        ".diagrams/static/parts.png": "",
        ".diagrams/html/parts.html": "<html></html>",
        ".diagrams/html/index.html": "<html></html>",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def rewritten(repo, source, text):
    """The text as the site needs it. A problem fails the test."""
    out, problems = build_site.rewrite(text, source, repo)
    assert problems == []
    return out


def test_a_link_to_a_document_gets_its_name_on_the_site(repo):
    text = "See [the guide](docs/guide.md#make-a-video) and [the skill](skill/SKILL.md).\n"
    assert rewritten(repo, "README.md", text) == "See [the guide](guide.md#make-a-video) and [the skill](storyboard.md).\n"


def test_a_link_is_resolved_from_the_folder_of_its_document(repo):
    text = "[The README](../README.md), [the speech page](speech.md#kokoro)\n"
    assert rewritten(repo, "docs/guide.md", text) == "[The README](index.md), [the speech page](speech.md#kokoro)\n"


def test_a_file_in_a_staged_folder_gets_its_place_on_the_site(repo):
    assert rewritten(repo, "README.md", "![A picture](docs/media/picture.gif)\n") == "![A picture](media/picture.gif)\n"
    assert rewritten(repo, "docs/guide.md", "![A picture](media/picture.gif)\n") == "![A picture](media/picture.gif)\n"


def test_any_other_file_gets_its_address_on_github(repo):
    text = "[The example](../examples/invite.yaml), [the licence](../LICENSE)\n"
    assert rewritten(repo, "docs/guide.md", text) == (
        "[The example](https://github.com/Ferroman/howto/blob/main/examples/invite.yaml), "
        "[the licence](https://github.com/Ferroman/howto/blob/main/LICENSE)\n"
    )


def test_a_folder_gets_its_address_on_github(repo):
    assert rewritten(repo, "README.md", "[The examples](examples)\n") == (
        "[The examples](https://github.com/Ferroman/howto/tree/main/examples)\n"
    )


def test_a_link_to_another_site_or_to_a_heading_of_the_page_stays(repo):
    text = "[A site](https://example.com/a.md), [mail](mailto:sam@example.com), [a heading](#speech)\n"
    assert rewritten(repo, "README.md", text) == text


def test_what_is_in_code_stays(repo):
    text = (
        "Write `[text](docs/guide.md)` like this:\n"
        "\n"
        "```markdown\n"
        "[the guide](docs/guide.md)\n"
        "```\n"
        "\n"
        "1. And in a list:\n"
        "\n"
        "   ~~~\n"
        "   [the guide](docs/gone.md)\n"
        "   ~~~\n"
    )
    assert rewritten(repo, "README.md", text) == text


def test_a_link_whose_words_are_code_is_rewritten(repo):
    assert rewritten(repo, "README.md", "[`docs/guide.md`](docs/guide.md)\n") == "[`docs/guide.md`](guide.md)\n"


def test_a_picture_that_is_a_link_has_both_targets_rewritten(repo):
    text = "[![A picture](docs/media/picture.gif)](docs/guide.md)\n"
    assert rewritten(repo, "README.md", text) == "[![A picture](media/picture.gif)](guide.md)\n"


def test_a_title_stays_on_its_link(repo):
    assert rewritten(repo, "README.md", '[The guide](docs/guide.md "How to")\n') == '[The guide](guide.md "How to")\n'


def test_a_document_without_a_last_line_end_gets_one(repo):
    assert rewritten(repo, "README.md", "One line.\r\n[The guide](docs/guide.md)") == "One line.\n[The guide](guide.md)\n"


def test_a_dead_link_is_a_problem_with_its_file_and_line(repo):
    out, problems = build_site.rewrite("One.\n\n[Gone](docs/gone.md#heading)\n", "README.md", repo)
    assert problems == ["README.md:3: the link `docs/gone.md#heading` names nothing: docs/gone.md does not exist"]


def test_a_link_that_leaves_the_repository_is_a_problem(repo):
    _, problems = build_site.rewrite("[Up](../elsewhere.md) and [root](/etc/hosts)\n", "README.md", repo)
    assert problems == [
        "README.md:1: the link `../elsewhere.md` leaves the repository",
        "README.md:1: the link `/etc/hosts` leaves the repository",
    ]


def test_a_link_definition_is_refused(repo):
    _, problems = build_site.rewrite("[The guide][guide]\n\n[guide]: docs/guide.md\n", "README.md", repo)
    assert problems == ["README.md:3: a link definition is not checked: write the link inline, as `[text](target)`"]
