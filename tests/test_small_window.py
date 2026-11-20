"""CleanListen's first page in a smaller window (the owner, 2026-11-20, with a screenshot of "Choose fo"
cut off and "Choose an audiobook first" pressed against the Next button: "the bar is ok when maximized
but not when smaller, the bottom part needs more space between"). The buttons get their room before
the words beside them (before=words), and the note keeps a gap from Next."""
import re
import tkinter as tk

import pytest

import cllook as CL
import cvlook as look
from conftest import REPO

SRC = (REPO / "CleanListen.pyw").read_text(encoding="utf8")


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no screen to draw on ({ex})")
    yield r
    r.destroy()


def card(root, before):
    row = tk.Frame(root, bg="#FFFFFF")
    row.pack(fill="x")
    words = tk.Frame(row, bg="#FFFFFF")
    words.pack(side="left", fill="x", expand=True)
    tk.Label(words, text="A folder of its files, or the files themselves.", wraplength=200).pack()
    kw = {"before": words} if before else {}
    files = look.Pill(row, "Choose files…", lambda: None, kind="secondary", size=11, pad=(18, 10))
    files.pack(side="right", **kw)
    folder = look.Pill(row, "Choose folder…", lambda: None, size=11, pad=(18, 10))
    folder.pack(side="right", padx=(0, 8), **kw)
    return folder


def narrow(root, folder):
    """Room for both buttons and a little more, not for the words too (whatever the scaling)."""
    files = [w for w in folder.master.pack_slaves() if w is not folder and isinstance(w, look.Pill)][0]
    root.geometry(f"{files.winfo_reqwidth() + folder.winfo_reqwidth() + 40}x200")
    root.update()


def test_the_buttons_keep_their_room(root):
    folder = card(root, before=True)
    narrow(root, folder)
    assert folder.winfo_width() >= folder.winfo_reqwidth()


def test_without_it_the_button_was_cut(root):
    folder = card(root, before=False)
    narrow(root, folder)
    assert folder.winfo_width() < folder.winfo_reqwidth()        # "Choose fo"


def test_every_card_on_the_first_page():
    assert SRC.count("before=words)") == 4      # files, folder, ebook, language


def test_a_gap_before_the_note(root):
    m = re.search(r"self\.start_hint\.pack\(side=\"right\", padx=\(X\((\d+)\), X\(10\)\)\)", SRC)
    assert m and int(m.group(1)) >= 14
    page = tk.Frame(root)
    page.pack(fill="both", expand=True)
    sp = CL.StepPage(root, page, "CleanListen", None, [("Audiobook", "a"), ("What", "b")],
                     lambda n: "", ("Start cleaning", lambda: None))
    note = tk.Label(sp.nav, text="Choose an audiobook first")
    note.pack(side="right", padx=(int(m.group(1)), 10))
    sp.go(1)
    root.geometry("700x400")
    root.update()
    gap = note.winfo_rootx() - (sp.next_btn.winfo_rootx() + sp.next_btn.winfo_width())
    assert gap >= int(m.group(1)) - 1


def test_cleanread_first_page_too():
    src = (REPO / "CleanRead.pyw").read_text(encoding="utf8")
    assert 'self.choose_btn.pack(side="right", before=words)' in src
    assert 'self.language_box.pack(side="right", before=words)' in src
