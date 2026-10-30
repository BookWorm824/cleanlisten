"""
What CleanListen learns from your choices on the review screen (same idea as
CleanView's learning), kept in %LOCALAPPDATA%\\CleanListen\\learned.json.

- Sentences you cut (or add yourself) are cut again when they come back (a
  re-check, the next book in a series), and ones you keep start unticked.
- Words you keep unticking start unticked.
- Your past choices are shown to the AI on this PC and to Claude/ChatGPT as
  examples of what you do and don't want.
- Claude's (or ChatGPT's) calls teach the AI on this PC too: sentences it said
  to cut or that were fine become examples (your own choices come first), and a
  word it said was fine in a phrase ("dinner at Hell's Kitchen") starts unticked
  when that phrase comes back.
- Every Claude/ChatGPT finding is also kept in claude_findings.csv (opens in Excel).
- export() puts everything learned into one file to send in, so it can be merged
  into shared_learned.json, which ships with CleanListen updates and gives every
  copy the same head start. Your own choices always beat the shared ones.
- send() posts that file to the owner's inbox (a Google Apps Script shared with
  CleanView, tools/cleanview_inbox.gs in the CleanView repo), which saves it in the
  owner's Google Drive. Senders need no Google account.
"""
import csv
import json
import os
import re
import urllib.request
from datetime import date
from pathlib import Path

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
PATH = APP_DATA / "learned.json"
FINDINGS = APP_DATA / "claude_findings"
CSV_PATH = APP_DATA / "claude_findings.csv"
HERE = Path(__file__).resolve().parent
# The inbox's web address (the same one CleanView uses). If it's emptied, the app just saves
# the file and says to attach it in a chat with Claude, as before.
SEND_URL = ("https://script.google.com/macros/s/AKfycbxfh9Cv3ctELA3352GTuVA1lshmGZKbwwPDsd39DEIm"
            "Z-bRjFYml78iYKYZ5a2RGt8/exec")
MAX_SEND = 2_000_000        # the inbox refuses more


def send_url():
    return os.environ.get("CLEANLISTEN_INBOX") or SEND_URL


def send(path, kind):
    """Send an exported file (kind "learned" or "refined") to the inbox.
    Raises if it couldn't: no inbox yet, no internet, or the inbox said no."""
    url = send_url()
    if not url:
        raise RuntimeError("CleanListen's inbox isn't set up yet")
    path = Path(path)
    body = json.dumps({"app": "CleanListen", "kind": kind, "name": path.name,
                       "data": json.loads(path.read_text(encoding="utf8"))}).encode("utf8")
    if len(body) > MAX_SEND:
        raise RuntimeError("the file is too big to send")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:     # follows Google's redirect
        answer = json.loads(r.read().decode("utf8") or "{}")
    if not answer.get("ok"):
        raise RuntimeError(f"the inbox didn't take it ({answer.get('why') or 'no reason given'})")
SHARED_PATH = HERE / "shared_learned.json"
MAX = 600
# A cut passage is learned sentence by sentence, so short everyday lines in it ("What do you
# think?", "Right, let's go.") would be cut again in every later book. Sentences this short are
# never cut again just because they were learned (CleanView's LEARNED_SHORTEST).
LEARNED_SHORTEST = 5
_shared = None


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", str(text).lower().replace("’", "'")).split())


def shared():
    """Built-in knowledge that comes with updates: {"cut": [], "kept": [], "ok_words": []}."""
    global _shared
    if _shared is None:
        try:
            _shared = json.loads(SHARED_PATH.read_text("utf8"))
        except Exception:
            _shared = {}
        for k in ("cut", "kept", "ok_words", "word_mutes"):
            _shared.setdefault(k, [])
        _shared.setdefault("cut_for", {})
    return _shared


def load():
    try:
        d = json.loads(PATH.read_text("utf8"))
    except Exception:
        d = {}
    for k, v in (("cut", []), ("kept", []), ("kinds", {}), ("words", {}), ("word_mutes", []),
                 ("claude_cut", []), ("claude_kept", []), ("claude_ok_words", []), ("cut_for", {}),
                 ("notes", [])):
        d.setdefault(k, v)
    return d


def save(d):
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        for k in ("cut", "kept", "claude_cut", "claude_kept", "claude_ok_words"):
            d[k] = d[k][-MAX:]
        d["cut_for"] = {t: k for t, k in d.get("cut_for", {}).items() if t in set(d["cut"])}
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf8")
        os.replace(tmp, PATH)
    except OSError:
        pass


def _remember(lst, text, other=None):
    n = norm(text)
    if len(n.split()) < 3:
        return
    if n in lst:
        lst.remove(n)
    lst.append(n)
    if other is not None and n in other:
        other.remove(n)


