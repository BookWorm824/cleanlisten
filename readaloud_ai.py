"""
ReadAloud's reading director: Claude (or ChatGPT, Gemini) reads the book before the voice does
and marks how to read it. Lauren, 2026-11-06: "have claude or chat go through the book - remove
anything that shouldn't be read, look at the context of the book and give the reading directions
for the reader ai to know how to read".

What the voice (Kokoro) can do with directions, and so what's asked for:
  * leave out what isn't the story (page numbers, running heads, jacket text, scanning garbage)
  * fix scanning mistakes ("Phylusa", "fiat" for "flat"), only when the words stay the same
  * who says each quoted line (so characters can have their own voices, and a first-person
    narrator's own lines stay in the narrator's voice)
  * pace (slower / faster) and pauses (a scene change, a dramatic beat)
  * how to say unusual names and words ("Tlaquepaque" -> "tlah-keh-pah-keh")
Kokoro can't act out an emotion on request, so mood is used for the pace only.

Flow: cast() reads the opening once (narrator, characters, names to say carefully); direct_chunk()
reads ~2500 words at a time (3 at once) and lists only the paragraphs that need something. Every
answer is kept in a cache folder per book and chapters (direction_dir()), so changing the voice later,
or carrying on after a stop, never asks again. apply() turns the answers into the job's
chapters: [kind, text, {"v": voice, "s": speed, "g": pause before}] items.
"""
import difflib
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import readaloud as R  # noqa: E402

CHUNK_WORDS = 2500
AT_ONCE = 3
SKIP_MOST = 150          # a paragraph longer than this is never left out (could be the story)
PACE = {"slower": 0.92, "normal": 1.0, "faster": 1.07}
PAUSE = {"short": 0.25, "long": 1.1, "scene": 1.6}
PART_GAP = 0.12          # between a quote and "she said" in one paragraph

SYSTEM = """You are the director for an audiobook. A text-to-speech voice will read this book
aloud. You read the text first and tell the voice how to read it. The voice reads exactly the
words it is given. It can change voice for a character, speed up or slow down, pause, and (the
better voices) act: it follows a short acting note for each paragraph and each quoted speech.

The text came from an ebook, sometimes a scanned printed book, so it can contain things that
must not be read aloud: page numbers, the book's title or author repeated at the top of pages,
jacket or flap text, publisher's lists, "continued on back flap", footnote markers, garbage
characters from scanning. Scanning also leaves mistakes: words glued together or split,
letters misread ("fiat" for "flat", "/" for "I", "1" for "I", stray commas).

Rules:
- Never change the story's words, never summarize, never censor. A fix only repairs scanning
  or typing mistakes; the corrected paragraph must say the same thing word for word.
- "skip" only for text that is clearly not part of the book's text (page furniture, jacket
  copy, scanning garbage). Front matter like a dedication is part of the book: keep it. When only
  part of a paragraph shouldn't be read (a script's "Name:" speaker label, a cast list run into
  the title, a page number in the middle), give the paragraph without it as "fix", taking words
  out only.
- Speakers: for each quoted speech in a paragraph ("..." pairs, in order), name who says it,
  using the names from the cast list. If the narrator is a character telling the story in the
  first person, their own speech is spoken by that character's name. If you can't tell, use
  "narrator". A speech continuing from the previous paragraph (opening quote, no closing quote
  before) counts as a quoted speech too.
- Pace "slower" for tender, sad, solemn or suspenseful moments; "faster" for urgent, excited or
  angry ones; otherwise "normal". Use it sparingly, as a good human narrator would.
- Pause "scene" before a paragraph that starts a new scene (a time or place jump), "long" for a
  dramatic beat, "short" to run on quickly; otherwise "normal".
- Acting notes, like a good audiobook director's: "delivery" for the paragraph's narration and
  "speech_delivery" for each quoted speech in order (one per speaker listed). 3 to 10 plain words
  on how it should sound, from what is happening and how the speaker feels: "quiet, numb
  disbelief", "teasing, warm", "urgent whisper", "dry and matter-of-fact". Keep them true to the
  scene and varied; most narration is just "natural, engaged storytelling" with a touch of the
  mood. Never theatrical, never overacted.
- "feel": how strong the emotion is: "calm", "warm" (normal), or "strong" (shouting, sobbing,
  terror, fury).
- List EVERY paragraph (each needs its acting note), in order.
- Pronunciations: unusual names and foreign words an American text-to-speech voice would get
  wrong. "say" is a plain respelling in lowercase syllables joined by hyphens
  (Tlaquepaque -> "tlah-keh-pah-keh", Hermione -> "her-my-oh-nee"). Leave ordinary names out."""

