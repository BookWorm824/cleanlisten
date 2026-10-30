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


# --- slang for a man's private parts: only the slang word, only in slang phrases -------
@pytest.mark.parametrize("text, word", [
    ("Grow some stones, Carter.", "stones"),
    ("He finally had the stones to ask her out.", "stones"),
    ("She kicked him right in the nuts.", "nuts"),
    ("Quit busting my balls.", "balls"),
    ("It's cold enough to freeze my nuts off.", "nuts"),
    ("They found the body, cut his balls off.", "balls"),   # one Lauren muted by hand
    ("Man up and grow a pair.", "pair"),
    ("That took brass balls.", "balls"),
    ("Nobody has the cojones to say it.", "cojones"),
])
def test_body_slang_muted(text, word):
    assert hits(text) == [(word, "moderate")]


@pytest.mark.parametrize("text", [
    "They skipped stones across the lake.",
    "He took the stones to the garden.",
    "They lifted the stones to build a wall.",
    "She bought a bag of nuts.",
    "The squirrel hid nuts in the tree.",
    "The kids threw tennis balls.",
    "She grew a pair of tomato plants.",
    "He grew some stones in his kidney.",
])
def test_body_slang_words_in_everyday_use(text):
    assert hits(text) == []


def test_body_slang_is_swearing():
    assert hits("Grow some stones.", ["mild", "deity", "sexual"]) == []


# --- fruit and vegetables for body parts: only in these phrases, only the slang word ----
@pytest.mark.parametrize("text, muted", [
    ("Check out those melons!", ["melons"]),
    ("Nice pair of cantaloupes", ["cantaloupes"]),
    ("He was staring at her coconuts", ["coconuts"]),
    ("Look at them big melons", ["melons"]),
    ("Her huge melons", ["melons"]),
    ("You popped her cherry?", ["cherry"]),
    ("I lost my cherry at prom", ["cherry"]),
    ("She kneed him in the grapes", ["grapes"]),
    ("Kicked me right in the plums", ["plums"]),
    ("hit him in the franks and beans", ["franks", "beans"]),
    ("He zipped his franks and beans", ["franks", "beans"]),
    ("freezing my grapes off out here", ["grapes"]),
    ("Is that a banana in your pocket?", ["banana"]),
    ("a cucumber in his pants", ["cucumber"]),
    ("Look at her tight buns", ["buns"]),
    ("his juicy peach", ["peach"]),
    ("kicked him in the meat and two veg", ["veg"]),
])
def test_fruit_slang_muted(text, muted):
    assert hits(text) == [(w, "moderate") for w in muted]


@pytest.mark.parametrize("text", [
    "These melons are ripe", "Check out these melons, only a dollar", "a slice of watermelon",
    "grapefruit for breakfast", "cherry pie", "She lost her cherry pie recipe",
    "the cherry on top", "a bunch of grapes", "We grew plums and beans",
    "pass the franks and beans", "meat and two veg for dinner",
    "I kept a carrot in my pocket for the horse", "a banana in my lunchbox", "a juicy peach",
    "hot cross buns", "She wore her hair in buns", "climbing for coconuts",
    "popped a cherry tomato in her mouth", "a big pair of shoes",
])
def test_fruit_words_in_everyday_use(text):
    assert hits(text) == []


def test_fruit_slang_is_swearing():
    assert hits("Check out those melons!", ["mild", "deity", "sexual"]) == []


# --- "that's bull": short for bullshit, mild; never the animal ---------------------------
@pytest.mark.parametrize("text", [
    "That's bull!", "That is bull and you know it", "What a load of bull", "This is total bull",
    "Cut the bull, Castle", "It's all bull", "You're full of bull", "a bunch of bull",
    "That's complete bull", "no more bull", "thats bull",
])
def test_bull_for_bullshit(text):
    assert hits(text) == [("bull", "mild")]