def _sentences(text):
    """A passage's sentences (what gets remembered and matched)."""
    parts = re.split(r"(?<=[.?!])[\"'”’]?\s+", str(text).strip())
    return [p for p in parts if len(norm(p).split()) >= 3]


def _word(m):
    return norm(m.get("word_raw") or m.get("word", ""))


def phrase(m):
    """A muted word with the two words before it, e.g. "dinner at hell"."""
    ctx = norm(m.get("ctx_raw") or m.get("ctx", "")).split()[-2:]
    return " ".join(ctx + [_word(m)])


def record(st):
    """Store what you chose on the review screen (st has the final ticks)."""
    d = load()
    for sc in st.get("scenes", []):
        on = sc.get("cut", True)
        for s in _sentences(sc.get("text", "")):
            _remember(d["cut"] if on else d["kept"], s, d["kept"] if on else d["cut"])
            if on and sc.get("kind") and sc.get("kind") != "added":
                d["cut_for"][norm(s)] = sc["kind"]    # cut for this filter (see _for_filters)
        k = d["kinds"].setdefault(sc.get("kind", "?"), {"cut": 0, "kept": 0})
        k["cut" if on else "kept"] += 1
    for m in st.get("mutes", []):
        w = _word(m)
        if not w:
            continue
        s = d["words"].setdefault(w, {"muted": 0, "kept": 0})
        s["muted" if m.get("on", True) else "kept"] += 1
        # words the lists don't know (added by you, Claude/ChatGPT or the AI): remember them
        # with the words around them, so they're muted again when that sentence comes back
        if m.get("on", True) and m.get("src") in ("claude", "ai") or m.get("by_you") and m.get("on", True):
            entry = [_context(m), m.get("word_raw") or m.get("word", ""), m.get("cat", "moderate")]
            d["word_mutes"] = [e for e in d["word_mutes"] if e[0] != entry[0]] + [entry]
    d["word_mutes"] = d["word_mutes"][-MAX:]
    save(d)


def _context(m):
    """The muted word with up to three words either side, e.g. "you're such a loser one of them"."""
    before = norm(m.get("ctx_raw") or m.get("ctx", "")).split()[-3:]
    after = norm(m.get("ctx_after_raw") or m.get("ctx_after", "")).split()[:3]
    return " ".join(before + [_word(m)] + after)


def _for_filters(lines, cut_for, on):
    """Cut sentences to cut again, without those cut for a filter that isn't ticked now
    ("cut_for": sentence -> filter; sentences without one count for every filter)."""
    return {t for t in lines if cut_for.get(t, "") not in KINDS or cut_for[t] in on}


# the passage filters a sentence can be remembered for ("added" etc. count for every filter)
KINDS = {"ref", "sex", "gore", "religion", "relationship", "crude", "bully", "disrespect", "flirt", "holiday",
         "birthday", "darkmagic", "magic", "vampires"}


def apply(st, asr, add_passage, add_word=None):
    """Use what was learned on a fresh analysis. Unticks what you (or Claude, or
    the shared file) said was fine, and adds sentences you cut before that the
    filters didn't catch. add_passage(a, b, kind, on, note) adds a passage for
    sentences a..b. Returns notes for the review screen."""
    d = load()
    sh = shared()
    cut, kept = set(d["cut"]), set(d["kept"])
    kept |= set(d["claude_kept"]) - cut
    shared_cut = set(sh["cut"]) - kept - set(d["claude_kept"])
    kept |= set(sh["kept"]) - cut - shared_cut
    cut |= set(d["claude_cut"]) - kept
    cut |= shared_cut
    on = set((st.get("filters") or {}).get("kinds") or [])
    cut = _for_filters(cut, {**sh["cut_for"], **d["cut_for"]}, on)
    n_kept = n_added = n_w = 0
    for sc in st.get("scenes", []):
        ss = [norm(s) for s in _sentences(sc.get("text", ""))]
        if ss and all(s in kept for s in ss) and sc.get("cut", True):
            sc["cut"] = False
            src = ("you kept this before" if all(s in d["kept"] for s in ss) else
                   "Claude said this was fine before" if all(s in d["claude_kept"] for s in ss) else
                   "learned this is fine")
            sc["ai_note"] = "Learned: fine"
            sc["learned"] = src
            n_kept += 1
    # sentences cut before that nothing flagged this time
    if cut and st.get("sentences"):
        for n, (a, b) in enumerate(st["sentences"]):
            t = " ".join(w["t"] for w in asr[a:b + 1])
            if (norm(t) in cut and len(norm(t).split()) >= LEARNED_SHORTEST and
                    add_passage(n, n, "added", True, "You cut this before")):
                n_added += 1
    word_mutes = d["word_mutes"] + [e for e in sh["word_mutes"]
                                    if e and e[0] not in {x[0] for x in d["word_mutes"]}]
    if add_word and word_mutes and st.get("sentences"):
        for n, (a, b) in enumerate(st["sentences"]):
            t = " " + norm(" ".join(w["t"] for w in asr[a:b + 1])) + " "
            for ctx, words, cat in word_mutes:
                if ctx and " " + ctx + " " in t and add_word(n, words, cat, "You muted this before"):
                    n_added += 1
    ok_words = {p for p in set(d["claude_ok_words"]) | set(sh["ok_words"]) if _may_be_fine(p)}
    for m in st.get("mutes", []):
        s = d["words"].get(_word(m))
        if s and s["kept"] >= 2 and s["muted"] == 0:
            m["on"], m["note"] = False, "You usually keep this"
            n_w += 1
        elif phrase(m) in ok_words and not (s and s["muted"]):
            m["on"], m["note"] = False, "Learned: fine here"
            n_w += 1
    notes = []
    if n_added:
        notes.append(f"Cut or muted {n_added} thing(s) you removed before.")
    if n_kept or n_w:
        notes.append("Left unticked because of what CleanListen has learned: " + ", ".join(
            x for x in (f"{n_kept} passage(s)" if n_kept else "", f"{n_w} word(s)" if n_w else "") if x) + ".")
    return notes