CAST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["first_person", "narrator_name", "characters", "pronounce", "notes"],
    "properties": {
        "first_person": {"type": "boolean"},
        "narrator_name": {"type": "string"},
        "characters": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "gender", "age", "manner"],
            "properties": {"name": {"type": "string"},
                           "gender": {"type": "string", "enum": ["female", "male", "unknown"]},
                           "age": {"type": "string", "enum": ["child", "teen", "adult", "older"]},
                           "manner": {"type": "string"}}}},
        "pronounce": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["word", "say"],
            "properties": {"word": {"type": "string"}, "say": {"type": "string"}}}},
        "notes": {"type": "string"},
    }}

CHUNK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["paragraphs", "characters", "pronounce"],
    "properties": {
        "paragraphs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["n", "skip", "fix", "pause", "pace", "mood", "speakers", "delivery",
                         "speech_delivery", "feel"],
            "properties": {
                "n": {"type": "integer"},
                "skip": {"type": "boolean"},
                "fix": {"type": "string"},
                "pause": {"type": "string", "enum": ["normal", "short", "long", "scene"]},
                "pace": {"type": "string", "enum": ["slower", "normal", "faster"]},
                "mood": {"type": "string"},
                "speakers": {"type": "array", "items": {"type": "string"}},
                "delivery": {"type": "string"},
                "speech_delivery": {"type": "array", "items": {"type": "string"}},
                "feel": {"type": "string", "enum": ["calm", "warm", "strong"]}}}},
        "characters": CAST_SCHEMA["properties"]["characters"],
        "pronounce": CAST_SCHEMA["properties"]["pronounce"],
    }}


def direction_dir():
    return R.JOBS / "direction"


def cc():
    import cleanlisten_claude
    return cleanlisten_claude


def provider_name(provider):
    return cc().NAMES.get(provider, "Claude")


# ---------------------------------------------------------------------------
# Splitting a paragraph into narration and quoted speech
# ---------------------------------------------------------------------------
def split_quotes(text):
    """[(is_speech, text)] in order. A speech still open at the end of the paragraph (it carries
    on in the next one, as books print long speeches) runs to the end."""
    out, k = [], 0
    for m in re.finditer(r'"[^"]*("|$)', text):
        if m.start() > k and text[k:m.start()].strip():
            out.append((False, text[k:m.start()].strip()))
        if m.group(0).strip('" '):
            out.append((True, m.group(0).strip()))
        k = m.end()
    if text[k:].strip():
        out.append((False, text[k:].strip()))
    return out or [(False, text)]


def only_removed(a, b):
    """The words taken out, if b is a with words only taken out (nothing added or changed): the cast
    list at the top of a script, or a stray "Melissa:" label in a line. "" if not."""
    wa = re.findall(r"[a-z0-9]+", a.lower())
    wb = re.findall(r"[a-z0-9]+", b.lower())
    if not wb or len(wb) >= len(wa):
        return ""
    gone = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "delete":
            gone += wa[i1:i2]
        elif op != "equal":
            return ""
    return " ".join(gone) if 0 < len(gone) <= SKIP_MOST else ""


