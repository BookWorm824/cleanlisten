"""The AI's steps are numbered and say what each is for (the owner, 2026-11-25: "double checking
what it read and then after that it says double checking the dialogue ... to the general people
it can seem to be redundant or not working"). Only the steps a check runs are counted."""
import cleanlisten as E
import cleanread as R


def test_steps_are_numbered_and_named():
    steps = E.Steps(["read", "found", None, "flagged"])
    assert steps("read", "40%") == "Step 1 of 3 · The AI is reading the book · 40%"
    assert steps("found", "3 of 9") == "Step 2 of 3 · The AI is making sure its own finds are right · 3 of 9"
    assert steps("flagged") == "Step 3 of 3 · The AI is checking what the word lists found"


def test_a_step_not_counted_or_a_lone_step_has_no_number():
    assert E.Steps()("read", "5%") == "The AI is reading the book · 5%"
    assert E.Steps(["read"])("read") == "The AI is reading the book"
    assert E.Steps(["read", "found"])("words") == "The AI is checking words that can have an innocent meaning"


def test_no_step_says_double_checking():
    assert not any("double" in t for t in E.STEP_TEXT.values())
    assert len(set(E.STEP_TEXT.values())) == len(E.STEP_TEXT)    # each one different


def test_cleanread_counts_its_steps_in_order(tmp_path, monkeypatch):
    p = tmp_path / "book.txt"
    p.write_text("The witch flew away tonight.\n\nThe children laughed at school.\n\n"
                 "Damn, the witch cast a spell today.", encoding="utf8")
    book = R.Book(str(p))

    class FakeAI:
        MODEL = "fake:steps"

        def ensure_ai(self, progress=None):
            pass

        def chat(self, prompt, schema=None, timeout=300):
            if "numbered sentences" in prompt:
                return {"flags": [{"n": 1, "type": "crude", "words": "The witch flew away tonight."}]}
            if '"fine"' in prompt:
                return {"fine": []}
            return {"fits": False, "confidence": "low"}
    monkeypatch.setattr(R, "_ai", lambda: FakeAI())
    said = []
    cuts = [{"kind": "crude", "text": "The children laughed at school.", "sents": [1], "para": 1}]
    mutes = [{"cat": "mild", "word_raw": "damn", "para": 2, "a": 0, "b": 4}]
    R._ai_clean(book, cuts, mutes, {"crude": "crude humor"}, set(), set(),
                lambda f, m: said.append(m), None)
    numbered = [m.split(" · ")[0] for m in said if m.startswith("Step ")]
    order = list(dict.fromkeys(numbered))
    assert order[0] == "Step 1 of 3" and order[-1] == "Step 3 of 3", said
    assert all(m.split(" · ")[0].endswith("of 3") for m in said if m.startswith("Step "))
