"""
CleanView's AI helpers, all running on your own computer:

- CLIP (OpenAI's free image model) scores every frame against plain-English
  descriptions: kissing, gore, a gun pointed at someone, smoking, a couple in
  bed. It finds candidate scenes even when they make no sound.
- A local language-and-vision model run by Ollama (gemma3:4b) takes a second
  look at those candidates (who is kissing, light or passionate, is it really
  gore) and reads the dialogue for sexual references, sleeping around and
  relationship talk.

Every step is optional: if a model is missing or fails, CleanView carries on
without it.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CLIP_DIR = HERE / "models" / "clip-vit-base-patch32"
CLIP_BASE = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
CLIP_FILES = {"vision_model_quantized.onnx": "onnx/vision_model_quantized.onnx",
              "text_model_quantized.onnx": "onnx/text_model_quantized.onnx",
              "tokenizer.json": "tokenizer.json"}
OLLAMA = os.environ.get("CLEANVIEW_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("CLEANVIEW_MODEL", "gemma3:4b")
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


# ---------------------------------------------------------------------------
# What CLIP looks for. Each frame is compared with all of these; a category
# "wins" a frame when its descriptions beat the everyday ones.
# ---------------------------------------------------------------------------
EVERYDAY = [
    "people talking", "a person standing", "a close-up of a face", "a landscape",
    "a room", "people walking", "a city street", "people eating at a table", "a car",
    "people hugging", "a group of people", "a person sitting", "an animal",
    "a person smiling", "a dark scene", "text on a screen", "a person running",
    "a person cooking", "children playing", "a person lying in bed asleep",
]
CLIP_CATS = {
    "kiss": ["two people kissing on the lips", "a couple kissing", "a passionate kiss"],
    "kiss_mf": ["a man and a woman kissing"],
    "kiss_mm": ["two men kissing"],
    "kiss_ff": ["two women kissing"],
    "bed": ["a couple in bed together", "a couple making out", "two people undressing each other"],
    "gore": ["a bloody wound", "gore and blood", "a dead body covered in blood",
             "a person being stabbed", "a person being shot with blood"],
    "fight": ["people fighting", "a person punching another person",
              "a person pointing a gun at someone", "a violent attack"],
    "smoking": ["a person smoking a cigarette", "a person smoking"],
    "drinking": ["a person drinking alcohol", "people drinking beer", "a glass of wine"],
    "drugs": ["a person using drugs", "a person snorting cocaine", "a person injecting drugs"],
    "immodest": ["a woman in a bikini", "a person in revealing underwear",
                 "a woman in a revealing low-cut outfit"],
}
# kiss_mf / kiss_mm / kiss_ff only decide *who*, never whether there is a kiss
WHO = ("kiss_mf", "kiss_mm", "kiss_ff")


def clip_prompts():
    names, texts = [], []
    for t in EVERYDAY:
        names.append("everyday")
        texts.append(f"a movie still of {t}")
    for cat, ts in CLIP_CATS.items():
        for t in ts:
            names.append(cat)
            texts.append(f"a movie still of {t}")
    return names, texts


def clip_ready():
    import importlib.util
    return (all((CLIP_DIR / f).exists() for f in CLIP_FILES)
            and importlib.util.find_spec("tokenizers") is not None
            and importlib.util.find_spec("onnxruntime") is not None)


def download(url, dest, progress=None, label=""):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "CleanView"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            got += len(b)
            if progress and total:
                progress(got / total, f"{label} {got / 1e6:.0f} of {total / 1e6:.0f} MB")
    os.replace(tmp, dest)


def install_clip(pip_python, progress=None):
    say = progress or (lambda f, m: None)
    import importlib.util
    if importlib.util.find_spec("tokenizers") is None:
        say(0.0, "Getting the picture AI's word reader…")
        r = subprocess.run([pip_python, "-m", "pip", "install", "--quiet",
                            "--disable-pip-version-check", "tokenizers"],
                           capture_output=True, text=True, **_NOWIN)
        if r.returncode != 0:
            raise RuntimeError("Couldn't download the picture AI.\n" + r.stderr[-500:])
        importlib.invalidate_caches()
    names = list(CLIP_FILES)
    for i, name in enumerate(names):
        if (CLIP_DIR / name).exists():
            continue
        download(CLIP_BASE + CLIP_FILES[name], CLIP_DIR / name,
                 lambda f, m, i=i: say((i + f) / len(names), "Getting the picture AI (one time) · " + m),
                 "")


# ---------------------------------------------------------------------------
# Image helpers (numpy only, no extra libraries)
# ---------------------------------------------------------------------------
def resize(img, w, h):
    """Bilinear resize of an HxWx3 uint8/float image."""
    H, W = img.shape[:2]
    if (W, H) == (w, h):
        return img.astype(np.float32)
    ys = (np.arange(h) + 0.5) * H / h - 0.5
    xs = (np.arange(w) + 0.5) * W / w - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, H - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, W - 1)
    y1, x1 = np.clip(y0 + 1, 0, H - 1), np.clip(x0 + 1, 0, W - 1)
    wy = np.clip(ys - np.floor(ys), 0, 1)[:, None, None]
    wx = np.clip(xs - np.floor(xs), 0, 1)[None, :, None]
    a = img.astype(np.float32)
    top = a[y0][:, x0] * (1 - wx) + a[y0][:, x1] * wx
    bot = a[y1][:, x0] * (1 - wx) + a[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


def nudenet_input(rgb):
    """NudeNet's own preparation: pad to a square (bottom/right), shrink to
    320, BGR channel order, 0..1."""
    H, W = rgb.shape[:2]
    s = 320 / max(H, W)
    w, h = max(1, round(W * s)), max(1, round(H * s))
    out = np.zeros((320, 320, 3), np.float32)
    out[:h, :w] = resize(rgb, w, h)
    return out[:, :, ::-1].transpose(2, 0, 1) / 255.0


CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def clip_crops(rgb):
    """224x224 crops covering the whole width (wide movie frames get three)."""
    H, W = rgb.shape[:2]
    s = 224 / min(H, W)
    w, h = max(224, round(W * s)), max(224, round(H * s))
    img = resize(rgb, w, h)
    if w / h > 1.4:
        xs = [0, (w - 224) // 2, w - 224]
    else:
        xs = [(w - 224) // 2]
    y = (h - 224) // 2
    crops = [img[y:y + 224, x:x + 224] for x in xs]
    return [((c / 255.0 - CLIP_MEAN) / CLIP_STD).transpose(2, 0, 1) for c in crops]


class Clip:
    def __init__(self, ort, threads=4):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.vis = ort.InferenceSession(str(CLIP_DIR / "vision_model_quantized.onnx"), opts,
                                        providers=["CPUExecutionProvider"])
        self.vin = self.vis.get_inputs()[0].name
        outs = [o.name for o in self.vis.get_outputs()]
        self.vout = "image_embeds" if "image_embeds" in outs else outs[0]
        self.names, texts = clip_prompts()
        self.text = self._text_embeds(ort, texts, opts)

    def _text_embeds(self, ort, texts, opts):
        key = hashlib.sha1("\n".join(texts).encode()).hexdigest()[:12]
        cache = CLIP_DIR / f"text_{key}.npy"
        if cache.exists():
            return np.load(cache)
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(CLIP_DIR / "tokenizer.json"))
        sess = ort.InferenceSession(str(CLIP_DIR / "text_model_quantized.onnx"), opts,
                                    providers=["CPUExecutionProvider"])
        ins = [i.name for i in sess.get_inputs()]
        outs = [o.name for o in sess.get_outputs()]
        oname = "text_embeds" if "text_embeds" in outs else outs[0]
        embs = []
        for t in texts:
            ids = np.array([tok.encode(t).ids[:77]], dtype=np.int64)
            feed = {"input_ids": ids}
            if "attention_mask" in ins:
                feed["attention_mask"] = np.ones_like(ids)
            e = sess.run([oname], feed)[0][0]
            embs.append(e / np.linalg.norm(e))
        arr = np.stack(embs).astype(np.float32)
        np.save(cache, arr)
        return arr

    def scores(self, rgb):
        """Per-category probability for one frame (max over its crops)."""
        crops = np.stack(clip_crops(rgb)).astype(np.float32)
        e = self.vis.run([self.vout], {self.vin: crops})[0]
        e = e / np.linalg.norm(e, axis=1, keepdims=True)
        logits = 100.0 * e @ self.text.T                       # (crops, prompts)
        out = {}
        main = [i for i, n in enumerate(self.names) if n not in WHO]
        lm = logits[:, main]
        p = np.exp(lm - lm.max(axis=1, keepdims=True))
        p /= p.sum(axis=1, keepdims=True)
        mnames = [self.names[i] for i in main]
        for cat in CLIP_CATS:
            if cat in WHO:
                continue
            idx = [k for k, n in enumerate(mnames) if n == cat]
            out[cat] = float(p[:, idx].sum(axis=1).max())
        # who is kissing: compare the three "who" descriptions on the crop
        # that looked most like a kiss
        best = int(p[:, [k for k, n in enumerate(mnames) if n == "kiss"]].sum(axis=1).argmax())
        who = [i for i, n in enumerate(self.names) if n in WHO]
        lw = logits[best, who]
        pw = np.exp(lw - lw.max())
        pw /= pw.sum()
        for k, i in enumerate(who):
            out[self.names[i]] = float(pw[k])
        return out


# ---------------------------------------------------------------------------
# Turning CLIP scores into candidate scenes
# ---------------------------------------------------------------------------
THRESH = {"kiss": 0.45, "bed": 0.5, "gore": 0.45, "fight": 0.55, "smoking": 0.55,
          "drinking": 0.6, "drugs": 0.5, "immodest": 0.55}


def clip_candidates(clipdata, wanted, gap=4.0, pad=1.0):
    """Runs of frames where a wanted category wins. Returns
    [{"cat", "s", "e", "peak_t", "peak", "who": {...}, "frames": [...]}]."""
    if not clipdata or not clipdata.get("t"):
        return []
    ts, rows = clipdata["t"], clipdata["scores"]
    out = []
    for cat in wanted:
        th = THRESH[cat]
        hits = [(t, r) for t, r in zip(ts, rows) if r.get(cat, 0) >= th]
        runs = []
        for t, r in hits:
            if runs and t - runs[-1][-1][0] <= gap:
                runs[-1].append((t, r))
            else:
                runs.append([(t, r)])
        for run in runs:
            if len(run) == 1 and run[0][1][cat] < th + 0.2:
                continue   # one weak frame is usually nothing
            peak = max(run, key=lambda x: x[1][cat])
            who = {}
            if cat == "kiss":
                for w in WHO:
                    who[w] = float(np.mean([r[w] for _, r in run]))
            out.append({"cat": cat, "s": max(0.0, run[0][0] - pad), "e": run[-1][0] + pad,
                        "peak_t": peak[0], "peak": round(peak[1][cat], 3), "who": who,
                        "frames": [t for t, _ in sorted(run, key=lambda x: -x[1][cat])[:3]]})
    return sorted(out, key=lambda c: c["s"])


# ---------------------------------------------------------------------------
# Ollama: the local language-and-vision model
# ---------------------------------------------------------------------------
def _api(path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def ollama_running():
    try:
        with _api("/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def find_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    if os.name == "nt":
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
            p = Path(base) / "Programs" / "Ollama" / "ollama.exe"
            if p.exists():
                return str(p)
            p = Path(base) / "Ollama" / "ollama.exe"
            if p.exists():
                return str(p)
    return None


def start_ollama(wait=60):
    if ollama_running():
        return True
    exe = find_ollama()
    if not exe:
        return False
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **_NOWIN)
    for _ in range(wait):
        if ollama_running():
            return True
        time.sleep(1)
    return ollama_running()


def model_ready():
    try:
        with _api("/api/tags", timeout=5) as r:
            tags = json.loads(r.read())
        want = MODEL if ":" in MODEL else MODEL + ":latest"
        return any(m.get("name") in (MODEL, want) or m.get("model") in (MODEL, want)
                   for m in tags.get("models", []))
    except Exception:
        return False


def install_ollama(progress=None):
    """Download and run Ollama's own installer (per-user, no admin)."""
    say = progress or (lambda f, m: None)
    if os.name != "nt":
        raise RuntimeError("Install Ollama from ollama.com, then try again.")
    tmp = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    download(OLLAMA_SETUP_URL, tmp, lambda f, m: say(f * 0.9, "Getting Ollama (one time) · " + m))
    say(0.92, "Installing Ollama…")
    subprocess.run([str(tmp), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], **_NOWIN)
    try:
        tmp.unlink()
    except OSError:
        pass
    if not start_ollama(wait=90):
        raise RuntimeError("Ollama installed but didn't start. Restart your PC and try again.")


