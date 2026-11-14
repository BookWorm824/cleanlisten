"""Nothing pops up while the tests run (the owner, 2026-11-13, to every chat working on her PC: "can
you keep everything from keep popping up while you are making changes? only fully pop when absolutely
necessary"). The set-up is in conftest.py."""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

import pytest

import conftest


def test_windows_are_see_through_but_still_there():
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no screen to draw on ({ex})")
    try:
        top = tk.Toplevel(r)
        r.update()
        assert float(r.attributes("-alpha")) == 0.0 and float(top.attributes("-alpha")) == 0.0
        assert r.winfo_ismapped() and r.winfo_width() > 1          # still drawn and measured
    finally:
        r.destroy()


def test_boxes_answer_quietly():
    n = len(conftest.BOXES)
    assert messagebox.showinfo("CleanListen", "Saved.") == "ok"
    assert messagebox.askyesno("CleanListen", "Send it in now?") is False
    assert conftest.BOXES[n:] == [("showinfo", "CleanListen", "Saved."),
                                  ("askyesno", "CleanListen", "Send it in now?")]


@pytest.mark.skipif(not hasattr(os, "startfile"), reason="Windows")
def test_files_and_folders_arent_opened(tmp_path):
    n = len(conftest.OPENED)
    os.startfile(str(tmp_path / "CleanListen report.txt"))
    p = subprocess.Popen(f'explorer /select,"{tmp_path}"')
    p.wait()
    q = subprocess.Popen(["notepad", str(tmp_path / "x.txt")])
    q.wait()
    assert len(conftest.OPENED) == n + 3 and conftest.OPENED[n].endswith("report.txt")
    # everything else still runs
    out = subprocess.run([sys.executable, "-c", "print('hi')"], capture_output=True, text=True)
    assert out.stdout.strip() == "hi"


def test_code_run_in_another_python_is_see_through_too():
    code = conftest.HIDE + "\nimport tkinter as tk\ntry:\n    r = tk.Tk()\nexcept tk.TclError:\n" \
        "    print('skip')\nelse:\n    r.update(); print(r.attributes('-alpha')); r.destroy()\n"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    if out.stdout.strip() == "skip":
        pytest.skip("no screen to draw on")
    assert float(out.stdout.strip()) == 0.0
