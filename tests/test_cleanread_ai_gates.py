"""The PC AI's own suggestions of violence, disturbing violence, disrespect, bullying, medical scenes
(and, in CleanListen, same-sex relationships) need some sign of the thing in the sentence or the
one before or after (cleanlisten.ai_gate; the owner, 2026-11-16: "you mentioned it over flagging. i
noticed that also. how can we work on it?"). In her Black Beauty report the small AI suggested 88
lines as violence (a stone in a hoof, a falling tree, a horse being shod, falls) and 55 as
disrespect (about one fits). The lines here are from her reports. A gate never drops a line with a
sign: Black Beauty's whippings, the war and the shooting, which she kept on purpose, are still
offered."""
import re

import pytest

import cleanlisten as E
import cleanread as R


def words(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


def keeps(kind, *sents):
    return E.ai_gate(kind, [words(s) for s in sents])


# ---- violence ------------------------------------------------------------------------------
VIOLENCE_DROPPED = [   # accidents, falls, lameness, shoeing... (all left unticked by her)
    "Then he took a piece of iron the shape of my foot, and clapped it on, and drove some nails "
    "through the shoe quite into my hoof, so that the shoe was firmly on.",
    "The words were scarcely out of his mouth when there was a groan, and a crack, and a splitting "
    "sound, and tearing, crashing down among the other trees came an oak, torn up by the roots, and "
    "it fell right across the road just before us.",
    "“The bridge is broken in the middle, and part of it is carried away; if you come on you’ll be "
    "into the river.”",
    "I stumbled, and fell with violence on both my knees.",
    "“Why, the horse has been down and thrown him!",
    "Nobody thought he could fall.",
    "Why, they have sent us out with a lame horse!",
    "Then holding it up he said, “There, that’s the stone your horse had picked up.",
    "The gig shaft ran right into the chest, making him stagger back with a cry that I shall never "
    "forget.",
    "“You can’t do it,” said Jerry, “you might be knocked down and the child be run over.",
    "A window was thrown up, and Dr. White, in his nightcap, put his head out and said, “What do "
    "you want?”",
    "Some men held Henry up high and carried him to Mr. Alden for the prize.",     # Boxcar Children
    "We could have been arrested for breaking and entering!",                      # Camp Club Girls
    "Chunks of wood crashed to the floor.",                                        # Wings of a Dream
    "Bump.",
]
VIOLENCE_KEPT = [      # real violence, kept even where she left it in on purpose
    "He whipped him again, but the pony turned off on the other side.",
    "Then the boy got off and gave him a hard thrashing, and knocked him about the head;",
    "A third time he was flogging me cruelly, when a lady stepped quickly up to him,",
    "He was raising the whip again, when the lady said, “Pray, stop; I think I can help you if you "
    "will let me.”",
    "My master as usual whipped me smartly, but the old man cried out, ‘You’re wrong! you’re wrong!",
    "He did not see me and I gave him a box on the ears that laid him sprawling on the floor.",
    "Then someone ran to our master’s house and came back with a gun; presently there was a loud "
    "bang and a dreadful shriek, and then all was still; the black horse moved no more.",
    "I saw many brave men cut down, many fall mortally wounded from their saddles.",
    "From the right, from the left, and from the front, shot and shell poured in upon us.",
    "Then slashing his jaded horse, he set off as hard as he could.",
    "He seemed furious at their having moved, and with whip and rein punished them brutally, even "
    "beating them about the head.",
    "I have given them a thrashing they will remember; a set of cowardly, rascally ‘orange’ "
    "blackguards.”",
    "he thought the kindest thing he could do for the fine old fellow would be to put a sure bullet "
    "through his head",
    "He hauled off and hit Henry square in the nose.",                             # Wings of a Dream
    "He hefted his weapon and brought it down again.",
]


@pytest.mark.parametrize("s", VIOLENCE_DROPPED)
def test_no_sign_of_violence_is_dropped(s):
    assert not keeps("violence", s)


@pytest.mark.parametrize("s", VIOLENCE_KEPT)
def test_real_violence_is_kept(s):
    assert keeps("violence", s)


def test_a_look_or_a_rise_is_not_a_gunshot():
    for s in ["Mama shot him a dark look.", "Then fear shot through me like a bolt of lightning.",
              "His eyebrows shot up.", "He poured a shot of whiskey."]:
        assert not keeps("violence", s), s
    for s in ["He shot him twice.", "The farriers shot all that were ruined."]:
        assert keeps("violence", s), s


def test_a_quiet_line_next_to_violence_is_kept():
    # "he did not give him any more punishment of that kind" comes right after the whipping
    quiet = "I never saw him so angry before; but he did not give him any more punishment of that kind."
    assert not keeps("violence", quiet)
    assert keeps("violence", "He whipped him again.", quiet, "The bus was late again.")


# ---- disrespect (a child or teen being rude to a grown-up) ---------------------------------
DISRESPECT_DROPPED = [
    "“Who is your master, young man? if it be a proper question.",
    "“Did not your master take any thought for you?”",
    "“Why, Dolly, what is the matter?”",
    "’Tis a hard world!”",
    "“Steady, steady, my boy,” he would say, “wait a bit, and we will have a good swing, and soon get "
    "the tickle out of your feet.”",
    "“Do you know what they fought about?” said I.",
    "“You had better write to him, York. I should be more particular about the place than the money "
    "he would fetch.”",
    "Rebekah Grace, if you don’t hurry we’ll be late for the lecture.”",           # Wings of a Dream
    "I felt Mama’s face fit over mine like a mask.",
    "Everyone expects me to be polite, to make good grades, to be clean and tidy.",  # Camp Club Girls
    "I’m going to report you.”",
]
DISRESPECT_KEPT = [
    # the son answering his father back (Black Beauty)
    "During this speech the boy had stood by, sullen and dogged, but when his father ceased he broke "
    "out angrily.",
    "“I haven’t lost them,” I sassed back.",
    "Dan crossed his arms. “But it’s cold outside.”",          # she left this one ticked
    "“You’re not the boss of me, Mom!”",
    "“I won’t, and you can’t make me,” she told her teacher.",
    "Jake rolled his eyes at his father.",
]


@pytest.mark.parametrize("s", DISRESPECT_DROPPED)
def test_no_sign_of_disrespect_is_dropped(s):
    assert not keeps("disrespect", s)
    assert not keeps("rebellion", s)            # the content check's name for it


@pytest.mark.parametrize("s", DISRESPECT_KEPT)
def test_real_disrespect_is_kept(s):
    assert keeps("disrespect", s)


def test_a_grownup_and_something_rude_can_be_in_neighbouring_sentences():
    assert keeps("disrespect", "“I hate this stupid farm!”", "she yelled at her mother.")
    assert not keeps("disrespect", "“I hate this stupid farm!”", "she yelled at the dog.")


# ---- bullying, disturbing, medical ---------------------------------------------------------
def test_bully_gate():
    for s in ["James pestered.", "Stop it, Dan.", "Mama’s smugness irritated me, like a bad case of "
              "poison oak.", "“Halloo! he’s bad in his foot as well as his knees.",
              "“Hold hard,” said Joe, “don’t go on flogging the horses like that; the wheels are so "
              "stuck that they cannot move the cart.”"]:
        assert not keeps("bully", s), s
    for s in ["“Mind your own business, you impudent young rascal, and I’ll mind mine!”",
              "“Who talks about blockheads?” said Merrylegs.", "The big boys laughed at him and "
              "called him a baby.", "At recess, Mark shoved Danny into the lockers and called him a "
              "loser."]:
        assert keeps("bully", s), s


def test_disturbing_gate():
    # the small AI ticked these on its own in Wings of a Dream and none fit (the owner, 2026-11-15)
    for s in ["A wail rose from inside the house.", "A scream.", "I fumed back to the house.",
              "Then fear shot through me like a bolt of lightning in a night sky.",
              "Dan’s screams filled the air, his eyes squeezed shut, mouth open wide.",
              "He growled again.", "“Take Benny now.”",                # The Boxcar Children
              "All of a sudden, a bloodcurdling scream pierced the air."]:
        assert not keeps("disturbing", s), s
    for s in ["There was a dreadful sound before we got into our stalls, the shrieks of those poor "
              "horses that were left burning to death in the stable.",
              "the carter was shouting and flogging the two horses unmercifully.",
              "while the man, fiercely pulling at the head of the fore horse, swore and lashed most "
              "brutally.", "They tortured him for days.",
              "there were some so thin you might see all their ribs, and some with old sores on "
              "their backs and hips."]:
        assert keeps("disturbing", s), s


def test_medical_gate():
    for s in ["The first thing was to pull my mouth open, then to look at my eyes, then feel all the "
              "way down my legs, and give me a hard feel of the skin and flesh, and then try my paces.",
              "The horse was hot and much exhausted; he hung his head down."]:
        assert not keeps("medical", s), s
    for s in ["he tied up my foot in a bran poultice, to draw out the heat and cleanse it before the "
              "horse-doctor saw it in the morning", "The nurse slid the needle into his arm.",
              "The coroner said the wound was made by a knife."]:
        assert keeps("medical", s), s


def test_other_kinds_are_not_gated():
    for kind in ("drinking", "smoking", "gore", "graphic", "religion", "kiss", "crude", "holiday"):
        assert E.ai_gate(kind, [words("The bus was late again.")])


# ---- in CleanRead's AI read ----------------------------------------------------------------
PLAIN = ["The wind blew across the fields.", "Anna fed the chickens before school.",
         "Her brother read a book by the fire.", "The bus was late again.", "They ate soup for lunch."]
STONE = "Then holding it up he said, “There, that’s the stone your horse had picked up.”"
WHIP = "The man was in a towering passion and laid on the whip again."
MASTER = "“Did not your master take any thought for you?”"
SASS = "“I haven’t lost them,” I sassed back."
FLAGS = {STONE: "violence", WHIP: "violence", MASTER: "disrespect", SASS: "disrespect"}


class FakeAI:
    """Like the small local AI: flags all four, and agrees when asked again."""
    MODEL = "fake:gates"

    def __init__(self):
        self.checks = []

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "numbered sentences" in prompt:
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("The sentences:")[-1], re.M)
            return {"flags": [{"n": int(n), "type": k, "words": s.strip("“”.")}
                              for n, t in lines for s, k in FLAGS.items() if s in t]}
        self.checks.append(prompt.split(">>> ")[-1].split(" <<<")[0])
        return {"fits": True, "confidence": "high"}


