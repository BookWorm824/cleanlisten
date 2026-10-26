"""Word lists and find_language(): what gets muted (CLAUDE.md §5, the family's rules)."""
import pytest

import cleanlisten as E
from conftest import words

EVERY = list(E.ALL_CATS)


def hits(text, cats=EVERY):
    ws = words(text)
    return [(" ".join(ws[i:j]), cat) for i, j, cat in E.find_language(ws, cats)]


# --- the f-word is a hard line; swear words are always found ---------------------------
@pytest.mark.parametrize("text, word, cat", [
    ("What the fuck is this", "fuck", "strong"),
    ("he was fucking furious", "fucking", "strong"),
    ("Motherfucker!", "motherfucker", "strong"),
    ("it's not shit, it's sexual", "shit", "moderate"),
    ("that bastard lied", "bastard", "moderate"),
    ("you asshole", "asshole", "moderate"),
    ("He's such a dick.", "dick", "moderate"),
    ("Damn it all", "damn", "mild"),
    ("What the hell", "hell", "mild"),
    ("This is crap", "crap", "mild"),
])
def test_swear_words_found(text, word, cat):
    assert (word, cat) in hits(text)


@pytest.mark.parametrize("text", [
    "The evidence was damning.",          # incriminating, not a swear
    "the damnation of the soul",
    "She passed the class with honors.",  # 'ass' inside a word
    "He bought an assortment of shells.",
    "Scunthorpe is a town.",
])
def test_innocent_words_not_found(text):
    assert hits(text) == []


# --- bloody: only as a swear ----------------------------------------------------------
def test_bloody_as_swear():
    assert ("bloody", "mild") in hits("You bloody idiot")
    assert ("bloody", "mild") in hits("bloody hell")


def test_bloody_meaning_covered_in_blood():
    assert hits("He dropped the bloody knife") == []


# --- screw: "screw you" yes, "screw it in" no ------------------------------------------
@pytest.mark.parametrize("text", ["Screw you!", "Oh, screw it.", "screw them all"])
def test_screw_as_insult(text):
    assert [c for _, c in hits(text)] == ["mild"]


@pytest.mark.parametrize("text", ["Screw it in tight", "screw it on firmly", "screw the lid on",
                                  "He found a screw on the floor"])
def test_screw_as_hardware(text):
    assert hits(text) == []


# --- God's name: exclamations muted, "thank God" fine ---------------------------------
@pytest.mark.parametrize("text, phrase", [
    ("Oh my God, look", "oh my god"),
    ("Jesus Christ, that hurt", "jesus christ"),
    ("God knows what he did", "god knows"),
    ("for God's sake", "for god's sake"),
    ("Good Lord!", "good lord"),
])
def test_deity_exclamations(text, phrase):
    assert (phrase, "deity") in hits(text)


@pytest.mark.parametrize("text", ["Thank God you're safe.", "She prayed to God every night.",
                                  "They went to church on Sunday."])
def test_thank_god_and_prayer_not_muted(text):
    assert hits(text) == []


def test_longest_phrase_wins():
    # "oh my god" is one hit, not "my god" plus a stray "oh"
    assert hits("oh my god") == [("oh my god", "deity")]


# --- sexual words and "mentions" phrases ----------------------------------------------
@pytest.mark.parametrize("text, phrase", [
    ("He slept with her last year", "slept with her"),
    ("they made love", "made love"),
    ("a one night stand", "one night stand"),
    ("she watched porn", "porn"),
    ("it's not sexual", "sexual"),   # muted even in a denial
])
def test_sexual(text, phrase):
    assert (phrase, "sexual") in hits(text)


def test_sleep_on_its_own_is_fine():
    assert hits("He slept on the couch") == []


# --- only the categories that are switched on ------------------------------------------
def test_categories_filter():
    assert hits("gosh darn it", ["strong", "moderate"]) == []
    assert hits("gosh darn it", ["minced"]) == [("gosh", "minced"), ("darn", "minced")]


def test_orientation_words_only_when_asked():
    assert hits("He is gay", ["strong", "moderate", "mild", "sexual"]) == []
    assert hits("He is gay", ["orientation"]) == [("gay", "orientation")]


# --- the shapes other apps depend on --------------------------------------------------
def test_cats_contract():
    """CleanView/CleanRead mask every CATS category; orientation must stay out of it."""
    assert set(E.CATS) == {"strong", "moderate", "mild", "minced", "deity", "sexual"}
    assert "orientation" in E.EXTRA_CATS
    assert set(E.ALL_CATS) == set(E.CATS) | set(E.EXTRA_CATS)


def test_names_other_apps_import():
    """cleanread.py and cleanview.py import these from the engine (CLAUDE.md §6.3)."""
    for name in ("_tool", "run", "popen", "norm", "mask", "fmt_t", "find_language", "probe_duration",
                 "est_time", "align", "GROUPS", "CATS", "ALL_CATS", "DEFAULT_MODEL", "SR",
                 "tokens_to_words", "snap_edges", "load_recognizer", "sex_score", "is_explicit",
                 "SEX_C", "SEX_WINDOW_SCORE", "GORE_C", "GORE_WINDOW_SCORE", "RELIGION_C",
                 "RELIGION_WINDOW_SCORE", "NO_GOD_PHRASES", "blames_god", "invokes_providence", "strict_religion_hit", "relationship_hit",
                 "crude_hit", "bully_hit", "flirt_hit", "read_ebook", "EbookError", "AI_TYPES", "_c"):
        assert hasattr(E, name), name


# --- small helpers ---------------------------------------------------------------------
def test_norm():
    assert E.norm("“Damn!”") == "damn"
    assert E.norm("God’s") == "god's"
    assert E.norm("'Hello'") == "hello"


def test_mask():
    assert E.mask("fuck") == "f***"
    assert E.mask("Shit!") == "S***"
    assert E.mask("a") == "a"


def test_clean_context_stars_neighbouring_swears():
    raw = "well damn it you shit head he said".split()
    before, after = E.clean_context(raw, [E.norm(w) for w in raw], 1, 2)
    assert before == "well"
    assert "s***" in after and "shit" not in after


# --- which listed words a checker may leave in ----------------------------------------
@pytest.mark.parametrize("word, cat, ok", [
    ("hell", "mild", True),          # the place
    ("bloody", "mild", True),        # covered in blood
    ("ass", "moderate", True),       # a donkey
    ("gay", "orientation", True),    # cheerful
    ("God", "deity", True),          # a sincere prayer
    ("fuck", "strong", False),       # never
    ("shit", "moderate", False),
    ("sexual", "sexual", False),     # even in "it's not sexual"
])
def test_may_untick_word(word, cat, ok):
    assert E.may_untick_word({"cat": cat, "word_raw": word}) is ok
