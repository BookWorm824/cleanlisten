"""Sex drugs are sexual references (CleanView 1.18.15; Lauren, 2026-11-04: "add sexual drugs to
sexual reference filter"): Viagra and the like, aphrodisiacs, drugging someone for sex. The same
lines as CleanView's tests/test_sex_drugs.py."""
import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R

CAUGHT = ("Did you take a Viagra?", "He's on Cialis now", "a little blue pill",
          "Grandpa's little blue pills", "erectile dysfunction", "boner pills",
          "It's an aphrodisiac", "a dash of Spanish fly", "Levitra")
NOT_CAUGHT = ("You take the blue pill, the story ends", "Take two pills with water",
              "a little blue bird", "He sold Spanish flies to fishermen")


def words(text):
    return [E.norm(w) for w in text.split()]


def test_word_list():
    for text in CAUGHT:
        assert E.sex_drug_spans(words(text)), text
    for text in NOT_CAUGHT:
        assert not E.sex_drug_spans(words(text)), text


def test_cleanread_counts_them():
    for text in CAUGHT:
        assert R._ref_hit(words(text)), text
    for text in NOT_CAUGHT:
        assert not R._ref_hit(words(text)), text


def test_the_words_are_not_muted_on_their_own():
    # a passage is cut; "Viagra" isn't a swear word (CleanView's word groups are unchanged)
    # ("boner" was already a sexual word, muted on its own)
    for text in (t for t in CAUGHT if "boner" not in t):
        assert not E.find_language(words(text), ["sexual"]), text


def test_the_readers_are_told():
    for text in (cc.KIND_RULES["ref"], E.AI_TYPES["ref"], R.SCAN_AI["ref"]):
        assert "Viagra" in text and "aphrodisiac" in text
        assert "drugging someone to have sex" in text
