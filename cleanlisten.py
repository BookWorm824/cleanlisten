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
import threading
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
# (most additions after 1.7.3 come from CleanView's lists, which were checked against TV and
# film dialogue; guards for everyday uses are in INNOCENT_NEXT / INNOCENT_PREV below)
STRONG = [r".*fuck.*", r"cunts?", r"motherf.*", r"fk", r"effing", r"effin", r"f'?ing",
          r"mofos?", r"wtf", r"stfu", r"omfg",
          # racial slurs (the unmistakable ones; "cracker", "coon", "chink" etc. have
          # everyday meanings too, so they're left to the AI and Claude)
          r"nigg(a|as|ah|az|er|ers)", r"kikes?", r"wetbacks?", r"gooks?", r"towelheads?",
          r"ragheads?", r"beaners?"]
MODERATE = [
    r".*shit.*", r"bitch.*", r"son(of|ofa|uva|na)?bitch.*", r"sumbitch.*", r"ass", r"asses",
    r"ass(holes?|wipes?|hats?|clowns?|face|faces|heads?|kick(s|ed|er|ers|ing)?|"
    r"kiss(er|ers|ing)?)", r"arse",
    r"arsehole.*", r"jackass.*", r"dumbass.*", r"badass.*", r"smartass.*",
    # "sweet-ass deal", "kick-ass": the hyphen is dropped, so list the joined forms
    r"(sweet|kick|big|fat|lazy|hard|half|wise|candy|cheap|kiss|tight|crazy|stupid|sorry|"
    r"lame|weird|broke|punk|wuss|bad|dumb|smart|jack|whole|cold|hot|mean|tough|fine|"
    r"nice|cool|pretty|ugly|old|cute|great|bitch)ass(es|ed)?",
    r"bastard.*", r"piss.*", r"dicks?", r"dickhead.*", r"pricks?", r"bollocks",
    r"bugger.*", r"wanker.*", r"wank(s|ed|ing|in)?", r"(jerk|jack)offs?", r"twats?", r"sluts?", r"slutty", r"whores?",
    r"skanks?", r"douche.*", r"tits", r"titties", r"cocksucker.*", r"cojones", r"ca[jh]ones", r"nads",
    r"(ball|nut)sacks?", r"ballsy", r"balls?bust(er|ers|ing)", r"dbags?",
    # more crude slang heard in TV and films
    r"a-?holes?", r"lardass(es)?", r"bia?y?o?tch(es)?", r"beyotch", r"shat",
    r"dick(wad|weed|face|ish|wit|bag|less)s?", r"numbnuts", r"knobheads?", r"tossers?",
    r"bellends?", r"feck(ing|in|er|ers)?", r"retard(s|ed|os?)?", r"retart(s|ed)?", r"(lib)?tards?",
    r"skeez(e|y|ier)", r"skeevy", r"arsed", r"arses",
    r"merde", r"scheisse", r"mierda",        # French, German and Spanish for "shit"
]
# swearing said as letters or two words ("S.O.B.", "D-bag" heard as "d bag", "eff you")
MODERATE_PHRASES = [("s", "o", "b"), ("d", "bag"), ("d", "bags"), ("dee", "bag"),
                    ("ball", "buster"), ("ball", "busters"), ("ball", "busting"),
                    ("balls", "buster")] + [("eff", o) for o in ("you", "off", "me", "him", "her",
                                                                  "them", "it", "that", "this")]
MODERATE_PHRASES += [("what", "the", "f"), ("what", "the", "eff")]
# "retarded" heard as two words by speech recognition
MODERATE_PHRASES += [("re", t) for t in ("tard", "tards", "tarded")]
# "yanking your chain" (teasing, with a crude double meaning): the whole phrase goes
MODERATE_PHRASES += [(y, o, c) for y in ("yank", "yanks", "yanked", "yanking", "yankin", "pull",
                                          "pulls", "pulled", "pulling", "pullin", "jerk", "jerks",
                                          "jerked", "jerking", "jerkin")
                     for o in ("my", "your", "his", "her", "their", "our", "ya", "yer", "someone's",
                               "somebody's", "everyone's", "everybody's", "people's")
                     for c in ("chain", "chains")]
# "what the fudge", "what the flip": stand-ins for the f-word (muted with the soft swears).
# And the same for God's name, Jesus and son of a bitch: "good grief", "for Pete's sake",
# "holy cow" (Lauren, 2026-10-29: "Holy cow and Holy molly are not fine"). Same as CleanView's
# cvcore.MINCED_SLANG.
MINCED_PHRASES = [("what", "the", w) for w in ("fudge", "flip", "fork", "frack", "fuh", "devil",
                                                 "dickens", "deuce", "blazes")]
MINCED_PHRASES += [(o, w) for o in ("oh", "aw", "ah", "ahh", "aww") for w in ("fudge", "shoot", "sugar")]
MINCED_PHRASES += [("gee", w) for w in ("whiz", "whizz", "willikers", "whillikers", "wilikers")]
MINCED_PHRASES += [("jeepers", "creepers"), ("goodness", "gracious"), ("my", "goodness"),
                   ("oh", "my", "goodness"), ("oh", "heavens"), ("for", "crying", "out", "loud")]
MINCED_PHRASES += [(w, "squat") for w in ("diddly", "diddley", "diddlee", "doodly", "jack")]
MINCED_PHRASES += [("son", "of", "a", w) for w in ("gun", "biscuit", "b")]
MINCED_PHRASES += [("good", w) for w in ("grief", "golly", "gravy", "heaven", "heavens", "gracious")]
MINCED_PHRASES += [("thank", w) for w in ("goodness", "heaven", "heavens")]
MINCED_PHRASES += [(*o, "heavens", "to", w) for o in ((), ("oh",)) for w in ("betsy", "murgatroyd")]
MINCED_PHRASES += [("in", w, "name") for w in ("heaven's", "heavens")]   # "what in heaven's name"
MINCED_PHRASES += [("for", w, s_) for w in ("goodness", "goodness's", "heaven's", "heavens", "pete's",
                                            "petes", "pete", "cripes", "mercy's", "land's", "lands")
                   for s_ in ("sake", "sakes")]
MINCED_PHRASES += [("holy", w) for w in ("cow", "cows", "moly", "molly", "moley", "mackerel", "smokes",
                                         "smoke", "toledo", "guacamole", "cannoli", "schmoley", "moses",
                                         "crud", "heck", "jeez", "geez", "cats", "socks", "jumping",
                                         "shamoley")]
# ("damning" = incriminating and "damnation" are left alone)
MILD = [r"damn", r"damned", r"damnit", r"damns", r"dammit", r"goddamn.*", r"goddam", r"godd?amm?it",
        r"hell", r"hellhole", r"crap", r"crappy", r"craps", r"craphole", r"bullcrap", r"crapper",
        r"sod", r"sodding", r"bloody", r"turds?", r"hella", r"hussy", r"hussies",
        r"crap(pier|piest|ped|ping|pers|holes|loads?|tastic|ola)", r"day+um+n?",   # "dayum"
        r"floozy", r"floozies", r"trollops?", r"strumpets?", r"verdammt"]
MINCED = [r"frigg?in[g']?", r"freakin[g']?", r"frickin[g']?", r"frick(ed|s)?", r"jeeze?", r"geeze?",
          r"gosh", r"gosh(darn|dang).*", r"darn.*", r"heck", r"dang", r"dang(it|ed)",
          r"dagnabb?it", r"frak(s|ked|king|kin)?", r"sheesh",
          # stand-ins for God, Jesus, Christ, damn and shit
          r"golly", r"jeepers", r"jee+sh", r"crikey", r"blimey", r"gorblimey", r"cripes",
          r"crim[ie]ny", r"egads?", r"gadzooks", r"zounds", r"lawdy", r"lawd", r"doggone(d|it)?",
          r"dadgum(med|mit|it)?", r"dadburn(ed|it)?", r"consarn(ed|it)?", r"tarnation",
          r"d[eu]rn(ed|it)?", r"crud", r"cruddy", r"shiz", r"shiznit", r"gee",
          r"diddl[ey]+squat", r"jacksquat"]
DEITY_PHRASES = [
    ("oh", "my", "god"), ("my", "god"), ("oh", "god"), ("good", "god"),
    ("dear", "god"), ("god", "almighty"), ("for", "god's", "sake"),
    ("for", "gods", "sake"), ("god", "knows"), ("god", "damn"),
    ("god", "dammit"), ("oh", "lord"), ("good", "lord"), ("dear", "lord"),
    ("lord", "almighty"), ("sweet", "jesus"), ("jesus", "christ"),
    ("for", "christ's", "sake"), ("for", "christs", "sake"), ("jesus", "h", "christ"),
    ("for", "god's", "sakes"), ("for", "gods", "sakes"), ("for", "christ's", "sakes"),
    ("for", "christs", "sakes"),
    ("christ", "almighty"), ("mother", "of", "god"), ("holy", "mother", "of", "god"),
    ("good", "god", "almighty"), ("oh", "my", "lord"), ("lord", "have", "mercy"),
    ("lord", "knows"), ("god", "help", "us"), ("god", "help", "me"), ("lord", "help", "us"),
    ("lord", "help", "me"), ("god", "forbid"), ("swear", "to", "god"), ("in", "god's", "name"),
    ("in", "gods", "name"), ("for", "the", "love", "of", "god"), ("christ", "on", "a", "bike"),
    ("god", "in", "heaven"), ("so", "help", "me", "god"), ("holy", "lord"),
    ("for", "the", "love", "of", "christ"), ("oh", "hallelujah"),    # not "the choir sang hallelujah"
    # from CleanView's reports (Aladdin, The Blind Side, 2026-10-30; CleanView 1.18.4)
    ("by", "allah"), ("allah", "forbid"), ("praise", "allah"), ("oh", "allah"),
    *((g, "help", w) for g in ("god", "lord") for w in ("him", "her", "them", "you", "that", "this",
                                                         "the")),
    # (not "thank the Lord": like "thank God", that's left to the strict religion filter)
]
DEITY_WORDS = [r"jesus", r"christ", r"lordy", r"omg", r"oh?m[iy]god", r"goddamn.*"]
# "Jesus" and "Christ" said with reverence aren't swearing ("the love of Christ", "to know Jesus",
# "Jesus told us"; Jason, 2026-10-30: 34 in one Christian novel were muted as swears, and someone
# who only wants the cursing out shouldn't lose them). An oath is said on its own ("Jesus!",
# "Christ, that hurt"); the name after one of these words, or before one of these verbs, is
# talk about Him. (The religion filter still decides about faith talk.)
REVERENT_BEFORE = {
    "of", "in", "to", "for", "about", "with", "through", "from", "by", "into", "unto", "toward",
    "towards", "upon", "than", "like", "as", "before", "the", "my", "our", "his", "her", "their",
    "lord", "jesus", "and", "please", "know", "knew", "knows", "known", "knowing", "accept",
    "accepted", "accepts", "need", "needs", "needed", "serve", "served", "serves", "serving",
    "follow", "followed", "follows", "following", "love", "loved", "loves", "loving", "praise",
    "praised", "praising", "trust", "trusted", "trusts", "believe", "believed", "believes",
    "found", "find", "finds", "meet", "met", "share", "shared", "sharing", "preach", "preached",
    "preaching", "proclaim", "proclaimed", "bring", "brought", "tell", "told", "teach", "taught",
    "worship", "worshipped", "worshiped", "glorify", "embraced", "embrace", "risen", "crucified"}
