#!/usr/bin/env python3
"""
ReadAloud's engine: turns an ebook you own (EPUB, PDF, Word or text) into an audiobook, read by
a natural-sounding voice that runs on this PC (Kokoro, through sherpa-onnx, the same speech
engine CleanListen uses). Free, offline, no account.

Lauren, 2026-11-04: "there are some books I have that they didn't make audiobooks for... I don't
want stilted computer voices... but I also don't want to pay $100 per."

How it works:
  load_book()   the book's title, author, cover, series and chapters (CleanRead's reader)
  start_job()   a job folder in APP_DATA/readaloud/<key> with the chapters' text and settings
  Maker         reads the chapters in several worker processes at once (`speak`), one
                chapter file each (AAC), so a closed window or a crash carries on where it was
  assemble()    joins the chapter files into one M4B with chapters, tags and cover (no
                re-encoding), and optionally MP3 chapter files (for a Yoto)

Command line (for testing):
  python readaloud.py info BOOK.epub
  python readaloud.py make BOOK.epub [--voice af_heart] [--out FOLDER] [--chapters 1-3]
  python readaloud.py speak JOBDIR CHAPTER THREADS      (one worker; used by Maker)
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
JOBS = APP_DATA / "readaloud"

MODEL_NAME = "kokoro-multi-lang-v1_0"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
             f"{MODEL_NAME}.tar.bz2")
MODEL_MB = 334
SR = 24000
BITRATE = "64k"          # one voice, mono: 64k AAC sounds the same as the original

# The English voices worth listening to (Kokoro's own quality grades: Heart and Bella are its
# best; the men's voices are a step below). (id in the model, name shown, what it sounds like,
# accent). The ids are the model's speaker numbers (its id2speaker table).
VOICES = [
    ("af_heart", 3, "Heart", "American woman, warm (the best voice)", "us"),
    ("af_bella", 2, "Bella", "American woman, bright", "us"),
    ("af_nicole", 6, "Nicole", "American woman, soft and close", "us"),
    ("af_sarah", 9, "Sarah", "American woman, plain", "us"),
    ("af_aoede", 1, "Aoede", "American woman, gentle", "us"),
    ("am_michael", 16, "Michael", "American man, steady", "us"),
    ("am_fenrir", 14, "Fenrir", "American man, deep", "us"),
    ("am_puck", 18, "Puck", "American man, lively", "us"),
    ("am_echo", 12, "Echo", "American man, calm", "us"),
    ("bf_emma", 21, "Emma", "British woman, warm", "gb"),
    ("bf_isabella", 22, "Isabella", "British woman, clear", "gb"),
    ("bm_george", 26, "George", "British man, older", "gb"),
    ("bm_fable", 25, "Fable", "British man, storyteller", "gb"),
    ("bm_lewis", 27, "Lewis", "British man, deep", "gb"),
]
VOICE = {v[0]: v for v in VOICES}
DEFAULT_VOICE = "af_heart"
SPEEDS = {"Slower": 0.9, "Normal": 1.0, "A bit faster": 1.1, "Faster": 1.2}

# Pauses, in seconds
GAP_SENTENCE = 0.18
GAP_PARA = 0.55
GAP_HEADING = 1.0
GAP_BREAK = 1.4          # a "* * *" scene break
LEAD_IN, TAIL = 0.6, 1.6  # silence at the start and end of each chapter

_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


class BookError(Exception):
    pass


# ---------------------------------------------------------------------------
# Tools and the voice model
# ---------------------------------------------------------------------------
def tool(name):
    local = HERE / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is missing. Run the CleanListen installer again.")
    return found


def model_dir():
    return Path(os.environ.get("READALOUD_MODEL") or HERE / "models" / MODEL_NAME)


def have_model():
    if os.environ.get("READALOUD_FAKE_VOICE"):
        return True
    d = model_dir()
    return all((d / f).exists() for f in ("model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt",
                                          "lexicon-gb-en.txt", "espeak-ng-data"))


def get_model(progress=None, stop=None):
    """Download the voices (about 334 MB, once). progress(fraction, message)."""
    if have_model():
        return
    say = progress or (lambda f, m: None)
    import urllib.request
    dest = model_dir().parent
    dest.mkdir(parents=True, exist_ok=True)
    dl = APP_DATA / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    tarball = dl / f"{MODEL_NAME}.tar.bz2"
    part = tarball.with_suffix(".part")
    if not tarball.exists():
        req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "ReadAloud"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or MODEL_MB * 1024 * 1024)
            got = 0
            while True:
                if stop is not None and stop.is_set():
                    raise Stopped()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                say(0.95 * got / total, f"Getting the voices (once): {got >> 20} of {total >> 20} MB")
        os.replace(part, tarball)
    say(0.96, "Unpacking the voices…")
    tmp = dest / ("~unpacking~" + MODEL_NAME)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    ok = False
    if os.name == "nt" and tar.exists():
        ok = subprocess.run([str(tar), "-xjf", str(tarball), "-C", str(tmp)], capture_output=True,
                            **_NOWIN).returncode == 0
    if not ok:
        import tarfile
        with tarfile.open(tarball, "r:bz2") as t:
            t.extractall(tmp, filter="data")
    inner = tmp / MODEL_NAME
    shutil.rmtree(model_dir(), ignore_errors=True)
    os.replace(inner if inner.exists() else tmp, model_dir())
    shutil.rmtree(tmp, ignore_errors=True)
    if not have_model():
        tarball.unlink(missing_ok=True)
        raise RuntimeError("The voices didn't unpack properly. Try again.")
    tarball.unlink(missing_ok=True)
    say(1.0, "The voices are ready.")


_TTS = {}
_TTS_LOCK = threading.Lock()


class _ToneVoice:
    """A stand-in voice for tests (READALOUD_FAKE_VOICE=1): a short tone per word."""

    class _Audio:
        def __init__(self, samples):
            self.samples, self.sample_rate = samples, SR

    def generate(self, text, sid=0, speed=1.0):
        import numpy as np
        n = int(SR * 0.08 * max(1, len(text.split())) / speed)
        t = np.arange(n, dtype=np.float32) / SR
        return self._Audio(0.3 * np.sin(2 * np.pi * (200 + 10 * sid) * t))


def voice_engine(accent="us", threads=4, names=""):
    """The speech engine for an accent (American or British pronunciations), made once. names: a
    book's own list of how to say its names (readaloud_ai), read before the voice's own list."""
    if os.environ.get("READALOUD_FAKE_VOICE"):
        return _ToneVoice()
    import sherpa_onnx as so
    names = names if names and Path(names).exists() else ""
    key = (accent, threads, names)
    with _TTS_LOCK:
        if key not in _TTS:
            d = model_dir()
            # espeak-ng has no "en-gb" here (every British line came out silent); its "en" is British
            lex, lang = (("lexicon-gb-en.txt", "en") if accent == "gb" else ("lexicon-us-en.txt", "en-us"))
            cfg = so.OfflineTtsConfig(
                model=so.OfflineTtsModelConfig(
                    kokoro=so.OfflineTtsKokoroModelConfig(
                        model=str(d / "model.onnx"), voices=str(d / "voices.bin"),
                        tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data"),
                        lexicon=(names + "," if names else "") + str(d / lex), lang=lang),
                    num_threads=threads, provider="cpu"),
                max_num_sentences=1)
            _TTS[key] = so.OfflineTts(cfg)
        return _TTS[key]


# ---------------------------------------------------------------------------
# Getting text ready to be read aloud
# ---------------------------------------------------------------------------
ROMAN = re.compile(r"^(?=[MDCLXVI])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
ROMAN_AFTER = re.compile(r"\b(chapter|part|book|volume|act|section)\s+([MDCLXVI]+)\b", re.I)
CAPS_WORD = re.compile(r"\b[A-Z][A-Z']{3,}\b")
BREAK_RE = re.compile(r"^[\s*#~•·◆◇♦❖⁂—–\-_=+o0]{1,20}$")
URL = re.compile(r"https?://\S+|www\.\S+")


def roman_to_int(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        total += -v if b != " " and vals.get(b, 0) > v else v
    return total


def speakable(text):
    """Text as it should be read: plain quotes and dashes, "Chapter IV" as "Chapter 4", words in
    capitals read as words (not spelled out), no web addresses or footnote numbers."""
    t = " ".join(str(text).split())
    if not t:
        return ""
    t = (t.replace("“", '"').replace("”", '"').replace("„", '"').replace("‘", "'").replace("’", "'")
         .replace("\u00ad", "").replace("\u200b", "").replace("…", "...").replace("\u00a0", " "))
    t = re.sub(r"\s*[—―]\s*|\s+–\s+|\s--\s|(?<=\w)--(?=\w)", ", ", t)   # dashes are a short pause
    t = re.sub(r",\s*([.!?])", r"\1", t)
    t = re.sub(r"^,\s*", "", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = URL.sub("", t)
    t = re.sub(r"\[\d{1,3}\]", "", t)
    t = ROMAN_AFTER.sub(lambda m: f"{m.group(1)} {roman_to_int(m.group(2).upper())}"
                        if ROMAN.match(m.group(2).upper()) else m.group(0), t)
    if t.isupper() and len(t) < 80:        # a heading in capitals: "CHAPTER ONE"
        t = title_case(t)
    else:
        t = CAPS_WORD.sub(lambda m: m.group(0).capitalize() if m.group(0) not in KEEP_CAPS else m.group(0), t)
    return " ".join(t.split()).strip(" ,")


# Short capitals that are read as letters, and long ones that are acronyms read as words
KEEP_CAPS = {"NASA", "NATO", "UNICEF", "AIDS", "OPEC", "FIFA", "NASCAR", "SCUBA", "LASER", "RADAR",
             "USSR", "YMCA", "NAACP", "ASAP", "HTML", "FBI'S", "CIA'S"}

SENT_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])")
ABBR = re.compile(r"\b(Mr|Mrs|Ms|Dr|St|Jr|Sr|Prof|Capt|Col|Gen|Lt|Sgt|Rev|Fr|Mt|vs|etc|No|Messrs|Mme|"
                  r"Hon|Gov|Sen|Rep|Pres|Ave|Co|Inc|Ltd|[A-Z])\.$")
MAX_CHUNK = 280


def sentences(text):
    """Split a paragraph into sentences (not after "Mr." or an initial)."""
    out, start = [], 0
    for m in SENT_END.finditer(text):
        piece = text[start:m.start()].rstrip()
        if ABBR.search(piece.rstrip("\"')]")):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def chunks(text, limit=MAX_CHUNK):
    """Pieces short enough for the voice (it can only take so much at once): sentences, and a
    very long sentence split at its commas, semicolons or dashes."""
    out = []
    for s in sentences(text):
        while len(s) > limit:
            cut = max(s.rfind(c, 0, limit) for c in (", ", "; ", ": ", " ("))
            if cut < limit // 3:
                cut = s.rfind(" ", 0, limit)
            if cut <= 0:
                break
            out.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Reading the book
# ---------------------------------------------------------------------------
SKIP_TITLES = re.compile(
    r"^\s*(table of )?contents\s*$|^\s*copyright|^\s*(also|other books|more books) by\b|^\s*by the same author"
    r"|^\s*praise for\b|^\s*about the publisher|^\s*(sign up|newsletter|get (your )?free)|^\s*index\s*$"
    r"|^\s*cover\s*$|^\s*title page\s*$|^\s*half title|^\s*frontispiece|^\s*imprint\s*$"
    r"|^\s*(a )?note on the (type|text)|^\s*credits\s*$|^\s*landmarks\s*$|^\s*(list of )?illustrations\s*$"
    r"|project gutenberg|gutenberg.*licen[cs]e|^\s*the full .*licen[cs]e", re.I)
LICENSE = re.compile(r"project gutenberg|licen[cs]e", re.I)


def title_case(s):
    """"CHAPTER I. THE KEY" -> "Chapter I. The Key" (Roman numbers stay; "WON'T" -> "Won't")."""
    small = {"a", "an", "the", "and", "but", "or", "of", "to", "in", "on", "at", "by", "for", "with"}
    out = []
    for k, w in enumerate(s.split()):
        core = w.strip("\"'“”‘’.,:;!?()")
        prev = out[-1].lower().strip(".,:") if out else ""
        if core == "I" or (ROMAN.match(core) and prev in ("chapter", "part", "book", "volume", "act")):
            out.append(w)
            continue
        lead = len(w) - len(w.lstrip("\"'“”‘’("))
        w = w[:lead] + w[lead:lead + 1].upper() + w[lead + 1:].lower()
        if k and w.lower() in small and not out[-1].endswith((".", ":")):
            w = w.lower()
        out.append(w)
    return " ".join(out)


def _calibre_meta(opf, name):
    m = re.search(r"<meta\b[^>]*name\s*=\s*[\"']calibre:" + name + r"[\"'][^>]*>", opf)
    if not m:
        return ""
    c = re.search(r"content\s*=\s*[\"']([^\"']*)", m.group(0))
    return html.unescape(c.group(1)).strip() if c else ""


def _epub_extras(path):
    """(cover bytes, cover extension, series, number) from an EPUB's package file."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None, "", "", ""
    with z:
        names = z.namelist()
        try:
            container = z.read("META-INF/container.xml").decode("utf8", "ignore")
            opf_path = re.search(r'full-path\s*=\s*"([^"]+)"', container).group(1)
            opf = z.read(opf_path).decode("utf8", "ignore")
        except (KeyError, AttributeError):
            return None, "", "", ""
        base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
        items = []
        for tag in re.findall(r"<item\b[^>]*>", opf):
            d = {}
            for k in ("id", "href", "media-type", "properties"):
                m = re.search(r"\b" + k + r"""\s*=\s*["']([^"']*)["']""", tag)
                d[k] = m.group(1) if m else ""
            items.append(d)
        series = _calibre_meta(opf, "series")
        number = _calibre_meta(opf, "series_index")
        if not series:   # EPUB 3
            m = re.search(r"<meta\b[^>]*property\s*=\s*[\"']belongs-to-collection[\"'][^>]*>(.*?)</meta>", opf, re.S)
            if m:
                series = html.unescape(m.group(1)).strip()
                n = re.search(r"property\s*=\s*[\"']group-position[\"'][^>]*>(.*?)</meta>", opf, re.S)
                number = n.group(1).strip() if n else ""
        number = re.sub(r"\.0+$", "", number or "")
        # the cover: EPUB 3's cover-image, EPUB 2's <meta name="cover">, else a picture named cover
        cover = next((it for it in items if "cover-image" in it["properties"].split()), None)
        if not cover:
            m = re.search(r"<meta\b[^>]*name\s*=\s*[\"']cover[\"'][^>]*>", opf)
            cid = re.search(r"content\s*=\s*[\"']([^\"']+)", m.group(0)).group(1) if m else None
            cover = next((it for it in items if cid and it["id"] == cid
                          and it["media-type"].startswith("image/")), None)
        if not cover:
            cover = next((it for it in items if it["media-type"].startswith("image/")
                          and "cover" in (it["id"] + it["href"]).lower()), None)
        data, ext = None, ""
        if cover:
            href = str(PurePosixPath(base) / cover["href"]) if base else cover["href"]
            parts = []
            for seg in href.replace("%20", " ").split("/"):
                if seg == "..":
                    parts and parts.pop()
                elif seg not in ("", "."):
                    parts.append(seg)
            href = "/".join(parts)
            if href in names:
                data = z.read(href)
                ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
        return data, ext, series, number