@pytest.fixture
def book(tmp_path):
    sents = [PLAIN[k % 5] for k in range(60)]
    sents[10], sents[20], sents[30], sents[45] = STONE, WHIP, MASTER, SASS
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(" ".join(sents[k:k + 5]) for k in range(0, 60, 5)), encoding="utf8")
    return R.Book(str(p))


def test_cleanread_drops_finds_with_no_sign(book, monkeypatch):
    ai = FakeAI()
    monkeypatch.setattr(R, "_ai", lambda: ai)
    info = {}
    found = R.ai_find(book, {"violence": R.CLEAN_AI["violence"],
                             "disrespect": R.CLEAN_AI["disrespect"]}, info=info)
    kept = {(book.sent_text(i), kind) for i, kind in found}
    assert kept == {(WHIP, "violence"), (SASS, "disrespect")}
    assert info["gated"] == {"violence": 1, "disrespect": 1}
    # the dropped ones aren't even double-checked (less waiting)
    assert not any(STONE[10:40] in c or MASTER[5:30] in c for c in ai.checks)
    note = R.ai_run_note(info)
    assert "left out 2 of its own ideas" in note and "violence 1" in note and "disrespect 1" in note


def test_your_kept_choices_still_win(book, monkeypatch, tmp_path):
    """A gate only takes away: what the gate keeps still starts unticked if you kept it before."""
    monkeypatch.setattr(R, "_ai", lambda: FakeAI())
    monkeypatch.setattr(R, "LEARNED", tmp_path / "learned.json")
    whip_key = R.item_key(WHIP)
    R.learn_marks([("violence", whip_key, WHIP, True)])
    an = R.analyze(book, {"violence": True, "disrespect": True, "ai": True})
    ai_cuts = {c["raw"]: c for c in an["cuts"] if c.get("ai")}
    assert STONE not in ai_cuts and MASTER not in ai_cuts
    assert ai_cuts[WHIP]["cut"] is False and ai_cuts[WHIP]["ai_note"] == "You kept this before"
    assert ai_cuts[SASS]["cut"] is False and ai_cuts[SASS]["ai_note"] == "AI suggests"


