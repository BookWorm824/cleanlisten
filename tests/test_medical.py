"""Medical, its own filter after Gore (the owner, 2026-11-12, via CleanView 1.18.62 and 1.18.63: "a lot
of the gore that gets flagged is medical. would it be good to create a separate filter", "autopsies
are medical only for adults though. ticked everywhere else", needles and shots too "but be sure
drugs are separated"). Ticked for Young kids, Kids and Teens, not for Adults; settings saved before
it follow Gore; off, a medical scene isn't cut even with Gore on; on, it's cut even with Gore off."""
import json

import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
import filters as F
from conftest import words

SURGERY = ("The surgeon cut through the abdomen with his scalpel. Blood welled up and spurted across "
           "the drapes. The intestines slid out onto the operating table, slick with blood, and the "
           "nurse clamped the torn flesh while blood gushed from the severed vessel.")
STABBING = ("The killer stabbed her again and again. Blood spattered the walls and gushed across the "
            "floor. Her intestines spilled out through the gash, and blood oozed from the mangled flesh "
            "while the paramedics arrived too late.")
NEEDLE = "The nurse gave him a shot before the dentist slid the needle into his gum."
PLAIN = "They walked home along the river and talked about the summer."
# two scenes a single ordinary paragraph apart are read as one gory stretch, so they're further apart
PARAS = [PLAIN, SURGERY, PLAIN, PLAIN, PLAIN, STABBING, PLAIN, PLAIN, NEEDLE, PLAIN]


def test_the_box_sits_after_gore_and_follows_the_ages():
    violence = next(items for head, _, items in F.SECTIONS if head == "Violence")
    keys = [k for k, _, _ in violence]
    assert keys.index("medical") == keys.index("gore") + 1
    assert F.LABELS["medical"].startswith("Medical  (surgery, autopsies")
    assert [F.PRESETS[p]["medical"] for p in ("young", "kids", "teens", "adults")] == [True, True, True, False]
    assert F.PRESETS["adults"]["gore"]                     # Gore stays ticked for Adults
    assert "medical" in F.listen_kwargs(dict(F.PRESETS["kids"]))["more"]
    assert "medical" not in F.listen_kwargs(dict(F.PRESETS["adults"]))["more"]


def test_saved_settings_follow_gore_until_ticked():
    assert F._upgrade({"gore": True, "graphic": True})["medical"] is True
    assert F._upgrade({"gore": False, "graphic": False})["medical"] is False
    assert F._upgrade({"gore": True, "medical": False})["medical"] is False      # her own tick wins
    assert R._upgrade({"gore": True})["medical"] is True and R._upgrade({})["medical"] is False


@pytest.mark.parametrize("line", [
    "She hated getting her flu shot.", "The nurse gave him a shot.", "The dentist slid the needle into her gum.",
    "They put an IV in his arm.", "The doctor stitched the gash on his forehead.", "He needed stitches.",
    "Mom gave her an insulin injection.", "The nurse drew some blood.", "The scalpel sliced through the skin.",
    "The vet injected her with a sedative."])
def test_needles_and_stitches_are_medical(line):
    assert R.MEDICAL(words(line))


@pytest.mark.parametrize("line", [
    "He shot up in the alley, the needle shaking in his hand.", "The junkie pushed the needle into his arm.",
    "She was in stitches all night.", "The car has fuel injection.", "He took a shot at the title.",
    "He had a shot of whiskey.", "She stitched the hem of her dress.", "An IV bag hung by the bed.",
    "She picked up her pills at the pharmacy.", "The doctor said it was the flu.",
    "He was in the hospital for a week.", "Give it a shot!", "He got his shot at revenge."])
def test_not_medical(line):
    assert not R.MEDICAL(words(line))


def test_drug_needles_stay_drugs():
    assert R.DRUGS(words("He shot up in the alley, the needle shaking in his hand."))


@pytest.mark.parametrize("text,kind", [
    (SURGERY, "medical"),
    ("At the autopsy the pathologist lifted out the blood-slick organs one by one.", "medical"),
    ("The nurse cleaned the bloody gash and the doctor stitched the torn flesh.", "medical"),
    (STABBING, "gore"),                                # an attack, even with paramedics there
    ("Blood gushed from the wound and spattered the floor.", "graphic")])
def test_a_gory_passage_in_a_medical_setting_is_medical(text, kind):
    assert E.gory_kind(words(text)) == kind


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(PARAS), encoding="utf8")
    return R.Book(str(p))


def kinds(an):
    return sorted((c["kind"], c["text"][:12]) for c in an["cuts"])


def test_cleanread_medical_off_gore_on(book):
    an = R.analyze(book, {"gore": True, "graphic": True, "medical": False})
    assert kinds(an) == [("gore", STABBING[:12])]


def test_cleanread_medical_on_gore_off(book):
    an = R.analyze(book, {"gore": False, "graphic": False, "medical": True})
    assert kinds(an) == [("medical", NEEDLE[:12]), ("medical", SURGERY[:12])]