def _read_docx(path):
    """(title, author, [(heading?, text)]) of a Word file."""
    try:
        with zipfile.ZipFile(path) as z:
            doc = z.read("word/document.xml").decode("utf8", "ignore")
            core = z.read("docProps/core.xml").decode("utf8", "ignore") if "docProps/core.xml" in z.namelist() else ""
    except (zipfile.BadZipFile, KeyError, OSError):
        raise BookError("This Word file can't be opened. (Only .docx works; save an older .doc as .docx.)")
    t = re.search(r"<dc:title>(.*?)</dc:title>", core, re.S)
    a = re.search(r"<dc:creator>(.*?)</dc:creator>", core, re.S)
    paras = []
    for p in re.findall(r"<w:p\b.*?</w:p>", doc, re.S):
        style = re.search(r"<w:pStyle w:val=\"([^\"]+)\"", p)
        heading = bool(style and re.match(r"(heading|title)", style.group(1), re.I))
        p = re.sub(r"<w:(tab|br|cr)\b[^>]*/>", " ", p)
        text = html.unescape("".join(re.findall(r"<w:t\b[^>]*>(.*?)</w:t>", p, re.S)))
        if text.strip():
            paras.append((heading, text))
    return (html.unescape(t.group(1)).strip() if t else "", html.unescape(a.group(1)).strip() if a else "", paras)


