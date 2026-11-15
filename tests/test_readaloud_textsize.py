"""ReadAloud's text size, as CleanView's (the owner, 2026-11-14: "you need the text menu like clean
view"): "Text size: Normal" under the steps opens Normal / Larger / Largest, and the page is built
again at once at that size, keeping the book, the ticks and the step. One choice for CleanListen,
CleanRead and ReadAloud, kept with light / dark (filters.json)."""
import importlib.util

import pytest

from conftest import REPO
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


@pytest.fixture
def no_popup(monkeypatch):
    import tkinter as tk
    shown = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y, entry="": shown.append(self))
    return shown


def _labels(menu):
    return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]


def test_the_link_and_the_menu(window, no_popup):
    win, app = window
    assert list(win.F.TEXT_SIZES) == ["Normal", "Larger", "Largest"]
    assert app.text_size == "Normal" and "Text size: Normal" in app.steps_page.links
    app._text_size_menu()
    assert len(no_popup) == 1
    assert _labels(no_popup[0]) == ["✓ Normal", "    Larger", "    Largest"]


def test_larger_is_bigger_at_once_and_keeps_everything(window, no_popup, tmp_path):
    win, app = window
    from test_readaloud import STORY, make_epub
    b = win.engine.load_book(make_epub(tmp_path / "book.epub", STORY))
    app.q.put(("book", str(tmp_path / "book.epub"), b, None))
    _pump(app, 0.5)
    app.steps_page.go(4)
    app.chapter_vars[1].set(False)
    app.series_var.set("My series")
    before = app.winfo_fpixels("1p"), app.steps_page.title.winfo_reqheight(), app.winfo_width()
    app._text_size_menu()
    no_popup[-1].invoke(1)                          # "Larger"
    _pump(app)
    after = app.winfo_fpixels("1p"), app.steps_page.title.winfo_reqheight(), app.winfo_width()
    assert after[0] == pytest.approx(before[0] * 1.15, rel=0.01)
    assert after[1] > before[1] and after[2] >= before[2]
    assert app.text_size == "Larger" and "Text size: Larger" in app.steps_page.links
    assert app.steps_page.now == 4 and app.book is b
    assert [v.get() for v in app.chapter_vars] == [False, False, True]
    assert app.series_var.get() == "My series"
    assert win.F.load()["text_size"] == "Larger"
    app._text_size_menu()
    assert _labels(no_popup[-1]) == ["    Normal", "✓ Larger", "    Largest"]
    app._set_text_size("Normal")
    assert app.winfo_fpixels("1p") == pytest.approx(before[0])


def test_largest_still_fits_the_buttons(window, tmp_path):
    # the Next and Make audiobook buttons and every step's words still show at Largest
    win, app = window
    app._set_text_size("Largest")
    for n in range(1, 6):
        app.steps_page.go(n)
        _pump(app, 0.2)
        nav = app.steps_page.nav
        for btn in (app.steps_page.main_btn, app.steps_page.next_btn):
            if btn.winfo_ismapped():
                assert btn.winfo_rootx() >= nav.winfo_rootx()
                assert btn.winfo_rootx() + btn.winfo_width() <= nav.winfo_rootx() + nav.winfo_width() + 1


def test_the_next_window_opens_at_the_size_chosen(tmp_path, monkeypatch):
    import filters as F
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    spec = importlib.util.spec_from_file_location("ReadAloudSize", REPO / "ReadAloud.pyw")
    win = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(win)
    monkeypatch.setattr(win, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(win, "APP_DATA", tmp_path)
    monkeypatch.setattr(win.engine, "JOBS", tmp_path / "jobs")
    w = win.freezes.Watch
    monkeypatch.setattr(win.freezes, "Watch", lambda root, app, folder, prefix="": w(root, app, tmp_path, prefix))
    F.save({"text_size": "Largest"})        # chosen in CleanListen or CleanRead
    app = win.App()
    try:
        assert app.text_size == "Largest" and "Text size: Largest" in app.steps_page.links
        assert app.winfo_fpixels("1p") == pytest.approx(app._base_scaling * 1.3, rel=0.01)
    finally:
        app.destroy()