REVERENT_NEXT = {
    "told", "tells", "said", "says", "taught", "teaches", "loves", "loved", "died", "dies", "rose",
    "sent", "sends", "heard", "hears", "healed", "heals", "saves", "saved", "wept", "promised",
    "promises", "forgave", "forgives", "answered", "answers", "himself", "alone", "came", "comes",
    "lives", "lived", "calls", "called"}
REVERENT_IS = {"risen", "lord", "king", "god", "alive", "coming", "here", "with", "the", "my",
               "our", "love", "real", "born", "in"}   # "Christ is risen", not "Jesus, is that you?"


def reverent(words, i, j=None):
    """True if the name at words[i:j] ("jesus", "christ", "jesus christ") is talk about Him,
    not an oath."""
    j = j or i + 1
    prev, two = (words[i - 1] if i else ""), (words[i - 2] if i > 1 else "")
    nxt = words[j] if j < len(words) else ""
    if prev in ("my", "sweet", "dear") and two == "oh":
        return False                   # "oh my Jesus"
    if nxt in ("is", "was"):
        return (words[j + 1] if j + 1 < len(words) else "") in REVERENT_IS
    return prev in REVERENT_BEFORE or nxt in REVERENT_NEXT or (two, prev) == ("thank", "you")
# Sexual words muted one at a time, wherever they come up (separate from
# cutting whole explicit scenes). Words with innocent everyday meanings
# (bed, naked, breast, screw) are deliberately left out.
SEXUAL_WORDS = [
    r"sex", r"sexes", r"sexy", r"sexier", r"sexiest", r"sexual", r"sexually", r"sexuality",
    r"sexed", r"sexting", r"horny", r"orgasm.*", r"erections?", r"arous(ed|al)",
    r"condoms?", r"boobs?", r"boobies", r"penis(es)?", r"vaginas?", r"genital.*",
    r"nipples?", r"porn.*", r"foreplay", r"intercourse", r"masturbat.*", r"climaxed",
    r"hookers?", r"blowjobs?", r"threesomes?", r"lingerie", r"panties",
    # crude words for body parts and sex (from CleanView's TV and film list)
    r"pussy", r"pussies", r"boners?", r"knockers", r"titty", r"peckers?", r"peen", r"jizz",
    r"cum", r"boink(s|ed|ing)?", r"nookie", r"milfs?", r"dilfs?", r"hoochies?",
    r"cockblock(s|ed|er|ing)?", r"schlongs?", r"todgers?", r"dildos?",
]
SEXUAL_PHRASES = [
    ("make", "love"), ("making", "love"), ("made", "love"), ("makes", "love"),
    ("get", "laid"), ("got", "laid"), ("getting", "laid"),
    ("one", "night", "stand"), ("one", "night", "stands"), ("hook", "up", "with"),
    ("hooked", "up", "with"), ("hooking", "up", "with"),
    # slang for touching yourself ("beat off", "whack off", "yank it" are left out: everyday too)
    ("rub", "one", "out"), ("rubbing", "one", "out"), ("rubbed", "one", "out"),
    ("spank", "the", "monkey"), ("spanking", "the", "monkey"),
    ("choke", "the", "chicken"), ("choking", "the", "chicken"),
] + [(v, "off") for v in ("jerk", "jerks", "jerked", "jerking", "jerkin", "jack", "jacks", "jacked",
                          "jacking", "jackin")] + [(v, "with", o) for v in ("sleep", "sleeps", "slept", "sleeping")
     for o in ("him", "her", "me", "you", "them", "someone", "somebody", "anyone",
               "anybody", "each", "everyone", "everybody")]
# "screw you" / "screw it" as an insult (muted with the mild words). "Screw" on its
# own is left alone, and so is "screw it in / on / tight..." (hardware).
SCREW_PHRASES = [("screw", o) for o in ("you", "him", "her", "them", "it", "this", "that", "off",
                                        "yourself", "em", "'em", "everyone", "everybody", "y'all")]
# "up yours", and "we're screwed" (in trouble), not "screwed to the wall" or "screwed up"
SCREW_PHRASES += [("up", "yours")] + [(*w.split(), "screwed") for w in (
    "i'm", "we're", "you're", "he's", "she's", "they're", "it's", "we are", "i am", "you are",
    "totally", "completely", "royally", "so", "really", "just",
    "get", "gets", "got", "getting", "gotten",
    "be", "been", "is", "are", "was", "were")]        # "we would be screwed" (CleanView 1.18.5)
SCREWED_SAFE_NEXT = {"in", "into", "on", "onto", "down", "together", "shut", "tight", "tightly", "to",
                     "the", "it", "that", "this", "back", "off", "up"}
# "jerked off the road", "jacked off his feet": a place or thing follows, so it's literal
OFF_SAFE_NEXT = {"the", "a", "an", "his", "her", "its", "their", "my", "your", "our", "of", "to",
                 "into", "onto", "from", "at", "toward", "towards", "course", "balance", "guard",
                 "track", "road", "path", "ground", "floor", "table", "shelf", "wall", "hook"}
SCREW_SAFE_NEXT = {"in", "into", "on", "onto", "to", "back", "down", "tight", "tightly", "shut",
                   "together", "up", "through", "firmly", "securely", "loose", "around", "the",
                   "a", "an", "lid", "cap", "bolt", "hinge", "panel", "plate", "bracket"}
# Slang for a man's private parts. These are everyday words too ("skipping stones", "tennis
# balls", "a pair of shoes"), so only the slang word in these phrases is muted (as swearing):
# grow some stones / grow a pair, has the balls to, kicked him in the nuts, busting my balls,
# freeze my nuts off, cut his balls off, brass balls.
BODY_SLANG = {"stones", "balls", "nuts", "pair", "set", "jewels"}
GROW = {"grow", "grows", "grew", "grown", "growing"}
SELF = {"yourself", "himself", "herself", "themselves", "you", "me"}
HAVE = {"has", "have", "had", "got", "gotten", "having", "lack", "lacks", "lacked", "lacking"}
STRIKE = {"kick", "kicks", "kicked", "kicking", "knee", "kneed", "kneeing", "punch", "punched",
          "punching", "hit", "hits", "hitting", "smack", "smacked", "whack", "whacked", "kick'em"}
POSS = {"my", "his", "your", "their", "our", "her"}
GOT_WHO = {"you've", "you", "he's", "he", "she's", "she", "they've", "they", "i've"}
# "I've got some nuts in my bag", "you got some stones for the garden": the real thing
NOT_SLANG_NEXT = {"in", "on", "for", "from", "at", "to", "left", "that", "the", "a", "here",
                  "there", "and", "of", "with", "out", "into", "inside"}
BUST = {"bust", "busts", "busting", "busted", "break", "breaks", "breaking", "broke"}
OFF_VERBS = {"freeze", "freezes", "freezing", "froze", "frozen", "work", "works", "working", "worked",
             "cut", "cuts", "cutting", "chop", "chops", "chopped", "rip", "rips", "ripped", "tear",
             "tore", "torn", "bite", "bit", "bitten", "shoot", "shot", "blow", "blew", "blown"}


def body_slang(words, i):
    """Is words[i] (stones, balls, nuts, pair, set, "family jewels") slang for a man's private
    parts here?"""
    w = words[i]
    if w not in BODY_SLANG:
        return False
    if w == "jewels":       # "kicked him in the family jewels": read it as one word
        if i < 1 or words[i - 1] != "family":
            return False
        words, i, w = words[:i - 1] + ["balls"] + words[i + 1:], i - 1, "balls"
    at = lambda k: words[k] if 0 <= k < len(words) else ""
    p1, p2, n1 = at(i - 1), at(i - 2), at(i + 1)
    if p2 in SELF and at(i - 3) in GROW:      # "grow yourself some stones"
        p2 = "grow"
    if p1 in ("real", "big") and p2 == "some" and at(i - 3) in GROW | HAVE:
        return True                            # "you've got some real stones"
    if (p1 in ("some", "real", "big") and p2 == "got" and at(i - 3) in GOT_WHO and
            w in ("stones", "balls", "nuts") and n1 not in NOT_SLANG_NEXT):
        return True                            # "you've got some balls", "she's got real stones"
    if p1 == "of" and p2 in ("pair", "set") and at(i - 3) == "a" and at(i - 4) in GROW:
        return True                            # "grow a pair of balls"
    if any(at(k) in ("kidney", "kidneys", "gall", "gallbladder", "bladder") for k in range(i - 2, i + 5)):
        return False   # kidney stones
    if w in ("pair", "set"):   # "grow a pair", "grow a set" (not "a pair of ...")
        return p1 == "a" and p2 in GROW and n1 != "of"
    if p1 == "some" and p2 in GROW:
        return True
    if p1 == "the" and p2 in HAVE and n1 == "to":
        return True
    if p1 == "the" and p2 == "in" and any(at(k) in STRIKE for k in range(i - 6, i - 2)):
        return True
    if p1 in POSS and (p2 in BUST or (p2 in OFF_VERBS and n1 == "off")):
        return True
    return w == "balls" and (p1 in ("brass", "blue") or (n1, at(i + 2)) == ("of", "steel"))