MAX_NOTES = 40


def add_note(text, title="", everywhere=False):
    """Something they told the chat to keep in mind from now on ("it's Aladdin, the Genie's
    magic is fine"; Jason, 2026-10-30: the chat said it couldn't learn). Kept for this book
    (title) or for every book. Returns True if it's new."""
    text = " ".join(str(text).split())[:300]
    if not text:
        return False
    t = "" if everywhere else norm(title or "")
    d = load()
    if any(n["text"].lower() == text.lower() and n.get("title", "") == t for n in d["notes"]):
        return False
    d["notes"].append({"text": text, "title": t, "added": date.today().isoformat()})
    d["notes"] = d["notes"][-MAX_NOTES:]
    save(d)
    return True


def notes(title=""):
    """The notes for this book: for every book, then for this one."""
    t, out = norm(title or ""), []
    for n in load()["notes"]:
        if (not n.get("title") or n["title"] == t) and n["text"] not in out:
            out.append(n["text"])
    return out


def told(title=""):
    """The notes, ready to go at the top of an AI's instructions ("" if there are none)."""
    ns = notes(title)
    if not ns:
        return ""
    return ("They have told CleanListen to keep this in mind (follow it; it outweighs the "
            "examples):\n" + "\n".join(f"- {t}" for t in ns[:MAX_NOTES]))


def examples(n=12):
    """Some past choices for the AI readers: yours first, then Claude's, then shared."""
    d = load()
    sh = shared()
    out = {}
    for k in ("cut", "kept"):
        mine = d[k][-n:][::-1]
        theirs = [t for t in d["claude_" + k][::-1] if t not in mine][:n - len(mine)]
        built = [t for t in sh[k][::-1] if t not in mine + theirs]
        out[k] = (mine + theirs + built)[:n]
    return out


def examples_text(title=""):
    ex = examples()
    t = ("\n\n" + told(title)) if notes(title) else ""
    if not ex["cut"] and not ex["kept"]:
        return t
    t += "\n\nThis family's past choices (follow the same judgment):"
    if ex["cut"]:
        t += "\nThey CUT sentences like:\n" + "\n".join(f'- "{s}"' for s in ex["cut"])
    if ex["kept"]:
        t += "\nThey KEPT (not a problem) sentences like:\n" + "\n".join(f'- "{s}"' for s in ex["kept"])
    return t


def _may_be_fine(phrase_):
    """Only words that can be innocent ("dinner at hell") are ever learned as fine in a phrase;
    listed words like "sexual" are always muted (this also drops older wrong entries)."""
    try:
        import cleanlisten as E
        words = phrase_.split()
        for i, j, cat in E.find_language(words, list(E.ALL_CATS)):
            if j == len(words) or i >= len(words) - 2:   # the listed word(s) the phrase ends on
                if not E.may_untick_word({"cat": cat}, words[i:j]):
                    return False
        return True
    except Exception:
        return True