def test_bull_split_from_its_ending():
    assert hits("that's bull shit") == [("bull", "mild"), ("shit", "moderate")]
    assert hits("total bull crap") == [("bull", "mild"), ("crap", "mild")]


def test_bull_is_moderate_when_only_moderate_is_ticked():
    assert hits("That's bull!", ["moderate"]) == [("bull", "moderate")]
    assert hits("That's bull!", ["sexual", "deity"]) == []


@pytest.mark.parametrize("text", [
    "The bull charged at him", "That's bull riding for you", "That's a bull, not a cow",
    "a bull market", "It's a pit bull", "like a bull in a china shop",
    "take the bull by the horns", "the Chicago Bulls", "That's bull terrier hair",
    "a bull's eye", "is that bull dangerous", "Sitting Bull", "a red bull",
])
def test_bull_the_animal(text):
    assert hits(text) == []


# --- more swearing and crude slang (from CleanView's TV and film lists) -----------------
@pytest.mark.parametrize("text, word, cat", [
    ("What a sweet-ass deal.", "sweetass", "moderate"),
    ("You sumbitch.", "sumbitch", "moderate"),
    ("Don't be such an a-hole.", "ahole", "moderate"),
    ("He's a total dickwad.", "dickwad", "moderate"),
    ("What a dbag.", "douchebag", "moderate"),
    ("Eff you, buddy.", "eff you", "moderate"),
    ("S O B, that hurt.", "s o b", "moderate"),
    ("That's some bullcrap.", "bullcrap", "mild"),
    ("Frak, we're late.", "frak", "minced"),
    ("Christ almighty, look at that.", "christ almighty", "deity"),
    ("She called him a pussy.", "pussy", "sexual"),
    ("WTF is this?", "wtf", "strong"),
])
def test_more_slang_found(text, word, cat):
    assert (word, cat) in hits(text)


@pytest.mark.parametrize("text", [
    "Moby Dick is a long book.",
    "She graduated summa cum laude.",
    "The pussy cat purred.",
    "They polished the brass door knockers.",
    "General Hooker led the army.",
    "The family jewels were stolen.",
    "Her damning evidence and his damnation.",   # left alone on purpose
    "Thank God you're safe.",                     # CleanListen keeps "thank God"
])
def test_more_slang_innocent_uses(text):
    assert hits(text) == []


def test_slurs_are_strong():
    assert [c for _, c in hits("He called them wetbacks.")] == ["strong"]


# --- rude words kids copy: only when that box is ticked --------------------------------
@pytest.mark.parametrize("text, found", [
    ("You stupid jerk, shut up!", ["stupid", "jerk", "shut up"]),
    ("That sucks.", ["that sucks"]),
    ("What a dummy.", ["dummy"]),
])
def test_rude_words(text, found):
    assert [w for w, c in hits(text, ["rude"])] == found
    assert hits(text) == []                       # not part of the swearing groups


@pytest.mark.parametrize("text", [
    "Shut it down now.",
    "She was shut up in the attic.",
    "He jerks the door open.",
    "Don't fool around.",
    "Cigarette butts were everywhere.",
    "He was deaf and dumb.",
    "It was a crash test dummy.",
])
def test_rude_words_everyday_uses(text):
    assert hits(text, ["rude"]) == []


def test_rude_is_its_own_group():
    assert E.GROUPS["rude"] == ["rude"] and "rude" not in E.ALL_CATS


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
                 "RELIGION_WINDOW_SCORE", "NO_GOD_PHRASES", "blames_god", "invokes_providence",
                 "strict_religion_hit", "body_slang", "relationship_hit",
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
    ("stones", "moderate", True),    # skipping stones
    ("gay", "orientation", True),    # cheerful
    ("God", "deity", True),          # a sincere prayer
    ("fuck", "strong", False),       # never
    ("shit", "moderate", False),
    ("sexual", "sexual", False),     # even in "it's not sexual"
])
def test_may_untick_word(word, cat, ok):
    assert E.may_untick_word({"cat": cat, "word_raw": word}) is ok


