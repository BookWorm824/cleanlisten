"""CleanRead (Jason, 2026-11-03: "Can it have the ask claude under each line"): the "Ask Claude"
link beside a finding, heading, cut or word opens the chat about that one, so only the question
is typed, and the chat is told which one it is."""
import importlib.machinery
import importlib.util
import types

import pytest

import cleanlisten_learn as L
import cleanread as R
from conftest import REPO

BOOK = """Chapter One

The witch cast a spell on the old oak tree and stirred her potion.

The witch flew away on her broomstick under the full moon.

"What the hell is going on?" asked Dad.
"""


@pytest.fixture
def ui():
    loader = importlib.machinery.SourceFileLoader("cr_ask_ui", str(REPO / "CleanRead.pyw"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def fake(chat):
    said = []
    return types.SimpleNamespace(chat=chat, _chat_say=lambda who, t: said.append(t), said=said,
                                 chat_entry=types.SimpleNamespace(focus_set=lambda: None))


def test_asking_about_one_finding_or_a_heading(ui, book, tmp_path):
    r = R.scan(book)
    chat = R.CheckChat(book, r, tmp_path / "chat")
    kind, label, it = chat.items[1]
    c = next(c for c in r["cats"].values() if any(x is it for x in c["items"]))
    app = fake(chat)
    ui.App._ask_about(app, ("finding", c, it))
    assert app._chat_about.startswith("this finding on my list (F2), under “") and "broomstick" in app._chat_about
    assert "Your next message is about" in app.said[-1]
    ui.App._ask_about(app, ("heading", c))
    assert "(F1, F2)" in app._chat_about and c["label"] in app.said[-1]


def test_asking_about_one_cut_or_word(ui, book, tmp_path):
    an = R.analyze(book, {"magic": True, "darkmagic": True, "mild": True})
    chat = R.Chat(book, an, tmp_path / "chat")
    app = fake(chat)
    c, m = an["cuts"][0], an["mutes"][0]
    ui.App._ask_about(app, ("cut", c))
    assert app._chat_about.startswith(f"this cut on my list (C{c['id']})")
    ui.App._ask_about(app, ("word", m))
    assert app._chat_about.startswith(f"this marked-out word on my list (W{m['id']})")
    assert "hell" not in app.said[-1]                     # starred out on screen


def test_each_line_has_its_ask_link():
    src = (REPO / "CleanRead.pyw").read_text(encoding="utf8")
    for about in ('("finding", c, it)', '("heading", c)', '("cut", c)', '("word", m)'):
        assert about in src
