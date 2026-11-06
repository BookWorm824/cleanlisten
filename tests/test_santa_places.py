"""Santa before a place name isn't Christmas (CleanView 1.18.20; Jason, That Thing You Do:
"Santa Anita" and "Santa Monica" were flagged as Christmas), nor is Christmas Island."""
import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R


def words(text):
    return [E.norm(w) for w in text.split()]


CAUGHT = ("Santa Claus is coming.", "Santa!", "Santa and his elves.", "Jiminy Christmas.",
          "Christmas in July.", "We'll see Santa at the mall.", "Merry Xmas")
NOT_CAUGHT = ("We drove out to Santa Anita for the races.", "A gig in Santa Monica.",
              "Santa Barbara is lovely.", "They flew to Santa Fe.", "Christmas Island is far away.",
              "Santa Cruz boardwalk.")


def test_christmas_words():
    for text in CAUGHT:
        assert E.topic_hit("holiday", words(text)), text
    for text in NOT_CAUGHT:
        assert not E.topic_hit("holiday", words(text)), text


def test_cleanread_uses_the_same_words():
    hit = next(fn for k, _, fn in R.SCAN if k == "holiday") if any(
        row[0] == "holiday" for row in R.SCAN) else (lambda w: E.topic_hit("holiday", w))
    assert hit is not None
    assert E.topic_hit("holiday", words("A gig in Santa Monica.")) is False


def test_the_readers_are_told():
    for text in (E.AI_TYPES["holiday"], cc.KIND_RULES["holiday"]):
        assert "Santa Anita" in text and "Christmas Island" in text
