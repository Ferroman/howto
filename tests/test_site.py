"""The script that stages the documentation for the site: scripts/build_site.py."""
import importlib.util
import shutil
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


PLAYER = '<video controls preload="metadata" width="100%" src="media/invite.mp4">\n</video>\n'


def test_a_link_to_a_video_gets_a_player_under_its_paragraph(repo):
    text = "Watch [the video](docs/media/invite.mp4),\nwhich is short.\n\nThe next paragraph.\n"
    assert rewritten(repo, "README.md", text) == (
        "Watch [the video](media/invite.mp4),\nwhich is short.\n\n" + PLAYER + "\nThe next paragraph.\n"
    )


def test_a_player_follows_a_paragraph_that_ends_the_document(repo):
    assert rewritten(repo, "docs/speech.md", "[The video](media/invite.mp4)\n") == (
        "[The video](media/invite.mp4)\n\n" + PLAYER
    )


def test_a_player_has_subtitles_when_they_lie_beside_the_video(repo):
    (repo / "docs/media/invite.vtt").write_text("WEBVTT\n", encoding="utf-8")
    assert rewritten(repo, "README.md", "[The video](docs/media/invite.mp4)\n") == (
        "[The video](media/invite.mp4)\n\n"
        '<video controls preload="metadata" width="100%" src="media/invite.mp4">\n'
        '  <track kind="subtitles" srclang="en" label="English" src="media/invite.vtt" default>\n'
        "</video>\n"
    )


def test_a_video_linked_twice_in_a_paragraph_gets_one_player(repo):
    text = "[Once](docs/media/invite.mp4) and [again](docs/media/invite.mp4).\n"
    assert rewritten(repo, "README.md", text).count("<video") == 1


def test_a_video_in_a_list_plays_after_the_list(repo):
    text = "- [The video](docs/media/invite.mp4)\n- Another item\n\nAfter the list.\n"
    assert rewritten(repo, "README.md", text) == (
        "- [The video](media/invite.mp4)\n- Another item\n\n" + PLAYER + "\nAfter the list.\n"
    )


def test_a_video_named_in_code_gets_no_player(repo):
    text = "The file `[video](docs/media/invite.mp4)` is not a link.\n"
    assert rewritten(repo, "README.md", text) == text


def test_the_picture_of_a_diagram_opens_its_live_page(repo):
    assert rewritten(repo, "docs/internals.md", "![The parts](../.diagrams/static/parts.png)\n") == (
        "[![The parts](diagrams/static/parts.png)](diagrams/html/parts.html)\n"
    )


def test_a_diagram_without_a_live_page_is_a_problem(repo):
    (repo / ".diagrams/html/parts.html").unlink()
    _, problems = build_site.rewrite("![The parts](.diagrams/static/parts.png)\n", "README.md", repo)
    assert problems == ["README.md:1: the diagram `parts` has no live page: run `diagc publish` first"]


def test_a_diagram_that_is_already_a_link_is_not_wrapped_again(repo):
    text = "[![The parts](.diagrams/static/parts.png)](docs/guide.md)\n"
    assert rewritten(repo, "README.md", text) == "[![The parts](diagrams/static/parts.png)](guide.md)\n"


def test_another_picture_is_not_made_a_link(repo):
    assert rewritten(repo, "README.md", "![A picture](docs/media/picture.gif)\n") == "![A picture](media/picture.gif)\n"


def staged_files(out):
    return sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())


def test_the_staged_tree_has_the_documents_and_the_folders(repo):
    out = repo / "_build" / "docs"
    assert build_site.stage(repo, out) == []
    assert staged_files(out) == [
        "diagrams/html/index.html",
        "diagrams/html/parts.html",
        "diagrams/static/parts.png",
        "guide.md",
        "index.md",
        "internals.md",
        "media/invite.mp4",
        "media/picture.gif",
        "speech.md",
        "storyboard.md",
    ]
    assert (out / "index.md").read_text(encoding="utf-8") == "# howto\n"


def test_a_second_run_replaces_the_first(repo):
    out = repo / "_build" / "docs"
    assert build_site.stage(repo, out) == []
    (repo / "docs/media/picture.gif").unlink()
    assert build_site.stage(repo, out) == []
    assert "media/picture.gif" not in staged_files(out)


def test_a_problem_leaves_no_staged_tree_not_even_an_earlier_one(repo):
    out = repo / "_build" / "docs"
    assert build_site.stage(repo, out) == []
    (repo / "docs/guide.md").write_text("[Gone](gone.md)\n", encoding="utf-8")
    assert build_site.stage(repo, out) == ["docs/guide.md:1: the link `gone.md` names nothing: docs/gone.md does not exist"]
    assert not out.exists()


def test_a_missing_folder_of_diagc_says_how_to_make_it(repo):
    shutil.rmtree(repo / ".diagrams/html")
    assert build_site.stage(repo, repo / "_build" / "docs") == [
        ".diagrams/html: the folder is missing: run `diagc publish` first"
    ]


def test_a_missing_document_is_a_problem(repo):
    (repo / "docs/speech.md").unlink()
    problems = build_site.stage(repo, repo / "_build" / "docs")
    assert len(problems) == 1 and problems[0].startswith("docs/speech.md: cannot be read")


def test_the_command_prints_the_folder_and_exits_with_0(repo, capsys):
    assert build_site.main(["--root", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == str(repo / "_build" / "docs")


def test_the_command_prints_every_problem_and_exits_with_1(repo, capsys):
    (repo / "README.md").write_text("[A](a.md)\n\n[B](b.md)\n", encoding="utf-8")
    assert build_site.main(["--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "build_site: README.md:1: the link `a.md` names nothing" in err
    assert "build_site: README.md:3: the link `b.md` names nothing" in err
    assert "build_site: 2 problem(s). Nothing is staged." in err


@pytest.mark.parametrize("source", build_site.PAGES)
def test_the_links_of_a_real_document_resolve(source):
    _, problems = build_site.rewrite((ROOT / source).read_text(encoding="utf-8"), source, ROOT)
    # The live pages of the diagrams are build output, which a fresh checkout does not have.
    assert [problem for problem in problems if "has no live page" not in problem] == []
