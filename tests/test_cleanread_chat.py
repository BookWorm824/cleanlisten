"""CleanRead (Jason, 2026-11-03): a long sentence loses only the part with the problem, and you
can tell Claude what's fine - it changes the list and remembers the lesson."""
import pytest

import cleanlisten_claude as cc
import cleanlisten_learn as L
import cleanread as R

BOOK = """Chapter One

After the long drive home through the rain, Tom came in the back door, poured himself a tall glass of whiskey, and sat down at the kitchen table to read the evening paper.

He lit a cigarette.

When the bell rang for the end of the school day, the children ran out into the yard, and Billy punched Sam hard in the stomach before anyone could stop him, which made the teacher very cross.

Mary looked out at the garden, where the roses grew along the old stone wall, and she thought of her grandmother, who had planted them long ago, and who had always smoked a pipe on the porch.

She kissed him passionately, and they stood there in the hallway for a long time without saying anything at all.

"What the hell is going on?" asked Dad.
"""
OPTS = {"drinking": True, "smoking": True, "violence": True, "kiss": "passionate", "mild": True}


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    monkeypatch.setattr(L, "APP_DATA", tmp_path)
    monkeypatch.setattr(L, "_shared", {"cut": [], "kept": [], "ok_words": [], "word_mutes": [],
                                       "cut_for": {}})
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def _cuts(an):
    return {c["kind"]: c for c in an["cuts"]}


def test_a_long_sentence_loses_only_the_part_with_the_problem(book):
    c = _cuts(R.analyze(book, OPTS))
    assert c["drinking"]["text"] == "poured himself a tall glass of whiskey,"
    assert c["violence"]["text"].startswith("and Billy punched Sam")
    assert c["smoking"]["text"] == ", and who had always smoked a pipe on the porch"
    assert c["kiss"]["text"] == "She kissed him passionately, and"
    assert all(x.get("part") for x in c.values())
    assert "Tom came in the back door," in c["drinking"]["before"]


def test_a_short_sentence_is_still_cut_whole(book):
    an = R.analyze(book, {"smoking": True})
    whole = [c for c in an["cuts"] if not c.get("part")]
    assert [c["text"] for c in whole] == ["He lit a cigarette."]


def test_jokes_and_meaning_still_take_the_whole_sentence():
    assert "ref" not in R.PART_KINDS and "crude" not in R.PART_KINDS
    assert "sleeping" not in R.PART_KINDS and "religion" not in R.PART_KINDS


def test_the_clean_copy_reads_well(book, tmp_path):
    an = R.analyze(book, OPTS)
    out = tmp_path / "out.txt"
    res = R.write_clean(book, an["cuts"], an["mutes"], out, marker=True)
    t = out.read_text(encoding="utf8")
    assert "Tom came in the back door, […] and sat down at the kitchen table" in t
    assert "who had planted them long ago […]." in t
    assert "[…] They stood there in the hallway" in t
    assert "whiskey" not in t and "pipe" not in t and "punched" not in t
    assert res["cut_parts"] == 4 and res["cut_sents"] == 1
    R.write_clean(book, an["cuts"], an["mutes"], out, marker=False)
    t = out.read_text(encoding="utf8")
    assert "Tom came in the back door, and sat down" in t
    assert "who had planted them long ago." in t
    assert "\nThey stood there in the hallway" in t


def _chat(book, an, tmp_path, monkeypatch, data):
    asked = []

    def run(prompt, system, schema=None, **kw):
        asked.append((prompt, system))
        return {"session_id": "s1", "data": data}
    monkeypatch.setattr(cc, "run", run)
    monkeypatch.setattr(cc, "saved_provider", lambda: "claude")
    return R.Chat(book, an, tmp_path / "chat"), asked


def test_tell_claude_its_fine_and_it_remembers(book, tmp_path, monkeypatch):
    an = R.analyze(book, OPTS)
    drink = _cuts(an)["drinking"]
    chat, asked = _chat(book, an, tmp_path, monkeypatch, {
        "answer": "I kept the whiskey line.",
        "changes": [{"action": "untick", "id": f"C{drink['id']}"}],
        "remember": [{"note": "A grown-up having a drink at home is fine.", "for": "everything"}]})
    ans, changes, kept = chat.ask("The drinking is fine")
    assert kept == [("A grown-up having a drink at home is fine.", True)]
    assert "Drinking" in asked[0][1] and "findings.txt" in asked[0][1]
    findings = (tmp_path / "chat" / "findings.txt").read_text(encoding="utf8")
    assert f"C{drink['id']} [ticked] drinking · part of a sentence" in findings
    assert "S2: After the long drive" in (tmp_path / "chat" / "book.txt").read_text(encoding="utf8")
    done = chat.apply(changes)
    assert drink["cut"] is False and drink["ai_note"] == "Kept by chat" and done
    # the next chat, and the AI helper, are told
    chat.ask("thanks")
    assert "A grown-up having a drink at home is fine." in asked[1][0]
    assert "A grown-up having a drink" in R.told("Another book")


def test_the_chat_can_cut_less_or_just_the_word(book, tmp_path, monkeypatch):
    an = R.analyze(book, {"smoking": True, "violence": True})
    smoke = next(c for c in an["cuts"] if not c.get("part"))
    hit = _cuts(an)["violence"]
    chat, _ = _chat(book, an, tmp_path, monkeypatch, {})
    chat.apply([{"action": "part", "id": f"C{hit['id']}", "words": "punched Sam hard in the stomach"},
                {"action": "just_the_word", "id": f"C{smoke['id']}", "words": "cigarette", "type": "mild"}])
    assert hit["text"] == "punched Sam hard in the stomach" and hit["cut"]
    assert smoke["cut"] is False
    m = an["mutes"][-1]
    assert m["word_raw"] == "cigarette" and m["note"] == "Added by chat"


def test_the_chat_can_add_what_was_missed(book, tmp_path, monkeypatch):
    an = R.analyze(book, {"mild": True})
    chat, _ = _chat(book, an, tmp_path, monkeypatch, {})
    n = next(si for si in range(len(book.sents)) if "lit a cigarette" in book.sent_text(si))
    done = chat.apply([{"action": "add", "from": f"S{n + 1}", "to": f"S{n + 1}", "type": "smoking"},
                       {"action": "add", "from": "S1", "to": "S1", "type": "not-a-kind"}])
    assert len(done) == 1 and an["cuts"][0]["kind"] == "smoking" and an["cuts"][0]["cut"]


def test_words_have_ids_for_the_chat(book):
    an = R.analyze(book, OPTS)
    assert [m["id"] for m in an["mutes"]] == list(range(1, len(an["mutes"]) + 1))
