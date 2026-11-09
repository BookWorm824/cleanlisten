"""CleanRead's AI helper, faster without losing accuracy (the owner, 2026-11-09: "make clean read
faster" but "keep checks accurate"): the AI's answers are kept per book and only reused for
exactly the same question, a stopped check picks up where it left off, a part the AI is too slow
on is split up instead of skipped, and Find also checks what the content check found."""
import re

import pytest

import cleanread as R

PLAIN = ["The wind blew across the fields.", "Anna fed the chickens before school.",
         "Her brother read a book by the fire.", "The bus was late again.", "They ate soup for lunch."]
BAD = "At recess, Mark shoved Danny into the lockers and called him a loser."


@pytest.fixture
def book(tmp_path):
    sents = [PLAIN[k % 5] for k in range(120)]
    sents[70] = BAD
    text = "\n\n".join(" ".join(sents[k:k + 6]) for k in range(0, 120, 6))
    p = tmp_path / "book.txt"
    p.write_text(text, encoding="utf8")
    return R.Book(str(p))


class FakeAI:
    """Flags the bullying sentence; the double-check agrees with it."""
    MODEL = "fake:1"

    def __init__(self, fail=None, flag=True):
        self.reads, self.checks, self.fail, self.flag = [], [], fail, flag

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "numbered sentences" in prompt:
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("The sentences:")[-1], re.M)
            self.reads.append(len(lines))
            if self.fail and self.fail(lines):
                raise TimeoutError("timed out")
            return {"flags": [{"n": int(n), "type": "bully", "words": "shoved Danny into the lockers"}
                              for n, t in lines if "shoved" in t and self.flag]}
        self.checks.append(prompt)
        marked = prompt.split(">>> ")[-1].split(" <<<")[0] if ">>> " in prompt else prompt
        if "fits" in str(schema) and "confidence" in str(schema):
            return {"fits": "shoved" in marked, "confidence": "high"}
        return {"fits": "shoved" in marked}


def bully_si(book):
    return next(i for i in range(len(book.sents)) if "shoved" in book.sent_text(i))


@pytest.fixture
def fake(monkeypatch):
    ai = FakeAI()
    monkeypatch.setattr(R, "_ai", lambda: ai)
    return ai


DEFS = {"bully": R.CLEAN_AI["bully"]}


def test_the_same_question_twice_gets_the_same_answer_without_asking(book, fake):
    first = R.ai_find(book, DEFS)
    asked = len(fake.reads) + len(fake.checks)
    assert first == {(bully_si(book), "bully"): "high"} and asked > 0
    again = R.ai_find(book, DEFS)
    assert again == first
    assert len(fake.reads) + len(fake.checks) == asked          # nothing asked the second time


def test_a_stopped_check_picks_up_where_it_left_off(book, fake):
    stop = {"after": 2}

    def cancel():
        return len(fake.reads) >= stop["after"]
    with pytest.raises(KeyboardInterrupt):
        R.ai_find(book, DEFS, cancel=cancel)
    assert len(fake.reads) == 2
    said = []
    found = R.ai_find(book, DEFS, progress=lambda f, m: said.append(m))
    whole = len(range(0, len(book.sents), 37))
    assert len(fake.reads) == whole            # the first two parts weren't asked again
    assert found == {(bully_si(book), "bully"): "high"}
    assert any("picking up where it left off" in m for m in said)


def test_a_different_question_is_asked_again(book, fake):
    R.ai_find(book, DEFS)
    n = len(fake.reads)
    R.ai_find(book, DEFS, notes="Don't count teasing between brothers.")    # what they told the chat
    assert len(fake.reads) == 2 * n
    fake.MODEL = "other:2"                     # another AI model: asked again too
    R.ai_find(book, DEFS)
    assert len(fake.reads) == 3 * n


def test_a_part_the_ai_is_too_slow_on_is_split_not_skipped(book, monkeypatch):
    ai = FakeAI(fail=lambda lines: len(lines) > 20)       # only 20 sentences at a time work
    monkeypatch.setattr(R, "_ai", lambda: ai)
    info = {}
    found = R.ai_find(book, DEFS, info=info)
    assert found == {(bully_si(book), "bully"): "high"}
    assert info["unread"] == 0
    assert ai.reads[:3] == [40, 20, 20]        # the first part split in half...
    assert max(ai.reads[3:]) <= 20             # ...and the rest asked in smaller parts from then on


def test_what_the_ai_still_cant_read_is_said(book, monkeypatch):
    ai = FakeAI(fail=lambda lines: any("shoved" in t for _, t in lines))
    monkeypatch.setattr(R, "_ai", lambda: ai)
    info = {}
    found = R.ai_find(book, DEFS, info=info)
    assert found == {} and info["unread"] > 0
    assert "couldn't read" in R.unread_note(info) and R.unread_note({}) == ""
    assert R.unread_note({"unread": 0}) == ""


def test_an_ai_that_stopped_answering_ends_the_ai_part_with_a_plain_note(book, monkeypatch):
    ai = FakeAI(fail=lambda lines: True)
    monkeypatch.setattr(R, "_ai", lambda: ai)
    with pytest.raises(R.AIStopped):
        R.ai_find(book, DEFS)
    assert len(ai.reads) == 4                  # not hours of waiting on every part
    res = R.scan(book, use_ai=True)
    assert "stopped answering partway" in res["ai_note"] and "word lists only" in res["ai_note"]


def test_find_also_checks_what_the_content_check_found(book, monkeypatch):
    check = FakeAI()
    monkeypatch.setattr(R, "_ai", lambda: check)
    R.ai_find(book, {"bully": R.SCAN_AI["bully"], "witchcraft": R.SCAN_AI["witchcraft"]})
    find = FakeAI(flag=False)                  # this time the read misses it
    monkeypatch.setattr(R, "_ai", lambda: find)
    find.MODEL = check.MODEL
    found = R.ai_find(book, {"bully": R.CLEAN_AI["bully"], "crude": R.CLEAN_AI["crude"]})
    assert found == {(bully_si(book), "bully"): "high"}     # the check's find, double-checked


def test_a_line_cut_short_by_a_power_cut_is_ignored(book, fake):
    R.ai_find(book, DEFS)
    path = next(R.ANSWERS_DIR.glob("*.jsonl"))
    with open(path, "a", encoding="utf8") as f:
        f.write('{"k": "abc", "a": {"fla')
    n = len(fake.reads)
    assert R.ai_find(book, DEFS) == {(bully_si(book), "bully"): "high"}
    assert len(fake.reads) == n


def test_the_book_is_read_in_the_same_parts_as_before(book, fake):
    # the parts decide what the small AI notices, so they're kept as they were: 40 sentences,
    # each starting 37 after the last
    R.ai_find(book, DEFS)
    S = len(book.sents)
    want = [min(40, S - a) for a in range(0, S, 37)]
    want = want[:next(k for k, a in enumerate(range(0, S, 37)) if a + 40 >= S) + 1]
    assert fake.reads == want


def test_old_answer_files_are_tidied(book, fake, monkeypatch):
    monkeypatch.setattr(R, "KEEP_ANSWERS", 3)
    R.ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    for k in range(5):
        (R.ANSWERS_DIR / f"old{k}.jsonl").write_text("")
    R.ai_find(book, DEFS)
    assert len(list(R.ANSWERS_DIR.glob("*.jsonl"))) <= 3
