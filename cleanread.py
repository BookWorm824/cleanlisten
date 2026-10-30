#!/usr/bin/env python3
"""
CleanRead's engine: reads an ebook you own (EPUB, PDF or TXT) and either
  * writes a content report for parents (witches, vampires, bullying,
    disrespect toward parents, language... with the actual sentences), or
  * makes a clean copy, using the same filters as CleanListen and CleanView
    (words are marked out, sentences and passages are cut).

The word lists and filters come from CleanListen's engine (cleanlisten.py), so a
fix to a list there reaches CleanRead too. The optional AI helper uses the same
local AI as CleanListen (Ollama + gemma3:4b via cleanview_ai.py).

Command line (for testing):
  python cleanread.py scan BOOK.epub [--ai] [--html REPORT.html]
  python cleanread.py clean BOOK.epub [--out OUT.epub] [--ai]
"""
import argparse
import difflib
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cleanlisten as E  # noqa: E402  (shared word lists and filters)


class BookError(Exception):
    pass


# ---------------------------------------------------------------------------
# Reading a book while keeping its markup, so a clean copy can be written back
# with only the changed words touched.
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![A-Za-z][^>]*>"
                      r"|<(?:\"[^\"]*\"|'[^']*'|[^'\">])*>", re.S)
ENTITY_RE = re.compile(r"&(#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
TAGNAME_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][\w:.-]*)")
ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")
BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div", "td", "th", "dd",
         "dt", "pre", "figcaption", "caption", "section", "article", "aside", "header", "footer",
         "body", "tr", "table", "ul", "ol", "dl", "hr", "nav", "figure", "main", "hgroup",
         "address", "html", "tbody", "thead"}
SKIP = {"head", "script", "style", "title", "svg", "math"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# A word, kept whole when it's bleeped ("f***ing", "s**t", "f--k") so the swear is still found,
# or a grawlix ("#@$%"). A "***" scene break isn't a word.
WORD_RE = re.compile(r"[0-9A-Za-zÀ-ɏ]+(?:['’‘\-][0-9A-Za-zÀ-ɏ]+|[*#]+[0-9A-Za-zÀ-ɏ]*|-{2,}[0-9A-Za-zÀ-ɏ]+)*"
                     r"|(?<![^\s\"'(])(?=[*#@$%&!]*#)(?=[*#@$%&!]*@)[*#@$%&!]{3,}")


def _deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def mask_words(s):
    return " ".join(E.mask(w) for w in s.split())


def nrm(tok):
    return E.norm(_deaccent(tok))


class Para:
    __slots__ = ("doc", "text", "src", "tag", "heading", "open_pi", "close_pi", "chapter")

    def __init__(self, doc):
        self.doc, self.text, self.src = doc, "", []
        self.tag, self.heading, self.open_pi, self.close_pi, self.chapter = None, False, None, None, 0


class Doc:
    def __init__(self, name, pieces, enc="utf-8", xml=True):
        self.name, self.pieces, self.enc, self.xml = name, pieces, enc, xml


def _decode_units(raw, pi):
    """A text piece -> list of (char, (piece, raw_start, raw_end))."""
    out, k = [], 0
    for m in ENTITY_RE.finditer(raw):
        for x in range(k, m.start()):
            out.append((raw[x], (pi, x, x + 1)))
        ch = html.unescape(m.group(0))
        for c in ch:
            out.append((c, (pi, m.start(), m.end())))
        k = m.end()
    for x in range(k, len(raw)):
        out.append((raw[x], (pi, x, x + 1)))
    return out


def _parse_markup(doc_i, doc, anchors, start_chapter, chapter_titles):
    """Split one XHTML document into paragraphs. anchors: {element id: chapter index}."""
    paras, cur = [], None
    skip = 0
    chapter = start_chapter

    def flush(close_pi=None):
        nonlocal cur
        if cur is not None and cur.text.strip():
            if close_pi is not None:
                cur.close_pi = close_pi
            paras.append(cur)
        cur = None

    def ensure():
        nonlocal cur
        if cur is None:
            cur = Para(doc_i)
            cur.chapter = chapter
        return cur

    for pi, piece in enumerate(doc.pieces):
        if piece.startswith("<"):
            if piece.startswith(("<!--", "<?", "<!")):
                continue
            m = TAGNAME_RE.match(piece)
            if not m:
                continue
            closing, name = m.group(1) == "/", m.group(2).lower().split(":")[-1]
            selfclose = piece.rstrip().endswith("/>")
            if not closing:
                idm = ID_RE.search(piece)
                if idm and idm.group(1) in anchors and anchors[idm.group(1)] != chapter:
                    flush()
                    chapter = anchors[idm.group(1)]
            if name in SKIP:
                if not closing and not selfclose:
                    skip += 1
                elif closing:
                    skip = max(0, skip - 1)
                continue
            if skip:
                continue
            if name == "br":
                if cur is not None:
                    cur.text += " "
                    cur.src.append(None)
                continue
            if name in BLOCK:
                if closing:
                    simple = cur is not None and cur.tag == name and cur.open_pi is not None
                    flush(pi if simple else None)
                else:
                    flush()
                    if not selfclose:
                        p = ensure()
                        p.tag, p.open_pi, p.heading = name, pi, name in HEADINGS
            continue
        if skip:
            continue
        units = _decode_units(piece, pi)
        if not units:
            continue
        p = ensure()
        p.text += "".join(c for c, _ in units)
        p.src.extend(s for _, s in units)
    flush()
    # a heading that starts a document names the chapter when the TOC doesn't
    for p in paras:
        if p.heading and chapter_titles[p.chapter] is None:
            chapter_titles[p.chapter] = " ".join(p.text.split())[:80]
    return paras, chapter


def _zip_path(base, href):
    href = unquote(href.split("#")[0])
    parts = []
    for seg in (PurePosixPath(base) / href).parts if base else PurePosixPath(href).parts:
        if seg == "..":
            if parts:
                parts.pop()
        elif seg not in (".", ""):
            parts.append(seg)
    return "/".join(parts)


def _attr(tag, name):
    m = re.search(r"\b" + name + r"""\s*=\s*["']([^"']*)["']""", tag)
    return m.group(1) if m else None


def _toc_entries(z, opf_dir, manifest_items, opf):
    """[(zip path of document, fragment or '', title)] in reading order."""
    out = []
    nav = next((it for it in manifest_items if "nav" in (it.get("properties") or "").split()), None)
    if nav:
        try:
            path = _zip_path(opf_dir, nav["href"])
            text = z.read(path).decode("utf8", "ignore")
            m = re.search(r"<nav\b[^>]*(?:epub:)?type\s*=\s*[\"'][^\"']*\btoc\b[^>]*>(.*?)</nav>", text, re.S)
            body = m.group(1) if m else text
            ndir = path.rsplit("/", 1)[0] if "/" in path else ""
            for a in re.finditer(r"<a\b([^>]*)>(.*?)</a>", body, re.S):
                href = _attr(a.group(1), "href")
                if not href:
                    continue
                title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", a.group(2))).split())
                frag = href.split("#", 1)[1] if "#" in href else ""
                out.append((_zip_path(ndir, href), frag, title))
            if out:
                return out
        except KeyError:
            pass
    tocid = re.search(r"<spine\b[^>]*\btoc\s*=\s*[\"']([^\"']+)", opf)
    ncx = next((it for it in manifest_items if (tocid and it["id"] == tocid.group(1))
                or it.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx:
        try:
            path = _zip_path(opf_dir, ncx["href"])
            text = z.read(path).decode("utf8", "ignore")
            ndir = path.rsplit("/", 1)[0] if "/" in path else ""
            for m in re.finditer(r"<navLabel>\s*<text>(.*?)</text>\s*</navLabel>\s*<content\b([^>]*)/?>",
                                 text, re.S):
                href = _attr(m.group(2), "src")
                if href:
                    frag = href.split("#", 1)[1] if "#" in href else ""
                    out.append((_zip_path(ndir, href), frag, " ".join(html.unescape(m.group(1)).split())))
        except KeyError:
            pass
    return out


class Book:
    """A parsed book. paras hold the text; words and sentences index into them."""

    def __init__(self, path):
        self.path = Path(path)
        self.fmt = self.path.suffix.lower().lstrip(".")
        self.title, self.author = self.path.stem, ""
        self.docs, self.paras, self.chapters = [], [], []
        self.zip_names, self.opf_path = [], None
        if self.fmt == "epub":
            self._read_epub()
        elif self.fmt in ("txt", "text", "md"):
            self._read_plain(self.path.read_text("utf8", "ignore"))
        elif self.fmt == "pdf":
            try:
                paras = E.read_ebook(self.path)
            except E.EbookError as ex:
                raise BookError(str(ex))
            self._read_plain("\n\n".join(paras))
        elif self.fmt in ("azw", "azw3", "kfx", "mobi", "prc"):
            raise BookError("Kindle books can't be opened here. If it's a DRM-free book, convert it "
                            "to EPUB first with the free program Calibre.")
        else:
            raise BookError(f"Can't open .{self.fmt} files. Use an EPUB, PDF or TXT book.")
        if not self.paras:
            raise BookError("No text was found in this book. (A scanned PDF has pictures of pages "
                            "rather than text, so it can't be read.)")
        self._index()

    # ----- reading -----
    def _read_epub(self):
        try:
            z = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile:
            raise BookError("This file isn't a working EPUB.")
        with z:
            names = z.namelist()
            self.zip_names = names
            enc = [n for n in names if n.endswith("encryption.xml")]
            if enc:
                data = z.read(enc[0])
                if b"EncryptedData" in data and data.count(b"EncryptedData") > data.lower().count(b"font"):
                    raise BookError("This ebook is copy-protected (DRM), so it can't be read. "
                                    "Books from Kobo, Google Play and Apple usually are; "
                                    "DRM-free shops and library-free books aren't.")
            try:
                container = z.read("META-INF/container.xml").decode("utf8", "ignore")
                self.opf_path = re.search(r'full-path\s*=\s*"([^"]+)"', container).group(1)
                opf = z.read(self.opf_path).decode("utf8", "ignore")
            except (KeyError, AttributeError):
                raise BookError("This EPUB is damaged (its table of contents is missing).")
            opf_dir = self.opf_path.rsplit("/", 1)[0] if "/" in self.opf_path else ""
            t = re.search(r"<dc:title\b[^>]*>(.*?)</dc:title>", opf, re.S)
            if t:
                self.title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).split())
            a = re.search(r"<dc:creator\b[^>]*>(.*?)</dc:creator>", opf, re.S)
            if a:
                self.author = " ".join(html.unescape(re.sub(r"<[^>]+>", "", a.group(1))).split())
            items = []
            for tag in re.findall(r"<item\b[^>]*>", opf):
                d = {k: _attr(tag, k) for k in ("id", "href", "media-type", "properties")}
                if d["id"] and d["href"]:
                    items.append(d)
            manifest = {it["id"]: it for it in items}
            toc = _toc_entries(z, opf_dir, items, opf)
            spine = []
            for tag in re.findall(r"<itemref\b[^>]*>", opf):
                it = manifest.get(_attr(tag, "idref") or "")
                if it and (it.get("media-type") or "").endswith(("html+xml", "html", "xml")):
                    path = _zip_path(opf_dir, it["href"])
                    if path in names:
                        spine.append(path)
            # chapters from the table of contents
            self.chapters = []
            doc_start, anchors = {}, {}
            for path, frag, title in toc:
                ci = len(self.chapters)
                self.chapters.append(title or None)
                if frag:
                    anchors.setdefault(path, {})[frag] = ci
                else:
                    doc_start.setdefault(path, ci)
            chapter = None
            for path in spine:
                raw = z.read(path)
                encm = re.match(rb"<\?xml[^>]*encoding\s*=\s*[\"']([\w-]+)", raw)
                enc_name = encm.group(1).decode() if encm else "utf-8"
                try:
                    text = raw.decode(enc_name)
                except (LookupError, UnicodeDecodeError):
                    enc_name, text = "utf-8", raw.decode("utf8", "replace")
                pieces = [x for x in TOKEN_RE.split(text)]
                tags = TOKEN_RE.findall(text)
                merged = []
                for k, txt in enumerate(pieces):
                    if txt:
                        merged.append(txt)
                    if k < len(tags):
                        merged.append(tags[k])
                doc = Doc(path, merged, enc_name, True)
                di = len(self.docs)
                self.docs.append(doc)
                if path in doc_start:
                    chapter = doc_start[path]
                elif chapter is None:
                    chapter = len(self.chapters)
                    self.chapters.append(None)
                paras, chapter = _parse_markup(di, doc, anchors.get(path, {}), chapter, self.chapters)
                self.paras.extend(paras)
        # name any chapter still without a title
        n = 0
        for i, t in enumerate(self.chapters):
            if not t:
                n += 1
                self.chapters[i] = f"Section {n}"

    def _read_plain(self, text):
        parts = re.split(r"(\n[ \t]*\n\s*)", text.replace("\r\n", "\n"))
        doc = Doc("text", parts, "utf-8", False)
        self.docs = [doc]
        self.chapters = []
        chap_re = re.compile(r"^\s*(chapter|book|part|prologue|epilogue)\b[^\n]{0,60}$", re.I)
        for pi, piece in enumerate(parts):
            if pi % 2 or not piece.strip():
                continue
            p = Para(0)
            p.text = piece
            p.src = [(pi, k, k + 1) for k in range(len(piece))]
            if chap_re.match(piece) and len(piece) < 80:
                self.chapters.append(" ".join(piece.split()))
                p.heading = True
            if not self.chapters:
                self.chapters.append("Beginning")
            p.chapter = len(self.chapters) - 1
            self.paras.append(p)

    # ----- words and sentences -----
    def _index(self):
        self.words, self.wn, self.word_para = [], [], []   # (para, a, b) / normalized / para
        self.sents = []                                     # (para, a, b, w0, w1)
        self.para_sents = []
        for q, p in enumerate(self.paras):
            s0 = len(self.sents)
            spans = split_sentences(p.text)
            toks = [(m.start(), m.end()) for m in WORD_RE.finditer(p.text)]
            k = 0
            for a, b in spans:
                w0 = len(self.words)
                while k < len(toks) and toks[k][0] < b:
                    ta, tb = toks[k]
                    n = nrm(p.text[ta:tb])
                    if n in ("lord", "lords") and k + 1 < len(toks):
                        # "Lord Godalming" is a title, not God (so no "God's name" or anger-at-God hits)
                        nxt = p.text[toks[k + 1][0]:toks[k + 1][1]]
                        if (p.text[tb:toks[k + 1][0]] == " " and nxt[:1].isupper()
                                and nxt not in ("I", "God", "Jesus", "Christ", "Almighty", "Lord", "O", "Oh")):
                            n = "lord-title"
                    if n:
                        self.words.append((q, ta, tb))
                        self.wn.append(n)
                        self.word_para.append(q)
                    k += 1
                if len(self.words) > w0:
                    self.sents.append((q, a, b, w0, len(self.words)))
            self.para_sents.append(range(s0, len(self.sents)))
        self.word_sent = [0] * len(self.words)
        for si, (_, _, _, w0, w1) in enumerate(self.sents):
            for k in range(w0, w1):
                self.word_sent[k] = si
        # every bad word in the book (all categories), for starring out previews
        self.old_style = old_style_book(self.wn)
        self.bad = {}
        self.lang_hits = E.find_language(self.wn, E.ALL_CATS)
        for i, j, cat in self.lang_hits:
            q = self.words[i][0]
            self.bad.setdefault(q, []).append((self.words[i][1], self.words[j - 1][2]))

    # ----- helpers for showing text -----
    def sent_words(self, si):
        _, _, _, w0, w1 = self.sents[si]
        return self.wn[w0:w1]

    def sent_text(self, si):
        q, a, b, _, _ = self.sents[si]
        return self.paras[q].text[a:b]

    def masked(self, q, a, b):
        """Text of paragraph q from a to b, with bad words starred out."""
        t = self.paras[q].text
        out, k = [], a
        for x, y in sorted(self.bad.get(q, [])):
            if y <= a or x >= b:
                continue
            x, y = max(x, a), min(y, b)
            out.append(t[k:x])
            out.append(mask_words(t[x:y]))
            k = y
        out.append(t[k:b])
        return " ".join("".join(out).split())

    def masked_sent(self, si):
        q, a, b, _, _ = self.sents[si]
        return self.masked(q, a, b)

    def chapter_of_para(self, q):
        return self.chapters[self.paras[q].chapter] if self.chapters else ""

    def where(self, q):
        pct = int(100 * q / max(1, len(self.paras)))
        return f"{self.chapter_of_para(q)} · {pct}%"

    def has_bad(self, q, a, b):
        return any(not (y <= a or x >= b) for x, y in self.bad.get(q, []))


    def doubtful_word(self, i, j, cat):
        """A note when a flagged word probably has its innocent meaning, else ''."""
        si = self.word_sent[i]
        ws = self.sent_words(si)
        k = i - self.sents[si][3]
        w = self.wn[i]
        if cat == "orientation" and w in AMBIG_ORIENT and not modern_orientation(ws, k, self.old_style):
            return "probably means cheerful / strange (older meaning)"
        if cat == "sexual" and w.startswith("arous"):
            strong = {x for x in ws if any(p.match(x) for p in E.SEX_C[3])}
            if len(strong) < 2:
                return "probably means woke up / stirred"
        return ""


ABBR = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "vs", "etc", "mt", "capt", "col", "gen",
        "lt", "sgt", "rev", "fr", "no", "messrs", "mme", "mlle", "esq", "hon", "ave", "co", "inc", "ltd"}