def same_words(a, b):
    """Is b the same paragraph as a with scanning mistakes fixed (not reworded or shortened)?"""
    wa = re.findall(r"[a-z0-9]+", a.lower())
    wb = re.findall(r"[a-z0-9]+", b.lower())
    if not wa or not wb or not 0.75 <= len(wb) / len(wa) <= 1.3:
        return False
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio() >= 0.75


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------
DIRECTION_VERSION = "2"     # 2: acting notes, feel, manner (1.17.0); older answers are asked again


def book_key(job, chapters):
    text = json.dumps([c["paras"] for c in chapters])
    return hashlib.sha1((job.get("director", "") + "|" + DIRECTION_VERSION + "|" + text)
                        .encode("utf8")).hexdigest()[:16]


def _ask(prompt, schema, timeout=1200):
    lib = cc()
    try:
        return lib.run(prompt, SYSTEM, schema=schema, timeout=timeout)["data"]
    except lib.ClaudeError as ex:
        raise RuntimeError(f"{lib.name()} couldn't go through the book: {ex}")


def cast(job, chapters, cache):
    f = cache / "cast.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf8"))
    opening, n = [], 0
    for c in chapters:
        for kind, text, *_ in c["paras"]:
            if kind != "b":
                opening.append(text)
                n += len(text.split())
        if n > 6000:
            break
    prompt = (f"Book: {job['title']}" + (f" by {job['author']}" if job.get("author") else "") +
              f"\nChapters: {', '.join(c['title'] for c in chapters)[:1500]}\n\n"
              "Here is the opening of the book. Say whether it is told in the first person and by "
              "whom, list the characters who speak or are likely to speak (gender, rough age, and "
              "their manner of speaking in a few words, like \"gruff and impatient\" or \"soft, "
              "hesitant\"), and "
              "the unusual names or words to pronounce carefully. Notes: one or two sentences on the "
              "book's tone for the reader.\n\n" + "\n\n".join(opening))
    data = _ask(prompt, CAST_SCHEMA)
    f.write_text(json.dumps(data, indent=1), encoding="utf8")
    return data


# ---------------------------------------------------------------------------
# Names: how to say them, looked up (Lauren, 2026-11-06: "when there are names, look up how to
# pronounce"). The answer is in the voice's own sound symbols, so Kokoro says it exactly (a
# lexicon file read before its own), not a respelling it has to guess at.
# ---------------------------------------------------------------------------
NAMES_MAX = 220
# Kokoro's sounds (misaki): one symbol each, the double vowels are capitals
SOUND_HELP = """"sounds" is the word in the voice's phonetic alphabet, one symbol per sound, separated by
spaces, with ˈ before the stressed syllable's vowel (ˌ for a secondary stress). Vowels: æ (cat)
ɑ (father) ɛ (bed) ɪ (sit) i (see) ʊ (book) u (food) ʌ (cup) ə (about) ɜ ɹ (bird) ɔ (law)
A (day) I (my) O (go) W (now) Y (boy). Consonants: p b t d k ɡ f v θ (thin) ð (this) s z ʃ (she)
ʒ (vision) h ʧ (church) ʤ (judge) m n ŋ (sing) l ɹ (red) j (yes) w. Examples from the voice's
own list: Arizona = ˌ ɛ ɹ ə z ˈ O n ə ; Sedona = s ɪ d ˈ O n ə ; Hopi = h ˈ O p i ;
Marilla = m ə ɹ ˈ ɪ l ə ; Siobhan = ʃ ə v ˈ ɔ n ."""

NAMES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["words"],
    "properties": {"words": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["word", "sounds", "say", "looked_up", "tricky", "note"],
        "properties": {"word": {"type": "string"}, "sounds": {"type": "string"},
                       "say": {"type": "string"}, "looked_up": {"type": "boolean"},
                       "tricky": {"type": "boolean"},
                       "note": {"type": "string"}}}}}}

_SENT_START = re.compile(r'(^|[.!?…:]["”’)]*\s+["“‘(]*|^["“‘(]+)$')


