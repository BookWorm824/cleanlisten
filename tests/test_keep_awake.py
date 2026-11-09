"""The PC doesn't go to sleep while a book is worked on (the owner, 2026-11-09: a CleanRead
book left overnight paused for nine hours while Windows slept)."""
import ast
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import freezes  # noqa: E402

ON = freezes.ES_CONTINUOUS | freezes.ES_SYSTEM_REQUIRED
OFF = freezes.ES_CONTINUOUS


@pytest.fixture
def asked(monkeypatch):
    calls = []
    monkeypatch.setattr(freezes, "_set_state",
                        lambda flags: calls.append((flags, threading.current_thread().name)) or 1)
    return calls


def wait_for(calls, n):
    end = time.time() + 3
    while len(calls) < n and time.time() < end:
        time.sleep(0.01)
    time.sleep(0.05)      # and nothing more comes
    return [f for f, _ in calls]


def test_awake_while_working_and_back_to_normal_after(asked):
    with freezes.awake():
        assert wait_for(asked, 1) == [ON]
    assert wait_for(asked, 2) == [ON, OFF]


def test_two_jobs_at_once_stay_awake_until_both_end(asked):
    a, b = freezes.awake(), freezes.awake()
    a.__enter__()
    b.__enter__()
    assert wait_for(asked, 1) == [ON]
    a.__exit__(None, None, None)
    assert wait_for(asked, 1) == [ON]          # one is still going
    b.__exit__(None, None, None)
    assert wait_for(asked, 2) == [ON, OFF]


def test_an_error_still_lets_the_pc_sleep_again(asked):
    with pytest.raises(ValueError):
        with freezes.awake():
            assert wait_for(asked, 1) == [ON]
            raise ValueError("boom")
    assert wait_for(asked, 2) == [ON, OFF]


def test_one_thread_asks_windows(asked):
    # Windows ties the request to the thread that makes it, so it must be the keeper
    def job():
        with freezes.awake():
            wait_for(asked, 1)
    t = threading.Thread(target=job)
    t.start()
    t.join()
    wait_for(asked, 2)
    assert {name for _, name in asked} == {"keep the PC awake"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_accepts_the_request():
    assert freezes._set_state(OFF) != 0


def _awake_wraps(path, func):
    tree = ast.parse(path.read_text(encoding="utf8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return any(isinstance(n, ast.With) and "awake" in ast.unparse(n.items[0].context_expr)
                       for n in node.body) or "freezes.awake()" in ast.unparse(node)
    raise AssertionError(f"{func} not found in {path.name}")


@pytest.mark.parametrize("path, func", [
    ("CleanRead.pyw", "_scan_thread"), ("CleanRead.pyw", "_analyze_thread"),
    ("CleanRead.pyw", "_write_thread"), ("bookrunner.py", "main"),
])
def test_the_long_jobs_keep_the_pc_awake(path, func):
    assert _awake_wraps(ROOT / path, func)