END_RE = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)")


def split_sentences(text):
    spans, start = [], 0
    for m in END_RE.finditer(text):
        end = m.end()
        before = re.search(r"([A-Za-z]+)\.$", text[start:m.start() + 1])
        if m.group(0).startswith(".") and before and (
                before.group(1).lower() in ABBR or len(before.group(1)) == 1):
            continue
        nxt = re.match(r"\s*([\"'“‘(\[]*)(\S?)", text[end:])
        if nxt and nxt.group(2) and nxt.group(2).islower():
            continue  # "Hi!" she said.
        spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    out = []
    for a, b in spans:
        seg = text[a:b]
        a2 = a + (len(seg) - len(seg.lstrip()))
        b2 = b - (len(seg) - len(seg.rstrip()))
        if b2 > a2:
            out.append((a2, b2))
    return out


# ---------------------------------------------------------------------------
# Phrase matching: "cast|casts a|the spell" = any word from each slot, in order
# ---------------------------------------------------------------------------
class Phrases:
    """Phrases like "cast|casts a|the spell". A slot starting with "!" is a word that
    must NOT come right before (at the start) or right after (at the end):
    "!don't|not want to die", "cut herself !some|a|the"."""

    def __init__(self, lst):
        self.by_first = {}
        for p in lst:
            toks = p.split()
            pre = post = None
            if toks and toks[0].startswith("!"):
                pre = frozenset(toks.pop(0)[1:].split("|"))
            if toks and toks[-1].startswith("!"):
                post = frozenset(toks.pop()[1:].split("|"))
            slots = tuple(frozenset(t.split("|")) for t in toks)
            for w in slots[0]:
                self.by_first.setdefault(w, []).append((pre, slots, post))

    def spans(self, words):
        out, n = [], len(words)
        for i, w in enumerate(words):
            for pre, slots, post in self.by_first.get(w, ()):
                L = len(slots)
                if i + L > n or not all(words[i + k] in slots[k] for k in range(1, L)):
                    continue
                if pre and i > 0 and words[i - 1] in pre:
                    continue
                if post and i + L < n and words[i + L] in post:
                    continue
                out.append((i, i + L))
        return out


class Words:
    """Regex word list with a cache (a book has far fewer different words than words)."""

    def __init__(self, pats):
        self.regs, self.cache = E._c(pats), {}

    def __call__(self, w):
        r = self.cache.get(w)
        if r is None:
            r = self.cache[w] = any(p.match(w) for p in self.regs)
        return r

    def spans(self, words):
        return [(i, i + 1) for i, w in enumerate(words) if self(w)]


def _ph(lst):
    return Phrases(lst)


def _spans(words, regs=None, phrases=None):
    out = regs.spans(words) if regs else []
    return out + phrases.spans(words) if phrases else out


class Matcher:
    """Words (regex), phrases, and 'weak' words that only count when one of the
    context words is in the same or a neighbouring sentence."""

    def __init__(self, words=(), phrases=(), weak=(), weak_phrases=(), context=()):
        self.regs, self.phrases = Words(words), Phrases(phrases)
        self.weak, self.weak_phrases = Words(weak), Phrases(weak_phrases)
        self.has_weak = bool(weak or weak_phrases)
        self.context = frozenset(context)

    def __call__(self, words, near=None):
        sp = _spans(words, self.regs, self.phrases)
        if self.has_weak and near is not None and self.context & near:
            sp += _spans(words, self.weak, self.weak_phrases)
        return sp


PARENTS = {"mom", "mother", "mum", "mommy", "mummy", "mama", "momma", "ma", "dad", "father", "daddy",
           "papa", "pa", "parents", "parent", "stepmom", "stepdad", "stepmother", "stepfather",
           "grandma", "grandpa", "grandmother", "grandfather", "granny", "gran", "nana", "aunt",
           "auntie", "uncle", "teacher", "teachers", "principal", "mom's", "dad's", "mother's",
           "father's", "parents'", "folks", "grownups", "grown-ups", "adults", "babysitter"}
P = "|".join
POSS = "her|his|my|their|our|your"
PARENT_W = "mom|mother|mum|mommy|mama|dad|father|daddy|papa|parents|grandma|grandpa|grandmother|grandfather"


def _fn(f):
    """Wrap a yes/no sentence test from CleanListen's engine as a matcher."""
    return lambda words, near=None: [(0, 0)] if f(words) else []


# "gay" meaning cheerful and "queer" meaning strange are common in older books.
# They only count as orientation words in a modern pattern ("gay couple", "he is gay").
AMBIG_ORIENT = {"gay", "gays", "queer", "queers"}
MODERN_NEXT = {"man", "men", "woman", "women", "couple", "couples", "people", "person", "kids", "kid",
               "teen", "teens", "teenager", "teenagers", "son", "daughter", "brother", "sister",
               "friend", "friends", "marriage", "marriages", "rights", "pride", "bar", "bars", "club",
               "community", "character", "characters", "boy", "boys", "girl", "girls", "guy", "guys",
               "dad", "dads", "mom", "moms", "parents", "relationship", "relationships", "students",
               "uncle", "aunt", "lgbt", "lgbtq", "identity", "and", "or", "best", "lifestyle", "agenda",
               "activist", "activists", "culture", "love", "romance", "wedding", "husband", "wife",
               "partner", "partners", "lover", "lovers", "youth", "folks"}
MODERN_PREV = {"is", "was", "are", "were", "i'm", "im", "he's", "she's", "you're", "they're", "am",
               "being", "openly", "be", "been", "out", "as", "the", "a", "an", "were", "isn't", "wasn't",
               "aren't", "not", "secretly", "also", "both", "totally", "so"}
OLD_NEXT = {"and", "with", "as", "little", "colors", "colours", "spirits", "laughter", "music",
            "dress", "dresses", "flowers", "voices", "lights", "ribbons", "banners", "young",
            "old", "life", "world", "time", "times", "tune", "song", "songs", "feeling", "sort",
            "kind", "thing", "things", "look", "looking", "face", "noise", "sound", "smell", "fish"}


STRONG_MODERN_NEXT = {"rights", "pride", "marriage", "marriages", "couple", "couples", "community",
                      "lgbt", "lgbtq", "bar", "bars", "club", "agenda", "activist", "activists",
                      "lifestyle", "wedding", "culture", "identity", "son", "daughter", "dads", "moms",
                      "parents", "husband", "wife", "boyfriend", "girlfriend", "partner"}
OLD_PREV = {"so", "very", "rather", "quite", "how", "most", "too", "a", "an", "such", "looked",
            "seemed", "felt", "sounded", "mighty", "uncommonly", "awfully", "pretty"}


def old_style_book(wn):
    """True when the book uses "gay"/"queer" in the old sense (cheerful / strange)."""
    old = modern = 0
    for i, w in enumerate(wn):
        if w in ("gay", "queer"):
            nxt = wn[i + 1] if i + 1 < len(wn) else ""
            prv = wn[i - 1] if i > 0 else ""
            if nxt in OLD_NEXT or prv in OLD_PREV:
                old += 1
            elif nxt in STRONG_MODERN_NEXT or prv in ("openly", "secretly"):
                modern += 1
    return old >= 2 and old > modern


def modern_orientation(words, i, old_style=False):
    w = words[i]
    if w not in AMBIG_ORIENT:
        return True
    nxt = words[i + 1] if i + 1 < len(words) else ""
    prv = words[i - 1] if i > 0 else ""
    if "lgbt" in words or "lgbtq" in words or "homosexual" in words or "lesbian" in words:
        return True
    if old_style:
        return nxt in STRONG_MODERN_NEXT or prv in ("openly", "secretly") or (
            prv == "as" and i > 1 and words[i - 2] in ("out", "identifies", "identified", "identify"))
    if nxt in OLD_NEXT and nxt not in ("and",):
        return False
    if nxt in MODERN_NEXT and nxt not in ("and", "or"):
        return True
    if w in ("gays", "queers"):
        return True
    if prv in MODERN_PREV and nxt == "":
        return prv not in ("the", "a", "an", "so")
    return prv in ("openly", "secretly") or (prv == "as" and i > 1 and words[i - 2] in ("out", "identifies", "identified", "identify"))