# Fruit and vegetables for body parts ("check out those melons", "pop her cherry", "kneed him in
# the grapes"). Only these phrases count, never "a melon" or "cherry pie"; as with "stones", only
# the slang word is muted (as swearing). Same phrases as CleanView's cvcore.BODY_SLANG, which
# mutes the whole phrase.
_CHEST = (r"(melons|cantaloupes|watermelons|grapefruits|coconuts|honeydews|"
          r"jugs|hooters|knockers|bazongas|bazooms|bazoombas)")
_BIG = r"((big|huge|giant|great|massive|enormous|perky|nice|lovely) )?"
_LOW = (r"(grapes|plums|berries|beans|walnuts|franks and beans|frank and beans|meat and two veg|"
        r"crown jewels|package|junk(?! (pile|piles|yard|yards|drawer|heap|food|mail|room|shop|"
        r"car|box|bin)\b))")
_NOT_FRUIT = (r"(?! (pie|pies|tree|trees|tomato|tomatoes|blossom|blossoms|cola|coke|juice|jam|"
              r"stem|stems|pit|pits|lipstick|chapstick|red|wood|bomb|bombs|on top)\b)")
FRUIT_SLANG = [re.compile(r"(?<!\S)" + p) for p in (
    r"(nice|big|huge|giant|great|massive|enormous|perky|lovely) (pair|set) of (?P<part>" + _CHEST + r")\b",
    r"(check|checks|checking|checked|checkin) out (those|them|her|your) " + _BIG +
    r"(?P<part>" + _CHEST + r")\b",                        # not "these melons": a market seller
    r"(stare|stares|staring|stared|ogle|ogles|ogling|ogled|gawk|gawking|gawked|look|looks|"
    r"looking|looked|lookin) at (her|them) " + _BIG + r"(?P<part>" + _CHEST + r")\b",
    r"(her|your) (big|huge|giant|massive|enormous|perky|nice|lovely) (?P<part>" + _CHEST + r")\b",
    r"(pop|pops|popped|popping|poppin|bust|busts|busted|busting|lose|loses|lost|losing|take|"
    r"took|taking|taken|break|broke|broken) (her|his|my|your|their|our) (?P<part>cherry)\b" + _NOT_FRUIT,
    r"(?P<part>cherry) (popper|poppers|popping)\b",
    r"(kick|kicks|kicked|kicking|knee|kneed|kneeing|hit|hits|hitting|punch|punched|punches|"
    r"punching|smack|smacked|whack|whacked)( \S+){0,3} in the (?P<part>" + _LOW + r")\b",
    r"(zip|zips|zipped|zipping|caught|catch|catching|snag|snagged) (his|my|your) "
    r"(?P<part>(franks?|frank) and beans)\b",
    r"(is that|that's|that is|was that) an? (?P<part>banana|cucumber|zucchini|eggplant|carrot|pickle) "
    r"in (your|his|my) (pants|pocket|trousers|shorts|jeans|underwear)\b",
    r"(?P<part>banana|cucumber|zucchini|eggplant|pickle) in (your|his|my) "
    r"(pants|trousers|shorts|jeans|underwear)\b",
    r"(her|his|your) (tight|juicy|round|perfect) (?P<part>peach|buns)\b",
    r"(nice|great|big|huge|what a) (?P<part>rack)\b(?! of)",           # not "a rack of lamb"
    # not "the cock crowed", "cock the gun", "a cock and bull story"
    r"(my|his|your|big|little|hard|suck|sucks|sucking|sucked) (?P<part>cocks?)\b(?! (of the walk|a "
    r"doodle|doodle|doo|fight|fights|fighting|fighter|fighters|crow|crows|crowed|crowing|robin|"
    r"robins|sparrow|sparrows|and bull|eyed|pheasant|pheasants|tail|tails)\b)",
    r"(" + "|".join(sorted(OFF_VERBS)) + r") (my|his|your|her|our|their) (?P<part>grapes|plums) off\b",
)]
FRUIT_WORDS = {"melons", "cantaloupes", "watermelons", "grapefruits", "coconuts", "honeydews",
               "cherry", "grapes", "plums", "berries", "beans", "walnuts", "franks", "frank",
               "veg", "banana", "cucumber", "zucchini", "eggplant", "carrot", "pickle", "peach",
               "buns", "jugs", "hooters", "knockers", "bazongas", "bazooms", "bazoombas", "crown",
               "jewels", "package", "junk", "rack", "cock", "cocks"}


def fruit_slang(words):
    """Positions of fruit and vegetable words used for body parts ("those melons")."""
    text, starts, pos = " ".join(words), [], 0
    for w in words:
        starts.append(pos)
        pos += len(w) + 1
    out = set()
    for p in FRUIT_SLANG:
        for m in p.finditer(text):
            a, b = m.span("part")
            out |= {k for k, s in enumerate(starts)
                    if a <= s < b and words[k] in FRUIT_WORDS}   # "franks and beans": not "and"
    return out


# "That's bull", "what a load of bull", "cut the bull": short for bullshit, muted with the
# mild group. Only the word "bull", only after these words (or just before "crap"/"shit", as
# speech recognition splits "bullshit"), and not "that's bull riding" or "a bull market".
# Same as CleanView's cvcore.bull_swear.
BULL_BEFORE = re.compile(r"(^| )(that's|thats|that is|that was|this is|this was|it's|it is|"
                         r"it was|all|such|total|complete|utter|absolute|pure|load of|bunch of|"
                         r"pile of|full of|cut the|cut out the|enough of the|enough with the|"
                         r"no more|sounds like|sounded like)$")
BULL_SWEAR_NEXT = {"crap", "crapping", "shit", "shits", "shitting", "shitter"}
BULL_NOT_NEXT = {"riding", "rider", "riders", "ride", "rides", "market", "markets", "terrier",
                 "terriers", "shark", "sharks", "frog", "frogs", "elephant", "elephants", "seal",
                 "seals", "moose", "dog", "dogs", "run", "runs", "ring", "rings", "fight",
                 "fights", "fighter", "fighters", "fighting", "pen", "pens", "horn", "horns",
                 "whip", "whips", "dozer", "dozers", "session", "sessions", "calf", "calves",
                 "breed", "breeds", "semen", "snake", "snakes", "mastiff", "mastiffs", "nose",
                 "neck", "pup", "pups", "elk", "whale", "whales", "pit", "pits"}


def bull_swear(words, i):
    """Is words[i] "bull" said for bullshit ("that's bull")?"""
    if words[i] != "bull":
        return False
    nxt = words[i + 1] if i + 1 < len(words) else ""
    if nxt in BULL_SWEAR_NEXT:
        return True
    return nxt not in BULL_NOT_NEXT and bool(BULL_BEFORE.search(" ".join(words[max(0, i - 3):i])))


# "You don't know squat", "it doesn't mean squat": short for "jack shit", a soft swear. Only
# the word "squat", only straight after these words, and not "do squat jumps" or "squat down".
# Same as CleanView's cvcore.squat_swear.
SQUAT_BEFORE = {"know", "knows", "knew", "mean", "means", "meant", "do", "does", "did", "done",
                "doing", "worth", "care", "cares", "cared", "got", "get", "gets", "gotten",
                "have", "has", "had", "say", "says", "said", "see", "saw", "seen", "find",
                "found", "give", "gives", "gave", "pay", "pays", "paid", "about", "for",
                "learned", "learnt", "proves", "proved", "prove"}
SQUAT_NOT_NEXT = {"down", "jump", "jumps", "thrust", "thrusts", "rack", "racks", "position",
                  "toilet", "toilets", "lift", "lifts", "press", "exercise", "exercises", "low",
                  "lower", "deep", "deeper", "squat", "squats", "reps", "sets", "and", "with"}


def squat_swear(words, i):
    """Is words[i] "squat" said for "jack shit" ("you don't know squat")?"""
    if words[i] != "squat" or not i or words[i - 1] not in SQUAT_BEFORE:
        return False
    return (words[i + 1] if i + 1 < len(words) else "") not in SQUAT_NOT_NEXT


PHRASES = {"deity": None, "sexual": SEXUAL_PHRASES, "mild": SCREW_PHRASES,  # deity filled in below
           "moderate": MODERATE_PHRASES, "minced": MINCED_PHRASES}
# Words that are innocent next to these: "pussy cat", "Moby Dick", "summa cum laude",
# "General Hooker", "door knockers". (The word after, or before.)
INNOCENT_NEXT = {"pussy": {"cat", "cats", "willow", "willows", "footing", "foot"},
                 "dick": {"grayson", "tracy", "van", "whittington", "cheney", "clark", "york",
                          "turpin", "dastardly", "smith", "jones", "johnson", "and", "francis"},
                 "cum": {"laude"}, "peckers": {"up"}, "pecker": {"up"},
                 "retard": {"the", "its", "their", "growth"},
                 "horny": {"toad", "toads"}, "boob": {"tube", "tubes"},
                 # rude words box: "jerks her up", "fool around", "butt in", "dumb luck"
                 **{w: {"her", "him", "me", "them", "it", "us", "up", "away", "back", "open", "out",
                        "forward", "free", "awake", "his", "my", "your", "their", "our", "the"}
                    for w in ("jerk", "jerks")},
                 "fool": {"around", "with", "proof"}, "fools": {"gold", "around", "rush"},
                 "butt": {"in", "heads"}, "butts": {"in", "heads"},
                 "dumb": {"waiter", "waiters", "luck", "founded", "show"},
                 # "gee up" to a horse; the letter G ("a gee string", "gee major")
                 "gee": {"up", "string", "strings", "major", "minor", "sharp", "flat", "clef"},
                 "dumdum": {"bullet", "bullets"}, "dumdums": {"bullet", "bullets"}}