def record_claude(st, book=""):
    """Remember Claude's/ChatGPT's verdicts and keep them in a spreadsheet."""
    d = load()
    rows = []

    def t(sec):
        sec = int(sec)
        return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
    for sc in st.get("scenes", []):
        v = sc.get("claude_verdict")
        if not v:
            continue
        for s in _sentences(sc.get("text", "")):
            if v == "remove":
                _remember(d["claude_cut"], s)
            elif v in ("keep", "just the word"):
                _remember(d["claude_kept"], s)
        rows.append([f"Part {sc['part'] + 1} " + t(sc["s"]), "passage", sc.get("kind", ""),
                     sc.get("text", "")[:400], v, sc.get("claude_word", ""), sc.get("claude_reason", "")])
    for m in st.get("mutes", []):
        v = m.get("claude_verdict")
        if not v:
            continue
        if v == "keep":
            p = phrase(m)
            if p and p not in d["claude_ok_words"]:
                d["claude_ok_words"].append(p)
        rows.append([f"Part {m['part'] + 1} " + t(m["s"]), "word", m.get("cat", ""),
                     ((m.get("ctx_raw") or m.get("ctx", "")) + " [" + (m.get("word_raw") or m.get("word", "")) + "]").strip(),
                     v, "", m.get("claude_reason", "")])
    save(d)
    try:  # one file per book (a re-check replaces it), then one spreadsheet of everything
        FINDINGS.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", book) or "book"
        (FINDINGS / f"{name}.json").write_text(json.dumps(
            {"book": book, "date": date.today().isoformat(), "rows": rows,
             "reviewer": st.get("reviewer") or "Claude"}), encoding="utf8")
        allrows = []
        for f in sorted(FINDINGS.glob("*.json")):
            try:
                j = json.loads(f.read_text("utf8"))
            except Exception:
                continue
            allrows += [[j.get("date", ""), j.get("book", ""), j.get("reviewer", "Claude")] + r
                        for r in j.get("rows", [])]
        tmp = CSV_PATH.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Date", "Book", "Reviewer", "Where", "What", "Flagged as", "Text",
                        "Verdict", "Word", "Why"])
            w.writerows(allrows)
        os.replace(tmp, CSV_PATH)
    except OSError:
        pass


def export_book(st, title="", dest_dir=None):
    """Everything refined on one book (final decisions, your changes, Claude's/ChatGPT's
    reasons, the chat), plus everything learned so far - one file to send in."""
    out = {"what": "CleanListen refined", "date": date.today().isoformat(), "book": title,
           "filters": st.get("filters"), "notes": [st.get(k) for k in ("claude_note", "learn_note",
                                                                         "ai_note") if st.get(k)],
           "chat": st.get("chat_history", []), "items": [], "learned": load(), "findings": []}
    try:
        out["version"] = json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        pass

    def origin(x):
        if x.get("by_you"):
            return "you"
        if x.get("claude") or x.get("src") == "claude":
            return "Claude/ChatGPT/Gemini"
        if x.get("learned"):
            return "learned"
        if x.get("ai") or x.get("src") == "ai":
            return "AI on PC"
        return "word lists"
    for sc in st.get("scenes", []):
        out["items"].append({"type": "passage", "kind": sc.get("kind"), "part": sc.get("part"),
                             "start": sc.get("s"), "removed": bool(sc.get("cut", True)),
                             "origin": origin(sc), "note": sc.get("ai_note"),
                             "reason": sc.get("claude_reason"), "verdict": sc.get("claude_verdict"),
                             "trimmed": bool(sc.get("trimmed")), "chat": sc.get("chat_answer"),
                             "text": sc.get("text", "")})
    for m in st.get("mutes", []):
        out["items"].append({"type": "word", "kind": m.get("cat"), "part": m.get("part"),
                             "start": m.get("s"), "removed": bool(m.get("on", True)),
                             "origin": origin(m), "note": m.get("note"),
                             "reason": m.get("claude_reason"), "verdict": m.get("claude_verdict"),
                             "word": m.get("word_raw") or m.get("word"),
                             "text": f"{m.get('ctx_raw', '')} [{m.get('word_raw') or m.get('word', '')}] "
                                     f"{m.get('ctx_after_raw', '')}".strip()})
    if FINDINGS.exists():
        for f in sorted(FINDINGS.glob("*.json")):
            try:
                out["findings"].append(json.loads(f.read_text("utf8")))
            except Exception:
                pass
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    dest = Path(dest_dir) if dest_dir else next(
        (d for d in (home / "OneDrive" / "Desktop", home / "Desktop", home / "Documents") if d.exists()),
        APP_DATA)
    dest.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "", title)[:60].strip() or "book"
    path = dest / f"CleanListen refined - {safe} {out['date']}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf8")
    return path


def export(dest_dir=None):
    """Everything CleanListen has learned on this PC, in one file to send in."""
    out = {"what": "CleanListen learned", "date": date.today().isoformat(), "learned": load(),
           "findings": []}
    try:
        out["version"] = json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        pass
    if FINDINGS.exists():
        for f in sorted(FINDINGS.glob("*.json")):
            try:
                out["findings"].append(json.loads(f.read_text("utf8")))
            except Exception:
                pass
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    dest = Path(dest_dir) if dest_dir else next(
        (d for d in (home / "OneDrive" / "Desktop", home / "Desktop", home / "Documents") if d.exists()),
        APP_DATA)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"CleanListen learned {out['date']}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf8")
    return path
