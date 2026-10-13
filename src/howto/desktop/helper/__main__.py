"""The helper's entry: `python3 -m helper`, the main process of the container."""
from __future__ import annotations

import os
import sys

from .desk import Desk
from .protocol import serve


def main() -> int:
    # Stdout carries the protocol and nothing else. Whatever writes to it from now on writes to stderr.
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    desk = Desk()
    try:
        serve(desk.handlers(), sys.stdin, replies)
    finally:
        desk.stop()
    return 0


raise SystemExit(main())
