"""The AI's "relationship" finds (same-sex and non-traditional relationships) need a word of romance
or of a couple in the sentence or next to it (the owner, 2026-11-09: Camp Club Girls had 43 plain
lines between friends suggested, "“No,” they replied.", "Elizabeth giggled nervously.").
Real ones stay; other filters are not touched."""
import re

import pytest

import cleanread as R

PLAIN = ["The wind blew across the fields.", "Anna fed the chickens before school.",
         "Her brother read a book by the fire.", "The bus was late again.", "They ate soup for lunch."]
FRIENDS = "“No,” they replied."
GIGGLE = "Elizabeth giggled nervously."
REAL = "Claire leaned over and kissed Mia on the lips."
QUIET = "Mia smiled back at her."          # no romance word, but right after REAL
BULLY = "At recess, Mark shoved Danny into the lockers and called him a loser."

# lines from the owner's reports that must not come back as relationship finds
HARMLESS = [FRIENDS, GIGGLE, "Jessie asked.", "“Hey!”", "“Okay, girls.",
            "The girls breathed deep sighs of relief.", "“You’re right,” whispered Elizabeth.",
            "Alex sat up and stretched, while Elizabeth began making her bed.",
            "“I saw that, too,” said the counselor.", "“I like you.”"]
# and real ones that must
KEEP = ["Emma kissed her girlfriend goodnight and closed the door.",
        "Mark and his husband had been married for ten years.",
        "Hannah wanted to be more than friends with Rachel.",
        "Her two moms waved from the porch as the bus pulled away.",
        "The three of them lived together as a throuple.",
        "Ben had a crush on Luke and blushed whenever he walked by.",
        "My dad has three wives, and we all live in the same big house.",
        "Jake flirted with Tom all through dinner.", "They had an open marriage."]


@pytest.fixture
def book(tmp_path):
    sents = [PLAIN[k % 5] for k in range(60)]
    sents[10], sents[20], sents[30], sents[31], sents[45] = FRIENDS, GIGGLE, REAL, QUIET, BULLY
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(" ".join(sents[k:k + 5]) for k in range(0, 60, 5)), encoding="utf8")
    return R.Book(str(p))


class FakeAI:
    """Like the small local AI: calls every one of these a relationship, and agrees when asked
    again; the bullying line is bullying."""
    MODEL = "fake:rel"

    def __init__(self):
        self.checks = []

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "numbered sentences" in prompt:
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("The sentences:")[-1], re.M)
            out = []
            for n, t in lines:
                for s in (FRIENDS, GIGGLE, REAL, QUIET):
                    if s in t:
                        out.append({"n": int(n), "type": "relationship", "words": s})
                if "shoved" in t:
                    out.append({"n": int(n), "type": "bully", "words": "shoved Danny"})
            return {"flags": out}
        self.checks.append(prompt.split(">>> ")[-1].split(" <<<")[0])
        return {"fits": True, "confidence": "high"}


@pytest.fixture
def fake(monkeypatch):
    ai = FakeAI()
    monkeypatch.setattr(R, "_ai", lambda: ai)
    return ai


def si_of(book, text):
    return next(i for i in range(len(book.sents)) if text in book.sent_text(i))


def test_plain_lines_between_friends_are_not_relationship_finds(book, fake):
    found = R.ai_find(book, {"relationship": R.SCAN_AI["relationship"], "bully": R.SCAN_AI["bully"]})
    kept = {book.sent_text(i) for i, kind in found if kind == "relationship"}
    assert REAL in kept and QUIET in kept          # the kiss, and the line right after it
    assert FRIENDS not in kept and GIGGLE not in kept
    assert (si_of(book, BULLY), "bully") in found  # other filters as before
    # the dropped ones aren't even double-checked (less waiting)
    assert not any(FRIENDS in c or GIGGLE in c for c in fake.checks)


def test_the_owners_lines():
    class B:
        old_style = False

        def __init__(self, s):
            self.sents, self.s = [s], s

        def sent_text(self, i):
            return self.s

        def sent_words(self, i):
            return [R.nrm(w) for w in self.s.split() if R.nrm(w)]
    assert [h for h in HARMLESS if R.romance_near(B(h), 0)] == []
    assert [k for k in KEEP if not R.romance_near(B(k), 0)] == []