# ---------------------------------------------------------------------------
# PDFs: pages, not a story. Lauren's Vermilion.pdf (a 1981 book scanned by the Internet Archive)
# came out with "Vermilion" and "Phyllis A. Whitney" read at the top of every page, every page
# number, and every printed line as its own paragraph ("the woman who" / pause / "hadn't wanted
# me"), so it sounded stilted. Read page by page instead: drop the running heads and page
# numbers, join lines into real paragraphs, mend words split at the end of a line, and find the
# chapters (a short page with no running head starts one).
# ---------------------------------------------------------------------------
_WORDS = None


def known_words():
    """Every word the voice knows (its own pronouncing lists, 178,000 words), for telling a word
    split at a line end ("know-" "ing") from a real hyphen ("high-" "heeled")."""
    global _WORDS
    if _WORDS is None:
        words = set()
        for name in ("lexicon-us-en.txt", "lexicon-gb-en.txt"):
            try:
                with open(model_dir() / name, encoding="utf8") as f:
                    for line in f:
                        words.add(line.split(" ", 1)[0].lower())
            except OSError:
                pass
        _WORDS = words
    return _WORDS


def join_lines(a, b):
    """Two lines of print as one text: "know-" + "ing gone" -> "knowing gone", "high-" +
    "heeled" -> "high-heeled" (both are words), "hol- lowness" -> "hollowness"."""
    m = re.search(r"([A-Za-z]+)[-­]$", a)
    n = re.match(r"([a-z]+)", b)
    if m and n:
        whole = (m.group(1) + n.group(1)).lower()
        words = known_words()
        if not words or whole in words or not (m.group(1).lower() in words and n.group(1) in words):
            return a[:-1] + b
        return a + b
    return a + " " + b


SPLIT_WORD = re.compile(r"\b([A-Za-z]+)-\s+([a-z]+)\b")


def mend_words(text):
    """Words split by a line end inside a paragraph: "know- ing" -> "knowing"."""
    words = known_words()

    def fix(m):
        # the voice's lists lack many -ed/-ing forms ("waited"), so join unless both halves are
        # words and the whole isn't ("guest-house")
        whole = (m.group(1) + m.group(2)).lower()
        if words and whole not in words and m.group(1).lower() in words and m.group(2) in words:
            return m.group(1) + "-" + m.group(2)
        return m.group(1) + m.group(2)
    return SPLIT_WORD.sub(fix, text)


# Scanned books glue short words onto their neighbours ("inmy", "ofthat", "butnow", "she'dbeen").
# A word the voice doesn't know is split when it's one of these little words plus a known word.
GLUE = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "but", "or", "my", "me", "he", "she",
        "we", "it", "is", "was", "with", "for", "from", "that", "this", "not", "now", "had", "been",
        "his", "her", "him", "you", "your", "i", "i'd", "she'd", "he'd", "i'm", "i've", "i'll", "as",
        "be", "by", "so", "no", "if", "up", "out", "all", "into", "were", "have", "has", "did", "would",
        "could", "there", "they", "them", "then", "than", "what", "when", "who", "how", "our", "its"}
GLUED = re.compile(r"(?<![\w'’-])([a-z]+(?:'[a-z]+)?[a-z]*)(?![\w'’-])")


def unglue(text):
    words = known_words()
    if not words:
        return text

    def fix(m):
        w = m.group(1)
        if w in words or len(w) < 4:
            return w
        for k in range(1, len(w)):
            a, b = w[:k], w[k:]
            if (a in GLUE and b in words and len(b) >= 2) or (b in GLUE and a in words and len(a) >= 2):
                return f"{a} {b}"
        return w
    text = GLUED.sub(fix, text)
    return re.sub(r"(?:(?<=^)|(?<=[\s\"(]))/(?=\s+[a-z])", "I", text)     # "/ was" is "I was"


def _letters(s):
    return re.sub(r"[^a-z]", "", s.lower())


PAGE_NO = re.compile(r"^[\dIVXLCivxlc .\-–—|]{1,9}$")
END_PUNCT = re.compile(r"[.!?…:\"'”’)\]]$")
CHAPTER_LINE = re.compile(r"^(chapter|part|book)\s+([\dIVXLC]+|one|two|three|four|five|six|seven|eight|nine|"
                          r"ten|eleven|twelve|[a-z]+teen|twenty[\w-]*|thirty[\w-]*)\b.{0,50}$|^(prologue|epilogue)\b.{0,40}$",
                          re.I)