CAME_OUT_OK = {"her", "his", "my", "their", "our", "your", "me", "him", "them", "us", "everyone",
               "everybody", "family", "parents", "mom", "dad", "mother", "father", "friends"}
CAME_OUT_AS_OK = {"gay", "lesbian", "bi", "bisexual", "trans", "transgender", "queer", "nonbinary",
                  "pansexual", "asexual", "lgbt", "lgbtq", "homosexual"}


def rel_hit(words, old_style=False):
    """CleanListen's relationship test, but "gay" (cheerful) and "queer" (strange) in an
    old-fashioned sense don't count, and neither does "the people came out to look"."""
    w2 = list(words)
    for k, w in enumerate(words):
        if w in AMBIG_ORIENT and not modern_orientation(words, k, old_style):
            w2[k] = "\x00"
        if w in ("came", "coming") and words[k + 1:k + 3] == ["out", "to"]:
            if (words[k + 3] if k + 3 < len(words) else "") not in CAME_OUT_OK:
                w2[k] = "\x00"
        if w in ("came", "coming") and words[k + 1:k + 3] == ["out", "as"]:
            if (words[k + 3] if k + 3 < len(words) else "") not in CAME_OUT_AS_OK:
                w2[k] = "\x00"
    return E.relationship_hit(w2)


def _ref_hit(words):
    """A sexual reference: a sexual word or phrase ("sexy", "make love", "slept with him"),
    or two explicit words together. One "breast", "naked" or "pleasure" on its own
    doesn't count ("the Tin Woodman's breast", "a thrill of pleasure")."""
    for i, j, _ in E.find_language(words, ["sexual"]):
        if not words[i].startswith("arous"):
            return True
    strong = {w for w in words if any(p.match(w) for p in E.SEX_C[3])}
    return len(strong) >= 2


GOD_NEAR = {"god", "god's", "jesus", "christ", "almighty", "lord", "heaven"}
STRONG_BLAME = Words([r"hat(e|es|ed|ing)", r"blam(e|es|ed|ing)", r"curs(e|es|ed|ing)", r"cruel(ty)?",
                      r"monster", r"sadist(ic)?", r"fault", r"resent(s|ed|ful)?", r"despis(e|ed|es)",
                      r"mock(s|ed|ing)?", r"deserted", r"abandoned", r"forsaken", r"betray(ed|s)?",
                      r"heartless", r"unfair", r"spite"])
MAD_AT_GOD = Phrases(["angry|mad|furious|livid|bitter|upset at|with god|heaven|jesus"])


def faith_neg_spans(words, near=None):
    """Tighter than CleanListen's blames_god for the report: a blame word right next to God."""
    # (two-word ones like "God, let..." are usually prayers, so only the longer phrases)
    if any(tuple(words[i:i + len(ph)]) == ph for ph in E.NO_GOD_PHRASES if len(ph) > 2
           for i in range(len(words))):
        return [(0, 0)]
    sp = MAD_AT_GOD.spans(words) + MOCK_FAITH.spans(words)
    for i, w in enumerate(words):
        if w in GOD_NEAR and any(STRONG_BLAME(x) for x in words[max(0, i - 4):i + 5]):
            sp.append((i, i + 1))
    return sp


# ----- extra sentence filters for cleaning (CleanView has these for movies) -----
KISS_W = Words([r"kiss(ed|es|ing)?", r"smooch.*", r"snog.*"])
KISS_PH = _ph(["made|making|make|makes out with", "made|making out !of|the|a|an|that|what|his|her|its|their|to|something|anything|nothing|some|any|this|these|those|which|who|how|where|like|as|for|from|my|your|our|no|only|just|very|clearly|faintly|dimly|whether|if|it|them|him|me|us|figures|shapes|words"])
PASSION_W = {"passionately", "deeply", "hungrily", "fiercely", "hard", "tongue", "tongues",
             "deepened", "breathlessly", "urgently", "feverishly", "greedily", "longingly",
             "sensually", "lingering", "lingered", "melted"}
PASSION_PH = _ph(["made|making|make out !of|the|a|an|that|what|his|her|its|their|to|something|anything|nothing|some|any|this|these|those|which|who|how|where|like|as|for|from|my|your|our|no|only|just|very|clearly|faintly|dimly|whether|if|it|them|him|me|us|figures|shapes|words", "pressed her|him against", "pulled her|him close",
                  "against her|his lips", "lost in the kiss"])
FAMILY = {"mother", "mom", "mum", "mommy", "mama", "father", "dad", "daddy", "papa", "son", "daughter",
          "baby", "babies", "grandma", "grandpa", "grandmother", "grandfather", "granny", "aunt",
          "auntie", "uncle", "sister", "brother", "niece", "nephew", "kids", "children", "child",
          "puppy", "dog", "cat", "forehead", "goodnight", "goodbye", "blew", "toddler", "boy's",
          "girl's", "infant", "mother's", "father's"}


def kiss_hit(words, mode):
    if mode not in ("passionate", "all"):
        return False
    if not (KISS_W.spans(words) or KISS_PH.spans(words)):
        return False
    ws = set(words)
    if FAMILY & ws or ("little" in ws and ws & {"girl", "boy", "one", "ones"}):
        return False
    if mode == "all":
        return True
    return bool(PASSION_W & set(words)) or bool(PASSION_PH.spans(words))


def romance_spans(words, near=None):
    sp = ROMANCE(words)
    if not FAMILY & set(words):
        sp += KISS_W.spans(words)
    return sp


_SLEEPING = Matcher(
    words=[r"adulter(y|ous|er|ers|ess)", r"infidelit(y|ies)", r"adulterers?"],
    phrases=["slept|sleep|sleeping|sleeps together", "spent|spend|spending|spends the night together",
             "spent|spend|spending the night with", "moved|move|moving in together",
             "living|lived|live|lives together", "one night stand|stands",
             "cheated|cheating|cheats|cheat on " + P(["her", "him", "his", "my", "your", "their"]),
             "having|had|has|have an affair", "an|the|their|his|her|secret|torrid affair with",
             "live-in|livein boyfriend|girlfriend|lover", "sleeping|slept|sleeps around",
             "were|became|become|are|be|being|been lovers", "secret|illicit lover|lovers",
             "took|take|taking|taken|takes a lover", "his mistress",
             "kept|keep|keeps|keeping|took|take a mistress"])


def SLEEPING(words, near=None):
    """Not "we slept together as children" or "living together with her sisters"."""
    sp = _SLEEPING(words)
    return sp if sp and not (FAMILY | {"girls", "boys", "sisters", "brothers", "friends", "roommates",
                                       "family", "families", "children"}) & set(words) else []
SUBSTANCES = Matcher(
    words=[r"drunk(en|enly|ard|ards|s)?", r"beers?", r"wines?", r"whiske?y", r"vodka", r"tequila",
           r"booze", r"boozing", r"liquor", r"alcohol(ic|ics|ism)?", r"hangover", r"hungover",
           r"cigarettes?", r"cigars?", r"tobacco", r"vap(e|es|ing|ed)", r"marijuana", r"cocaine",
           r"heroin", r"meth", r"opioids?", r"drugs?", r"overdos(e|ed|es|ing)", r"bong",
           r"champagne", r"cocktails?", r"brandy", r"bourbon", r"gin", r"tipsy", r"smoked",
           r"smoking", r"stoned"],
    phrases=["got|getting|get high", "a|another|his|her drink"])

CLEAN_AI = dict(E.AI_TYPES)     # the same definitions as CleanListen (kissing, drinking... too)


# ---------------------------------------------------------------------------
# Content check for parents
# ---------------------------------------------------------------------------
# (key, group, label, what it covers, matcher or special)
SCAN_GROUPS = ["Magic & the supernatural", "Behavior & attitudes", "Romance & relationships",
               "Violence & scary content", "Faith", "Language", "Other mature topics"]

