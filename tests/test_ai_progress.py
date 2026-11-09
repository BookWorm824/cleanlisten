"""The AI helper's double-check steps count under the progress bar ("14 of 150"), in
CleanListen as in CleanRead (the owner, 2026-11-09: "it says checking what ai found. is it
frozen?" - the words never changed during a long check)."""
import cleanlisten as E

TEXT = "The witch flew away tonight. The children laughed at school. The witch cast a spell today."


def test_cleanlisten_ai_double_check_counts(monkeypatch):
    asr = [{"t": w, "s": k * 0.5, "e": k * 0.5 + 0.4, "part": 0} for k, w in enumerate(TEXT.split())]
    ends = [k for k, w in enumerate(asr) if w["t"].endswith(".")]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)

    class FakeAI:
        def ensure_ai(self, progress=None):
            pass

        def chat(self, prompt, schema=None, timeout=300):
            if "sentences in order" in prompt:    # flag both witch sentences
                return {"flags": [{"quote": "The witch flew away tonight.", "type": "ref"},
                                  {"quote": "The witch cast a spell today.", "type": "ref"}]}
            return {"fits": False, "confidence": "low"}

    monkeypatch.setattr(E, "_ai_module", lambda: FakeAI())
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    said = []
    E.ai_assist(asr, [], ["ref"], to_sentences, E.span_times, progress=lambda f, m: said.append(m))
    checks = [m for m in said if m.startswith("AI is double-checking what it found")]
    assert checks == ["AI is double-checking what it found · 1 of 2",
                      "AI is double-checking what it found · 2 of 2"]
