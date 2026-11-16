"""The AI on this PC never ticks anything on its own (the owner, 2026-11-15: in Wings of a Dream it
ticked 38 sentences, "Doc shook his head." as a sexual reference, "Blood rushed into my face." as
gore, "I kissed him on the cheek." as a passionate kiss, and none fit; in a CleanListen report 21 of
25 of its finds were wrong). Everything it finds comes in unticked, "AI suggests", for her to decide.
And "his tortured face / eyes / soul" is a pained look, not torture (families kept all five)."""
import re

import cleanlisten as E
import cleanread as R

# what the small AI was "very sure" about in Wings of a Dream
WINGS = {"Doc shook his head.": "ref",
         "A fit of coughing shook me.": "ref",
         "Blood rushed into my face.": "gore",
         "Chunks of wood crashed to the floor.": "disturbing",
         "I kissed him on the cheek.": "kiss",
         "I fumed back to the house.": "disturbing"}
PLAIN = ["The wind blew across the fields.", "Anna fed the chickens before school.",
         "Her brother read a book by the fire.", "The bus was late again."]


class VerySure:
    """The small AI: flags every Wings line, and is "high" sure of each when asked again."""
    MODEL = "fake:sure"

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "numbered sentences" in prompt:            # CleanRead's read
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("The sentences:")[-1], re.M)
            return {"flags": [{"n": int(n), "type": WINGS[s], "words": s.rstrip(".")}
                              for n, t in lines for s in WINGS if s in t]}
        if "sentences in order" in prompt:            # CleanListen's read
            return {"flags": [{"quote": s, "type": WINGS[s]} for s in WINGS if s in prompt]}
        if '{"sexual": true or false}' in prompt:
            return {"sexual": False}
        if '"fine"' in prompt:
            return {"fine": []}
        return {"fits": True, "confidence": "high"}


def test_cleanread_offers_every_ai_find_unticked(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_ai", lambda: VerySure())
    paras = []
    for s in WINGS:
        paras += [" ".join(PLAIN), s]
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(paras + [" ".join(PLAIN)]), encoding="utf8")
    an = R.analyze(R.Book(str(p)), {"refs": True, "gore": True, "disturbing": True,
                                    "kiss": "passionate", "ai": True})
    ai_cuts = [c for c in an["cuts"] if c.get("ai")]
    # not sexual references any more (the owner, 2026-11-15: "stop showing them"), and not the
    # "disturbing" lines with nothing disturbing in them (the word gates, 2026-11-16)
    assert {c["raw"] for c in ai_cuts} == {s for s, k in WINGS.items() if k not in ("ref", "disturbing")}
    assert all(c["cut"] is False and c["ai_note"] == "AI suggests" for c in ai_cuts)
    note = " ".join(an.get("notes", [])) + str(an.get("ai_note", ""))
    assert "sure about" not in note


def test_cleanlisten_offers_every_ai_find_unticked(monkeypatch):
    text = " ".join(PLAIN + list(WINGS) + PLAIN)
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate(text.split())]
    ends = [k for k, w in enumerate(asr) if re.search(r"[.!?][”\"]?$", w["t"])]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    monkeypatch.setattr(E, "_ai_module", lambda: VerySure())
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    scenes = E.ai_assist(asr, [], ["ref", "gore", "disturbing", "kiss"], to_sentences, E.span_times)
    assert scenes and all(sc["cut"] is False and sc["ai_note"] == "AI suggests" for sc in scenes)
    assert "gore" in {sc["kind"] for sc in scenes}
    # "Chunks of wood crashed to the floor." has nothing disturbing in it (word gates, 2026-11-16)
    assert "disturbing" not in {sc["kind"] for sc in scenes}
    assert "ref" not in {sc["kind"] for sc in scenes}       # (2026-11-15: "stop showing them")


def words(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


def test_a_tortured_look_is_not_disturbing():
    for s in ["I could only see a sliver of his tortured face.",
              "their expressions of bewilderment jabbing my already tortured soul",
              "The tortured look in his eyes wrenched my heart.",
              "Frank’s tortured eyes found mine, but"]:
        assert not R.DISTURBING(words(s)), s
        assert not E.sentence_hit("disturbing", words(s)), s


def test_real_torture_still_is():
    for s in ["They tortured him for days.", "The prisoners were tortured.",
              "He was tortured and killed.", "The torturer smiled.", "It was torture."]:
        assert R.DISTURBING(words(s)), s
        assert E.sentence_hit("disturbing", words(s)), s
