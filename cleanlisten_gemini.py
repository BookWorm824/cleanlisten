"""
Gemini inside CleanListen, through Google's Antigravity CLI ("agy") on this PC.

Antigravity CLI is Google's own program (it replaced Gemini CLI for personal
Google accounts in June 2026). Signed in with your Google account it uses your
own Gemini allowance (the free tier, or Google AI Pro/Ultra; no API key,
nothing extra to pay). CleanListen sends it only the book's words as text,
never the audio. In headless mode agy can't approve writing files or running
commands, and it runs sandboxed in a folder holding just those words, so it
only reads and answers.

Same interface as cleanlisten_gpt.py: find, install, status, open_sign_in, ask.
Built from Google's published docs (agy 1.1.10 or newer); not yet tried on a
real account, so every failure is turned into a plain message.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}
MODEL = os.environ.get("CLEANLISTEN_GEMINI_MODEL", "")    # empty: your account's default
ARGV_MAX = 24000      # longer requests go in a file agy reads (Windows command lines max out ~32k)
REQUEST = "cleanlisten_request.md"


class GeminiError(Exception):
    pass


def find():
    exe = shutil.which("agy")
    if exe:
        return exe
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in (la / "agy" / "bin" / "agy.exe",
              la / "Microsoft" / "WinGet" / "Links" / "agy.exe",
              Path.home() / ".local" / "bin" / "agy"):
        if str(p) not in (".", "") and p.exists():
            return str(p)
    return None


def install(progress=None):
    """Run Google's own installer (per-user, no admin rights)."""
    say = progress or (lambda f, m: None)
    if os.name != "nt":
        raise GeminiError("Install Antigravity CLI from antigravity.google, then try again.")
    say(0.1, "Installing Antigravity CLI (Google's program that lets CleanListen talk to Gemini)…")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "irm https://antigravity.google/cli/install.ps1 | iex"],
                       capture_output=True, text=True, timeout=900, **_NOWIN)
    if not find():
        raise GeminiError("Antigravity CLI didn't install.\n\n" + (r.stderr or r.stdout)[-500:])
    say(1.0, "Antigravity CLI is installed.")


def _env():
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):   # always the Google account, never a paid key
        env.pop(k, None)
    return env


def signed_in():
    """agy has no sign-in check of its own; listing the models needs a signed-in account."""
    exe = find()
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env=_env(), **_NOWIN)
    except Exception:
        return False
    out = (r.stdout + r.stderr).lower()
    return r.returncode == 0 and bool(r.stdout.strip()) and not any(
        k in out for k in ("sign in", "log in", "login", "not authenticated", "unauthenticated"))


def open_sign_in():
    exe = find()
    if not exe:
        raise GeminiError("Antigravity CLI isn't installed yet.")
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "Sign in to Gemini", "cmd", "/k",
                          f'echo Sign in with your Google account in the browser window that '
                          f'opens. & echo When you see the agy prompt, you are signed in: close this '
                          f'window and go back to CleanListen. & echo. & "{exe}"'], env=_env())
    else:
        subprocess.Popen([exe], env=_env())


def status():
    if not find():
        return "missing"
    return "ready" if signed_in() else "signed_out"


def _answer(env, schema):
    """The structured answer from agy's JSON result (structured_output, else the response text,
    which may come wrapped in a ```json fence)."""
    so = env.get("structured_output")
    if isinstance(so, dict):
        return so
    text = env.get("response") or env.get("result") or ""
    if isinstance(text, dict):
        return text
    text = str(text).strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    try:
        ans = json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        try:
            ans = json.loads(text[a:b + 1]) if 0 <= a < b else None
        except ValueError:
            ans = None
    if isinstance(ans, dict):
        for k in ("toolAction", "toolSummary"):    # extra fields some agy versions add
            ans.pop(k, None)
    return ans if isinstance(ans, dict) else None


def ask(prompt, schema, stdin_text="", system=None, session=None, keep=False, timeout=600,
        folder=None):
    """One request to Gemini. Returns (answer_dict, conversation_id). With folder, it may
    read (only) the files in that folder - used for the book and findings in the chat."""
    exe = find()
    if not exe:
        raise GeminiError("Gemini isn't set up yet.")
    work = APP_DATA / "gemini"
    work.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=work))
    full = ((system + "\n\n") if system and not session else "") + prompt + (
        "\n\nOnly read the files in this folder; don't change anything, run commands or search "
        "the web." if folder else
        "\n\nAnswer only from the text given here. Don't run any commands, change files or "
        "search the web.")
    if stdin_text:
        full += "\n\n<stdin>\n" + stdin_text + "\n</stdin>"
    if schema:
        full += "\n\nReply with only one JSON object that fits this schema:\n" + json.dumps(schema)
    here = Path(folder) if folder else tmp
    req = here / REQUEST
    if len(full) <= ARGV_MAX:
        p = full
    else:   # too long for a command line: agy reads it from a file
        req.write_text(full, encoding="utf8")
        p = (f"Read the whole file {REQUEST} in this folder (all of it, every part) and do exactly "
             f"what it says. Don't change any files.")
    cmd = [exe, "-p", p, "--output-format", "json", "--sandbox",
           "--print-timeout", f"{max(60, int(timeout) - 30)}s"]
    if schema:
        sf = tmp / "schema.json"
        sf.write_text(json.dumps(schema), encoding="utf8")
        cmd += ["--json-schema", str(sf)]
    if MODEL:
        cmd += ["--model", MODEL]
    if session:
        cmd += ["--conversation", session]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace",
                           timeout=timeout, cwd=str(here), stdin=subprocess.DEVNULL, env=_env(),
                           **_NOWIN)
    except subprocess.TimeoutExpired:
        raise GeminiError("Gemini took too long to answer. Try again.")
    finally:
        try:
            req.unlink()
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)
    out = (r.stdout or "").strip()
    env = None
    for chunk in [out] + list(reversed(out.splitlines())):
        try:
            v = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(v, dict):
            env = v
            break
    answer = _answer(env, schema) if env else None
    st = str((env or {}).get("status") or "").upper()
    if answer is None or (st and st != "SUCCESS"):
        msg = " ".join(str(x) for x in ((env or {}).get("error"), r.stderr, "" if env else out) if x)[-400:]
        low = msg.lower()
        if any(k in low for k in ("sign in", "log in", "login", "unauthenticated", "not authenticated",
                                  "401", "credentials")):
            raise GeminiError("Gemini isn't signed in. Use the Sign in button, then try again.")
        if any(k in low for k in ("rate limit", "quota", "limit reached", "resource_exhausted",
                                  "429", "usage limit")):
            raise GeminiError("You've reached your Gemini limit for now. It resets after a while; "
                              "CleanListen's own checks still work meanwhile.")
        if st == "WAITING":
            raise GeminiError("Gemini stopped to ask for a permission CleanListen doesn't give. "
                              "Try again.")
        if not out:
            raise GeminiError("Gemini gave no answer. Update Antigravity CLI (run “agy update”) "
                              "and try again.")
        raise GeminiError("Gemini couldn't answer: " + (msg or out[-300:]))
    sid = (env or {}).get("conversation_id") or session
    return answer, sid
