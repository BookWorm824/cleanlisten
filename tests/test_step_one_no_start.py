"""No Start cleaning on step 1: Next leads on to the choices, green (as CleanView 1.18.135; the owner,
2026-11-18: "get rid of the green start cleaning button on page 1, by doing that it leads to page 2
the the tick menus are", "keep the button on 2 and others"). ReadAloud's "Make audiobook" isn't a
Start cleaning and stays on step 1."""
import tkinter as tk
from pathlib import Path

import pytest

import cllook as CL

ROOT = Path(__file__).resolve().parent.parent
STEPS = [("Audiobook", "a"), ("What to remove", "b"), ("Where to save", "c")]


@pytest.fixture
def root():
    r = tk.Tk()
    yield r
    r.destroy()


def page(root, **kw):
    sp = CL.StepPage(root, tk.Frame(root), "CleanListen", None, STEPS, lambda n: "",
                     ("Start cleaning", lambda: None), **kw)
    return sp


def shown(btn):
    return btn.winfo_manager() == "pack"


def test_step_one_leads_on_to_the_ticks(root):
    sp = page(root)
    sp.go(1)
    assert not shown(sp.main_btn)
    assert shown(sp.next_btn) and sp.next_btn._kind == "primary"
    assert sp.next_btn._text == "Next: What to remove"
    sp.go(2)
    assert shown(sp.main_btn) and shown(sp.next_btn) and sp.next_btn._kind == "secondary"
    assert shown(sp.back_btn)
    sp.go(3)
    assert shown(sp.main_btn) and not shown(sp.next_btn)
    sp.go(1)                                      # back to step 1: gone again
    assert not shown(sp.main_btn) and sp.next_btn._kind == "primary"


def test_readaloud_keeps_its_button_on_step_one(root):
    sp = page(root, main_on_first=True)
    sp.go(1)
    assert shown(sp.main_btn) and shown(sp.next_btn) and sp.next_btn._kind == "secondary"


def test_which_apps():
    for app in ("CleanListen.pyw", "CleanRead.pyw"):
        assert "main_on_first" not in (ROOT / app).read_text(encoding="utf8"), app
    assert "main_on_first=True" in (ROOT / "ReadAloud.pyw").read_text(encoding="utf8")


def test_cleanread_starts_on_the_ticks(root):
    """CleanRead: no Start cleaning on step 2 either ("What to do"): Next leads to the ticks on 3 (the
    owner, 2026-11-20: "the start cleaning on section 2 should be removed. 2 leads to 3 to show them
    what to tick")."""
    steps = [("Ebook", "a"), ("What to do", "b"), ("What to take out", "c"), ("Options", "d")]
    sp = CL.StepPage(root, tk.Frame(root), "CleanRead", None, steps, lambda n: "",
                     ("Start cleaning", lambda: None), main_from=3)
    for n in (1, 2):
        sp.go(n)
        assert not shown(sp.main_btn) and sp.next_btn._kind == "primary", n
    sp.go(2)
    assert sp.next_btn._text == "Next: What to take out"
    sp.go(3)
    assert shown(sp.main_btn) and sp.next_btn._kind == "secondary"
    assert "main_from=3" in (ROOT / "CleanRead.pyw").read_text(encoding="utf8")
    assert "main_from" not in (ROOT / "CleanListen.pyw").read_text(encoding="utf8")
