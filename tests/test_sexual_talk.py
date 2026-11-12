"""Innuendo, a conversation at a time (CleanView 1.18.70; the owner, 2026-11-12: "yes to the check").
The small AI reading 40 sentences for every filter missed lines like "Take your pants off!" (0 of 8
in a test); asked per 30 sentences whether anything sexual is said, then which lines (with their
exact words), then each line alone, it caught 4 of 8 and none of 60 innocent lines. Its finds are
for you to decide (unticked), and a line with a word on the list stays "just the word"."""
import re

import cleanlisten as E
import cleanread as R

PANTS = "“Take your pants off!” she called from the bedroom, laughing."
SEXY = "“You look sexy in that,” he said."
PLAIN = ["Beckett pulled the file across the desk.", "Ryan checked the phone records again.",
         "The rain hammered on the windows.", "Castle leaned back and grinned."]


class FakeAI:
    """Like the small AI: the all-filters read misses the innuendo, the three steps find it."""
    MODEL = "fake:talk"

    def __init__(self, quote=None):
        self.asked = []
        self.quote = quote

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        self.asked.append(prompt)
        if "numbered sentences" in prompt or "sentences in order" in prompt:
            return {"flags": []}
        if '{"sexual": true or false}' in prompt:
            return {"sexual": "pants" in prompt or "sexy" in prompt}
        if "Which lines say something sexual" in prompt:
            lines = re.findall(r"^(\d+)\. (.*)$", prompt, re.M)
            return {"lines": [{"n": int(n), "words": self.quote or t[:30]} for n, t in lines
                              if "pants" in t or "sexy" in t]}
        if "Does the marked line contain" in prompt:
            return {"fits": True}
        return {"fits": False, "confidence": "low"}


def test_three_steps_find_the_innuendo():
    ai = FakeAI()
    texts = PLAIN * 10 + [PANTS] + PLAIN * 10
    got = E.sexual_talk(texts, lambda p, s, t: ai.chat(p, s, t), "a sexual reference")
    assert got == {40}
    asks = [p for p in ai.asked if '{"sexual": true or false}' in p]
    assert len(asks) == 3                       # one quick question per 30 sentences


def test_quiet_parts_cost_one_question():
    ai = FakeAI()
    assert E.sexual_talk(PLAIN * 15, lambda p, s, t: ai.chat(p, s, t), "x") == set()
    assert len(ai.asked) == 2


def test_words_that_arent_in_the_line_are_dropped():
    ai = FakeAI(quote="come up and see my etchings")
    assert E.sexual_talk(PLAIN + [PANTS], lambda p, s, t: ai.chat(p, s, t), "x") == set()


def test_cleanread_suggests_it_and_a_listed_word_stays_just_the_word(tmp_path, monkeypatch):
    ai = FakeAI()
    monkeypatch.setattr(R, "_ai", lambda: ai)
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join([" ".join(PLAIN), PANTS, " ".join(PLAIN), SEXY, " ".join(PLAIN)]),
                 encoding="utf8")
    book = R.Book(str(p))
    found = R.ai_find(book, {"ref": R.CLEAN_AI["ref"]})
    hits = {book.sent_text(i): conf for (i, k), conf in found.items() if k == "ref"}
    assert hits == {PANTS: "medium"}            # unticked, for you to decide
    an = R.analyze(book, {"refs": True, "sexual": True, "ai": True})
    pants = [c for c in an["cuts"] if PANTS in c["text"]]
    assert pants and pants[0]["cut"] is False and pants[0]["ai_note"] == "AI suggests"
    assert any(m["word_raw"].lower() == "sexy" for m in an["mutes"])


def test_cleanlisten_suggests_it(monkeypatch):
    text = " ".join(PLAIN + [PANTS] + PLAIN + [SEXY])
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate(text.split())]
    ends = [k for k, w in enumerate(asr) if re.search(r"[.!?][”\"]?$", w["t"])]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    monkeypatch.setattr(E, "_ai_module", lambda: FakeAI())
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    scenes = E.ai_assist(asr, [], ["ref"], to_sentences, E.span_times)
    got = [(sc["text"][:22], sc["cut"], sc["ai_note"]) for sc in scenes if sc["kind"] == "ref"]
    assert got == [(PANTS[:22], False, "AI suggests")]     # not the sexy line: that word is muted