def _pdf_author(a):
    """"Whitney, Phyllis A., 1903-2008" -> "Phyllis A. Whitney"."""
    a = re.sub(r",?\s*\d{4}\s*-\s*(\d{4})?\.?\s*$", "", " ".join(str(a or "").split())).strip(" ,")
    m = re.fullmatch(r"([^,]+),\s*([^,]+)", a)
    return f"{m.group(2)} {m.group(1)}" if m else a


def _pdf_title(raw, path):
    """The title in a PDF's details, without what the program that made it added: "Microsoft Word -
    The_Mystery_of_the_Old_Schoolhouse" (Lauren's script) -> "The Mystery of the Old Schoolhouse"."""
    t = " ".join(str(raw or "").split())
    t = re.sub(r"^(Microsoft (Word|PowerPoint)|Word|Writer|Untitled)\s*-\s*", "", t, flags=re.I)
    t = re.sub(r"\.(docx?|odt|rtf|pdf|txt)$", "", t, flags=re.I)
    if t.count("_") >= 1 and " " not in t:
        t = t.replace("_", " ")
    t = " ".join(t.split())
    if not t or t.lower() in ("untitled", "document", "microsoft word"):
        t = " ".join(Path(path).stem.replace("_", " ").split())
    return t


def read_pdf(path):
    """(title, author, cover bytes or None, chapters [{"title", "paras", "read"}])."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        if r.is_encrypted and not r.decrypt(""):
            raise BookError("This PDF is locked with a password, so it can't be read.")
        pages = [[" ".join(l.split()) for l in (pg.extract_text() or "").split("\n") if l.strip()]
                 for pg in r.pages]
    except BookError:
        raise
    except Exception as ex:
        raise BookError(f"This PDF couldn't be opened ({ex}).")
    meta = r.metadata or {}
    title = _pdf_title(meta.get("/Title"), path)
    author = _pdf_author(meta.get("/Author"))
    n = len(pages)
    # running heads: the same words at the top or bottom of many pages ("Phyllis A. Whitney 11")
    seen = {}
    for lines in pages:
        for line in set(lines[:3] + lines[-2:]):
            k = _letters(line)
            if 3 <= len(k) <= 60 and len(line.split()) <= 8:
                seen[k] = seen.get(k, 0) + 1
    heads = {k for k, c in seen.items() if c >= max(4, 0.06 * n)}

    def is_head(line):
        k = _letters(line)
        if not k:
            return bool(PAGE_NO.match(line))
        if len(line.split()) > 8:
            return False
        import difflib
        return k in heads or any(difflib.SequenceMatcher(None, k, h).ratio() >= 0.8 for h in heads)

    body, had_head = [], []
    for lines in pages:
        lines, top, head = list(lines), 0, False
        while lines and top < 4 and is_head(lines[0]):
            head |= bool(_letters(lines.pop(0)))
            top += 1
        bottom = 0
        while lines and bottom < 3 and is_head(lines[-1]):
            head |= bool(_letters(lines.pop()))
            bottom += 1
        body.append(lines)
        had_head.append(head)
    long_lines = sorted(len(l) for lines in body for l in lines if len(l) > 20)
    if not long_lines:
        raise BookError("No text was found in this PDF. (A scanned PDF needs its text recognized "
                        "first; this one has only pictures of the pages.)")
    full = long_lines[len(long_lines) * 3 // 4]      # a full line of print
    counts = sorted(len(b) for b in body if len(b) > 5)
    usual = counts[len(counts) // 2] if counts else 30

    def prose(lines):
        return len(lines) >= 4 and sum(len(l) > 0.6 * full for l in lines) >= 3

    # where chapters start: a "Chapter 3" line, or a short page without the running head whose
    # next page with text has it again (the story carrying on). Not when no page has a head.
    starts = {}
    any_heads = any(had_head)
    nxt = [None] * n
    following = None
    for i in range(n - 1, -1, -1):
        nxt[i] = following
        if body[i]:
            following = i
    for i, lines in enumerate(body):
        if lines and CHAPTER_LINE.match(lines[0]) and len(lines[0]) < 60:
            starts[i] = title_case(lines[0]) if lines[0].isupper() else lines[0]
            body[i] = lines[1:]
        elif (any_heads and not had_head[i] and prose(lines) and len(lines) <= 0.75 * usual
              and nxt[i] is not None and had_head[nxt[i]]):
            starts[i] = ""
    first = min(starts) if starts else None
    # the back of the jacket after the story ("(continued from front flap)")
    jacket = next((i for i, lines in enumerate(body) if i > (first or 0)
                   and any(re.search(r"continued\s*(from|on)\s*(the\s*)?(front|back)\s*flap", l, re.I)
                           for l in lines)), None)

    chapters = []

    def new(name, read=True):
        chapters.append({"title": name, "paras": [], "read": read, "_cur": ""})

    def flush():
        ch = chapters[-1]
        t = " ".join(ch["_cur"].split())
        if t:
            ch["paras"].append(["p", t])
        ch["_cur"] = ""

    new("Front matter (jacket, title page, copyright)" if first else "Beginning", read=not first)
    k = 0
    for i, lines in enumerate(body):
        if jacket is not None and i == jacket and i > (first or 0):
            flush()
            new("Book jacket", read=False)
        elif i in starts:
            flush()
            k += 1
            new(starts[i] or f"Chapter {k}")
        for line in lines:
            ch = chapters[-1]
            ch["_cur"] = join_lines(ch["_cur"], line) if ch["_cur"] else line
            if END_PUNCT.search(line) and len(line) < 0.85 * full:
                flush()
    flush()
    for ch in chapters:
        ch.pop("_cur", None)
    cover = None
    try:            # a scanned book's first page is often its cover (when it's a JPEG)
        for img in r.pages[0].images[:1]:
            if img.data[:3] == b"\xff\xd8\xff":
                cover = img.data
    except Exception:
        pass
    return title, author, cover, [c for c in chapters if c["paras"]]


def mend_paragraphs(paras):
    """Join a paragraph that stops mid-sentence to the next one when that starts in lower case
    (a line break from a PDF or a converted file, not a real paragraph)."""
    out = []
    for kind, text in paras:
        if (out and kind == "p" and out[-1][0] == "p" and text[:1].islower()
                and not END_PUNCT.search(out[-1][1])):
            out[-1] = ["p", join_lines(out[-1][1], text)]
        else:
            out.append([kind, text])
    return out


def load_book(path):
    """The book as {"title", "author", "series", "number", "cover" (bytes), "cover_ext", "path",
    "chapters": [{"title", "paras": [[kind, text]], "words", "read"}]}, kind = "h" heading,
    "p" paragraph, "b" scene break. "read" is False for parts nobody wants read aloud (the table
    of contents, the copyright page, "Also by")."""
    path = Path(path)
    fmt = path.suffix.lower()
    chapters = []
    title, author, series, number, cover, cover_ext = path.stem, "", "", "", None, ""
    if fmt == ".pdf":
        title, author, cover, chapters = read_pdf(path)
        cover_ext = ".jpg" if cover else ""
    elif fmt == ".docx":
        t, a, paras = _read_docx(path)
        title, author = t or title, a
        for heading, text in paras:
            if heading or not chapters:
                chapters.append({"title": " ".join(text.split())[:80] if heading else "Beginning", "paras": []})
            chapters[-1]["paras"].append(["h" if heading else "p", text])
    elif fmt == ".doc":
        raise BookError("Old Word files (.doc) can't be read. Open it in Word and save it as .docx.")
    else:
        sys.path.insert(0, str(HERE))
        import cleanread
        try:
            book = cleanread.Book(path)
        except cleanread.BookError as ex:
            raise BookError(str(ex))
        title, author = book.title or title, book.author
        by_ch = {}
        for p in book.paras:
            by_ch.setdefault(p.chapter, []).append(p)
        for ci in sorted(by_ch):
            name = book.chapters[ci] if ci < len(book.chapters) else ""
            chapters.append({"title": " ".join((name or "").split()),
                             "paras": [["h" if p.heading else "p", p.text] for p in by_ch[ci]]})
        if fmt == ".epub":
            cover, cover_ext, series, number = _epub_extras(path)
    out = []
    for ch in chapters:
        paras = []
        for kind, text in mend_paragraphs(ch["paras"]):
            raw = " ".join(str(text).split())
            if not raw:
                continue
            if BREAK_RE.match(raw):
                if paras and paras[-1][0] != "b":
                    paras.append(["b", ""])
                continue
            s = speakable(unglue(mend_words(raw)) if fmt == ".pdf" else mend_words(raw))
            if s:
                paras.append([kind, s])
        while paras and paras[-1][0] == "b":
            paras.pop()
        if not paras:
            continue
        words = sum(len(t.split()) for _, t in paras)
        name = ch["title"] or (paras[0][1][:60] if paras[0][0] == "h" else "")
        name = name.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        if name.isupper():
            name = title_case(name)
        # (only short ones: a whole story once sat under "List of Illustrations")
        skip = bool(SKIP_TITLES.search(name or "")) and (words < 1500 or bool(LICENSE.search(name)))
        out.append({"title": name or f"Part {len(out) + 1}", "paras": paras, "words": words,
                    "read": ch.get("read", True) and not skip})
    # a "chapter" that is only a heading ("Part One") is read with the chapter after it
    merged = []
    for ch in out:
        if merged and merged[-1]["words"] <= 6 and all(k == "h" for k, _ in merged[-1]["paras"]) \
                and merged[-1]["read"]:
            prev = merged.pop()
            ch = dict(ch, paras=prev["paras"] + ch["paras"], words=prev["words"] + ch["words"],
                      title=ch["title"] if ch["title"] != prev["title"] else prev["title"])
        merged.append(ch)
    if not merged:
        raise BookError("No text was found in this book. (A scanned PDF has pictures of pages "
                        "rather than text, so it can't be read.)")
    return {"title": title, "author": author, "series": series, "number": number, "cover": cover,
            "cover_ext": cover_ext, "path": str(path), "chapters": merged}


def cover_online(book):
    """A cover from the internet for a book without one (a scanned PDF's is often a format the
    M4B can't hold), the way CleanListen finds one: only the title and author are sent, and only
    a sure match is taken. Sets book["cover"]; True if one was found."""
    try:
        sys.path.insert(0, str(HERE))
        import cleanlisten as E
        found = E.find_cover_online(book["title"], book.get("author", ""), APP_DATA / "covers", log=lambda m: None)
        if found:
            data = Path(found["file"]).read_bytes()
            book["cover"], book["cover_ext"] = data, Path(found["file"]).suffix.lower()
            return True
    except Exception:
        pass
    return False


def sample_text(book, words=45):
    """A couple of sentences from the start of the story, to hear a voice."""
    for ch in book["chapters"]:
        if not ch["read"]:
            continue
        text = " ".join(t for k, t in ch["paras"] if k == "p")
        if len(text.split()) < 20:
            continue
        out = []
        for s in sentences(text):
            out.append(s)
            if len(" ".join(out).split()) >= words:
                break
        return " ".join(out)
    return "Once upon a time, in a house at the end of a quiet street, there lived a girl who loved books."


# ---------------------------------------------------------------------------
# Speaking
# ---------------------------------------------------------------------------
def _trim(x, level=0.008, keep=0.04):
    import numpy as np
    loud = np.flatnonzero(np.abs(x) > level)
    if not len(loud):
        return x[:0]
    pad = int(keep * SR)
    return x[max(0, loud[0] - pad): loud[-1] + pad]


def _silence(sec):
    import numpy as np
    return np.zeros(int(sec * SR), dtype=np.float32)


def say_text(tts, text, sid, speed, stop=None):
    """One piece of text -> float32 samples at 24 kHz, with even pauses between sentences."""
    import numpy as np
    out = []
    for c in chunks(text):
        if stop and stop():
            raise Stopped()
        a = tts.generate(c, sid=sid, speed=speed)
        x = _trim(np.asarray(a.samples, dtype=np.float32))
        if not len(x) and re.search(r"[A-Za-z]{2}", c):
            # never a silent gap where there were words: try once more, then say so
            x = _trim(np.asarray(tts.generate(c.strip(" .,;:") + ".", sid=sid, speed=speed).samples,
                                 dtype=np.float32))
            if not len(x):
                raise RuntimeError(f"The voice couldn't read this part: “{c[:120]}”")
        if len(x):
            if out:
                out.append(_silence(GAP_SENTENCE))
            out.append(x)
    return np.concatenate(out) if out else _silence(0)


def sample_wav(text, voice, speed, dst):
    """A WAV of `text` in `voice`, to hear before choosing (the 'Hear it' button)."""
    v = VOICE[voice]
    x = say_text(voice_engine(v[4], threads=max(2, (os.cpu_count() or 4) // 2)), text, v[1], speed)
    write_wav(dst, x)
    return dst


def write_wav(dst, x):
    import wave
    import numpy as np
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


class Stopped(Exception):
    pass


def chapter_file(jobdir, i):
    return Path(jobdir) / f"ch{i:04d}.m4a"


def speak_chapter(jobdir, i, threads=4, report=None):
    """Worker: read chapter i of the job and save it as AAC (ch0003.m4a). report(words_done)."""
    import numpy as np
    jobdir = Path(jobdir)
    job = json.loads((jobdir / "job.json").read_text(encoding="utf8"))
    ch = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[i]
    v = VOICE.get(job["voice"]) or VOICE[DEFAULT_VOICE]
    names = job.get("lexicon") or ""
    tts = voice_engine(v[4], threads, names)
    pron = job.get("pronounce") or {}
    stopfile = jobdir / "stop"

    def stop():
        return stopfile.exists()

    dst = chapter_file(jobdir, i)
    tmp = dst.with_name("~" + dst.name)
    proc = subprocess.Popen([tool("ffmpeg"), "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1",
                             "-i", "pipe:0", "-c:a", "aac", "-b:a", job.get("bitrate", BITRATE),
                             "-f", "mp4", str(tmp)], stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)

    def put(x):
        proc.stdin.write((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

    done = 0
    try:
        put(_silence(LEAD_IN))
        prev = None
        for item in ch["paras"]:
            # [kind, text] or, directed (readaloud_ai), [kind, text, {"v": voice, "s": pace, "g": pause}]
            kind, text = item[0], item[1]
            o = item[2] if len(item) > 2 else {}
            if kind == "b":
                put(_silence(GAP_BREAK))
                prev = "b"
                continue
            if "g" in o and prev:
                put(_silence(o["g"]))
            elif prev in ("p", "h"):
                put(_silence(GAP_HEADING if prev == "h" or kind == "h" else GAP_PARA))
            sv = VOICE.get(o.get("v")) or v
            speaker = voice_engine(sv[4], threads, names) if sv[4] != v[4] else tts
            if pron:
                import readaloud_ai
                text = readaloud_ai.pronounce(text, pron)
            put(say_text(speaker, text, sv[1], job.get("speed", 1.0) * o.get("s", 1.0), stop))
            prev = kind
            done += len(text.split())
            if report:
                report(done)
        put(_silence(TAIL))
        proc.stdin.close()
        err = proc.stderr.read().decode("utf8", "ignore")
        if proc.wait() != 0:
            raise RuntimeError(f"Couldn't save chapter {i + 1}: {err[-300:]}")
        os.replace(tmp, dst)
    except BaseException:
        try:
            proc.kill()
            proc.wait(timeout=15)       # Windows can't delete the file while ffmpeg holds it
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dst


# ---------------------------------------------------------------------------
# A job: one book, one voice
# ---------------------------------------------------------------------------
def job_key(book_path, voice, speed, chapter_ids, director="", cast=False, reader="kokoro"):
    p = Path(book_path)
    try:
        st = p.stat()
        ident = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        ident = str(p)
    ident += f"|{voice}|{speed}|{','.join(map(str, chapter_ids))}"
    if director:
        ident += f"|{director}|{bool(cast)}"
    if reader and reader != "kokoro":
        ident += f"|{reader}"
    return hashlib.sha1(ident.encode("utf8")).hexdigest()[:16]


def start_job(book, voice, speed, chapter_ids, out_file, extra=None):
    """Make (or find again) the job folder for this book, voice and chapters. Chapters already
    read in an earlier run are kept. extra: {"mp3", "reader" (kokoro/acting/steady/chatterbox, readaloud_gpu), "director" ("claude"/"chatgpt"/"gemini" to
    have it go through the book first, readaloud_ai), "cast" (characters get their own voices)}."""
    extra = extra or {}
    key = job_key(book["path"], voice, speed, chapter_ids, extra.get("director", ""), extra.get("cast"),
                  extra.get("reader", "kokoro"))
    jobdir = JOBS / key
    jobdir.mkdir(parents=True, exist_ok=True)
    chosen = [book["chapters"][i] for i in chapter_ids]
    (jobdir / "chapters.json").write_text(json.dumps(
        [{"title": c["title"], "paras": c["paras"], "words": c["words"]} for c in chosen]), encoding="utf8")
    if book.get("cover"):
        (jobdir / ("cover" + book["cover_ext"])).write_bytes(book["cover"])
    job = {"book": book["path"], "title": book["title"], "author": book["author"],
           "series": book.get("series", ""), "number": book.get("number", ""),
           "voice": voice, "speed": speed, "chapters": chapter_ids, "out": str(out_file),
           "bitrate": BITRATE, "started": time.strftime("%Y-%m-%d %H:%M")}
    job.update(extra)
    (jobdir / "job.json").write_text(json.dumps(job, indent=1), encoding="utf8")
    (jobdir / "stop").unlink(missing_ok=True)
    (jobdir / "done.json").unlink(missing_ok=True)
    # the chapters were just written undirected: the directions are put back from their cache
    (jobdir / "directed.json").unlink(missing_ok=True)
    return jobdir


def unfinished_jobs():
    """Jobs that were stopped before the audiobook was made, newest first."""
    out = []
    if JOBS.exists():
        for d in JOBS.iterdir():
            j = d / "job.json"
            if j.exists() and not (d / "done.json").exists():
                try:
                    job = json.loads(j.read_text(encoding="utf8"))
                    n = len(json.loads((d / "chapters.json").read_text(encoding="utf8")))
                except (OSError, ValueError):
                    continue
                got = sum(chapter_file(d, i).exists() for i in range(n))
                out.append((j.stat().st_mtime, d, job, got, n))
    return [(d, job, got, n) for _, d, job, got, n in sorted(out, key=lambda t: t[0], reverse=True)]


def workers_for_pc():
    """How many chapters to read at once, and threads for each. One voice uses about 1 GB of
    memory; more than 4 threads each doesn't help. On the owner's 16-thread Ryzen: one voice
    with 8 threads read 4x real time, two with 4 threads each 5.5x together, four 5x (no better,
    and twice the memory), so at most 3."""
    cores = os.cpu_count() or 4
    n = max(1, min(3, cores // 5))
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        ms = MS()
        ms.len = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            n = max(1, min(n, int(ms.avail / (1.5 * 2 ** 30))))
    except Exception:
        pass
    return n, max(2, min(4, cores // n))


class Maker:
    """Reads a job's chapters, several at once, each in its own worker process (a crash in one
    never takes the window down). progress(fraction, message, seconds_left or None)."""

    def __init__(self, jobdir, progress=None, workers=None):
        self.jobdir = Path(jobdir)
        self.say = progress or (lambda f, m, left=None: None)
        self.n_workers, self.threads = workers or workers_for_pc()
        self.procs = {}
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        try:
            (self.jobdir / "stop").write_text("stop")
        except OSError:
            pass
        for p in list(self.procs.values()):
            try:
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except OSError:
                    pass

    def run(self):
        """Read every chapter not read yet, then make the audiobook. Returns assemble()'s result."""
        # "Stop for now" left a stop note; carrying on must clear it, or every worker stops at
        # once and the book is put together with chapters missing (Lauren's first try, 1.15.0)
        (self.jobdir / "stop").unlink(missing_ok=True)
        job = json.loads((self.jobdir / "job.json").read_text(encoding="utf8"))
        gpu = job.get("reader") in ("acting", "steady", "chatterbox")
        if gpu:
            import readaloud_gpu as G
            if not G.ready(job["reader"]):
                raise RuntimeError(f"The {G.READERS[job['reader']][0]} voice isn't set up on this computer "
                                   "yet. Choose it under 2. Voice on the first page and press the green "
                                   "Set up button.")
        elif not have_model():
            get_model(lambda f, m: self.say(f * 0.02, m), self._stop)
        if job.get("director") and not (self.jobdir / "directed.json").exists():
            import readaloud_ai
            readaloud_ai.direct(self.jobdir, lambda f, m: self.say(0.02 + 0.08 * f, m, None), self._stop)
        base = 0.1 if job.get("director") else 0.02
        chapters = json.loads((self.jobdir / "chapters.json").read_text(encoding="utf8"))
        words = [c["words"] for c in chapters]
        total = max(1, sum(words))
        todo = [i for i in range(len(chapters)) if not chapter_file(self.jobdir, i).exists()]
        # longest first, so the last few minutes aren't one long chapter on its own
        todo.sort(key=lambda i: -words[i])
        done_words = sum(words[i] for i in range(len(chapters)) if i not in todo)
        start_words, first = done_words, None
        partial = {}
        lock = threading.Lock()
        errors = []

        def worker_loop():
            while not self._stop.is_set() and not errors:
                with lock:
                    if not todo:
                        return
                    i = todo.pop(0)
                try:
                    self._one(i, partial, lock)
                except Stopped:
                    return
                except Exception as ex:
                    errors.append(ex)
                    return

        self.status = None

        def gpu_loop():
            # one worker on the graphics card: it loads the voice once and reads the chapters in turn.
            # Another program can take the card's memory midway (Premiere Pro, once): wait a minute
            # and start the worker again on what's left, up to 10 times
            for attempt in range(11):
                left = [i for i in todo if not chapter_file(self.jobdir, i).exists()]
                try:
                    self._gpu(left, partial, lock)
                    return
                except Stopped:
                    return
                except Exception as ex:
                    if "ran out of memory" not in str(ex) or attempt == 10:
                        errors.append(ex)
                        return
                with lock:
                    self.status = ("The graphics card is busy with another program (a game or video "
                                   "editor?). Waiting for it, then carrying on…")
                if self._stop.wait(60):
                    return

        threads = ([threading.Thread(target=gpu_loop, daemon=True)] if gpu else
                   [threading.Thread(target=worker_loop, daemon=True) for _ in range(self.n_workers)])
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
            with lock:
                have = [chapter_file(self.jobdir, i).exists() for i in range(len(chapters))]
                now = sum(words[i] if have[i] else min(words[i], partial.get(i, 0)) for i in range(len(chapters)))
                left_ch = len(chapters) - sum(have)
            # time left: measured from the first words read (the voices take a while to start),
            # and only once there's a fair sample, so it never says "4 hours" for a 12-minute job
            if first is None and now > start_words:
                first = (time.time(), now)
            left = None
            if first and time.time() - first[0] > 45 and now - first[1] > 0.02 * total:
                rate = (now - first[1]) / (time.time() - first[0])
                left = (total - now) / rate
            msg = f"Reading the book aloud… {len(chapters) - left_ch} of {len(chapters)} chapters done"
            if self.status:
                msg = self.status
            self.say(base + (0.95 - base) * now / total, msg, left)
        if errors:
            raise errors[0]
        if self._stop.is_set():
            raise Stopped()
        missing = [i + 1 for i in range(len(chapters)) if not chapter_file(self.jobdir, i).exists()]
        if missing:
            raise RuntimeError(f"Chapter {missing[0]} wasn't read aloud. Press Resume to try again.")
        return assemble(self.jobdir, lambda f, m: self.say(0.95 + 0.05 * f, m, None))

    def _gpu(self, order, partial, lock):
        import readaloud_gpu as G
        logf = self.jobdir / "worker_gpu.log"
        log = open(logf, "w", encoding="utf8")
        try:
            flags = {"creationflags": 0x08000000 | 0x00004000} if os.name == "nt" else {}
            p = subprocess.Popen(G.worker_cmd(self.jobdir, order), stdout=subprocess.PIPE, stderr=log,
                                 stdin=subprocess.DEVNULL, text=True, encoding="utf8", errors="replace",
                                 cwd=str(HERE), env=G.worker_env(), **flags)
        except OSError:
            log.close()
            raise
        self.procs["gpu"] = p
        try:
            for line in p.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                with lock:
                    if "w" in msg:
                        partial[msg["i"]] = msg["w"]
                        self.status = None
                    elif "done" in msg:
                        partial.pop(msg["done"], None)
                    elif "m" in msg:
                        self.status = msg["m"]
            code = p.wait()
        finally:
            self.procs.pop("gpu", None)
            log.close()
        if self._stop.is_set() or (self.jobdir / "stop").exists():
            raise Stopped()
        missing = [i for i in order if not chapter_file(self.jobdir, i).exists()]
        if code != 0 or missing:
            text = logf.read_text(encoding="utf8", errors="ignore")
            if "out of memory" in text.lower() or "OutOfMemoryError" in text:
                raise RuntimeError("The graphics card ran out of memory. Close other programs (games, "
                                   "video editors) and press Resume: it carries on where it stopped.")
            if "MemoryError" in text or "1455" in text:
                raise RuntimeError("The computer ran low on memory. Close other programs and press "
                                   "Resume: it carries on where it stopped.")
            lines = [ln for ln in text.strip().splitlines() if not ln.startswith("read again")]
            raise RuntimeError("The book couldn't be read aloud.\n\n" + "\n".join(lines)[-600:])
        logf.unlink(missing_ok=True)

    def _one(self, i, partial, lock):
        cmd = [sys.executable, str(Path(__file__).resolve()), "speak", str(self.jobdir), str(i), str(self.threads)]
        log = open(self.jobdir / f"worker_{i:04d}.log", "w", encoding="utf8")
        try:
            # below normal priority: the PC stays quick for everything else while it reads
            flags = {"creationflags": 0x08000000 | 0x00004000} if os.name == "nt" else {}
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL,
                                 text=True, cwd=str(HERE), **flags)
        except OSError:
            log.close()
            raise
        self.procs[i] = p
        try:
            for line in p.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "w" in msg:
                    with lock:
                        partial[i] = msg["w"]
            code = p.wait()
        finally:
            self.procs.pop(i, None)
            log.close()
            with lock:
                partial.pop(i, None)
        if self._stop.is_set() or (self.jobdir / "stop").exists():
            raise Stopped()
        if code != 0 or not chapter_file(self.jobdir, i).exists():
            text = (self.jobdir / f"worker_{i:04d}.log").read_text(encoding="utf8", errors="ignore")
            if "MemoryError" in text or "bad allocation" in text or "1455" in text:
                raise RuntimeError("The computer ran low on memory. Close other programs and press "
                                   "Make audiobook again: it carries on where it stopped.")
            raise RuntimeError(f"Chapter {i + 1} couldn't be read aloud.\n\n{text.strip()[-600:]}")
        (self.jobdir / f"worker_{i:04d}.log").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Putting the audiobook together
