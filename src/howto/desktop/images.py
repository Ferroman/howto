"""The base image of a desktop storyboard: what goes into it, how it is built, and whether an image is the right one."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from importlib import metadata
from pathlib import Path

from ..errors import RunError

BASE = "howto-desktop"
LABEL = "howto.build"
HERE = Path(__file__).parent


def files() -> list[tuple[str, Path]]:
    """What the image is built from, each with its name in the build: the Dockerfile, and the helper."""
    helper = HERE / "helper"
    found = [("Dockerfile", HERE / "image" / "Dockerfile")]
    found += [(f"helper/{path.relative_to(helper).as_posix()}", path) for path in sorted(helper.rglob("*.py"))]
    return found


def version() -> str:
    try:
        return metadata.version("howto-video")
    except metadata.PackageNotFoundError:
        return "0"


def build_id() -> str:
    """The version of howto, and a digest of what the image is built from.

    The version alone does not say enough: howto is installed from its
    repository, where the helper changes between two releases.
    """
    digest = hashlib.sha256()
    for name, path in files():
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return f"{version()}+{digest.hexdigest()[:8]}"


def context() -> bytes:
    """The build as a tar. Docker reads it from stdin, so the build needs no folder that Docker can read."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name, path in files():
            content = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), 0o644
            tar.addfile(info, io.BytesIO(content))
    return data.getvalue()


def build(docker: list[str]) -> tuple[str, str]:
    """Builds the base image and returns its two tags. Docker's own progress goes to the terminal."""
    tags = (f"{BASE}:{version()}", f"{BASE}:latest")
    command = [*docker, "build", "--build-arg", f"BUILD={build_id()}"]
    for tag in tags:
        command += ["-t", tag]
    try:
        proc = subprocess.run([*command, "-"], input=context())
    except OSError as exc:
        raise RunError(f"cannot start Docker: {exc.strerror or exc}") from None
    if proc.returncode != 0:
        raise RunError(f"docker build failed (exit {proc.returncode})")
    return tags


def _is_base(image: str) -> bool:
    return image.split(":")[0] == BASE


def built_by(docker: list[str], image: str) -> str:
    """The build of howto that an image holds, or nothing for an image that was not built from the base.

    Stops with what to run when the image does not exist, or when Docker does not answer.
    """
    command = [*docker, "image", "inspect", "--format", "{{json .Config.Labels}}", image]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise RunError(f"cannot start Docker: {exc.strerror or exc}") from None
    if proc.returncode == 0:
        try:
            labels = json.loads(proc.stdout or "null") or {}
        except ValueError:
            labels = {}
        return str(labels.get(LABEL, ""))
    if "no such image" in proc.stderr.lower():
        if _is_base(image):
            raise RunError(f"the image {image} does not exist: run `howto image`")
        raise RunError(f"the image {image} does not exist: run `docker build -t {image} DIR`, where DIR has its Dockerfile")
    said = proc.stderr.strip().splitlines()
    raise RunError(f"Docker does not answer: {said[-1] if said else 'it said nothing'}")


def check(docker: list[str], image: str, built: str | None = None) -> None:
    """Stops unless the image holds the helper of this howto. `built` is what a helper said of itself."""
    built = built_by(docker, image) if built is None else built
    ours = build_id()
    if built == ours:
        return
    if not built:
        raise RunError(f"the image {image} was not built from {BASE}: start its Dockerfile with `FROM {BASE}`")
    again = "run `howto image`" if _is_base(image) else f"run `howto image`, then build {image} again"
    raise RunError(f"the image {image} was built by howto {built}, and this is howto {ours}: {again}")
