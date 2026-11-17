"""The owner's Railway Children report (CleanRead, 2026-11-16): "i think too much was flagged here",
"not ticked but flagged". Old-fashioned meanings that aren't the problem they look like:
"rum" meaning odd, "Bong" (the French "bon"), beating up whites of eggs, "on pain of torture",
"Come hither with me", screwing up one's eyelids, "Sissy" as a name for a sister and the
children's game of "the broken boner". The real thing is still found in each case.
"""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import MODERN, OLD, _book


def hit(matcher, text):
    return bool(matcher(words(text)))


# --- "rum" meaning odd ----------------------------------------------------------------------
@pytest.mark.parametrize("text", ["What rum names.", "It is most extraordinarily rum!", "That's a rum go.",
                                  "He's a rum old fellow.", "It was a very rum thing to do."])
def test_rum_meaning_odd_is_not_drinking(text):
    assert not hit(R.DRINKING, text)


@pytest.mark.parametrize("text", ["Fifteen men on the dead man's chest, yo-ho-ho and a bottle of rum!",
                                  "He drank rum and water.", "Pass the rum.", "Bring me a rum punch.",
                                  "The pirate smelled of rum."])
def test_rum_the_drink_still_found(text):
    assert hit(R.DRINKING, text)


# --- "Bong" is the French "bon" -------------------------------------------------------------
def test_bong_said_in_french_is_not_drugs():
    assert not R.DRUGS(words("Bong is good, said Phyllis. Nous etre bong pour vous."))
    assert not R.DRUGS(words("The clock went bong."))


def test_a_bong_for_smoking_still_found():
    assert R.DRUGS(words("They passed the bong around and smoked weed."))
    assert R.DRUGS(words("He took a hit from the bong."))


# --- beating eggs ---------------------------------------------------------------------------
def test_beat_up_eggs_is_cooking():
    assert not R.VIOLENCE(words("You beat up whites of eggs and mix powdered sugar with them."))
    assert not R.VIOLENCE(words("Beat up the cream until it is stiff."))


def test_beat_up_a_person_still_violence():
    assert R.VIOLENCE(words("The bullies beat up the new boy."))
    assert R.VIOLENCE(words("They beat him up behind the school."))
    assert R.VIOLENCE(words("He got beat up after school."))


# --- "on pain of torture" -------------------------------------------------------------------
def test_on_pain_of_torture_is_a_warning_in_fun():
    assert not R.DISTURBING(words("Don't you let the word pass your lips on pain of torture."))
    assert not R.DISTURBING(words("He swore them to secrecy under pain of torture."))


def test_torture_still_disturbing():
    assert R.DISTURBING(words("The prisoners were put to torture."))
    assert R.DISTURBING(words("They tortured him for days."))


# --- "come hither" --------------------------------------------------------------------------
def test_come_hither_meaning_come_here_is_not_flirting():
    assert not E.flirt_hit(words("Come hither with me, he said, and bring the Roman Chariot."))


def test_a_come_hither_look_is_still_flirting():
    assert E.flirt_hit(words("She gave him a come hither look across the room."))
    assert E.flirt_hit(words("She gave him a come-hither smile."))


# --- screwing up a face ---------------------------------------------------------------------
def test_screwing_her_eyelids_together_is_not_rude():
    assert E.find_language(words("asked Phyllis, screwing her eyelids more tightly together"), E.ALL_CATS) == []
    assert E.find_language(words("He screwed his eyes shut."), E.ALL_CATS) == []


def test_screw_you_still_marked():
    assert E.find_language(words("Screw you, I'm leaving."), ["mild"])
    assert E.find_language(words("He was screwing her behind his wife's back."), ["mild"])


# --- "Sissy" and "boner" in an older book ---------------------------------------------------
def test_sissy_the_name_and_the_broken_boner_left_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["I do believe I'm a bit off my head, Sissy, he said.",
                                  "You can be the broken boner; we can get at your legs more easily.",
                                  "Peter's the broken boner, and I was the doctor."], "old_railway")
    assert book.old_style
    an = R.analyze(book, dict(rude=True, sexual=True, refs=True))
    assert [m["word_raw"] for m in an["mutes"]] == []
    assert [c for c in an["cuts"] if c["kind"] == "ref"] == []


def test_sissy_the_insult_still_marked_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["Don't be such a sissy, said Tom.", "Get away, you Sissy!"], "old_sissy")
    assert book.old_style
    an = R.analyze(book, dict(rude=True))
    assert [m["word_raw"] for m in an["mutes"]] == ["sissy", "Sissy"]


def test_boner_still_marked_in_a_modern_book(tmp_path):
    book = _book(tmp_path, MODERN + ["He made a joke about having a boner."], "modern_boner")
    assert not book.old_style
    an = R.analyze(book, dict(sexual=True))
    assert [m["word_raw"] for m in an["mutes"]] == ["boner"]


# --- brief mentions (the owner, 2026-11-16: "Yes, teach it") -------------------------------
@pytest.mark.parametrize("text", [
    "She can have grapes now, and beef essence and soda-water and milk, and you'd better get in a bottle of brandy.",
    "Mrs. Viney was sent to the village to get as much brandy and soda-water and beef tea as she could buy.",
    "The doctor said to give the invalid a little wine with her dinner.",
    "Mr. Perks made tea in a beer can, as usual.",
])
def test_brandy_for_the_sick_and_a_beer_can_for_tea_are_not_drinking(text):
    assert not R.DRINKING(words(text)), text


@pytest.mark.parametrize("text", [
    "He poured himself a brandy after the doctor left.", "The doctor was drunk on brandy.",
    "They drank wine all evening.", "He opened a beer can and drank it.", "Pots of beer were held in midair.",
    "She sipped her brandy while the patient slept.",
])
def test_real_drinking_still_found(text):
    assert R.DRINKING(words(text)), text


@pytest.mark.parametrize("text", [
    "And everyone would be killed.", "How dreadful if they had all been killed!",
    "You might have been killed.", "He says his father killed a bear.",
    "It sounded exactly like a pig being killed a quarter of a mile off.", "The cat killed a mouse.",
])
def test_killed_when_nobody_is_hurt_is_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


@pytest.mark.parametrize("text", [
    "He killed her with a knife.", "They were killed in the war.", "The soldiers killed the prisoners.",
    "The bear killed the hunter.", "She was killed instantly.",
])
def test_real_killing_still_violence(text):
    assert R.VIOLENCE(words(text)), text


def test_brandy_for_the_sick_told_in_the_sentences_around(tmp_path):
    book = _book(tmp_path, MODERN + [
        "The doctor came and said Mother had a fever and must have beef tea.",
        "Bobbie ran to the village.", "Did you get the brandy?", "I've got the brandy, said Bobbie."],
        "sick_brandy")
    an = R.analyze(book, dict(drinking=True))
    assert [c for c in an["cuts"] if c["kind"] == "drinking"] == []