INNOCENT_PREV = {"dick": {"moby", "uncle", "big"}, "cum": {"summa", "magna"},
                 "hooker": {"general", "john", "joe"}, "hookers": {"general"},
                 "knockers": {"door"}, "fools": {"april"}, "fool": {"april"},
                 "butt": {"cigarette", "cigar", "rifle", "gun"},
                 "butts": {"cigarette", "cigar", "rifle", "gun"},
                 "dumb": {"deaf", "struck"}, "dummy": {"test", "ventriloquist", "ventriloquist's"},
                 "dummies": {"test", "crash"}, "brat": {"army", "navy", "military"},
                 "brats": {"army", "navy", "military"}, "twits": {"the"}}   # Roald Dahl's book
# Rude words kids copy (CleanListen's "Rude words" box, off unless ticked; the same list as
# CleanView's). "Shut it" is rude, "shut it down" isn't.
RUDE = [r"stupid(er|est)?", r"stupidity", r"dumb(er|est)?", r"dumbo", r"idiots?", r"idiotic",
        r"morons?", r"moronic", r"dumm(y|ies)", r"dorks?", r"dorky", r"dweebs?", r"jerks?",
        r"losers?", r"fools?", r"butts?", r"butthead(s)?", r"buttface", r"nincompoops?",
        r"nitwits?", r"dimwits?", r"halfwits?", r"numbskulls?", r"knucklehead(s)?",
        r"dummkopf", r"bonehead(s)?", r"airhead(s)?", r"doofus", r"dingbat(s)?", r"pea-?brain(s)?",
        r"poopyhead", r"weirdo(s)?",
        r"imbeciles?", r"cretins?", r"buffoons?", r"twits?", r"twerps?", r"pinheads?",
        r"meatheads?", r"lamebrains?", r"birdbrains?", r"dunces?", r"wimps?",   # not Wimpy
        r"wuss(es)?", r"wussy", r"sissy", r"sissies", r"crybab(y|ies)", r"scaredy(cats?)?",
        r"fatsos?", r"putz(es)?", r"schmucks?", r"ignoramus(es)?", r"brats?", r"dumbdumbs?",
        r"dumdums?", r"fatheads?",   # "dum-dum" is joined to "dumdum"
        r"sucky", r"suckage", r"sucktastic"]
RUDE_PHRASES = [("shut", "up"), ("shut", "your", "mouth"), ("shut", "your", "trap"),
                ("shut", "your", "face"), ("shut", "it"), ("you", "suck"), ("it", "sucks"),
                ("this", "sucks"), ("that", "sucks"), ("shut", "your", "pie", "hole"),
                ("shut", "your", "piehole"), ("shut", "your", "cake", "hole"),
                ("shut", "your", "cakehole"), ("shut", "your", "yap"),
                ("shut", "your", "big", "mouth"), ("shut", "your", "big", "fat", "mouth"),
                ("buzz", "off"), ("i", "hate", "you"), ("talk", "to", "the", "hand"),
                ("eat", "my", "shorts"), ("suck", "it"), ("sucks", "to", "be", "you"),
                ("you", "sucker"), ("you", "suckers")]
# (not "bug off": "get that bug off me")
NOT_RUDE_NEXT = {"down", "off", "in", "into", "on", "onto", "up", "out", "together", "tight",
                 "tightly", "shut", "back", "open", "closed", "loose", "tighter", "away"}
# "shut up shop", "shut up in the attic", "shut up the house": shut away, not rude
SHUT_UP_SAFE_NEXT = {"in", "inside", "shop", "house", "the", "his", "her", "my", "their", "our",
                     "with", "within", "together", "tight", "tightly", "alone", "for", "here",
                     "there", "like"}
PHRASES["rude"] = RUDE_PHRASES
# "Suck" meaning "is bad" ("life sucks", "he sucks at math", "that sucked"), with the rude words
# (Lauren, 2026-10-29). Not sucking something ("suck it up", "sucking his thumb", "the vacuum
# sucks up dirt"). ("Sucking" is left out: "the baby keeps sucking".) Same as CleanView's
# cvcore.suck_swear.
SUCK_WORDS = {"suck", "sucks", "sucked"}
SUCK_NOT_NEXT = {"up", "in", "on", "out", "into", "through", "from", "down", "off", "away", "back",
                 "the", "a", "an", "my", "his", "her", "your", "their", "its", "our", "all", "it",
                 "them", "him", "me", "us", "blood", "air", "juice", "water", "poison", "venom",
                 "thumb", "thumbs", "milk", "dry", "every", "some", "those", "these", "straws",
                 "straw", "candy", "lollipops", "lollipop", "face", "faces", "teeth", "breath",
                 "cock", "cocks", "dick"}
SUCK_NOT_BEFORE = {"vacuum", "vacuums", "straw", "straws", "pump", "pumps", "hose", "fan", "drain",
                   "leech", "leeches", "mosquito", "mosquitoes", "vampire", "vampires", "octopus",
                   "baby", "babies", "calf", "calves", "piglet", "piglets", "whirlpool",
                   "quicksand", "mud", "plant", "roots", "sponge", "lamprey", "lampreys"}


def suck_swear(words, i):
    """Is words[i] "suck(s/ed)" meaning "is bad" ("that sucks"), not sucking something?"""
    return (words[i] in SUCK_WORDS and not (i and words[i - 1] in SUCK_NOT_BEFORE) and
            (words[i + 1] if i + 1 < len(words) else "") not in SUCK_NOT_NEXT)


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
# Polite "a pleasure", and "sex" meaning men or women ("your sex", "the fair sex"), aren't
# sex talk. (The word before.) Same as CleanView's cvcore.NOT_SEX_BEFORE.
NOT_SEX_BEFORE = {
    "pleasure": {"a", "my", "the", "our", "great", "such", "real", "your", "true"},
    "sex": {"your", "our", "her", "his", "their", "fair", "fairer", "weaker", "gentle",
            "gentler", "opposite", "same", "other", "either", "each", "whose"},
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


# Ebooks (and some transcripts) bleep swears ("f***ing", "s**t", "a**hole", "#@$%"). Each is
# matched against these, most common first, so the word is still found; same length wins.
# (Ported from CleanView's cvcore.)
BLEEPED = ["fuck", "fucking", "fuckin", "fucked", "fucker", "fuckers", "fucks", "motherfucker",
           "motherfuckers", "motherfucking", "shit", "shits", "shitty", "shitting", "bullshit",
           "horseshit", "bitch", "bitches", "bitching", "ass", "asses", "asshole", "assholes",
           "jackass", "dumbass", "damn", "damned", "dammit", "goddamn", "goddammit", "hell", "crap",
           "dick", "dicks", "dickhead", "bastard", "bastards", "piss", "pissed", "cunt", "whore",
           "slut", "cock", "prick", "god", "jesus", "christ"]
_BLEEP = re.compile(r"[*#]|[@$%&!]{2,}|(?<=[a-z])-{2,}(?=[a-z])")


def unbleep(w):
    """'f***ing' -> 'fucking', 's**t' -> 'shit', '#@$%' -> 'fuck'; anything else as it was.
    A scene break ("***", "* * *") or "$$$" isn't a word, so it's left alone."""
    t = w.lower().strip(".,!?;:\"'()[]")
    if not _BLEEP.search(t):
        return w
    if not re.search(r"[a-z]", t) and len(set(t) & set("#@$%&")) < 2:
        return w
    parts = re.split(r"([*#@$%&!-]+)", t)
    for exact in (True, False):
        pat = "".join(re.escape(p) if not re.fullmatch(r"[*#@$%&!-]+", p) else
                      (f"[a-z]{{{len(p)}}}" if exact else "[a-z]+") for p in parts if p)
        found = [b for b in BLEEPED if re.fullmatch(pat, b)]
        if found:
            same = [b for b in found if len(b) == len(t)]
            return (same or found)[0]
    return w


# Short forms of swears on the lists. "sob" is also a real word (to cry, a sob story), so
# it only counts written as an abbreviation: capitals ("SOB") or dots ("S.O.B.").
ABBREVIATIONS = [(re.compile(r"[Ss]\.[Oo]\.[Bb]\.?('?s)?|SOB('?S|'?s)?|S-O-B"), "sonofabitch"),
                 (re.compile(r"[Dd][-.]?[Bb][Aa][Gg][Ss]?"), "douchebag"),
                 # "PO'd" (pissed off); not "Po'd" (Po would, Kung Fu Panda). CleanView 1.18.4
                 (re.compile(r"PO'e?d|[Pp]\.[Oo]\.'?e?d"), "pissed")]


def unabbreviate(w):
    """'S.O.B.' / 'SOB' -> 'sonofabitch', 'D-bag' -> 'douchebag'; else as it was."""
    core = w.strip(".,!?;:\"()[]").replace("’", "'")
    if core.endswith(".") and core.count(".") == 1:
        core = core[:-1]
    for pat, full in ABBREVIATIONS:
        if pat.fullmatch(core) or pat.fullmatch(core.rstrip(".")):
            return full
    return w


def norm(w):
    w = unbleep(unabbreviate(w)).lower().replace("’", "'").replace("‘", "'")
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
    r"polyamor.*", r"dykes?", r"fags?", r"faggots?", r"lesbos?", r"lez(z?ie|z?ies|bos?)",
]
EXTRA_CATS = {"orientation": _c(ORIENTATION_WORDS)}
GROUPS["orientation"] = ["orientation"]
# rude words: CleanListen's own box too, but not starred out like swears (so not in ALL_CATS,
# which CleanRead uses for that)
KID_CATS = {"rude": _c(RUDE)}
GROUPS["rude"] = ["rude"]
SEX_C = {w: _c(p) for w, p in SEX_TERMS.items()}


