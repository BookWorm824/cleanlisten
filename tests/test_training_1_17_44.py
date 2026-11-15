"""False alarms found in a training run (the owner, 2026-11-15: "can you do an in depth training on
clean read"): CleanRead with every filter on over A Candle in Her Heart and her own children's
stories. Each one is fixed without losing the real ones."""
import pytest

import cleanlisten as E
import cleanread as R


def w(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


NOT = [
    ("drugs", "Could he be bribed if the price were high enough?"),
    ("drugs", "Sparks were shooting up from the top of the bridge now."),
    ("drugs", "Flames were shooting up from the river."),
    ("drugs", "Grace's head shot up."),
    ("drugs", "Her hand shot up before the teacher finished the question."),
    ("smoking", "There were smoked turkey, baked ham,"),
    ("smoking", "They walked through the smoking ruins."),
    ("drinking", "Tonight, there was a mammoth bowl of shrimp on ice with pungent cocktail sauce."),
    ("drinking", "Crabmeat cocktail was followed by a clear soup"),
    ("drinking", "He threw a Molotov cocktail at the tank."),
    ("drinking", "Eli Whitney invented the cotton gin."),
    ("nudity", "He looked up and met Harrison's eyes, read the naked hostility in them."),
    ("nudity", "such naked hatred in his green eyes that Shaw was startled"),
    ("nudity", "My naked arms had nowhere to hide."),
    ("violence", "without going through all that hocus-pocus, punching clocks, and all that."),
    ("violence", "He punched the button for the fifth floor."),
    ("violence", "Frank shot him a quick look."),
    ("violence", "medium-wide farmyard shot at sunset,"),
]
STILL = [
    ("drugs", "He was shooting up heroin in the alley."),
    ("drugs", "She was high again."),
    ("drugs", "They got high behind the gym."),
    ("drugs", "He was high as a kite."),
    ("drugs", "I think he's high."),
    ("drugs", "He smoked pot every day."),
    ("smoking", "He smoked a pipe after dinner."),
    ("smoking", "She smoked."),
    ("smoking", "Smoking is bad for you, the doctor said."),
    ("smoking", "Donald lighted a cigarette slowly."),
    ("drinking", "He mixed her a cocktail."),
    ("drinking", "They met for cocktails at six."),
    ("drinking", "She ordered a gin and tonic."),
    ("nudity", "James and Dan stood naked and unashamed."),
    ("nudity", "He ran naked through the yard."),
    ("violence", "He punched Henry in the nose."),
    ("violence", "She was punched in the face."),
    ("violence", "He shot him dead."),
    ("violence", "They shot at the soldiers."),
    ("violence", "The deserter was shot at dawn."),
    ("violence", "He shot him in the leg."),
]


@pytest.mark.parametrize("kind,s", NOT)
def test_not_flagged(kind, s):
    assert not E.sentence_hit(kind, w(s))


@pytest.mark.parametrize("kind,s", STILL)
def test_still_flagged(kind, s):
    assert E.sentence_hit(kind, w(s))


def test_substances_in_the_content_check_too():
    assert not R.SUBSTANCES(w("There were smoked turkey, baked ham, and shrimp cocktail."))
    assert R.SUBSTANCES(w("He smoked and drank cocktails all night."))


def test_crude():
    for s in ["mooning like a lovesick schoolgirl.", "I mooned around her for months",
              "She longed for the tooting of boats signaling in the East River."]:
        assert not E.crude_hit(w(s)), s
    for s in ["They mooned the bus.", "Somebody tooted and everyone laughed.", "He farted."]:
        assert E.crude_hit(w(s)), s


@pytest.mark.parametrize("s", ["If I know anything about my own sex, she is a woman who is all set to pounce.",
                               "She was popular with members of the opposite sex.",
                               "the battle of the sexes", "the others of my sex"])
def test_sex_meaning_men_or_women(s):
    assert not E.find_language(w(s), ["sexual"])
    assert not R._ref_hit(w(s))


@pytest.mark.parametrize("s", ["They talked about her sex life.", "They had sex.",
                               "Sex is all he thinks about."])
def test_sex_still(s):
    assert E.find_language(w(s), ["sexual"])


def test_fool_as_a_verb_or_idiom():
    for s in ["You are too honest to try to fool yourself or to fail to face the facts.",
              "You can't fool me.", "I mooned around her for months, making a complete fool of myself."]:
        assert not E.find_language(w(s), ["rude"]), s
    for s in ["Don't be a fool.", "You fool!", "The old fool!", "Don't be a little idiot."]:
        assert E.find_language(w(s), ["rude"]), s


# The content check, from her own "Not a problem" choices (Wings of a Dream)
SCAN = {x[0]: x[-1] for x in R.SCAN}
SCAN_CASES = [
    ("lying", False, "Tears stole down my cheeks."),
    ("lying", False, "Humiliation stole over me, burning my face."),
    ("lying", False, "That he trusted me with such knowledge stole my breath."),
    ("lying", False, "You truly stole their hearts during your short stay."),
    ("lying", False, "I noticed Ollie Elizabeth then, stealing along the side porch."),
    ("lying", False, "He clasped his hands behind his back."),
    ("lying", False, "Virgil crouched with one hand behind his back in the center circle."),
    ("lying", False, "My gaze held Frank's. He wouldn't lie to me."),
    ("lying", True, "He stole a car."),
    ("lying", True, "She stole money from her mother's purse."),
    ("lying", True, "Don't lie to me!"),
    ("lying", True, "They talked about her behind her back."),
    ("lying", True, "Someone has been stealing cookies."),
    ("scary", False, "The whistle shrieked, the timekeeper waving his arms overhead."),
    ("scary", True, "A scream."),
    ("scary", True, "She shrieked in terror."),
    ("death", False, "Mama said you were leaving, Mr. Graves."),
    ("death", False, "I'd ridden with Barney Graves in his Model T once."),
    ("death", True, "They dug two graves under the oak."),
    ("death", True, "She visited her mother's grave."),
]


@pytest.mark.parametrize("kind,want,s", SCAN_CASES)
def test_content_check(kind, want, s):
    assert bool(SCAN[kind](w(s))) is want


@pytest.mark.parametrize("want,s", [
    (False, "I’m in the closet."),                     # Camp Club Girls: a girl hiding
    (False, "She heard the click of the office door opening, then saw light beneath the crack in "
            "the closet door."),
    (False, "Jessie came out of the closet with a broom."),
    (False, "Benny hid in the closet."),
    (True, "He was still in the closet when he met Tom."),
    (True, "She came out of the closet at sixteen."),
    (True, "He stayed in the closet for years."),
    (True, "He'd been in the closet for years before he told his parents."),
])
def test_in_the_closet(want, s):
    assert E.relationship_hit(w(s)) is want
    assert R.rel_hit(w(s)) is want


@pytest.mark.parametrize("want,s", [
    (False, "Quietly, Elizabeth tiptoed to the door, shut it softly, and turned the lock."),
    (False, "He shut it behind him."),
    (True, "Shut it!"),
    (True, "Oh, shut it, Tom."),
    (False, "Sometimes it’s best just to play dumb,"),
    (False, "Play dumb?"),
    (False, "He played dumb when they asked."),
    (True, "You’re so dumb."),
])
def test_shut_it_and_play_dumb(want, s):
    assert bool(E.find_language(w(s), ["rude"])) is want


@pytest.mark.parametrize("s", ["What a fool you are!", "Such a fool you are", "You old fool, you!"])
def test_calling_someone_a_fool_still_counts(s):
    # 1.17.45, from CleanView 1.18.106: the 1.17.44 verb guard let these through
    assert E.find_language(w(s), ["rude"])
