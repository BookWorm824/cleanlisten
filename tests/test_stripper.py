""""Stripper" the person is a sexual word; the tool and the chemical aren't (the owner, 2026-11-13:
"read the context. like a paint stripper would be ok. but a person stripper isnt. a pole by itself is
fine but with stripper it isn't")."""
import pytest

import cleanlisten as E
import cleanread as R
import filters as F

PERSON = ["She worked nights as a stripper.", "The strippers danced on the stage.",
          "He hired a stripper for the bachelor party.", "Nobody knew the stripper's real name.",
          "Her mother had been a stripper in Vegas.", "A stripper? In this town?"]
TOOL = ["He bought a can of paint stripper.", "Use the wire strippers on that cable.",
        "The stripper took the old varnish right off the table.",
        "Brush the stripper on and wait ten minutes.", "We rented a wallpaper stripper.",
        "She soaked the furniture in chemical stripper.", "He loaded another stripper clip.",
        "Hand me the strippers and the pliers.", "The paper called him an asset stripper."]
POLE_ALONE = ["Santa lives at the North Pole.", "He leaned on the fishing pole.",
              "The flag went up the pole."]


def words(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


def found(line):
    w = words(line)
    return [" ".join(w[i:j]) for i, j, _ in E.find_language(w, ["sexual"])]


@pytest.mark.parametrize("line", PERSON)
def test_a_person_is_muted(line):
    got = found(line)
    assert len(got) == 1 and got[0].startswith("stripper")


@pytest.mark.parametrize("line", TOOL + POLE_ALONE)
def test_the_tool_and_a_pole_alone_are_left(line):
    assert found(line) == []


def test_stripper_and_pole_together_are_both_muted():
    assert found("She slid down the stripper pole.") == ["stripper pole"]
    assert found("The stripper swung around the pole.") == ["stripper"]      # pole alone stays
    assert found("He scraped paint stripper off the pole.") == []


def test_only_with_sexual_words_ticked_and_an_ai_may_mute_it_alone():
    w = words("She worked nights as a stripper.")
    assert E.find_language(w, ["strong", "moderate", "mild", "rude"]) == []
    assert E.listed_word("stripper", ["sexual"]) and not E.listed_word("stripper", ["mild"])


def test_cleanread_marks_out_the_person_and_leaves_the_paint_stripper(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Chapter 1\n\nHer aunt was a stripper in Reno.\n\nDad opened a can of paint "
                 "stripper and brushed it on the old door.\n\nThey walked to the North Pole.\n",
                 encoding="utf8")
    book = R.Book(p)
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = [book.paras[m["para"]].text[m["a"]:m["b"]] for m in an["mutes"]]
    assert hit == ["stripper"]
    assert book.paras[an["mutes"][0]["para"]].text.startswith("Her aunt")
    # the immodest-clothing list reads the context too
    assert R.IMMODEST(words("Her aunt was a stripper in Reno."))
    assert R.IMMODEST(words("Dad opened a can of paint stripper.")) == []
    assert R.IMMODEST(words("She wore a bikini."))                          # the rest as before
    out = tmp_path / "clean.txt"
    R.write_clean(book, [], an["mutes"], out)
    clean = out.read_text(encoding="utf8")
    assert "paint stripper" in clean and "North Pole" in clean and "a stripper in Reno" not in clean