# "what the hell", "who the heck", "where in the hell": with lead_in=True the words leading up
# to a swear are muted too. Only for swearing (not "what the sex ed teacher said").
LEAD_WH = {"what", "who", "where", "how", "why", "whatd", "what'd", "whered", "where'd", "howd",
           "how'd", "whyd", "why'd"}
LEAD_CATS = {"strong", "moderate", "mild", "minced"}
LEAD_WORDS = LEAD_WH | {"in", "the"}


def lead_in(words, i):
    """How many words before words[i] are a lead-in like "what the" or "where in the" (0 if none)."""
    if i >= 2 and words[i - 1] == "the" and words[i - 2] in LEAD_WH:
        return 2
    if i >= 3 and words[i - 2:i] == ["in", "the"] and words[i - 3] in LEAD_WH:
        return 3
    return 0


def listed_word(text, cats):
    """True if the word or words (as written) are on the lists of the word groups ticked
    (cats), so an AI may mute them on its own (CleanView's listed_word: an AI muted "butts" with
    rude words off, and speech recognition mishears names). Anything else is only suggested."""
    ws = [norm(w) for w in str(text).split() if norm(w)]
    return bool(ws) and bool(find_language(ws, list(cats)))


def find_language(words, cats, lead_in_too=False):
    """Return (i, j, category) spans of words[i:j] to mute. With lead_in_too, a swear's
    lead-in ("what the" hell) is part of its span."""
    hits = _find_language(words, cats)
    if lead_in_too:
        for k, (i, j, cat) in enumerate(hits):
            back = lead_in(words, i) if cat in LEAD_CATS else 0
            if back and (k == 0 or hits[k - 1][1] <= i - back):
                hits[k] = (i - back, j, cat)
    return hits


def _find_language(words, cats):
    hits, n, i = [], len(words), 0
    fruit = fruit_slang(words) if "moderate" in cats else set()
    while i < n:
        found = None
        for cat in cats:
            for ph in sorted(PHRASES.get(cat) or [], key=len, reverse=True):
                if tuple(words[i:i + len(ph)]) == ph:
                    nxt = words[i + len(ph)] if i + len(ph) < n else ""
                    if ph[0] == "screw" and (words[i + 2] if i + 2 < n else "") in SCREW_SAFE_NEXT:
                        continue  # "screw it in tight", "screw that lid on"
                    if cat == "rude" and (ph[-1] == "it" and nxt in NOT_RUDE_NEXT or
                                          ph == ("shut", "up") and nxt in SHUT_UP_SAFE_NEXT or
                                          ph[-1] in SUCK_WORDS and nxt in SUCK_NOT_NEXT):
                        continue  # "shut it down", "shut up in the attic", "it sucks the juice out"
                    if ph[-1] == "off" and cat == "sexual" and nxt in OFF_SAFE_NEXT:
                        continue  # "the car jerked off the road"
                    if ph[-1] == "screwed" and nxt in SCREWED_SAFE_NEXT:
                        continue  # "it's screwed to the wall", "we're screwed up"
                    if ph == ("jesus", "christ") and reverent(words, i, i + 2):
                        continue  # "the gospel of Jesus Christ"
                    found = (ph, cat)
                    break
            if found:
                break
        if found:
            hits.append((i, i + len(found[0]), found[1]))
            i += len(found[0])
            continue
        if ("mild" in cats or "moderate" in cats) and bull_swear(words, i):   # "that's bull"
            hits.append((i, i + 1, "mild" if "mild" in cats else "moderate"))
            i += 1
            continue
        if "minced" in cats and squat_swear(words, i):                   # "you don't know squat"
            hits.append((i, i + 1, "minced"))
            i += 1
            continue
        if "rude" in cats and suck_swear(words, i):                       # "life sucks"
            hits.append((i, i + 1, "rude"))
            i += 1
            continue
        w = words[i]
        for cat in cats:
            pats = CATS.get(cat) or EXTRA_CATS.get(cat) or KID_CATS.get(cat) or []
            if any(p.match(w) for p in pats):
                if w == "bloody" and (words[i + 1] if i + 1 < n else "") not in BLOODY_SWEAR_NEXT:
                    break
                if ((words[i + 1] if i + 1 < n else "") in INNOCENT_NEXT.get(w, ()) or
                        (words[i - 1] if i else "") in INNOCENT_PREV.get(w, ()) or
                        w == "dumb" and words[max(0, i - 2):i] == ["deaf", "and"] or
                        w in ("jesus", "christ") and reverent(words, i)):
                    break     # "pussy cat", "Moby Dick", "summa cum laude", "the love of Christ"
                hits.append((i, i + 1, cat))
                break
        else:
            if "moderate" in cats and (body_slang(words, i) or i in fruit):
                hits.append((i, i + 1, "moderate"))
        i += 1
    return hits


def sex_score(words):
    """Score a stretch of text. Only stretches with at least two explicit
    words count at all: kissing, beds and sheets alone never flag a scene
    (romance without explicit content is left alone)."""
    s, explicit = 0, 0
    for k, w in enumerate(words):
        if k and words[k - 1] in NOT_SEX_BEFORE.get(w, ()):
            continue                    # "it's a pleasure", "the fair sex" (Pride and Prejudice)
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
        r"messiah", r"godless", r"heathens?", r"blasphem.*", r"hymns?", r"congregation",
        # other faiths and Catholic teaching
        r"catholics?", r"catholicism", r"protestants?", r"mormons?", r"popes?", r"papal", r"vatican",
        r"nuns?", r"monks?", r"monaster(y|ies)", r"convents?", r"rosar(y|ies)", r"purgatory",
        r"sacraments?", r"communion", r"eucharist", r"catechism", r"baptism", r"baptiz.*",
        r"baptis(e|ed|es|ing)", r"transubstantiation", r"immaculate", r"novenas?",
        r"buddhas?", r"buddha's", r"nirvana", r"dharma", r"sutras?", r"mosques?", r"quran", r"koran",
        r"imams?", r"ramadan", r"hajj", r"rabbis?", r"synagogues?", r"torah", r"talmud", r"judaism",
        r"sikh.*", r"jains?", r"jainism", r"shinto.*", r"taoism", r"taoist", r"confucian.*",
        r"pagans?", r"paganism", r"wicca.*", r"scientolog.*", r"krishna", r"vishnu", r"shiva",
        r"brahma", r"ganesh(a)?"],
    1: [r"god", r"gods", r"god's", r"lord", r"jesus", r"christ", r"believe", r"believed",
        r"believes", r"beliefs?", r"miracles?", r"forgive(n|ness)?", r"mercy", r"fate",
        r"destiny", r"universe", r"hell", r"spirit", r"evil", r"punish(ed|ment)?",
        r"saints?", r"sacred", r"temples?", r"trinity", r"prophets?", r"mecca", r"jews?", r"jewish",
        r"meditat.*", r"enlightenment", r"zen", r"gurus?", r"lama", r"confess(ion|ions|ed)?",
        r"limbo", r"chakras?"],
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
    r"losers?", r"freaks?", r"idiots?", r"morons?", r"stupid", r"dummy", r"dumb",
    r"retard(ed|s|os?)?", r"(lib)?tards?",
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


# Disrespect: a child talking back to or disobeying a parent ("you can't tell me what to do",
# "you're not my real mom"). Only lines that are hard to mistake; the AI helper and Claude catch
# the rest (sassing, sneaking out, lying to them). Not "whatever" or "make me": too common.
# The same list as CleanView's LINE_WORDS["disrespect"] (Lauren, 2026-10-30).
DISRESPECT = re.compile(
    r"\b(you can'?t tell me what to do|you'?re not the boss of me|"
    r"you'?re not my (real )?(mom|mum|dad|mother|father|boss)|"
    r"i don'?t have to (listen to|obey|do what) you|you can'?t make me|"
    r"i hate you,? (mom|mum|mommy|mummy|dad|daddy|mother|father)|"
    r"i don'?t care what you (say|think|want))\b")


def disrespect_hit(words):
    return bool(DISRESPECT.search(" ".join(words)))


# Holidays, candles on a birthday cake, magic, dark magic, and vampires and werewolves (for
# young kids; all off unless ticked). Only phrases that are hard to mistake; the AI helper and Claude catch the rest.
# The same lists as CleanView's LINE_WORDS, matched on the normalised words (so "x-mas" is
# "xmas" and "jack-o'-lantern" is "jacko'lantern"). Thanksgiving is fine (Lauren).
TOPIC_WORDS = {
    # Christmas, Halloween, Valentine's Day, Easter and St. Patrick's Day: one tick box
    # (not "elves", "stockings" or "make a wish": too often something else; not "Rudolph" on its
    # own: a name in one of Lauren's books)
    "holiday": re.compile(
        r"\b(christmas|xmas|santa( claus)?|saint nick|north pole|reindeer|rudolph the|"
        r"rudolph's (red )?nose|mistletoe|"
        r"yuletide|jingle bells|"
        r"hallowe'?en|trick ?or ?treat\w*|jack ?o'?lanterns?|all hallows|"
        r"valentines?|valentine's|cupid|"
        r"easter\b(?! island)|egg hunts?|"
        r"(st|saint) (patrick|paddy|patty)'?s( day)?\b(?! (cathedral|church|school|hospital))|"
        r"leprechauns?|pot of gold)\b"),
    # only the candles: "happy birthday", birthday parties and cake are fine (Lauren)
    "birthday": re.compile(
        r"\b((blow(s|ing|n)?|blew) out (the|your|my|his|her|their|all the|all your) candles|"
        r"birthday candles?|candles on (the|your|my|his|her|a|that) (birthday )?cake)\b"),
    # not "witch" (an insult too), "curse" (swearing), "spirits" (drinks, cheer), "psychic" or
    # "crystal ball" ("what am I, psychic?")
    "darkmagic": re.compile(
        r"\b(witchcraft|black magic|dark magic|dark arts|sorcer(y|er|ers|ess|esses)|necromanc\w*|"
        r"voodoo|hoodoo|warlocks?|ouija|s[eé]?ances?|hex(es|ed)? (on|you|him|her|them)|"
        r"put a curse|cast a curse|occult|satanic|satanists?|devil worship\w*|pentagrams?|"
        r"fortune ?tell(er|ers|ing)|tarot|"
        r"summon(s|ed|ing)? (a |the )?(demons?|spirits?|the dead|dead)|"
        # wizards are dark magic (Lauren, 2026-10-29); not "a wizard with numbers"
        r"wizards?(?! (with|at|of))|wizardry)\b"),
    # not "magic" alone ("it was magic", "the magic word") or "spell" (spelling)
    "magic": re.compile(
        r"\b(magic (spells?|wands?|potions?|powers?|carpets?|lamps?|beans|mirrors?|rings?|kingdom|"
        r"book|dust)|magical powers?|cast(s|ing)? a spell|put a spell|under (a|the|her|his) spell|"
        r"spell (on|to make)|spells?book|enchant(ed|ment|ments|ress)|abracadabra|hocus ?pocus|bibbidi|potions?|"
        r"fairy godmother|gummiberry juice)\b"),
    # not "vampire bats" or "vampire squid" (real animals), or "vamp" (a dance, a flirt)
    "vampires": re.compile(
        r"\b(vampires?(?! (bats?|squids?|finch|finches|weekend|facials?|energy|power|devices?))|"
        r"vampiric|vampirism|dracula|nosferatu|the undead|werewol(f|ves|f's)|lycanthrop\w*|"
        r"wolf ?m[ae]n)\b"),
}


