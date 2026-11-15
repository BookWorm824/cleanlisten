"""The AI on this PC no longer suggests sexual references from its general read (the owner, 2026-11-15:
"stop showing them"). In a training run on her books every one it suggested was wrong ("Jasper found
her udder. And began to nurse.", "Twice.", "A gentle Thank You!"). The innuendo check, a conversation
at a time, still runs, and so do the word lists and the other types."""
import re

import cleanlisten as E
import cleanread as R

LINES = {"Jasper found her udder.": "ref", "Twice.": "ref",
         "Blood poured from the wound in his chest.": "gore"}
PLAIN = ["The wind blew across the fields.", "Anna fed the chickens before school.",
         "Her brother read a book by the fire.", "The bus was late again."]


class Eager:
    """A small AI that flags every line above, is sure of each, and remembers what it was asked."""
    MODEL = "fake:eager"

    def __init__(self):
        self.prompts = []

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        self.prompts.append(prompt)
        if "numbered sentences" in prompt:            # CleanRead's read
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("The sentences:")[-1], re.M)
            return {"flags": [{"n": int(n), "type": LINES[s], "words": s.rstrip(".")}
                              for n, t in lines for s in LINES if s in t]}
        if "sentences in order" in prompt:            # CleanListen's read
            return {"flags": [{"quote": s, "type": LINES[s]} for s in LINES if s in prompt]}
        if '{"sexual": true or false}' in prompt:
            return {"sexual": False}
        if '"fine"' in prompt:
            return {"fine": []}
        return {"fits": True, "confidence": "high"}


def reads(ai):
    return [p for p in ai.prompts if "numbered sentences" in p or "sentences in order" in p]


def test_cleanread_reads_for_the_rest_but_not_sexual_references(tmp_path, monkeypatch):
    ai = Eager()
    talk = []
    monkeypatch.setattr(R, "_ai", lambda: ai)
    monkeypatch.setattr(R.E, "sexual_talk", lambda texts, *a, **k: talk.append(len(texts)) or [])
    paras = []
    for s in LINES:
        paras += [" ".join(PLAIN), s]
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(paras + [" ".join(PLAIN)]), encoding="utf8")
    an = R.analyze(R.Book(str(p)), {"refs": True, "gore": True, "ai": True})
    ai_cuts = [c for c in an["cuts"] if c.get("ai")]
    assert [c["kind"] for c in ai_cuts] == ["gore"]
    assert reads(ai) and not any('- "ref":' in p for p in reads(ai))
    assert talk                                    # the innuendo check still ran


def test_cleanread_with_only_sexual_references_still_runs_the_innuendo_check(tmp_path, monkeypatch):
    ai = Eager()
    monkeypatch.setattr(R, "_ai", lambda: ai)
    monkeypatch.setattr(R.E, "sexual_talk", lambda texts, *a, **k: [1])
    p = tmp_path / "book.txt"
    p.write_text("The bus was late. He said take your pants off. She laughed.", encoding="utf8")
    found = R.ai_find(R.Book(str(p)), {"ref": E.AI_TYPES["ref"]})
    assert found == {(1, "ref"): "medium"}
    assert not reads(ai)                           # no general read at all


def test_cleanlisten_reads_for_the_rest_but_not_sexual_references(monkeypatch):
    text = " ".join(PLAIN + list(LINES) + PLAIN)
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate(text.split())]
    ends = [k for k, w in enumerate(asr) if re.search(r"[.!?][”\"]?$", w["t"])]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    ai = Eager()
    talk = []
    monkeypatch.setattr(E, "_ai_module", lambda: ai)
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    monkeypatch.setattr(E, "sexual_talk", lambda texts, *a, **k: talk.append(len(texts)) or [])
    scenes = E.ai_assist(asr, [], ["ref", "gore"], to_sentences, E.span_times)
    assert [sc["kind"] for sc in scenes] == ["gore"]
    assert reads(ai) and not any('- "ref":' in p for p in reads(ai))
    assert talk


def test_cleanlisten_with_only_sexual_references_skips_the_read(monkeypatch):
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate("The bus was late. Twice. She laughed.".split())]
    ends = [k for k, w in enumerate(asr) if w["t"].endswith(".")]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    ai = Eager()
    monkeypatch.setattr(E, "_ai_module", lambda: ai)
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    monkeypatch.setattr(E, "sexual_talk", lambda texts, *a, **k: [1])
    scenes = E.ai_assist(asr, [], ["ref"], to_sentences, E.span_times)
    assert not reads(ai)
    assert [(sc["kind"], sc["cut"], sc["ai_note"]) for sc in scenes] == [("ref", False, "AI suggests")]
