"""As CleanView 1.18.84 and 1.18.85 (the owner, 2026-11-13: asked whether to bring them to the book
apps, "all"):
- the language choice is a rounded drop-down list ("as we get more languages, instead of labelling
  them all on the front page, should we have a a drop down", "yes round them");
- the "... was updated to version ..." line goes away after 3 seconds ("it leaves a long bar on the
  top it should go away after 3 seconds");
- an answer's words wrap to the room its box has ("the box that opens on the response is clipping
  off on both left and right. i cant see the full response")."""
import time
import tkinter as tk
from tkinter import ttk

import pytest

import cllook as CL
import cvlang
from conftest import REPO


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no screen to draw on ({ex})")
    r.withdraw()
    CL.use_theme("light")
    CL.style(r, ttk.Style(r))
    yield r
    r.destroy()


def pump(root, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def test_the_drop_down_shows_names_and_keeps_the_code(root):
    picked = []
    var = tk.StringVar(root, value="en")
    box = CL.dropdown(root, var, cvlang.LANGS, command=lambda: picked.append(var.get()))
    box.pack()
    root.update()
    assert str(box.cget("style")) == "Round.TCombobox" and str(box.cget("state")) == "readonly"
    assert list(box.cget("values")) == list(cvlang.LANGS.values())
    assert box.get() == "English"
    box.set("Spanish")                              # she picks Spanish from the list
    box.event_generate("<<ComboboxSelected>>")
    root.update()
    assert var.get() == "es" and picked == ["es"]
    var.set("fr")                                   # set from the book: the list follows
    root.update()
    assert box.get() == "French" and picked == ["es"]
    var.set("xx")                                   # something unknown shows the first choice
    root.update()
    assert box.get() == "English"


def test_scrolling_past_the_drop_down_doesnt_change_it(root):
    var = tk.StringVar(root, value="es")
    box = CL.dropdown(root, var, cvlang.LANGS)
    box.pack()
    root.deiconify()
    root.update()
    box.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    box.event_generate("<MouseWheel>", delta=120, x=5, y=5)
    root.update()
    assert var.get() == "es" and box.get() == "Spanish"


def test_a_note_is_said_briefly_then_gone(root):
    assert CL.UPDATED_SHOWN_SECS == 3
    note = CL.said_briefly(tk.Label(root, text="CleanListen was updated to version 1.17.32."),
                           secs=0.15)
    note.pack()
    root.update()
    assert note.winfo_exists()
    pump(root, 0.5)
    assert not note.winfo_exists()
    gone = CL.said_briefly(tk.Label(root, text="x"), secs=0.1)
    gone.destroy()                                  # the page was left first: nothing to do
    pump(root, 0.3)


def test_words_wrap_to_the_room_their_box_has(root):
    root.deiconify()
    box = tk.Frame(root, width=300, height=80)
    box.pack_propagate(False)
    box.pack()
    said = tk.Label(box, text="word " * 60, wraplength=680, justify="left")
    said.pack(anchor="w")
    CL.fit_text(said, box, margin=20)
    pump(root, 0.3)
    assert int(str(said.cget("wraplength"))) == 280            # it was 680: off both sides
    box.config(width=420)
    pump(root, 0.3)
    assert int(str(said.cget("wraplength"))) == 400            # and again when the room changes


@pytest.mark.parametrize("app", ["CleanListen.pyw", "CleanRead.pyw"])
def test_both_apps_use_them(app):
    src = (REPO / app).read_text(encoding="utf8")
    assert "self.language_box = CL.dropdown(b, self.lang_var," in src
    assert "look.Segmented(b, list(engine" not in src
    assert src.count("CL.said_briefly(tk.Label(") == (2 if app == "CleanListen.pyw" else 1)


def test_cleanlistens_answer_tip_and_status_fit_their_box():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert "CL.fit_text(said, said, margin=20)" in src
    assert "CL.fit_text(tip, box, margin=20)" in src and "CL.fit_text(status, box, margin=20)" in src