# --- "yanking your chain", "sheesh", and slang for touching yourself ------------------
@pytest.mark.parametrize("text, phrase, cat", [
    ("Quit yanking my chain!", "yanking my chain", "moderate"),
    ("He was just yanking your chain.", "yanking your chain", "moderate"),
    ("You yanked my chain, sheesh.", "sheesh", "minced"),
    ("He was jerking off.", "jerking off", "sexual"),
    ("Go rub one out.", "rub one out", "sexual"),
    ("What a jerk-off.", "jerkoff", "moderate"),
    ("Stop wanking.", "wanking", "moderate"),
])
def test_chain_and_slang_found(text, phrase, cat):
    ws = words(text)
    assert (phrase, cat) in [(" ".join(ws[i:j]), c) for i, j, c in E.find_language(ws, EVERY)]


@pytest.mark.parametrize("text", [
    "She yanked the chain of the toilet.",
    "He yanked the chain off the gate.",
    "The car jerked off the road.",
    "He jerked off his jacket.",
    "She yanked it out of the wall.",
])
def test_chain_and_slang_everyday_uses(text):
    assert hits(text) == []


# --- "what the hell": the lead-in is muted with the swear (audio mutes) ----------------
def lead(text):
    ws = words(text)
    return [(" ".join(ws[i:j]), c) for i, j, c in E.find_language(ws, EVERY, lead_in_too=True)]


@pytest.mark.parametrize("text, phrase", [
    ("What the hell?", "what the hell"),
    ("What the fuck is that?", "what the fuck"),
    ("Who the hell are you?", "who the hell"),
    ("Where in the hell did you go?", "where in the hell"),
    ("How the heck did you do that?", "how the heck"),
    ("Why the hell not?", "why the hell"),
    ("What the f?", "what the f"),
    ("What the eff, man.", "what the eff"),
    ("What the fudge!", "what the fudge"),
])
def test_what_the_lead_in_muted(text, phrase):
    assert phrase in [p for p, _ in lead(text)]


@pytest.mark.parametrize("text, found", [
    ("What the sex ed teacher said.", ["sex"]),      # only swearing takes the lead-in
    ("What the teacher said was fine.", []),
    ("Get the hell out.", ["hell"]),
    ("He asked what the Lord wanted.", []),
])
def test_what_the_lead_in_only_for_swears(text, found):
    assert [p for p, _ in lead(text)] == found


def test_lead_in_off_by_default():
    assert hits("What the hell?") == [("hell", "mild")]   # CleanRead and context starring


def test_shown_keeps_lead_in_readable():
    raw = "What the hell?".split()
    assert E.shown(raw, words("What the hell?")) == "What the h***"


# --- "retarded" and its forms (swearing group, like CleanView 1.15.1) ------------------
@pytest.mark.parametrize("text, phrase", [
    ("That is so retarded.", "retarded"),
    ("Shut up, retardo.", "retardo"),
    ("What a tard.", "tard"),
    ("Those libtards again.", "libtards"),
    ("Retarts everywhere.", "retarts"),            # a subtitle misspelling
    ("He is re tarded.", "re tarded"),             # speech recognition split it in two
    ("You re tards.", "re tards"),
])
def test_retarded_forms_muted(text, phrase):
    assert (phrase, "moderate") in hits(text)


@pytest.mark.parametrize("text", [
    "He was tardy for class.", "She wore a leotard.", "Pass the mustard.", "Custard pie.",
    "Fire retardant foam.", "This will retard the spread.",
    "Mental retardation was the old term.", "Re the tax form, call me.",
])
def test_retarded_lookalikes_kept(text):
    assert hits(text) == []


