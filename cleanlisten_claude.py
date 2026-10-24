"""Claude (or ChatGPT) for CleanListen: a whole-book double-check and a chat.

Claude runs through Claude Code (Anthropic's own program) signed in with the
user's Claude plan; ChatGPT runs through Codex (OpenAI's own program) with the
user's ChatGPT plan - the same way CleanView does, no API keys. Only the words of the
book (the transcript) and the list of findings are sent, never the audio.
Claude gets no tools for the double-check; for the chat it can only read and
search the two text files written for it (the book and the findings).
"""
import bisect
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cleanlisten as E

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
WORK = APP_DATA / "claude"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# Which Claude model to use (chosen in the app; remembered in settings.json)
MODELS = [("opus", "Opus (smartest)"), ("sonnet", "Sonnet (faster)"), ("haiku", "Haiku (fastest)")]
DEFAULT_MODEL = "opus"
SETTINGS = APP_DATA / "settings.json"


def get_model():
    try:
        m = json.loads(SETTINGS.read_text(encoding="utf-8")).get("claude_model")
        if m in dict(MODELS):
            return m
    except Exception:
        pass
    return DEFAULT_MODEL


def set_model(m):
    if m not in dict(MODELS):
        return
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    except Exception:
        data = {}
    data["claude_model"] = m
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception:
        pass
CHUNK_WORDS = 30000      # book text per request (about 40k tokens); long books go in sections
CONTEXT_SENTS = 12       # sentences shown before a section, for context only

KIND_NAMES = {"sex": "explicit sex scene", "ref": "sexual reference", "gore": "gory description",
              "religion": "religious content", "relationship": "same-sex / non-traditional relationship",
              "crude": "crude humor", "bully": "bullying", "flirt": "flirting",
              "added": "passage you chose to cut"}
CAT_NAMES = {"strong": "swearing (strong)", "moderate": "swearing", "mild": "mild word",
             "deity": "God's name as a swear", "minced": "soft substitute", "sexual": "sexual word",
             "orientation": "orientation word", "ai": "word found by AI", "claude": "word found by Claude"}

# What the family wants, filter by filter (from Lauren's own rules for CleanListen)
KIND_RULES = {
    "sex": "Explicit sex scenes: cut the explicit part of the scene. Kissing, romance, a couple "
           "going to bed or waking up together, beds and sheets are fine - only explicit sexual "
           "content is cut.",
    "ref": "Sexual references: cut sentences that talk about sex, sexual jokes or innuendo, "
           "someone being sexy or aroused, sleeping around, one-night stands. Ordinary romance, "
           "affection, dating, marriage and kissing are fine.",
    "gore": "Gory descriptions: cut overly graphic, gory descriptions of wounds, bodies or "
            "violence. Saying someone was shot, stabbed, killed or found dead, or some blood, is "
            "normal for a mystery and fine.",
    "religion": "Religious content: cut people explaining, preaching or debating religious "
                "beliefs, and anyone angry with, blaming, hating or denying God or losing their "
                "faith (e.g. 'I'm angry with God', 'God took my daughter', 'there is no God'). "
                "Fine: someone prayed, said grace, thanked God, believes in God, goes to church.",
    "relationship": "Same-sex and non-traditional relationships: cut sentences that show a "
                    "same-sex couple, romance or flirting (including a man flirting with a man), "
                    "throuples, polyamory, open marriages, swingers, polygamy. A man and woman "
                    "together is fine.",
    "crude": "Crude humor: cut toilet and gross-out jokes (farting, pooping, burping, boogers, "
             "pranks like that). Someone being sick or using the bathroom plainly is fine.",
    "bully": "Bullying: cut taunting, name-calling, mocking or picking on someone. An ordinary "
             "argument, a villain's plan or a police interrogation is fine.",
    "flirt": "Flirting: cut sentences where someone flirts, hits on, winks at or makes romantic "
             "advances toward someone. A married couple being affectionate is fine.",
}
CAT_RULES = {
    "strong": "Strong swearing: the f-word or c-word in any form - always mute.",
    "moderate": "Swearing: s***, b****, a**, a**hole, b******, p***ed, d***, and any word "
                "containing them (e.g. 'shitload', 'bullshit') - always mute.",
    "mild": "Mild words: damn, hell used as a curse, crap, bloody used as a curse, 'screw you' / "
            "'screw it'. 'Hell' as the place in religious talk, 'bloody' meaning covered in blood, "
            "or screwing something in, are fine.",
    "deity": "God's name as a swear: 'Oh my God', 'Jesus Christ', 'good Lord' as exclamations. "
             "'Thank God' is FINE (the family keeps it), as are prayers and sincere talk about God.",
    "minced": "Soft substitutes: gosh, heck, darn, dang, jeez, freaking, fricking.",
    "sexual": "Sexual words: sex, sexual, sexually, sexy, horny, aroused, orgasm and crude words for "
              "body parts - mute the word every time.",
    "orientation": "Orientation words: gay, lesbian, homosexual, bisexual, queer and slurs - mute "
                   "the word (e.g. 'Are you gay?'). 'Gay' meaning cheerful or bright is fine.",
}


class ClaudeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Which online AI: Claude or ChatGPT (chosen in the app; remembered)
# ---------------------------------------------------------------------------
NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}
PROVIDER = "claude"


def _settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_setting(k, v):
    data = _settings()
    data[k] = v
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception:
        pass


def use(provider):
    """Pick Claude or ChatGPT for everything below (and remember it)."""
    global PROVIDER
    PROVIDER = provider if provider in NAMES else "claude"
    _save_setting("reviewer", PROVIDER)


def saved_provider():
    p = _settings().get("reviewer")
    return p if p in NAMES else "claude"


def name(provider=None):
    return NAMES.get(provider or PROVIDER, "Claude")


def _gpt():
    try:
        import cleanlisten_gpt as gpt
        return gpt
    except Exception as ex:
        raise ClaudeError("The ChatGPT files are missing. Reopen CleanListen so it can update.") from ex


def _env():
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)   # always the Claude plan, never a paid API key
    return env


# ---------------------------------------------------------------------------
# Claude Code: find it, install it, sign in
# ---------------------------------------------------------------------------
def find_claude():
    p = shutil.which("claude")
    if p:
        return p
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for c in (home / ".local" / "bin" / "claude.exe", home / ".local" / "bin" / "claude",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "claude.exe"):
        if c.exists():
            return str(c)
    return None


def install(progress=None, provider=None):
    """One-time install of Claude Code (or Codex for ChatGPT) with the maker's own installer."""
    if (provider or PROVIDER) == "chatgpt":
        gpt = _gpt()
        try:
            gpt.install(progress)
            return gpt.find()
        except gpt.GptError as ex:
            raise ClaudeError(str(ex))
    say = progress or (lambda f, m: None)
    if find_claude():
        return find_claude()
    if os.name != "nt":
        raise ClaudeError("Claude Code isn't installed (see https://claude.ai/install.sh).")
    say(0.0, "Installing Claude Code (one time, about a minute)…")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "irm https://claude.ai/install.ps1 | iex"],
                       capture_output=True, text=True, timeout=900, creationflags=NO_WINDOW)
    exe = find_claude()
    if not exe:
        raise ClaudeError("Claude Code didn't install. " + ((r.stderr or r.stdout or "")[-300:]).strip())
    return exe


def status(provider=None):
    """'ok', 'signed_out' or 'missing'."""
    if (provider or PROVIDER) == "chatgpt":
        try:
            st = _gpt().status()
        except ClaudeError:
            return "missing"
        return "ok" if st == "ready" else st
    exe = find_claude()
    if not exe:
        return "missing"
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=60,
                           creationflags=NO_WINDOW, env=_env())
    except Exception:
        return "signed_out"
    if r.returncode != 0:
        return "signed_out"
    try:
        if json.loads(r.stdout).get("authMethod") in (None, "none"):
            return "signed_out"
    except Exception:
        pass
    return "ok"


def open_sign_in(provider=None):
    """Opens a small window that runs Claude's (or ChatGPT's) own sign-in in the browser."""
    if (provider or PROVIDER) == "chatgpt":
        gpt = _gpt()
        if not gpt.find():
            install(provider="chatgpt")
        try:
            return gpt.open_sign_in()
        except gpt.GptError as ex:
            raise ClaudeError(str(ex))
    exe = find_claude() or install(provider="claude")
    WORK.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        subprocess.Popen([exe, "auth", "login"], env=_env())
        return
    bat = WORK / "sign_in.cmd"
    bat.write_text("@echo off\r\ntitle Sign in to Claude\r\n"
                   "echo A browser window will open. Sign in with your Claude account,\r\n"
                   "echo then come back to CleanListen.\r\necho.\r\n"
                   f'"{exe}" auth login\r\necho.\r\n'
                   "echo All set - you can close this window.\r\npause\r\n", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=subprocess.CREATE_NEW_CONSOLE, env=_env())


def _friendly(text):
    t = (text or "").strip()
    low = t.lower()
    if any(k in low for k in ("not logged in", "please run /login", "invalid api key", "authentication",
                              "oauth", "log in", "login")):
        return f"{name()} isn't signed in. Press “Set up / sign in” and try again."
    if "limit" in low and ("usage" in low or "reached" in low or "rate" in low):
        return f"Your {name()} usage limit was reached. Try again after it resets."
    return t[-400:] or "Claude Code stopped without an answer."