def topic_hit(kind, words):
    """One sentence: does it mention this holiday or magic topic (TOPIC_WORDS)?"""
    return bool(TOPIC_WORDS[kind].search(" ".join(words)))


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


# Providence in place of God ("Providence only knows", "trust in Providence", "thank
# Providence"), but not the city ("we drove to Providence", "Providence, Rhode Island").
PLACE_BEFORE = {"in", "to", "from", "near", "at", "outside", "around", "into", "toward", "towards",
                "via", "downtown", "visit", "visited", "visiting"}
PLACE_AFTER = {"rhode", "ri", "college", "hospital", "street", "st", "road", "avenue", "place",
               "journal", "friars", "bruins", "airport", "station", "mall", "plantations"}
TRUST_IN = {"trust", "trusted", "trusting", "trusts", "faith", "believe", "believed", "believes",
            "believing", "belief", "hope", "rely", "relied"}


def invokes_providence(words):
    """One sentence: does it speak of Providence as God?"""
    for i, w in enumerate(words):
        if w not in ("providence", "providence's"):
            continue
        before = words[i - 1] if i else ""
        if words[i + 1:i + 2] and words[i + 1] in PLACE_AFTER:
            continue
        if before in PLACE_BEFORE and not (before == "in" and i >= 2 and words[i - 2] in TRUST_IN):
            continue
        if before == "of" and i >= 2 and words[i - 2] in ("city", "town"):
            continue
        return True
    return False


# Strict religion (an option): any sincere mention of God and anything from scripture,
# prayer or worship goes, even "thank God", "God bless" or "Amen". Everyday words (prayed,
# church, grace, soul, angel, faith) stay, and so do swear-like exclamations ("oh my God"),
# which the God's-name word group mutes on its own.
STRICT_WORDS_C = _c([
    r"god", r"god's", r"godly", r"ungodly", r"godless", r"jesus", r"jesus'", r"christ", r"christ's",
    r"allah", r"buddhas?", r"buddha's", r"krishna", r"vishnu", r"messiah", r"saviou?r",
    r"bible", r"bibles", r"biblical", r"scriptures?", r"gospels?", r"psalms?", r"sermons?",
    r"salvation", r"sinners?", r"sinned", r"repent.*", r"resurrect.*", r"crucif.*", r"rosar(y|ies)",
    r"purgatory", r"sacraments?", r"eucharist", r"catechism", r"baptism", r"baptiz.*",
    r"commandments?", r"apostles?", r"disciples?", r"blasphem.*", r"hymns?", r"hymnals?",
    r"quran", r"koran", r"torah", r"talmud", r"sutras?", r"nirvana", r"dharma", r"amen",
    r"hallelujah", r"alleluia", r"heavenly", r"afterlife", r"hallowed", r"verily", r"shalt"])
STRICT_PHRASES = [("the", "lord"), ("our", "lord"), ("dear", "lord"), ("lord", "jesus"),
                  ("lord", "god"), ("lord", "willing"), ("the", "almighty"), ("lord's", "prayer"), ("o", "lord"),
                  ("thank", "you", "lord"), ("praise", "the", "lord"), ("holy", "spirit"),
                  ("holy", "ghost"), ("holy", "communion"), ("holy", "water"), ("in", "heaven"),
                  ("to", "heaven"), ("from", "heaven"), ("heaven", "knows"), ("heaven", "only", "knows"),
                  ("thank", "heaven"), ("thank", "heavens"), ("heaven", "help"), ("heaven's", "gate"),
                  ("son", "of", "god"), ("born", "again"), ("came", "to", "pass")]
# not divine: "the Lord of the Rings", "the Lord Mayor", "a match made in heaven"
STRICT_NOT_AFTER_LORD = {"of", "mayor", "chancellor", "protector", "chamberlain", "high", "and"}
# exclamations the God's-name word group handles (muted, not cut)
STRICT_SWEARS = [("oh", "my", "god"), ("my", "god"), ("oh", "god"), ("good", "god"), ("good", "lord"),
                 ("oh", "lord"), ("for", "god's", "sake"), ("for", "gods", "sake"), ("god", "damn"),
                 ("god", "dammit"), ("goddamn",), ("jesus", "christ"), ("sweet", "jesus"),
                 ("for", "christ's", "sake"), ("for", "christs", "sake"), ("god", "almighty"),
                 ("lord", "almighty"), ("oh", "jesus"), ("jesus", "h", "christ"),
                 ("christ", "almighty"), ("good", "god", "almighty"), ("god", "in", "heaven"),
                 ("oh", "my", "lord"), ("lord", "have", "mercy"), ("god", "help", "us"),
                 ("god", "help", "me"), ("lord", "help", "us"), ("lord", "help", "me"),
                 ("swear", "to", "god"), ("for", "the", "love", "of", "god")]


def strict_religion_hit(words):
    """One sentence, for the strict religion option: any sincere religious mention."""
    n = len(words)
    swear = set()
    for i in range(n):
        for ph in STRICT_SWEARS:
            if tuple(words[i:i + len(ph)]) == ph:
                swear.update(range(i, i + len(ph)))
    for i in range(n):
        for ph in STRICT_PHRASES:
            if tuple(words[i:i + len(ph)]) == ph and not swear.issuperset(range(i, i + len(ph))):
                if ph[-1] == "lord" and (words[i + len(ph)] if i + len(ph) < n else "") in STRICT_NOT_AFTER_LORD:
                    continue
                if ph == ("in", "heaven") and i and words[i - 1] == "made":
                    continue
                return True
    if any(i not in swear and any(p.match(w) for p in STRICT_WORDS_C) for i, w in enumerate(words)):
        return True
    return invokes_providence(words)


def mask(word):
    core = re.sub(r"[^A-Za-z]", "", word)
    return word if len(core) <= 1 else core[0] + "*" * (len(core) - 1)