SCAN = [
    ("witchcraft", 0, "Witches & spells", "witches, spells, potions, hexes, covens",
     Matcher(words=[r"witch(es|craft|y|ing)?", r"warlocks?", r"covens?", r"spellbooks?",
                    r"spellcast(ing|er|ers)?", r"incantations?", r"potions?", r"cauldrons?",
                    r"hex(es|ed|ing)?", r"sorcer(er|ers|ess|esses|y)", r"enchantress(es)?",
                    r"broomsticks?"],
             phrases=["spells !of|in", "cast|casts|casting a|the|his|her|their|another|that|this|any spell",
                      "under a|the|her|his|its|their spell", "put|puts|putting|placed a spell",
                      "magic|magical|love|sleeping spell", "a spell on|upon",
                      "break|broke|breaking|broken the spell"])),
    ("dark_magic", 0, "Dark magic & the occult",
     "black magic, curses, necromancy, séances, Ouija boards, summoning spirits",
     Matcher(words=[r"necromanc(y|er|ers)", r"occult(ist|ists|ism)?", r"satanic", r"satanism",
                    r"satanists?", r"voodoo", r"hoodoo", r"ouija", r"seances?", r"pentagrams?",
                    r"demonolog(y|ist)", r"witchdoctors?"],
             phrases=["dark magic|arts|spell|spells|sorcery|ritual|rituals|powers|lord|forces",
                      "black magic|arts|mass", "blood magic|ritual|rituals|sacrifice",
                      "human|ritual|animal sacrifice|sacrifices",
                      "raise|raised|raising|raises the dead",
                      "summon|summoned|summoning|summons a|the|an demon|demons|spirit|spirits|dead|evil",
                      "a|the|his|her|ancient|family|terrible|dreadful curse",
                      "put|placed|laid|lay a curse", "sold|sell|selling his|her|their|my|your soul",
                      "deal with the devil", "pact with the|a devil|demon",
                      "speak|spoke|talk|talked|talking|commune|communicate with|to the dead",
                      "spirit board", "evil eye"])),
    ("demons", 0, "Demons, devils & Satan", "demons, devils, Satan, possession, exorcism",
     Matcher(words=[r"demons?", r"demonic", r"devils?", r"satan", r"lucifer", r"beelzebub",
                    r"exorcis(m|ms|t|ts|e|ed|ing)", r"hellhounds?", r"fiends?", r"fiendish"],
             phrases=["possessed by", "evil spirit|spirits", "unclean spirit|spirits"])),
    ("ghosts", 0, "Ghosts & hauntings", "ghosts, haunted houses, poltergeists, spirits",
     Matcher(words=[r"ghosts?", r"ghostly", r"haunt(ed|ing|s)?", r"poltergeists?", r"phantoms?",
                    r"spect(er|ers|re|res|ral)", r"apparitions?", r"wraiths?", r"banshees?"])),
    ("vampires", 0, "Vampires", "vampires, drinking blood",
     Matcher(words=[r"vampir(e|es|ic|ism)", r"bloodsuckers?", r"nosferatu", r"undead"],
             phrases=["drink|drank|drinking|drinks|drunk|suck|sucked|sucking " + POSS +
                      "|human|the blood"])),
    ("werewolves", 0, "Werewolves & shapeshifters", "werewolves, shapeshifters, skinwalkers",
     Matcher(words=[r"werewol(f|ves|fish)", r"lycan(s|thrope|thropes|thropy)?",
                    r"shape-?shift(er|ers|ing|ed|s)?", r"shapeshift(er|ers|ing|ed|s)?",
                    r"skinwalkers?"],
             phrases=["turned|turns|turning|changed|changes|changing|shifted into a|the wolf",
                      "wolf form"])),
    ("undead", 0, "Zombies & the undead", "zombies, ghouls, the walking dead",
     Matcher(words=[r"zombies?", r"zombified", r"ghouls?", r"revenants?", r"liches", r"mummies"],
             phrases=["walking dead", "living dead"])),
    ("magic", 0, "Magic & wizards", "wizards, magic, wands, enchantments (often fairy-tale magic)",
     Matcher(words=[r"wizard(s|ry)?", r"magic", r"magical(ly)?", r"mages?", r"wands?",
                    r"enchant(ed|ing|ment|ments|s)?", r"conjur(e|ed|es|ing|er|ers)",
                    r"sorcery", r"warlock"],
             phrases=["fairy godmother", "magic powers"])),
    ("new_age", 0, "Psychics, fortune telling & New Age",
     "tarot, horoscopes, astrology, psychics, crystal balls, karma, reincarnation",
     Matcher(words=[r"fortune-?tell(er|ers|ing)", r"fortunetell(er|ers|ing)", r"tarot",
                    r"horoscopes?", r"astrolog(y|er|ers|ical)", r"zodiac", r"psychics?",
                    r"clairvoyan(t|ts|ce)", r"divination", r"karma", r"karmic", r"chakras?",
                    r"reincarnat.*", r"soothsayers?", r"seers?", r"mediums"],
             phrases=["crystal ball", "palm reading|reader|readers", "tea leaves",
                      "read|reads|reading|read " + POSS + " palm|palms|fortune",
                      "spirit guide|guides|animal|animals", "past life|lives", "third eye",
                      "the universe sent|wants|has|is telling"])),
    ("mythology", 0, "Other gods & mythology", "Greek, Norse and other gods, pagan worship",
     Matcher(words=[r"goddess(es)?", r"demigods?", r"zeus", r"poseidon", r"hades", r"athena",
                    r"apollo", r"artemis", r"aphrodite", r"hera", r"dionysus", r"hermes", r"ares",
                    r"thor", r"odin", r"loki", r"freya", r"osiris", r"anubis", r"pagans?",
                    r"paganism", r"idols?", r"gods"],
             phrases=["pray|prayed|praying|prays|sacrifice|sacrificed to the|a|their gods|goddess|god",
                      "worship|worshipped|worshiped|worshipping|worshiping the|their|false gods|idols"])),

    ("rebellion", 1, "Disrespect or rebellion toward parents",
     "sneaking out, talking back, lying to parents, defying adults",
     Matcher(words=[r"backtalk", r"sass(ed|ing|y)?"],
             phrases=["sneak|snuck|sneaked|sneaking|sneaks out", "ran|run|running|runs away from home",
                      "you can't|cannot|can tell me what to do",
                      "you're|youre not my mother|mom|father|dad|boss|mum",
                      "you are not my mother|mom|father|dad|boss|mum",
                      "i don't|dont|do not have to listen", "talked|talk|talking|talks back",
                      "back talk", "mouthed|mouthing|mouths off",
                      "don't|dont tell mom|dad|mum|mother|father|grandma|grandpa",
                      "don't|dont tell " + POSS + " " + PARENT_W,
                      "without telling " + POSS + " " + PARENT_W,
                      "behind " + POSS + " parents|parents'|mom's|dad's|mother's|father's|mum's back|backs",
                      "lied|lie|lying|lies to " + POSS + " " + PARENT_W,
                      "yelled|screamed|shouted|snapped at " + POSS + " " + PARENT_W,
                      "ignored|ignoring " + POSS + " " + PARENT_W,
                      "against " + POSS + " parents' wishes", "without permission"],
             weak=[r"rebel(s|led|ling|lion|lious)?", r"defi(ant|ance|antly|ed)", r"defy(ing)?",
                   r"grounded", r"brat(ty)?", r"disobe(y|ys|yed|ying|dient|dience)"],
             weak_phrases=["rolled|rolls|rolling " + POSS + " eyes", "i hate you", "shut up",
                           "leave me alone", "slammed|slams|slamming the|her|his|my door",
                           "stormed|storms off|out|upstairs|away",
                           "you never|can't understand", "it's none of your business",
                           "none of your business", "i don't care", "not fair"],
             context=PARENTS)),
    ("bully", 1, "Bullying & name-calling", "taunts, name-calling, picking on someone",
     _fn(E.bully_hit)),
    ("rude_words", 1, "Rude words kids may copy", "stupid, shut up, idiot, dumb, loser, butt",
     Matcher(words=[r"stupid", r"idiots?", r"idiotic", r"dumb", r"moron(s|ic)?", r"losers?",
                    r"jerks?", r"butts?", r"butthead", r"dummy", r"dummies", r"weirdo", r"sucks",
                    r"buttface", r"poopyhead", r"doofus", r"dork"],
             phrases=["shut up !in|here|there|for|inside|the|a|an|his|her|my|their|our|with|within|at|by|alone|like|together|tight|tightly|shop|house|and|all|day|night|forever|so|until",
                      "hate you", "you suck !from|out|the|it|on|up|in|at|all|my|his|her"])),
    ("lying", 1, "Lying, sneaking & stealing", "lies, cheating on tests, stealing, shoplifting",
     Matcher(words=[r"lied", r"liars?", r"steal(s|ing)?", r"stole", r"stolen", r"shoplift.*",
                    r"thie(f|ves|very|ving)", r"pickpocket.*", r"robb(ed|ing|ery)"],
             phrases=["told|tell|telling|tells a lie|lies", "lying to", "lie to",
                      "cheat|cheated|cheating|cheats on the|a|his|her|my|your|their test|exam|quiz|homework",
                      "copied|copy|copying " + POSS + " answers|homework",
                      "behind " + POSS + " back", "sneak|snuck|sneaked|sneaking into|past|away"])),
    ("revenge", 1, "Revenge", "getting even, vengeance, payback",
     Matcher(words=[r"revenge", r"vengeance", r"vengeful", r"aveng(e|ed|es|ing)", r"payback"],
             phrases=["get|got|getting|gets even", "teach|taught him|her|them|you a lesson"])),
    ("crude", 1, "Crude & potty humor", "farts, burps, boogers, toilet jokes",
     _fn(E.crude_hit)),

    ("romance", 2, "Romance, crushes & kissing", "kissing, crushes, dating, boyfriends and girlfriends",
     romance_spans),
    ("flirt", 2, "Flirting", "flirting, winking at, hitting on someone", _fn(E.flirt_hit)),
    ("ref", 2, "Sexual references", "sentences that mention sex or sexual body parts", None),
    ("sex", 2, "Sexual or sensual scenes", "whole passages heavy with sexual or sensual description", None),
    ("sleeping", 2, "Sleeping around, affairs & living together",
     "unmarried couples sleeping or living together, affairs, cheating", SLEEPING),
    ("relationship", 2, "Same-sex & non-traditional relationships",
     "same-sex couples or flirting, throuples, open marriages, polygamy", "rel"),
    ("gender", 2, "Gender identity topics", "transgender or non-binary characters, pronoun talk",
     Matcher(words=[r"transgenders?", r"transgenderism", r"nonbinary", r"genderqueer",
                    r"genderfluid", r"transsexuals?", r"agender", r"cisgender"],
             phrases=["drag queen|queens|king|kings", "gender identity|transition|affirming",
                      "assigned male|female at birth",
                      "my|her|his|their|our|your|preferred pronouns",
                      "trans girl|boy|woman|man|kid|kids|people|person|teen|youth",
                      "came|coming|come out as trans|transgender|nonbinary"])),

    ("violence", 3, "Violence, fighting & weapons", "fights, killing, guns, knives, battles",
     Matcher(words=[r"kill(s|ed|ing|er|ers)?", r"murder.*", r"punch(ed|es|ing)?", r"stab(s|bed|bing)?",
                    r"shoot(s|ing)?", r"strangl.*", r"slaughter.*", r"fight(s|ing)?", r"fought",
                    r"attack(s|ed|ing|er|ers)?", r"brawl.*", r"assault.*", r"guns?", r"pistols?",
                    r"rifles?", r"shotguns?", r"revolvers?", r"bullets?", r"daggers?", r"swords?",
                    r"knives", r"battles?", r"war"],
             phrases=["beat|beats|beating|beaten him|her|them|me|you|us up", "beat up",
                      "shot him|her|them|me|you|at", "slit his|her|their throat"])),
    ("gore", 3, "Gory descriptions", "graphic, bloody descriptions of injuries or bodies", None),
    ("scary", 3, "Scary & creepy moments", "monsters, nightmares, terror, screaming, skeletons",
     Matcher(words=[r"monsters?", r"monstrous", r"nightmares?", r"terrif(ied|ying)", r"terror",
                    r"horrif(ied|ying)", r"horrors?", r"creep(y|ier|iest)", r"scream(s|ed|ing)?",
                    r"shriek(s|ed|ing)?", r"skeletons?", r"corpses?", r"bloodcurdling",
                    r"spooky", r"eerie", r"sinister", r"menacing"])),
    ("death", 3, "Death & grief", "characters dying, funerals, graves, grieving",
     Matcher(words=[r"died", r"dies", r"deaths?", r"dead", r"dying", r"funerals?", r"graves?",
                    r"graveyards?", r"cemeter(y|ies)", r"coffins?", r"caskets?", r"mourn(ed|ing|s)?",
                    r"grie(f|ving|ved|ve|ves)", r"orphan(s|ed)?"],
             phrases=["passed away", "pass away"])),
    ("suicide", 3, "Suicide or self-harm", "any mention of suicide or hurting oneself",
     Matcher(words=[r"suicid(e|al|es)", r"selfharm", r"overdos(e|ed)"],
             phrases=["kill|killed|killing|kills myself|himself|herself|themselves|yourself",
                      "end|ended|ending my|his|her|their|your life", "end|ending it all",
                      "take|took|taking|takes my|his|her|their|your own life",
                      "cut|cutting|cuts herself|himself|myself|themselves !some|a|an|the|off|another|loose|free|short|out|down|slightly|while|on|accidentally|shaving|by|with|his|her|my|their|bread|meat|loose",
                      "slit|slitting|slits her|his|my|their wrists",
                      "!don't|dont|not|didn't|never|doesn't want|wanted|wants to die", "better off dead"])),
    ("abuse", 3, "Abuse", "abuse or a parent beating a child",
     Matcher(words=[r"abus(e|ed|er|ers|ive|ing)", r"molest.*"],
             phrases=["beat|beats|beating|hit|hits|hitting his|her|their wife|husband|son|daughter|kids|children|mother|mom"])),

    ("faith_neg", 4, "Anger at God or mocking faith",
     "angry with or blaming God, denying God, mocking believers",
     lambda words, near=None: faith_neg_spans(words)),
    ("religion", 4, "Long religious discussions", "passages where beliefs are explained, preached or debated",
     None),
    ("other_religions", 4, "Other religions", "other faiths' practices and teachings",
     Matcher(words=[r"allah", r"buddha", r"buddhis(m|t|ts)", r"hindu(s|ism)?", r"krishna",
                    r"vishnu", r"shiva", r"muslims?", r"islam(ic)?", r"mosques?", r"quran", r"koran",
                    r"wicca(n|ns)?", r"druids?", r"shamans?", r"shamanism", r"mantras?", r"nirvana",
                    r"enlightenment"])),

    ("substances", 6, "Drinking, smoking & drugs", "alcohol, being drunk, cigarettes, vaping, drugs",
     SUBSTANCES),
    ("divorce", 6, "Divorce", "parents divorcing or custody",
     Matcher(words=[r"divorc(e|ed|es|ing)", r"custody"],
             phrases=["my|her|his|their parents split|separated", "split up"])),
]
ROMANCE = Matcher(
    words=[r"romance", r"romantic(ally)?", r"boyfriends?", r"girlfriends?", r"dating", r"sweethearts?"],
    phrases=["crush on", "a|her|his|my|their|the|your crush !of", "in love", "fell|fall|falling|falls for him|her|you|me",
             "asked|ask|asking|asks her|him|me out", "on a date", "made|making|make|makes out with"])
MOCK_FAITH = _ph(["religious nut|nuts|freak|freaks|fanatic|fanatics|nutjob|zealot|zealots",
                  "bible thumper|thumpers|thumping|basher", "jesus freak|freaks", "holy roller|rollers",
                  "god squad", "sky daddy|fairy", "fairy tale|tales about god",
                  "imaginary friend in the sky"])

LANG_CATS = [("strong", "F-word & worse"), ("moderate", "Swear words (s-word, b-word, a-word…)"),
             ("mild", "Mild words (damn, hell, crap)"), ("deity", "God's name used as a swear"),
             ("minced", "Soft substitutes (gosh, heck, freaking)"), ("sexual", "Sexual words"),
             ("orientation", "Orientation words (gay, lesbian…)")]

SCAN_AI = {
    "rebellion": "a child or teenager disrespecting, defying, disobeying, deceiving, sneaking around "
                 "or rebelling against their parents, teachers or other adults in charge (a child "
                 "simply disagreeing politely is NOT this)",
    "bully": E.AI_TYPES["bully"],
    "witchcraft": "witchcraft, casting spells, potions or curses",
    "dark_magic": "dark magic or the occult: black magic, curses, summoning demons or spirits, "
                  "contacting the dead, blood rituals or deals with the devil",
    "ref": E.AI_TYPES["ref"],
    "crude": E.AI_TYPES["crude"],
    "relationship": E.AI_TYPES["relationship"],
    "faith_neg": "someone mocking faith or religious people, or being angry with, blaming or "
                 "denying God",
    "gender": "a transgender or non-binary character, or talk about gender identity or pronouns",
}


def _rating(n):
    if n == 0:
        return "none"
    if n <= 2:
        return "mentioned"
    if n <= 9:
        return "some"
    return "a lot"


RATING_LABEL = {"none": "None found", "mentioned": "Mentioned", "some": "Some", "a lot": "A lot"}


# ---------------------------------------------------------------------------
# Passages (explicit scenes, gore, religious discussions)
# ---------------------------------------------------------------------------
# Same scoring rules as CleanListen's sex_score / gore_score / religion_score, with the
# word weights cached so a whole book is quick: (terms, threshold, rule, need)
#   rule "count": at least "need" strong words; "distinct": at least "need" different strong words
PASSAGE_KINDS = {
    "sex": (lambda: E.SEX_C, lambda: E.SEX_WINDOW_SCORE, "count", 2),
    "gore": (lambda: E.GORE_C, lambda: E.GORE_WINDOW_SCORE, "distinct", 2),
    "religion": (lambda: E.RELIGION_C, lambda: E.RELIGION_WINDOW_SCORE, "distinct", 3),
}