def run(prompt, system, schema=None, resume=None, persist=False, tools="", cwd=None,
        timeout=1200, model=None):
    """One request. Claude: a `claude -p` call; ChatGPT: a `codex exec` call. Returns a dict
    with "data" (the structured answer when a schema is given) and "session_id"."""
    if PROVIDER == "chatgpt":
        gpt = _gpt()
        try:
            answer, sid = gpt.ask(prompt, schema, system=system, session=resume, keep=persist,
                                  timeout=timeout, folder=cwd if tools else None)
        except gpt.GptError as ex:
            raise ClaudeError(str(ex))
        if not isinstance(answer, dict):
            raise ClaudeError("ChatGPT didn't return its answer in the expected form.")
        return {"data": answer, "session_id": sid}
    exe = find_claude()
    if not exe:
        raise ClaudeError("Claude Code isn't installed yet. Press “Sign in to Claude” to set it up.")
    WORK.mkdir(parents=True, exist_ok=True)
    fd, sp = tempfile.mkstemp(prefix="system_", suffix=".txt", dir=WORK)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(system)
    model = model or get_model()
    args = [exe, "-p", "--output-format", "json", "--model", model, "--tools", tools,
            "--disallowedTools", "mcp__*", "--strict-mcp-config", "--system-prompt-file", sp]
    if tools:
        args += ["--allowedTools", tools]
    if schema:
        args += ["--json-schema", json.dumps(schema)]
    if not persist:
        args.append("--no-session-persistence")
    if resume:
        args += ["--resume", resume]
    try:
        r = subprocess.run(args, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout,
                           cwd=str(cwd or WORK), creationflags=NO_WINDOW, env=_env())
    except subprocess.TimeoutExpired:
        raise ClaudeError("Claude took too long to answer.")
    finally:
        try:
            os.remove(sp)
        except OSError:
            pass
    out = r.stdout.decode("utf-8", "replace").strip()
    res = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                res = json.loads(line)
                break
            except ValueError:
                continue
    if res is None:
        try:
            res = json.loads(out)
        except ValueError:
            raise ClaudeError(_friendly(out or r.stderr.decode("utf-8", "replace")))
    if res.get("is_error") or r.returncode != 0:
        raise ClaudeError(_friendly(str(res.get("result") or res.get("subtype") or
                                        r.stderr.decode("utf-8", "replace"))))
    if schema:
        so = res.get("structured_output")
        if not isinstance(so, dict):
            raise ClaudeError("Claude didn't return its answer in the expected form.")
        res["data"] = so
    return res


# ---------------------------------------------------------------------------
# The book and findings as text Claude can read
# ---------------------------------------------------------------------------
def sentence_texts(st, asr):
    return [" ".join(w["t"] for w in asr[a:b + 1]) for a, b in st["sentences"]]


def _sent_index(st):
    """word index -> sentence number (0-based)"""
    idx = {}
    for n, (a, b) in enumerate(st["sentences"]):
        for k in range(a, b + 1):
            idx[k] = n
    return idx


class _Locator:
    """Finds which sentences a finding covers, from its part and times (fast, by bisect)."""
    def __init__(self, st, asr):
        self.widx = _sent_index(st)
        self.by_part = {}
        for k, w in enumerate(asr):
            self.by_part.setdefault(w["part"], ([], []))
            self.by_part[w["part"]][0].append(w["s"])
            self.by_part[w["part"]][1].append(k)

    def span(self, item):
        starts, ks = self.by_part.get(item["part"], ([], []))
        if not ks:
            return 0, 0
        # words that start inside the finding (cuts end just before the next word starts)
        lo = bisect.bisect_left(starts, item["s"] - 0.01)
        hi = max(lo, bisect.bisect_left(starts, item["e"] - 0.08) - 1)
        lo, hi = min(lo, len(ks) - 1), min(hi, len(ks) - 1)
        return self.widx.get(ks[lo], 0), self.widx.get(ks[hi], 0)


def _word_of(m):
    return (m.get("word_raw") or m.get("word") or "").strip()


