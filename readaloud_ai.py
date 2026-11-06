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
words it is given, in one even tone; it can change voice for a character, speed up or slow down,
and pause, but it cannot act out emotions on request.

The text came from an ebook, sometimes a scanned printed book, so it can contain things that
must not be read aloud: page numbers, the book's title or author repeated at the top of pages,
jacket or flap text, publisher's lists, "continued on back flap", footnote markers, garbage
characters from scanning. Scanning also leaves mistakes: words glued together or split,
letters misread ("fiat" for "flat", "/" for "I", "1" for "I", stray commas).

Rules:
- Never change the story's words, never summarize, never censor. A fix only repairs scanning
  or typing mistakes; the corrected paragraph must say the same thing word for word.
- "skip" only for text that is clearly not part of the book's text (page furniture, jacket
  copy, scanning garbage). Front matter like a dedication is part of the book: keep it.
- Speakers: for each quoted speech in a paragraph ("..." pairs, in order), name who says it,
  using the names from the cast list. If the narrator is a character telling the story in the
  first person, their own speech is spoken by that character's name. If you can't tell, use
  "narrator". A speech continuing from the previous paragraph (opening quote, no closing quote
  before) counts as a quoted speech too.
- Pace "slower" for tender, sad, solemn or suspenseful moments; "faster" for urgent, excited or
  angry ones; otherwise "normal". Use it sparingly, as a good human narrator would.
- Pause "scene" before a paragraph that starts a new scene (a time or place jump), "long" for a
  dramatic beat, "short" to run on quickly; otherwise "normal".
- List ONLY paragraphs that need something: a skip, a fix, quoted speech, or a pace or pause
  that isn't normal. Leave plain narration paragraphs out of the list.
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
            "required": ["name", "gender", "age"],
            "properties": {"name": {"type": "string"},
                           "gender": {"type": "string", "enum": ["female", "male", "unknown"]},
                           "age": {"type": "string", "enum": ["child", "teen", "adult", "older"]}}}},
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
            "required": ["n", "skip", "fix", "pause", "pace", "mood", "speakers"],
            "properties": {
                "n": {"type": "integer"},
                "skip": {"type": "boolean"},
                "fix": {"type": "string"},
                "pause": {"type": "string", "enum": ["normal", "short", "long", "scene"]},
                "pace": {"type": "string", "enum": ["slower", "normal", "faster"]},
                "mood": {"type": "string"},
                "speakers": {"type": "array", "items": {"type": "string"}}}}},
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
def book_key(job, chapters):
    text = json.dumps([c["paras"] for c in chapters])
    return hashlib.sha1((job.get("director", "") + "|" + text).encode("utf8")).hexdigest()[:16]


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
              "whom, list the characters who speak or are likely to speak (gender and rough age), and "
              "the unusual names or words to pronounce carefully. Notes: one or two sentences on the "
              "book's tone for the reader.\n\n" + "\n\n".join(opening))
    data = _ask(prompt, CAST_SCHEMA)
    f.write_text(json.dumps(data, indent=1), encoding="utf8")
    return data


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


def direct(jobdir, progress=None, stop=None):
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
    parts = chunks_of(chapters)
    results = [None] * len(parts)
    errors, lock, done = [], threading.Lock(), [0]
    todo = list(range(len(parts)))

    def loop():
        while not errors and not (stop and stop.is_set()):
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
    summary = apply(jobdir, job, chapters, cast_data, results)
    (jobdir / "directed.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    return summary


# ---------------------------------------------------------------------------
# Turning directions into what the voice reads
# ---------------------------------------------------------------------------
WOMEN = {"us": ["af_bella", "af_nicole", "af_sarah", "af_aoede", "af_heart"], "gb": ["bf_emma", "bf_isabella"]}
MEN = {"us": ["am_michael", "am_fenrir", "am_puck", "am_echo"], "gb": ["bm_george", "bm_fable", "bm_lewis"]}


def cast_voices(job, cast_data, lines_by):
    """{character: voice}. The narrator keeps the chosen voice (and so does a first-person
    narrator's own speech); the others, most lines first, get the other voices of their accent."""
    narrator = job["voice"]
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
        pool = [v for v in (WOMEN if g == "female" else MEN if g == "male" else {})
                .get(accent, []) if v != narrator]
        if not pool:
            out[name] = narrator
            continue
        out[name] = pool[used[g] % len(pool)]
        used[g] += 1
    return out


def norm_name(n):
    return " ".join(str(n or "").lower().split())


def apply(jobdir, job, chapters, cast_data, results):
    """Rewrite chapters.json with the directions; write the report. Returns the summary."""
    pron = {}
    for d in [cast_data] + [r for r in results if r]:
        for p in d.get("pronounce", []):
            w, s = p.get("word", "").strip(), p.get("say", "").strip().lower()
            # only words the voice doesn't know: it says "Sybil" and "Sedona" well, and a respelling
            # ("sib-ul") sounds worse
            if w.lower() in R.known_words():
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
    report = {"skipped": [], "fixed": [], "ignored": [], "voices": voices, "pronounce": pron}
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
                else:
                    report["ignored"].append(f"{c['title']} (a change that wasn't only a fix): {fix[:200]}")
            opts = {}
            speed = PACE.get(p.get("pace"), 1.0)
            if speed != 1.0:
                opts["s"] = speed
            if p.get("pause") in PAUSE:
                opts["g"] = PAUSE[p["pause"]]
            speakers = [norm_name(s) for s in p.get("speakers") or []]
            pieces = split_quotes(text) if voices and speakers and kind == "p" else [(False, text)]
            q = 0
            for j, (speech, piece) in enumerate(pieces):
                o = dict(opts) if j == 0 else ({"s": opts["s"]} if "s" in opts else {})
                if j:
                    o["g"] = PART_GAP
                if speech:
                    who = speakers[min(q, len(speakers) - 1)]
                    q += 1
                    v = voices.get(who, job["voice"])
                    if v != job["voice"]:
                        o["v"] = v
                out.append([kind, piece, o] if o else [kind, piece])
        c["paras"] = out
        c["words"] = sum(len(i[1].split()) for i in out)
    (jobdir / "chapters.json").write_text(json.dumps(chapters), encoding="utf8")
    job["pronounce"] = pron
    (jobdir / "job.json").write_text(json.dumps(job, indent=1), encoding="utf8")
    write_report(jobdir, job, cast_data, report)
    return {"skipped": len(report["skipped"]), "fixed": len(report["fixed"]), "voices": voices,
            "pronounce": len(pron)}


def write_report(jobdir, job, cast_data, rep):
    who = provider_name(job.get("director"))
    lines = [f"{job['title']} — what {who} changed before ReadAloud read it", "",
             f"Told {'in the first person by ' + cast_data.get('narrator_name', '') if cast_data.get('first_person') else 'by a narrator'}.",
             cast_data.get("notes", ""), ""]
    if rep["voices"]:
        lines += ["Voices:"] + [f"  {n or 'narrator'}: {R.VOICE[v][2]}" for n, v in rep["voices"].items()] + [""]
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