def name_candidates(chapters):
    """{word: (count, example)}: names (capitalised other than at a sentence start) and words the
    voice doesn't know, most used first."""
    known = R.known_words()
    found = {}
    for c in chapters:
        for kind, text, *_ in c["paras"]:
            if kind == "b":
                continue
            for m in re.finditer(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*[A-Za-zÀ-ÿ]", text):
                w = re.sub(r"['’]s$", "", m.group(0))
                low = w.lower()
                if w[0].isupper():
                    if _SENT_START.search(text[:m.start()]) and low in known:
                        continue        # an ordinary word starting a sentence
                    if w.isupper() and len(w) > 1 and low in known:
                        continue        # shouting, not a name
                elif not known or low in known or low.rstrip("s") in known or any(
                        low.endswith(x) and low[:-len(x)] in known for x in ("ed", "d", "ing", "ly", "er")):
                    continue
                n, ex = found.get(w, (0, ""))
                if not ex:
                    a = max(0, m.start() - 90)
                    ex = text[a:m.end() + 90].replace("\n", " ")
                found[w] = (n + 1, ex)
    # a name used once at a sentence start is usually just an ordinary capital
    out = {w: v for w, v in found.items() if v[0] >= 2 or w.lower() not in known}
    return dict(sorted(out.items(), key=lambda kv: -kv[1][0])[:NAMES_MAX])


def names(job, chapters, cast_data, cache):
    """Look up how to say the book's names and unusual words (cached)."""
    f = cache / "names.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf8"))
    cands = name_candidates(chapters)
    if not cands:
        data = {"words": []}
        f.write_text(json.dumps(data), encoding="utf8")
        return data
    lib = cc()
    web = lib.PROVIDER == "claude"
    lines = [f"- {w} (used {n}x): …{ex}…" for w, (n, ex) in cands.items()]
    prompt = (f"Book: {job['title']}" + (f" by {job['author']}" if job.get("author") else "") +
              f"\nTone and setting: {cast_data.get('notes', '')}\n\n"
              "Below are the names and unusual words in this book, each with where it is used. For "
              "each one, work out how it is really pronounced. " +
              ("Search the web for the ones you aren't sure of: real places, people, and words from "
               "other languages (say them the way people there do), and for made-up names look for the "
               "author's own guidance or the audiobook of this book. " if web else
               "For real places, people and words from other languages, say them the way people there "
               "do; for made-up names, the most natural reading or the author's own guidance. ") +
              "Leave out ordinary English words and common names an American voice already says right "
              "(John, Sarah, London). looked_up is true if you confirmed it rather than guessed. "
              "tricky is true only if a good American reader would likely say it wrong from the "
              "spelling alone (Tlaquepaque, Siobhan, Oraibi: yes; Marilla, Sedona, Celia: no). say "
              "is a plain respelling with the stressed syllable in capitals (muh-RIL-uh).\n\n" +
              SOUND_HELP + "\n\n" + "\n".join(lines))
    try:
        data = lib.run(prompt, SYSTEM, schema=NAMES_SCHEMA, timeout=1800,
                       tools="WebSearch" if web else "")["data"]
    except lib.ClaudeError as ex:
        raise RuntimeError(f"{lib.name()} couldn't look up the names: {ex}")
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf8")
    return data


def _voice_sounds():
    try:
        return {line.split(" ", 1)[0] for line in
                (R.model_dir() / "tokens.txt").read_text(encoding="utf8").splitlines() if line.strip()}
    except OSError:
        return set()


def _base_sounds():
    """{word: sounds} from the voice's American list (to see if a lookup changes anything)."""
    out = {}
    try:
        with open(R.model_dir() / "lexicon-us-en.txt", encoding="utf8") as fh:
            for line in fh:
                w, _, s = line.rstrip("\n").partition(" ")
                out.setdefault(w, s)
    except OSError:
        pass
    return out