def findings_lines(st, asr, only=None):
    """One line per finding, with its ID, type, sentences and tick state."""
    loc = _Locator(st, asr)
    rows = []
    for sc in st["scenes"]:
        a, b = loc.span(sc)
        if only and not (only[0] <= a <= only[1]):
            continue
        note = f" · note: {sc['ai_note']}" if sc.get("ai_note") else ""
        if sc.get("by_you"):
            note += " · set by the family"
        rows.append((a, f"P{sc['id']} · cut passage · {KIND_NAMES.get(sc.get('kind'), sc.get('kind'))} "
                        f"· S{a + 1}" + (f"–S{b + 1}" if b != a else "") +
                        f" · {'ticked (will be cut)' if sc.get('cut', True) else 'UNticked (kept)'}{note}"))
    for m in st["mutes"]:
        a, _ = loc.span(m)
        if only and not (only[0] <= a <= only[1]):
            continue
        note = f" · note: {m['note']}" if m.get("note") else ""
        if m.get("by_you"):
            note += " · set by the family"
        rows.append((a, f"W{m['id']} · mute word · {CAT_NAMES.get(m.get('cat'), m.get('cat'))} "
                        f"· \"{_word_of(m)}\" in S{a + 1} · "
                        f"{'ticked (will be muted)' if m.get('on', True) else 'UNticked (kept)'}{note}"))
    rows.sort(key=lambda r: r[0])
    return [r[1] for r in rows]


def rules_text(st):
    f = st.get("filters") or {}
    kinds, cats = f.get("kinds", []), f.get("cats", [])
    on = [KIND_RULES[k] for k in kinds if k in KIND_RULES] + [CAT_RULES[c] for c in cats if c in CAT_RULES]
    off = [KIND_NAMES[k] for k in KIND_RULES if k not in kinds] + \
          [CAT_RULES[c].split(":")[0] for c in CAT_RULES if c not in cats]
    t = "The family's filters that are ON (follow them exactly):\n" + "\n".join(f"- {x}" for x in on)
    if off:
        t += ("\n\nFilters that are OFF - do not flag these: " + "; ".join(off) + ".")
    return t


