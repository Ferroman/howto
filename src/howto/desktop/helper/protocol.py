"""The helper's side of the link: one request on each line of stdin, one reply on each line of stdout.

A request is {"id": N, "request": NAME, ...}. A reply is {"id": N, "ok": true, ...}
or {"id": N, "ok": false, "kind": KIND, "error": WHY}.
"""
from __future__ import annotations

import json
import traceback
from typing import Callable, TextIO

Handler = Callable[[dict], "dict | None"]


class Refusal(Exception):
    """A request that could not be carried out. `kind` tells the stage what happened."""

    def __init__(self, kind: str, error: str) -> None:
        super().__init__(error)
        self.kind = kind


def answer(handlers: dict[str, Handler], line: str) -> dict:
    """The reply to one line."""
    try:
        request = json.loads(line)
        number, name = request["id"], request["request"]
    except (ValueError, KeyError, TypeError):
        return {"id": None, "ok": False, "kind": "bad_request", "error": "not a request: " + line.strip()[:200]}
    handler = handlers.get(name)
    if handler is None:
        return {"id": number, "ok": False, "kind": "bad_request", "error": f"unknown request `{name}`"}
    try:
        reply = handler(request) or {}
    except Refusal as exc:
        return {"id": number, "ok": False, "kind": exc.kind, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the stage must hear of it, whatever it is
        traceback.print_exc()
        return {"id": number, "ok": False, "kind": "internal", "error": f"{type(exc).__name__}: {exc}"}
    return {"id": number, "ok": True, **reply}


def serve(handlers: dict[str, Handler], requests: TextIO, replies: TextIO) -> None:
    """Answers requests until the pipe closes. When the stage is gone, so is the reason to stay."""
    for line in requests:
        if not line.strip():
            continue
        replies.write(json.dumps(answer(handlers, line)) + "\n")
        replies.flush()