def names_lexicon(data):
    """{word (lower case): sounds} the voice should use instead of its own guess. Only sounds made
    of the voice's own symbols; a name the voice already knows is changed only if it was looked up."""
    ok = _voice_sounds()
    base = _base_sounds() if ok else {}
    out = {}
    for x in data.get("words", []):
        w = (x.get("word") or "").strip().lower()
        s = " ".join((x.get("sounds") or "").replace("/", " ").split())
        if not w or " " in w or not s or (ok and any(t not in ok for t in s.split())):
            continue
        if not any(t in s for t in "ˈˌ"):
            continue
        mine = base.get(w)
        if (mine or w in R.known_words()) and not x.get("looked_up"):
            continue                    # the voice knows it: a guess won't do better
        if mine and mine.replace(" ", "") == s.replace(" ", ""):
            continue
        out[w] = s
        last = s.split()[-1]
        out.setdefault(w + "'s", s + (" ɪ z" if last in ("s", "z", "ʃ", "ʒ", "ʧ", "ʤ") else
                                      " s" if last in ("p", "t", "k", "f", "θ") else " z"))
    return out


def write_lexicon(jobdir, lex):
    """The job's names list, read by the voice before its own (the first entry for a word wins)."""
    f = Path(jobdir) / "names-lexicon.txt"
    if lex:
        f.write_text("".join(f"{w} {s}\n" for w, s in sorted(lex.items())), encoding="utf8")
    else:
        f.unlink(missing_ok=True)
    return f if lex else None


def chunks_of(chapters):
    """[(chapter index, [paragraph indexes])] of about CHUNK_WORDS words, inside one chapter."""
    out = []
    for ci, c in enumerate(chapters):
        cur, n = [], 0
        for pi, (kind, text, *_) in enumerate(c["paras"]):
            if kind == "b":
                continue
            cur.append(pi)
            n += len(text.split())
            if n >= CHUNK_WORDS:
                out.append((ci, cur))
                cur, n = [], 0
        if cur:
            out.append((ci, cur))
    return out


def direct_chunk(job, chapters, cast_data, ci, pis, cache, k):
    f = cache / f"part{k:04d}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf8"))
    c = chapters[ci]
    names = ", ".join(f"{x['name']} ({x['gender']}, {x['age']})" for x in cast_data.get("characters", []))
    who = (f"The story is told in the first person by {cast_data.get('narrator_name') or 'the narrator'}."
           if cast_data.get("first_person") else "The story is told by a narrator (not a character).")
    lines = []
    for n, pi in enumerate(pis, 1):
        kind, text = c["paras"][pi][:2]
        lines.append(f"[{n}]{' (heading)' if kind == 'h' else ''} {text}")
    prompt = (f"Book: {job['title']}" + (f" by {job['author']}" if job.get("author") else "") +
              f"\n{who}\nCast: {names or 'not known yet'}\n"
              f"Tone: {cast_data.get('notes', '')}\n\n"
              f"This is part of \"{c['title']}\". Paragraphs are numbered. Direct them.\n\n" + "\n\n".join(lines))
    data = _ask(prompt, CHUNK_SCHEMA)
    data["_pis"] = pis
    data["_chapter"] = ci
    f.write_text(json.dumps(data, indent=1), encoding="utf8")
    return data


