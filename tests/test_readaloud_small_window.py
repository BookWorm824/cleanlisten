"""The first page's buttons aren't cut off in a small window (the owner's screenshot of CleanListen,
2026-11-20: "Choose fo" cut off, "ok when maximized but not when smaller"): the words beside them
are squeezed instead."""
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


def _pills(widget, found):
    for w in widget.winfo_children():
        if w.__class__.__name__ == "Pill":
            found.append(w)
        _pills(w, found)
    return found


def test_choose_ebook_and_convert_stay_whole_when_the_window_is_small(window):
    win, app = window
    app.minsize(1, 1)
    app.steps_page.go(1)
    for width in (1100, 760, 640):
        app.geometry(f"{width}x700")
        _pump(app, 0.5)
        pills = {p.text if hasattr(p, "text") else "": p for p in _pills(app.page, [])}
        shown = [p for p in _pills(app.page, []) if p.winfo_ismapped()]
        assert len(shown) >= 2, pills
        for p in shown:
            assert p.winfo_width() >= p.winfo_reqwidth() - 1, (width, p.winfo_width(), p.winfo_reqwidth())
