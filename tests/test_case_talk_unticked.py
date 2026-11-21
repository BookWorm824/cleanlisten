"""CleanView 1.18.152 (Criminal Minds S1E20; the owner: "All of them", here "Yes, both"):
"unfaithful" and "infidelity" are sleeping around; with Medical off, a passage an AI cut as a sexual
reference whose only sexual words are case talk ("That sounds like statutory rape. I'm not surprised.
You talk to Hotch?") is offered unticked."""
import cleanlisten as E
import cleanread as R


def w(text):
    return [E.norm(t) for t in text.split() if E.norm(t)]


def test_unfaithful_and_infidelity_are_sleeping_around():
    for line in ("Mark was obsessed with thinking she was unfaithful.", "That explains his issues with infidelity.",
                 "Her unfaithfulness broke him.", "Two infidelities in a year."):
        assert R.SLEEPING(w(line)), line
    assert not R.SLEEPING(w("Thou wicked and unfaithful servant."))


def test_case_talk_only():
    assert E.case_talk_only(w("That sounds like statutory rape. I'm not surprised. You talk to Hotch?"))
    assert E.case_talk_only(w("Any signs of sexual assault?"))
    assert E.case_talk_only(w("He's a registered sex offender."))
    assert not E.case_talk_only(w("The rape kit came back with vaginal tearing."))      # explicit finding
    assert not E.case_talk_only(w("The rapist said she was sexy."))                     # a sexual word too
    assert not E.case_talk_only(w("She was unfaithful to me."))                          # no case talk


def review(kinds, **scene):
    text = "That sounds like statutory rape. I'm not surprised. You talk to Hotch?"
    asr = [{"t": t, "n": E.norm(t), "part": 0, "s": float(k), "e": k + 0.5} for k, t in enumerate(text.split())]
    sc = dict({"kind": "ref", "part": 0, "s": 0.0, "e": float(len(asr)), "cut": True}, **scene)
    return {"filters": {"kinds": kinds}, "scenes": [sc]}, asr


def test_an_ai_cut_is_offered_unticked_with_medical_off():
    for who in ({"ai": True}, {"claude": True}):
        st, asr = review(["ref"], **who)
        assert E.apply_case_talk(st, asr) == 1
        assert st["scenes"][0]["cut"] is False and st["scenes"][0]["ai_note"] == E.CASE_TALK_UNTICKED


def test_left_as_it_was():
    st, asr = review(["ref", "medical"], ai=True)                 # Medical ticked: case talk goes
    assert E.apply_case_talk(st, asr) == 0 and st["scenes"][0]["cut"]
    st, asr = review(["ref"], ai=True, by_you=True)               # her own choice
    assert E.apply_case_talk(st, asr) == 0 and st["scenes"][0]["cut"]
    st, asr = review(["ref"], ai=True, learned="you")             # learned from her choices
    assert E.apply_case_talk(st, asr) == 0
    st, asr = review(["ref"])                                     # found by the word lists
    assert E.apply_case_talk(st, asr) == 0


def test_it_runs_with_the_other_last_rules():
    src = (E.Path(E.__file__)).read_text(encoding="utf8")
    assert "    apply_case_talk(st, asr)             # case talk" in src
    claude = (E.Path(E.__file__).parent / "cleanlisten_claude.py").read_text(encoding="utf8")
    assert "E.apply_case_talk(st, asr)" in claude
    read = (E.Path(E.__file__).parent / "cleanread.py").read_text(encoding="utf8")
    assert "E.case_talk_only(_words(c))" in read
