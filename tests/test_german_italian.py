"""German and Italian in CleanListen and CleanRead, as CleanView 1.18.145 (the owner, 2026-11-19:
"i think german , italian, espanola"; Spanish was already in). cvlang.py is CleanView's file,
byte for byte. German umlauts and ß are written out before matching ("schwül", humid, isn't
"schwul"); Italian joined-on short words come off ("dell'idiota" is "idiota"). Dutch is now the
language the listening model hears that has no lists. No native speaker has checked the lists."""
import pytest

import cleanlisten as E
import cleanlisten_learn as L
import cleanread as R
import cvlang
import filters as F
from conftest import words

EVERY = ["strong", "moderate", "mild", "minced", "deity", "sexual", "orientation", "rude"]

GERMAN = ("Es regnete die ganze Nacht. Max rief: Scheiße, was war das? Sein Bruder sagte: halt die "
          "Klappe, du Vollidiot. Oh mein Gott, sagte die Oma, dieser Hurensohn hat das Geld genommen. "
          "Es war heute so schwül, und der Bauer fuhr den Mist aufs Feld.")
ITALIAN = ("Piovve tutta la notte. Marco gridò: merda, che cazzo era? Il fratello rispose: stai zitto, "
           "idiota. Oh mio Dio, disse la nonna, quel figlio di puttana ha preso i soldi. Poi mangiarono "
           "il finocchio in insalata e tornarono a casa.")


@pytest.fixture(autouse=True)
def back_to_english():
    yield
    E.use_language("en")


def found(text, cats=EVERY):
    ws = words(text)
    return [(" ".join(ws[i:j]), cat) for i, j, cat in E.find_language(ws, cats)]


def test_both_are_on_the_list():
    assert cvlang.LANGS["de"] == "German" and cvlang.LANGS["it"] == "Italian"


def test_german_words_by_our_groups():
    E.use_language("de")
    got = dict(found(GERMAN))
    assert got["scheisse"] == "moderate" and got["vollidiot"] == "rude"
    assert got["halt die klappe"] == "rude" and got["oh mein gott"] == "deity"
    assert got["hurensohn"] == "strong"
    assert not {"schwuel", "mist", "geld", "oma"} & set(got)       # humid; the manure on the field
    assert E.mask("Scheiße") == "S******"
    assert E.listed_word("Scheiße", ["moderate"]) and not E.listed_word("Haus", EVERY)


def test_italian_words_by_our_groups():
    E.use_language("it")
    got = dict(found(ITALIAN))
    assert got["merda"] == "moderate" and got["cazzo"] == "strong" and got["puttana"] == "strong"
    assert got["stai zitto"] == "rude" and got["idiota"] == "rude" and got["oh mio dio"] == "deity"
    assert not {"finocchio", "casa", "soldi", "nonna"} & set(got)   # fennel in the salad
    assert found("Vai all'inferno") == [("vai inferno", "mild")]    # "all'" comes off
    assert E.mask("cazzo") == "c****"


def test_each_language_keeps_to_its_own_list():
    E.use_language("de")
    assert found("Vaffanculo, cazzo, mierda") == []
    E.use_language("it")
    assert found("Scheiße, Arschloch, putain") == []
    E.use_language("en")
    assert found("What the hell, you idiot.") == [("hell", "mild"), ("idiot", "rude")]
    assert found(GERMAN) == []


def test_a_german_line_is_remembered_as_itself():
    E.use_language("de")
    assert R.item_key("Halt die Klappe!") == "halt die klappe"
    assert L.norm("Halt die Klappe!") == "halt die klappe"


def test_a_german_ebook_through_cleanread(tmp_path):
    p = tmp_path / "buch.txt"
    p.write_text("Kapitel 1\n\n" + GERMAN + "\n", encoding="utf8")
    book = R.Book(p, "de")
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = {book.paras[m["para"]].text[m["a"]:m["b"]].lower() for m in an["mutes"]}
    assert {"scheiße", "vollidiot", "hurensohn"} <= hit
    assert not {"schwül", "mist", "oma"} & hit
    out = tmp_path / "sauber.txt"
    R.write_clean(book, [], an["mutes"], out)
    clean = out.read_text(encoding="utf8")
    assert "Scheiße" not in clean and "Hurensohn" not in clean
    assert "Es regnete die ganze Nacht." in clean and "so schwül" in clean


def test_an_italian_ebook_through_cleanread(tmp_path):
    p = tmp_path / "libro.txt"
    p.write_text("Capitolo 1\n\n" + ITALIAN + " Che faccia dell'idiota!\n", encoding="utf8")
    book = R.Book(p, "it")
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = [book.paras[m["para"]].text[m["a"]:m["b"]].lower() for m in an["mutes"]]
    assert {"merda", "cazzo", "puttana"} <= set(hit)
    assert any("idiota" in h for h in hit if "dell" in h or h == "idiota")
    assert not {"finocchio", "casa"} & set(hit)
    out = tmp_path / "pulito.txt"
    R.write_clean(book, [], an["mutes"], out)
    clean = out.read_text(encoding="utf8")
    assert "cazzo" not in clean and "puttana" not in clean and "Piovve tutta la notte." in clean


def test_dutch_is_left_for_her_to_choose(tmp_path):
    nl = ("De oude man zat in de keuken en hij keek naar de kinderen die met een bal op het plein "
          "speelden. Het was een mooie dag en zij wilden niet naar huis.")
    (tmp_path / "nl.txt").write_text("\n\n".join([nl] * 20), encoding="utf8")
    assert E.guess_language(tmp_path / "nl.txt") is None
