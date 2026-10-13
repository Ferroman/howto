"""Measurement: does Docker from a snap carry the link?

1. A request and its reply over `docker run -i`: the median of 200 round trips.
2. `docker cp` of a 200 MB file out of a container, as a tar on stdout.
3. A file fetched into a hidden folder, where a snap cannot write itself.
4. Ctrl+C in the terminal: the program that holds the pipe ends, and no container stays.

Run:  uv run python spike/desktop/docker.py
"""
from __future__ import annotations

import json
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

import box

ECHO = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line)\n    sys.stdout.flush()\n"
# Stands in for howto: it holds the pipe of a container, and ends on Ctrl+C.
HOLDER = """
import subprocess, sys, time
proc = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE, start_new_session=True)
try:
    time.sleep(120)
except KeyboardInterrupt:
    pass
"""


def round_trip() -> float:
    """Milliseconds for one request and its reply."""
    command = [*box.DOCKER, "run", "--rm", "-i", "--init", "--name", box.new_name(), box.IMAGE, "python3", "-u", "-c", ECHO]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
    times = []
    for number in range(220):
        began = time.perf_counter()
        proc.stdin.write(json.dumps({"id": number, "request": "echo"}) + "\n")
        proc.stdin.flush()
        assert json.loads(proc.stdout.readline())["id"] == number
        times.append((time.perf_counter() - began) * 1000)
    proc.stdin.close()
    proc.wait(timeout=30)
    # The first ones include the start of the container.
    return statistics.median(times[20:])


def copy_out() -> tuple[float, bool]:
    """Seconds to fetch 200 MB, and whether a small file arrives in a hidden folder."""
    name = box.new_name()
    make = "head -c 200000000 /dev/urandom > /tmp/big && mkdir /tmp/small && echo arrived > /tmp/small/note.txt"
    subprocess.run([*box.DOCKER, "run", "--name", name, box.IMAGE, "sh", "-c", make], check=True)
    try:
        began = time.perf_counter()
        proc = subprocess.Popen([*box.DOCKER, "cp", f"{name}:/tmp/big", "-"], stdout=subprocess.PIPE)
        size = 0
        while chunk := proc.stdout.read(1 << 20):
            size += len(chunk)
        proc.wait()
        seconds = time.perf_counter() - began
        assert size >= 200_000_000, size
        hidden = Path.home() / ".cache" / "howto" / "spike-fetch"
        box.fetch(name, "/tmp/small", hidden)
        return seconds, (hidden / "note.txt").read_text() == "arrived\n"
    finally:
        subprocess.run([*box.DOCKER, "rm", "-f", name], capture_output=True)


def containers(name: str) -> str:
    return subprocess.run([*box.DOCKER, "ps", "-aq", "--filter", f"name={name}"], capture_output=True, text=True).stdout.strip()


def interrupted() -> bool:
    """Whether the container is gone ten seconds after Ctrl+C reaches the program that holds its pipe."""
    name = box.new_name()
    command = [*box.DOCKER, "run", "--rm", "-i", "--init", "--name", name, box.IMAGE, "python3", "-c", "import sys; sys.stdin.read()"]
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, *command], start_new_session=True)
    deadline = time.monotonic() + 60
    while not containers(name):
        assert time.monotonic() < deadline, "the container never started"
        time.sleep(0.2)
    # What a terminal sends: SIGINT to the foreground group. Docker is in a session of its own.
    os.killpg(holder.pid, signal.SIGINT)
    holder.wait(timeout=20)
    deadline = time.monotonic() + 10
    while containers(name) and time.monotonic() < deadline:
        time.sleep(0.2)
    gone = not containers(name)
    subprocess.run([*box.DOCKER, "rm", "-f", name], capture_output=True)
    return gone


def main() -> int:
    box.build()
    trip = round_trip()
    seconds, hidden = copy_out()
    gone = interrupted()
    lines = [
        (trip <= 20, f"a round trip takes {trip:.1f} ms (20 or less)"),
        (seconds <= 5, f"docker cp fetches 200 MB in {seconds:.1f} s (5 or less)"),
        (hidden, "a file arrives in a hidden folder"),
        (gone, "Ctrl+C leaves no container"),
    ]
    for ok, text in lines:
        print(f'{"PASS" if ok else "FAIL"}  {text}')
    return 0 if all(ok for ok, _ in lines) else 1


if __name__ == "__main__":
    raise SystemExit(main())
