"""cleanlisten_gemini: Gemini through Google's Antigravity CLI (agy), with agy faked.

agy's headless answer is one JSON object (status, response, conversation_id, and
structured_output when a schema is given). These tests check how CleanListen reads it and
turns failures into plain messages; they don't talk to Google.
"""
import json
import types

import pytest

import cleanlisten_claude as cc
import cleanlisten_gemini as G

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


@pytest.fixture
def agy(monkeypatch, tmp_path):
    """A fake agy: records each command and replies with whatever the test sets."""
    calls, reply = [], {"out": "", "err": "", "code": 0}

    def run(cmd, **kw):
        req = kw["cwd"] + "/" + G.REQUEST
        try:
            with open(req, encoding="utf8") as f:
                text = f.read()
        except OSError:
            text = None
        calls.append({"cmd": cmd, "cwd": kw["cwd"], "file": text})
        return types.SimpleNamespace(stdout=reply["out"], stderr=reply["err"], returncode=reply["code"])

    monkeypatch.setattr(G, "find", lambda: "agy.exe")
    monkeypatch.setattr(G, "APP_DATA", tmp_path)
    monkeypatch.setattr(G.subprocess, "run", run)
    return calls, reply


def env(**kw):
    return json.dumps({"status": "SUCCESS", "conversation_id": "c1", **kw})


def test_structured_output(agy):
    calls, reply = agy
    reply["out"] = env(response="", structured_output={"answer": "ok"})
    assert G.ask("Hello", SCHEMA, system="Be brief.") == ({"answer": "ok"}, "c1")
    cmd = calls[0]["cmd"]
    assert cmd[:2] == ["agy.exe", "-p"] and "Be brief." in cmd[2] and "Hello" in cmd[2]
    assert ["--output-format", "json"] == cmd[3:5] and "--sandbox" in cmd and "--json-schema" in cmd


def test_answer_in_a_json_fence(agy):
    _, reply = agy
    reply["out"] = env(response='```json\n{"answer": "fenced", "toolSummary": "x"}\n```')
    assert G.ask("Hi", SCHEMA)[0] == {"answer": "fenced"}


def test_long_request_goes_in_a_file(agy):
    calls, reply = agy
    reply["out"] = env(structured_output={"answer": "read it"})
    book = "word " * 20000
    G.ask("Check this book.", SCHEMA, stdin_text=book)
    c = calls[0]
    assert G.REQUEST in c["cmd"][2] and len(c["cmd"][2]) < 500
    assert "Check this book." in c["file"] and book.strip() in c["file"]


def test_chat_reads_its_folder_and_resumes(agy, tmp_path):
    calls, reply = agy
    reply["out"] = env(structured_output={"answer": "two"})
    folder = tmp_path / "chat"
    folder.mkdir()
    G.ask("How many?", SCHEMA, session="c0", folder=str(folder))
    c = calls[0]
    assert c["cwd"] == str(folder) and c["cmd"][-2:] == ["--conversation", "c0"]
    assert not (folder / G.REQUEST).exists()      # tidied up


@pytest.mark.parametrize("out, err, words", [
    ("", "Error: not authenticated. Please sign in.", "isn't signed in"),
    (json.dumps({"status": "ERROR", "error": "429 RESOURCE_EXHAUSTED quota"}), "", "limit"),
    ("", "", "gave no answer"),
    (json.dumps({"status": "WAITING", "response": ""}), "", "permission"),
    (json.dumps({"status": "SUCCESS", "response": "I can't do that."}), "", "couldn't answer"),
])
def test_failures_in_plain_words(agy, out, err, words):
    _, reply = agy
    reply.update(out=out, err=err, code=1 if err else 0)
    with pytest.raises(G.GeminiError, match=words):
        G.ask("Hi", SCHEMA)


def test_run_goes_through_gemini(agy, monkeypatch):
    _, reply = agy
    reply["out"] = env(structured_output={"answer": "via run"})
    monkeypatch.setattr(cc, "PROVIDER", "gemini")
    res = cc.run("Hi", "System.", schema=SCHEMA)
    assert res == {"data": {"answer": "via run"}, "session_id": "c1"}
    assert cc.name() == "Gemini"


def test_run_turns_gemini_errors_into_claude_errors(agy, monkeypatch):
    _, reply = agy
    reply["out"] = ""
    monkeypatch.setattr(cc, "PROVIDER", "gemini")
    with pytest.raises(cc.ClaudeError, match="Gemini gave no answer"):
        cc.run("Hi", "System.", schema=SCHEMA)


def test_status_when_missing(monkeypatch):
    monkeypatch.setattr(G, "find", lambda: None)
    assert cc.status("gemini") == "missing"