def find_passages(book, kind):
    """Runs of paragraphs whose vocabulary scores above threshold (same idea as
    CleanListen's ebook mode). A passage starts and ends on a paragraph that is
    itself heavy with the content, so a passing mention next door is left alone."""
    terms_f, thr_f, rule, need = PASSAGE_KINDS[kind]
    terms_c, threshold = terms_f(), thr_f()
    top = max(terms_c)
    cache = {}

    def weight(w):
        r = cache.get(w)
        if r is None:
            r = 0
            for wt, pats in terms_c.items():  # first match wins, like the engine
                if any(p.match(w) for p in pats):
                    r = wt
                    break
            cache[w] = r
        return r

    n = len(book.paras)
    psum, pstrong = [0] * n, [[] for _ in range(n)]
    for k, q in enumerate(book.word_para):
        wt = weight(book.wn[k])
        if wt:
            psum[q] += wt
            if wt == top:
                pstrong[q].append(book.wn[k])

    def score(qs):
        strong = [w for q in qs for w in pstrong[q]]
        ok = len(strong) >= need if rule == "count" else len(set(strong)) >= need
        return sum(psum[q] for q in qs) if ok else 0

    def keeps(e, inner):
        ns = len(pstrong[e])
        return ns >= 2 or psum[e] >= top + 1 or (ns > 0 and inner is not None and psum[inner] >= 2 * top)

    hot = set()
    for x in range(n):
        if not psum[x]:
            continue
        win = range(x, min(n, x + 3))   # three paragraphs, like CleanListen's ebook mode
        if score(win) >= threshold:
            hot.update(q for q in win if pstrong[q])
    runs = []
    for q in sorted(hot):
        if runs and q - runs[-1][-1] <= 2:
            runs[-1].extend(range(runs[-1][-1] + 1, q + 1))
        else:
            runs.append([q])
    out = []
    for run_ in runs:
        while run_ and not keeps(run_[0], run_[1] if len(run_) > 1 else None):
            run_ = run_[1:]
        while run_ and not keeps(run_[-1], run_[-2] if len(run_) > 1 else None):
            run_ = run_[:-1]
        if run_ and score(run_):
            out.append(run_)
    return out


def _sentence_runs(book, hit):
    """Consecutive sentences where hit(words) is true -> [[si, ...], ...]."""
    runs = []
    for si in range(len(book.sents)):
        if hit(book.sent_words(si)):
            if runs and runs[-1][-1] == si - 1:
                runs[-1].append(si)
            else:
                runs.append([si])
    return runs


# ---------------------------------------------------------------------------
# AI helper (optional): the same local AI CleanListen uses
# ---------------------------------------------------------------------------
def _ai():
    try:
        import cleanview_ai as ai
        return ai
    except Exception as ex:
        raise RuntimeError("The AI helper files are missing. Open CleanListen once so it can "
                           "update, then try again.") from ex


def ai_find(book, defs, progress=None, cancel=None, chunk=40):
    """The AI reads numbered sentences and names the ones that fit a type, quoting the words
    that show it (a find whose words aren't in that sentence is dropped); then each find is
    double-checked one at a time. Returns {(sentence index, type): 'high'|'medium'}.
    Answers are short on purpose: on a PC without a graphics card, writing the answer was
    most of the time (the old "quote the first 8 words" prompt flagged half of every chunk)."""
    ai = _ai()
    say = progress or (lambda f, m: None)
    ai.ensure_ai(lambda f, m: say(f, m))
    types = list(defs)
    if not types:
        return {}
    listing_defs = "\n".join(f'- "{t}": {defs[t]}' for t in types)
    schema = {"type": "object", "properties": {"flags": {"type": "array", "items": {
        "type": "object", "properties": {"n": {"type": "integer"},
                                         "type": {"type": "string", "enum": types},
                                         "words": {"type": "string"}},
        "required": ["n", "type", "words"]}}}, "required": ["flags"]}
    S = len(book.sents)

    def shows(words, i):
        """Are the quoted words (nearly) in sentence i?"""
        q = [nrm(w) for w in str(words).split() if nrm(w)]
        if not q or not 0 <= i < S:
            return False
        sw = book.sent_words(i)
        best = 0.0
        for st in range(0, max(1, len(sw) - len(q) + 1)):
            best = max(best, difflib.SequenceMatcher(None, q, sw[st:st + len(q)], autojunk=False).ratio())
            if best == 1.0:
                break
        return best >= 0.8

    fine = all_fine()
    not_these = [(t, e[1]) for t in types for e in fine.get(t, [])[-4:] if e[1]][-12:]
    teach = ("\n\nThis family marked sentences like these as NOT a problem, so don't flag ones "
             "like them:\n" + "\n".join(f'- "{x}" (not "{t}")' for t, x in not_these)) if not_these else ""
    cands = set()
    starts = list(range(0, S, chunk - 3))
    t0 = time.time()
    for n, a in enumerate(starts):
        if cancel and cancel():
            raise KeyboardInterrupt
        left = ""
        if n >= 3:
            per = (time.time() - t0) / n
            left = f" · about {per * (len(starts) - n) / 60:.0f} min left"
        say(0.75 * n / max(len(starts), 1), f"AI is reading the book · "
            f"{100 * n // max(len(starts), 1)}%{left}")
        part = range(a, min(S, a + chunk))
        listing = "\n".join(f"{i - a + 1}. " + " ".join(book.sent_text(i).split()) for i in part)
        prompt = ("You help parents know what is in a book before their child reads it. You will read "
                  "numbered sentences and point out only the ones that clearly show one of these:\n" +
                  listing_defs + "\n\nMost sentences in a book show none of these: everyday actions, "
                  "feelings, worry, danger, driving, running away from a threat, and adventure are NOT "
                  "flagged. Most of the time the answer is an empty list. Flag a sentence only if you "
                  "can quote the exact words in it that show the type (for example, for \"ref\" the "
                  "words must be about sex or sexual body parts)." + teach +
                  "\n\nAnswer in JSON: {\"flags\": [{\"n\": sentence number, \"type\": \"one of the "
                  "types\", \"words\": \"the exact words that show it\"}]}, or {\"flags\": []}."
                  "\n\nThe sentences:\n" + listing)
        try:
            res = ai.chat(prompt, schema=schema, timeout=300)
        except Exception:
            continue
        for f in res.get("flags", []):
            if f.get("type") not in defs or not isinstance(f.get("n"), int):
                continue
            i = a + f["n"] - 1
            # the number is sometimes one off; the quoted words decide
            i = next((k for k in (i, i - 1, i + 1) if k in part and shows(f.get("words"), k)), None)
            if i is not None:
                cands.add((i, f["type"]))
        if a + chunk >= S:
            break

    sure_schema = {"type": "object", "properties": {
        "fits": {"type": "boolean"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
        "required": ["fits", "confidence"]}
    found = {}
    todo = sorted(cands)
    for n, (i, kind) in enumerate(todo):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(0.75 + 0.25 * n / max(len(todo), 1), "AI is double-checking what it found…")
        prev = " ".join(book.sent_text(i - 1).split()) if i > 0 else ""
        nxt = " ".join(book.sent_text(i + 1).split()) if i + 1 < S else ""
        ex = f"{prev}\n>>> {' '.join(book.sent_text(i).split())} <<<\n{nxt}".strip()
        seen = [e[1] for e in fine.get(kind, [])[-3:] if e[1]]
        seen = ("\nThe family said sentences like these do NOT count:\n" +
                "\n".join(f'- "{x}"' for x in seen)) if seen else ""
        try:
            res = ai.chat("Below is a short excerpt from a book. The sentence between >>> and <<< is "
                          "the one being checked; the others are only context.\n\n" + ex +
                          f"\n\nQuestion: Does the marked sentence clearly contain {defs[kind]}? " + seen +
                          "\nJudge only the marked sentence. Be strict: when in doubt, answer false.\n"
                          'Answer in JSON: {"fits": true or false, "confidence": "high", "medium" or "low"}',
                          schema=sure_schema, timeout=120)
        except Exception:
            continue
        if res.get("fits") is True and res.get("confidence") in ("high", "medium"):
            found[(i, kind)] = res["confidence"]
    return found


def ai_second_opinion(text, definition):
    """True / False / None (couldn't tell)."""
    ai = _ai()
    try:
        res = ai.chat("Here is a passage from a book:\n\n" + text[:4000] + "\n\nDoes it contain " +
                      definition + '? Answer in JSON: {"fits": true} or {"fits": false}.',
                      schema={"type": "object", "properties": {"fits": {"type": "boolean"}},
                              "required": ["fits"]}, timeout=120)
        return res.get("fits")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Learning from your marks: what you mark "Not a problem" on a content check, or
# untick on the review page, is left out (or starts unticked) when it comes back,
# and the AI helper sees it as examples. export_marks() puts one book's finds and
# your marks in a file to send in (through CleanListen's inbox).
# ---------------------------------------------------------------------------
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
LEARNED = APP_DATA / "cleanread_learned.json"
# What families marked fine in the reports they sent in, shipped with updates ("cleanread_fine" in
# CleanListen's shared_learned.json): clear wrong flags only, never a family's own choice to keep
# something that fits its filter. Your own marks come first.
SHARED = HERE / "shared_learned.json"
MAX_LEARNED = 400       # per kind


def item_key(text):
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", str(text).lower().replace("’", "'")).split())[:300]


def word_key(before, word, after):
    """A flagged word with up to three words either side, so only that spot matches."""
    return item_key(" ".join(str(before).split()[-3:] + [str(word)] + str(after).split()[:3]))


def load_learned():
    try:
        d = json.loads(LEARNED.read_text(encoding="utf8"))
    except Exception:
        d = {}
    d.setdefault("fine", {})        # kind -> [[key, text], ...]; words are kind "word"
    return d


def save_learned(d):
    try:
        LEARNED.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEARNED.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf8")
        os.replace(tmp, LEARNED)
    except OSError:
        pass


def learn_marks(marks):
    """marks: [(kind, key, text, fine)] — remember each as fine, or forget that it was."""
    d = load_learned()
    for kind, key, text, fine in marks:
        if not key:
            continue
        lst = [e for e in d["fine"].get(kind, []) if e[0] != key]
        if fine:
            lst.append([key, " ".join(str(text).split())[:200]])
        d["fine"][kind] = lst[-MAX_LEARNED:]
    save_learned(d)


LEARNED_SHORTEST = 5    # shorter lines ("Shut up, Sam.") are too common to re-apply (as CleanListen)


def shared_fine():
    """The built-in marks: {kind: [[key, text], ...]} ({} if the file can't be read)."""
    try:
        d = json.loads(SHARED.read_text(encoding="utf8")).get("cleanread_fine", {})
        return {k: [e for e in v if isinstance(e, list) and len(e) == 2] for k, v in d.items()}
    except Exception:
        return {}


def all_fine(d=None):
    """Your marks and the built-in ones, per filter (built-in first, so yours are the last)."""
    d = d or load_learned()
    out = {k: list(v) for k, v in shared_fine().items()}
    for kind, lst in d["fine"].items():
        keys = {e[0] for e in lst}
        out[kind] = [e for e in out.get(kind, []) if e[0] not in keys] + list(lst)
    return out


def fine_keys(d=None, shared=True):
    """What was marked fine, per filter (shared: the built-in marks too). A mark only applies
    to what that same filter finds again, so it never acts while its filter is off."""
    d = d or load_learned()
    return {kind: {e[0] for e in lst if len(e[0].split()) >= LEARNED_SHORTEST}
            for kind, lst in (all_fine(d) if shared else d["fine"]).items()}


def recount(c):
    """Count, rating and chapters of a report category, leaving out what was marked fine."""
    items = [it for it in c["items"] if not it.get("fine")]
    c["count"] = len(items)
    c["rating"] = _rating(len(items))
    c["chapters_list"] = _chapter_list(items)
    return c


def without_fine(res):
    """A copy of a content check without the finds marked "Not a problem" (for the report)."""
    out = dict(res)
    out["cats"] = {k: recount(dict(c, items=[it for it in c["items"] if not it.get("fine")]))
                   for k, c in res["cats"].items()}
    out["lang"] = {k: recount(dict(c, items=[it for it in c["items"] if not it.get("fine")]))
                   for k, c in res["lang"].items()}
    return out


def export_marks(found, mode, dest_dir=None):
    """One book's finds and what you marked, in a file to send in. found is a content check
    (mode "check") or a review (mode "clean", with the final ticks)."""
    out = {"what": "CleanRead refined", "mode": mode, "date": date.today().isoformat(),
           "book": found.get("title") or "", "notes": [found[k] for k in ("ai_note", "learn_note")
                                                         if found.get(k)],
           "items": [], "learned": load_learned()}
    try:
        out["version"] = json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        pass
    if mode == "check":
        for kind, c in found["cats"].items():
            for it in c["items"]:
                out["items"].append({"type": "sentence" if not it.get("passage") else "passage",
                                     "kind": kind, "where": it["where"],
                                     "origin": "AI on PC" if it.get("src") == "ai" else "word lists",
                                     "ai": it.get("ai"), "not_a_problem": bool(it.get("fine")),
                                     "text": it.get("raw") or it["text"]})
        for cat, c in found["lang"].items():
            for it in c["items"]:
                out["items"].append({"type": "word", "kind": cat, "where": it["where"],
                                     "word": it["word_raw"], "not_a_problem": bool(it.get("fine")),
                                     "text": f'{it["before_raw"]} [{it["word_raw"]}] {it["after_raw"]}'})
    else:
        out["filters"] = found.get("opts")
        for c in found["cuts"]:
            out["items"].append({"type": "passage" if c.get("paras") else "sentence",
                                 "kind": c["kind"], "where": c["where"], "removed": bool(c.get("cut", True)),
                                 "origin": "AI on PC" if c.get("ai") else "word lists",
                                 "note": c.get("ai_note"), "text": c.get("raw") or c["text"]})
        for m in found["mutes"]:
            out["items"].append({"type": "word", "kind": m["cat"], "where": m["where"],
                                 "removed": bool(m.get("on", True)), "word": m["word_raw"],
                                 "note": m.get("note"),
                                 "text": f'{m["ctx_raw"]} [{m["word_raw"]}] {m["ctx_after_raw"]}'})
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    dest = Path(dest_dir) if dest_dir else next(
        (d for d in (home / "OneDrive" / "Desktop", home / "Desktop", home / "Documents") if d.exists()),
        APP_DATA)
    dest.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "", out["book"])[:60].strip() or "book"
    what = "checked" if mode == "check" else "refined"
    path = dest / f"CleanRead {what} - {safe} {out['date']}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf8")
    return path


