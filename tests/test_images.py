"""The base image: what goes into it, how `howto image` builds it, and how a wrong image is told from the right one."""
import pytest

from howto import cli
from howto.desktop import images
from howto.errors import RunError
from howto.tools import docker_command


def test_the_build_holds_the_dockerfile_and_every_file_of_the_helper():
    names = [name for name, _ in images.files()]
    assert names[0] == "Dockerfile"
    assert "helper/__init__.py" in names and "helper/tree.py" in names
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]


def test_the_build_id_is_the_version_and_a_digest():
    version, _, digest = images.build_id().partition("+")
    assert version == images.version()
    assert len(digest) == 8 and int(digest, 16) >= 0


def test_a_changed_helper_gives_another_build_id(tmp_path, monkeypatch):
    (tmp_path / "image").mkdir()
    (tmp_path / "helper").mkdir()
    (tmp_path / "image" / "Dockerfile").write_text("FROM ubuntu:24.04\n")
    (tmp_path / "helper" / "tree.py").write_text("A = 1\n")
    monkeypatch.setattr(images, "HERE", tmp_path)
    before = images.build_id()
    (tmp_path / "helper" / "tree.py").write_text("A = 2\n")
    assert images.build_id() != before


def test_howto_image_builds_from_stdin_and_prints_the_tags(fake_docker, capsys):
    assert cli.main(["image"]) == 0
    version = images.version()
    assert capsys.readouterr().out.splitlines() == [f"howto-desktop:{version}", "howto-desktop:latest"]
    assert fake_docker.calls() == [[
        "build", "--build-arg", f"BUILD={images.build_id()}",
        "-t", f"howto-desktop:{version}", "-t", "howto-desktop:latest", "-",
    ]]
    assert "Dockerfile" in fake_docker.context() and "helper/protocol.py" in fake_docker.context()


def test_a_failed_build_exits_1(fake_docker, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_DOCKER_FAIL", "build")
    assert cli.main(["image"]) == 1
    assert "docker build failed (exit 1)" in capsys.readouterr().err


def test_an_image_of_this_build_passes(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_BUILD", images.build_id())
    images.check(docker_command(), "howto-inkscape")


def refused(image):
    with pytest.raises(RunError) as caught:
        images.check(docker_command(), image)
    return str(caught.value)


def test_a_missing_base_image_names_the_command_that_builds_it(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_MISSING", "howto-desktop")
    assert refused("howto-desktop") == "the image howto-desktop does not exist: run `howto image`"


def test_a_missing_image_of_an_app_names_the_docker_build(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_MISSING", "howto-inkscape")
    assert refused("howto-inkscape") == (
        "the image howto-inkscape does not exist: run `docker build -t howto-inkscape DIR`, where DIR has its Dockerfile"
    )


def test_an_image_from_another_build_names_both_commands(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_BUILD", "0.0.9+00000000")
    ours = images.build_id()
    assert refused("howto-inkscape") == (
        f"the image howto-inkscape was built by howto 0.0.9+00000000, and this is howto {ours}: "
        "run `howto image`, then build howto-inkscape again"
    )
    assert refused("howto-desktop:latest").endswith(f"and this is howto {ours}: run `howto image`")


def test_an_image_that_was_not_built_from_the_base_says_so(fake_docker):
    assert refused("ubuntu") == "the image ubuntu was not built from howto-desktop: start its Dockerfile with `FROM howto-desktop`"


def test_what_a_helper_said_of_itself_is_checked_without_asking_docker(fake_docker):
    images.check(docker_command(), "howto-inkscape", built=images.build_id())
    with pytest.raises(RunError, match="was built by howto 0.0.1"):
        images.check(docker_command(), "howto-inkscape", built="0.0.1")
    assert fake_docker.calls() == []


def test_a_daemon_that_is_not_running_is_named(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    assert refused("howto-inkscape").startswith("Docker does not answer: Cannot connect to the Docker daemon")


def test_docker_that_is_not_installed_is_named(monkeypatch, tmp_path):
    monkeypatch.setenv("HOWTO_DOCKER", str(tmp_path / "no-docker"))
    with pytest.raises(RunError, match="no-docker not found: install Docker, or set HOWTO_DOCKER"):
        docker_command()


def test_the_docker_command_may_have_words_in_front(fake_docker, monkeypatch):
    monkeypatch.setenv("HOWTO_DOCKER", f"env SUDO=1 {fake_docker.program}")
    monkeypatch.setenv("FAKE_DOCKER_BUILD", images.build_id())
    assert docker_command() == ["env", "SUDO=1", fake_docker.program]
    assert images.built_by(docker_command(), "howto-inkscape") == images.build_id()


def test_the_docker_command_is_docker_unless_told(monkeypatch, tmp_path):
    program = tmp_path / "docker"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.delenv("HOWTO_DOCKER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert docker_command() == ["docker"]