def shown(raw, normed):
    """A muted span as the review screen shows it: swears starred, "what the" left readable."""
    return " ".join(w if n_ in LEAD_WORDS else mask(w) for w, n_ in zip(raw, normed))


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
    "ref": "a sexual reference, sexual joke or innuendo, or talk about sex, including talk of oral "
           "sex or of touching someone's private parts; only the sentences that are sexual "
           "themselves, not the ones around a joke (plainly mentioning underwear, ordinary romance, "
           "affection and kissing, pregnancy or babies, 'sex' meaning men or women ('the fair "
           "sex'), a polite 'it's a pleasure', or a body part in a threat are NOT this)",
    # judged by what's happening, not by where they are or what they wear (Lauren, 2026-10-30:
    # "sometimes a sex scene is just sitting and wearing clothes", and oral/hand pleasures)
    "sex": "part of a sex scene, judged by what is happening, not by where they are or whether "
           "they are dressed: it includes oral sex and touching someone's private parts (two "
           "people only talking, sitting or lying in bed is NOT this)",
    "gore": "a graphic, gory description of injuries, wounds, dead bodies or violence (simply "
            "saying someone died, was shot or was found dead is NOT this)",
    "religion": None,      # set below from RELIGION_PARTS (religion_def)
    "relationship": "a same-sex couple, romance, relationship or flirting (for example a man "
                    "flirting with or hitting on another man), or a non-traditional relationship "
                    "such as a throuple, polyamory, an open marriage, swingers or polygamy "
                    "('gay' meaning happy or cheerful, as in an old song or 'gay apparel', is NOT "
                    "this)",
    "bully": "bullying or mean-spirited cruelty: taunting, name-calling, mocking or humiliating "
             "someone, or picking on someone weaker, including a villain's mocking song and an "
             "insult passed on ('she called you a ...') (an ordinary argument, a villain's plot or "
             "a police interrogation is NOT this)",
    "disrespect": "a child or teen being bratty or disrespectful to a parent, teacher or other "
                  "grown-up: talking back, sassing, mocking or insulting them, refusing to do what "
                  "they're told, openly disobeying, sneaking out or lying to them (grown-ups "
                  "disagreeing with each other, a child politely saying no or standing up to "
                  "something wrong, friendly teasing, or a child asking why are NOT this)",
    "kiss": "romantic kissing or making out between two people (a parent kissing a child, or a "
            "greeting kiss on the cheek, is NOT this)",
    "sleeping": "an unmarried couple sleeping together or living together, sleeping around, "
                "cheating on a husband, wife or partner, or an affair",
    "substances": "someone drinking alcohol, being drunk, smoking, vaping or using drugs",
    "flirt": "flirting: someone flirting with, hitting on, winking at, sweet-talking or making "
             "romantic advances toward someone (a married couple being affectionate, a simple "
             "compliment or ordinary friendliness is NOT this)",
    "crude": "crude or gross-out humor: jokes about farting, pooping, peeing, burping, boogers or "
             "other bodily functions, toilet humor, or vulgar jokes and pranks (a character simply "
             "feeling sick or using the bathroom is NOT this)",
    "holiday": "a holiday: Christmas (Santa, Christmas trees and decorations, presents, carols), "
               "Halloween (trick-or-treating, Halloween costumes, jack-o'-lanterns), Valentine's "
               "Day (valentines, Cupid), Easter (the Easter bunny, Easter eggs or egg hunts, Easter "
               "baskets) or St. Patrick's Day (leprechauns, a pot of gold, wearing green or "
               "shamrocks for the day, its parades) (Thanksgiving, ordinary eggs or rabbits, "
               "Easter Island, Ireland or Irish people in general, or a church or school named "
               "St. Patrick's are NOT this)",
    "birthday": "candles on a birthday cake: lit candles on a cake, blowing them out, or making a "
                "wish over them (birthdays, parties, cake, presents and singing Happy Birthday are "
                "NOT this)",
    "darkmagic": "dark magic and the occult: witchcraft, wizards and witches doing magic, "
                 "sorcery, curses and hexes, black magic, voodoo, summoning demons or spirits, "
                 "talking to the dead, seances, Ouija boards, fortune telling, tarot, psychics or "
                 "devil worship ('witch' said as an insult, 'a wizard with numbers', stage magic "
                 "tricks or a Halloween costume are NOT this)",
    "magic": "magic: spells, magic wands, fairies doing magic, potions, enchantments, magic "
             "powers, a genie's wishes or a magic object (dark magic, wizards or witches, stage "
             "magic tricks, or 'magic' meaning wonderful, as in 'it was magic' or 'the magic "
             "word', are NOT this)",
    "vampires": "vampires or werewolves: vampires, Dracula, drinking someone's blood, turning "
                "into a bat, werewolves, turning into a wolf at the full moon (vampire bats or "
                "other real animals, and ordinary wolves, are NOT this)",
}
TOPICS = ("holiday", "birthday", "darkmagic", "magic", "vampires")
TOPIC_LABELS = {"holiday": "Holidays", "birthday": "Birthday candles", "darkmagic": "Dark magic",
                "magic": "Magic", "vampires": "Vampires & werewolves"}

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
    "moderate": "a crude swear word such as s***, b****, a**, a**hole, b******, p***ed or d***, "
                "or slang for a man's private parts ('grow some stones', 'has the balls to'), "
                "or fruit and vegetables used for body parts ('check out those melons', "
                "'pop her cherry', 'kneed him in the grapes')",
    "mild": "a mild swear word such as damn, hell used as a curse, crap, bloody used as a curse, "
            "'that's bull' (short for bullshit, not the animal), "
            "or 'screw you' / 'screw it' as an insult ('screw it into the wall' is NOT this)",
    "deity": "God's or Jesus's name used as a swear or exclamation (not in a prayer or sincere "
             "talk about God; 'thank God' is fine)",
    "minced": "a soft substitute swear such as gosh, heck, freaking, darn, golly, good grief, "
              "for Pete's sake, holy cow or 'you don't know squat'",
    "sexual": "a sexual word such as sex, sexy or horny, or a crude word for body parts",
    "orientation": "a word about sexual orientation such as gay, lesbian, homosexual or bisexual "
                   "('gay' meaning cheerful or bright is NOT this)",
    "rude": "a rude word kids copy such as stupid, dumb, idiot, moron, loser, jerk or butt, or "
            "'shut up' / 'you suck' said to someone",
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
                  "peed", "peeing", "screw", "craps", "stones", "balls", "nuts", "pair", "set",
                  "jewels", "pussy", "pussies", "cum", "knockers", "pecker", "peckers", "hooker",
                  "hookers", "tosser", "tossers", "shat", "boner", "boners", "bull", "squat", "gee",
                  "crud", "cruddy", *SUCK_WORDS, *FRUIT_WORDS}
# Not "retard"/"retarded": a slur even said as a description ("a severely retarded boy"). The
# verb ("retard the spread") is never flagged in the first place (INNOCENT_NEXT).


def may_untick_word(m, words=None):
    """Can a checker leave this listed word in? (see INNOCENT_WORDS)"""
    if m.get("cat") in ("deity", "ai", "claude", "rude"):
        return True
    ws = words if words is not None else [norm(w) for w in str(m.get("word_raw") or m.get("word", "")).split()]
    return any(w in INNOCENT_WORDS for w in ws)


# Religious content comes in parts, each its own box (Jason, 2026-10-30: "leave the category as
# a whole that can be clicked off if wanted, but maybe some subcategories"; one Christian novel had
# 69 religion flags, nearly all prayers). Preaching and anger at God are on by default; prayers &
# verses is the old "strict" box.
RELIGION_PARTS = {
    "preach": "someone explaining, preaching, teaching or debating religious beliefs of any faith "
              "(Christian, Catholic, Buddhist, Hindu, Muslim, Jewish or other), or Providence "
              "spoken of as God",
    "anger": "someone being angry with, blaming, hating or denying God, or losing their faith",
    "prayers": "a prayer, a Bible verse or hymn, thanking or praising God, or other sincere talk "
               "about God or faith",
}
RELIGION_LABELS = {"preach": "Preaching", "anger": "Anger at God", "prayers": "Prayers & verses"}


def religion_def(parts=("preach", "anger")):
    """The AI's definition of religious content for the parts ticked."""
    on = [RELIGION_PARTS[p] for p in RELIGION_PARTS if p in parts]
    t = "; or ".join(on) or "religious content"
    if "prayers" not in parts:
        t += (" (praying, a short prayer, saying grace, thanking God, a Bible verse read in passing, "
              "believing in God or going to church are NOT this; nor is God's name said as an "
              "exclamation, like 'Thank God', 'Dear God', 'Oh, hallelujah' or 'go to hell')")
    t += (" (idioms like 'a match made in heaven', 'fire and brimstone', 'get to the church on time' "
          "or 'penance' meaning a punishment are NOT this)")
    if "preach" not in parts:
        t += " (preaching or explaining beliefs is NOT this)"
    if "anger" not in parts:
        t += " (doubting, being angry with or denying God is NOT this)"
    return t


AI_TYPES["religion"] = religion_def()
PASSIONATE_KISS = ("passionate romantic kissing or making out (a quick or gentle kiss, or a parent "
                   "kissing a child, is NOT this)")


def ai_defs_for(religion_parts=("preach", "anger"), kiss="all"):
    """The AI's definitions that depend on the options: religion's parts, and kissing."""
    out = {"religion": religion_def(religion_parts)}
    if kiss == "passionate":
        out["kiss"] = PASSIONATE_KISS
    return out


def _read():
    """CleanRead's engine (it ships with CleanListen): its word lists for sleeping around,
    drinking, smoking & drugs and kissing are used for audiobooks too, so both apps match."""
    import cleanread
    return cleanread


def sleeping_hit(words):
    return bool(_read().SLEEPING(words))


def substances_hit(words):
    return bool(_read().SUBSTANCES(words))


def kiss_hit(words, mode="all"):
    """mode: "passionate" (only passionate kissing) or "all" (any romantic kiss)."""
    return bool(_read().kiss_hit(words, mode))


def _ai_backed(kind, words):
    """Does a passage the AI on this PC flagged contain anything the word lists recognise
    for that kind? (Its unbacked finds are mostly false alarms, so they start unticked.)"""
    try:
        if kind in ("sex", "ref"):
            return is_explicit(words) or bool(find_language(words, ["sexual"]))
        if kind == "gore":
            return is_gory(words)
        if kind == "religion":
            return religion_score(words) > 0 or blames_god(words) or invokes_providence(words)
        if kind == "crude":
            return crude_hit(words)
        if kind == "bully":
            return bully_hit(words)
        if kind == "disrespect":
            return disrespect_hit(words)
        if kind == "flirt":
            return flirt_hit(words)
        if kind == "sleeping":
            return sleeping_hit(words)
        if kind == "substances":
            return substances_hit(words)
        if kind == "kiss":
            return kiss_hit(words, "all")
        if kind in TOPICS:
            return topic_hit(kind, words)
    except Exception:
        pass
    return False


def _learned_examples(title=""):
    """What they told the chat to keep in mind, and past choices (yours, then Claude's), for
    the AI on this PC to follow."""
    try:
        import cleanlisten_learn as learn
        t = learn.examples_text(title).strip()
        return (t + "\n\n") if t else ""
    except Exception:
        return ""