def pull_model(progress=None):
    say = progress or (lambda f, m: None)
    with _api("/api/pull", {"model": MODEL, "stream": True}, timeout=600) as r:
        for line in r:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("error"):
                raise RuntimeError("Couldn't download the AI model: " + d["error"])
            if d.get("total"):
                done = d.get("completed", 0)
                say(done / d["total"], f"Getting the AI model (one time) · "
                    f"{done / 1e9:.1f} of {d['total'] / 1e9:.1f} GB")
    if not model_ready():
        raise RuntimeError("The AI model download didn't finish. Try again.")


def ensure_ai(progress=None):
    """Make sure Ollama is installed, running and has the model."""
    if not start_ollama():
        install_ollama(progress)
    if not model_ready():
        pull_model(progress)


def chat(prompt, images=None, schema=None, timeout=300):
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images
    payload = {"model": MODEL, "messages": [msg], "stream": False,
               "options": {"temperature": 0, "num_ctx": 8192}}
    if schema:
        payload["format"] = schema
    with _api("/api/chat", payload, timeout=timeout) as r:
        d = json.loads(r.read())
    text = (d.get("message") or {}).get("content", "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


# ---------------------------------------------------------------------------
# Second look at picture candidates
# ---------------------------------------------------------------------------
def grab_frames(ffmpeg, path, times, run):
    out = []
    for t in times:
        r = run([ffmpeg, "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(path), "-map", "0:v:0",
                 "-frames:v", "1", "-vf", "scale=640:-2", "-f", "image2", "-c:v", "mjpeg",
                 "-q:v", "4", "-"], capture_output=True)
        if r.returncode == 0 and r.stdout:
            out.append(base64.b64encode(r.stdout).decode())
    return out


LOOK = {
    "kiss": ("These are frames from one moment of a movie. Is anyone kissing? If so, who is "
             "kissing (a man and a woman, two men, two women, or a parent/child or family "
             "kiss on the cheek), and is it a light kiss (a peck or short kiss) or a "
             "passionate one (long, open-mouthed, making out)?",
             {"type": "object", "properties": {
                 "kissing": {"type": "boolean"},
                 "who": {"type": "string", "enum": ["man and woman", "two men", "two women",
                                                    "family or friendly", "unclear"]},
                 "level": {"type": "string", "enum": ["light", "passionate", "none"]}},
              "required": ["kissing", "who", "level"]}),
    "bed": ("These are frames from one moment of a movie. Is a couple shown in a sexual or "
            "intimate way (in bed together, making out, undressing each other)? Who is the "
            "couple (a man and a woman, two men, two women)?",
            {"type": "object", "properties": {
                "intimate": {"type": "boolean"},
                "who": {"type": "string", "enum": ["man and woman", "two men", "two women",
                                                   "unclear"]}},
             "required": ["intimate", "who"]}),
    "gore": ("These are frames from one moment of a movie. Do they show graphic violence or "
             "gore: blood, wounds, injuries, a dead body, someone being shot, stabbed or hurt?",
             {"type": "object", "properties": {"graphic": {"type": "boolean"},
                                               "what": {"type": "string"}},
              "required": ["graphic", "what"]}),
    "fight": ("These are frames from one moment of a movie. Do they show violence: people "
              "fighting, hitting, shooting, threatening someone with a weapon?",
              {"type": "object", "properties": {"violent": {"type": "boolean"},
                                                "what": {"type": "string"}},
               "required": ["violent", "what"]}),
    "smoking": ("These are frames from a movie. Is someone smoking (cigarette, cigar, vape, "
                "pipe)?", {"type": "object", "properties": {"yes": {"type": "boolean"}},
                           "required": ["yes"]}),
    "drinking": ("These are frames from a movie. Is someone drinking alcohol (beer, wine, "
                 "liquor), or drunk?", {"type": "object", "properties": {"yes": {"type": "boolean"}},
                                       "required": ["yes"]}),
    "drugs": ("These are frames from a movie. Is someone using illegal drugs (smoking a joint, "
              "snorting, injecting, pills)?", {"type": "object",
                                              "properties": {"yes": {"type": "boolean"}},
                                              "required": ["yes"]}),
    "immodest": ("These are frames from a movie. Is someone dressed immodestly (swimsuit, "
                 "underwear, lingerie, very revealing clothes)?",
                 {"type": "object", "properties": {"yes": {"type": "boolean"}},
                  "required": ["yes"]}),
}
WHO_KEY = {"man and woman": "mf", "two men": "mm", "two women": "ff"}


def second_look(cands, frames_for, progress=None, cancel=None):
    """Ask the local model about each candidate. Adds "verdict" to each:
    {"keep": bool, "who": "mf|mm|ff|?", "level": "light|passionate|?", "what": str}."""
    for n, c in enumerate(cands):
        if cancel and cancel():
            raise KeyboardInterrupt
        if progress:
            progress(n / max(1, len(cands)))
        q, schema = LOOK[c["cat"]]
        imgs = frames_for(c)
        try:
            a = chat(q + " Answer in JSON.", imgs, schema, timeout=180)
        except Exception as ex:
            c["verdict"] = {"keep": True, "who": "?", "level": "?", "what": "", "error": str(ex)}
            continue
        v = {"keep": True, "who": "?", "level": "?", "what": str(a.get("what", ""))[:60]}
        if c["cat"] == "kiss":
            v["keep"] = bool(a.get("kissing")) and a.get("who") != "family or friendly"
            v["who"] = WHO_KEY.get(a.get("who"), "?")
            v["level"] = a.get("level") if a.get("level") in ("light", "passionate") else "?"
        elif c["cat"] == "bed":
            v["keep"] = bool(a.get("intimate"))
            v["who"] = WHO_KEY.get(a.get("who"), "?")
        elif c["cat"] == "gore":
            v["keep"] = bool(a.get("graphic"))
        elif c["cat"] == "fight":
            v["keep"] = bool(a.get("violent"))
        else:
            v["keep"] = bool(a.get("yes"))
        c["verdict"] = v
    if progress:
        progress(1.0)
    return cands


# ---------------------------------------------------------------------------
# Reading the dialogue
# ---------------------------------------------------------------------------
LINE_TYPES = {
    "sexref": "a sexual reference, sexual joke or innuendo, or crude talk about bodies or sex",
    "casual": "sleeping around: casual sex, hooking up, one-night stands, cheating or affairs, "
              "many partners",
    "samesex": "a same-sex romance or relationship: a gay or lesbian couple, same-sex dating, "
               "attraction or partners",
    "oppsex": "an opposite-sex couple living together or sleeping together without being "
              "married",
}


def dialogue_lines(cues, asr, spoken):
    """Lines of dialogue with times: subtitle lines when there are subtitles,
    otherwise sentences from what was heard."""
    lines = []
    if cues:
        for c in cues:
            txt = " ".join(spoken(c["text"])).strip()
            if txt:
                lines.append({"s": c["s"], "e": c["e"], "text": txt})
        return lines
    cur = []
    for w in asr:
        if cur and (w["s"] - cur[-1]["e"] > 0.8 or len(cur) > 25):
            lines.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["t"] for x in cur)})
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["t"]):
            lines.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["t"] for x in cur)})
            cur = []
    if cur:
        lines.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["t"] for x in cur)})
    return lines


