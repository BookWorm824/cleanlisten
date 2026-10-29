"""Passage and sentence detectors (CLAUDE.md §3.4, rules in §5)."""
import pytest

import cleanlisten as E
from conftest import words


# --- explicit sex: romance, kissing, beds and sheets are fine --------------------------
ROMANCE = ("He kissed her softly and pulled her close. Later they lay in bed under the sheets, "
           "her head on his chest, his lips touching her hair. She shivered and kissed him again.")
EXPLICIT = ("He unbuttoned her blouse and she moaned as he kissed her breasts. Naked, she "
            "straddled him and they began thrusting, her arousal building until her orgasm.")


def test_romance_scores_zero():
    assert E.sex_score(words(ROMANCE)) == 0


def test_explicit_scene_scores_over_threshold():
    assert E.sex_score(words(EXPLICIT)) >= E.SEX_WINDOW_SCORE


def test_one_explicit_word_is_not_enough():
    # sex_score needs two explicit words before anything counts
    assert E.sex_score(words("She was naked in the bath, then kissed him on the lips in bed.")) == 0


# --- gore: mystery-level violence stays; prolonged graphic description goes -----------
@pytest.mark.parametrize("text", [
    "They found the body by the river. He had been stabbed and there was blood on the grass.",
    "The blow had split his skull and blood pooled beneath him.",   # one grim line is fine
    "She bled from a wound on her arm.",
])
def test_mystery_violence_not_gore(text):
    assert E.gore_score(words(text)) == 0


def test_graphic_gore_scores_over_threshold():
    text = ("His entrails spilled out, the severed arm still twitching. Blood gushed and spurted "
            "from the mangled flesh while maggots crawled over the rotting corpse.")
    assert E.gore_score(words(text)) >= E.GORE_WINDOW_SCORE


# --- religion: strict, but brief prayers / grace / church stay -------------------------
@pytest.mark.parametrize("text", [
    "Thank God you're home.",
    "They said grace before dinner.",
    "She prayed for her mother.",
    "We went to church on Sunday.",
])
def test_brief_religion_is_fine(text):
    ws = words(text)
    assert E.religion_score(ws) == 0
    assert not E.blames_god(ws)


def test_preaching_scores_over_threshold():
    text = ("The pastor preached that salvation comes through faith alone. Read the scripture, "
            "repent of your sins, and the Savior will redeem your soul for eternity in heaven.")
    assert E.religion_score(words(text)) >= E.RELIGION_WINDOW_SCORE


@pytest.mark.parametrize("text", [
    "There is no God.",
    "I hate God for taking her.",
    "Where was God when my son died?",
    "I lost my faith after the accident.",
    "God doesn't care about any of us.",
])
def test_blaming_or_denying_god(text):
    assert E.blames_god(words(text))


@pytest.mark.parametrize("text", [
    "The Catholic priest taught that souls in purgatory are helped by the rosary, the "
    "sacraments and the prayers of the saints at Mass.",
    "The monks taught that the Buddha found nirvana, and that following the dharma frees "
    "the soul from karma and reincarnation.",
    "The imam explained the Quran at the mosque during Ramadan, and the rabbi read the "
    "Torah in the synagogue.",
])
def test_other_faiths_score_over_threshold(text):
    assert E.religion_score(words(text)) >= E.RELIGION_WINDOW_SCORE


@pytest.mark.parametrize("text", [
    "Her family was Catholic.",
    "They visited a Buddhist temple on holiday.",
    "The old monastery was now a hotel.",
])
def test_brief_mention_of_a_faith_is_fine(text):
    assert E.religion_score(words(text)) == 0


# --- Providence as God, not the city ----------------------------------------------------
@pytest.mark.parametrize("text", [
    "Providence only knows what will happen.",
    "We must trust in Providence.",
    "Thank Providence you're safe.",
    "It was an act of Providence.",
    "Divine Providence brought them together.",
])
def test_providence_as_god(text):
    assert E.invokes_providence(words(text))


@pytest.mark.parametrize("text", [
    "We drove to Providence on Friday.",
    "She grew up in Providence.",
    "Providence, Rhode Island is cold in winter.",
    "He studied at Providence College.",
    "The city of Providence was quiet.",
])
def test_providence_the_city(text):
    assert not E.invokes_providence(words(text))


# --- same-sex and non-traditional relationships ---------------------------------------
@pytest.mark.parametrize("text", [
    "He introduced me to his husband.",
    "She lives with her wife in Denver.",
    "He kissed him gently.",
    "She kissed her.",
    "They have an open marriage.",
    "He came out as gay last year.",
    "My husband, he said, was the cook.",
    "He was flirting with him all night.",
])
def test_relationship_hit(text):
    assert E.relationship_hit(words(text))