# ---------------------------------------------------------------------------
def probe_duration(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, **_NOWIN).stdout
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def _cover(jobdir):
    return next((p for p in (Path(jobdir) / "cover.jpg", Path(jobdir) / "cover.png") if p.exists()), None)


def assemble(jobdir, progress=None):
    """Join the chapter files into one M4B (chapters, title, author, cover), plus MP3 chapter
    files when the job asks for them. Returns {"file", "chapters", "hours", "mp3_dir"}."""
    sys.path.insert(0, str(HERE))
    import cleanlisten as E
    say = progress or (lambda f, m: None)
    jobdir = Path(jobdir)
    job = json.loads((jobdir / "job.json").read_text(encoding="utf8"))
    chapters = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))
    files = [chapter_file(jobdir, i) for i in range(len(chapters))]
    say(0.1, "Putting the chapters together…")
    starts, at = [], 0.0
    for f in files:
        starts.append(at)
        at += probe_duration(f)
    lst = jobdir / "list.txt"
    lst.write_text("ffconcat version 1.0\n" + "".join(
        "file '" + f.resolve().as_posix().replace("'", "'\\''") + "'\n" for f in files), encoding="utf8")
    meta = jobdir / "meta.txt"
    tags = E.m4b_tags(job["title"], job.get("author", ""))
    tags["comment"] = f"Read aloud by ReadAloud ({voice_label(job)})"
    if job.get("series"):
        tags["grouping"] = job["series"] + (f" #{job['number']}" if job.get("number") else "")
    titles = [c["title"] for c in chapters]
    n_ch = E.write_ffmeta(meta, tags, list(zip(starts, titles)), at)
    dst = Path(job["out"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name("~saving~ " + dst.name)
    def join(cover):
        cmd = [tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(meta)]
        if cover:
            cmd += ["-i", str(cover), "-map", "0:a", "-map", "2:v", "-c:v", "copy",
                    "-disposition:v:0", "attached_pic"]
        else:
            cmd += ["-map", "0:a"]
        cmd += ["-c:a", "copy", "-map_metadata", "1", "-map_chapters", "1", "-movflags", "+faststart",
                "-f", "ipod", str(tmp)]
        return subprocess.run(cmd, capture_output=True, text=True, **_NOWIN)

    cover = _cover(jobdir)
    r = join(cover)
    if r.returncode != 0 and cover:      # a cover ffmpeg can't take: leave it off rather than fail
        r = join(None)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Couldn't make the audiobook file:\n{r.stderr[-500:]}")
    try:
        os.replace(tmp, dst)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Couldn't save {dst.name}: it's open in another program (a player?). "
                           "Close it and try again.")
    mp3_dir = None
    if job.get("mp3"):
        mp3_dir = Path(job.get("mp3_dir") or dst.parent / (dst.stem + " - chapters"))
        mp3_dir.mkdir(parents=True, exist_ok=True)
        for f in mp3_dir.glob("*.mp3"):
            f.unlink(missing_ok=True)
        for i, f in enumerate(files):
            say(0.3 + 0.7 * i / len(files), f"Making the MP3 chapter files… {i + 1} of {len(files)}")
            name = E.safe_name(f"{i + 1:02d} - {titles[i]}")[:120] + ".mp3"
            subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(f), "-c:a", "libmp3lame", "-b:a", "96k",
                            "-metadata", f"title={titles[i]}", "-metadata", f"album={job['title']}",
                            "-metadata", f"artist={job.get('author', '')}", "-metadata", f"track={i + 1}",
                            str(mp3_dir / name)], capture_output=True, **_NOWIN)
    report = None
    if (jobdir / "report.txt").exists():    # what the reading director changed (readaloud_ai)
        try:
            report = APP_DATA / "readaloud_reports" / (E.safe_name(job["title"]) + " - what was changed.txt")
            report.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(jobdir / "report.txt", report)
        except OSError:
            report = None
    result = {"file": str(dst), "chapters": n_ch, "hours": round(at / 3600, 2),
              "mp3_dir": str(mp3_dir) if mp3_dir else None, "finished": time.strftime("%Y-%m-%d %H:%M"),
              "report": str(report) if report else None}
    (jobdir / "done.json").write_text(json.dumps(result, indent=1), encoding="utf8")
    for f in (lst, meta):
        f.unlink(missing_ok=True)
    say(1.0, "Done")
    return result


