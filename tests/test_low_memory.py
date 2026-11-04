"""Windows running low on memory ("[WinError 1455] The paging file is too small", saving a
4.5-hour book on a smaller PC, 2026-11-04)."""
import pytest

import cleanlisten as E


def _low_memory(code=1455):
    ex = OSError("The paging file is too small for this operation to complete")
    ex.winerror = code
    return ex


@pytest.fixture
def no_wait(monkeypatch):
    waits = []
    monkeypatch.setattr(E.time, "sleep", waits.append)
    return waits


def test_starting_ffmpeg_waits_and_tries_again(monkeypatch, no_wait):
    tries = []

    def start(cmd, **kw):
        tries.append(cmd)
        if len(tries) < 3:
            raise _low_memory()
        return "started"
    monkeypatch.setattr(E.subprocess, "run", start)
    assert E.run(["ffmpeg"]) == "started"
    assert len(tries) == 3 and no_wait == [5, 15]


def test_gives_up_after_a_few_tries(monkeypatch, no_wait):
    def start(cmd, **kw):
        raise _low_memory(1450)
    monkeypatch.setattr(E.subprocess, "Popen", start)
    with pytest.raises(OSError):
        E.popen(["ffmpeg"])
    assert no_wait == list(E.LOW_MEMORY_WAITS)


def test_other_problems_are_not_retried(monkeypatch, no_wait):
    def start(cmd, **kw):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(E.subprocess, "run", start)
    with pytest.raises(FileNotFoundError):
        E.run(["ffmpeg"])
    assert no_wait == []


def test_the_ai_helper_lets_go_of_its_model(monkeypatch):
    calls = []

    class Reply:
        def close(self):
            calls.append("closed")

    class FakeAI:
        MODEL = "gemma3:4b"

        @staticmethod
        def _api(path, payload=None, timeout=10):
            calls.append((path, payload))
            return Reply()
    monkeypatch.setattr(E, "_ai_module", lambda: FakeAI)
    E.free_ai_memory()
    assert calls == [("/api/generate", {"model": "gemma3:4b", "keep_alive": 0}), "closed"]

    def broken(*a, **k):
        raise OSError("Ollama isn't running")
    monkeypatch.setattr(FakeAI, "_api", staticmethod(broken))
    E.free_ai_memory()                       # never a problem of its own
