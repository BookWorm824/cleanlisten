"""Gore and graphic suggestions from the AI on this PC need a word of blood, a wound or a body torn
open nearby, and blood with no insides is graphic, not gore (the owner's Hugo and Jane Eyre
audiobook, 2026-11-15 and 2026-11-20: the small AI offered muddy carts and farmers' outhouses as
gore, and a bleeding cut on the head as gore; she ticked none of them)."""
import cleanlisten as E


def words(s):
    return [E.norm(w) for w in s.split() if E.norm(w)]


NOT_GORY = [
    "There were sheltered from the weather that very day rude carts, bespattered with rustic mire, "
    "snuffed about by pigs, and roosted in by poultry, which the farmer, death, had already set "
    "apart to be his tumbrels of the revolution.",
    "It is likely enough that in the rough outhouses of some tillers of the heavy lands adjacent "
    "to Paris.",
    "The wind blew across the fields.",
]
BLOOD = [
    "It hit me, and I fell, striking my head against the door and cutting it. The cut bled, the "
    "pain was sharp.",
    "I felt a drop or two of blood from my head trickle down my neck, and was sensible of somewhat "
    "pungent suffering.",
]
INSIDES = "The wolf tore him open and his entrails spilled onto the snow."
TORTURE = ("sentencing a youth to have his hands cut off, his tongue torn out with pincers, and his "
           "body burned alive")


def test_no_blood_no_gore_suggestion():
    for s in NOT_GORY:
        assert not E.ai_gate("gore", [words(s)]), s
        assert not E.ai_gate("graphic", [words(s)]), s
    for s in BLOOD + [INSIDES, TORTURE]:
        assert E.ai_gate("gore", [words(s)]), s


def test_a_neighbouring_sentence_counts():
    assert E.ai_gate("graphic", [words(NOT_GORY[2]), words(BLOOD[1])])


def test_blood_without_insides_is_graphic():
    for s in BLOOD:
        assert E.ai_gore_kind("gore", [words(s)], ["gore", "graphic"]) == "graphic", s
        assert E.ai_gore_kind("gore", [words(s)], ["gore"]) is None, s     # graphic not filtered
    assert E.ai_gore_kind("gore", [words(INSIDES)], ["gore"]) == "gore"
    assert E.ai_gore_kind("violence", [words(BLOOD[0])], []) == "violence"


class Small:
    """The small AI: calls every listed sentence gore, and is "high" sure when asked again."""
    MODEL = "fake:small"

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "sentences in order" in prompt:
            return {"flags": [{"quote": " ".join(s.split()[:8]), "type": "gore"}
                              for s in NOT_GORY + BLOOD[1:] + [INSIDES] if s in prompt]}
        if '{"sexual": true or false}' in prompt:
            return {"sexual": False}
        if '"fine"' in prompt:
            return {"fine": []}
        return {"fits": True, "confidence": "high"}


def test_cleanlisten_offers_only_real_blood(monkeypatch):
    plain = ["Anna fed the chickens before school.", "Her brother read a book by the fire.",
             "They ate soup for lunch."]
    text = " ".join(plain + [NOT_GORY[0]] + plain + [BLOOD[1]] + plain + [INSIDES] + plain)
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate(text.split())]
    ends = [k for k, w in enumerate(asr) if w["t"].endswith(".")]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    monkeypatch.setattr(E, "_ai_module", lambda: Small())
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    scenes = E.ai_assist(asr, [], ["gore", "graphic"], to_sentences, E.span_times)
    got = sorted((sc["kind"], sc["text"].split()[1]) for sc in scenes)
    assert got == [("gore", "wolf"), ("graphic", "felt")]
    assert all(sc["cut"] is False and sc["ai_note"] == "AI suggests" for sc in scenes)
