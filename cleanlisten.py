#!/usr/bin/env python3
"""
CleanListen engine — mute language and cut sexual content from audiobooks
you own. Used by the CleanListen app; can also run from a command line:

  python cleanlisten.py analyze WORKDIR AUDIO [AUDIO ...] [--ebook BOOK.epub]
  python cleanlisten.py render  WORKDIR [--out OUTDIR]
"""
import argparse
import bisect
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "models" / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
SR = 16000
AUDIO_EXTS = (".mp3", ".m4b", ".m4a", ".aac", ".mp4", ".ogg", ".opus", ".flac", ".wav", ".wma")


# ---------------------------------------------------------------------------
# Running ffmpeg quietly (no console windows flashing on Windows)
# ---------------------------------------------------------------------------
def _tool(name):
    local = HERE / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is missing. Re-run the CleanListen installer.")
    return found


_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


def run(cmd, **kw):
    return subprocess.run(cmd, **_NOWIN, **kw)


def popen(cmd, **kw):
    return subprocess.Popen(cmd, **_NOWIN, **kw)


def probe_duration(path):
    out = run([_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------
STRONG = [r".*fuck.*", r"cunts?", r"motherf.*", r"fk", r"effing"]
MODERATE = [
    r".*shit.*", r"bitch.*", r"ass", r"asses", r"ass(hole|holes|wipe)", r"arse",
    r"arsehole.*", r"jackass.*", r"dumbass.*", r"badass.*", r"smartass.*",
    r"bastard.*", r"piss.*", r"dicks?", r"dickhead.*", r"pricks?", r"bollocks",
    r"bugger.*", r"wanker.*", r"twats?", r"sluts?", r"slutty", r"whores?",
    r"skanks?", r"douche.*", r"tits", r"titties", r"cocksucker.*",
]
# ("damning" = incriminating and "damnation" are left alone)
MILD = [r"damn", r"damned", r"damnit", r"damns", r"dammit", r"goddamn.*", r"goddam", r"hell", r"hellhole",
        r"crap", r"crappy", r"craps", r"sod", r"sodding", r"bloody"]
MINCED = [r"frigg?in[g']?", r"freakin[g']?", r"frickin[g']?", r"jeez", r"geez",
          r"gosh", r"darn.*", r"heck", r"dang"]
DEITY_PHRASES = [
    ("oh", "my", "god"), ("my", "god"), ("oh", "god"), ("good", "god"),
    ("dear", "god"), ("god", "almighty"), ("for", "god's", "sake"),
    ("for", "gods", "sake"), ("god", "knows"), ("god", "damn"),
    ("god", "dammit"), ("oh", "lord"), ("good", "lord"), ("dear", "lord"),
    ("lord", "almighty"), ("sweet", "jesus"), ("jesus", "christ"),
    ("for", "christ's", "sake"), ("for", "christs", "sake"),
]
DEITY_WORDS = [r"jesus", r"christ", r"lordy", r"omg", r"goddamn.*"]
# Sexual words muted one at a time, wherever they come up (separate from
# cutting whole explicit scenes). Words with innocent everyday meanings
# (bed, naked, breast, screw) are deliberately left out.
SEXUAL_WORDS = [
    r"sex", r"sexes", r"sexy", r"sexier", r"sexiest", r"sexual", r"sexually", r"sexuality",
    r"sexed", r"sexting", r"horny", r"orgasm.*", r"erections?", r"arous(ed|al)",
    r"condoms?", r"boobs?", r"boobies", r"penis(es)?", r"vaginas?", r"genital.*",
    r"nipples?", r"porn.*", r"foreplay", r"intercourse", r"masturbat.*", r"climaxed",
    r"hookers?", r"blowjobs?", r"threesomes?", r"lingerie", r"panties",
]
SEXUAL_PHRASES = [
    ("make", "love"), ("making", "love"), ("made", "love"), ("makes", "love"),
    ("get", "laid"), ("got", "laid"), ("getting", "laid"),
    ("one", "night", "stand"), ("one", "night", "stands"), ("hook", "up", "with"),
    ("hooked", "up", "with"), ("hooking", "up", "with"),
] + [(v, "with", o) for v in ("sleep", "sleeps", "slept", "sleeping")
     for o in ("him", "her", "me", "you", "them", "someone", "somebody", "anyone",
               "anybody", "each", "everyone", "everybody")]
# "screw you" / "screw it" as an insult (muted with the mild words). "Screw" on its
# own is left alone, and so is "screw it in / on / tight..." (hardware).
SCREW_PHRASES = [("screw", o) for o in ("you", "him", "her", "them", "it", "this", "that", "off",
                                        "yourself", "em", "'em", "everyone", "everybody", "y'all")]
SCREW_SAFE_NEXT = {"in", "into", "on", "onto", "to", "back", "down", "tight", "tightly", "shut",
                   "together", "up", "through", "firmly", "securely", "loose", "around", "the",
                   "a", "an", "lid", "cap", "bolt", "hinge", "panel", "plate", "bracket"}
PHRASES = {"deity": None, "sexual": SEXUAL_PHRASES, "mild": SCREW_PHRASES}  # deity filled in below
BLOODY_SWEAR_NEXT = {
    "hell", "well", "idiot", "fool", "fools", "stupid", "ridiculous", "nuisance",
    "nonsense", "cheek", "marvellous", "marvelous", "brilliant", "awful", "good",
    "great", "mess", "typical", "lucky", "useless", "thing", "things", "obvious",
    "right", "freezing", "sure", "christ", "god", "minded",
}
SEX_TERMS = {
    3: [r"orgasm.*", r"climax(ed|ing)?", r"erection", r"arous(ed|al|ing)",
        r"nipples?", r"naked", r"nude", r"groin", r"thrust(s|ed|ing)?",
        r"moan(s|ed|ing)?", r"undress(ed|ing)?", r"panties", r"lingerie",
        r"straddl(e|ed|ing)", r"breasts?", r"sex", r"sexual(ly)?", r"lust(ed|ful|ing)?",
        r"unzip(ped|s)?", r"unbutton(ed|ing)?", r"bra", r"intercourse",
        r"pleasure", r"writh(e|ed|ing)", r"hardness", r"condoms?", r"foreplay",
        r"bedded", r"seduc(e|ed|ing|tion)"],
    1: [r"kiss(ed|es|ing)?", r"thighs?", r"hips?", r"caress(ed|es|ing)?",
        r"tongue", r"sheets", r"bed", r"bedroom", r"skin", r"shirt", r"blouse",
        r"gasp(ed)?", r"desire", r"body", r"bodies", r"touch(ed|ing)?", r"lips",
        r"stroked?", r"breath(less)?", r"shiver(ed)?", r"zipper", r"husky", r"hungrily"],
}
SEX_WINDOW_SCORE = 9   # a stretch of ~3 paragraphs (or ~60s) scoring this much gets flagged
SEX_PARA_SCORE = 3     # a single paragraph inside such a stretch must score this to be cut

# Checkbox groups shown in the app → word-list categories
GROUPS = {
    "sexual": ["sexual"],
    "swearing": ["strong", "moderate"],
    "mild": ["mild"],
    "deity": ["deity"],
    "minced": ["minced"],
}


def norm(w):
    w = w.lower().replace("’", "'").replace("‘", "'")
    w = re.sub(r"[^a-z0-9']", "", w)
    return w.strip("'")


def _c(pats):
    return [re.compile(p + r"$") for p in pats]


CATS = {"strong": _c(STRONG), "moderate": _c(MODERATE), "mild": _c(MILD),
        "minced": _c(MINCED), "deity": _c(DEITY_WORDS), "sexual": _c(SEXUAL_WORDS)}
PHRASES["deity"] = DEITY_PHRASES
# Orientation words, muted one at a time when CleanListen's relationships filter
# is on. Kept OUT of CATS on purpose: CleanView masks every CATS category in its
# subtitles, and this list is CleanListen's choice only.
ORIENTATION_WORDS = [
    r"gays?", r"lesbians?", r"homosexual(s|ity)?", r"bisexual(s|ity)?", r"queers?",
    r"homos?", r"pansexual(s)?", r"lgbt", r"lgbtq", r"lgbtqia", r"lgbtq\+?", r"throuples?",
    r"polyamor.*", r"dykes?", r"fags?", r"faggots?",
]
EXTRA_CATS = {"orientation": _c(ORIENTATION_WORDS)}
GROUPS["orientation"] = ["orientation"]
SEX_C = {w: _c(p) for w, p in SEX_TERMS.items()}


def find_language(words, cats):
    """Return (i, j, category) spans of words[i:j] to mute."""
    hits, n, i = [], len(words), 0
    while i < n:
        found = None
        for cat in cats:
            for ph in sorted(PHRASES.get(cat) or [], key=len, reverse=True):
                if tuple(words[i:i + len(ph)]) == ph:
                    if ph[0] == "screw" and (words[i + 2] if i + 2 < n else "") in SCREW_SAFE_NEXT:
                        continue  # "screw it in tight", "screw that lid on"
                    found = (ph, cat)
                    break
            if found:
                break
        if found:
            hits.append((i, i + len(found[0]), found[1]))
            i += len(found[0])
            continue
        w = words[i]
        for cat in cats:
            if any(p.match(w) for p in (CATS.get(cat) or EXTRA_CATS.get(cat) or [])):
                if w == "bloody" and (words[i + 1] if i + 1 < n else "") not in BLOODY_SWEAR_NEXT:
                    break
                hits.append((i, i + 1, cat))
                break
        i += 1
    return hits


def sex_score(words):
    """Score a stretch of text. Only stretches with at least two explicit
    words count at all: kissing, beds and sheets alone never flag a scene
    (romance without explicit content is left alone)."""
    s, explicit = 0, 0
    for w in words:
        for weight, pats in SEX_C.items():
            if any(p.match(w) for p in pats):
                s += weight
                explicit += weight == 3
                break
    return s if explicit >= 2 else 0


def is_explicit(words):
    return any(p.match(w) for w in words for p in SEX_C[3])


# Graphic violence. A body being found, a stabbing or "blood" alone is normal
# for a mystery and is NOT flagged: a stretch needs several strongly graphic
# words close together.
GORE_TERMS = {
    3: [r"entrails", r"intestines?", r"innards", r"viscera", r"disembowel.*", r"eviscerat.*",
        r"decapitat.*", r"beheaded", r"dismember.*", r"mutilat.*", r"severed", r"gore", r"gory",
        r"gush(ed|ing)", r"spurt(ed|ing|s)?", r"splatter(ed|ing|s)?", r"spatter(ed)?", r"ooz(ed|ing)",
        r"maggots?", r"putrid", r"putrefy.*", r"rotting", r"decompos(ed|ing|ition)", r"flayed",
        r"gouged", r"impaled", r"pus", r"mangled", r"charred", r"brains", r"gristle",
        r"sinews?", r"tendons?", r"eyeballs?", r"bloodbath", r"slaughtered", r"butchered"],
    1: [r"blood", r"bloody", r"bloodied", r"flesh", r"wounds?", r"gash(ed|es)?", r"throat",
        r"corpse", r"bones?", r"stab(bed|bing|s)?", r"bleed(ing|s)?", r"bled", r"torn", r"ripped",
        r"crushed", r"veins?", r"guts", r"organs?", r"skull", r"slit", r"carcass", r"limbs?",
        r"jaw", r"teeth", r"stench", r"vomit(ed)?"],
}
GORE_C = {w: _c(p) for w, p in GORE_TERMS.items()}
GORE_WINDOW_SCORE = 10


def gore_score(words):
    s, strong = 0, set()
    for w in words:
        for weight, pats in GORE_C.items():
            if any(p.match(w) for p in pats):
                s += weight
                if weight == 3:
                    strong.add(w)
                break
    return s if len(strong) >= 2 else 0


def is_gory(words):
    return any(p.match(w) for w in words for p in GORE_C[3])


# Religious content. A passing mention ("she prayed", "thank God", "he believed
# in God") never flags: a stretch needs several distinct religious words close
# together (someone explaining their beliefs), or a sentence that pairs God
# with blame or hatred.
RELIGION_TERMS = {
    2: [r"faith", r"scriptures?", r"bible", r"biblical", r"gospels?", r"salvation", r"sins?",
        r"sinful", r"sinners?", r"sinned", r"heaven(ly)?", r"damnation", r"damned", r"saviou?r",
        r"worship(ped|ping)?", r"churche?s?", r"pastors?", r"preach(er|ers|ing|ed)?", r"sermons?",
        r"priests?", r"prayers?", r"prayed", r"praying", r"pray", r"holy", r"divine", r"almighty",
        r"souls?", r"redemption", r"redeem(ed|er)?", r"repent.*", r"resurrect.*", r"crucif.*",
        r"eternal", r"eternity", r"providence", r"deity", r"atheists?", r"atheism", r"agnostic",
        r"religions?", r"religious", r"theolog.*", r"creator", r"angels?", r"demons?", r"devil",
        r"satan", r"rapture", r"afterlife", r"blessed", r"blessings?", r"grace", r"spiritual",
        r"christians?", r"christianity", r"muslims?", r"islam", r"allah", r"buddhis.*", r"hindu.*",
        r"karma", r"reincarnat.*", r"psalms?", r"commandments?", r"apostles?", r"disciples?",
        r"messiah", r"godless", r"heathens?", r"blasphem.*", r"hymns?", r"congregation"],
    1: [r"god", r"gods", r"god's", r"lord", r"jesus", r"christ", r"believe", r"believed",
        r"believes", r"beliefs?", r"miracles?", r"forgive(n|ness)?", r"mercy", r"fate",
        r"destiny", r"universe", r"hell", r"spirit", r"evil", r"punish(ed|ment)?"],
}
RELIGION_C = {w: _c(p) for w, p in RELIGION_TERMS.items()}
RELIGION_WINDOW_SCORE = 9
GOD_WORDS = {"god", "god's", "gods", "lord", "jesus", "christ", "heaven", "almighty", "creator"}
BLAME_C = _c([r"hate[sd]?", r"hating", r"blame[sd]?", r"blaming", r"cruel(ty)?", r"punish.*",
              r"abandon(ed|s)?", r"forsak(en|e)", r"unfair", r"curse[sd]?", r"cursing", r"angry",
              r"furious", r"fault", r"monster", r"sadist.*", r"spite", r"rage[ds]?", r"betray.*",
              r"deserted", r"useless", r"heartless", r"evil", r"mad", r"upset",
              r"resent.*", r"bitter(ness|ly)?", r"unanswered", r"furiously", r"livid",
              r"allow(s|ed|ing)?", r"permit(s|ted)?"])
NO_GOD_PHRASES = [("there", "is", "no", "god"), ("there's", "no", "god"), ("god", "is", "dead"),
                  ("god", "doesn't", "exist"), ("god", "does", "not", "exist"),
                  ("no", "such", "thing", "as", "god"), ("where", "was", "god"),
                  ("if", "there", "is", "a", "god"), ("if", "there's", "a", "god"),
                  ("how", "could", "god"), ("why", "would", "god"), ("why", "did", "god"),
                  # losing or rejecting faith
                  ("lost", "my", "faith"), ("lost", "her", "faith"), ("lost", "his", "faith"),
                  ("lost", "their", "faith"), ("losing", "my", "faith"), ("lose", "my", "faith"),
                  ("lost", "faith", "in", "god"), ("stopped", "believing"), ("stop", "believing"),
                  ("gave", "up", "on", "god"), ("give", "up", "on", "god"), ("given", "up", "on", "god"),
                  ("don't", "believe", "in", "god"), ("doesn't", "believe", "in", "god"),
                  ("didn't", "believe", "in", "god"), ("never", "believed", "in", "god"),
                  ("do", "not", "believe", "in", "god"), ("turned", "away", "from", "god"),
                  # God as uncaring or to blame
                  ("god", "doesn't", "care"), ("god", "didn't", "care"), ("god", "never", "cared"),
                  ("if", "god", "loved"), ("if", "god", "cared"), ("if", "god", "really"),
                  ("god", "never", "answered"), ("god", "didn't", "answer"), ("god", "wasn't", "listening"),
                  ("god", "never", "listened"), ("god", "didn't", "listen"),
                  # ("turned" on its own isn't blame: "oh my God ... she's turned up")
                  ("god", "turned", "his", "back"), ("god", "turned", "away"), ("god", "has", "turned"),
                  ("god", "had", "turned"),
                  ("god", "took"), ("god", "takes"), ("god", "let"), ("god", "lets"),
                  ("god", "has", "taken"), ("god", "had", "taken"), ("taken", "by", "god"),
                  ("god", "gave", "up"), ("god", "forgot"), ("god", "left", "us"), ("god", "left", "me"),
                  ("god's", "fault"), ("god", "did", "this"), ("god", "did", "nothing"),
                  ("prayers", "went", "unanswered"), ("prayers", "were", "never", "answered"),
                  ("unanswered", "prayers"), ("prayers", "unanswered"), ("prayed", "for", "nothing"),
                  ("praying", "for", "nothing"), ("what", "good", "is", "praying"),
                  ("praying", "doesn't", "work"), ("prayer", "doesn't", "work")]


# Same-sex and non-traditional relationships (kept separate from the mute
# word lists so CleanView's subtitle masking is unaffected). Sentence-level:
# any sentence that makes such a relationship clear is offered for cutting.
RELATIONSHIP_WORDS = _c([
    r"gay", r"gays", r"lesbians?", r"bisexuals?", r"bi-?curious", r"queer", r"homosexual(s|ity)?",
    r"throuples?", r"polyamor.*", r"polygam.*", r"polyandr.*", r"swingers?"])
RELATIONSHIP_PHRASES = [
    ("same", "sex"), ("same-sex",), ("his", "husband"), ("his", "husband's"), ("his", "husbands"),
    ("her", "wife"), ("her", "wife's"), ("her", "wives"), ("his", "boyfriend"), ("his", "boyfriend's"),
    ("her", "girlfriend"), ("her", "girlfriend's"), ("two", "husbands"), ("two", "wives"),
    ("two", "dads"), ("two", "moms"), ("two", "mommies"), ("two", "daddies"),
    ("open", "marriage"), ("open", "relationship"), ("wife", "swapping"), ("wife", "swap"),
    ("sister", "wives"), ("sister", "wife"), ("our", "girlfriend"), ("our", "boyfriend"),
    ("both", "of", "us", "are", "dating"), ("dating", "both", "of"), ("married", "to", "both"),
    ("came", "out", "of", "the", "closet"),
    ("in", "the", "closet"), ("swinging", "couple"), ("swinging", "couples"), ("swinging", "lifestyle"),
]
KISS_AFTER = {"", "again", "back", "gently", "softly", "hard", "deeply", "passionately", "then",
              "and", "slowly", "hungrily", "tenderly", "fiercely"}
# "came out to his parents" is coming out; "came out to my office" / "to the car" isn't
OUT_TO_PEOPLE = {"me", "him", "them", "us", "everyone", "everybody", "family", "friends", "parents"}
OUT_TO_OWNER = {"my", "his", "her", "their", "our", "your"}
OUT_TO_FAMILY = {"parents", "family", "folks", "mom", "mum", "mother", "dad", "father", "friends",
                 "friend", "sister", "sisters", "brother", "brothers", "wife", "husband", "kids",
                 "children", "son", "daughter", "grandparents", "grandmother", "grandfather", "grandma",
                 "grandpa", "boss", "coworkers", "colleagues", "teammates", "team", "class", "pastor",
                 "church", "congregation", "roommate", "best"}
# "came out as gay" / "as a lesbian" is coming out; "came out as a winner" isn't (same list as CleanRead)
OUT_AS = {"gay", "lesbian", "bi", "bisexual", "trans", "transgender", "queer", "nonbinary",
          "pansexual", "asexual", "lgbt", "lgbtq", "homosexual"}


def _came_out(words, i):
    if words[i] not in ("came", "coming", "come", "comes") or words[i + 1:i + 2] != ["out"]:
        return False
    how, nxt, after = (words[i + 2:i + 5] + ["", "", ""])[:3]
    if how == "as":
        return nxt in OUT_AS or (nxt in ("a", "an") and after in OUT_AS)
    if how != "to":
        return False
    if nxt in OUT_TO_PEOPLE:
        return True
    # "came out to her" (and nothing more) vs "came out to her car"
    return nxt in OUT_TO_OWNER and (after in OUT_TO_FAMILY or (nxt == "her" and after in KISS_AFTER))


def relationship_hit(words):
    """Does this sentence make a same-sex or non-traditional relationship clear?"""
    if any(any(p.match(w) for p in RELATIONSHIP_WORDS) for w in words):
        return True
    for i in range(len(words)):
        for ph in RELATIONSHIP_PHRASES:
            if tuple(words[i:i + len(ph)]) == ph:
                return True
        if _came_out(words, i):
            return True
        # "my husband, he said" / "my wife, she told him": partner word + same-gender speaker tag
        for partner, tags in (((("my", "husband"), ("my", "boyfriend")), ("he",)),
                              ((("my", "wife"), ("my", "girlfriend")), ("she",))):
            if any(tuple(words[i:i + 2]) == ph for ph in partner):
                verbs = {"said", "says", "added", "told", "explained", "replied", "answered", "laughed", "admitted"}
                near = words[max(0, i - 8):i + 10]
                for j in range(len(near) - 1):
                    if (near[j] in tags and near[j + 1] in verbs) or (near[j] in verbs and near[j + 1] in tags):
                        return True
        # "he kissed him" / "she kissed her" (but not "she kissed her daughter")
        for subj, obj in (("he", "him"), ("she", "her")):
            if words[i:i + 3] == [subj, "kissed", obj] or words[i:i + 3] == [subj, "kisses", obj]:
                if (words[i + 3] if i + 3 < len(words) else "") in KISS_AFTER:
                    return True
    return same_sex_flirt(words)


# Flirting. "*" is the person being flirted with. Sentence-level, like crude humor.
PERSON = {"me", "you", "him", "her", "them", "us"}
FLIRT_PATTERNS = (
    [(v, "with", "*") for v in ("flirt", "flirts", "flirted", "flirting")]
    + [(v, "at", "*") for v in ("wink", "winks", "winked", "winking")]
    + [(v, "on", "*") for v in ("hit", "hits", "hitting")]
    + [(v, "on", "to", "*") for v in ("come", "comes", "came", "coming")]
    + [(v, "eyes", "at", "*") for v in ("make", "makes", "made", "making")]
    + [(v, "*", "out") for v in ("checked", "checking")]
    + [(v, "*", "up") for v in ("chat", "chats", "chatted", "chatting", "eyed", "eyeing")]
    + [(v, p, l, "at", "*") for v in ("batted", "batting", "bats", "bat")
       for p in ("her", "his") for l in ("eyelashes", "lashes")]
    + [(v, p, l) for v in ("batted", "batting", "bats", "bat")
       for p in ("her", "his") for l in ("eyelashes", "lashes")]
)
# slots that must be a pronoun (so "hit on the head" / "checked the car out" don't count)
PRONOUN_SLOT = {"hit", "hits", "hitting", "checked", "checking", "chat", "chats", "chatted",
                "chatting", "eyed", "eyeing", "come", "comes", "came", "coming"}
FLIRT_WORDS = _c([r"flirty", r"flirtatious(ly)?", r"flirtations?", r"flirts?", r"flirted",
                  r"flirting", r"coquettish(ly)?", r"come-hither", r"pick-?up-?lines?"])
FLIRT_PHRASES = [("pickup", "line"), ("pick", "up", "line"), ("pick-up", "line"),
                 ("pickup", "lines"), ("bedroom", "eyes"), ("playing", "hard", "to", "get"),
                 ("played", "hard", "to", "get"), ("gave", "him", "the", "eye"),
                 ("gave", "her", "the", "eye"), ("come", "hither")]
FLIRT_OBJ_AFTER = KISS_AFTER | {"from", "across", "over", "while", "as", "when", "until", "before",
                                "after", "during", "at", "in", "on", "shamelessly", "openly",
                                "outrageously", "all", "throughout", "for", "but", "so", "too"}


def _flirt_spans(words):
    """(start, object index or None, subject gender hint or None) for each flirting phrase."""
    out = []
    for i in range(len(words)):
        for pat in FLIRT_PATTERNS:
            if i + len(pat) > len(words):
                continue
            ok, obj = True, None
            for k, p in enumerate(pat):
                w = words[i + k]
                if p == "*":
                    if pat[0] in PRONOUN_SLOT and w not in PERSON:
                        ok = False
                        break
                    obj = i + k
                elif w != p:
                    ok = False
                    break
            if ok:
                hint = {"his": "he", "her": "she"}.get(pat[1]) if pat[0].startswith("bat") else None
                out.append((i, obj, hint))
    return out


FLIRT_NOT = {"disaster", "danger", "death", "idea", "notion", "thought", "bankruptcy", "fame",
             "trouble", "madness", "suicide", "ruin", "temptation", "fate", "possibility"}


def _flirt_metaphor(words, i):
    """"flirted with disaster", "flirting with the idea" aren't flirting."""
    nxt = words[i + 1:i + 4]
    if nxt[:1] != ["with"]:
        return False
    return (len(nxt) > 1 and nxt[1] in FLIRT_NOT) or (
        len(nxt) > 2 and nxt[1] in ("the", "a") and nxt[2] in FLIRT_NOT)


def flirt_hit(words):
    if any(not (words[i].startswith("flirt") and _flirt_metaphor(words, i))
           for i, *_ in _flirt_spans(words)):
        return True
    if any(any(p.match(w) for p in FLIRT_WORDS) and not _flirt_metaphor(words, i)
           for i, w in enumerate(words)):
        return True
    return any(tuple(words[i:i + len(ph)]) == ph for ph in FLIRT_PHRASES for i in range(len(words)))


def same_sex_flirt(words):
    """"He was flirting with him", "she winked at her" (not "winked at her sister")."""
    for start, obj, hint in _flirt_spans(words):
        if obj is None or (words[start].startswith("flirt") and _flirt_metaphor(words, start)):
            continue
        o = words[obj]
        subj = hint
        if subj is None:
            before = [w for w in words[max(0, start - 8):start] if w in ("he", "she")]
            subj = before[-1] if before else None
        nxt = words[obj + 1] if obj + 1 < len(words) else ""
        if subj == "he" and o == "him":
            return True
        if subj == "she" and o == "her" and nxt in FLIRT_OBJ_AFTER:
            return True
    return False


# Bullying: name-calling aimed at someone ("you loser", "you're so stupid"),
# taunts ("nobody likes you"), and narration of bullying ("picked on", "made fun of").
BULLY_INSULTS = _c([
    r"losers?", r"freaks?", r"idiots?", r"morons?", r"stupid", r"dummy", r"dumb", r"retard(ed|s)?",
    r"fatso", r"fatty", r"lardo", r"lard-?ass", r"pig", r"ugly", r"weirdo", r"nerd", r"geek", r"dork",
    r"fat", r"wimp", r"sissy", r"crybaby", r"scaredy-?cat", r"worthless", r"pathetic", r"useless", r"creep",
    r"jerk", r"dweeb", r"doofus", r"imbecile", r"cretin", r"runt", r"shrimp", r"four-?eyes", r"brat",
    r"twerp", r"trash", r"scum", r"garbage", r"coward", r"lame", r"pansy", r"nobody", r"failure",
    r"disgusting", r"gross", r"psycho", r"spaz", r"klutz", r"airhead", r"bimbo", r"dimwit", r"halfwit",
    r"nitwit", r"numbskull", r"bonehead", r"blockhead", r"freakshow", r"reject", r"misfit",
])
BULLY_LEAD = {"you", "you're", "youre", "ya", "ur", "yer"}
BULLY_FILL = {"so", "such", "a", "an", "big", "little", "total", "complete", "fat", "stupid",
              "ugly", "dumb", "pathetic", "worthless", "useless", "are", "really", "just", "nothing",
              "but", "the", "biggest", "most", "lousy", "sorry", "filthy", "dirty", "skinny", "tiny"}
BULLY_PHRASES = [
    ("nobody", "likes", "you"), ("no", "one", "likes", "you"), ("everybody", "hates", "you"),
    ("everyone", "hates", "you"), ("nobody", "wants", "you"), ("no", "one", "wants", "you"),
    ("nobody", "cares", "about", "you"), ("no", "one", "cares", "about", "you"),
    ("go", "cry", "to"), ("cry", "to", "your", "mommy"), ("cry", "to", "your", "mama"),
    ("run", "home", "to", "mommy"), ("kill", "yourself"), ("you're", "nothing"),
    ("you", "are", "nothing"), ("you'll", "never", "be"), ("what", "a", "loser"),
    ("what", "a", "freak"), ("picked", "on"), ("pick", "on"), ("picks", "on"), ("picking", "on"),
    ("made", "fun", "of"), ("make", "fun", "of"), ("makes", "fun", "of"), ("making", "fun", "of"),
    ("called", "him", "names"), ("called", "her", "names"), ("called", "me", "names"),
    ("calling", "him", "names"), ("calling", "her", "names"), ("name", "calling"), ("name-calling",),
    ("shoved", "him", "into"), ("shoved", "her", "into"), ("stuffed", "him", "in"),
    ("stuffed", "him", "into"), ("dunked", "his", "head"), ("swirly",), ("swirlies",),
]
# ("mocking smile", "felt humiliated", "tormented by guilt" are ordinary in a mystery,
# so those words only count when aimed at someone: "tormenting him", "mocked her")
BULLY_WORDS = _c([r"bull(y|ies|ied|ying)", r"taunt(s|ed|ing)?", r"jeer(s|ed|ing)?",
                  r"ridiculed"])
BULLY_PHRASES += [(v, o) for v in ("tormented", "tormenting", "torment", "mocked", "mocking",
                                   "humiliated", "humiliating")
                  for o in ("him", "her", "them", "me", "us")]


def bully_hit(words):
    if any(any(p.match(w) for p in BULLY_WORDS) for w in words):
        return True
    n = len(words)
    for i in range(n):
        if any(tuple(words[i:i + len(ph)]) == ph for ph in BULLY_PHRASES):
            return True
        if words[i] in BULLY_LEAD:  # "you idiot", "you're such a loser", "you fat pig"
            j = i + 1
            while j < n and j - i <= 4 and words[j] in BULLY_FILL and not any(
                    p.match(words[j]) for p in BULLY_INSULTS):
                j += 1
            for k in range(i + 1, min(n, i + 5)):
                if k > j:
                    break
                if any(p.match(words[k]) for p in BULLY_INSULTS):
                    return True
    return False


def religion_score(words):
    s, strong = 0, set()
    for w in words:
        for weight, pats in RELIGION_C.items():
            if any(p.match(w) for p in pats):
                s += weight
                if weight == 2:
                    strong.add(w)
                break
    return s if len(strong) >= 3 else 0


def is_religious(words):
    return any(p.match(w) for w in words for p in RELIGION_C[2])


def blames_god(words):
    """One sentence: does it pair God with blame or hatred, or deny God?"""
    if any(tuple(words[i:i + len(ph)]) == ph for ph in NO_GOD_PHRASES for i in range(len(words))):
        return True
    return bool(GOD_WORDS & set(words)) and any(p.match(w) for w in words for p in BLAME_C)


def mask(word):
    core = re.sub(r"[^A-Za-z]", "", word)
    return word if len(core) <= 1 else core[0] + "*" * (len(core) - 1)


ALL_CATS = ["strong", "moderate", "mild", "deity", "minced", "sexual", "orientation"]


def raw_fields(raw, i, j, before=6, after=5):
    """The unmasked word and its surroundings, for the review screen's Show link."""
    return {"word_raw": " ".join(raw[i:j]),
            "ctx_raw": " ".join(raw[max(0, i - before):i]),
            "ctx_after_raw": " ".join(raw[j:j + after])}


def clean_context(raw, normed, i, j, before=6, after=5):
    """Words around a hit, with any bad words in the context starred out."""
    lo, hi = max(0, i - before), min(len(raw), j + after)
    win_n = normed[lo:hi]
    bad = set()
    for a, b, _ in find_language(win_n, ALL_CATS):
        bad.update(range(lo + a, lo + b))
    show = lambda k: mask(raw[k]) if k in bad else raw[k]
    return (" ".join(show(k) for k in range(lo, i)),
            " ".join(show(k) for k in range(j, hi)))


def fmt_t(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


# ---------------------------------------------------------------------------
# Speech recognition
# ---------------------------------------------------------------------------
def load_recognizer(model_dir=DEFAULT_MODEL, threads=None):
    import sherpa_onnx
    d = Path(model_dir)
    threads = threads or max(1, min(8, (os.cpu_count() or 2)))
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
        num_threads=threads, model_type="nemo_transducer")


def tokens_to_words(res, offset):
    words = []
    durs = list(res.durations) if res.durations else [0.08] * len(res.tokens)
    for tok, ts, du in zip(res.tokens, res.timestamps, durs):
        start, end = offset + ts, offset + ts + max(du, 0.08)
        if tok.startswith(" ") or not words:
            words.append({"t": tok.strip(), "s": start, "e": end})
        else:
            words[-1]["t"] += tok
            words[-1]["e"] = max(words[-1]["e"], end)
    for w in words:
        w["s"], w["e"] = round(w["s"], 3), round(w["e"], 3)
    return [w for w in words if w["t"]]


def transcribe(path, rec, progress=None, chunk=30.0, overlap=2.0, cancel=None):
    """Stream audio through ffmpeg in overlapping chunks (long books never
    need to fit in memory)."""
    proc = popen([_tool("ffmpeg"), "-v", "error", "-i", str(path), "-ac", "1",
                  "-ar", str(SR), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    C, O = int(chunk * SR), int(overlap * SR)
    buf, offset, first, eof, out = np.zeros(0, dtype=np.float32), 0.0, True, False, []
    try:
        while True:
            if cancel and cancel():
                raise KeyboardInterrupt
            while not eof and len(buf) < C:
                data = proc.stdout.read((C - len(buf)) * 4)
                if not data:
                    eof = True
                    break
                buf = np.concatenate([buf, np.frombuffer(data, dtype=np.float32)])
            last = eof and len(buf) <= C
            seg = buf[:C]
            if len(seg) > SR * 0.2:
                s = rec.create_stream()
                s.accept_waveform(SR, seg)
                rec.decode_stream(s)
                lo = offset + (overlap / 2 if not first else -1)
                hi = offset + chunk - overlap / 2 if not last else 1e12
                out.extend(w for w in tokens_to_words(s.result, offset) if lo <= w["s"] < hi)
            if progress:
                progress(offset + len(seg) / SR)
            if last:
                break
            buf = buf[C - O:]
            offset += (C - O) / SR
            first = False
    finally:
        proc.kill()
        proc.wait()
    return out


def snap_edges(path, s, e, wide=False):
    """Timestamps are only accurate to ~80ms. Look at the real audio and move
    each edge out to true silence; if speech is continuous, pad generously
    (better to clip a tiny neighbouring word than leak part of a swear)."""
    reach = 0.3 if wide else 0.18
    t0 = max(0.0, s - reach - 0.05)
    dur = (e + reach + 0.05) - t0
    raw = run([_tool("ffmpeg"), "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}",
               "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
              capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    hop = SR // 100
    if len(a) < hop * 5:
        return round(max(0, s - 0.12), 3), round(e + 0.12, 3)
    en = np.array([np.sqrt(np.mean(a[k:k + hop] ** 2)) for k in range(0, len(a) - hop, hop)])
    en = np.convolve(en, np.ones(3) / 3, mode="same")
    tt = t0 + np.arange(len(en)) * 0.01
    floor = 0.06 * float(en.max())

    def silent(lo, hi):
        idx = np.where((tt >= lo) & (tt <= hi) & (en < floor))[0]
        return idx if len(idx) else None

    lo, hi = silent(s - reach, s), silent(e, e + reach)
    ns = float(tt[lo[-1]]) if lo is not None else s - 0.12
    ne = float(tt[hi[0]] + 0.01) if hi is not None else e + 0.12
    return round(max(0, ns), 3), round(max(ne, e), 3)


# ---------------------------------------------------------------------------
# Ebook
# ---------------------------------------------------------------------------
def _html_paragraphs(markup):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(markup, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    paras = []
    for b in soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "blockquote", "div"]):
        if b.find(["p", "div", "li"]):
            continue
        txt = " ".join(b.get_text(" ").split())
        if txt:
            paras.append(txt)
    return paras or [p for p in soup.get_text("\n").split("\n") if p.strip()]


class EbookError(Exception):
    pass


def read_ebook(path):
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".epub":
        z = zipfile.ZipFile(p)
        names = z.namelist()
        enc = [n for n in names if n.endswith("encryption.xml")]
        if enc:
            data = z.read(enc[0])
            if b"EncryptedData" in data and data.count(b"EncryptedData") > data.lower().count(b"font"):
                raise EbookError("This ebook is copy-protected (DRM), so it can't be read. "
                                 "You can still clean the audiobook without it.")
        container = z.read("META-INF/container.xml").decode("utf8", "ignore")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = z.read(opf_path).decode("utf8", "ignore")
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        manifest = {}
        for item in re.findall(r"<item\b[^>]*>", opf):
            i = re.search(r'\bid="([^"]+)"', item)
            h = re.search(r'\bhref="([^"]+)"', item)
            if i and h:
                manifest[i.group(1)] = h.group(1)
        paras = []
        for idref in re.findall(r'<itemref\b[^>]*?idref="([^"]+)"', opf):
            href = manifest.get(idref)
            if href and (base + unquote(href)) in names:
                paras.extend(_html_paragraphs(z.read(base + unquote(href)).decode("utf8", "ignore")))
        return paras
    if ext == ".pdf":
        exe = shutil.which("pdftotext") or (str(HERE / "bin" / "pdftotext.exe")
                                           if (HERE / "bin" / "pdftotext.exe").exists() else None)
        if exe:
            txt = run([exe, str(p), "-"], capture_output=True, text=True).stdout
        else:
            try:
                from pypdf import PdfReader
            except ImportError:
                raise EbookError("PDF support isn't installed. Use the EPUB version if you have it.")
            txt = "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        return [" ".join(b.split()) for b in re.split(r"\n\s*\n", txt) if b.strip()]
    if ext in (".html", ".htm", ".xhtml"):
        return _html_paragraphs(p.read_text("utf8", "ignore"))
    if ext in (".txt", ".md"):
        return [" ".join(b.split()) for b in re.split(r"\n\s*\n", p.read_text("utf8", "ignore")) if b.strip()]
    if ext in (".azw", ".azw3", ".kfx", ".mobi"):
        raise EbookError("Kindle books are copy-protected and can't be read. "
                         "You can still clean the audiobook without it.")
    raise EbookError(f"Can't read {ext} files. Use EPUB, PDF or TXT.")


def align(eb, asr_n, gram=4):
    """Map each ebook word index to an ASR word index (or None)."""
    def uniq(seq):
        seen = {}
        for i in range(len(seq) - gram + 1):
            g = tuple(seq[i:i + gram])
            seen[g] = None if g in seen else i
        return {g: i for g, i in seen.items() if i is not None}

    ge, ga = uniq(eb), uniq(asr_n)
    pairs = sorted((ge[g], ga[g]) for g in ge.keys() & ga.keys())
    tails, tidx, prev = [], [], [None] * len(pairs)
    for k, (_, a) in enumerate(pairs):
        pos = bisect.bisect_left(tails, a)
        if pos == len(tails):
            tails.append(a)
            tidx.append(k)
        else:
            tails[pos], tidx[pos] = a, k
        prev[k] = tidx[pos - 1] if pos > 0 else None
    chain, k = [], (tidx[-1] if tidx else None)
    while k is not None:
        chain.append(pairs[k])
        k = prev[k]
    chain.reverse()
    mapping = [None] * len(eb)
    for e, a in chain:
        for d in range(gram):
            mapping[e + d] = a + d
    bounds = [(-gram, -gram)] + chain + [(len(eb), len(asr_n))]
    for (e0, a0), (e1, a1) in zip(bounds, bounds[1:]):
        es, ee, as_, ae = e0 + gram, e1, a0 + gram, a1
        if es >= ee or as_ >= ae or (e0 < 0 and e1 == len(eb)):
            continue
        if e0 < 0:
            es, as_ = max(es, ee - 400), max(as_, ae - 400)
        elif e1 == len(eb):
            ee, ae = min(ee, es + 400), min(ae, as_ + 400)
        sm = difflib.SequenceMatcher(None, eb[es:ee], asr_n[as_:ae], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
                for d in range(i2 - i1):
                    mapping[es + i1 + d] = as_ + j1 + d
    return mapping


def est_time(idx, mapping, asr):
    a = mapping[idx]
    if a is not None:
        return asr[a]["s"], asr[a]["e"], True, asr[a]["part"]
    lo = hi = None
    for d in range(1, 40):
        if lo is None and idx - d >= 0 and mapping[idx - d] is not None:
            lo = (idx - d, mapping[idx - d])
        if hi is None and idx + d < len(mapping) and mapping[idx + d] is not None:
            hi = (idx + d, mapping[idx + d])
        if lo and hi:
            break
    if not lo or not hi:
        return None
    t0, t1 = asr[lo[1]]["e"], asr[hi[1]]["s"]
    if asr[lo[1]]["part"] != asr[hi[1]]["part"] or t1 < t0 or t1 - t0 > 8:
        return None
    mid = t0 + (t1 - t0) * (idx - lo[0]) / (hi[0] - lo[0])
    return max(t0, mid - 0.45), min(t1, mid + 0.45), False, asr[lo[1]]["part"]


def span_times(asr, i, j):
    """Cut boundaries for ASR words i..j inclusive: from just before word i to
    just before the word after j."""
    part = asr[i]["part"]
    prev_e = asr[i - 1]["e"] if i > 0 and asr[i - 1]["part"] == part else 0
    s = max(asr[i]["s"] - 0.15, prev_e)
    e = asr[j]["e"]
    if j + 1 < len(asr) and asr[j + 1]["part"] == part and asr[j + 1]["s"] - e < 0.6:
        e = asr[j + 1]["s"] - 0.03
    else:
        e += 0.25
    return round(max(0, s), 3), round(e, 3)


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AI helper (optional). Uses the same local AI as CleanView (Ollama running
# gemma3:4b on this PC, nothing uploaded): reads the book for what the word
# lists miss, and gives a second opinion on what they flagged.
# ---------------------------------------------------------------------------
AI_TYPES = {
    "ref": "a sexual reference, sexual joke or innuendo, or talk about sex (ordinary romance, "
           "affection and kissing are NOT this)",
    "sex": "part of an explicit sex scene",
    "gore": "a graphic, gory description of injuries, wounds, dead bodies or violence (simply "
            "saying someone died, was shot or was found dead is NOT this)",
    "religion": "someone explaining, preaching or debating religious beliefs, or someone being "
                "angry with, blaming, hating or denying God, or losing their faith (brief mentions "
                "like praying, saying grace, thanking God, believing in God or going to church are "
                "NOT this)",
    "relationship": "a same-sex couple, romance, relationship or flirting (for example a man "
                    "flirting with or hitting on another man), or a non-traditional relationship "
                    "such as a throuple, polyamory, an open marriage, swingers or polygamy",
    "bully": "bullying or mean-spirited cruelty: taunting, name-calling, mocking or humiliating "
             "someone, or picking on someone weaker (an ordinary argument, a villain's plot or a "
             "police interrogation is NOT this)",
    "flirt": "flirting: someone flirting with, hitting on, winking at, sweet-talking or making "
             "romantic advances toward someone (a married couple being affectionate, a simple "
             "compliment or ordinary friendliness is NOT this)",
    "crude": "crude or gross-out humor: jokes about farting, pooping, peeing, burping, boogers or "
             "other bodily functions, toilet humor, or vulgar jokes and pranks (a character simply "
             "feeling sick or using the bathroom is NOT this)",
}

# Crude humor: words that are almost always toilet / gross-out humor in a story.
CRUDE_WORDS = _c([
    r"farts?", r"farted", r"farting", r"farty", r"poop(s|ed|ing|y)?", r"poo", r"poos", r"turds?",
    r"boogers?", r"burp(s|ed|ing)?", r"belch(es|ed|ing)?", r"diarrh(o)?ea", r"wedgies?",
    r"tooted", r"tooting", r"butthole", r"buttcheeks?", r"mooned", r"mooning", r"peed",
    r"peeing", r"pee", r"wee-?wee", r"number-?two", r"skidmarks?", r"snot", r"dookie",
])
CRUDE_PHRASES = [("pull", "my", "finger"), ("butt", "crack"), ("skid", "marks"),
                 ("dropped", "a", "deuce"), ("passed", "gas"), ("passing", "gas"), ("break", "wind"),
                 ("broke", "wind"), ("whoopee", "cushion"), ("number", "two")]


def crude_hit(words):
    if any(any(p.match(w) for p in CRUDE_WORDS) for w in words):
        return True
    return any(tuple(words[i:i + len(ph)]) == ph for ph in CRUDE_PHRASES for i in range(len(words)))


def _ai_module():
    try:
        import cleanview_ai as ai  # ships alongside CleanListen (shared with CleanView)
        return ai
    except Exception as ex:
        raise RuntimeError("The AI helper files are missing. Close and reopen CleanListen so it "
                           "can update, then try again.") from ex


LANGUAGE_DEFS = {
    "strong": "the f-word or c-word in any form",
    "moderate": "a crude swear word such as s***, b****, a**, a**hole, b******, p***ed or d***",
    "mild": "a mild swear word such as damn, hell used as a curse, crap, bloody used as a curse, "
            "or 'screw you' / 'screw it' as an insult ('screw it into the wall' is NOT this)",
    "deity": "God's or Jesus's name used as a swear or exclamation (not in a prayer or sincere "
             "talk about God; 'thank God' is fine)",
    "minced": "a soft substitute swear such as gosh, heck, freaking or darn",
    "sexual": "a sexual word such as sex, sexy or horny, or a crude word for body parts",
    "orientation": "a word about sexual orientation such as gay, lesbian, homosexual or bisexual "
                   "('gay' meaning cheerful or bright is NOT this)",
}


def _masked_text(words):
    return " ".join(mask(t) if find_language([norm(t)], ALL_CATS) else t for t in words)


# Words from the lists that can have an innocent meaning ("hell" the place, "bloody" covered in
# blood, "ass" a donkey, "gay" cheerful, "screw it in"). Only these (and God's name, which can be
# a sincere prayer) may be unticked by the AI helper, Claude or ChatGPT; every other listed word
# is muted every time it's said - even in a denial ("it's not sexual") or a question - unless the
# narrator didn't actually say it (misheard).
INNOCENT_WORDS = {"hell", "bloody", "ass", "asses", "arse", "dick", "dicks", "prick", "pricks",
                  "bugger", "climaxed", "homo", "homos", "queer", "queers", "gay", "gays", "pee",
                  "peed", "peeing", "screw", "craps"}


def may_untick_word(m, words=None):
    """Can a checker leave this listed word in? (see INNOCENT_WORDS)"""
    if m.get("cat") in ("deity", "ai", "claude"):
        return True
    ws = words if words is not None else [norm(w) for w in str(m.get("word_raw") or m.get("word", "")).split()]
    return any(w in INNOCENT_WORDS for w in ws)


def _ai_backed(kind, words):
    """Does a passage the AI on this PC flagged contain anything the word lists recognise
    for that kind? (Its unbacked finds are mostly false alarms, so they start unticked.)"""
    try:
        if kind in ("sex", "ref"):
            return is_explicit(words) or bool(find_language(words, ["sexual"]))
        if kind == "gore":
            return is_gory(words)
        if kind == "religion":
            return religion_score(words) > 0 or blames_god(words)
        if kind == "crude":
            return crude_hit(words)
        if kind == "bully":
            return bully_hit(words)
        if kind == "flirt":
            return flirt_hit(words)
    except Exception:
        pass
    return False


def _learned_examples():
    """Past choices (yours, then Claude's) for the AI on this PC to follow."""
    try:
        import cleanlisten_learn as learn
        t = learn.examples_text().strip()
        return (t + "\n\n") if t else ""
    except Exception:
        return ""


def ai_assist(asr, scenes, kinds, to_sentences, span_times, progress=None, cancel=None,
              chunk=40, overlap=6, mutes=None, cats=(), parts=None):
    """Checks every filter both ways: adds what the word lists missed (passages
    and single words) and unticks what they flagged wrongly, with a note."""
    ai = _ai_module()
    say = progress or (lambda f, m: None)
    ai.ensure_ai(lambda f, m: say(f, m))
    # relationship talk is left to the word lists and Claude/ChatGPT: the small AI here
    # flagged almost every man-and-woman scene as a same-sex relationship
    kinds = [k for k in kinds if k in AI_TYPES and k != "relationship"]
    lang = [c for c in cats if c in LANGUAGE_DEFS]
    mutes = mutes if mutes is not None else []
    if not kinds and not lang:
        return scenes
    # sentences with their word ranges
    sents, k = [], 0
    while k < len(asr):
        a_, b_ = to_sentences(k, k)
        sents.append((a_, b_, " ".join(w["t"] for w in asr[a_:b_ + 1])))
        k = b_ + 1
    # ---- 1. AI reads the book and QUOTES what it flags (no line numbers: a
    # small model often gets numbers wrong and flags the sentence next door)
    types = list(kinds) + (["language"] if lang else [])
    defs = "\n".join(f'- "{t}": {AI_TYPES[t]}' for t in kinds)
    if lang:
        defs += ('\n- "language": a word that is ' + "; or ".join(LANGUAGE_DEFS[c] for c in lang)
                 + ' (put the exact word in "word")')
    schema = {"type": "object", "properties": {"flags": {"type": "array", "items": {
        "type": "object", "properties": {"quote": {"type": "string"},
                                         "type": {"type": "string", "enum": types},
                                         "word": {"type": "string"}},
        "required": ["quote", "type"]}}}, "required": ["flags"]}
    sent_norm = [[norm(w) for w in t.split() if norm(w)] for _, _, t in sents]

    def locate(quote, lo, hi):
        q = [norm(w) for w in str(quote).split() if norm(w)]
        if len(q) < 2:
            return None
        best, best_i = 0.0, None
        for i in range(lo, hi):
            words = sent_norm[i]
            if not words:
                continue
            for st_ in range(0, max(1, len(words) - len(q) + 1)):
                r = difflib.SequenceMatcher(None, q, words[st_:st_ + len(q)], autojunk=False).ratio()
                if r > best:
                    best, best_i = r, i
                if r == 1.0:
                    break
        return best_i if best >= 0.8 else None

    cands, word_cands = set(), set()
    chunk = 25
    starts = list(range(0, len(sents), chunk - 3))
    for n, a in enumerate(starts):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(n / max(len(starts), 1), f"AI is reading the book · {100 * n // max(len(starts), 1)}%")
        part = sents[a:a + chunk]
        listing = "\n".join(f"- {t}" for _, _, t in part)
        prompt = _learned_examples() + ("You help a family decide which sentences of an audiobook to cut. Here are "
                  "sentences in order:\n\n" + listing + "\n\nFind sentences that CLEARLY contain "
                  "one of these:\n" + defs + "\n\nBe strict. Ordinary conversation, affection, "
                  "kissing, worry, danger, crime and death are NOT flagged unless they clearly fit "
                  "a type above. For each sentence you flag, copy its first 8 words exactly into "
                  "\"quote\". Answer in JSON like {\"flags\": [{\"quote\": \"first words of the "
                  "sentence\", \"type\": \"gore\"}]}; use an empty list if nothing fits.")
        try:
            res = ai.chat(prompt, schema=schema, timeout=300)
        except Exception:
            continue
        for f in res.get("flags", []):
            i = locate(f.get("quote", ""), a, a + len(part))
            if i is None:
                continue
            if f.get("type") in kinds:
                cands.add((i, f["type"]))
            elif f.get("type") == "language" and f.get("word"):
                word_cands.add((i, str(f["word"]).strip()))
        if a + chunk >= len(sents):
            break

    # ---- 2. strict second check of every AI find, one sentence at a time
    sure_schema = {"type": "object", "properties": {
        "fits": {"type": "boolean"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
        "required": ["fits", "confidence"]}

    def excerpt(i):
        prev = sents[i - 1][2] if i > 0 else ""
        nxt = sents[i + 1][2] if i + 1 < len(sents) else ""
        return f"{prev}\n>>> {sents[i][2]} <<<\n{nxt}".strip()

    def verify(question, i):
        try:
            res = ai.chat("Below is a short excerpt from an audiobook. The sentence between >>> and "
                          "<<< is the one being checked; the others are only context.\n\n" +
                          excerpt(i) + "\n\nQuestion: " + question + " Judge only the marked "
                          "sentence. Be strict: when in doubt, answer false.\nAnswer in JSON: "
                          '{"fits": true or false, "confidence": "high", "medium" or "low"}',
                          schema=sure_schema, timeout=120)
        except Exception:
            return None
        if res.get("fits") is not True:
            return None
        return res.get("confidence") if res.get("confidence") in ("high", "medium") else None

    found = {}
    todo = sorted(cands)
    for n, (i, kind) in enumerate(todo):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(n / max(len(todo), 1), "AI is double-checking what it found…")
        conf = verify(f"Does the marked sentence clearly contain {AI_TYPES[kind]}?", i)
        if conf:
            found.setdefault(kind, {})[i] = conf

    # ---- 3. second opinion on what the word lists flagged
    checks = [sc for sc in scenes if sc.get("kind") in AI_TYPES and not sc.get("ai")]
    yes_no = {"type": "object", "properties": {"fits": {"type": "boolean"}}, "required": ["fits"]}
    for n, sc in enumerate(checks):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(n / max(len(checks), 1), "AI is double-checking what was flagged…")
        try:
            res = ai.chat("Here is a passage from an audiobook:\n\n" + sc["text"][:4000] +
                          "\n\nDoes it contain " + AI_TYPES[sc["kind"]] +
                          '? Answer in JSON: {"fits": true} or {"fits": false}.', schema=yes_no,
                          timeout=120)
            if res.get("fits") is False:
                sc["cut"] = False
                sc["ai_note"] = "AI thinks this one is fine"
            elif res.get("fits") is True:
                sc["ai_note"] = "AI agrees"
        except Exception:
            pass

    # ---- 4. muted words: the AI only gets a say on words with an innocent meaning
    # too (hell, bloody, ass, Jesus, gay...). Clear swear words are never unticked.
    checkable = [m for m in mutes if m.get("i") is not None and
                 (m.get("cat") == "deity" or
                  any(norm(asr[x]["t"]) in INNOCENT_WORDS for x in range(m["i"], m["j"])))]
    fine_schema = {"type": "object", "properties": {"fine": {"type": "array", "items": {
        "type": "integer"}}}, "required": ["fine"]}
    for b0 in range(0, len(checkable), 20):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(b0 / max(len(checkable), 1), "AI is double-checking the muted words…")
        batch = checkable[b0:b0 + 20]
        rows = []
        for q, m in enumerate(batch):
            i, j = m["i"], m["j"]
            before = " ".join(w["t"] for w in asr[max(0, i - 10):i])
            after = " ".join(w["t"] for w in asr[j:j + 8])
            rows.append(f"{q}: ...{before} [[{' '.join(w['t'] for w in asr[i:j])}]] {after}...")
        prompt = ("Each numbered line below has one word or phrase in [[double brackets]] that a "
                  "family's filter plans to mute from an audiobook:\n\n" + "\n".join(rows) +
                  "\n\nList ONLY the numbers where you are sure the bracketed word has an innocent "
                  "meaning, for example: 'hell' as a place in a sermon, 'bloody' meaning covered in "
                  "blood, 'ass' meaning a donkey, 'Jesus' in a sincere prayer, 'gay' meaning "
                  "cheerful or bright. Answer in JSON like {\"fine\": [3, 7]}; use an empty list "
                  "if none are innocent.")
        try:
            res = ai.chat(prompt, schema=fine_schema, timeout=180)
            for q in res.get("fine", []):
                if isinstance(q, int) and 0 <= q < len(batch):
                    batch[q]["on"] = False
                    batch[q]["note"] = "AI thinks this isn't swearing"
        except Exception:
            pass

    # ---- 5. words the lists missed (often ones the speech recognition misheard)
    for n, (li, word) in enumerate(sorted(word_cands)):
        if cancel and cancel():
            raise KeyboardInterrupt
        target = [norm(w) for w in word.split() if norm(w)]
        if not target:
            continue
        a_, b_, _ = sents[li]
        span = [norm(asr[x]["t"]) for x in range(a_, b_ + 1)]
        hit = next((x for x in range(len(span)) if span[x:x + len(target)] == target), None)
        if hit is None:
            continue
        i, j = a_ + hit, a_ + hit + len(target)
        part = asr[i]["part"]
        if any(m["part"] == part and not (asr[j - 1]["e"] < m["s"] or asr[i]["s"] > m["e"])
               for m in mutes):
            continue
        say(n / max(len(word_cands), 1), "AI is double-checking words it found…")
        conf = verify(f'Is the word "{word}" in the marked sentence used as ' +
                      "; or as ".join(LANGUAGE_DEFS[c] for c in lang) + "?", li)
        if not conf:
            continue
        s_, e_ = asr[i]["s"], asr[j - 1]["e"]
        if parts:
            try:
                s_, e_ = snap_edges(parts[part], s_, e_)
            except Exception:
                pass
        mutes.append({"part": part, "s": s_, "e": e_, "cat": "ai", "src": "ai", "i": i, "j": j,
                      "word": " ".join(mask(asr[x]["t"]) for x in range(i, j)),
                      "ctx": _masked_text([w["t"] for w in asr[max(0, i - 6):i]]),
                      "ctx_after": _masked_text([w["t"] for w in asr[j:j + 5]]),
                      **raw_fields([w["t"] for w in asr[max(0, i - 6):j + 5]],
                                   min(i, 6), min(i, 6) + (j - i)),
                      "on": conf == "high",
                      "note": "found by AI" if conf == "high" else "AI suggests"})
    mutes.sort(key=lambda m: (m["part"], m["s"]))

    # ---- 6. turn verified AI finds into passages (adjacent sentences merge).
    # Very sure = ticked; somewhat sure = unticked "AI suggests" for you to decide.
    for kind, idx_conf in found.items():
        runs = []
        for i in sorted(idx_conf):
            if runs and i <= runs[-1][-1] + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        for run_ in runs:
            a_, b_ = sents[run_[0]][0], sents[run_[-1]][1]
            if asr[a_]["part"] != asr[b_]["part"]:
                continue
            s_, e_ = span_times(asr, a_, b_)
            part = asr[a_]["part"]
            if any(x["part"] == part and not (e_ < x["s"] or s_ > x["e"]) for x in scenes):
                continue  # already flagged by the word lists
            sure = any(idx_conf[i] == "high" for i in run_)
            # only ticked when the word lists back it up; otherwise left for you to decide
            sure = sure and _ai_backed(kind, [asr[k]["n"] for k in range(a_, b_ + 1)])
            scenes.append({"kind": kind, "part": part, "s": s_, "e": e_, "ai": True,
                           "cut": sure, "ai_note": "found by AI" if sure else "AI suggests",
                           "text": " ".join(w["t"] for w in asr[a_:b_ + 1])})
    say(1.0, "AI check done")
    return scenes


def load_asr(workdir, parts):
    """The transcript as one word list (same shape analyze() uses)."""
    done = json.loads((Path(workdir) / "transcript.json").read_text())
    return [{**w, "part": pi, "n": norm(w["t"])} for pi, p in enumerate(parts) for w in done[p]]


def analyze(parts, workdir, ebook=None, groups=("swearing", "mild", "deity", "sexual"),
            find_sex=True, progress=None, log=print, model_dir=DEFAULT_MODEL,
            find_refs=False, find_gore=False, find_religion=False, find_relationships=False,
            find_crude=False, use_ai=False,
            threads=None, cancel=None, find_bully=False, find_flirt=False, use_claude=False):
    """progress(fraction 0..1, message). Returns the analysis dict (also saved
    to workdir/analysis.json)."""
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    parts = [str(Path(p).resolve()) for p in parts]
    cats = [c for g in groups for c in GROUPS[g]]
    say = progress or (lambda f, m: None)

    tfile = work / "transcript.json"
    done = json.loads(tfile.read_text()) if tfile.exists() else {}
    durs = {p: probe_duration(p) for p in parts}
    total = sum(durs.values()) or 1.0
    todo = [p for p in parts if p not in done]
    if todo:
        say(0.0, "Loading the listening model…")
        rec = load_recognizer(model_dir, threads)
        t0 = time.time()
        before = sum(durs[p] for p in parts if p in done)
        heard = 0.0
        for n, p in enumerate(todo, 1):
            def prog(sec, p=p, n=n):
                got = heard + sec
                rate = got / max(time.time() - t0, 1e-6)
                left = (total - before - got) / max(rate, 1e-6)
                frac = (before + got) / total
                eta = f"about {left / 60:.0f} min left" if got > 60 else "estimating time…"
                say(0.92 * frac, f"Listening to part {n} of {len(todo)} · {eta}")
            done[p] = transcribe(p, rec, prog, cancel=cancel)
            heard += durs[p]
            tfile.write_text(json.dumps(done))
            log(f"Listened to {Path(p).name}: {len(done[p])} words")

    asr = [{**w, "part": pi, "n": norm(w["t"])} for pi, p in enumerate(parts) for w in done[p]]
    asr_n = [w["n"] for w in asr]

    say(0.93, "Finding language…")
    asr_t = [w["t"] for w in asr]
    mutes = []
    for i, j, cat in find_language(asr_n, cats):
        b, a = clean_context(asr_t, asr_n, i, j)
        mutes.append({"part": asr[i]["part"], "s": asr[i]["s"], "e": asr[j - 1]["e"], "cat": cat,
                      "src": "audio", "word": " ".join(mask(asr_t[k]) for k in range(i, j)),
                      "ctx": b, "ctx_after": a, "i": i, "j": j, **raw_fields(asr_t, i, j)})

    paras = mapping = None
    ebook_note = ""
    if ebook:
        say(0.94, "Checking against the ebook…")
        try:
            paras = read_ebook(ebook)
        except EbookError as ex:
            ebook_note = str(ex)
            log(ebook_note)
            paras = None
    if paras:
        eb_words, eb_para = [], []
        for pi_, para in enumerate(paras):
            for w in para.split():
                if norm(w):
                    eb_words.append(w)
                    eb_para.append(pi_)
        eb_n = [norm(w) for w in eb_words]
        mapping = align(eb_n, asr_n)
        aligned = sum(m is not None for m in mapping)
        pct = 100 * aligned / max(len(eb_n), 1)
        if pct < 30:
            ebook_note = (f"Only {pct:.0f}% of the ebook matched the audio — "
                          "is it the same book? Ebook check skipped.")
            log(ebook_note)
            paras = mapping = None
        else:
            added = 0
            for i, j, cat in find_language(eb_n, cats):
                t = est_time(i, mapping, asr)
                if not t:
                    continue
                s, e, exact, part = t
                if j - i > 1:
                    t2 = est_time(j - 1, mapping, asr)
                    if t2:
                        e = max(e, t2[1])
                if any(m["part"] == part and m["s"] - 0.8 <= s <= m["e"] + 0.8 for m in mutes):
                    continue
                b, a = clean_context(eb_words, eb_n, i, j)
                mutes.append({"part": part, "s": round(s, 3), "e": round(e, 3), "cat": cat,
                              "src": "ebook" if exact else "ebook-estimated",
                              "word": " ".join(mask(w) for w in eb_words[i:j]),
                              "ctx": b, "ctx_after": a, **raw_fields(eb_words, i, j)})
                added += 1
            ebook_note = f"Ebook matched {pct:.0f}% of the audio and caught {added} extra word(s)."
            log(ebook_note)

    mutes.sort(key=lambda m: (m["part"], m["s"]))
    say(0.96, "Fine-tuning mute timing…")
    for m in mutes:
        m["s"], m["e"] = snap_edges(parts[m["part"]], m["s"], m["e"], m["src"] == "ebook-estimated")

    ends = {k for k, w in enumerate(asr) if re.search(r"[.?!][\"'\u201d\u2019]?$", w["t"])}

    def to_sentences(a_, b_):
        while a_ > 0 and (a_ - 1) not in ends and asr[a_ - 1]["part"] == asr[a_]["part"]:
            a_ -= 1
        while b_ + 1 < len(asr) and b_ not in ends and asr[b_ + 1]["part"] == asr[b_]["part"]:
            b_ += 1
        return a_, b_

    def find_passages(score_fn, terms_c, threshold, kind):
        """Stretches whose vocabulary scores above threshold. With an ebook the
        cut follows paragraph edges; without, sentence edges in the transcript.
        A passage starts and ends on a paragraph/sentence that is itself heavy
        with the content, so a passing mention next door is left alone."""
        top = max(terms_c)

        def raw(ws):
            return sum(wt for w in ws for wt, pats in terms_c.items() if any(p.match(w) for p in pats))

        def nstrong(ws):
            return sum(1 for w in ws if any(p.match(w) for p in terms_c[top]))

        def edge_ok(ws):
            return nstrong(ws) >= 2 or raw(ws) >= top + 1  # one strong word plus some support

        def keeps(edge, inner):
            # an edge unit stays if it's heavy itself, or it has a content word
            # and sits right against a very heavy unit (e.g. the last line of a sermon)
            return edge_ok(edge) or (nstrong(edge) > 0 and raw(inner) >= 2 * top)

        def trim(units, words_of):
            while units and not keeps(words_of(units[0]), words_of(units[1]) if len(units) > 1 else []):
                units = units[1:]
            while units and not keeps(words_of(units[-1]), words_of(units[-2]) if len(units) > 1 else []):
                units = units[:-1]
            return units

        out = []
        if paras:
            pwords = {}
            for k, pi_ in enumerate(eb_para):
                pwords.setdefault(pi_, []).append(k)
            ids = sorted(pwords)
            pw = {q: [eb_n[k] for k in pwords[q]] for q in ids}
            hot = set()
            for x in range(len(ids)):
                win = ids[x:x + 3]
                if score_fn([w for q in win for w in pw[q]]) >= threshold:
                    hot.update(q for q in win if nstrong(pw[q]))
            runs = []
            for q in sorted(hot):
                if runs and ids.index(q) - ids.index(runs[-1][-1]) <= 2:
                    runs[-1].extend(ids[ids.index(runs[-1][-1]) + 1: ids.index(q) + 1])
                else:
                    runs.append([q])
            for run_ in runs:
                run_ = trim(run_, lambda q: pw[q])
                if not run_ or not score_fn([w for q in run_ for w in pw[q]]):
                    continue
                al = [mapping[k] for q in run_ for k in pwords[q] if mapping[k] is not None]
                if len(al) < 5:
                    continue
                i0, i1 = min(al), max(al)
                if asr[i0]["part"] != asr[i1]["part"]:
                    i1 = max(a_ for a_ in al if asr[a_]["part"] == asr[i0]["part"])
                s_, e_ = span_times(asr, i0, i1)
                out.append({"kind": kind, "part": asr[i0]["part"], "s": s_, "e": e_,
                            "text": "\n\n".join(paras[q] for q in run_)})
            return out
        # no ebook: 60-second windows over the transcript, then sentence runs
        k, flagged = 0, []
        while k < len(asr):
            j = k
            while j < len(asr) and asr[j]["part"] == asr[k]["part"] and asr[j]["s"] - asr[k]["s"] < 60:
                j += 1
            if score_fn(asr_n[k:j]) >= threshold:
                flagged.append([k, j - 1])
            step = k
            while step < len(asr) and asr[step]["part"] == asr[k]["part"] and asr[step]["s"] - asr[k]["s"] < 20:
                step += 1
            k = max(step, k + 1)
        merged = []
        for a_, b_ in flagged:
            if merged and asr[a_]["part"] == asr[merged[-1][0]]["part"] and a_ <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b_)
            else:
                merged.append([a_, b_])
        for a_, b_ in merged:
            a_, b_ = to_sentences(a_, b_)
            sents, x = [], a_
            while x <= b_:
                sa, sb = to_sentences(x, x)
                sents.append((sa, sb))
                x = sb + 1
            sw = lambda se: asr_n[se[0]:se[1] + 1]
            runs, cur, gap = [], [], 0
            for se in sents:
                if nstrong(sw(se)):
                    cur.append(se)
                    gap = 0
                elif cur and gap == 0:
                    cur.append(se)  # allow one quieter sentence inside a passage
                    gap = 1
                else:
                    if cur:
                        runs.append(cur)
                    cur, gap = [], 0
            if cur:
                runs.append(cur)
            for run_ in runs:
                run_ = trim(run_, sw)
                if not run_:
                    continue
                ra, rb = run_[0][0], run_[-1][1]
                if not score_fn(asr_n[ra:rb + 1]):
                    continue
                s_, e_ = span_times(asr, ra, rb)
                out.append({"kind": kind, "part": asr[ra]["part"], "s": s_, "e": e_,
                            "text": " ".join(w["t"] for w in asr[ra:rb + 1])})
        return out

    scenes = []
    if find_sex:
        say(0.97, "Looking for sex scenes\u2026")
        scenes += find_passages(sex_score, SEX_C, SEX_WINDOW_SCORE, "sex")
    if find_gore:
        say(0.98, "Looking for gory descriptions\u2026")
        scenes += find_passages(gore_score, GORE_C, GORE_WINDOW_SCORE, "gore")
    if find_refs:
        # any sentence that talks about sex, even in passing
        say(0.99, "Looking for sexual references\u2026")
        refs = []
        for i, j, _ in find_language(asr_n, ["sexual"]) + [
                (x, x + 1, "") for x in range(len(asr)) if is_explicit([asr_n[x]])]:
            a_, b_ = to_sentences(i, j - 1)
            if refs and refs[-1][0] == asr[a_]["part"] and a_ <= refs[-1][2] + 1:
                refs[-1][2] = max(refs[-1][2], b_)
            else:
                refs.append([asr[a_]["part"], a_, b_])
        for part, a_, b_ in refs:
            s_, e_ = span_times(asr, a_, b_)
            if any(sc["part"] == part and sc["s"] - 1 <= s_ and e_ <= sc["e"] + 1 for sc in scenes):
                continue  # already inside a scene being cut
            scenes.append({"kind": "ref", "part": part, "s": s_, "e": e_,
                           "text": " ".join(w["t"] for w in asr[a_:b_ + 1])})
    if find_religion:
        say(0.99, "Looking for religious content\u2026")
        rel = find_passages(religion_score, RELIGION_C, RELIGION_WINDOW_SCORE, "religion")
        # single sentences that blame or hate God, or deny God
        k = 0
        while k < len(asr):
            a_, b_ = to_sentences(k, k)
            if blames_god(asr_n[a_:b_ + 1]):
                s_, e_ = span_times(asr, a_, b_)
                part = asr[a_]["part"]
                inside = any(x["part"] == part and x["s"] - 1 <= s_ and e_ <= x["e"] + 1 for x in rel)
                if not inside:
                    if rel and rel[-1]["part"] == part and rel[-1].get("blame") and s_ - rel[-1]["e"] < 2:
                        rel[-1]["e"] = e_
                        rel[-1]["text"] += " " + " ".join(w["t"] for w in asr[a_:b_ + 1])
                    else:
                        rel.append({"kind": "religion", "blame": True, "part": part, "s": s_, "e": e_,
                                    "text": " ".join(w["t"] for w in asr[a_:b_ + 1])})
            k = b_ + 1
        scenes += rel
    if find_relationships:
        say(0.99, "Looking for relationship content\u2026")
        rel_s, k = [], 0
        while k < len(asr):
            a_, b_ = to_sentences(k, k)
            if relationship_hit(asr_n[a_:b_ + 1]):
                if rel_s and rel_s[-1][0] == asr[a_]["part"] and a_ <= rel_s[-1][2] + 1:
                    rel_s[-1][2] = b_
                else:
                    rel_s.append([asr[a_]["part"], a_, b_])
            k = b_ + 1
        for part, a_, b_ in rel_s:
            s_, e_ = span_times(asr, a_, b_)
            if any(x["part"] == part and x["s"] - 1 <= s_ and e_ <= x["e"] + 1 for x in scenes):
                continue
            scenes.append({"kind": "relationship", "part": part, "s": s_, "e": e_,
                           "text": " ".join(w["t"] for w in asr[a_:b_ + 1])})
    # sentence-level filters: each flagged sentence (and neighbours that also hit) is cut
    for on, hit, kind, msg in ((find_crude, crude_hit, "crude", "Looking for crude humor…"),
                               (find_bully, bully_hit, "bully", "Looking for bullying…"),
                               (find_flirt, flirt_hit, "flirt", "Looking for flirting…")):
        if not on:
            continue
        say(0.99, msg)
        cr, k = [], 0
        while k < len(asr):
            a_, b_ = to_sentences(k, k)
            if hit(asr_n[a_:b_ + 1]):
                if cr and cr[-1][0] == asr[a_]["part"] and a_ <= cr[-1][2] + 1:
                    cr[-1][2] = b_
                else:
                    cr.append([asr[a_]["part"], a_, b_])
            k = b_ + 1
        for part, a_, b_ in cr:
            s_, e_ = span_times(asr, a_, b_)
            if any(x["part"] == part and x["s"] - 1 <= s_ and e_ <= x["e"] + 1 for x in scenes):
                continue
            scenes.append({"kind": kind, "part": part, "s": s_, "e": e_,
                           "text": " ".join(w["t"] for w in asr[a_:b_ + 1])})
    ai_note = ""
    kinds = [k for k, on in (("ref", find_refs), ("sex", find_sex), ("gore", find_gore),
                             ("religion", find_religion), ("relationship", find_relationships),
                             ("crude", find_crude), ("bully", find_bully),
                             ("flirt", find_flirt)) if on]
    if use_ai and use_claude:
        # Claude/ChatGPT reads the whole book anyway; the AI on this PC mostly added noise
        # (in one book it flagged 406 things and Claude cleared 387), so it's skipped
        ai_note = "Skipped the AI on this PC because the final check reads everything."
        use_ai = False
    if use_ai:
        try:
            for sc in scenes:
                sc.setdefault("cut", True)
            ai_assist(asr, scenes, kinds, to_sentences, span_times,
                      progress=lambda f, m: say(0.99, m), cancel=cancel,
                      mutes=mutes, cats=cats, parts=parts)
            n_sure = (sum(1 for x in scenes if x.get("ai") and x.get("cut")) +
                      sum(1 for m in mutes if m.get("src") == "ai" and m.get("on", True)))
            n_sugg = (sum(1 for x in scenes if x.get("ai") and not x.get("cut")) +
                      sum(1 for m in mutes if m.get("src") == "ai" and not m.get("on", True)))
            n_off = (sum(1 for x in scenes if x.get("ai_note") == "AI thinks this one is fine") +
                     sum(1 for m in mutes if m.get("note") == "AI thinks this isn't swearing"))
            ai_note = (f"AI helper added {n_sure} it's sure about, suggested {n_sugg} more for you "
                       f"to decide (left unticked), and unticked {n_off} it thinks were flagged "
                       f"by mistake.")
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            ai_note = f"AI helper couldn't run ({ex}); results are from the word lists only."
        log(ai_note)
    scenes.sort(key=lambda x: (x["part"], x["s"]))
    for n, sc in enumerate(scenes, 1):
        sc["id"] = n
        sc.setdefault("cut", True)
    for n, m in enumerate(mutes, 1):
        m["id"] = n
        m.setdefault("on", True)
    # sentence word ranges, kept so Claude (and the Ask Claude chat) can read the book later
    sents, k = [], 0
    while k < len(asr):
        a_, b_ = to_sentences(k, k)
        sents.append([a_, b_])
        k = b_ + 1

    st = {"parts": parts, "groups": list(groups), "mutes": mutes, "scenes": scenes,
          "ebook": ebook, "ebook_note": ebook_note, "duration": total, "words": len(asr),
          "ai_note": ai_note, "sentences": sents, "filters": {"cats": cats, "kinds": kinds}}
    try:   # what CleanListen has learned from your past choices (and Claude's, and the shared file)
        import cleanlisten_learn as learn
        import cleanlisten_claude as cc
        st["learn_note"] = " ".join(learn.apply(
            st, asr, lambda a_, b_, kind, on, note: cc._add_passage(st, asr, a_, b_, kind, on, note, "",
                                                                    src="you"),
            lambda n_, words, cat, note: cc._add_word(st, asr, n_, words, cat, True, note, "")))
        st["scenes"].sort(key=lambda x: (x["part"], x["s"]))
    except Exception as ex:
        log(f"Learned choices not applied: {ex}")
    if use_claude:
        try:
            import cleanlisten_claude as cc
            cc.review(st, asr, progress=lambda f, m: say(0.99, m), cancel=cancel)
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            st["claude_note"] = (f"Claude couldn't check this book ({ex}). The results below are "
                                 "from the word lists" + (" and the AI helper." if use_ai else "."))
        log(st.get("claude_note", ""))
    (work / "analysis.json").write_text(json.dumps(st, indent=1))
    say(1.0, "Done listening.")
    return st


# ---------------------------------------------------------------------------
# Chapters (for Yoto and players that can't skip inside one long file)
# ---------------------------------------------------------------------------
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
             "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
             "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
             "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
CHAPTER_WORDS = {"prologue", "epilogue", "interlude", "introduction", "afterword", "foreword"}
TRACK_MAX = 58 * 60  # Yoto allows 60 min per track; leave a little room


def _chapter_number(words, k):
    """Read a chapter number starting at words[k] ("one", "twenty-three", "12")."""
    w = words[k] if k < len(words) else ""
    if w.isdigit():
        return int(w), k + 1
    parts = w.replace("-", " ").split()
    if parts and all(p in NUM_WORDS for p in parts):
        n, j = sum(NUM_WORDS[p] for p in parts), k + 1
        # "twenty three" spoken as two words
        if n % 10 == 0 and n >= 20 and j < len(words) and words[j] in NUM_WORDS and NUM_WORDS[words[j]] < 10:
            n += NUM_WORDS[words[j]]
            j += 1
        return n, j
    return None, k


def find_chapters(asr):
    """Chapter starts the narrator announces after a pause: 'Chapter One',
    'Chapter 12', 'Prologue'. Returns [{part, t, title}]."""
    out = []
    for k, w in enumerate(asr):
        n = w["n"]
        prev = asr[k - 1] if k > 0 and asr[k - 1]["part"] == w["part"] else None
        gap = (w["s"] - prev["e"]) if prev else 99
        sentence_start = prev is None or gap >= 0.45 or re.search(r"[.?!:;\"”]$", prev["t"])
        if not sentence_start:
            continue  # "...as she read in chapter two..." is not a heading
        if n == "chapter":
            num, _ = _chapter_number([x["n"] for x in asr[k + 1:k + 4]], 0)
            if num is not None:
                out.append({"part": w["part"], "t": max(0.0, w["s"] - 0.3), "title": f"Chapter {num}"})
        elif n in CHAPTER_WORDS:
            nxt = asr[k + 1] if k + 1 < len(asr) and asr[k + 1]["part"] == w["part"] else None
            if not nxt or nxt["s"] - w["e"] > 0.35 or re.search(r"[.?!:]$", w["t"]):
                out.append({"part": w["part"], "t": max(0.0, w["s"] - 0.3), "title": n.capitalize()})
    return out


def _shift(t, cuts):
    """Where time t (original) lands after the cuts are removed."""
    removed = sum(min(e, t) - s for s, e in cuts if s < t)
    return max(0.0, t - removed)


def plan_tracks(asr, clean_durs, cuts_by_part):
    """Chapter tracks on ONE continuous timeline across all the cleaned files,
    so a chapter can span several CD tracks / parts. Adds splits so no track
    runs over an hour; books with no spoken chapter headings get ~30-minute
    sections at natural pauses. Returns [{"g": start_seconds, "title"}]."""
    offsets = [0.0]
    for d in clean_durs:
        offsets.append(offsets[-1] + d)
    total = offsets[-1]

    def g(part, t):
        return offsets[part] + _shift(t, cuts_by_part.get(part, []))

    starts = []
    for c in find_chapters(asr):
        at = g(c["part"], c["t"])
        if starts and at - starts[-1]["g"] < 5:
            continue
        starts.append({"g": at, "title": c["title"]})
    pauses = [(offsets[j], 2.0) for j in range(1, len(clean_durs))]  # file boundaries
    for k in range(1, len(asr)):
        if asr[k]["part"] == asr[k - 1]["part"]:
            gap = asr[k]["s"] - asr[k - 1]["e"]
            if gap > 0.6:
                pauses.append((g(asr[k]["part"], asr[k - 1]["e"] + gap / 2), gap))
    no_chapters = not starts
    if no_chapters:
        starts = [{"g": 0.0, "title": None}]
    elif starts[0]["g"] > 20:
        starts = [{"g": 0.0, "title": "Opening"}] + starts
    starts[0]["g"] = 0.0
    target = 30 * 60 if no_chapters else TRACK_MAX
    tracks, section = [], 0
    for x, st_ in enumerate(starts):
        end = starts[x + 1]["g"] if x + 1 < len(starts) else total
        pieces = max(1, int(np.ceil((end - st_["g"]) / target)))
        cut_at = [st_["g"]]
        for q in range(1, pieces):
            want = st_["g"] + (end - st_["g"]) * q / pieces
            cands = [p for p in pauses if abs(p[0] - want) < 120]
            cut_at.append(max(cands, key=lambda p: p[1] - abs(p[0] - want) / 60)[0] if cands else want)
        for q, at in enumerate(cut_at, 1):
            if no_chapters:
                section += 1
                title = f"Section {section}"
            elif pieces > 1:
                title = f"{st_['title']} ({q} of {pieces})"
            else:
                title = st_["title"]
            tracks.append({"g": at, "title": title})
    return tracks


def split_tracks(clean_files, clean_durs, tracks, outdir, book_title, log=print):
    """Write one MP3 per track into a single numbered "Chapters" folder,
    joining pieces of several cleaned files when a chapter spans them."""
    import tempfile
    offsets = [0.0]
    for dd in clean_durs:
        offsets.append(offsets[-1] + dd)
    total = offsets[-1]
    made = []
    for x, t in enumerate(tracks):
        g0 = t["g"]
        g1 = tracks[x + 1]["g"] if x + 1 < len(tracks) else total
        if g1 - g0 < 1:
            continue
        segs = []
        for j, f in enumerate(clean_files):
            a, b = max(g0, offsets[j]), min(g1, offsets[j + 1])
            if b - a > 0.05:
                segs.append((f, a - offsets[j], b - offsets[j]))
        if segs:
            made.append({"title": t["title"], "segs": segs})
    d = Path(outdir) / "Chapters"
    if d.exists():
        for old in d.glob("*.mp3"):  # clear files from an earlier run of this book
            try:
                old.unlink()
            except OSError:
                pass
    d.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(made))))
    all_mp3 = all(Path(f).suffix.lower() == ".mp3" for f in clean_files)
    codec = ["-c", "copy"] if all_mp3 else ["-c:a", "libmp3lame", "-b:a", "128k"]
    for i, m in enumerate(made, 1):
        safe = re.sub(r'[\\/:*?"<>|]', "", m["title"])
        dst = d / f"{i:0{width}d} {safe}.mp3"  # Yoto takes MP3, so chapter files are always MP3
        tags = ["-id3v2_version", "3", "-metadata", f"title={m['title']}",
                "-metadata", f"track={i}/{len(made)}", "-metadata", f"album={book_title}"]
        if len(m["segs"]) == 1:
            f, a, b = m["segs"][0]
            cmd = [_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                   "-i", str(f), "-map", "0:a", *codec, *tags, str(dst)]
            r = run(cmd, capture_output=True, text=True)
        else:
            lines = ["ffconcat version 1.0"]
            for f, a, b in m["segs"]:
                fp = Path(f).resolve().as_posix().replace("'", "'\\''")
                lines += [f"file '{fp}'", f"inpoint {a:.3f}", f"outpoint {b:.3f}"]
            fd, lst = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf8") as fh:
                fh.write("\n".join(lines) + "\n")
            try:
                cmd = [_tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                       "-map", "0:a", *codec, *tags, str(dst)]
                r = run(cmd, capture_output=True, text=True)
            finally:
                try:
                    os.unlink(lst)
                except OSError:
                    pass
        if r.returncode != 0:
            raise RuntimeError(f"Couldn't make chapter file {dst.name}:\n{r.stderr[-500:]}")
    log(f"Made {len(made)} chapter files")
    return {"tracks": len(made), "cards": 1, "folders": [str(d)],
            "titles": [m["title"] for m in made]}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _ranges(rs):
    return "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in rs)


def render(workdir, outdir, cuts=None, progress=None, log=print, chapters=False, mutes=None):
    """Write clean audio. cuts: list of {"part","s","e","note"}; defaults to
    the scenes marked cut=True in the analysis. chapters=True also writes one
    file per chapter (Yoto-friendly)."""
    work = Path(workdir)
    st = json.loads((work / "analysis.json").read_text())
    if cuts is None:
        cuts = [c for c in st["scenes"] if c.get("cut")]
    if mutes is not None:
        st["mutes"] = sorted(mutes, key=lambda m: (m["part"], m["s"]))
    else:  # no review screen: leave out what the AI unticked
        st["mutes"] = [m for m in st["mutes"] if m.get("on", True)]
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda f, m: None)
    total_cut_sec = 0.0
    report = []
    clean_files = []
    multi_dir = len({str(Path(p).parent) for p in st["parts"]}) > 1
    used_names = set()
    for pi, p in enumerate(st["parts"]):
        say(pi / len(st["parts"]), f"Saving part {pi + 1} of {len(st['parts'])}…")
        mr = sorted((m["s"], m["e"]) for m in st["mutes"] if m["part"] == pi)
        cr = sorted((c["s"], c["e"]) for c in cuts if c["part"] == pi)
        src = Path(p)
        ext = src.suffix.lower()
        filt = []
        if mr:
            filt.append(f"volume=volume=0:enable='{_ranges(mr)}'")
        if cr:
            filt.append(f"aselect='not({_ranges(cr)})',asetpts=N/SR/TB")
        fs = work / f"filter_{pi}.txt"
        fs.write_text(",".join(filt) or "anull")
        br = run([_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                  "stream=bit_rate", "-of", "default=nw=1:nk=1", str(src)],
                 capture_output=True, text=True).stdout.strip()
        br = br if br.isdigit() else "96000"
        if ext in (".m4b", ".m4a", ".mp4", ".aac"):
            codec, out_ext = ["-c:a", "aac", "-b:a", br], ext
        else:
            codec, out_ext = ["-c:a", "libmp3lame", "-b:a", br], ".mp3"
        # books split into Disc 1, Disc 2... folders: keep the disc in the name so
        # files sort in order and identically named tracks don't overwrite each other
        stem = f"{src.parent.name} - {src.stem}" if multi_dir else src.stem
        name, k = stem + out_ext, 2
        while name.lower() in used_names:
            name, k = f"{stem} ({k}){out_ext}", k + 1
        used_names.add(name.lower())
        dst = out / name
        # Write to a temporary file first, then swap it in (so a half-written file
        # never replaces a good one, and a file that's open elsewhere is reported).
        tmp = out / f"~saving~ {name}"
        # ffmpeg 7+ reads filter files with "-/filter:a"; older builds use
        # "-filter_script:a"; a short filter can also go straight on the command line.
        # For each, fall back to dropping cover art / chapters, then to just the
        # first audio stream, if the output container objects to them.
        text_filter = fs.read_text()
        fopts = [["-/filter:a", str(fs)], ["-filter_script:a", str(fs)]]
        if len(text_filter) < 20000:
            fopts.append(["-filter:a", text_filter])
        extras = (["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-map_metadata", "0",
                   "-map_chapters", "0"],
                  ["-map", "0:a", "-map_metadata", "0"],
                  ["-map", "0:a:0", "-vn", "-sn", "-dn", "-map_chapters", "-1"])
        r, errors = None, []
        for fopt in fopts:
            base = [_tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), *fopt]
            for extra in extras:
                r = run(base + extra + codec + [str(tmp)], capture_output=True, text=True)
                if r.returncode == 0:
                    break
                errors.append((" ".join(fopt[:1] + extra), r.stderr.strip()))
                if "Unrecognized option" in r.stderr or "Error splitting the argument" in r.stderr:
                    break      # this ffmpeg doesn't know that option; try the next way
            if r.returncode == 0:
                break
        if r.returncode != 0:
            try:
                (work / "save_error.txt").write_text(
                    "\n\n".join(f"[{how}]\n{err}" for how, err in errors), encoding="utf8")
            except OSError:
                pass
            real = [e for _, e in errors if "Unrecognized option" not in e
                    and "Error splitting the argument" not in e] or [e for _, e in errors] or [""]
            msg = real[0][-600:]
            if any(k in msg for k in ("Permission denied", "being used by another process")):
                msg = ("The file is open in another program (a player, Yoto app or cloud sync?). "
                       "Close it and press Save again.\n\n" + msg)
            try:
                tmp.unlink()
            except OSError:
                pass
            raise RuntimeError(f"Couldn't save {src.name}:\n{msg}")
        try:
            os.replace(tmp, dst)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise RuntimeError(f"Couldn't replace {dst.name} in {out} — it's open in another "
                               "program (a player, the Yoto app or cloud sync?). Close it and press "
                               "Save again.")
        clean_files.append(str(dst))
        report.append(f"\n{src.name}\n" + "-" * len(src.name))
        for m in (m for m in st["mutes"] if m["part"] == pi):
            via = {"audio": "", "ai": "   (found by AI)"}.get(m["src"], "   (caught by ebook check)")
            report.append(f"  {fmt_t(m['s'])}  muted  {m['word']}{via}")
        for c in (c for c in cuts if c["part"] == pi):
            total_cut_sec += c["e"] - c["s"]
            label = {"sex": "explicit scene", "gore": "gory description",
                     "ref": "sexual reference", "religion": "religious content",
                     "relationship": "relationship content",
                     "crude": "crude humor", "bully": "bullying",
                     "flirt": "flirting"}.get(c.get("kind"), "scene")
            report.append(f"  {fmt_t(c['s'])}  CUT {c['e'] - c['s']:.0f} seconds  "
                          f"{c.get('note') or label}")
    chap = None
    if chapters:
        say(0.95, "Splitting into chapters…")
        tr = json.loads((work / "transcript.json").read_text())
        asr = [{**w, "part": pi, "n": norm(w["t"])} for pi, p in enumerate(st["parts"]) for w in tr[p]]
        cuts_by_part = {}
        for c in cuts:
            cuts_by_part.setdefault(c["part"], []).append((c["s"], c["e"]))
        clean_durs = [probe_duration(f) for f in clean_files]
        tracks = plan_tracks(asr, clean_durs, cuts_by_part)
        first = Path(st["parts"][0])
        if len({str(Path(p).parent) for p in st["parts"]}) > 1:
            title = first.parent.parent.name  # the book folder that holds Disc 1, Disc 2...
        else:
            title = re.sub(r"[\s_-]*(part|pt|disc|cd)?[\s_-]*\d+$", "", first.stem,
                           flags=re.I) or first.parent.name or first.stem
        chap = split_tracks(clean_files, clean_durs, tracks, out, title, log)
        report.append("\nChapter files\n-------------")
        report.extend(f"  {i:02d}  {t}" for i, t in enumerate(chap["titles"], 1))
    head = ["CleanListen report", "==================",
            f"{len(st['mutes'])} words/phrases muted, {len(cuts)} passages cut "
            f"({total_cut_sec / 60:.1f} minutes removed)."]
    if st.get("ebook_note"):
        head.append(st["ebook_note"])
    (out / "CleanListen report.txt").write_text("\n".join(head + report) + "\n", encoding="utf8")
    say(1.0, "Saved.")
    log(f"Saved to {out}")
    return {"mutes": len(st["mutes"]), "cuts": len(cuts), "cut_minutes": total_cut_sec / 60,
            "out": str(out), "chapters": chap}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyze")
    an.add_argument("workdir")
    an.add_argument("audio", nargs="+")
    an.add_argument("--ebook")
    an.add_argument("--groups", default="swearing,mild,deity")
    an.add_argument("--no-sex", action="store_true")
    rn = sub.add_parser("render")
    rn.add_argument("workdir")
    rn.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "analyze":
        st = analyze(a.audio, a.workdir, a.ebook, a.groups.split(","), not a.no_sex,
                     progress=lambda f, m: print(f"[{f * 100:3.0f}%] {m}", flush=True))
        print(f"{st['words']} words; {len(st['mutes'])} to mute; {len(st['scenes'])} scenes flagged")
    else:
        print(render(a.workdir, a.out or str(Path(a.workdir) / "clean")))


if __name__ == "__main__":
    _cli()