def voice_label(job):
    """ "Heart voice" or "Grace voice, Qwen acting" """
    v = job.get("voice", "")
    if v in VOICE:
        return f"{VOICE[v][2]} voice"
    try:
        import readaloud_gpu as G
        name = (G.GPU_VOICES.get(v) or (v,))[0].split(" - ")[0]
        return f"{name} voice, {G.READERS.get(job.get('reader'), ('',))[0]}".rstrip(", ")
    except Exception:
        return f"{v} voice"


def clean_up(jobdir):
    """Delete a finished job's chapter files (the audiobook itself is kept)."""
    shutil.rmtree(jobdir, ignore_errors=True)


def out_path(book, folder, abs_layout=False):
    """Where the M4B goes: folder/Title.m4b, or with abs_layout the Audiobookshelf folders
    (Author/Series/Book 2 - Title/Title.m4b), like CleanListen's M4B."""
    sys.path.insert(0, str(HERE))
    import cleanlisten as E
    title = E.safe_name(book["title"])
    if abs_layout:
        d = E.abs_folder(folder, book["title"], book.get("author", ""), book.get("series", ""), book.get("number", ""))
        return d / (E.safe_name(E.strip_number(book["title"], book.get("number", ""))) + ".m4b")
    return Path(folder) / (title + ".m4b")