SYSTEM_REVIEW = """You double-check an audiobook filter for a family who wants to listen to \
audiobooks with certain content removed. A word-list filter (and sometimes a small local AI) has \
already gone through the book and listed FINDINGS: passages it plans to cut (IDs starting with P) \
and single words it plans to mute (IDs starting with W). You read the book text yourself, in \
context, and decide:
1. For EVERY finding listed: is it really something the family's rules remove ("remove"), or is it \
not an issue ("keep")? For a passage whose ONLY problem is one word or a few words (e.g. "one \
sweet-ass deal"), answer "just_the_word" and put those exact words in "words" and their kind of \
language in "word_type" - the family mutes just the word and keeps the sentence.
2. What did the filter MISS that the family's rules say should be removed?

{rules}

How to judge:
- Judge by the family's rules above, in context - not by single words. Read the sentences around \
each finding. Ordinary story content (romance, kissing, marriage, danger, crime, death, a body \
being found, plain violence, praying) stays unless a rule above covers it.
- Listed words (the W findings) are muted EVERY time they're said - in a denial ("it's not \
sexual"), a question, a quote or a joke. Say "keep" for a word only when it has a different, \
innocent meaning right there (hell as the place, bloody meaning covered in blood, ass meaning a \
donkey, gay meaning cheerful, God or Jesus in a sincere prayer, screwing something in) or the \
narrator didn't actually say it (misheard).
- The text comes from speech recognition, so some words are misheard. Judge what the narrator \
really said: a misheard swear word is still swearing; a normal word that was misheard as a swear \
word is not (say so and set misheard to true).
- Sentences are numbered S1, S2, ... For missed passages give the first and last sentence numbers \
covering only what needs cutting (whole sentences, as few as possible). For missed words give the \
sentence number and the exact word or words as they appear in that sentence.
- Don't list something again that is already a finding.
- confidence "high" means you are sure. Use "medium" when it's a judgment call - the family will \
decide those themselves.
- Some findings say "set by the family": they decided those themselves. Still give your view, but \
know your answer won't change them.
- Every reason: plain English, under 20 words.{examples}"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "verdict": {"type": "string", "enum": ["remove", "keep", "just_the_word"]},
            "words": {"type": "string"}, "word_type": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium"]},
            "misheard": {"type": "boolean"},
            "reason": {"type": "string"}},
            "required": ["id", "verdict", "confidence", "reason"]}},
        "missed_passages": {"type": "array", "items": {"type": "object", "properties": {
            "from": {"type": "string"}, "to": {"type": "string"},
            "type": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium"]},
            "reason": {"type": "string"}},
            "required": ["from", "to", "type", "confidence", "reason"]}},
        "missed_words": {"type": "array", "items": {"type": "object", "properties": {
            "sentence": {"type": "string"}, "words": {"type": "string"},
            "type": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium"]},
            "reason": {"type": "string"}},
            "required": ["sentence", "words", "type", "confidence", "reason"]}},
    },
    "required": ["decisions", "missed_passages", "missed_words"],
}


def _sections(texts):
    """Split the book into sections of about CHUNK_WORDS words."""
    out, start, count = [], 0, 0
    for n, t in enumerate(texts):
        count += len(t.split())
        if count >= CHUNK_WORDS:
            out.append((start, n))
            start, count = n + 1, 0
    if start < len(texts):
        out.append((start, len(texts) - 1))
    return out or [(0, -1)]


def _snum(v):
    m = re.search(r"\d+", str(v))
    return int(m.group()) - 1 if m else None


CLEAR_SWEARS = {"strong", "moderate"}


# ---------------------------------------------------------------------------
# Applying Claude's answers
# ---------------------------------------------------------------------------
def _add_passage(st, asr, a, b, kind, on, note, reason, src="claude"):
    sents = st["sentences"]
    if not (0 <= a <= b < len(sents)):
        return False
    wa, wb = sents[a][0], sents[b][1]
    if asr[wa]["part"] != asr[wb]["part"]:
        return False
    s_, e_ = E.span_times(asr, wa, wb)
    part = asr[wa]["part"]
    for x in st["scenes"]:   # already covered (edges may touch the neighbour by a fraction)
        if x["part"] == part and e_ - 0.3 > x["s"] and s_ + 0.3 < x["e"]:
            return False
    sc = {"id": max([x.get("id", 0) for x in st["scenes"]] + [0]) + 1, "kind": kind,
          "part": part, "s": s_, "e": e_, "cut": on, "ai_note": note,
          "text": " ".join(w["t"] for w in asr[wa:wb + 1])}
    if src == "claude":
        sc.update(claude=True, claude_reason=reason, claude_verdict="remove" if on else "suggested")
    else:
        sc.update(learned=src)
    st["scenes"].append(sc)
    return True


def _add_word(st, asr, si, words, cat, on, note, reason):
    sents = st["sentences"]
    target = [E.norm(w) for w in str(words).split() if E.norm(w)]
    if not target or not (0 <= si < len(sents)):
        return False
    a_, b_ = sents[si]
    span = [asr[x]["n"] for x in range(a_, b_ + 1)]
    hit = next((x for x in range(len(span)) if span[x:x + len(target)] == target), None)
    if hit is None:
        return False
    i, j = a_ + hit, a_ + hit + len(target)
    part = asr[i]["part"]
    if any(m["part"] == part and not (asr[j - 1]["e"] < m["s"] or asr[i]["s"] > m["e"]) for m in st["mutes"]):
        return False
    s_, e_ = asr[i]["s"], asr[j - 1]["e"]
    try:
        s_, e_ = E.snap_edges(st["parts"][part], s_, e_)
    except Exception:
        pass
    ctx = [w["t"] for w in asr[max(0, i - 6):j + 5]]
    st["mutes"].append({"id": max([m["id"] for m in st["mutes"]] + [0]) + 1, "part": part,
                        "s": s_, "e": e_, "cat": cat, "src": "claude", "i": i, "j": j,
                        "word": " ".join(E.mask(asr[x]["t"]) for x in range(i, j)),
                        "ctx": E._masked_text([w["t"] for w in asr[max(0, i - 6):i]]),
                        "ctx_after": E._masked_text([w["t"] for w in asr[j:j + 5]]),
                        **E.raw_fields(ctx, min(i, 6), min(i, 6) + (j - i)),
                        "on": on, "note": note, "claude_reason": reason,
                        "claude_verdict": "remove" if on else "suggested"})
    st["mutes"].sort(key=lambda m: (m["part"], m["s"]))
    return True


def _norm_kind(t, kinds):
    t = str(t).lower()
    for k in kinds:
        if k == t or KIND_NAMES.get(k, "").split(" ")[0] in t or k in t:
            return k
    return None


def _norm_cat(t, cats):
    t = str(t).lower()
    for c in cats:
        if c == t or c in t:
            return c
    if "swear" in t or "profan" in t or "curse" in t:
        for c in ("moderate", "strong", "mild"):
            if c in cats:
                return c
    if "god" in t or "deity" in t:
        return "deity" if "deity" in cats else None
    return None


def apply_review(st, data, counts, asr=None):
    """Apply one section's answer. counts collects totals for the summary line.
    Anything the family set themselves keeps their choice (only the reason is shown)."""
    N = name()
    by_id = {f"P{sc['id']}": ("P", sc) for sc in st["scenes"]}
    by_id.update({f"W{m['id']}": ("W", m) for m in st["mutes"]})
    cats = (st.get("filters") or {}).get("cats", [])
    for d in data.get("decisions", []):
        hit = by_id.get(str(d.get("id", "")).strip().upper())
        if not hit:
            continue
        kind, it = hit
        reason = str(d.get("reason", "")).strip()
        sure = d.get("confidence") == "high"
        key = "cut" if kind == "P" else "on"
        verdict = d.get("verdict")
        it["claude_reason"] = reason
        it["claude_verdict"] = {"keep": "keep", "just_the_word": "just the word"}.get(verdict, "remove")
        if it.get("by_you"):
            it["ai_note" if kind == "P" else "note"] = (
                f"{N} agrees" if (verdict == "remove") == bool(it.get(key, True)) else f"Your call ({N} differs)")
            continue
        if verdict == "just_the_word" and kind == "P" and asr is not None:
            # keep the sentence, mute only the word(s)
            loc = _Locator(st, asr)
            a, b = loc.span(it)
            words = str(d.get("words", "")).strip()
            cat = _norm_cat(d.get("word_type") or "swearing", cats or list(CAT_RULES)) or "moderate"
            first = E.norm(words.split()[0]) if words else ""
            already = bool(first) and any(
                m["part"] == it["part"] and it["s"] - 0.5 <= m["s"] <= it["e"] + 0.5
                and first in E.norm(m.get("word_raw") or m.get("word", "")) for m in st["mutes"])
            added = already or (any(_add_word(st, asr, si, words, cat, True, f"{N}: just the word", reason)
                                    for si in range(a, b + 1)) if words else False)
            if added or not sure:
                it[key] = False if added else it.get(key, True)
                it["ai_note"] = f"{N}: just the word" if added else f"{N} unsure"
                it["claude_word"] = words
                counts["word" if added else "unsure"] += 1
                continue
            verdict = "remove"
        if verdict == "keep" or verdict == "just_the_word":
            if kind == "W" and not d.get("misheard") and not E.may_untick_word(it):
                # listed words are always muted unless misheard or innocent in meaning
                if not it.get(key, True):
                    it[key] = True            # e.g. unticked earlier by the AI on this PC
                    counts["on"] += 1
                it["claude_verdict"] = "unsure"
                note = f"Muted ({N} questioned it)"
            elif sure:
                it[key] = False
                note = f"{N}: fine"
                counts["off"] += 1
            else:
                note = f"{N} unsure"
                it["claude_verdict"] = "unsure"
                counts["unsure"] += 1
        else:
            if sure and not it.get(key, True):
                it[key] = True
                counts["on"] += 1
            note = f"{N} agrees"
            counts["agree"] += 1
        it["ai_note" if kind == "P" else "note"] = note
    return counts


def review(st, asr, progress=None, cancel=None):
    """Claude reads the whole book, section by section, with every finding marked,
    and decides what's really an issue and what was missed. Changes st in place."""
    say = progress or (lambda f, m: None)
    if not st.get("sentences"):
        raise ClaudeError("this result is from an older version - press Re-check first")
    N = name()
    if status() != "ok":
        raise ClaudeError(f"{N} isn't set up or signed in yet")
    for n, m in enumerate(st["mutes"], 1):
        m.setdefault("id", n)
    try:
        import cleanlisten_learn as learn
        examples = learn.examples_text()
    except Exception:
        learn, examples = None, ""
    f = st.get("filters") or {}
    kinds, cats = f.get("kinds", []), f.get("cats", [])
    texts = sentence_texts(st, asr)
    system = SYSTEM_REVIEW.format(rules=rules_text(st), examples=examples)
    secs = _sections(texts)
    counts = {"agree": 0, "off": 0, "unsure": 0, "on": 0, "found": 0, "suggested": 0, "word": 0}
    errors = []
    for n, (a, b) in enumerate(secs):
        if cancel and cancel():
            raise KeyboardInterrupt
        say(n / len(secs), f"{N} is reading the book · section {n + 1} of {len(secs)}")
        ctx0 = max(0, a - CONTEXT_SENTS)
        lines = []
        if ctx0 < a:
            lines.append("(Earlier sentences, for context only - already checked:)")
            lines += [f"S{k + 1}: {texts[k]}" for k in range(ctx0, a)]
            lines.append("(Section to check starts here:)")
        lines += [f"S{k + 1}: {texts[k]}" for k in range(a, b + 1)]
        finds = findings_lines(st, asr, only=(a, b))
        prompt = (f"BOOK TEXT - section {n + 1} of {len(secs)} (sentences S{a + 1} to S{b + 1}):\n\n"
                  + "\n".join(lines) + "\n\nFINDINGS IN THIS SECTION:\n" +
                  ("\n".join(finds) if finds else "(none)") +
                  "\n\nGive a decision for every finding ID above, then list anything missed in "
                  "sentences S%d to S%d." % (a + 1, b + 1))
        try:
            data = run(prompt, system, schema=REVIEW_SCHEMA)["data"]
        except ClaudeError as ex:
            errors.append(str(ex))
            if "signed in" in str(ex) or "limit" in str(ex):
                break
            continue
        apply_review(st, data, counts, asr)
        for p in data.get("missed_passages", []):
            k = _norm_kind(p.get("type"), kinds)
            pa, pb = _snum(p.get("from")), _snum(p.get("to"))
            if k is None or pa is None:
                continue
            sure = p.get("confidence") == "high"
            if _add_passage(st, asr, pa, pb if pb is not None else pa, k, sure,
                            f"Found by {N}" if sure else f"{N} suggests", str(p.get("reason", ""))):
                counts["found" if sure else "suggested"] += 1
        for w in data.get("missed_words", []):
            c = _norm_cat(w.get("type"), cats)
            si = _snum(w.get("sentence"))
            if c is None or si is None:
                continue
            sure = w.get("confidence") == "high"
            if _add_word(st, asr, si, w.get("words", ""), c, sure,
                         f"Found by {N}" if sure else f"{N} suggests", str(w.get("reason", ""))):
                counts["found" if sure else "suggested"] += 1
    st["scenes"].sort(key=lambda x: (x["part"], x["s"]))
    say(1.0, f"{N} check done")
    note = (f"{N} read the whole book: agreed with {counts['agree']}, unticked {counts['off']} it "
            f"says aren't an issue, found {counts['found']} more (ticked) and suggested "
            f"{counts['suggested']} for you to decide (unticked)."
            + (f" For {counts['word']} it mutes just the bad word and keeps the sentence." if counts["word"] else "")
            + (f" {counts['unsure']} it wasn't sure about are marked “{N} unsure”." if counts["unsure"] else ""))
    if errors:
        note += f" Some sections couldn't be checked: {errors[0]}"
    st["claude_note"] = note
    st["claude_checked"] = True
    st["reviewer"] = N
    if learn is not None:
        try:   # Claude's calls teach the AI on this PC, and go in the findings spreadsheet
            learn.record_claude(st, book=st.get("title", ""))
        except Exception:
            pass
    return st


