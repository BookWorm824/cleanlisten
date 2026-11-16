"""The owner's word decisions of 2026-11-16 (CLAUDE.md §5).

A. From her Black Beauty report, about old-fashioned words: "leave all words except pussy. take
   that word out", then "i guess if jerk is used directed towards a person it should come out",
   "but if its a motion should stay. like he jerked the rope", "and dumb if its aninsult".
B. CleanView's Forest Gump lessons (1.18.111: "lets train from this", "Add the 2 words", "any of
   the strip club stuff needs cut for all ages if it is checked"), brought here as words go to
   all three apps.
"""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words


def found(text, cats):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, list(cats))]


def _book(tmp_path, lines, name):
    p = tmp_path / f"{name}.txt"
    p.write_text("\n\n".join(lines), encoding="utf8")
    return R.Book(str(p))


# --- A1. "jerk": out when aimed at a person, left alone when it's a movement -------------------
@pytest.mark.parametrize("text", [
    "You jerk!", "What a jerk.", "He's a jerk.", "Those jerks laughed at me.", "you stupid jerk",
    "That jerk of a husband left her.", "Don't be a jerk at the party.",
    "He's such a jerk on the phone.", "She went out with a jerk like him.",
])
def test_jerk_aimed_at_a_person(text):
    assert [w for w in found(text, ["rude"]) if w.startswith("jerk")], text


@pytest.mark.parametrize("text", [
    "He jerked the rope.",                         # "like he jerked the rope" (never matched)
    "He gave a jerk of his head toward the door.", "With a decided jerk he was free.",
    "There was a sudden jerk and the cart stopped.", "She stopped him with a jerk.",
    "a jerk at the reins", "He gave a jerk at the rein.", "I felt a jerk on the line.",
    "with a sudden jerk", "with one jerk", "with a little jerk", "He gave the rein a jerk.",
    "a quick jerk upon the bridle", "a sharp jerk", "a slight jerk", "a violent jerk",
    "an impatient jerk", "short jerks", "Jerk the rope hard.",
    "He jerks her up by the arm.",                 # the existing guards stay
])
def test_jerk_as_a_movement(text):
    assert not [w for w in found(text, ["rude"]) if w.startswith("jerk")], text


# --- A2. "dumb": out as an insult, left alone when it means unable to speak --------------------
@pytest.mark.parametrize("text", [
    "You're dumb.", "That's dumb.", "What a dumb idea.", "you dumb animal", "You dumb brute!",
    "She is so dumb.",
])
def test_dumb_as_an_insult(text):
    assert "dumb" in found(text, ["rude"]), text


@pytest.mark.parametrize("text", [
    "We should be kind to dumb beasts.", "a poor dumb animal", "our dumb animals",
    "the dumb creatures", "a dumb creature", "dumb brutes", "He was struck dumb.",
    "He was deaf and dumb.", "She stood dumb with fright.", "They sat dumb.",
    "He remained dumb.", "The room fell dumb.", "She was stricken dumb for five seconds.",
    # the classics: speechless with a feeling, and a parlour game
    "Marilla listened in dumb amazement.", "they were all in a kind of dumb stupor",
    "he crouched in dumb patience", "It is something like dumb Crambo.",
    "It was dumb luck.", "the dumb waiter", "Don't play dumb.",      # the existing guards stay
])
def test_dumb_meaning_unable_to_speak(text):
    assert "dumb" not in found(text, ["rude"]), text


# --- A3. "pussy": always out, in every book --------------------------------------------------
@pytest.mark.parametrize("text", ["The pussy cat purred.", "a sprig of pussy willow",
                                  "Here, pussy, pussy!", "He called him a pussy.",
                                  "The pussies were asleep in the barn."])
def test_pussy_always_marked(text):
    assert [w for w in found(text, ["sexual"]) if w.startswith("puss")], text


def test_pussy_not_left_in_by_an_ai():
    # Claude, ChatGPT and the AI helper may only untick words with an innocent meaning
    assert not E.may_untick_word({"cat": "sexual", "word_raw": "pussy"})
    assert not E.may_untick_word({"cat": "sexual", "word_raw": "pussies"})
    assert "pussy" not in E.INNOCENT_NEXT and "pussy" not in E.INNOCENT_PREV


def test_pussy_marked_in_cleanread_even_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["The pussy cat sat by the fire."], "old_pussy")
    assert book.old_style
    an = R.analyze(book, dict(sexual=True))
    assert [m["word_raw"] for m in an["mutes"] if m["on"]] == ["pussy"]


# --- A4. "Dick" the name in an older book --------------------------------------------------
# An older book: old-fashioned words in the dialogue and narration ("'tis", "thee", "hostler")
OLD = ["'Tis a fine morning, said the old hostler, and the horses are fresh.",
       "Thou shalt have thy oats ere long, he said to the mare.",
       "I shan't be long, said James; 'twas only a short way to the farm.",
       "The squire's carriage stood at the door, and the ostler held the horses.",
       "She was gay and merry all the day long.", "The children heard a queer noise in the night."]
MODERN = ["She checked her phone and texted her mom.", "They drove to the mall after school.",
          "The TV was on in the living room.", "He grabbed a soda from the fridge.",
          "I can't believe it, she said. That's so cool.", "Ok, whatever, he said."]


def _dicks(an):
    return [m["word_raw"] for m in an["mutes"] if m["cat"] == "moderate"]


