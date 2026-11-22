"""Swearing sorted by type (as CleanView 1.18.150; the owner, in the CleanStream chat: "when i had the
hard language filter on it took out some words that should be in other categories", "organize better
by type", "Yes, all of it"). Slurs are a box of their own, ticked for every age; the sexual slang words
go with Sexual words, "balls" meaning nerve and the poop word with Crude humor, "skeevy" with the rude
words. CleanListen and CleanRead share the lists (cleanlisten.py) and the boxes (filters.py)."""
import cleanlisten as E
import cleanread as R
import filters as F


def found(text, cats):
    words = [E.norm(w) for w in text.split()]
    return [(" ".join(words[a:b]), cat) for a, b, cat in E.find_language(words, cats)]


def cats(groups):
    return [c for g in groups for c in E.GROUPS[g]]


EVERY_CAT = sorted({c for g in E.GROUPS.values() for c in g})
SLURS = ["you lazy wop", "that polack", "you retard", "a faggot", "what a dyke", "you homo", "re tard"]
SEX = ["shes a hussy", "nice pair of melons", "he is horny", "what a slut", "pop her cherry",
       "is that a banana in your pocket", "a cheap whore"]
CRUDE = ["that took some balls", "grow a pair", "what a turd", "kicked him in the nuts", "he is ballsy",
         "a real ball buster"]
SWEARING = ["shit", "what the eff", "you bastard", "eff you", "s o b"]


def test_slurs_have_their_own_box():
    for t in SLURS:
        assert found(t, [c for c in EVERY_CAT if c != "slurs"]) == [], t
        assert [c for _, c in found(t, ["slurs"])] == ["slurs"], t


def test_sexual_words_go_with_sexual_words():
    for t in SEX:
        assert found(t, [c for c in EVERY_CAT if c != "sexual"]) == [], t
        assert [c for _, c in found(t, ["sexual"])] == ["sexual"], t


def test_crude_words_go_with_crude_humor():
    for t in CRUDE:
        assert found(t, [c for c in EVERY_CAT if c != "crude"]) == [], t
        assert [c for _, c in found(t, ["crude"])] == ["crude"], t


def test_swearing_keeps_the_swears():
    for t in SWEARING:
        assert [c for _, c in found(t, cats(["swearing"]))] == ["moderate"], t


def test_skeevy_is_a_rude_word():
    assert found("you skeevy guy", cats(["swearing"])) == []
    assert found("you skeevy guy", ["rude"]) == [("skeevy", "rude")]


def test_gay_is_still_an_orientation_word():
    assert found("he is gay", ["orientation"]) == [("gay", "orientation")]
    assert found("he is gay", ["slurs"]) == []


def test_everyday_words_still_left():
    for t in ("tennis balls", "a pair of shoes", "cherry pie", "ripe melons", "the coon dog barked",
              "retard the spread"):
        assert found(t, EVERY_CAT) == [], t


def test_slurs_still_not_left_by_a_checker():
    for w in ("wop", "retarded", "spic", "faggot"):
        assert not E.may_untick_word({"cat": "slurs", "word": w}), w


def test_slurs_starred_in_books():
    assert "slurs" in E.ALL_CATS


def test_slurs_ticked_for_every_age():
    assert "slurs" in F.WORD_GROUPS and "slurs" in F.BOXES
    for p, ticks in F.PRESETS.items():
        assert ticks["slurs"], p
        assert "slurs" in F.groups(ticks), p


def test_saved_ticks_get_the_slurs_box():
    assert F._upgrade({"swearing": False})["slurs"] is True
    assert F._upgrade({"slurs": False})["slurs"] is False        # her own untick stays
    assert R._upgrade({})["slurs"] is True


def test_what_each_age_mutes():
    for p, ticks in F.PRESETS.items():
        on = cats(F.groups(ticks)) + (["crude"] if ticks.get("crude") else [])
        for t in SLURS + SWEARING + SEX:
            assert found(t, on), (p, t)
        # Crude humor is off for Teens: "balls" meaning nerve plays there
        assert bool(found("that took some balls", on)) == bool(ticks["crude"]), p


def test_cleanread_uses_the_slurs_box():
    src = (E.Path(R.__file__)).read_text(encoding="utf8")
    assert src.count('("swearing", "slurs", "mild", "deity", "minced", "sexual", "rude", "crude", "drugtalk")') == 2
