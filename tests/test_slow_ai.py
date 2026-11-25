"""When the AI doesn't answer (Riley + Sam, a 10-hour book, 2026-11-25: "ChatGPT took too long to
answer" after hours, on every section): a section that gets no answer is split in two and tried
once more; if a half gets none either, or ChatGPT never starts, the check stops there and says so.
ChatGPT's own messages go in a short log, so the reason can be seen."""
import json
import subprocess
import sys

import pytest

import cleanlisten_claude as cc
import cleanlisten_gpt as G

SLOW = "ChatGPT took too long to answer. Try again."
DEAD = G.NOT_STARTED
OK = {"data": {"decisions": [], "missed_passages": [], "missed_words": []}}


def book(n_sents):
    asr, sents = [], []
    for k in range(n_sents):
        i = len(asr)
        for w in ("One", "two", "three."):
            asr.append({"t": w, "s": len(asr) * 1.0, "e": len(asr) * 1.0 + 0.5, "part": 0})
        sents.append((i, i + 2))
    return asr, {"sentences": sents, "scenes": [], "mutes": [], "filters": {}}


@pytest.fixture
def fake(monkeypatch):
    calls = []
    monkeypatch.setattr(cc, "status", lambda *a: "ok")
    monkeypatch.setattr(cc, "RETRY_WAIT", 0)
    monkeypatch.setattr(cc, "_sections", lambda texts: [(0, 39), (40, 79)])

    def use(answer):
        def run(prompt, system, schema=None, **kw):
            calls.append((prompt.split(" (sentences")[0].replace("BOOK TEXT - ", ""), kw.get("timeout")))
            a = answer(prompt)
            if isinstance(a, str):
                raise cc.ClaudeError(a)
            return OK
        monkeypatch.setattr(cc, "run", run)
        return calls
    return use


def test_a_slow_section_is_split_in_two(fake):
    calls = fake(lambda p: SLOW if "section 1 of" in p else OK)
    asr, st = book(80)
    cc.review(st, asr)
    assert [c[0] for c in calls] == ["section 1 of 2", "section 1 (first half) of 2",
                                     "section 1 (second half) of 2", "section 2 of 2"]
    assert calls[1][1] == calls[2][1] == cc.HALF_TIMEOUT          # a shorter wait for each half
    assert "couldn't be checked" not in st["claude_note"] and not st["claude_unchecked"]


def test_a_half_that_is_slow_too_stops_the_check(fake):
    calls = fake(lambda p: SLOW if "section 2" in p else OK)
    asr, st = book(80)
    cc.review(st, asr)
    assert [c[0] for c in calls] == ["section 1 of 2", "section 2 of 2", "section 2 (first half) of 2"]
    assert "About 50% of the book couldn't be checked" in st["claude_note"]
    assert st["claude_unchecked"]


def test_nothing_read_is_a_failed_check_without_hours_of_waiting(fake):
    calls = fake(lambda p: SLOW)
    asr, st = book(80)
    with pytest.raises(cc.ClaudeError, match="took too long"):
        cc.review(st, asr)
    assert len(calls) == 2              # section 1, its first half: not every section twice


def test_chatgpt_that_never_starts_stops_at_once(fake):
    calls = fake(lambda p: DEAD)
    asr, st = book(80)
    with pytest.raises(cc.ClaudeError, match="didn't start"):
        cc.review(st, asr)
    assert len(calls) == 1


def test_other_failures_are_still_tried_again(fake):
    calls = fake(lambda p: "Claude Code stopped without an answer." if len(calls) < 2 else OK)
    asr, st = book(80)
    cc.review(st, asr)
    assert [c[0] for c in calls] == ["section 1 of 2", "section 1 of 2", "section 2 of 2"]


# --- ChatGPT itself (a stand-in for Codex that hangs) ----------------------------------------

HANG = """import sys, time
sys.stdin.read()
if sys.argv[1] == "started":
    print('{"type": "thread.started", "thread_id": "t1"}', flush=True)
    print('{"type": "turn.started"}', flush=True)
time.sleep(60)
"""


@pytest.fixture
def codex(monkeypatch, tmp_path):
    script = tmp_path / "codex_hangs.py"
    script.write_text(HANG)
    monkeypatch.setattr(G, "APP_DATA", tmp_path / "app")
    monkeypatch.setattr(G, "LOG", tmp_path / "app" / "chatgpt" / "chatgpt_log.txt")
    monkeypatch.setattr(G, "find", lambda: "codex")
    real = subprocess.Popen

    def use(how):
        def popen(cmd, **kw):
            if cmd[0] != "codex":           # (taskkill, which stops it)
                return real(cmd, **kw)
            return real([sys.executable, str(script), how], **kw)
        monkeypatch.setattr(G.subprocess, "Popen", popen)
    return use


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def test_codex_that_never_starts(codex):
    codex("silent")
    with pytest.raises(G.GptError, match="didn't start on this PC"):
        G.ask("Say hi.", SCHEMA, timeout=3)
    log = G.LOG.read_text("utf8")
    assert "TIMED OUT" in log and "messages: (none)" in log and "Say hi" not in log


def test_codex_that_starts_but_never_answers(codex):
    codex("started")
    with pytest.raises(G.GptError, match="took too long"):
        G.ask("Say hi.", SCHEMA, timeout=3)
    assert "messages: thread.started > turn.started" in G.LOG.read_text("utf8")


def test_the_log_stays_short(codex, monkeypatch):
    G.LOG.parent.mkdir(parents=True)
    G.LOG.write_text("x" * 300000)
    G._log(["codex", "exec"], 0, 0, json.dumps({"type": "turn.completed"}), "", 10)
    assert len(G.LOG.read_text("utf8")) < 201000


def test_codex_that_never_starts_is_stopped_after_two_minutes_not_the_whole_wait(codex, monkeypatch):
    import time
    codex("silent")
    monkeypatch.setattr(G, "START_WAIT", 1)
    t = time.time()
    with pytest.raises(G.GptError, match="didn't start on this PC"):
        G.ask("Say hi.", SCHEMA, timeout=60)
    assert time.time() - t < 20


def test_a_started_codex_is_not_stopped_early(codex, monkeypatch):
    codex("started")
    monkeypatch.setattr(G, "START_WAIT", 1)
    with pytest.raises(G.GptError, match="took too long"):
        G.ask("Say hi.", SCHEMA, timeout=4)
    assert "· 4 s ·" in G.LOG.read_text("utf8") or "· 5 s ·" in G.LOG.read_text("utf8")