def direct(jobdir, progress=None, stop=None, paused=None):
    """Ask for the directions (or take them from the cache) and rewrite the job's chapters with
    them. Returns a short summary for the report."""
    say = progress or (lambda f, m: None)
    jobdir = Path(jobdir)
    job = json.loads((jobdir / "job.json").read_text(encoding="utf8"))
    chapters = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))
    lib = cc()
    if job.get("director") in lib.NAMES:     # for this book only (not saved as CleanListen's choice)
        lib.PROVIDER = job["director"]
    who = lib.name()
    cache = direction_dir() / book_key(job, chapters)
    cache.mkdir(parents=True, exist_ok=True)
    say(0.0, f"{who} is getting to know the book…")
    cast_data = cast(job, chapters, cache)
    say(0.02, f"{who} is looking up how to say the names…")
    try:
        names_data = names(job, chapters, cast_data, cache)
    except RuntimeError as ex:          # the book can still be read with the voice's own guesses
        names_data = {"words": [], "error": str(ex)}
    parts = chunks_of(chapters)
    results = [None] * len(parts)
    errors, lock, done = [], threading.Lock(), [0]
    todo = list(range(len(parts)))

    def loop():
        while not errors and not (stop and stop.is_set()):
            while paused and paused.is_set() and not (stop and stop.is_set()):
                time.sleep(0.25)            # Pause: no new part is asked for until Resume
            if stop and stop.is_set():
                return
            with lock:
                if not todo:
                    return
                k = todo.pop(0)
            ci, pis = parts[k]
            try:
                results[k] = direct_chunk(job, chapters, cast_data, ci, pis, cache, k)
            except Exception as ex:
                errors.append(ex)
                return
            with lock:
                done[0] += 1
                say(done[0] / len(parts), f"{who} is going through the book and marking how to read it… "
                                          f"part {done[0]} of {len(parts)}")

    threads = [threading.Thread(target=loop, daemon=True) for _ in range(min(AT_ONCE, len(parts)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    if stop and stop.is_set():
        raise R.Stopped()
    summary = apply(jobdir, job, chapters, cast_data, results, names_data)
    (jobdir / "directed.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    return summary


# ---------------------------------------------------------------------------
# Turning directions into what the voice reads
# ---------------------------------------------------------------------------
WOMEN = {"us": ["af_bella", "af_nicole", "af_sarah", "af_aoede", "af_heart"], "gb": ["bf_emma", "bf_isabella"]}
MEN = {"us": ["am_michael", "am_fenrir", "am_puck", "am_echo"], "gb": ["bm_george", "bm_fable", "bm_lewis"]}


def gpu_pool(gender, age, accent, narrator):
    """The graphics-card voices for a character, best match first (readaloud_gpu.GPU_VOICES)."""
    import readaloud_gpu as G
    want = {"child": ["child", "teen"], "teen": ["teen", "child"], "adult": ["adult", "young"],
            "older": ["older", "elderly"]}.get(age, ["adult", "young"])
    vs = [(k, v) for k, v in G.GPU_VOICES.items() if v[2] == gender and k != narrator]
    rank = lambda kv: (want.index(kv[1][3]) if kv[1][3] in want else 9, kv[1][4] != accent)
    return [k for k, v in sorted(vs, key=rank) if v[3] in want] or [k for k, _ in sorted(vs, key=rank)]


def cast_voices(job, cast_data, lines_by):
    """{character: voice}. The narrator keeps the chosen voice (and so does a first-person
    narrator's own speech); the others, most lines first, get the other voices of their accent
    (for the graphics-card readers, the best match for their age too)."""
    narrator = job["voice"]
    gpu = R.VOICE.get(narrator) is None
    if gpu:
        import readaloud_gpu as G
        accent = (G.GPU_VOICES.get(narrator) or G.GPU_VOICES[G.DEFAULT_GPU_VOICE])[4]
    else:
        accent = R.VOICE[narrator][4]
    people = {}
    for c in cast_data.get("characters", []):
        people.setdefault(norm_name(c["name"]), c)
    out = {}
    me = norm_name(cast_data.get("narrator_name", "")) if cast_data.get("first_person") else ""
    used = {"female": 0, "male": 0}
    for name in sorted(lines_by, key=lambda n: -lines_by[n]):
        if name in ("", "narrator") or name == me:
            out[name] = narrator
            continue
        g = (people.get(name) or {}).get("gender", "unknown")
        if gpu:
            pool = gpu_pool(g, (people.get(name) or {}).get("age", "adult"), accent, narrator)                 if g in ("female", "male") else []
            taken = set(out.values())
            pool = [v for v in pool if v not in taken] + [v for v in pool if v in taken]
            if pool:
                out[name] = pool[0]
                continue
        pool = [] if gpu else [v for v in (WOMEN if g == "female" else MEN if g == "male" else {})
                               .get(accent, []) if v != narrator]
        if not pool:
            out[name] = narrator
            continue
        out[name] = pool[used[g] % len(pool)]
        used[g] += 1
    return out


def norm_name(n):
    return " ".join(str(n or "").lower().split())


def apply(jobdir, job, chapters, cast_data, results, names_data=None):
    """Rewrite chapters.json with the directions; write the report. Returns the summary."""
    names_data = names_data or {"words": []}
    lex = names_lexicon(names_data)
    lexfile = write_lexicon(jobdir, lex)
    pron = {}
    for d in [cast_data] + [r for r in results if r]:
        for p in d.get("pronounce", []):
            w, s = p.get("word", "").strip(), p.get("say", "").strip().lower()
            # only words the voice doesn't know: it says "Sybil" and "Sedona" well, and a respelling
            # ("sib-ul") sounds worse; and not the ones looked up (said exactly, from the names list)
            if w.lower() in R.known_words() or w.lower() in lex:
                continue
            if w and s and len(pron) < 60 and re.fullmatch(r"[a-z' -]+", s):
                pron.setdefault(w, s)
    lines_by = {}
    plan = {}          # (chapter, para) -> direction
    for r in results:
        if not r:
            continue
        pis = r["_pis"]
        for p in r.get("paragraphs", []):
            n = p.get("n")
            if isinstance(n, int) and 1 <= n <= len(pis):
                plan[(r["_chapter"], pis[n - 1])] = p
                for s in p.get("speakers") or []:
                    lines_by[norm_name(s)] = lines_by.get(norm_name(s), 0) + 1
    voices = cast_voices(job, cast_data, lines_by) if job.get("cast") else {}
    said = {}
    for x in names_data.get("words", []):
        w = (x.get("word") or "").strip()
        if w.lower() in lex:
            said[w] = (x.get("say") or "").strip() + ("" if x.get("looked_up") else " (best guess)")
    report = {"skipped": [], "fixed": [], "ignored": [], "voices": voices, "pronounce": pron,
              "said": said, "names_error": names_data.get("error", "")}
    for ci, c in enumerate(chapters):
        out = []
        for pi, item in enumerate(c["paras"]):
            kind, text = item[0], item[1]
            p = plan.get((ci, pi))
            if kind == "b" or not p:
                out.append([kind, text])
                continue
            if p.get("skip"):
                if len(text.split()) <= SKIP_MOST:
                    report["skipped"].append(f"{c['title']}: {text}")
                    continue
                report["ignored"].append(f"{c['title']} (kept, too long to leave out): {text[:200]}")
            fix = R.speakable(p.get("fix") or "")
            if fix and fix != text:
                if same_words(text, fix):
                    report["fixed"].append(f"{c['title']}: {text}\n    -> {fix}")
                    text = fix
                elif only_removed(text, fix):
                    # part of a paragraph that isn't the story (Lauren's script: the cast list in the
                    # title line, "Melissa whispered, Melissa:"); as much as a whole paragraph may be
                    report["skipped"].append(f"{c['title']} (from a paragraph): {only_removed(text, fix)}")
                    text = fix
                else:
                    report["ignored"].append(f"{c['title']} (a change that wasn't only a fix): {fix[:200]}")
            opts = {"x": p.get("feel") if p.get("feel") in ("calm", "strong") else "warm"}
            speed = PACE.get(p.get("pace"), 1.0)
            if speed != 1.0:
                opts["s"] = speed
            if p.get("pause") in PAUSE:
                opts["g"] = PAUSE[p["pause"]]
            speakers = [norm_name(s) for s in p.get("speakers") or []]
            pieces = split_quotes(text) if voices and speakers and kind == "p" else [(False, text)]
            notes = [str(x) for x in p.get("speech_delivery") or []]
            q = 0
            runs = []           # [voice, text, acting note, who]: next pieces in the same voice are
            for speech, piece in pieces:    # read in one go, so "I'm all right," I said. "I'm listening." flows
                v, note, who = job["voice"], p.get("delivery", ""), ""
                if speech:
                    who = speakers[min(q, len(speakers) - 1)]
                    v = voices.get(who, job["voice"])
                    note = notes[q] if q < len(notes) and notes[q] else note
                    q += 1
                if runs and runs[-1][0] == v:
                    runs[-1][1] += " " + piece
                else:
                    runs.append([v, piece, note, who])
            for j, (v, piece, note, who) in enumerate(runs):
                o = dict(opts) if j == 0 else {k: opts[k] for k in ("s", "x") if k in opts}
                if j:
                    o["g"] = PART_GAP
                if v != job["voice"]:
                    o["v"] = v
                if note:
                    o["m"] = note.strip()[:120]
                if who and v != job["voice"]:
                    o["who"] = who
                out.append([kind, piece, o])
        c["paras"] = out
        c["words"] = sum(len(i[1].split()) for i in out)
    (jobdir / "chapters.json").write_text(json.dumps(chapters), encoding="utf8")
    job["pronounce"] = pron
    job["lexicon"] = str(lexfile) if lexfile else ""
    # the graphics-card voices can't take sounds: they get a respelling, only for the names a reader
    # would trip on ("Tlaquepaque" -> "tlah-kuh-pah-kay"); "Marilla" respelled "muh-ril-uh" came
    # out "Mafrilla", and they say ordinary names well as written
    job["respell"] = {}
    for x in names_data.get("words", []):
        w, say = (x.get("word") or "").strip(), (x.get("say") or "").strip().lower()
        if w and x.get("tricky") and re.fullmatch(r"[a-z' -]+", say) and say.replace("-", "") != w.lower():
            job["respell"][w] = say
    job["manners"] = {norm_name(c.get("name")): c.get("manner", "") for c in cast_data.get("characters", [])
                      if c.get("manner")}
    (jobdir / "job.json").write_text(json.dumps(job, indent=1), encoding="utf8")
    write_report(jobdir, job, cast_data, report)
    return {"skipped": len(report["skipped"]), "fixed": len(report["fixed"]), "voices": voices,
            "pronounce": len(pron), "names": len([w for w in lex if not w.endswith("'s")])}


def voice_name(v):
    if v in R.VOICE:
        return R.VOICE[v][2]
    import readaloud_gpu as G
    return (G.GPU_VOICES.get(v) or (v,))[0].split(" - ")[0]


def write_report(jobdir, job, cast_data, rep):
    who = provider_name(job.get("director"))
    lines = [f"{job['title']} — what {who} changed before ReadAloud read it", "",
             f"Told {'in the first person by ' + cast_data.get('narrator_name', '') if cast_data.get('first_person') else 'by a narrator'}.",
             cast_data.get("notes", ""), ""]
    if rep["voices"]:
        lines += ["Voices:"] + [f"  {n or 'narrator'}: {voice_name(v)}" for n, v in rep["voices"].items()] + [""]
    if rep.get("said"):
        lines += ["Names, as looked up:"] + [f"  {w}: {s}" for w, s in rep["said"].items()] + [""]
    if rep.get("names_error"):
        lines += ["The names weren't looked up: " + rep["names_error"], ""]
    if rep["pronounce"]:
        lines += ["Said as:"] + [f"  {w} -> {s}" for w, s in rep["pronounce"].items()] + [""]
    lines += [f"Left out ({len(rep['skipped'])}):"] + [f"  {t}" for t in rep["skipped"]] + [""]
    lines += [f"Scanning mistakes fixed ({len(rep['fixed'])}):"] + [f"  {t}" for t in rep["fixed"]] + [""]
    if rep["ignored"]:
        lines += [f"Suggestions ReadAloud didn't take ({len(rep['ignored'])}):"] + [f"  {t}" for t in rep["ignored"]]
    (Path(jobdir) / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf8")


def pronounce(text, pron):
    """Say unusual names the way the director spelled them out."""
    for w, s in (pron or {}).items():
        text = re.sub(r"(?<![\w'])" + re.escape(w) + r"(?![\w'])", s, text)
    return text