# ---- in CleanListen's AI step --------------------------------------------------------------
REL_PLAIN = "Daphne is late."                          # You Will Remember Nothing
REL_REAL = "Emma kissed her girlfriend goodnight."


class FakeListenAI:
    MODEL = "fake:listen"

    def ensure_ai(self, progress=None):
        pass

    def chat(self, prompt, schema=None, timeout=300):
        if "sentences in order" in prompt:
            out = [{"quote": s, "type": k} for s, k in FLAGS.items() if s in prompt]
            out += [{"quote": s, "type": "relationship"} for s in (REL_PLAIN, REL_REAL) if s in prompt]
            return {"flags": out}
        if '"fine"' in prompt:
            return {"fine": []}
        return {"fits": True, "confidence": "high"}


def test_cleanlisten_uses_the_same_gates(monkeypatch):
    sents = PLAIN + [STONE] + PLAIN + [WHIP] + PLAIN + [MASTER] + PLAIN + [SASS] + PLAIN + \
        [REL_PLAIN] + PLAIN + [REL_REAL] + PLAIN
    text = " ".join(sents)
    asr = [{"t": w, "s": k * 0.4, "e": k * 0.4 + 0.3, "part": 0, "n": E.norm(w)}
           for k, w in enumerate(text.split())]
    ends = [k for k, w in enumerate(asr) if re.search(r"[.!?][”\"]?$", w["t"])]

    def to_sentences(i, j):
        a = max([e + 1 for e in ends if e < i] or [0])
        return a, min(e for e in ends if e >= j)
    monkeypatch.setattr(E, "_ai_module", lambda: FakeListenAI())
    monkeypatch.setattr(E, "_learned_examples", lambda title="": "")
    scenes = E.ai_assist(asr, [], ["violence", "disrespect", "relationship"], to_sentences,
                         E.span_times)
    got = {(sc["kind"], " ".join(sc["text"].split())) for sc in scenes}
    texts = " | ".join(t for _, t in got)
    assert any(k == "violence" and "laid on the whip" in t for k, t in got), got
    assert any(k == "disrespect" and "sassed back" in t for k, t in got), got
    assert any(k == "relationship" and "girlfriend" in t for k, t in got), got
    assert "stone your horse" not in texts and "your master take" not in texts
    assert "Daphne is late" not in texts