def test_cleanread_settings_from_before_follow_gore(book):
    an = R.analyze(book, {"gore": True, "graphic": True})
    assert {k for k, _ in kinds(an)} == {"gore", "medical"}


def test_cleanread_content_check_has_a_medical_list(book):
    res = R.scan(book)
    med = [it["text"][:12] for it in res["cats"]["medical"]["items"]]
    gore = [it["text"][:12] for it in res["cats"]["gore"]["items"]]
    assert SURGERY[:12] in med and NEEDLE[:12] in med and gore == [STABBING[:12]]


def _listen(tmp_path, monkeypatch, **kw):
    src = tmp_path / "book.mp3"
    src.write_bytes(b"")
    t, out = 0.0, []
    for s in PARAS:
        for w in s.split():
            out.append({"t": w, "s": round(t, 2), "e": round(t + 0.25, 2)})
            t += 0.3
        t += 1.5
    work = tmp_path / "work"
    work.mkdir()
    (work / "transcript.json").write_text(json.dumps({str(src.resolve()): out}))
    monkeypatch.setattr(E, "probe_duration", lambda p: t)
    E.analyze([str(src)], str(work), groups=(), find_sex=False, log=lambda m: None, **kw)
    st = json.loads((work / "analysis.json").read_text())
    scene = {"surgery": SURGERY, "stabbing": STABBING, "needle": NEEDLE}
    # (kind, which scene): a stretch of speech can start a sentence into the scene
    return sorted({(s["kind"], next(n for n, t in scene.items() if s["text"][-30:] in t))
                   for s in st["scenes"]})


def test_cleanlisten_medical_off_gore_on(tmp_path, monkeypatch):
    # the stabbing stretch begins after "The killer stabbed her", so only blood and paramedics are
    # in it: the attack just before still makes it gore
    assert _listen(tmp_path, monkeypatch, find_gore=True, find_graphic=True) == [("gore", "stabbing")]


def test_cleanlisten_medical_on_gore_off(tmp_path, monkeypatch):
    got = _listen(tmp_path, monkeypatch, find_gore=False, find_graphic=False, more=["medical"])
    assert got == [("medical", "needle"), ("medical", "surgery")]


def test_the_ai_and_claude_know_it():
    assert "medical" in E.AI_TYPES and "medical" in cc.KIND_RULES and "medical" in cc.KIND_NAMES
    assert "medical scene" in E.AI_TYPES["gore"] and "medical" in cc.KIND_RULES["graphic"]
    assert "drug use" in E.AI_TYPES["medical"] and "drug use" in cc.KIND_RULES["medical"]


# Coroner, medical examiner, doctor and detective case talk is part of Medical (CleanView 1.18.72 made
# it its own box; for books the owner chose "Part of Medical, no new box", 2026-11-12). With Medical
# off it's left alone, and "sexual" in it isn't muted as a sexual word.
CASE = "Any signs of sexual assault?"


@pytest.mark.parametrize("line", [
    CASE, "She was sexually assaulted before she died.", "He is a registered sex offender.",
    "We found a rape kit in the car.", "She was raped.", "Cause of death was a single blow to the head.",
    "Time of death between ten and midnight.", "The autopsy showed water in her lungs.",
    "Two stab wounds to the chest.", "A gunshot wound to the back.", "Blunt force trauma.",
    "Ligature marks on her neck.", "Lividity says she was moved.", "Rigor mortis has set in.",
    "Defensive wounds on her hands.", "The post-mortem is tomorrow.", "GSW to the abdomen."])
def test_case_talk_is_medical(line):
    assert R.MEDICAL(words(line))


@pytest.mark.parametrize("line", ["I ran a tox screen.", "He'll be fine.", "Time to go home.",
                                  "She's stable now.", "That was a big wound to my pride."])
def test_everyday_talk_isnt(line):
    assert not R.MEDICAL(words(line))


def test_sexual_in_case_talk_isnt_a_sexual_word():
    for line in (CASE, "He is a registered sex offender.", "She was sexually assaulted."):
        assert not E.find_language(words(line), ["sexual"]) and not R._ref_hit(words(line))
    for line in ("They had sex.", "She looked sexy.", "a sexual joke"):
        assert E.find_language(words(line), ["sexual"])
    assert "case talk" in E.AI_TYPES["ref"] and "case talk" in E.AI_TYPES["medical"]
    assert "case talk" in cc.KIND_RULES["ref"] and "case talk" in cc.KIND_RULES["medical"]


def test_case_talk_with_medical_off_and_on(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join([PLAIN, "“" + CASE + "” Beckett asked the coroner.", PLAIN]), encoding="utf8")
    book = R.Book(str(p))
    off = R.analyze(book, {"sexual": True, "refs": True, "medical": False})
    assert not off["cuts"] and not off["mutes"]                 # left alone
    on = R.analyze(book, {"sexual": True, "refs": True, "medical": True})
    assert [c["kind"] for c in on["cuts"]] == ["medical"] and not on["mutes"]