# --- from CleanView 1.16.2 (the three apps share word changes) -------------------------
@pytest.mark.parametrize("text, phrase", [
    ("Quit pulling my chain.", "pulling my chain"),
    ("He was jerking your chain.", "jerking your chain"),
    ("You've got some balls!", "balls"),
    ("She's got real stones.", "stones"),
])
def test_cleanview_phrases_found(text, phrase):
    assert phrase in [p for p, _ in hits(text)]


@pytest.mark.parametrize("text", [
    "Pull the chain to flush.", "I've got some nuts in my bag.",
    "You got some stones for the garden?", "A horny toad sat there.", "Turn off the boob tube.",
])
def test_cleanview_lookalikes_kept(text):
    assert hits(text) == []


# --- bleeped and abbreviated swears (ebooks; ported from CleanView's cvcore) ----------------
@pytest.mark.parametrize("bleeped, word", [
    ("f***", "fuck"), ("F***ing", "fucking"), ("f**king", "fucking"), ("s**t", "shit"),
    ("s***", "shit"), ("bulls**t", "bullshit"), ("a**hole", "asshole"), ("b****", "bitch"),
    ("d*mn", "damn"), ("h***", "hell"), ("G*d", "god"), ("motherf***er", "motherfucker"),
    ("f--k", "fuck"), ("#@$%", "fuck"), ("f***!", "fuck"),
    ("SOB", "sonofabitch"), ("S.O.B.", "sonofabitch"), ("D-bag", "douchebag"),
])
def test_bleeps_and_short_forms_read_as_the_word(bleeped, word):
    assert E.norm(bleeped) == word


@pytest.mark.parametrize("text, same", [
    ("#1", "1"), ("x-ray", "xray"), ("well--", "well"), ("$5", "5"), ("*", ""), ("hello", "hello"),
    ("***", ""), ("$$$", ""), ("sob", "sob"), ("Hey!", "hey"),
])
def test_ordinary_text_and_scene_breaks_untouched(text, same):
    assert E.norm(text) == same


def test_cleanread_keeps_bleeped_words_whole():
    import cleanread as R
    toks = lambda t: [m.group() for m in R.WORD_RE.finditer(t)]
    assert toks("What the f***ing hell? That's s**t.") == ["What", "the", "f***ing", "hell",
                                                            "That's", "s**t"]
    assert toks("He said #@$% loudly.") == ["He", "said", "#@$%", "loudly"]
    assert toks("* * *") == [] and toks("***") == [] and toks("It cost $$$.") == ["It", "cost"]
    assert toks("well-- maybe f--k") == ["well", "maybe", "f--k"]


# --- more of the same kind (CleanView 1.17, Lauren's review 2026-10-28/29) --------------
@pytest.mark.parametrize("text, phrase", [
    ("Golly, that's big", "golly"), ("Jeepers!", "jeepers"), ("Crikey, mate", "crikey"),
    ("Blimey", "blimey"), ("Cripes almighty", "cripes"), ("Well, doggone it", "doggone"),
    ("Tarnation!", "tarnation"), ("Oh, crud.", "crud"), ("Good grief!", "good grief"),
    ("Good heavens!", "good heavens"), ("Oh my goodness!", "oh my goodness"),
    ("Thank goodness you're here", "thank goodness"), ("For Pete's sake", "for pete's sake"),
    ("For crying out loud!", "for crying out loud"), ("Holy cow!", "holy cow"),
    ("Holy moly", "holy moly"), ("Holy molly!", "holy molly"), ("Holy smokes", "holy smokes"),
    ("Gee whiz", "gee whiz"), ("Jeepers creepers", "jeepers creepers"),
    ("You son of a gun!", "son of a gun"), ("Oh, fudge.", "oh fudge"),
    ("Oh shoot, I forgot", "oh shoot"), ("Goodness gracious me", "goodness gracious"),
    ("Gee, thanks", "gee"), ("Gee, Mom!", "gee"), ("You don't know squat", "squat"),
    ("It doesn't mean squat", "squat"), ("He didn't do squat all day", "squat"),
    ("That's not worth squat", "squat"), ("You got jack squat", "jack squat"),
    ("Diddly squat", "diddly squat"), ("diddlysquat", "diddlysquat"),
])
def test_more_soft_swears(text, phrase):
    assert hits(text, ["minced"]) == [(phrase, "minced")]


