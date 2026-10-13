"""Runs a measurement inside the spike image and brings its files out.

No folder of the host is mounted: Docker from a snap limits what it mounts.
A script goes in through stdin, and files come out as the tar that
`docker cp` writes to its stdout.
"""
from __future__ import annotations

import io
import os
import shlex
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

HERE = Path(__file__).parent
IMAGE = "howto-spike"
DOCKER = shlex.split(os.environ.get("HOWTO_DOCKER") or "docker")
OUT = HERE.parent.parent / "spike-out" / "desktop"


def new_name() -> str:
    return f"howto-spike-{uuid.uuid4().hex[:8]}"


def build() -> None:
    """Builds the spike image. The Dockerfile goes in as a tar on stdin, so the build reads no folder."""
    data = io.BytesIO()
    # pax headers break docker build: the first member must be the Dockerfile itself.
    with tarfile.open(fileobj=data, mode="w", format=tarfile.GNU_FORMAT) as tar:
        tar.add(HERE / "Dockerfile", arcname="Dockerfile")
    subprocess.run([*DOCKER, "build", "-t", IMAGE, "-"], input=data.getvalue(), check=True)


def fetch(name: str, inside_path: str, target: Path) -> None:
    """Copies the files of one folder of a container into `target`."""
    tarred = subprocess.run([*DOCKER, "cp", f"{name}:{inside_path}", "-"], capture_output=True, check=True).stdout
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tarred)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                (target / Path(member.name).name).write_bytes(tar.extractfile(member).read())


def inside(*scripts: str, args=(), out: str | None = None, timeout: int = 900) -> str:
    """Runs the files spike/desktop/inside/SCRIPT..., joined into one program, in a new container.

    Returns the last line that the program printed. With `out`, what it left
    in /out is copied to spike-out/desktop/OUT.
    """
    source = "\n".join((HERE / "inside" / name).read_text(encoding="utf-8") for name in scripts)
    name = new_name()
    command = [*DOCKER, "run", "-i", "--init", "--shm-size=1g", "--user", "howto", "-e", "HOME=/home/howto",
               "--name", name, IMAGE, "python3", "-", *args]
    try:
        proc = subprocess.run(command, input=source, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-4000:])
            raise SystemExit(f"{scripts[-1]} failed in the container (exit {proc.returncode})")
        if out:
            fetch(name, "/out", OUT / out)
        # The result is the last line. A program of the desktop may have printed before it.
        return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    finally:
        subprocess.run([*DOCKER, "rm", "-f", name], capture_output=True)
