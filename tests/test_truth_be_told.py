"""Truth Be Told (the owner, 2026-11-24): "there was a lot tagged and not cut ... if it doesn't need
cut why tag so much". The AI on her PC offered 181 lines for her to decide and she ticked none:
"Amelia sprang to her feet." and "Chapter 14" as nudity, "Merrick took a step forward." as living
together, plain lines of a man-and-woman romance as same-sex, an ordinary kiss as innuendo. Now each
of those kinds needs a word of the thing nearby before it's shown; real ones still pass."""
import pytest

import cleanlisten as E
import cleanread as R


def words(s):
    return [E.norm(w) for w in s.split() if E.norm(w)]


DROPPED = [   # (kind, line) from her report: none ticked
    ("nudity", "Amelia sprang to her feet."),
    ("nudity", "A loud snort was Homer’s only response."),
    ("nudity", "Chapter 14"),
    ("nudity", "Ben straightened and tucked his thumb in one pocket."),
    ("nudity", "She clasped her hands together and squeezed until her knuckles turned white."),
    ("unmarried", "Merrick took a step forward."),
    ("unmarried", "So I ran.”"),
    ("unmarried", "“But I’m sure she’ll be joining her mother and me shortly.”"),
    ("sleeping", "off in search of a story without having the decency to sign it—it’s just the kind "
                 "of thing I would expect from you.”"),
    ("flirt", "“Where are my peppermints?”"),
    ("flirt", "A smile of welcome lit Merrick’s face."),
    ("flirt", "It’s good to see you.”"),
    ("gestures", "A deep chuckle rumbled from his chest."),
    ("gestures", "He beat out a light rhythm on the desktop with his fingertips."),
    ("gestures", "Merrick drummed his fingers on the desk for a moment."),
    ("drinking", ". condition I was in this afternoon.”"),
    ("kiss_ss", "Amelia caught her breath."),
]
KEPT = [      # real ones of these kinds still reach the AI's own check
    ("nudity", "He stood there naked in the moonlight."),
    ("implied", "She pulled the sheet up to her chin."),
    ("immodest", "She wore a skimpy bikini to the party."),
    ("unmarried", "They lived together for two years before the baby came."),
    ("unmarried", "My girlfriend kicked me out last week."),
    ("sleeping", "He had been having an affair with his secretary."),
    ("flirt", "A smile creased his face, and he gave Amelia a wink."),
    ("flirt", "He was hitting on her all night."),
    ("gestures", "He gave the driver the finger."),
    ("gestures", "She flipped him off."),
    ("drinking", "Seems like I was always hiding in a bottle."),
    ("drinking", "He drank the whiskey in one gulp."),
    ("smoking", "He lit a cigarette."),
    ("drugs", "She swallowed two of the pills."),
    ("kiss", "She pressed her lips to his."),
]


@pytest.mark.parametrize("kind,line", DROPPED)
def test_her_lines_with_no_sign_are_left_out(kind, line):
    assert not E.ai_gate(kind, [words(line)]), line


@pytest.mark.parametrize("kind,line", KEPT)
def test_real_ones_still_pass(kind, line):
    assert E.ai_gate(kind, [words(line)]), line


def test_a_sign_in_the_next_sentence_counts():
    assert E.ai_gate("drinking", [words("I had to give him time to clean up."),
                                  words("He had been drinking all day.")])


# ---- same-sex: a man-and-woman romance -----------------------------------------------------
MAN_AND_WOMAN = [
    ["“How delightful to see you, my dear.” He leaned over and kissed her on the cheek."],
    ["She wasn’t sure which sickened her more, the sight of him acting that way with a married woman."],
    ["Two matrons stood engrossed in conversation just below where Amelia stood."],
    ["“Papa?”"],
    ["She came out here a few months ago to keep house for him.”"],
    ["“Her mother and I only married recently,” he said."],
    ["He kissed her hand."],
]
SAME_SEX = [
    ["Emma kissed her girlfriend goodnight and closed the door."],
    ["Mark and his husband had been married for ten years."],
    ["Claire leaned over and kissed Mia on the lips."],
    ["Her two moms waved from the porch while her father watched."],
    ["She came out as a lesbian to her father."],
]


