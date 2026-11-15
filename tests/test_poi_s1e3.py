"""Person of Interest S1E3 words (CleanView 1.18.104): someone's "other woman", "grateful
señoritas", and "screwed us" / "screw with us" / "screwed over" with the mild words."""
import pytest

import cleanlisten as E

ALL = list(E.ALL_CATS) if hasattr(E, "ALL_CATS") else ["strong", "moderate", "mild", "minced",
                                                        "deity", "sexual"]


def hits(text, cats=ALL):
    ws = [E.norm(w) for w in text.split() if E.norm(w)]
    return [(" ".join(ws[i:j]), c) for i, j, c in E.find_language(ws, cats)]


@pytest.mark.parametrize("text", ["So... Who's the other woman?", "Who is the other woman?",
                                  "Who was the other woman?",
                                  "Looks like Joey's other woman's got a little girl.",
                                  "He went back to his other woman."])
def test_other_woman_found(text):
    got = hits(text)
    assert len(got) == 1 and got[0][1] == "sexual" and got[0][0].startswith("other wom"), got


@pytest.mark.parametrize("text", ["Where's the other woman going?", "the two other women in the car",
                                  "We don't want him to hurt other women.",
                                  "Did you recognize any of the other men over there tonight?",
                                  "They followed two other men out.",
                                  "How I begged him to take other women on",
                                  "That's other women's business."])
def test_other_women_and_men_left(text):
    assert hits(text) == []


def test_other_woman_needs_the_sexual_words():
    assert hits("Who's the other woman?", ["strong", "mild"]) == []


@pytest.mark.parametrize("text", ["and grateful señoritas.", "and grateful senoritas.",
                                  "a grateful señorita"])
def test_senoritas_found(text):
    got = hits(text)
    assert len(got) == 1 and got[0][1] == "sexual" and got[0][0].startswith("grateful"), got


def test_senorita_alone_left():
    assert hits("Buenos días, señorita.") == []


@pytest.mark.parametrize("text, said", [
    ("Latimer screwed us.", "screwed us"),
    ("He screwed me over.", "screwed me over"),
    ("You don't screw with us.", "screw with us"),
    ("Someone is screwing with me.", "screwing with me"),
    ("Every crook HR screwed over", "screwed over"),
    ("We didn't want to screw Max over.", "screw max over"),
    ("Don't screw us over.", "screw us over"),
    ("She screws everybody.", "screws everybody"),
])
def test_screwed_found_with_the_mild_words(text, said):
    assert hits(text) == [(said, "mild")]


def test_screwed_not_strong_or_deity():
    assert hits("Latimer screwed us.", ["strong", "deity"]) == []


@pytest.mark.parametrize("text", ["He screwed him up good.", "They screwed it in tight.",
                                  "She screws them in tight.", "Hand me the screw you dropped.",
                                  "I screwed up.", "Screw the lid over the jar.",
                                  "a titanium screw with a flat head", "He screwed me back in."])
def test_screws_and_messing_up_left(text):
    assert hits(text) == []


def test_screw_you_and_were_screwed_as_before():
    assert hits("Screw you.") == [("screw you", "mild")]
    assert hits("if it is that, we're screwed.") == [("we're screwed", "mild")]


@pytest.mark.parametrize("text", ["Bank robber and a cheat.", "You big cheater!",
                                  "Are you calling me a cheater, Harold?"])
def test_cheat_and_cheater_not_on_the_lists(text):
    # CleanView taught "Bank robber and a cheat" for Person of Interest only (games, poker)
    assert hits(text) == []
