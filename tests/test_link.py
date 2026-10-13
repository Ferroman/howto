"""The link to the helper, with a fake docker that plays the helper."""
import os

import pytest

from howto.desktop.link import HelperError, open_link
from howto.errors import RunError
from howto.tools import docker_command


@pytest.fixture
def link(fake_docker):
    opened = open_link(docker_command(), "howto-fixture")
    # One round trip, so that the fake has started and written its call down before a test reads the calls.
    opened.request("echo", limit=5)
    yield opened
    opened.close(wait=0.5)


def test_the_container_is_started_for_the_length_of_the_pipe(fake_docker, link):
    assert fake_docker.calls() == [["run", "--rm", "-i", "--init", "--shm-size=1g", "--name", link.name, "howto-fixture"]]
    assert link.name.startswith(f"howto-{os.getpid()}-")


def test_a_request_gets_its_reply(link):
    reply = link.request("echo", limit=5, text="héllo", box=[1, 2])
    assert reply["fields"] == {"text": "héllo", "box": [1, 2]}
    assert link.request("echo", limit=5)["id"] == reply["id"] + 1


def test_a_refusal_carries_its_kind_and_its_reason(link):
    with pytest.raises(HelperError) as caught:
        link.request("refuse", limit=5)
    assert (caught.value.kind, str(caught.value)) == ("covered", "another window covers it")


def test_a_line_that_is_no_reply_is_passed_over(link):
    assert link.request("noise", limit=5)["ok"] is True


def test_a_helper_that_does_not_answer_ends_the_command(link):
    with pytest.raises(RunError, match="the desktop stopped answering: `hang` got no reply in 0.3 seconds"):
        link.request("hang", limit=0.3)


def test_a_helper_that_ends_is_reported_with_what_it_said(link):
    with pytest.raises(RunError) as caught:
        link.request("die", limit=5)
    assert str(caught.value) == "the desktop stopped:\nthe helper fell over"


def test_a_request_after_the_helper_ended_says_so_too(link):
    with pytest.raises(RunError):
        link.request("die", limit=5)
    with pytest.raises(RunError, match="the desktop stopped"):
        link.request("echo", limit=5)


def test_a_file_comes_out_of_the_tar_that_docker_writes(fake_docker, link, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_DOCKER_FILE", "a recording")
    out = tmp_path / "work" / "capture.mkv"
    link.fetch("/tmp/howto/take.mkv", out)
    assert out.read_text() == "a recording"
    assert fake_docker.calls()[-1] == ["cp", f"{link.name}:/tmp/howto/take.mkv", "-"]


def test_a_file_that_docker_cannot_give_is_named(link, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    with pytest.raises(RunError, match="cannot fetch /tmp/howto/take.mkv from the desktop: Cannot connect"):
        link.fetch("/tmp/howto/take.mkv", tmp_path / "capture.mkv")


def test_closing_the_pipe_ends_the_container(fake_docker):
    opened = open_link(docker_command(), "howto-fixture")
    opened.request("echo", limit=5)
    opened.close()
    assert [call[0] for call in fake_docker.calls()] == ["run"]


def test_a_container_that_stays_is_removed(fake_docker):
    opened = open_link(docker_command(), "howto-fixture")
    with pytest.raises(RunError):
        opened.request("hang", limit=0.2)
    opened.close(wait=0.3)
    assert fake_docker.calls()[-1] == ["rm", "-f", opened.name]


def test_docker_runs_in_a_session_of_its_own(link):
    # Ctrl+C in the terminal goes to the foreground group, and must not reach the container.
    assert os.getsid(link._process.pid) != os.getsid(0)


def test_docker_that_cannot_be_started_is_a_run_error(tmp_path):
    with pytest.raises(RunError, match="cannot start Docker"):
        open_link([str(tmp_path / "no-docker")], "howto-fixture")