def test_her_brother_next_door_doesnt_make_it_a_man_and_a_woman():
    lines = ["Her brother read a book by the fire.", "Claire leaned over and kissed Mia on the lips.",
             "Mia smiled back at her."]
    assert R.couple_ok([words(t) for t in lines], lines, at=1)


def test_the_romance_word_must_be_in_the_suggested_line():
    # her book: a line near a "husband" or "darling" was offered ("Two matrons stood engrossed in
    # conversation", "Papa?"); and "lips" alone isn't romance ("Clara's lips spread in a wide grin")
    for lines in (["When women reach a certain age without finding a husband, they turn desperate.",
                   "Two matrons stood engrossed in conversation."],
                  ["Clara’s lips spread in a wide grin."]):
        assert not R.couple_ok([words(t) for t in lines], lines, at=len(lines) - 1), lines
    lines = ["When women reach a certain age without finding a husband, they turn desperate."]
    assert not R.couple_ok([words(lines[0])], lines, at=0)        # women and a husband


def ok(lines):
    return R.couple_ok([words(t) for t in lines], lines)


@pytest.mark.parametrize("lines", MAN_AND_WOMAN)
def test_a_man_and_a_woman_is_not_a_same_sex_suggestion(lines):
    assert not ok(lines), lines


@pytest.mark.parametrize("lines", SAME_SEX)
def test_same_sex_couples_still_pass(lines):
    assert ok(lines), lines


# ---- innuendo: needs a sign of sex, the body or a come-on ----------------------------------
INNUENDO_DROPPED = ["Don’t let me down.", "Or away from me.", "I plan to stick around here like a burr.",
                    "“I wouldn’t want to put my guardian angel to the test too often.”",
                    "Amelia caught her breath at the memory of his lips, so tantalizingly close to hers.",
                    "With every fiber of her being, she longed to reach up and trace his lips with her "
                    "fingers, feel his strong arms encircle her.",
                    "“Thanks to your meddling, it looks like we have a full afternoon ahead of us.”",
                    "So you could worm your way into my good graces?”"]
INNUENDO_KEPT = ["Like this evening, when he made a show of complimenting her appearance, eyeing her as "
                 "though looking through her dress, not at it.",
                 "His eyes traveled down the front of her bodice.",
                 "So far, his intrusion had been nothing more than suggestive words.",
                 "“Take your pants off!” she called from the bedroom, laughing.",
                 "“You look sexy in that,” he said.", "That’s code for ‘do me.’",
                 "Want to come up for a nightcap?"]


@pytest.mark.parametrize("line", INNUENDO_DROPPED)
def test_plain_romance_is_not_innuendo(line):
    assert not E.innuendo_sign(words(line)), line


@pytest.mark.parametrize("line", INNUENDO_KEPT)
def test_real_innuendo_still_reaches_the_check(line):
    assert E.innuendo_sign(words(line)), line


def test_sexual_talk_skips_a_line_with_no_sign():
    texts = ["Don’t let me down.", "“You look sexy in that,” he said."]
    asked = []

    def ask(prompt, schema, timeout):
        if '"sexual"' in prompt:
            return {"sexual": True}
        if '"lines"' in prompt:
            return {"lines": [{"n": 1, "words": "Don’t let me down."},
                              {"n": 2, "words": "You look sexy in that"}]}
        asked.append(prompt)
        return {"fits": True}
    assert E.sexual_talk(texts, ask, "a sexual reference") == {1}
    assert len(asked) == 1          # the plain line wasn't even asked about


# ---- the word lists: a feeling that "stabs" or "assaults" isn't violence --------------------
@pytest.mark.parametrize("line", ["The thought stabbed at her heart.",
                                  "The headache she'd been fighting since midmorning assaulted her temples.",
                                  "The stench assaulted his nostrils.",
                                  "A sharp pain stabbed through her side."])
def test_a_feeling_that_stabs_is_not_violence(line):
    assert not R.VIOLENCE(words(line)), line


@pytest.mark.parametrize("line", ["He stabbed her heart with a knife.", "He stabbed her in the back.",
                                  "The man assaulted her in the alley.", "He stabbed the guard."])
def test_real_stabbing_still_counts(line):
    assert R.VIOLENCE(words(line)), line
