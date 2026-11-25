"""Each app's logo on every window and its taskbar button, never Tk's feather (the owner,
2026-11-25, of ReadAloud: "it has the same problem with the logo in start bar turning into a
feather, it needs the correct logo"; CleanView's set_icon, 2026-11-13)."""
import tkinter as tk

import pytest

import logo
from conftest import REPO


@pytest.mark.parametrize("app,ico", [("ReadAloud.pyw", "readaloud.ico"), ("CleanRead.pyw", "cleanread.ico"),
                                     ("CleanListen.pyw", "icon.ico")])
def test_each_app_sets_its_logo_for_every_window(app, ico):
    src = (REPO / app).read_text(encoding="utf8")
    init = src[src.index("class App(tk.Tk):"):]
    assert f'LOGO.set_icon(self, "{ico}")' in init[:init.index("self.q = queue.Queue()")]


class FakeWin:
    def __init__(self, fail=False):
        self.calls, self.later, self.fail = [], [], fail

    def winfo_exists(self):
        return True

    def iconbitmap(self, path=None, default=None):
        if self.fail:
            raise tk.TclError("bitmap not defined")
        self.calls.append(("default", default) if default else ("own", path))

    def after(self, ms, fn):
        self.later.append((ms, fn))


def test_the_logo_is_every_windows_default_and_is_set_again_once_up():
    win = FakeWin()
    assert logo.set_icon(win, "readaloud.ico") is True
    path = str(logo.HERE / "readaloud.ico")
    assert win.calls == [("default", path), ("own", path)]     # the default first: no feather anywhere
    assert [ms for ms, _ in win.later] == [500, 3000]
    for _, fn in win.later:
        fn()
    assert len(win.calls) == 6


def test_set_icon_copes_when_it_cant_be_set():
    assert logo.set_icon(FakeWin(fail=True), "readaloud.ico") is False