@pytest.mark.parametrize("text", [
    "Do ten squats", "Squat down low", "Can you do squat jumps?", "He did a squat",
    "squatters moved in", "a squat little teapot", "Gee up, horse!", "Sit squat on the floor",
])
def test_exercise_squats_and_horses_left_alone(text):
    assert hits(text) == []


@pytest.mark.parametrize("text, phrase", [
    ("Oh my Lord, look at that", "oh my lord"), ("Lord have mercy", "lord have mercy"),
    ("I swear to God", "swear to god"), ("God forbid", "god forbid"),
    ("What in God's name?", "in god's name"), ("Lord knows I tried", "lord knows"),
])
def test_more_gods_name(text, phrase):
    assert hits(text, ["deity"]) == [(phrase, "deity")]


def test_thank_the_lord_is_left_to_strict_religion():
    assert hits("Thank the Lord you're safe", ["deity"]) == []
    assert E.strict_religion_hit(words("Thank the Lord you're safe"))


@pytest.mark.parametrize("text, phrase", [
    ("You wimp!", "wimp"), ("What a weirdo", "weirdo"), ("Don't be a crybaby", "crybaby"),
    ("You big sissy", "sissy"), ("You twit", "twit"), ("Stop it, you brat", "brat"),
    ("You imbecile!", "imbecile"), ("scaredy-cat", "scaredycat"), ("I hate you!", "i hate you"),
    ("Talk to the hand", "talk to the hand"), ("Shut your pie hole", "shut your pie hole"),
    ("Shut your big mouth", "shut your big mouth"), ("Buzz off!", "buzz off"),
    ("Eat my shorts", "eat my shorts"),
])
def test_more_rude_words(text, phrase):
    assert hits(text, ["rude"]) == [(phrase, "rude")]


@pytest.mark.parametrize("text, muted, cat", [
    ("We're screwed", ["we're screwed"], "mild"), ("Up yours!", ["up yours"], "mild"),
    ("That was craptastic", ["craptastic"], "mild"), ("Dayum", ["dayum"], "mild"),
    ("She's a floozy", ["floozy"], "mild"), ("Can't be arsed", ["arsed"], "moderate"),
    ("Check out those jugs", ["jugs"], "moderate"), ("Nice rack", ["rack"], "moderate"),
    ("Kicked him in the junk", ["junk"], "moderate"), ("suck my cock", ["cock"], "moderate"),
    ("kneed him in the crown jewels", ["crown", "jewels"], "moderate"),
    ("a big schlong", ["schlong"], "sexual"),
])
def test_more_mild_and_crude_words(text, muted, cat):
    assert hits(text, [cat]) == [(w, cat) for w in muted]


def test_more_orientation_words():
    assert [w for w, _ in hits("lesbos", ["orientation"])] == ["lesbos"]


@pytest.mark.parametrize("text", [
    "The shelf is screwed to the wall", "I screwed up the order", "The lid was screwed on tight",
    "a rack of lamb", "the spice rack", "The cock crowed at dawn", "Cock the gun",
    "a cock and bull story", "Throw it in the junk pile", "Your package arrived",
    "Army brats move a lot", "The Twits by Roald Dahl", "Wimpy ate a burger",
    "Get that bug off me", "Holy water", "the Holy Bible", "a holy man", "Good night",
    "My goodwill", "a big jug of milk", "I hate yogurt", "Golf is fun",
    "the Crown Jewels in London",
])
def test_more_everyday_uses_left_alone(text):
    assert hits(text, EVERY + ["rude"]) == []


