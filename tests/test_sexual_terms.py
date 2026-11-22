"""CleanView 1.18.127's researched sexual words, carried over (the owner, 2026-11-17: "do research on words
that world uses as innuendo/sexual terms - do nitty gritty research - make sure all are on our list",
"pass on to the others"), with the book meanings CleanView's TV lines never meet left alone, and the older
meanings found by running the lists over the 24 classics left in older books."""
import time

import pytest

import cleanlisten as E
import cleanread as R


def words(text):
    return [w for w in (E.norm(t) for t in text.split()) if w]


def found(text, cats=None):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, cats or list(E.PHRASES) + ["orientation"])]


@pytest.mark.parametrize("text", [
    "She gave him a handjob.", "He went down on her.", "I'd tap that.", "Did you get laid?",
    "Get your freak on!", "They were knocking boots all night.", "Netflix and chill?", "He got a hard-on.",
    "He was rubbing one out.", "He wanted to jump her bones.", "Stop flogging the dolphin.",
    "I want to shag you.", "She's a call girl.", "They met at a brothel.", "Is that porno?",
    "No more schtupping my wife.", "What a schlong.", "You're a gigolo?", "I'm dying to cop a feel.",
    "Which makes you sloppy seconds.", "He's running an escort service.", "We tried the reverse cowgirl.",
    "That was orgasmic.", "He has a foot fetish.", "Death by coitus.", "Smash or pass?", "Thirst trap.",
    "They found a vibrator.", "Shagging in the shed.", "He couldn't get it up.", "cum on the sheets",
    "trying to get in her pants", "a peeping Tom", "You have an atrophied testicle.", "It was a gang bang.",
    "a gangbang video", "They gang-banged her.", "She is bi-curious.", "He's a twink.", "a wild orgy",
])
def test_caught(text):
    assert found(text), text


@pytest.mark.parametrize("text", [
    "He has a shag carpet.", "She graduated summa cum laude.", "We beat off the attackers.",
    "Don't be so hard on yourself.", "He'll eat her out of house and home.", "Let's get a head start.",
    "He tried to pervert the course of justice.", "Twinkies for lunch.", "She wore a shaggy coat.",
    "I'll whack off the dead branches.", "They live in South Carolina.", "Hello, Carol.",
    "The cumin is in the cupboard.", "He was a gangbanger in LA.",
    # books
    "He swung his leg over the fence.", "They laid the pipe to the house.", "We made up a foursome for golf.",
    "She patted the little head.", "The sun went down on them.", "The car jerked off the road.",
    "She got into her pants and boots.", "the male members of the family", "the purple-headed mountain",
    "an orgy of eating", "Anne suddenly went down on her knees.", "going down on her hands and knees",
    "She tidies the room.", "They set face to face, sitting in the heather.", "a bit on the side of the road",
    "the ice rimming the pond", "her rosy palm", "the girl on top of the wall",
])
def test_left(text):
    assert not found(text), text


def test_sleeping_around_and_case_talk():
    for text in ("He is a womanizer.", "Accused of adultery.", "She's his side chick.",
                 "He's sowing his wild oats.", "They have an open marriage."):
        assert R.SLEEPING(words(text)), text
    for text in ("He was a pedophile.", "a convicted child molester", "Charged with indecent exposure.",
                 "bestiality and incest"):
        assert R.FORENSIC(words(text)), text
    # "molest" meaning bother, as older books use it, isn't case talk
    assert not R.FORENSIC(words("No one shall molest you on the road."))


@pytest.mark.parametrize("text", [
    "Well, for goodness' sakes! ejaculated Elizabeth Ann.", "Well, I sort of boffed, said Tigger.",
    "If there ain't no better way, cum over here.", "She puts too much lovemaking into her stories.",
    "the idle trollops", "Hannah knocked up a couple of pies.", "you hussy, how dare you",
    "It was a good lay, some of you pretty handy.", "I could easily have my way with him.",
    "bid you pleasure yourself with your dream", "breeches of black shag", "an orgy was beginning",
    "the smutty rabble",
])
def test_older_meanings_left_in_an_older_book(text):
    ws = words(text)
    assert not R._ref_hit(ws, old_style=True), text
    assert R._ref_hit(ws, old_style=False) or not found(text, ["sexual"]), text


def test_philandering_in_an_older_book_is_dawdling():
    assert not R.old_sleeping_hit(words("we mustn't stand philandering here"), True)
    assert R.old_sleeping_hit(words("we mustn't stand philandering here"), False)


def test_still_quick():
    ws = words("What did you say to the man at the door last night?")
    t = time.perf_counter()
    for _ in range(2000):
        E.term_spans(ws, E.SEXUAL_TERMS_RX)
        E.term_spans(ws, E.CASUAL_TERMS_RX)
    assert time.perf_counter() - t < 2.0


def test_sexual_release_criminal_minds():
    # CleanView 1.18.136 (Criminal Minds S1E8)
    assert "sexual release" in found("Is it the only thing that can give you a sexual release?")