def test_dick_the_name_left_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["Dick, the ploughboy, came running down the lane.",
                                  "The boy they called Dick threw stones at the colts.",
                                  "Thank you, Dick, said the farmer."], "old_dick")
    assert book.old_style
    an = R.analyze(book, dict(swearing=True))
    assert _dicks(an) == []
    assert not any(cat == "moderate" for _, _, cat in book.lang_hits)    # not starred out either


def test_dick_the_insult_still_marked_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["Get away, you Dick!", "Don't be such a Dick.",
                                  "He's a dick, said Tom."], "old_insult")
    assert book.old_style
    assert _dicks(R.analyze(book, dict(swearing=True))) == ["Dick", "Dick", "dick"]


def test_dick_still_marked_in_a_modern_book(tmp_path):
    book = _book(tmp_path, MODERN + ["Dick said he was coming over."], "modern_dick")
    assert not book.old_style
    assert _dicks(R.analyze(book, dict(swearing=True))) == ["Dick"]


# --- B1. the slur "coon(s)" ------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Coons are trying to get into school.",
                                  "Get lost, you big coons!", "that coon"])
def test_coon_slur_marked(text):
    assert [w for w in found(text, ["strong"]) if w.startswith("coon")], text


@pytest.mark.parametrize("text", ["a Maine Coon", "a coon dog", "we went coon hunting",
                                  "the old coon hound", "I haven't seen you in a coon's age",
                                  "a coonskin cap", "Not raccoons, you fool",
                                  "raccoons on the porch", "a coon trap"])
def test_coon_the_animal_left_alone(text):
    assert found(text, ["strong"]) == [], text


# --- B2. "faggotty" with the same-sex words -------------------------------------------------
def test_faggotty():
    assert "faggotty" in found("Get your faggotty ass on the bus.", ["orientation"])
    assert "faggoty" in found("that faggoty little", ["orientation"])


# --- B3. strip clubs are sexual content ------------------------------------------------------
CLUB = [("He took me to a strip club.", "strip club"), ("a striptease", "striptease"),
        ("a strip-tease", "striptease"), ("she gave him a lap dance", "lap dance"),
        ("an exotic dancer", "exotic dancer"), ("pole dancing", "pole dancing"),
        ("a strip joint downtown", "strip joint"), ("the strip shows", "strip shows")]
NOT_CLUB = ["a comic strip", "strip the bed", "the Vegas strip", "a pole vault",
            "a strip of land", "the North Pole", "she danced on his lap"]


@pytest.mark.parametrize("text, word", CLUB)
def test_strip_club_is_a_sexual_word(text, word):
    assert found(text, ["sexual"]) == [word]


@pytest.mark.parametrize("text", NOT_CLUB)
def test_strip_and_pole_left_alone(text):
    assert found(text, E.ALL_CATS) == [], text


def test_strip_club_line_cut_in_cleanread_with_sexual_references(tmp_path):
    for text, _ in CLUB:
        assert R._ref_hit(words(text)), text
    for text in NOT_CLUB:
        assert not R._ref_hit(words(text)), text
    book = _book(tmp_path, MODERN + ["After work they went to a strip club downtown."], "club")
    an = R.analyze(book, dict(refs=True, immodest=True))
    kinds = [c["kind"] for c in an["cuts"]]
    assert kinds == ["ref"]          # one cut, as a sexual reference (not twice with immodest)
    an = R.analyze(book, dict(refs=False))
    assert an["cuts"] == []          # only when it's ticked


# --- old_style: an older book is told by its words, not only "gay"/"queer" ---------------------
# (Before, only "gay"/"queer" told it: of the 12 classics in the phone's library, Treasure Island
# (26 "Dick"s), Heidi and The Swiss Family Robinson weren't old-style; now all 12 are.)
def test_old_style_from_old_words(tmp_path):
    book = _book(tmp_path, [l for l in OLD if "gay" not in l and "queer" not in l] * 2, "archaic")
    assert book.old_style
    # Treasure Island's own few: 'tis, ere, nay, hither, thither, whither (17 in 69,000 words)
    pirate = ["'Tis a long way hither, said the captain.", "Nay, we shall go thither ere dark.",
              "And whither goes the ship?"]
    assert _book(tmp_path, MODERN + pirate, "pirate").old_style
    words = R.Book(str(tmp_path / "pirate.txt")).wn
    assert not R.old_style_book(words + ["word"] * 50000)    # 6 are too few in a long book


def test_old_style_from_project_gutenberg(tmp_path):
    # Standard Ebooks' colophon: "Heidi was published in 1881 by ... for Project Gutenberg"
    book = _book(tmp_path, MODERN + ["This ebook is based on a transcription produced for Project "
                                     "Gutenberg."], "heidi")
    assert book.old_style
    assert not _book(tmp_path, MODERN + ["Gutenberg built a printing press. It was a project."],
                     "press").old_style


@pytest.mark.parametrize("lines", [
    MODERN * 3,
    MODERN + ["Shall we go? she asked. I shan't, he said."],          # one or two old words
    MODERN + ["Tis the season, the sign said.", "Thou shalt not steal, the pastor read."],
    # a Christian novel quoting the Bible: thee, thou, thy, hath, doth don't count
    MODERN + ["The Lord bless thee and keep thee; thou art mine, and thy faith hath made thee "
              "whole, she read. He doth know.", "Whilst we wait, she said."],
    # old words, but "gay" the modern way
    ["Tis true, nay, ere long, hither and thither, he said.", "His gay son and his son's "
     "husband came.", "The gay rights march was loud.", "She's openly gay."],
])
def test_modern_books_stay_modern(tmp_path, lines):
    assert not _book(tmp_path, lines * 2, "modern").old_style
