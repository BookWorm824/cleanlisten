"""Blue Ridge Sunrise (2026-11-05): "its really bad..the flagging ... it doesn't seem to be
learning, I think its getting worse" and "claude didn't change". The report had 1,012 items,
902 from the AI on this PC (unticked, none backed by the word lists); the learned "kept" memory
would fill with them; the examples Claude got as "this family's choices" were its own; a section
Claude couldn't read was skipped without another try."""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanlisten_learn as L


def _scene(kind, text, s, part=0, **kw):
    return dict({"kind": kind, "part": part, "s": s, "e": s + 2.0, "ai": True, "cut": False,
                 "ai_note": "AI suggests", "text": text}, **kw)


def test_unbacked_picks_are_left_out_where_claude_read():
    st = {"scenes": [], "mutes": []}
    found = [_scene("relationship", "He hasn't.", 10.0),
             _scene("kiss_ss", "His lips found hers, teasing and playing.", 20.0),
             _scene("ref", "He wanted to have sex with her right there.", 30.0)]   # backed
    note = E._merge_ai(st, [], [], found, [], claude_ok=True)
    assert [x["text"] for x in st["scenes"]] == ["He wanted to have sex with her right there."]
    assert st["scenes"][0]["cut"] is False and st["scenes"][0]["ai_note"] == "AI on this PC suggests"
    assert "2 other passages" in note


def test_where_claude_couldnt_read_the_ai_on_this_pc_decides():
    st = {"scenes": [], "mutes": [], "claude_unchecked": [{"part": 1, "s": 0.0, "e": 100.0}]}
    found = [_scene("relationship", "He hasn't.", 10.0, part=0),
             _scene("relationship", "She hasn't.", 10.0, part=1, cut=True, ai_note="AI found")]
    E._merge_ai(st, [], [], found, [], claude_ok=True)
    assert [(x["part"], x["cut"], x["ai_note"]) for x in st["scenes"]] == [(1, True, "AI found")]


def test_without_claude_nothing_changes():
    st = {"scenes": [], "mutes": []}
    found = [_scene("relationship", "He hasn't.", 10.0)]
    E._merge_ai(st, [], [], found, [], claude_ok=False)
    assert len(st["scenes"]) == 1


@pytest.fixture
def learned(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    monkeypatch.setattr(L, "_shared", {"cut": [], "kept": [], "ok_words": [], "word_mutes": [],
                                       "cut_for": {}})


def test_only_real_choices_are_learned(learned):
    st = {"scenes": [
        {"kind": "religion", "cut": True, "text": "She had everything in place, God rest her soul."},
        {"kind": "relationship", "cut": False, "ai_note": "AI on this PC suggests",
         "text": "Kyle was practically preening as he looked down at Zoe."},          # left alone
        {"kind": "ref", "cut": False, "by_you": True,
         "text": "Her eyes raked over him, and he felt the look like a touch."}],      # unticked
        "mutes": [{"word": "darn", "ctx": "oh", "on": False, "note": "Claude suggests"}]}
    L.record(st)
    d = L.load()
    assert d["cut"] == ["she had everything in place god rest her soul"]
    assert d["kept"] == ["her eyes raked over him and he felt the look like a touch"]
    assert "relationship" not in d["kinds"] and d["words"] == {}


def test_claude_is_shown_your_choices_not_its_own(learned):
    d = L.load()
    d["claude_cut"] = ["something claude cut before in another book"]
    d["kept"] = ["valerie cheated on me and i was so mad"]
    L.save(d)
    ex = L.examples()
    assert ex["cut"] == [] and ex["kept"] == ["valerie cheated on me and i was so mad"]
    assert "claude cut before" not in L.examples_text()


def test_a_section_that_fails_is_tried_again_and_noted(monkeypatch):
    calls = []

    def run(prompt, system, schema=None, **kw):
        calls.append(prompt)
        if "section 2 of" in prompt:
            raise cc.ClaudeError("Claude Code stopped without an answer.")
        if "section 1 of" in prompt and len(calls) == 1:
            raise cc.ClaudeError("Claude Code stopped without an answer.")   # once, then fine
        return {"data": {"decisions": [], "missed_passages": [], "missed_words": []}}
    monkeypatch.setattr(cc, "run", run)
    monkeypatch.setattr(cc, "status", lambda *a: "ok")
    monkeypatch.setattr(cc, "RETRY_WAIT", 0)
    monkeypatch.setattr(cc, "_sections", lambda texts: [(0, 0), (1, 1)])
    asr = [{"t": w, "s": i * 1.0, "e": i * 1.0 + 0.5, "part": 0 if i < 3 else 1}
           for i, w in enumerate("One two three. Four five six.".split())]
    st = {"sentences": [(0, 2), (3, 5)], "scenes": [], "mutes": [], "filters": {}}
    cc.review(st, asr)
    assert sum("section 1 of" in c for c in calls) == 2       # tried again, then it worked
    assert sum("section 2 of" in c for c in calls) == 2       # tried twice, still failed
    (u,) = st["claude_unchecked"]                # part 2's sentence, with the usual padding
    assert u["part"] == 1 and u["s"] <= 3.0 and u["e"] >= 5.5
    assert "1 of 2 sections couldn't be checked" in st["claude_note"]


def test_a_book_claude_couldnt_read_at_all_is_a_failed_check(monkeypatch):
    def run(*a, **kw):
        raise cc.ClaudeError("Claude Code stopped without an answer.")
    monkeypatch.setattr(cc, "run", run)
    monkeypatch.setattr(cc, "status", lambda *a: "ok")
    monkeypatch.setattr(cc, "RETRY_WAIT", 0)
    monkeypatch.setattr(cc, "_sections", lambda texts: [(0, 0)])
    asr = [{"t": w, "s": i * 1.0, "e": i * 1.0 + 0.5, "part": 0}
           for i, w in enumerate("One two three.".split())]
    st = {"sentences": [(0, 2)], "scenes": [], "mutes": [], "filters": {}}
    with pytest.raises(cc.ClaudeError):
        cc.review(st, asr)