@pytest.mark.parametrize("text, muted, cat", [
    ("Grow some cajones", ["cajones"], "moderate"), ("He's got cahones", ["cahones"], "moderate"),
    ("Merde!", ["merde"], "moderate"), ("Scheisse", ["scheisse"], "moderate"),
    ("Verdammt!", ["verdammt"], "mild"), ("You still get screwed", ["get screwed"], "mild"),
    ("We got screwed!", ["got screwed"], "mild"), ("So help me God", ["so help me god"], "deity"),
    ("Holy Lord!", ["holy lord"], "deity"), ("What the devil?", ["what the devil"], "minced"),
    ("What the dickens is that?", ["what the dickens"], "minced"),
])
def test_cleanview_1_17_4_words(text, muted, cat):
    assert hits(text, [cat]) == [(w, cat) for w in muted]


@pytest.mark.parametrize("text", [
    "The lid got screwed on tight", "It got screwed to the wall", "Get screwed in properly",
    "The devil is in the details", "the dickens novel", "He played the devil",
])
def test_cleanview_1_17_4_everyday_uses_left_alone(text):
    assert hits(text, EVERY + ["rude"]) == []


@pytest.mark.parametrize("text, phrase, cat", [
    ("For God's sakes!", "for god's sakes", "deity"), ("For Christ's sakes", "for christ's sakes", "deity"),
    ("Morning, dum-dum.", "dumdum", "rude"), ("Fathead.", "fathead", "rude"),
])
def test_cleanview_1_17_5_words(text, phrase, cat):
    assert hits(text, [cat]) == [(phrase, cat)]


def test_dumdum_bullets_left_alone():
    assert hits("loaded with dum-dum bullets", EVERY + ["rude"]) == []


@pytest.mark.parametrize("text, phrase", [
    ("That really sucks", "sucks"), ("Life sucks", "sucks"), ("He sucks at math", "sucks"),
    ("That sucked", "sucked"), ("What a sucky day", "sucky"), ("You sucker!", "you sucker"),
    ("This sucks big time", "this sucks"), ("Man, that sucks.", "that sucks"),
])
def test_suck_meaning_bad_is_rude(text, phrase):
    assert hits(text, ["rude"]) == [(phrase, "rude")]


@pytest.mark.parametrize("text", [
    "Suck it up", "Suck on a lollipop", "The vacuum sucks up dirt", "Sucking his thumb",
    "The baby sucked", "Sucked into the whirlpool", "A lollipop sucker", "Sucker punch",
    "He is a sucker for romance", "It sucks the juice out", "The straw sucks",
    "The baby keeps sucking",
])
def test_sucking_something_left_alone(text):
    assert hits(text, EVERY + ["rude"]) == []


def test_po_d_is_pissed_but_po_would_is_not():
    # CleanView 1.18.4: "PO'd" (pissed off), not "Po'd" (Po would, Kung Fu Panda)
    assert E.find_language(words("He's PO'd at me."), ["moderate"])
    assert E.find_language(words("Po'd never do that."), list(E.CATS)) == []


def test_listed_word_only_counts_the_ticked_lists():
    assert E.listed_word("butts", ["rude"]) and not E.listed_word("butts", ["mild", "moderate"])
    assert E.listed_word("Lord help that", ["deity"]) and not E.listed_word("Grafi", list(E.CATS))


@pytest.mark.parametrize("text,cat,hit", [
    # CleanView 1.18.5 (The Resident)
    ("If they find out, we would be screwed.", "mild", True),
    ("The shelf was screwed to the wall.", "mild", False),
    ("What in heaven's name are you doing?", "minced", True),
    ("Oh, hallelujah, it's over!", "deity", True),
    ("The choir sang hallelujah at the end.", "deity", False)])
def test_cleanview_1_18_5_words(text, cat, hit):
    assert bool(E.find_language(words(text), [cat])) is hit
