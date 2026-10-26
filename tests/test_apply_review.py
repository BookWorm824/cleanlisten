"""cleanlisten_claude.apply_review(): how Claude's/ChatGPT's answers change the review list.

The rules under test (CLAUDE.md §3.7 and §5):
- what the family set by hand (by_you) is never changed;
- listed words stay muted unless misheard or innocent in meaning (INNOCENT_WORDS, God's name);
- "trim" shrinks a passage, "just_the_word" keeps the sentence and mutes the word;
- a passage Claude doubts is left in, except religion (doubtful religion is cut).
"""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc
from conftest import make_book

SENTENCES = [
    "It was a quiet morning.",                    # S1
    "He said damn it and left.",                  # S2
    "Then they talked about sex for an hour.",    # S3
    "Later she went home.",                       # S4
    "The pastor preached about salvation.",       # S5
]


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    """_add_word snaps mute edges to silence in the real audio; there is none here."""
    monkeypatch.setattr(E, "snap_edges", lambda path, s, e, wide=False: (s, e))
    monkeypatch.setattr(cc, "PROVIDER", "claude")


def passage(asr, sents, pid, a, b, kind="ref", **kw):
    wa, wb = sents[a][0], sents[b][1]
    s, e = E.span_times(asr, wa, wb)
    return {"id": pid, "kind": kind, "part": 0, "s": s, "e": e, "cut": True,
            "text": " ".join(w["t"] for w in asr[wa:wb + 1]), **kw}


def mute(asr, mid, word, cat, **kw):
    i = next(k for k, w in enumerate(asr) if w["n"] == E.norm(word))
    return {"id": mid, "part": 0, "s": asr[i]["s"], "e": asr[i]["e"], "cat": cat, "src": "audio",
            "i": i, "j": i + 1, "word": E.mask(asr[i]["t"]), "word_raw": asr[i]["t"], "on": True, **kw}


@pytest.fixture
def book():
    asr, sents = make_book(SENTENCES)
    st = {"parts": ["book.mp3"], "sentences": sents, "scenes": [], "mutes": [],
          "filters": {"cats": ["strong", "moderate", "mild", "deity", "sexual"],
                      "kinds": ["sex", "ref", "religion"]}}
    return st, asr


def counts():
    return {"agree": 0, "off": 0, "unsure": 0, "on": 0, "found": 0, "suggested": 0, "word": 0,
            "trim": 0}


def decide(st, asr, *decisions):
    c = counts()
    cc.apply_review(st, {"decisions": list(decisions)}, c, asr)
    return c


def d(id_, verdict, confidence="high", **kw):
    return {"id": id_, "verdict": verdict, "confidence": confidence, "reason": "test", **kw}


# --- passages -------------------------------------------------------------------------
def test_remove_reticks_a_passage(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2, cut=False))
    c = decide(st, asr, d("P1", "remove"))
    sc = st["scenes"][0]
    assert sc["cut"] is True
    assert sc["ai_note"] == "Claude agrees"
    assert sc["claude_verdict"] == "remove"
    assert c["on"] == 1 and c["agree"] == 1


def test_keep_sure_unticks_a_passage(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    c = decide(st, asr, d("P1", "keep"))
    assert st["scenes"][0]["cut"] is False
    assert st["scenes"][0]["ai_note"] == "Claude: fine"
    assert c["off"] == 1


def test_keep_unsure_leaves_passage_in(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    c = decide(st, asr, d("P1", "keep", "medium"))
    assert st["scenes"][0]["cut"] is False
    assert st["scenes"][0]["ai_note"] == "Claude unsure"
    assert c["unsure"] == 1


def test_doubtful_religion_stays_cut(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 4, 4, kind="religion"))
    decide(st, asr, d("P1", "keep", "medium"))
    assert st["scenes"][0]["cut"] is True
    assert st["scenes"][0]["ai_note"] == "Claude unsure"


def test_ids_are_matched_loosely_and_unknown_ids_ignored(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    decide(st, asr, d(" p1 ", "keep"), d("P99", "keep"), d("W7", "keep"), {"verdict": "keep"})
    assert st["scenes"][0]["cut"] is False
    assert len(st["scenes"]) == 1


# --- the family's own ticks are never overridden ---------------------------------------
@pytest.mark.parametrize("verdict, note", [("keep", "Your call (Claude differs)"),
                                           ("remove", "Claude agrees")])
def test_by_you_passage_never_changes(book, verdict, note):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2, by_you=True))
    before = dict(st["scenes"][0])
    decide(st, asr, d("P1", verdict))
    sc = st["scenes"][0]
    assert sc["cut"] is True and sc["s"] == before["s"] and sc["e"] == before["e"]
    assert sc["ai_note"] == note