# ---------------------------------------------------------------------------
# Ask Claude: a chat about the whole book
# ---------------------------------------------------------------------------
SYSTEM_CHAT = """You help a family fine-tune what CleanListen removes from an audiobook. In your \
working folder are two files:
- book.txt: the whole book as numbered sentences (S1, S2, ...), from speech recognition, so some \
words may be misheard.
- findings.txt: everything CleanListen currently plans to cut (P = passage) or mute (W = word), \
with whether each is ticked, plus any notes. It is rewritten before every message, so read it \
again when the family asks about the findings.

Use Read and Grep on those files to look over everything in context - don't judge from a single \
line. When asked to check something, check the whole book, not just one scene.

{rules}

Answer in plain, friendly English, short and to the point (the family is not technical). Never \
mention IDs like P12, W40 or S300 in your answer - the family can't see them; quote a few words \
of the sentence instead. Don't spell out swear words in your answer (write s***). If your answer \
means the list should change, put each change in "changes":
- {{"action": "untick", "id": "P12"}} or {{"action": "tick", "id": "W40"}} for existing findings
- {{"action": "add_passage", "from": "S300", "to": "S302", "type": one of {kinds}, "reason": "..."}}
- {{"action": "add_word", "sentence": "S410", "words": "exact words", "type": one of {cats}, "reason": "..."}}
Only include changes you are confident about; the family will see them and choose to apply them."""