def classify_dialogue(lines, wanted, progress=None, cancel=None, chunk=40, overlap=6):
    """Returns {line_index: set(types)} for the wanted LINE_TYPES."""
    if not lines or not wanted:
        return {}
    defs = "\n".join(f'- "{k}": {LINE_TYPES[k]}' for k in wanted)
    schema = {"type": "object", "properties": {"flags": {"type": "array", "items": {
        "type": "object", "properties": {"line": {"type": "integer"},
                                         "type": {"type": "string", "enum": list(wanted)}},
        "required": ["line", "type"]}}}, "required": ["flags"]}
    found = {}
    starts = list(range(0, len(lines), chunk - overlap))
    for n, a in enumerate(starts):
        if cancel and cancel():
            raise KeyboardInterrupt
        if progress:
            progress(n / len(starts))
        part = lines[a:a + chunk]
        listing = "\n".join(f"{a + i}: {l['text']}" for i, l in enumerate(part))
        prompt = ("You help a family decide which lines of movie dialogue to mute. Here are "
                  "numbered lines in order:\n\n" + listing + "\n\nList every line that contains "
                  "any of these:\n" + defs + "\n\nOnly flag a line when it clearly fits. Ordinary "
                  "romance, family love and friendship are not flagged unless they fit a type "
                  'above. Answer in JSON like {"flags": [{"line": 12, "type": "sexref"}]}; use '
                  'an empty list if nothing fits.')
        try:
            res = chat(prompt, schema=schema, timeout=300)
        except Exception:
            continue
        for f in res.get("flags", []):
            try:
                i = int(f.get("line"))
            except (TypeError, ValueError):
                continue
            t = f.get("type")
            if a <= i < a + len(part) and t in wanted:
                found.setdefault(i, set()).add(t)
        if a + chunk >= len(lines):
            break
    if progress:
        progress(1.0)
    return found