def test_by_you_word_never_changes(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "damn", "mild", on=False, by_you=True))
    decide(st, asr, d("W1", "remove"))
    assert st["mutes"][0]["on"] is False
    assert st["mutes"][0]["note"] == "Your call (Claude differs)"


def test_by_you_passage_is_not_trimmed(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 1, 3, by_you=True))
    before = (st["scenes"][0]["s"], st["scenes"][0]["e"])
    decide(st, asr, d("P1", "trim", **{"from": "S3", "to": "S3"}))
    assert (st["scenes"][0]["s"], st["scenes"][0]["e"]) == before
    assert not st["scenes"][0].get("trimmed")


# --- words: listed words stay muted unless misheard or innocent -----------------------
def test_listed_swear_stays_muted_when_claude_says_keep(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "sex", "sexual"))
    c = decide(st, asr, d("W1", "keep"))
    m = st["mutes"][0]
    assert m["on"] is True
    assert m["claude_verdict"] == "unsure"
    assert m["note"] == "Muted (Claude questioned it)"
    assert c["off"] == 0


def test_listed_swear_unticked_earlier_is_reticked(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "sex", "sexual", on=False))   # e.g. the AI on this PC
    c = decide(st, asr, d("W1", "keep"))
    assert st["mutes"][0]["on"] is True
    assert c["on"] == 1


def test_misheard_word_can_be_unticked(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "sex", "sexual"))
    decide(st, asr, d("W1", "keep", misheard=True))
    assert st["mutes"][0]["on"] is False
    assert st["mutes"][0]["note"] == "Claude: fine"


def test_innocent_word_can_be_unticked(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "damn", "mild", word_raw="hell"))   # "hell" the place
    decide(st, asr, d("W1", "keep"))
    assert st["mutes"][0]["on"] is False


def test_gods_name_can_be_unticked(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "salvation", "deity"))
    decide(st, asr, d("W1", "keep"))
    assert st["mutes"][0]["on"] is False


def test_unsure_keep_never_unticks_a_word(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "damn", "mild", word_raw="hell"))
    c = decide(st, asr, d("W1", "keep", "medium"))
    assert st["mutes"][0]["on"] is True
    assert st["mutes"][0]["note"] == "Claude unsure"
    assert c["unsure"] == 1


def test_remove_reticks_a_word(book):
    st, asr = book
    st["mutes"].append(mute(asr, 1, "damn", "mild", on=False))
    decide(st, asr, d("W1", "remove"))
    assert st["mutes"][0]["on"] is True


# --- trim -----------------------------------------------------------------------------
def test_trim_shrinks_passage_to_the_problem_sentence(book):
    st, asr = book
    sents = st["sentences"]
    st["scenes"].append(passage(asr, sents, 1, 1, 3))           # S2..S4
    c = decide(st, asr, d("P1", "trim", **{"from": "S3", "to": "S3"}))
    sc = st["scenes"][0]
    assert sc["cut"] is True and sc["trimmed"] is True
    assert sc["text"] == SENTENCES[2]
    assert (sc["s"], sc["e"]) == E.span_times(asr, sents[2][0], sents[2][1])
    assert sc["ai_note"] == "Claude: trimmed"
    assert c["trim"] == 1


def test_trim_never_grows_a_passage(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 3))   # S3..S4
    decide(st, asr, d("P1", "trim", **{"from": "S1", "to": "S3"}))
    sc = st["scenes"][0]
    assert sc["text"] == SENTENCES[2]                               # clipped to S3, not S1..S3


