"""CleanRead's word lessons from the 2026-11-03 reports (Wings of a Dream, Playing by Heart, All
That Glitters; CleanView 1.18.11): nudity words about something other than a body, and God's
name phrases across a full stop."""
import cleanread as R


def nude(text):
    w = [R.nrm(t) for t in text.split() if R.nrm(t)]
    return bool(R.NUDITY(w))


def test_nudity_words_about_something_else():
    for t in ["They drove off in a topless automobile.", "My discomfort stood naked.",
              "The fear in her eyes naked for all to see.", "You can see it with the naked eye.",
              "That is the naked truth.", "A naked blade gleamed."]:
        assert not nude(t), t
    for t in ["She was a topless dancer.", "He stood naked and unashamed.", "They were naked.",
              "She sunbathed topless on the beach.", "He was stark naked."]:
        assert nude(t), t


def test_gods_name_not_matched_across_a_full_stop(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Chapter One\n\nHelp me, Lord. Help me now, I prayed.\n\nLord help me, I will strangle him.\n",
                 encoding="utf8")
    book = R.Book(str(p))
    found = [" ".join(book.wn[i:j]) for i, j, _ in R.E.find_language(book.wn, ["deity"], breaks=book.breaks)]
    assert found == ["lord help me"]
    assert len(book.lang_hits) == 1