def ai_assist(asr, scenes, kinds, to_sentences, span_times, progress=None, cancel=None,
              chunk=40, overlap=6, mutes=None, cats=(), parts=None, title="", defs_for=None):
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
    T = {**AI_TYPES, **(defs_for or {})}     # religion and kissing as the boxes say
    defs = "\n".join(f'- "{t}": {T[t]}' for t in kinds)
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
        prompt = _learned_examples(title) + ("You help a family decide which sentences of an audiobook to cut. Here are "
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
        conf = verify(f"Does the marked sentence clearly contain {T[kind]}?", i)
        if conf:
            found.setdefault(kind, {})[i] = conf

    # ---- 3. second opinion on what the word lists flagged
    checks = [sc for sc in scenes if sc.get("kind") in AI_TYPES and not sc.get("ai") and not sc.get("strict")]
    yes_no = {"type": "object", "properties": {"fits": {"type": "boolean"}}, "required": ["fits"]}
    for n, sc in enumerate(checks):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(n / max(len(checks), 1), "AI is double-checking what was flagged…")
        try:
            res = ai.chat("Here is a passage from an audiobook:\n\n" + sc["text"][:4000] +
                          "\n\nDoes it contain " + T[sc["kind"]] +
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


def in_background(work):
    """Start work() in a thread. Returns the job for wait_for()."""
    job = {"error": None}

    def run():
        try:
            work()
        except BaseException as ex:      # KeyboardInterrupt (cancelled) too
            job["error"] = ex
    job["thread"] = threading.Thread(target=run, daemon=True)
    job["thread"].start()
    return job


def wait_for(job, waiting=None, cancel=None):
    """Wait for an in_background() job; pass on its error (or a cancel)."""
    while job["thread"].is_alive():
        if waiting:
            waiting()
        if cancel and cancel():
            raise KeyboardInterrupt
        job["thread"].join(0.5)
    if job["error"]:
        raise job["error"]


def _overlaps(x, items):
    return any(y["part"] == x["part"] and not (x["e"] <= y["s"] or x["s"] >= y["e"]) for y in items)


def _merge_ai(st, scene_pairs, mute_pairs, ai_scenes, ai_mutes, claude_ok):
    """Put what the AI on this PC found (in its own copies) into the checked results. After a
    final check, it can't untick anything (the final check decides), and what only it found is
    added unticked for you to decide. If the final check failed, it works as it does alone.
    Returns the note for the review screen."""
    scenes, mutes = st["scenes"], st["mutes"]
    n_new = n_sure = n_off = 0
    if not claude_ok:
        live = {id(x) for x in scenes + mutes}
        for orig, mine in scene_pairs:
            if id(orig) in live and mine.get("ai_note") == "AI thinks this one is fine" and \
                    orig.get("cut", True) and not orig.get("by_you"):
                orig.update(cut=False, ai_note=mine["ai_note"])
                n_off += 1
        for orig, mine in mute_pairs:
            if id(orig) in live and mine.get("note") == "AI thinks this isn't swearing" and \
                    orig.get("on", True) and not orig.get("by_you"):
                orig.update(on=False, note=mine["note"])
                n_off += 1
    copies = {id(c) for _, c in scene_pairs + mute_pairs}
    for items, found, key, note_key in ((scenes, ai_scenes, "cut", "ai_note"),
                                        (mutes, ai_mutes, "on", "note")):
        for x in found:
            if id(x) in copies or _overlaps(x, items):
                continue
            if claude_ok:
                x[key], x[note_key] = False, "AI on this PC suggests"
            n_new += 1
            n_sure += bool(x[key])
            items.append(x)
    scenes.sort(key=lambda x: (x["part"], x["s"]))
    mutes.sort(key=lambda m: (m["part"], m["s"]))
    for n, x in enumerate(scenes, 1):
        x["id"] = n
    for n, m in enumerate(mutes, 1):
        m["id"] = n
    if claude_ok:
        return (f"The AI on this PC looked too, at the same time: it found {n_new} more the final "
                "check didn't (left unticked for you to decide).")
    return (f"AI helper added {n_sure} it's sure about, suggested {n_new - n_sure} more for you to "
            f"decide (left unticked), and unticked {n_off} it thinks were flagged by mistake.")


def load_asr(workdir, parts):
    """The transcript as one word list (same shape analyze() uses)."""
    done = json.loads((Path(workdir) / "transcript.json").read_text())
    return [{**w, "part": pi, "n": norm(w["t"])} for pi, p in enumerate(parts) for w in done[p]]


def analyze(parts, workdir, ebook=None, groups=("swearing", "mild", "deity", "sexual"),
            find_sex=True, progress=None, log=print, model_dir=DEFAULT_MODEL,
            find_refs=False, find_gore=False, find_religion=False, find_relationships=False,
            find_crude=False, use_ai=False,
            threads=None, cancel=None, find_bully=False, find_flirt=False, use_claude=False,
            find_disrespect=False,
            strict_religion=False, find_topics=(), title="", find_sleeping=False,
            find_substances=False, kiss="keep", religion_parts=None):
    """progress(fraction 0..1, message). Returns the analysis dict (also saved
    to workdir/analysis.json). find_topics: any of TOPICS (holidays, birthday candles, magic,
    dark magic) to cut."""
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
    for i, j, cat in find_language(asr_n, cats, lead_in_too=True):
        b, a = clean_context(asr_t, asr_n, i, j)
        mutes.append({"part": asr[i]["part"], "s": asr[i]["s"], "e": asr[j - 1]["e"], "cat": cat,
                      "src": "audio", "word": shown(asr_t[i:j], asr_n[i:j]),
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
            for i, j, cat in find_language(eb_n, cats, lead_in_too=True):
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
                              "word": shown(eb_words[i:j], eb_n[i:j]),
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
    # which kinds of religious content (Jason, 2026-10-30): preaching, anger at God, and prayers
    # & verses (the old "strict" box); without religion_parts it's preaching and anger, plus
    # prayers when strict_religion
    rparts = set(religion_parts if religion_parts is not None else
                 ("preach", "anger") + (("prayers",) if strict_religion else ()))
    rparts &= set(RELIGION_PARTS)
    find_religion = find_religion and bool(rparts)
    if find_religion:
        say(0.99, "Looking for religious content\u2026")
        rel = (find_passages(religion_score, RELIGION_C, RELIGION_WINDOW_SCORE, "religion")
               if "preach" in rparts else [])
        # single sentences that blame or hate God, deny God, or speak of Providence as God
        # (strict: any sincere religious mention, "thank God", a verse, a prayer)
        k = 0
        while k < len(asr):
            a_, b_ = to_sentences(k, k)
            ws = asr_n[a_:b_ + 1]
            anger = "anger" in rparts and blames_god(ws)
            prov = "preach" in rparts and invokes_providence(ws)
            strict = "prayers" in rparts and strict_religion_hit(ws) and not (blames_god(ws) or
                                                                              invokes_providence(ws))
            if strict or anger or prov:
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
                        if strict:
                            rel[-1]["strict"] = True   # the AI on this PC doesn't second-guess these
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
                               (find_disrespect, disrespect_hit, "disrespect",
                                "Looking for disrespect…"),
                               (find_flirt, flirt_hit, "flirt", "Looking for flirting…"),
                               (find_sleeping, sleeping_hit, "sleeping",
                                "Looking for sleeping around…"),
                               (find_substances, substances_hit, "substances",
                                "Looking for drinking, smoking & drugs…"),
                               (kiss in ("passionate", "all"), lambda w: kiss_hit(w, kiss), "kiss",
                                "Looking for kissing…"),
                               *((t in find_topics, lambda w, t=t: topic_hit(t, w), t,
                                  f"Looking for {TOPIC_LABELS[t].lower()}…") for t in TOPICS)):
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
                             ("disrespect", find_disrespect),
                             ("flirt", find_flirt), ("sleeping", find_sleeping),
                             ("substances", find_substances), ("kiss", kiss in ("passionate", "all")),
                             *((t, t in find_topics) for t in TOPICS)) if on]
    ai_defs = ai_defs_for(rparts, kiss)
    ai_job = None
    if use_ai and use_claude:
        # both look (Lauren, 2026-10-29), at the same time: the AI on this PC reads its own copy
        # of what was found while Claude/ChatGPT/Gemini reads the book, then the two are merged
        # (_merge_ai). Not one after the other: that was the same slow step twice.
        for sc in scenes:
            sc.setdefault("cut", True)
        pairs = [(x, dict(x)) for x in scenes], [(m, dict(m)) for m in mutes]
        ai_scenes, ai_mutes = [c for _, c in pairs[0]], [c for _, c in pairs[1]]
        ai_job = in_background(lambda: ai_assist(
            asr, ai_scenes, kinds, to_sentences, span_times, cancel=cancel, mutes=ai_mutes,
            cats=cats, parts=parts, title=title, defs_for=ai_defs))
    elif use_ai:
        try:
            for sc in scenes:
                sc.setdefault("cut", True)
            ai_assist(asr, scenes, kinds, to_sentences, span_times,
                      progress=lambda f, m: say(0.99, m), cancel=cancel,
                      mutes=mutes, cats=cats, parts=parts, title=title, defs_for=ai_defs)
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
          "ai_note": ai_note, "sentences": sents, "title": title,
          "filters": {"cats": cats, "kinds": kinds,
                      "strict_religion": bool(find_religion and "prayers" in rparts),
                      "religion_parts": sorted(rparts) if find_religion else [], "kiss": kiss}}
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
        claude_ok = False
        try:
            import cleanlisten_claude as cc
            cc.review(st, asr, progress=lambda f, m: say(0.99, m), cancel=cancel)
            claude_ok = True
        except KeyboardInterrupt:
            raise                        # (the AI on this PC sees the same cancel and stops)
        except Exception as ex:
            st["claude_note"] = (f"Claude couldn't check this book ({ex}). The results below are "
                                 "from the word lists" + (" and the AI helper." if use_ai else "."))
        log(st.get("claude_note", ""))
        if ai_job:
            try:
                wait_for(ai_job, lambda: say(0.99, "Finishing the AI on this PC\u2026"), cancel)
                st["ai_note"] = _merge_ai(st, *pairs, ai_scenes, ai_mutes, claude_ok)
            except KeyboardInterrupt:
                raise
            except Exception as ex:
                st["ai_note"] = f"AI helper couldn't run ({ex})."
            log(st["ai_note"])
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
def extract_clip(path, s, e, dst, pad=1.0, longest=300.0):
    """A WAV of the book from `pad` seconds before s to `pad` after e (at most `longest`
    seconds), for the review screen's Play button. Returns the clip's (start, end)."""
    a = max(0.0, s - pad)
    b = min(e + pad, a + longest)
    r = run([_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(path),
             "-vn", "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", str(dst)],
            capture_output=True, text=True)
    if r.returncode != 0 or not Path(dst).exists():
        raise RuntimeError(f"Couldn't play that part ({(r.stderr or '').strip()[-200:] or 'no audio'}).")
    return a, b


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
                     "crude": "crude humor", "bully": "bullying", "disrespect": "disrespect",
                     "sleeping": "sleeping around", "substances": "drinking, smoking & drugs",
                     "kiss": "kissing",
                     "flirt": "flirting",
                     **{t: TOPIC_LABELS[t].lower() for t in TOPICS}}.get(c.get("kind"), "scene")
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