def fmt_left(sec):
    if sec is None:
        return ""
    m = int(sec // 60) + 1
    if m < 2:
        return "about a minute left"
    if m < 60:
        return f"about {m} minutes left"
    h, m = divmod(m, 60)
    m = int(round(m / 5) * 5)
    if m == 60:
        h, m = h + 1, 0
    return f"about {h} hour{'s' if h > 1 else ''}" + (f" {m} minutes" if m else "") + " left"


def estimate_hours(words, speed=1.0):
    """How long the audiobook will be (Kokoro reads about 165 words a minute at normal speed)."""
    return words / (165.0 * speed) / 60.0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def _ranges(spec, n):
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += range(int(a) - 1, int(b or a))
    return [i for i in out if 0 <= i < n]


def _cli(argv):
    if argv and argv[0] == "speak":
        jobdir, i, threads = argv[1], int(argv[2]), int(argv[3])

        def report(w):
            print(json.dumps({"w": w}), flush=True)
        try:
            speak_chapter(jobdir, i, threads, report)
        except Stopped:
            return 3
        return 0
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["info", "make"])
    ap.add_argument("book")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--chapters", default=None)
    ap.add_argument("--mp3", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)
    book = load_book(a.book)
    if a.cmd == "info":
        print(f"{book['title']} by {book['author']}  series={book['series']!r} #{book['number']}  "
              f"cover={len(book['cover'] or b'')} bytes")
        for i, c in enumerate(book["chapters"]):
            print(f"{i + 1:3d} {'read' if c['read'] else 'skip'} {c['words']:6d}  {c['title'][:60]}")
        print(f"about {estimate_hours(sum(c['words'] for c in book['chapters'] if c['read'])):.1f} hours")
        return 0
    ids = _ranges(a.chapters, len(book["chapters"])) if a.chapters else \
        [i for i, c in enumerate(book["chapters"]) if c["read"]]
    out = out_path(book, a.out or Path(a.book).parent)
    jobdir = start_job(book, a.voice, a.speed, ids, out, {"mp3": a.mp3})
    workers = (a.workers, max(2, (os.cpu_count() or 4) // a.workers)) if a.workers else None
    t0 = time.time()
    res = Maker(jobdir, lambda f, m, left=None: print(f"{f:5.1%} {m} {fmt_left(left)}", flush=True),
                workers).run()
    print(json.dumps(res, indent=1), f"in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
