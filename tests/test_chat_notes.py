"""The chat can learn (CleanView 1.18.1, Jason): rules they give it are kept and followed later."""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanlisten_gpt as gpt
import cleanlisten_learn as L


@pytest.fixture
def learned(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    monkeypatch.setattr(L, "APP_DATA", tmp_path)
    monkeypatch.setattr(L, "_shared", {"cut": [], "kept": [], "ok_words": [], "word_mutes": [],
                                       "cut_for": {}})


def test_notes_for_this_book_stay_with_it(learned):
    assert L.add_note("The Genie's magic is fine.", "Aladdin")
    assert L.add_note("Never mute 'gosh'.", "Aladdin", everywhere=True)
    assert L.notes("Aladdin") == ["The Genie's magic is fine.", "Never mute 'gosh'."]
    assert L.notes("Peter Pan") == ["Never mute 'gosh'."]


def test_the_same_note_is_kept_once_and_only_the_last_40(learned):
    assert L.add_note("Fighting is fine.", "Book")
    assert not L.add_note("  fighting is   FINE. ", "Book")
    for n in range(50):
        L.add_note(f"Rule {n}", everywhere=True)
    assert len(L.load()["notes"]) == L.MAX_NOTES
    assert L.notes()[-1] == "Rule 49"


def test_the_ai_readers_get_the_notes_first(learned):
    assert L.examples_text("Book") == ""
    L.add_note("Fighting is fine in this series.", "Book")
    L.record({"scenes": [{"kind": "religion", "cut": True,
                          "text": "The minister preached about heaven for an hour."}]})
    t = L.examples_text("Book")
    assert t.index("keep this in mind") < t.index("past choices")
    assert "Fighting is fine in this series." in t
    assert "Fighting is fine" not in L.examples_text("Other book")
    assert "Fighting is fine in this series." in E._learned_examples("Book")


class _Chat(cc.Chat):
    def __init__(self, st):          # no book files needed for this
        self.st, self.asr, self.session, self.dir = st, [], None, None

    def _write_findings(self):
        pass


def test_the_chat_keeps_what_it_is_told_and_is_reminded_of_it(learned, monkeypatch):
    sent = []

    def run(prompt, system, schema=None, **kw):
        sent.append(prompt)
        return {"session_id": "s1", "data": {"answer": "Got it.", "changes": [], "remember": [
            {"note": "It's Aladdin: the Genie's magic is fine.", "for": "this"},
            {"note": "Never mute 'gosh'.", "for": "everything"}, {"note": " ", "for": "this"}]}}
    monkeypatch.setattr(cc, "run", run)
    monkeypatch.setattr(cc, "rules_text", lambda st: "")
    chat = _Chat({"title": "Aladdin", "filters": {}})
    ans, changes, kept = chat.ask("It's Aladdin, the magic is different.")
    assert (ans, changes) == ("Got it.", [])
    assert kept == [("It's Aladdin: the Genie's magic is fine.", False), ("Never mute 'gosh'.", True)]
    assert L.notes("Aladdin") == ["It's Aladdin: the Genie's magic is fine.", "Never mute 'gosh'."]
    chat.ask("Thanks.")
    assert "keep this in mind" not in sent[0] and "the Genie's magic is fine" in sent[1]
    assert chat.ask("Again.")[2] == []        # already kept: not announced twice


def test_the_chat_schema_works_for_chatgpt_too():
    assert "remember" in cc.CHAT_SCHEMA["required"]
    item = gpt.strict(cc.CHAT_SCHEMA)["properties"]["remember"]["items"]
    assert item["required"] == ["note", "for"] and item["additionalProperties"] is False
    assert "you CAN learn" in cc.SYSTEM_CHAT
