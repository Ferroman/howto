"""The helper's side of the link, with handlers that are plain functions."""
import io
import json

from howto.desktop.helper.protocol import Refusal, answer, serve


def refuse(request):
    raise Refusal("covered", 'another window covers it: "Open"')


def crash(request):
    raise ZeroDivisionError("division by zero")


HANDLERS = {
    "echo": lambda request: {"said": request["text"]},
    "nothing": lambda request: None,
    "refuse": refuse,
    "crash": crash,
}


def ask(**request):
    return answer(HANDLERS, json.dumps(request))


def test_a_reply_carries_the_number_of_its_request():
    assert ask(id=7, request="echo", text="hé") == {"id": 7, "ok": True, "said": "hé"}


def test_a_handler_that_returns_nothing_still_answers():
    assert ask(id=1, request="nothing") == {"id": 1, "ok": True}


def test_a_refusal_names_its_kind_and_its_reason():
    assert ask(id=2, request="refuse") == {
        "id": 2, "ok": False, "kind": "covered", "error": 'another window covers it: "Open"',
    }


def test_a_handler_that_fails_is_reported_and_does_not_end_the_helper(capsys):
    assert ask(id=3, request="crash") == {
        "id": 3, "ok": False, "kind": "internal", "error": "ZeroDivisionError: division by zero",
    }
    assert "ZeroDivisionError" in capsys.readouterr().err


def test_an_unknown_request_is_named():
    assert ask(id=4, request="fly") == {"id": 4, "ok": False, "kind": "bad_request", "error": "unknown request `fly`"}


def test_a_line_that_is_no_request_is_answered_without_a_number():
    reply = answer(HANDLERS, "not json\n")
    assert (reply["id"], reply["ok"], reply["kind"]) == (None, False, "bad_request")
    assert "not json" in reply["error"]
    assert answer(HANDLERS, '{"request": "echo"}')["kind"] == "bad_request"
    assert answer(HANDLERS, "[1, 2]")["kind"] == "bad_request"


def test_the_loop_answers_each_line_and_ends_with_the_pipe():
    requests = io.StringIO(
        json.dumps({"id": 1, "request": "echo", "text": "a"}) + "\n\n" + json.dumps({"id": 2, "request": "nothing"}) + "\n"
    )
    replies = io.StringIO()
    serve(HANDLERS, requests, replies)
    assert [json.loads(line) for line in replies.getvalue().splitlines()] == [
        {"id": 1, "ok": True, "said": "a"},
        {"id": 2, "ok": True},
    ]


def test_each_reply_is_one_line_whatever_it_holds():
    reply = io.StringIO()
    serve({"echo": lambda request: {"said": "two\nlines"}}, io.StringIO('{"id": 1, "request": "echo"}\n'), reply)
    assert reply.getvalue().count("\n") == 1