@pytest.mark.parametrize("text", [
    "She introduced me to her husband.",
    "He kissed his wife goodbye.",
    "She kissed her daughter goodnight.",
    "My husband, she said, was the cook.",
    "She was flirting with him.",
])
def test_man_and_woman_is_fine(text):
    assert not E.relationship_hit(words(text))


# --- flirting (off by default, but must not misfire when on) --------------------------
@pytest.mark.parametrize("text", [
    "She was flirting with him at the bar.",
    "He winked at her across the room.",
    "He kept hitting on her.",
    "She batted her eyelashes at him.",
    "What a cheesy pickup line.",
])
def test_flirt_hit(text):
    assert E.flirt_hit(words(text))


@pytest.mark.parametrize("text", [
    "He was flirting with disaster.",
    "She flirted with the idea of moving.",
    "The ball hit him on the head.",
    "He hit on the answer at last.",
    "She checked the car out before buying.",
])
def test_not_flirting(text):
    assert not E.flirt_hit(words(text))


def test_same_sex_flirt():
    assert E.same_sex_flirt(words("He was flirting with him."))
    assert E.same_sex_flirt(words("She winked at her and smiled."))
    assert not E.same_sex_flirt(words("She winked at her sister."))
    assert not E.same_sex_flirt(words("He was flirting with her."))


# --- bullying -------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "You idiot!",
    "You're such a loser.",
    "You fat pig.",
    "Nobody likes you.",
    "They made fun of him every day.",
    "The older boys picked on him.",
    "She mocked her in front of everyone.",
    "He was a bully.",
])
def test_bully_hit(text):
    assert E.bully_hit(words(text))


@pytest.mark.parametrize("text", [
    "The idiot left the door open.",          # not aimed at someone
    "He gave a mocking smile.",
    "She felt humiliated by her mistake.",
    "He was tormented by guilt.",
    "You did a great job.",
])
def test_not_bullying(text):
    assert not E.bully_hit(words(text))


# --- crude humor ----------------------------------------------------------------------
@pytest.mark.parametrize("text", ["He farted in class.", "Pull my finger!", "She picked a booger."])
def test_crude_hit(text):
    assert E.crude_hit(words(text))


@pytest.mark.parametrize("text", ["He went to the bathroom.", "She felt sick after lunch."])
def test_not_crude(text):
    assert not E.crude_hit(words(text))


# --- sentences Lauren KEPT in real books (shared_learned.json) that used to be flagged ----
def test_came_out_to_a_place_is_not_a_relationship():
    assert not E.relationship_hit(words(
        "it's coming up to twelve and i haven't done any work since i came out to my office at nine"))


@pytest.mark.parametrize("text", [
    "He came out to his parents last summer.",
    "She finally came out to her mom.",
    "When he came out to me, I hugged him.",
    "He came out to everyone at dinner.",
])
def test_coming_out_to_people_still_found(text):
    assert E.relationship_hit(words(text))


@pytest.mark.parametrize("text", ["She came out to the car.", "He came out to her car with a coffee.",
                                  "The kids came out to play."])
def test_came_out_to_somewhere_is_fine(text):
    assert not E.relationship_hit(words(text))


@pytest.mark.parametrize("text", [
    "He came out as gay in college.",
    "She came out as a lesbian at twenty.",
    "My cousin is coming out as trans.",
    "He came out as bisexual to his parents.",
])
def test_coming_out_as_still_found(text):
    assert E.relationship_hit(words(text))


@pytest.mark.parametrize("text", [
    "He came out as the winner.",
    "She came out as a better person.",
    "The truth came out as we talked.",
    "The cake came out as flat as a pancake.",
])
def test_came_out_as_something_else_is_fine(text):
    assert not E.relationship_hit(words(text))


def test_swinging_from_a_vine_is_not_a_relationship():
    assert not E.relationship_hit(words("swinging from a vine and dropping into a ravine"))


@pytest.mark.parametrize("text", ["They were swingers.", "The swinging couple next door invited them.",
                                  "They lived a swinging lifestyle."])
def test_swingers_still_found(text):
    assert E.relationship_hit(words(text))


def test_oh_my_god_turned_up_is_not_blaming_god():
    assert not E.blames_god(words(
        "oh my god she says pointing towards the house as if layla has turned up"))


@pytest.mark.parametrize("text", ["God turned his back on me.", "I turned away from God.",
                                  "God has turned away from us."])
def test_god_turning_away_still_found(text):
    assert E.blames_god(words(text))