# ---------------------------------------------------------------------------
# 1. Content check
# ---------------------------------------------------------------------------
def _syllables(w):
    w = w.lower()
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def reading_level(book):
    words = [book.paras[q].text[a:b] for q, a, b in book.words]
    if not words or not book.sents:
        return None
    syl = sum(_syllables(w) for w in words)
    grade = 0.39 * len(words) / len(book.sents) + 11.8 * syl / len(words) - 15.59
    return max(1, min(16, round(grade)))


def scan(book, use_ai=False, progress=None, cancel=None):
    say = progress or (lambda f, m: None)
    say(0.02, "Reading the book…")
    res = {"title": book.title, "author": book.author, "file": str(book.path),
           "words": len(book.words), "chapters": len(set(p.chapter for p in book.paras)),
           "grade": reading_level(book), "cats": {}, "lang": {}, "ai_note": ""}
    S = len(book.sents)
    near_sets = []
    for si in range(S):
        s = set(book.sent_words(si))
        if si > 0 and book.sents[si - 1][0] == book.sents[si][0]:
            s |= set(book.sent_words(si - 1))
        if si + 1 < S and book.sents[si + 1][0] == book.sents[si][0]:
            s |= set(book.sent_words(si + 1))
        near_sets.append(s)

    def sent_item(si, spans, src="list"):
        q, a, b, w0, _ = book.sents[si]
        hl = []
        for i, j in spans:
            if j > i:
                hl.append((book.words[w0 + i][1] - a, book.words[w0 + j - 1][2] - a))
        return {"si": si, "para": q, "where": book.where(q), "chapter": book.chapter_of_para(q),
                "text": book.masked_sent(si), "raw": " ".join(book.sent_text(si).split())
                if book.has_bad(q, a, b) else None, "hl": _hl_masked(book, si, hl), "src": src,
                "key": item_key(book.sent_text(si))}

    for n, (key, grp, label, desc, m) in enumerate(SCAN):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(0.05 + 0.4 * n / len(SCAN), f"Looking for {label.lower()}…")
        items = []
        if m == "rel":
            for si in range(S):
                if rel_hit(book.sent_words(si), book.old_style):
                    items.append(sent_item(si, []))
        elif m is not None:
            for si in range(S):
                sp = m(book.sent_words(si), near_sets[si])
                if sp:
                    items.append(sent_item(si, sp))
        elif key == "ref":
            for si in range(S):
                if _ref_hit(book.sent_words(si)):
                    items.append(sent_item(si, []))
        else:
            for run_ in find_passages(book, key):
                q = run_[0]
                text = "\n\n".join(book.masked(x, 0, len(book.paras[x].text)) for x in run_)
                items.append({"para": q, "paras": run_, "where": book.where(q),
                              "chapter": book.chapter_of_para(q), "text": text, "hl": [],
                              "passage": True, "src": "list",
                              "key": item_key(" ".join(book.paras[x].text for x in run_))})
        res["cats"][key] = {"label": label, "group": SCAN_GROUPS[grp], "desc": desc, "items": items}

    say(0.47, "Counting language…")
    for i, j, cat in book.lang_hits:
        if book.doubtful_word(i, j, cat):
            continue
        q, a, _ = book.words[i]
        b = book.words[j - 1][2]
        word = book.paras[q].text[a:b]
        t = book.paras[q].text
        lo = max(0, a - 70)
        hi = min(len(t), b + 60)
        lo = t.rfind(" ", 0, a - 60) + 1 if a > 70 else 0
        e = t.find(" ", b + 50)
        hi = e if e != -1 else len(t)
        res["lang"].setdefault(cat, []).append({
            "para": q, "where": book.where(q), "chapter": book.chapter_of_para(q),
            "word": mask_words(word), "word_raw": word,
            "before": book.masked(q, lo, a), "after": book.masked(q, b, hi),
            "before_raw": " ".join(t[lo:a].split()), "after_raw": " ".join(t[b:hi].split()),
            "key": word_key(t[lo:a], word, t[b:hi])})

    if use_ai:
        try:
            found = ai_find(book, SCAN_AI, progress=lambda f, m: say(0.5 + 0.5 * f, m), cancel=cancel)
            added = 0
            for (si, kind), conf in sorted(found.items()):
                items = res["cats"][kind]["items"]
                if any(it.get("si") == si for it in items):
                    for it in items:
                        if it.get("si") == si:
                            it["ai"] = "AI agrees"
                    continue
                if any(it.get("passage") and book.sents[si][0] in it["paras"] for it in items):
                    continue
                it = sent_item(si, [], "ai")
                it["ai"] = "found by AI" if conf == "high" else "AI thinks so"
                items.append(it)
                added += 1
            for c in res["cats"].values():
                c["items"].sort(key=lambda x: (x["para"], x.get("si", 0)))
            res["ai_note"] = f"The AI helper read the whole book and added {added} thing(s) the word lists missed."
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            res["ai_note"] = f"The AI helper couldn't run ({ex}). These results are from the word lists only."
    # what you marked "Not a problem" before stays marked (left out of the counts and report)
    fk = fine_keys()
    known = 0
    for kind, c in res["cats"].items():
        for it in c["items"]:
            if it["key"] in fk.get(kind, ()):
                it["fine"] = True
                known += 1
        recount(c)
    for cat, items in res["lang"].items():
        for it in items:
            if it["key"] in fk.get("word", ()):
                it["fine"] = True
                known += 1
        res["lang"][cat] = recount({"label": dict(LANG_CATS)[cat], "items": items})
    if known:
        res["learn_note"] = f"Left out {known} thing(s) you marked “Not a problem” before."
    say(1.0, "Done")
    return res


def _hl_masked(book, si, hl):
    """Highlight spans are relative to the raw sentence; the masked sentence has
    collapsed spaces and starred words, so re-find each highlighted word in it."""
    if not hl:
        return []
    raw = book.sent_text(si)
    masked = book.masked_sent(si)
    out, pos = [], 0
    for a, b in sorted(hl):
        frag = " ".join(raw[a:b].split())
        k = masked.find(frag, pos)
        if k == -1:
            k = masked.lower().find(frag.lower())
        if k != -1:
            out.append((k, k + len(frag)))
            pos = k + len(frag)
    return out


def _chapter_list(items):
    seen = []
    for it in items:
        if it["chapter"] not in seen:
            seen.append(it["chapter"])
    return seen


def scan_summary_lines(res):
    """Plain lines for the top of the report: what was found, most first."""
    order = {"a lot": 0, "some": 1, "mentioned": 2}
    found = [(c["rating"], c["label"], c["count"]) for c in res["cats"].values() if c["count"]]
    found += [(c["rating"], c["label"], c["count"]) for c in res["lang"].values() if c["count"]]
    found.sort(key=lambda x: (order[x[0]], -x[2]))
    return found


# ---------------------------------------------------------------------------
# HTML report (opens in the web browser; can be printed)
# ---------------------------------------------------------------------------
def _esc(s):
    return html.escape(s or "", quote=True)


def _hl_html(text, hl):
    out, k = [], 0
    for a, b in hl:
        out.append(_esc(text[k:a]))
        out.append("<mark>" + _esc(text[a:b]) + "</mark>")
        k = b
    out.append(_esc(text[k:]))
    return "".join(out)


def report_html(res):
    res = without_fine(res)
    chip ={"none": ("#EEF1EE", "#6D7A72"), "mentioned": ("#E6F0FA", "#2B5B8A"),
            "some": ("#FFF1D6", "#8A5A00"), "a lot": ("#FBE1DC", "#9A2F1F")}
    when = time.strftime("%B %d, %Y")
    title = res["title"] or "Book"
    h = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — Content Report</title>