CHAT_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"},
    "changes": {"type": "array", "items": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["untick", "tick", "add_passage", "add_word"]},
        "id": {"type": "string"}, "from": {"type": "string"}, "to": {"type": "string"},
        "sentence": {"type": "string"}, "words": {"type": "string"}, "type": {"type": "string"},
        "reason": {"type": "string"}}, "required": ["action"]}}},
    "required": ["answer", "changes"]}


class Chat:
    def __init__(self, st, asr, folder):
        self.st, self.asr = st, asr
        self.dir = Path(folder) / "claude_chat"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session = None
        texts = sentence_texts(st, asr)
        (self.dir / "book.txt").write_text("\n".join(f"S{k + 1}: {t}" for k, t in enumerate(texts)),
                                           encoding="utf-8")

    def _write_findings(self):
        head = []
        if self.st.get("claude_note"):
            head.append("The earlier whole-book check: " + self.st["claude_note"])
        lines = findings_lines(self.st, self.asr)
        reasons = {}
        for sc in self.st["scenes"]:
            if sc.get("claude_reason"):
                reasons[f"P{sc['id']}"] = sc["claude_reason"]
        for m in self.st["mutes"]:
            if m.get("claude_reason"):
                reasons[f"W{m['id']}"] = m["claude_reason"]
        out = []
        for ln in lines:
            fid = ln.split(" ", 1)[0]
            out.append(ln + (f" · reviewer's reason: {reasons[fid]}" if fid in reasons else ""))
        (self.dir / "findings.txt").write_text("\n".join(head + [""] + out), encoding="utf-8")

    def ask(self, question):
        self._write_findings()
        f = self.st.get("filters") or {}
        system = SYSTEM_CHAT.format(rules=rules_text(self.st),
                                    kinds=", ".join(f.get("kinds", [])) or "(none on)",
                                    cats=", ".join(f.get("cats", [])) or "(none on)")
        res = run(question + "\n\n(findings.txt has just been updated.)", system, schema=CHAT_SCHEMA,
                  resume=self.session, persist=True, tools="Read,Grep,Glob", cwd=self.dir,
                  timeout=900)
        self.session = res.get("session_id") or self.session
        data = res["data"]
        return str(data.get("answer", "")).strip(), [c for c in data.get("changes", []) if isinstance(c, dict)]

    def _snip(self, text, n=12):
        words = E._masked_text(str(text).split()).split()
        return "“" + " ".join(words[:n]) + ("…" if len(words) > n else "") + "”"

    def describe(self, c):
        """The change in plain words, quoting the book (swear words starred out)."""
        a = c.get("action")
        if a in ("tick", "untick"):
            fid = str(c.get("id", "")).strip().upper()
            for sc in self.st["scenes"]:
                if f"P{sc['id']}" == fid:
                    what = KIND_NAMES.get(sc.get("kind"), "passage")
                    verb = "Cut" if a == "tick" else "Keep (don’t cut)"
                    return f"{verb} the {what}: " + self._snip(sc.get("text", ""))
            for m in self.st["mutes"]:
                if f"W{m['id']}" == fid:
                    verb = "Mute" if a == "tick" else "Don’t mute"
                    return (f"{verb} “{m.get('word', '')}” in …{m.get('ctx', '')} "
                            f"{m.get('word', '')} {m.get('ctx_after', '')}…")
            return ("Tick" if a == "tick" else "Untick") + " an item"
        texts = sentence_texts(self.st, self.asr)
        if a == "add_passage":
            pa, pb = _snum(c.get("from")), _snum(c.get("to"))
            pb = pb if pb is not None else pa
            kind = KIND_NAMES.get(_norm_kind(c.get("type"), list(KIND_NAMES)) or "", c.get("type"))
            if pa is not None and 0 <= pa <= pb < len(texts):
                return f"Also cut ({kind}): " + self._snip(" ".join(texts[pa:pb + 1]), 18)
            return f"Also cut a passage ({kind})"
        if a == "add_word":
            si = _snum(c.get("sentence"))
            w = E._masked_text(str(c.get("words", "")).split())
            if si is not None and 0 <= si < len(texts):
                return f"Also mute “{w}” in " + self._snip(texts[si], 14)
            return f"Also mute “{w}”"
        return str(a)

    def apply(self, changes):
        """Apply the changes the family accepted; returns how many took effect."""
        f = self.st.get("filters") or {}
        # you approve each change yourself, so any type is allowed (ticked filters first)
        kinds = f.get("kinds", []) + [k for k in KIND_NAMES if k not in f.get("kinds", [])]
        cats = f.get("cats", []) + [c for c in CAT_RULES if c not in f.get("cats", [])]
        by_id = {f"P{sc['id']}": ("cut", sc) for sc in self.st["scenes"]}
        by_id.update({f"W{m['id']}": ("on", m) for m in self.st["mutes"]})
        done = 0
        for c in changes:
            a = c.get("action")
            reason = str(c.get("reason", "")).strip()
            if a in ("tick", "untick"):
                hit = by_id.get(str(c.get("id", "")).strip().upper())
                if hit:
                    key, it = hit
                    it[key] = a == "tick"
                    it["ai_note" if key == "cut" else "note"] = f"{name()} chat"
                    it["by_you"] = True
                    if reason:
                        it["claude_reason"] = reason
                    done += 1
            elif a == "add_passage":
                k = _norm_kind(c.get("type"), kinds)
                pa, pb = _snum(c.get("from")), _snum(c.get("to"))
                if k and pa is not None and _add_passage(self.st, self.asr, pa, pb if pb is not None else pa,
                                                         k, True, f"{name()} chat", reason):
                    done += 1
            elif a == "add_word":
                cat = _norm_cat(c.get("type"), cats) or (cats[0] if cats else "moderate")
                si = _snum(c.get("sentence"))
                if si is not None and _add_word(self.st, self.asr, si, c.get("words", ""), cat, True,
                                                f"{name()} chat", reason):
                    done += 1
        self.st["scenes"].sort(key=lambda x: (x["part"], x["s"]))
        return done

PROVIDER = saved_provider()