def test_trim_of_the_whole_passage_counts_as_remove(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 1, 3, cut=False))
    c = decide(st, asr, d("P1", "trim", **{"from": "S2", "to": "S4"}))
    assert st["scenes"][0]["cut"] is True
    assert not st["scenes"][0].get("trimmed")
    assert c["trim"] == 0 and c["agree"] == 1


# --- just the word --------------------------------------------------------------------
def test_just_the_word_keeps_sentence_and_mutes_word(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 1, 1))   # "He said damn it and left."
    c = decide(st, asr, d("P1", "just_the_word", words="damn", word_type="mild language"))
    sc = st["scenes"][0]
    assert sc["cut"] is False
    assert sc["ai_note"] == "Claude: just the word"
    assert sc["claude_word"] == "damn"
    [m] = st["mutes"]
    assert m["cat"] == "mild" and m["on"] is True and m["src"] == "claude"
    assert m["word_raw"] == "damn" and m["word"] == "d***"
    assert c["word"] == 1


def test_just_the_word_reuses_an_existing_mute(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 1, 1))
    st["mutes"].append(mute(asr, 1, "damn", "mild"))
    decide(st, asr, d("P1", "just_the_word", words="damn", word_type="mild"))
    assert st["scenes"][0]["cut"] is False
    assert len(st["mutes"]) == 1


def test_just_the_word_not_found_sure_means_remove(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    decide(st, asr, d("P1", "just_the_word", words="nowhere", word_type="mild"))
    assert st["scenes"][0]["cut"] is True
    assert st["mutes"] == []


def test_just_the_word_not_found_unsure_leaves_it(book):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    c = decide(st, asr, d("P1", "just_the_word", "medium", words="nowhere"))
    assert st["scenes"][0]["cut"] is True
    assert st["scenes"][0]["ai_note"] == "Claude unsure"
    assert c["unsure"] == 1


# --- the reviewer's name shows in the notes -------------------------------------------
def test_notes_name_chatgpt(book, monkeypatch):
    monkeypatch.setattr(cc, "PROVIDER", "chatgpt")
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))
    decide(st, asr, d("P1", "keep"))
    assert st["scenes"][0]["ai_note"] == "ChatGPT: fine"


# --- the whole review() loop with a stand-in for Claude --------------------------------
def test_review_adds_missed_items(book, monkeypatch):
    st, asr = book
    st["scenes"].append(passage(asr, st["sentences"], 1, 2, 2))      # S3, already found
    answer = {
        "decisions": [d("P1", "remove")],
        "missed_passages": [
            {"from": "S5", "to": "S5", "type": "religious content", "confidence": "high", "reason": "x"},
            {"from": "S3", "to": "S3", "type": "sexual reference", "confidence": "high", "reason": "dup"},
            {"from": "S4", "to": "S4", "type": "gory description", "confidence": "high",
             "reason": "gore filter is off"},
        ],
        "missed_words": [
            {"sentence": "S1", "words": "quiet", "type": "swearing", "confidence": "medium", "reason": "x"},
            {"sentence": "S1", "words": "not there", "type": "swearing", "confidence": "high", "reason": "x"},
        ],
    }
    prompts = []
    monkeypatch.setattr(cc, "status", lambda provider=None: "ok")
    monkeypatch.setattr(cc, "run", lambda prompt, system, schema=None, **kw:
                        prompts.append(prompt) or {"data": answer})
    cc.review(st, asr)

    assert len(prompts) == 1 and "P1 · cut passage" in prompts[0]
    kinds = [(sc["kind"], sc["text"], sc["cut"]) for sc in st["scenes"]]
    assert kinds == [("ref", SENTENCES[2], True), ("religion", SENTENCES[4], True)]
    [m] = st["mutes"]
    assert m["word_raw"] == "quiet" and m["cat"] == "moderate"
    assert m["on"] is False and m["note"] == "Claude suggests"     # medium confidence: unticked
    assert st["claude_checked"] is True
    assert "found 1 more" in st["claude_note"] and "suggested 1" in st["claude_note"]