<style>
:root{{--bg:#F6F3EE;--card:#fff;--ink:#23211F;--muted:#6D6862;--line:#E3DED6;--accent:#2F6F62}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif}}
.wrap{{max-width:900px;margin:0 auto;padding:28px 18px 60px}}
h1{{font-size:30px;margin:0 0 2px}} .by{{color:var(--muted);margin:0 0 14px}}
.facts{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 22px}}
.fact{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px}}
.fact b{{display:block;font-size:22px;color:var(--accent)}} .fact span{{color:var(--muted);font-size:13px}}
.glance{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:24px}}
.glance h2{{margin:0 0 8px;font-size:19px}} .glance ul{{margin:0;padding-left:20px}}
h2.grp{{font-size:20px;margin:30px 0 8px;border-bottom:2px solid var(--line);padding-bottom:4px}}
details{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}}
details[open]{{box-shadow:0 1px 4px rgba(0,0,0,.05)}}
summary{{cursor:pointer;padding:12px 16px;display:flex;gap:12px;align-items:center;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary .lbl{{font-weight:600;flex:1}} summary .desc{{display:block;font-weight:400;color:var(--muted);font-size:13px}}
.chip{{border-radius:999px;padding:2px 12px;font-size:13px;font-weight:600;white-space:nowrap}}
.cnt{{color:var(--muted);font-size:14px;min-width:34px;text-align:right}}
.none summary{{cursor:default;opacity:.65}}
.body{{padding:0 16px 14px}} .chs{{color:var(--muted);font-size:13px;margin:0 0 8px}}
.ex{{border-left:3px solid var(--line);padding:4px 0 4px 12px;margin:10px 0}}
.ex .w{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}}
.ex .ai{{background:#FFF4D6;color:#7A5A00;border-radius:6px;padding:0 6px;font-size:12px;margin-left:6px}}
.ex p{{margin:2px 0;white-space:pre-wrap}}
mark{{background:#F3E3DF;color:#8A3B2E;font-weight:600;border-radius:3px;padding:0 2px}}
.raw{{display:none}} body.show .raw{{display:inline}} body.show .masked{{display:none}}
.tools{{display:flex;gap:10px;align-items:center;margin:0 0 6px;flex-wrap:wrap}}
button{{font:inherit;background:#ECE7E0;border:0;border-radius:8px;padding:6px 14px;cursor:pointer}}
.note{{color:var(--muted);font-size:13px}}
@media print{{details{{break-inside:avoid}} button{{display:none}} body{{background:#fff}}}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1C1B1A;--card:#262523;--ink:#ECE8E2;--muted:#A49E96;--line:#3A3734;--accent:#7CC2B2}}
button{{background:#3A3734;color:var(--ink)}} mark{{background:#5A2E27;color:#FFD9D1}}}}
</style></head><body><div class="wrap">
<h1>{_esc(title)}</h1><p class="by">{_esc(res.get('author') or '')}</p>
<div class="facts">
<div class="fact"><b>{res['words']:,}</b><span>words</span></div>
<div class="fact"><b>{res['chapters']}</b><span>chapters / sections</span></div>"""]
    if res.get("grade"):
        h.append(f'<div class="fact"><b>Grade {res["grade"]}</b><span>about this reading level</span></div>')
    h.append("</div>")
    found = scan_summary_lines(res)
    h.append('<div class="glance"><h2>At a glance</h2>')
    if found:
        h.append("<ul>")
        for rating, label, n in found:
            bg, fg = chip[rating]
            h.append(f'<li><span class="chip" style="background:{bg};color:{fg}">'
                     f'{RATING_LABEL[rating]}</span> &nbsp;{_esc(label)} <span class="note">({n})</span></li>')
        h.append("</ul>")
    else:
        h.append("<p>Nothing on the checklist was found in this book.</p>")
    h.append("</div>")
    h.append('<div class="tools"><button onclick="document.querySelectorAll(\'details:not(.none)\')'
             '.forEach(d=>d.open=true)">Open all</button><button onclick="document.querySelectorAll'
             '(\'details\').forEach(d=>d.open=false)">Close all</button><button id="sw" onclick="'
             'document.body.classList.toggle(\'show\');this.textContent=document.body.classList.'
             'contains(\'show\')?\'Hide bad words\':\'Show bad words\'">Show bad words</button>'
             '<span class="note">Bad words are starred out unless you choose to show them.</span></div>')
    if res.get("ai_note"):
        h.append(f'<p class="note">{_esc(res["ai_note"])}</p>')

    def block(c, examples_html):
        bg, fg = chip[c["rating"]]
        cls = ' class="none"' if not c["count"] else ""
        h.append(f'<details{cls}><summary><span class="lbl">{_esc(c["label"])}'
                 f'<span class="desc">{_esc(c.get("desc", ""))}</span></span>'
                 f'<span class="cnt">{c["count"] or ""}</span>'
                 f'<span class="chip" style="background:{bg};color:{fg}">{RATING_LABEL[c["rating"]]}</span>'
                 f'</summary>')
        if c["count"]:
            h.append('<div class="body">')
            if c["chapters_list"]:
                chs = ", ".join(c["chapters_list"][:30]) + (" …" if len(c["chapters_list"]) > 30 else "")
                h.append(f'<p class="chs">Where: {_esc(chs)}</p>')
            h.append(examples_html)
            h.append("</div>")
        h.append("</details>")

    for grp in SCAN_GROUPS:
        if grp == "Language":
            h.append(f'<h2 class="grp">{_esc(grp)}</h2>')
            for cat, label in LANG_CATS:
                c = res["lang"].get(cat) or {"label": label, "items": [], "count": 0, "rating": "none",
                                              "chapters_list": []}
                ex = []
                for it in c["items"]:
                    ex.append(f'<div class="ex"><div class="w">{_esc(it["where"])}</div><p>…'
                              f'<span class="masked">{_esc(it["before"])} <mark>{_esc(it["word"])}</mark> '
                              f'{_esc(it["after"])}</span><span class="raw">{_esc(it["before_raw"])} '
                              f'<mark>{_esc(it["word_raw"])}</mark> {_esc(it["after_raw"])}</span>…</p></div>')
                block(c, "".join(ex))
            continue
        cats = [c for c in res["cats"].values() if c["group"] == grp]
        if not cats:
            continue
        h.append(f'<h2 class="grp">{_esc(grp)}</h2>')
        for c in cats:
            ex = []
            for it in c["items"]:
                ai = f'<span class="ai">{_esc(it["ai"])}</span>' if it.get("ai") else ""
                body = _hl_html(it["text"], it.get("hl") or [])
                if it.get("raw"):
                    body = (f'<span class="masked">{body}</span><span class="raw">{_esc(it["raw"])}</span>')
                ex.append(f'<div class="ex"><div class="w">{_esc(it["where"])}{ai}</div><p>{body}</p></div>')
            block(c, "".join(ex))
    h.append(f'<p class="note" style="margin-top:30px">Made by CleanRead on {when}. This report comes '
             f'from word lists{" and a local AI helper" if res.get("ai_note", "").startswith("The AI helper read") else ""}'
             f'. It is a guide, not a guarantee: themes can be present without the words that flag them, '
             f'and a flagged sentence may be harmless in context, so read the examples.</p>')
    h.append("</div></body></html>")
    return "".join(h)


# ---------------------------------------------------------------------------
# 2. Clean copy
# ---------------------------------------------------------------------------
CLEAN_LABELS = {"sex": "Explicit scenes", "ref": "Sexual references", "gore": "Gory descriptions",
                "religion": "Religious content", "relationship": "Same-sex & non-traditional relationships",
                "crude": "Crude humor", "bully": "Bullying", "disrespect": "Disrespect",
                "flirt": "Flirting", "kiss": "Kissing",
                "sleeping": "Sleeping around & affairs", "substances": "Drinking, smoking & drugs",
                **E.TOPIC_LABELS}


def religion_parts(opts):
    """The religion boxes ticked: preaching, anger at God, prayers & verses (none if religion is
    off). Settings from before the boxes count as preaching and anger at God."""
    if not opts.get("religion"):
        return set()
    return {p for p in E.RELIGION_PARTS
            if opts.get("religion_" + p, p != "prayers" or opts.get("religion_strict", False))}


def analyze(book, opts, progress=None, cancel=None):
    """opts: dict of the filter ticks. Returns {"cuts": [...], "mutes": [...]}."""
    say = progress or (lambda f, m: None)
    cats = [c for g in ("swearing", "mild", "deity", "minced", "sexual", "rude") if opts.get(g)
            for c in E.GROUPS[g]]
    # religion in parts, as in CleanListen (Jason): preaching, anger at God, prayers & verses
    rparts = religion_parts(opts)
    if opts.get("relationships"):
        cats.append("orientation")
    say(0.02, "Finding language…")
    mutes = []
    for i, j, cat in E.find_language(book.wn, cats):
        q, a, _ = book.words[i]
        if book.words[j - 1][0] != q:
            j = i + 1
        b = book.words[j - 1][2]
        t = book.paras[q].text
        word = t[a:b]
        lo = t.rfind(" ", 0, max(0, a - 50)) + 1 if a > 50 else 0
        e = t.find(" ", b + 40)
        hi = e if e != -1 else len(t)
        doubt = book.doubtful_word(i, j, cat)
        mutes.append({"para": q, "a": a, "b": b, "cat": cat, "where": book.where(q),
                      "word": mask_words(word), "word_raw": word,
                      "ctx": book.masked(q, lo, a), "ctx_after": book.masked(q, b, hi),
                      "ctx_raw": " ".join(t[lo:a].split()), "ctx_after_raw": " ".join(t[b:hi].split()),
                      "key": word_key(t[lo:a], word, t[b:hi]),
                      "on": not doubt, **({"note": doubt} if doubt else {})})

    cuts = []

    def add_passages(kind):
        for run_ in find_passages(book, kind):
            raw = "\n\n".join(book.paras[x].text for x in run_)
            cuts.append({"kind": kind, "paras": run_, "para": run_[0], "where": book.where(run_[0]),
                         "text": "\n\n".join(book.masked(x, 0, len(book.paras[x].text)) for x in run_),
                         "raw": raw, "key": item_key(raw)})

    if opts.get("sex"):
        say(0.1, "Looking for sex scenes…")
        add_passages("sex")
    if opts.get("gore"):
        say(0.15, "Looking for gory descriptions…")
        add_passages("gore")
    if "preach" in rparts:
        say(0.2, "Looking for religious content…")
        add_passages("religion")

    in_passage = set(q for c in cuts for q in c["paras"])
    kiss_mode = opts.get("kiss", "keep")
    sentence_filters = [
        ("ref", opts.get("refs"), _ref_hit),
        ("religion", bool(rparts), lambda w: ("anger" in rparts and E.blames_god(w) or
                                               "preach" in rparts and E.invokes_providence(w) or
                                               "prayers" in rparts and E.strict_religion_hit(w) and
                                               not (E.blames_god(w) or E.invokes_providence(w)))),
        ("relationship", opts.get("relationships"), lambda w: rel_hit(w, book.old_style)),
        ("crude", opts.get("crude"), E.crude_hit),
        ("bully", opts.get("bully"), E.bully_hit),
        ("disrespect", opts.get("disrespect"), E.disrespect_hit),
        ("flirt", opts.get("flirt"), E.flirt_hit),
        ("kiss", kiss_mode in ("passionate", "all"), lambda w: kiss_hit(w, kiss_mode)),
        ("sleeping", opts.get("sleeping"), lambda w: bool(SLEEPING(w))),
        ("substances", opts.get("substances"), lambda w: bool(SUBSTANCES(w))),
        *((t, opts.get(t), lambda w, t=t: E.topic_hit(t, w)) for t in E.TOPICS),
    ]
    taken = set()
    for n, (kind, on, hit) in enumerate(sentence_filters):
        if not on:
            continue
        if cancel and cancel():
            raise KeyboardInterrupt
        say(0.25 + 0.1 * n / len(sentence_filters), f"Looking for {CLEAN_LABELS[kind].lower()}…")
        for run_ in _sentence_runs(book, hit):
            run_ = [si for si in run_ if si not in taken and book.sents[si][0] not in in_passage]
            if not run_:
                continue
            taken.update(run_)
            cuts.append(_sent_cut(book, kind, run_))

    ai_note = ""
    if opts.get("ai"):
        kinds = {k: CLEAN_AI[k] for k, on in (
            ("ref", opts.get("refs")), ("sex", opts.get("sex")), ("gore", opts.get("gore")),
            ("religion", bool(rparts)),
            ("crude", opts.get("crude")), ("bully", opts.get("bully")),
            ("disrespect", opts.get("disrespect")), ("flirt", opts.get("flirt")),
            ("kiss", kiss_mode in ("passionate", "all")), ("sleeping", opts.get("sleeping")),
            ("substances", opts.get("substances")), *((t, opts.get(t)) for t in E.TOPICS)) if on}
        # (same-sex relationships are left to the word lists, as in CleanListen: the small AI
        # put 56 ordinary man-and-woman lines of one romance there)
        kinds.update({k: t for k, t in E.ai_defs_for(rparts, kiss_mode).items() if k in kinds})
        try:
            ai_note = _ai_clean(book, cuts, mutes, kinds, taken, in_passage,
                                lambda f, m: say(0.4 + 0.6 * f, m), cancel)
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            ai_note = f"AI helper couldn't run ({ex}); results are from the word lists only."
    cuts.sort(key=lambda c: (c["para"], c.get("sents", [0])[0]))
    for n, c in enumerate(cuts, 1):
        c["id"] = n
        c.setdefault("cut", True)
    # what you kept (or marked "Not a problem") before starts unticked
    fk, mine = fine_keys(), fine_keys(shared=False)
    known = 0
    for c in cuts:
        if c["key"] in fk.get(c["kind"], ()):
            c["cut"], c["ai_note"] = False, ("You kept this before" if c["key"] in mine.get(
                c["kind"], ()) else "Kept by families before")
            known += 1
    for m in mutes:
        if m["key"] in fk.get("word", ()):
            m["on"], m["note"] = False, ("You kept this before" if m["key"] in mine.get(
                "word", ()) else "Kept by families before")
            known += 1
    learn_note = f"Left {known} thing(s) unticked that were kept before." if known else ""
    say(1.0, "Done")
    return {"cuts": cuts, "mutes": mutes, "ai_note": ai_note, "learn_note": learn_note,
            "title": book.title, "opts": opts}


def _sent_cut(book, kind, run_):
    q = book.sents[run_[0]][0]
    raw = " ".join(" ".join(book.sent_text(si).split()) for si in run_)
    return {"kind": kind, "sents": run_, "para": q, "where": book.where(q),
            "text": " ".join(book.masked_sent(si) for si in run_), "raw": raw, "key": item_key(raw)}


AMBIGUOUS = {"hell", "bloody", "ass", "asses", "arse", "dick", "dicks", "prick", "pricks", "bugger",
             "tits", "sex", "sexes", "sexual", "sexually", "climaxed", "homo", "homos", "queer",
             "queers", "screw", "gay", "gays", "damned", "christ", "jesus", "lord", "god"}


def _ai_clean(book, cuts, mutes, kinds, taken, in_passage, say, cancel):
    ai = _ai()
    found = ai_find(book, kinds, progress=lambda f, m: say(0.7 * f, m), cancel=cancel) if kinds else {}
    added = sugg = off = 0
    # verified finds become sentence cuts (very sure = ticked, somewhat sure = unticked)
    by_kind = {}
    for (si, kind), conf in found.items():
        if si in taken or book.sents[si][0] in in_passage:
            continue
        by_kind.setdefault(kind, {})[si] = conf
    for kind, idx in by_kind.items():
        runs = []
        for si in sorted(idx):
            if runs and si == runs[-1][-1] + 1:
                runs[-1].append(si)
            else:
                runs.append([si])
        for run_ in runs:
            c = _sent_cut(book, kind, run_)
            sure = any(idx[si] == "high" for si in run_)
            c.update(ai=True, cut=sure, ai_note="found by AI" if sure else "AI suggests")
            cuts.append(c)
            taken.update(run_)
            added += sure
            sugg += not sure
    # second opinion on what the word lists flagged
    checks = [c for c in cuts if not c.get("ai") and c["kind"] in kinds]
    for n, c in enumerate(checks):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(0.7 + 0.15 * n / max(1, len(checks)), "AI is double-checking what was flagged…")
        fits = ai_second_opinion(c["text"], kinds[c["kind"]])
        if fits is False:
            c["cut"] = False
            c["ai_note"] = "AI thinks this one is fine"
            off += 1
        elif fits is True:
            c["ai_note"] = "AI agrees"
    # words with an innocent meaning too (hell, bloody, ass, gay, Jesus...)
    checkable = [m for m in mutes if m["cat"] in ("deity", "orientation") or
                 any(nrm(w) in AMBIGUOUS for w in m["word_raw"].split())]
    schema = {"type": "object", "properties": {"fine": {"type": "array", "items": {"type": "integer"}}},
              "required": ["fine"]}
    for b0 in range(0, len(checkable), 20):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(0.85 + 0.15 * b0 / max(1, len(checkable)), "AI is double-checking the marked-out words…")
        batch = checkable[b0:b0 + 20]
        rows = [f"{k}: ...{m['ctx_raw']} [[{m['word_raw']}]] {m['ctx_after_raw']}..." for k, m in enumerate(batch)]
        try:
            res = ai.chat("Each numbered line below has one word or phrase in [[double brackets]] that a "
                          "family's filter plans to mark out of a book:\n\n" + "\n".join(rows) +
                          "\n\nList ONLY the numbers where you are sure the bracketed word has an innocent "
                          "meaning, for example: 'hell' as a place in a sermon, 'bloody' meaning covered in "
                          "blood, 'ass' meaning a donkey, 'Jesus' or 'Lord' in a sincere prayer, 'gay' meaning "
                          "cheerful or bright, 'damned' in a theological sense. Answer in JSON like "
                          "{\"fine\": [3, 7]}; use an empty list if none are innocent.", schema=schema, timeout=180)
            for k in res.get("fine", []):
                if isinstance(k, int) and 0 <= k < len(batch):
                    batch[k]["on"] = False
                    batch[k]["note"] = "AI thinks this isn't swearing"
                    off += 1
        except Exception:
            pass
    return (f"AI helper added {added} it's sure about, suggested {sugg} more for you to decide "
            f"(left unticked), and unticked {off} it thinks were flagged by mistake.")


# ----- writing the clean copy -----
STYLES = {"dash": lambda w: "—", "stars": lambda w: mask_words(w), "remove": lambda w: ""}
MARK = "[…]"


def _quote_fix(text, a, b):
    """'' / '“' / '”' / '"' to keep dialogue quotes balanced after cutting text[a:b]."""
    seg = text[a:b]
    net = seg.count("“") - seg.count("”")
    if net > 0:
        return "open", "“"
    if net < 0:
        return "close", "”"
    if seg.count('"') % 2:
        inside = text[:a].count('"') % 2 == 1
        return ("close", '"') if inside else ("open", '"')
    return None, ""


def _cut_edit(text, a, b, marker):
    """Text edit (x, y, replacement) that removes text[a:b] tidily."""
    a2 = a
    while a2 > 0 and text[a2 - 1].isspace():
        a2 -= 1
    b2 = b
    while b2 < len(text) and text[b2].isspace():
        b2 += 1
    kind, q = _quote_fix(text, a, b)
    core = MARK if marker else ""
    if kind == "close":
        return (a, b, core + q) if core else (a2, b, q)
    if kind == "open":
        return (a, b2, core + " " + q) if core else (a, b2, q)
    if core:
        return a, b, core
    if b2 >= len(text.rstrip()):
        return a2, b2, ""
    return a, b2, ""


def _raw_edits(para, x, y, repl):
    """Turn a text edit on a paragraph into raw edits on its pieces."""
    units = [para.src[k] for k in range(x, y) if para.src[k] is not None]
    if not units:
        # pure insertion: put it before the next real character (or after the previous)
        for k in range(y, len(para.src)):
            if para.src[k] is not None:
                pi, rs, _ = para.src[k]
                return [(pi, rs, rs, repl)]
        for k in range(x - 1, -1, -1):
            if para.src[k] is not None:
                pi, _, re_ = para.src[k]
                return [(pi, re_, re_, repl)]
        return []
    out = []
    cur = None
    for pi, rs, re_ in units:
        if cur and cur[0] == pi and rs <= cur[2]:
            cur[2] = max(cur[2], re_)
        else:
            if cur:
                out.append(cur)
            cur = [pi, rs, re_]
    out.append(cur)
    res = []
    for k, (pi, rs, re_) in enumerate(out):
        res.append((pi, rs, re_, repl if k == 0 else ""))
    return res


def write_clean(book, cuts, mutes, out_path, style="dash", marker=True, progress=None):
    say = progress or (lambda f, m: None)
    say(0.1, "Writing the clean copy…")
    word_repl = STYLES.get(style, STYLES["dash"])
    cut_paras = set()
    sent_cut = set()
    for c in cuts:
        if c.get("paras"):
            cut_paras.update(c["paras"])
        else:
            sent_cut.update(c["sents"])
    for q, rng in enumerate(book.para_sents):
        if len(rng) and all(si in sent_cut for si in rng):
            cut_paras.add(q)

    text_edits = {}   # para -> [(x, y, repl)]
    for q, rng in enumerate(book.para_sents):
        if q in cut_paras:
            continue
        run = []
        for si in list(rng) + [None]:
            if si is not None and si in sent_cut:
                run.append(si)
                continue
            if run:
                t = book.paras[q].text
                text_edits.setdefault(q, []).append(_cut_edit(t, book.sents[run[0]][1], book.sents[run[-1]][2], marker))
                run = []
    n_mutes = 0
    for m in mutes:
        q = m["para"]
        if q in cut_paras:
            continue
        if any(not (m["b"] <= x or m["a"] >= y) for x, y, _ in text_edits.get(q, [])):
            continue
        text_edits.setdefault(q, []).append((m["a"], m["b"], word_repl(m["word_raw"])))
        n_mutes += 1

    raw = {}          # doc -> {piece: [(rs, re, repl)]}
    drop = {}         # doc -> set of pieces removed outright

    def add(doc, pi, rs, re_, repl):
        raw.setdefault(doc, {}).setdefault(pi, []).append((rs, re_, repl))

    for q, edits in text_edits.items():
        p = book.paras[q]
        for x, y, r in edits:
            for pi, rs, re_, rr in _raw_edits(p, x, y, r):
                add(p.doc, pi, rs, re_, rr)
    # whole paragraphs: the first of each run keeps a [...] marker, the rest go
    qs = sorted(cut_paras)
    for k, q in enumerate(qs):
        p = book.paras[q]
        first = k == 0 or qs[k - 1] != q - 1 or book.paras[q - 1].doc != p.doc
        if first and marker:
            for pi, rs, re_, rr in _raw_edits(p, 0, len(p.text), MARK):
                add(p.doc, pi, rs, re_, rr)
        elif p.open_pi is not None and p.close_pi is not None and book.docs[p.doc].xml:
            drop.setdefault(p.doc, set()).update(range(p.open_pi, p.close_pi + 1))
        else:
            for pi, rs, re_, rr in _raw_edits(p, 0, len(p.text), ""):
                add(p.doc, pi, rs, re_, rr)

    new_docs = {}
    for di, doc in enumerate(book.docs):
        if di not in raw and di not in drop:
            continue
        pieces = list(doc.pieces)
        for pi, eds in raw.get(di, {}).items():
            s = pieces[pi]
            for rs, re_, rr in sorted(eds, key=lambda e: (-e[0], -e[1])):
                if doc.xml:
                    rr = html.escape(rr, quote=False)
                s = s[:rs] + rr + s[re_:]
            pieces[pi] = s
        for pi in drop.get(di, ()):
            pieces[pi] = ""
        new_docs[di] = "".join(pieces)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".part")
    if book.fmt == "epub":
        by_name = {book.docs[di].name: (txt, book.docs[di].enc) for di, txt in new_docs.items()}
        with zipfile.ZipFile(book.path) as zin, zipfile.ZipFile(tmp, "w") as zout:
            names = zin.namelist()
            if "mimetype" in names:
                zout.writestr(zipfile.ZipInfo("mimetype"), zin.read("mimetype"), compress_type=zipfile.ZIP_STORED)
            for info in zin.infolist():
                if info.filename == "mimetype":
                    continue
                data = zin.read(info.filename)
                if info.filename in by_name:
                    txt, enc = by_name[info.filename]
                    data = txt.encode(enc, "xmlcharrefreplace")
                elif info.filename == book.opf_path:
                    data = _retitle_opf(data)
                zi = zipfile.ZipInfo(info.filename, info.date_time)
                zi.external_attr = info.external_attr
                zout.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED)
    elif book.fmt == "pdf":
        texts = new_docs.get(0, "".join(book.docs[0].pieces))
        paras = [" ".join(t.split()) for t in re.split(r"\n[ \t]*\n\s*", texts) if t.strip()]
        _simple_epub(tmp, book.title + " (Clean)", book.author, paras)
    else:
        tmp.write_text(new_docs.get(0, "".join(book.docs[0].pieces)), encoding="utf8")
    tmp.replace(out_path)
    say(1.0, "Saved")
    return {"out": str(out_path), "mutes": n_mutes, "cut_paras": len(cut_paras),
            "cut_sents": len(sent_cut), "cuts": len(cuts)}


def _retitle_opf(data):
    txt = data.decode("utf8", "ignore")
    new = re.sub(r"(<dc:title\b[^>]*>)(.*?)(</dc:title>)",
                 lambda m: m.group(1) + m.group(2) + ("" if "(Clean)" in m.group(2) else " (Clean)") + m.group(3),
                 txt, count=1, flags=re.S)
    return new.encode("utf8")


def _simple_epub(path, title, author, paras):
    uid = "cleanread-" + hashlib.sha1((title + str(len(paras))).encode()).hexdigest()[:16]
    body = "\n".join(f"<p>{html.escape(p)}</p>" for p in paras)
    xhtml = (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml">'
             f"<head><title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1>\n{body}\n</body></html>")
    opf = (f'<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           f'unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="uid">{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
           f'<dc:creator>{html.escape(author or "")}</dc:creator><dc:language>en</dc:language>'
           f'<meta property="dcterms:modified">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>'
           f'</metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           f'<item id="t" href="text.xhtml" media-type="application/xhtml+xml"/></manifest>'
           f'<spine><itemref idref="t"/></spine></package>')
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body>'
           f'<nav epub:type="toc"><ol><li><a href="text.xhtml">{html.escape(title)}</a></li></ol></nav></body></html>')
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/text.xhtml", xhtml, compress_type=zipfile.ZIP_DEFLATED)


def clean_out_path(book, folder=None):
    folder = Path(folder) if folder else book.path.parent
    ext = ".txt" if book.fmt in ("txt", "text", "md") else ".epub"
    return folder / f"{book.path.stem} (Clean){ext}"


def removal_report(book, cuts, mutes, res):
    lines = [f"CleanRead — what was removed from {book.title}", "",
             f"{res['mutes']} word(s) marked out, {res['cut_paras']} paragraph(s) and "
             f"{res['cut_sents']} sentence(s) cut.", ""]
    for c in sorted(cuts, key=lambda c: c["para"]):
        lines.append(f"[{CLEAN_LABELS.get(c['kind'], c['kind'])}] {c['where']}")
        lines.append("   " + c["text"].replace("\n", "\n   "))
        lines.append("")
    if mutes:
        lines.append("Words marked out:")
        for m in mutes:
            lines.append(f"   {m['where']}:  …{m['ctx']} [{m['word']}] {m['ctx_after']}…")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def _cli():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("book")
    s.add_argument("--ai", action="store_true")
    s.add_argument("--html")
    c = sub.add_parser("clean")
    c.add_argument("book")
    c.add_argument("--out")
    c.add_argument("--ai", action="store_true")
    c.add_argument("--style", default="dash")
    c.add_argument("--kiss", default="keep")
    a = ap.parse_args()
    book = Book(a.book)
    pr = lambda f, m: print(f"  {f * 100:5.1f}%  {m}", file=sys.stderr)
    if a.cmd == "scan":
        res = scan(book, a.ai, pr)
        for rating, label, n in scan_summary_lines(res):
            print(f"{RATING_LABEL[rating]:>10}  {label} ({n})")
        if a.html:
            Path(a.html).write_text(report_html(res), encoding="utf8")
    else:
        opts = dict(swearing=True, mild=True, deity=True, sexual=True, crude=True, refs=True, sex=True,
                    gore=True, religion=True, relationships=True, ai=a.ai, kiss=a.kiss)
        an = analyze(book, opts, pr)
        cuts = [x for x in an["cuts"] if x.get("cut")]
        mutes = [m for m in an["mutes"] if m.get("on")]
        res = write_clean(book, cuts, mutes, a.out or clean_out_path(book), a.style)
        print(json.dumps(res))


if __name__ == "__main__":
    _cli()
