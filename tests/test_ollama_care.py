"""Ollama only while CleanView, CleanListen or CleanRead are open (Lauren, 2026-11-05). The real
Ollama on this PC is never stopped here: stop() is a stand-in."""
import os
import subprocess
import sys
import time

import pytest

import ollama_care as O


def test_taken_out_of_windows_startup(tmp_path):
    link = tmp_path / "Ollama.lnk"
    link.write_bytes(b"x")
    assert O.autostart_off(link) is True and not link.exists()
    assert O.autostart_off(link) is False            # already gone: nothing to do


@pytest.fixture
def ollama(monkeypatch):
    state = {"running": True, "others": set(), "models": [[]], "stopped": 0, "slept": 0}
    monkeypatch.setattr(O, "running", lambda: state["running"])
    monkeypatch.setattr(O, "other_apps", lambda skip=(): state["others"])
    monkeypatch.setattr(O, "loaded_models",
                        lambda: state["models"].pop(0) if len(state["models"]) > 1
                        else state["models"][0])
    monkeypatch.setattr(O, "stop", lambda: state.__setitem__("stopped", state["stopped"] + 1))

    def sleep(s):
        state["slept"] += s
    monkeypatch.setattr(O.time, "sleep", sleep)
    return state


def test_stopped_when_nothing_uses_it(ollama):
    assert O.stop_when_idle() == "stopped" and ollama["stopped"] == 1


def test_left_running_while_another_app_is_open(ollama):
    ollama["others"] = {1234}
    assert O.stop_when_idle() == "in use" and ollama["stopped"] == 0
    ollama["others"] = None                          # Windows couldn't say: leave it
    assert O.stop_when_idle() == "in use" and ollama["stopped"] == 0


def test_waits_for_the_model_to_be_let_go_of(ollama):
    ollama["models"] = [[{"name": "gemma3:4b"}], [{"name": "gemma3:4b"}], []]
    assert O.stop_when_idle(every=15) == "stopped" and ollama["stopped"] == 1
    assert ollama["slept"] >= 30


def test_a_model_kept_loaded_by_something_else_is_left_alone(ollama, monkeypatch):
    ollama["models"] = [[{"name": "llama3"}]]
    clock = iter(range(0, 10_000, 60))
    monkeypatch.setattr(O.time, "time", lambda: next(clock))
    assert O.stop_when_idle(most=420) == "busy" and ollama["stopped"] == 0


def test_not_running_is_nothing_to_do(ollama):
    ollama["running"] = False
    assert O.stop_when_idle() == "not running" and ollama["stopped"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows processes")
def test_finds_a_running_book_worker():
    # a stand-in "book worker": its command line names bookrunner.py
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                          r"C:\x\bookrunner.py"], creationflags=0x08000000)
    try:
        time.sleep(0.5)
        found = O.other_apps()
        assert found is not None and p.pid in found
        assert p.pid not in O.other_apps(skip=[p.pid])
    finally:
        p.kill()


def test_closing_hands_it_to_a_small_program(monkeypatch):
    got = []
    monkeypatch.setattr(O, "installed", lambda: True)
    monkeypatch.setattr(O.os, "name", "nt")
    monkeypatch.setattr(O.subprocess, "Popen", lambda cmd, **kw: got.append((cmd, kw)))
    O.stop_later()
    (cmd, kw), = got
    assert cmd[0] == sys.executable and cmd[1] == "-c"
    compile(cmd[2], "helper", "exec")
    assert "stop_when_idle(skip=[%d])" % os.getpid() in cmd[2]
    # its own command line isn't mistaken for one of the apps
    import re
    assert not re.search(O.CLEAN_APPS, " ".join(cmd))
