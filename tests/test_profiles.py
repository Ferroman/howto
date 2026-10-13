"""The profile of a desktop storyboard: a Docker volume, with a fake docker."""
import pytest

from howto.desktop import profiles
from howto.errors import RunError
from howto.tools import docker_command


def test_the_volume_of_a_profile_has_its_name():
    assert profiles.volume("demo") == "howto-profile-demo"


def test_a_profile_that_docker_has_exists(fake_docker):
    assert profiles.exists(docker_command(), "demo") is True
    assert fake_docker.calls() == [["volume", "inspect", "howto-profile-demo"]]


def test_a_profile_that_docker_does_not_have_does_not_exist(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_NO_VOLUME", "howto-profile-demo")
    assert profiles.exists(docker_command(), "demo") is False


def test_a_docker_that_does_not_answer_is_not_a_missing_profile(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    with pytest.raises(RunError, match="Docker does not answer: Cannot connect to the Docker daemon"):
        profiles.exists(docker_command(), "demo")


def test_a_profile_is_made_as_a_volume(fake_docker):
    profiles.create(docker_command(), "demo")
    assert fake_docker.calls() == [["volume", "create", "howto-profile-demo"]]


def test_a_profile_that_cannot_be_made_says_why(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    with pytest.raises(RunError, match="cannot make the profile demo: Cannot connect to the Docker daemon"):
        profiles.create(docker_command(), "demo")


def test_docker_that_cannot_be_started_is_a_run_error(tmp_path):
    with pytest.raises(RunError, match="cannot start Docker"):
        profiles.exists([str(tmp_path / "no-docker")], "demo")