# --- timing helper used for every cut -------------------------------------------------
def test_span_times_ends_just_before_next_word():
    asr = [{"t": "a", "s": 1.0, "e": 1.2, "part": 0}, {"t": "b", "s": 1.3, "e": 1.5, "part": 0},
           {"t": "c", "s": 1.7, "e": 1.9, "part": 0}]
    s, e = E.span_times(asr, 1, 1)
    assert s == pytest.approx(1.2)   # not earlier than the end of the word before
    assert e == pytest.approx(1.67)  # just before "c" starts


def test_span_times_pads_end_when_there_is_a_pause():
    asr = [{"t": "a", "s": 1.0, "e": 1.2, "part": 0}, {"t": "b", "s": 5.0, "e": 5.2, "part": 0}]
    assert E.span_times(asr, 0, 0) == (pytest.approx(0.85), pytest.approx(1.45))


# --- strict religion (an option): even "thank God", prayers and verses -----------------
@pytest.mark.parametrize("text", [
    "Thank you God for this food.",
    "Thank God you're home.",
    "God bless you, my dear.",
    "The Lord is my shepherd, I shall not want.",
    "For God so loved the world that he gave his only Son.",
    "Grandma is in heaven now.",
    "God willing, we'll be there by noon.",
    "Amen.",
    "She read the Bible every night.",
])
def test_strict_religion_catches(text):
    assert E.strict_religion_hit(words(text))


@pytest.mark.parametrize("text", [
    "She prayed for her mother.",           # generic: prayed, church, grace stay
    "We went to church on Sunday.",
    "They said grace before dinner.",
    "Oh my God, look at that!",             # a swear: the God's-name words mute it
    "Jesus Christ, that hurt!",
    "He read the Lord of the Rings.",
    "My lord, the carriage is ready.",
    "They were a match made in heaven.",
    "Good heavens!",
    "Holy cow!",
    "She had a lot of faith in her team.",
    "My heart gives an almighty thud.",     # from Lauren's kept sentences
])
def test_strict_religion_leaves_generic(text):
    assert not E.strict_religion_hit(words(text))


# --- for young kids: holidays, candles on a birthday cake, magic, dark magic ---------
@pytest.mark.parametrize("kind, text", [
    ("holiday", "Santa brought her a bike."), ("holiday", "We put up the Christmas tree."),
    ("holiday", "They went trick-or-treating."), ("holiday", "He carved a jack-o'-lantern."),
    ("holiday", "She gave him a valentine."), ("holiday", "The kids hunted Easter eggs."),
    ("holiday", "The Easter bunny came."), ("holiday", "A leprechaun guards a pot of gold."),
    ("holiday", "Happy St. Patrick's Day!"), ("holiday", "Rudolph the red-nosed reindeer"),
    ("birthday", "She blew out the candles on her cake."),
    ("birthday", "Blow out your candles and make a wish!"),
    ("birthday", "They lit the birthday candles."),
    ("darkmagic", "The witchcraft of the coven grew."), ("darkmagic", "They used a Ouija board."),
    ("darkmagic", "She put a curse on the village."), ("darkmagic", "a fortune-teller read his palm"),
    ("darkmagic", "They tried to summon the dead."),
    ("magic", "He waved his magic wand."), ("magic", "The wizard cast a spell."),
    ("magic", "She drank the potion."), ("magic", "Her fairy godmother appeared."),
])
def test_kid_topics_found(kind, text):
    assert E.topic_hit(kind, words(text))


@pytest.mark.parametrize("kind, text", [
    ("holiday", "We had turkey for Thanksgiving."), ("holiday", "She boiled some eggs."),
    ("holiday", "The statues of Easter Island."), ("holiday", "Mass at St. Patrick's Cathedral."),
    ("holiday", "They sailed to Ireland."), ("holiday", "Rudolph Hill stood over her."),
    ("birthday", "Happy birthday to you!"), ("birthday", "We had a party with cake."),
    ("birthday", "She lit the candles for dinner."),
    ("darkmagic", "You old witch!"), ("darkmagic", "What am I, psychic?"),
    ("darkmagic", "He cursed under his breath."), ("darkmagic", "Their spirits were high."),
    ("magic", "It was magic."), ("magic", "Say the magic word."),
    ("magic", "Can you spell your name?"), ("magic", "He's a wizard with numbers."),
])
def test_kid_topics_left_alone(kind, text):
    assert not E.topic_hit(kind, words(text))


def test_kid_topics_are_off_unless_ticked_and_the_ai_knows_them():
    for t in E.TOPICS:
        assert t in E.AI_TYPES and t in E.TOPIC_LABELS
    import inspect
    assert inspect.signature(E.analyze).parameters["find_topics"].default == ()
