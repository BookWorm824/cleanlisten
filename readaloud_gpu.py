"""
ReadAloud's graphics-card readers. Lauren, 2026-11-06: "I like the idea of multi voices...but i'm
afraid our choice of voices is still cheap" and, after hearing the four tests, "I do like the qwen
acting better....could we have all 4 versions? let me choose by book".

Readers (job["reader"]):
  kokoro      Quick: the voice ReadAloud always had (readaloud.py, on the processor).
  acting      Qwen3-TTS 1.7B VoiceDesign: each line is read with an acting note from the reading
              director ("voice breaking, trying to stay composed") and the voice's description.
  steady      Qwen3-TTS 1.7B Base: copies a fixed voice clip, so a voice never drifts.
  chatterbox  Chatterbox (Resemble AI, MIT): copies the same clips, with one "how emotional" dial.
The three new ones need an NVIDIA card (6 GB or more) and live in their own Python install
(APP_DATA/gpu/venv, made once by install(): PyTorch 2.11 for CUDA 12.8, about 3 GB, then about
4 GB for each reader's model). The window runs in CleanListen's Python; reading runs in the gpu
venv as `python readaloud_gpu.py speak <job> <chapters>`, which loads the model once and reads the
chapters in turn (one GPU, one worker).

The voices: 18 clips (rv_<id>.flac, shipped with the app) designed once with VoiceDesign from the
descriptions in GPU_VOICES. "steady" and Chatterbox copy the clip; "acting" is given the same
description, so the voices match across readers, and "Hear it" just plays the clip.

Every line is listened to (CleanListen's Parakeet model) and read again, up to twice, if a word
was dropped or doubled: the new voices do that now and then ("I knew knew I must listen").

Tested on the owner's RTX 5070 Laptop (8 GB, driver 572.97): acting 0.35x real time one line at
a time, 0.8x seven at once (but 10 GB, so 4 at once); steady 0.42x; Chatterbox 1.07x.
"""
import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import readaloud as R  # noqa: E402

GPU_DIR = R.APP_DATA / "gpu"
VENV = GPU_DIR / "venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
HF_HOME = GPU_DIR / "hf"
MODELS = GPU_DIR / "models"     # plain folders: Hugging Face's cache needs symlinks, which Windows
                                # refuses ordinary accounts (WinError 1314 on the owner's PC)
CHATTERBOX_FILES = ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]
REQ = HERE / "readaloud_gpu_req.txt"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
ASR_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
ASR_MODEL = next((d for d in (HERE / "models" / ASR_NAME, R.APP_DATA / "app" / "models" / ASR_NAME)
                  if (d / "encoder.int8.onnx").exists()), HERE / "models" / ASR_NAME)

# name, what it is, real-time speed on the owner's laptop (for "about N hours"), model, GB
READERS = {
    "kokoro": ("Quick", "Works on any computer.", 5.0, None, 0),
    "acting": ("Qwen, acting", "Acts out every line the way the reading director says.", 0.8,
               "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", 4.3),
    "steady": ("Qwen, steady voices", "Each voice stays exactly the same all through the book.", 0.55,
               "Qwen/Qwen3-TTS-12Hz-1.7B-Base", 4.3),
    "chatterbox": ("Chatterbox", "Lively, and the fastest of the new voices.", 1.0,
                   "ResembleAI/chatterbox", 3.2),
}
READER_ORDER = ["acting", "steady", "chatterbox", "kokoro"]
GPU_READERS = ("acting", "steady", "chatterbox")
SOFTWARE_GB = 3.0

# id: (name shown, description (VoiceDesign), gender, age, accent). The clip rv_<id>.flac says REF_TEXT.
GPU_VOICES = {
    "grace": ("Grace - warm American woman", "A warm, intelligent American woman in her thirties with a clear, gentle mid-range voice. A seasoned audiobook narrator: natural, relaxed and expressive.", "female", "adult", "us"),
    "daniel": ("Daniel - warm American man", "A warm American man around forty with a relaxed, rich baritone voice. A seasoned audiobook narrator: natural, easygoing and expressive.", "male", "adult", "us"),
    "eleanor": ("Eleanor - British woman", "A warm, educated English woman in her thirties with a clear, refined southern English accent. A seasoned audiobook narrator: natural and expressive.", "female", "adult", "gb"),
    "oliver": ("Oliver - British man", "A warm, educated English man around forty with a mellow voice and a refined southern English accent. A seasoned audiobook narrator: natural and expressive.", "male", "adult", "gb"),
    "june": ("June - bright young American woman", "A bright, friendly American woman in her early twenties with a light, lively voice.", "female", "young", "us"),
    "ruth": ("Ruth - mature American woman", "A composed American woman in her fifties with a rich, slightly husky alto voice.", "female", "older", "us"),
    "edna": ("Edna - elderly American woman", "A kindly American woman in her late seventies with a soft, slightly thin and wavering voice.", "female", "elderly", "us"),
    "clara": ("Clara - Southern American woman", "A gracious American woman in her forties with a soft, warm Southern accent.", "female", "adult", "us"),
    "kayla": ("Kayla - American teenage girl", "An American teenage girl of about fifteen with a quick, expressive voice.", "female", "teen", "us"),
    "lily": ("Lily - American girl", "A sweet, clear-voiced American girl about nine years old.", "female", "child", "us"),
    "jack": ("Jack - deep American man", "A strong American man in his forties with a deep, slightly gruff voice and a steady, confident manner.", "male", "adult", "us"),
    "ben": ("Ben - young American man", "An easygoing American man in his twenties with a clear, friendly tenor voice.", "male", "young", "us"),
    "walter": ("Walter - elderly American man", "An American man in his late seventies with a gravelly, slow, weathered voice.", "male", "elderly", "us"),
    "hank": ("Hank - Southern American man", "A good-natured American man in his fifties with a slow, warm Texas drawl.", "male", "older", "us"),
    "tyler": ("Tyler - American teenage boy", "An American teenage boy of about fifteen with a youthful, slightly breaking voice.", "male", "teen", "us"),
    "sam": ("Sam - American boy", "A bright, energetic American boy about nine years old.", "male", "child", "us"),
    "harriet": ("Harriet - older British woman", "A brisk, cultured English woman in her sixties with a crisp, refined accent.", "female", "older", "gb"),
    "arthur": ("Arthur - older British man", "A dignified English gentleman in his sixties with a deep, measured voice and a refined accent.", "male", "older", "gb"),
}
NARRATORS = ["grace", "daniel", "eleanor", "oliver", "clara", "ruth", "jack", "hank", "june", "ben",
             "harriet", "arthur"]
DEFAULT_GPU_VOICE = "grace"
REF_TEXT = ("It was late in the afternoon when the letter finally came. I read it twice, standing by "
            "the window, and then I sat down and laughed, because after all those years, it had been "
            "so simple.")

PACE_WORDS = {"slower": " Take it a little slower than usual.", "faster": " A little quicker than usual."}
EXAGGERATION = {"calm": 0.4, "warm": 0.5, "strong": 0.7}
UNIT_CHARS = {"acting": 320, "steady": 320, "chatterbox": 260}
TRIES = 3


def model_dir(reader):
    return MODELS / READERS[reader][3].replace("/", "--")


def voice_clip(vid):
    return HERE / f"rv_{vid}.flac"


def is_gpu(reader):
    return reader in GPU_READERS


def reader_of(job):
    r = job.get("reader") or "kokoro"
    return r if r in READERS else "kokoro"


def hours_to_make(audio_hours, reader):
    return audio_hours / READERS[reader][2]


# ---------------------------------------------------------------------------
# Can this computer use them, and are they set up?
# ---------------------------------------------------------------------------
_NOWIN = R._NOWIN


def gpu_check():
    """(ok, message). The message says, in plain words, what's missing."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=20, **_NOWIN).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        out = []
    best = None
    for line in out:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                mem, drv = int(float(parts[1])), parts[2]
            except ValueError:
                continue
            if best is None or mem > best[1]:
                best = (parts[0], mem, drv)
    if not best:
        return False, ("These voices need an NVIDIA graphics card, and this computer doesn't seem to "
                       "have one. The Quick voice works on any computer.")
    name, mem, drv = best
    if mem < 5800:
        return False, (f"These voices need a graphics card with at least 6 GB of memory; this "
                       f"computer's {name} has {mem / 1024:.0f} GB. The Quick voice works on any computer.")
    try:
        major = int(drv.split(".")[0])
    except ValueError:
        major = 999
    if major < 570:
        return False, (f"Update the NVIDIA graphics driver first (this one is version {drv}; these voices "
                       "need 570 or newer). Open the NVIDIA app and choose to update the driver, then "
                       "come back.")
    return True, f"{name}, {mem / 1024:.0f} GB"


def _req_text():
    try:
        return REQ.read_text(encoding="utf8")
    except OSError:
        return ""


def software_ready():
    f = GPU_DIR / "software.ready"
    try:
        return PY.exists() and f.read_text(encoding="utf8") == _req_text()
    except OSError:
        return False


def model_ready(reader):
    return (GPU_DIR / f"{reader}.ready").exists()


def ready(reader):
    return not is_gpu(reader) or (software_ready() and model_ready(reader))


def setup_size_gb(reader):
    return (0 if software_ready() else SOFTWARE_GB) + (0 if model_ready(reader) else READERS[reader][4])


def _base_python():
    """The Python CleanListen's own venv was made from (a venv can't make a venv of itself)."""
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    if base.name.lower() == "pythonw.exe":
        base = base.with_name("python.exe")
    return str(base)


def _run_lines(cmd, on_line, stop=None, env=None):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         text=True, encoding="utf8", errors="replace", env=env, **_NOWIN)
    tail = []
    for line in p.stdout:
        if stop is not None and stop.is_set():
            p.kill()
            p.wait()
            raise R.Stopped()
        line = line.rstrip()
        tail = (tail + [line])[-40:]
        on_line(line)
    return p.wait(), "\n".join(tail)


def _env():
    env = dict(os.environ)
    env["HF_HOME"] = str(HF_HOME)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def install(reader, progress=None, stop=None):
    """Set up a reader (once): the gpu Python install, then its model. progress(fraction, message)."""
    say = progress or (lambda f, m: None)
    ok, why = gpu_check()
    if not ok:
        raise RuntimeError(why)
    GPU_DIR.mkdir(parents=True, exist_ok=True)
    if not software_ready():
        if not PY.exists():
            say(0.01, "Making a separate space for the new voices…")
            r = subprocess.run([_base_python(), "-m", "venv", str(VENV)], capture_output=True, text=True, **_NOWIN)
            if r.returncode != 0 or not PY.exists():
                raise RuntimeError("Couldn't make a space for the new voices:\n" + (r.stderr or r.stdout)[-400:])
        wanted = [ln for ln in _req_text().splitlines() if ln.strip() and not ln.startswith("#")]
        seen = [0]

        def pip_line(line):
            if line.startswith("Collecting ") or line.startswith("Requirement already satisfied"):
                seen[0] += 1
            m = re.search(r"Downloading (\S+?)(?:-\d[^ ]*)? \(([\d.]+ [kMG]B)\)", line)
            what = f" ({m.group(1).split('/')[-1]}, {m.group(2)})" if m else ""
            say(0.02 + 0.5 * min(1.0, seen[0] / max(1, len(wanted))),
                f"Getting the voice software (once, about {SOFTWARE_GB:.0f} GB){what}…")
        code, tail = _run_lines([str(PY), "-m", "pip", "install", "--disable-pip-version-check",
                                 "--no-input", "-r", str(REQ), "--extra-index-url", TORCH_INDEX],
                                pip_line, stop, _env())
        # "# no-deps: pkg==1.0" lines: packages put in on their own, after the rest (Chatterbox asks
        # for an older PyTorch than RTX 50 cards need, though it runs fine on the newer one)
        alone = [ln.split(":", 1)[1].split()[0] for ln in _req_text().splitlines() if ln.startswith("# no-deps:")]
        if code == 0 and alone:
            code, tail = _run_lines([str(PY), "-m", "pip", "install", "--disable-pip-version-check",
                                     "--no-input", "--no-deps"] + alone, pip_line, stop, _env())
        if code != 0:
            if "No space left" in tail or "Errno 28" in tail:
                raise RuntimeError("The computer ran out of disk space getting the voice software. "
                                   "Free up about 10 GB and try again.")
            raise RuntimeError("Couldn't get the voice software. Check the internet connection and try "
                               "again.\n\n" + tail[-600:])
        (GPU_DIR / "software.ready").write_text(_req_text(), encoding="utf8")
    if not model_ready(reader):
        def fetch_line(line):
            try:
                msg = json.loads(line)
            except ValueError:
                return
            if "f" in msg:
                say(0.55 + 0.44 * msg["f"], msg.get("m", ""))
        code, tail = _run_lines([str(PY), str(Path(__file__).resolve()), "fetch", reader], fetch_line, stop, _env())
        if code != 0:
            raise RuntimeError("Couldn't get the voice. Check the internet connection and try again.\n\n" + tail[-600:])
        (GPU_DIR / f"{reader}.ready").write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf8")
    say(1.0, "The voice is ready.")


def _fetch(reader):
    """(In the gpu venv) download a reader's model, printing progress lines."""
    from huggingface_hub import HfApi, snapshot_download
    repo = READERS[reader][3]
    name = READERS[reader][0]
    only = CHATTERBOX_FILES if reader == "chatterbox" else None
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        total = sum((s.size or 0) for s in info.siblings if not only or s.rfilename in only) or 1
    except Exception:
        total = int(READERS[reader][4] * 2 ** 30)
    folder = model_dir(reader)
    done = threading.Event()

    def watch():
        while not done.wait(1.0):
            got = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.exists() else 0
            print(json.dumps({"f": min(0.99, got / total),
                              "m": f"Getting the voice ({name}, once): {got >> 20:,} of {total >> 20:,} MB"}), flush=True)
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        # (the Qwen models carry their speech codec inside); files already there are checked, not
        # fetched again
        snapshot_download(repo, local_dir=str(folder), allow_patterns=only)
    finally:
        done.set()
    print(json.dumps({"f": 1.0, "m": "The voice is ready."}), flush=True)


# ---------------------------------------------------------------------------
# Listening back: did it say the words, once each?
# ---------------------------------------------------------------------------
def _words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower().replace("’", "'").replace("-", " "))


def _alike(a, b):
    """Two runs of words that sound the same: "race tracks"/"racetracks", "Lindsay"/"Lindsey",
    "twenty five"/"25" (the recognizer writes numbers as digits)."""
    if b and all(re.search(r"\d", w) for w in b) and len(a) <= 4:
        return True
    sa, sb = "".join(a), "".join(b)
    return bool(sa and sb) and difflib.SequenceMatcher(None, sa, sb, autojunk=False).ratio() >= 0.75


def check(expected, heard, skip=()):
    """Problems in what was heard: (score, why). Doubled words, dropped words (any, in a short line),
    and anything that's mostly different. Words in skip (respelled names) don't count."""
    a = [w for w in _words(expected)]
    b = _words(heard)
    if not a:
        return 0, ""
    skip = {w.lower() for w in skip}
    score, why = 0, []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if any(w in skip for w in a[max(0, i1 - 1):i2 + 1]):
            continue
        if op == "replace" and _alike(a[i1:i2], b[j1:j2]):
            continue
        if op in ("insert", "replace"):
            extra = b[j1:j2]
            near = set(a[max(0, i1 - 2):i2 + 2]) | set(b[max(0, j1 - 1):j1]) | set(b[j2:j2 + 1])
            if op == "insert" and any(w in near for w in extra):
                score += 3
                why.append("doubled " + " ".join(extra))
                continue
            if op == "insert" and len(extra) >= 3:
                score += 3
                why.append("extra words")
                continue
        if op in ("delete", "replace"):
            gone = a[i1:i2]
            if op == "delete" and (len(a) <= 6 or len(gone) >= 3):
                score += 3
                why.append("dropped " + " ".join(gone))
                continue
        score += max(i2 - i1, j2 - j1)
    if score <= max(1, int(0.08 * len(a))) and "doubled" not in " ".join(why) and "dropped" not in " ".join(why):
        return 0, ""
    return score, "; ".join(why) or "different words"


class Ears:
    """CleanListen's speech recognizer (Parakeet), on the processor."""

    def __init__(self):
        self.rec = None
        try:
            import sherpa_onnx
            d = ASR_MODEL
            if (d / "encoder.int8.onnx").exists():
                self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
                    joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
                    num_threads=4, model_type="nemo_transducer")
        except Exception:
            self.rec = None

    def hear(self, x, sr):
        if self.rec is None:
            return None
        s = self.rec.create_stream()
        s.accept_waveform(sr, x)
        self.rec.decode_stream(s)
        return s.result.text


# ---------------------------------------------------------------------------
# The voices
# ---------------------------------------------------------------------------
class Voice:
    """One reader's model. say(units) -> [float32 at 24 kHz]. A unit: dict(text, voice, note,
    manner, feel, pace)."""
    sr = 24000
    batch = 1

    def __init__(self, reader):
        import torch
        self.torch = torch
        self.reader = reader
        if reader == "chatterbox":
            from chatterbox.tts import ChatterboxTTS
            self.m = ChatterboxTTS.from_local(model_dir(reader), device="cuda")
            self.sr = self.m.sr
            self.conds = {}
        else:
            from qwen_tts import Qwen3TTSModel
            self.m = Qwen3TTSModel.from_pretrained(str(model_dir(reader)), device_map="cuda:0",
                                                   dtype=torch.bfloat16, attn_implementation="sdpa")
            self.prompts = {}
            self.batch = 4 if reader == "acting" else 3

    def _instruct(self, u):
        v = GPU_VOICES.get(u["voice"]) or GPU_VOICES[DEFAULT_GPU_VOICE]
        s = v[1]
        if u.get("manner"):
            s += " Character: " + u["manner"].rstrip(".") + "."
        s += " Read this " + (u.get("note") or "as natural, engaged audiobook narration").rstrip(".") + "."
        return s + PACE_WORDS.get(u.get("pace"), "")

    def _prompt(self, vid):
        if vid not in self.prompts:
            self.prompts[vid] = self.m.create_voice_clone_prompt(
                ref_audio=str(voice_clip(vid if voice_clip(vid).exists() else DEFAULT_GPU_VOICE)),
                ref_text=REF_TEXT)[0]
        return self.prompts[vid]

    def _cbox(self, u):
        vid = u["voice"] if voice_clip(u["voice"]).exists() else DEFAULT_GPU_VOICE
        ex = EXAGGERATION.get(u.get("feel"), 0.5)
        if vid not in self.conds:
            self.m.prepare_conditionals(str(voice_clip(vid)), exaggeration=0.5)
            self.conds[vid] = self.m.conds
        self.m.conds = self.conds[vid]
        w = self.m.generate(u["text"], exaggeration=ex, cfg_weight=0.35 if ex >= 0.7 else 0.5)
        return w.squeeze(0).float().cpu().numpy()

    def _many(self, units):
        if self.reader == "chatterbox":
            return [self._cbox(u) for u in units]
        texts = [u["text"] for u in units]
        lang = ["English"] * len(units)
        if self.reader == "acting":
            w, sr = self.m.generate_voice_design(text=texts, language=lang, instruct=[self._instruct(u) for u in units])
        else:
            w, sr = self.m.generate_voice_clone(text=texts, language=lang,
                                                voice_clone_prompt=[self._prompt(u["voice"]) for u in units])
        self.sr = sr
        return [self._np(x) for x in w]

    def _np(self, x):
        import numpy as np
        if hasattr(x, "detach"):
            x = x.detach().float().cpu().numpy()
        return np.asarray(x, dtype=np.float32).reshape(-1)

    def say(self, units):
        out = []
        i = 0
        while i < len(units):
            part = units[i:i + self.batch]
            try:
                out += self._many(part)
                i += len(part)
            except self.torch.cuda.OutOfMemoryError:
                self.torch.cuda.empty_cache()
                if self.batch == 1:
                    raise RuntimeError("The graphics card ran out of memory. Close other programs "
                                       "(games, video editors) and press Carry on.")
                self.batch = max(1, self.batch // 2)
        return out


def _trim(x, sr, level=0.01, keep=0.05):
    import numpy as np
    loud = np.flatnonzero(np.abs(x) > level)
    if not len(loud):
        return x[:0]
    pad = int(keep * sr)
    return x[max(0, loud[0] - pad): loud[-1] + pad]


def say_checked(voice, ears, units, log=None, skip=()):
    """Read the units; listen to each and read again (up to TRIES in all) when words were dropped
    or doubled. Returns the best take of each."""
    takes = [None] * len(units)
    best = [None] * len(units)
    todo = list(range(len(units)))
    for attempt in range(TRIES):
        if not todo:
            break
        got = voice.say([units[k] for k in todo])
        again = []
        for k, x in zip(todo, got):
            x = _trim(x, voice.sr)
            words = len(_words(units[k]["text"]))
            sec = len(x) / voice.sr
            heard = ears.hear(x, voice.sr) if len(x) else ""
            if heard is None:                       # no recognizer: trust it
                score, why = (0, "") if len(x) else (99, "silence")
            else:
                score, why = check(units[k]["text"], heard, skip)
            if words and sec > 1.6 * words + 2:     # a long hum or babble
                score, why = score + 5, (why + "; too long").strip("; ")
            if best[k] is None or score < best[k]:
                best[k], takes[k] = score, x
            if score and attempt < TRIES - 1:
                again.append(k)
                if log:
                    log(f"read again ({why}): {units[k]['text'][:80]}")
        todo = again
    return takes


# ---------------------------------------------------------------------------
# Reading a chapter
# ---------------------------------------------------------------------------
def respell(text, said):
    for w, s in (said or {}).items():
        text = re.sub(r"(?<![\w'])" + re.escape(w) + r"(?![\w'])", s, text)
    # an old book's spaced dots (". . .") read as a pause: Chatterbox said "thank you 2,000 thank you"
    return re.sub(r"\s*\.(?:\s*\.){2,}", "…", text)


def chapter_units(ch, job):
    """[(gap before, [units])] per paragraph, from the (directed) chapter."""
    reader = reader_of(job)
    narrator = job.get("voice") if job.get("voice") in GPU_VOICES else DEFAULT_GPU_VOICE
    manners = job.get("manners") or {}
    said = job.get("respell") or {}
    out, prev = [], None
    for item in ch["paras"]:
        kind, text = item[0], item[1]
        o = item[2] if len(item) > 2 else {}
        if kind == "b":
            out.append((R.GAP_BREAK, []))
            prev = "b"
            continue
        if "g" in o and prev:
            gap = o["g"]
        elif prev in ("p", "h"):
            gap = R.GAP_HEADING if prev == "h" or kind == "h" else R.GAP_PARA
        else:
            gap = 0.0
        vid = o.get("v") if o.get("v") in GPU_VOICES else narrator
        s = o.get("s", 1.0)
        pace = "slower" if s < 0.97 else "faster" if s > 1.03 else "normal"
        units = [{"text": respell(piece, said), "orig": piece, "voice": vid, "note": o.get("m", ""),
                  "manner": manners.get(o.get("who", ""), ""), "feel": o.get("x", "warm"), "pace": pace}
                 for piece in R.chunks(text, UNIT_CHARS.get(reader, 300))]
        out.append((gap, units))
        prev = kind
    return out


def speak_chapter(voice, ears, jobdir, i, report=None, log=None):
    import numpy as np
    jobdir = Path(jobdir)
    job = json.loads((jobdir / "job.json").read_text(encoding="utf8"))
    ch = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[i]
    stopfile = jobdir / "stop"
    sr = 24000
    dst = R.chapter_file(jobdir, i)
    tmp = dst.with_name("~" + dst.name)
    speed = float(job.get("speed", 1.0) or 1.0)
    cmd = [R.tool("ffmpeg"), "-y", "-v", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0"]
    if abs(speed - 1.0) > 0.01:
        cmd += ["-af", f"atempo={speed:.3f}"]
    cmd += ["-c:a", "aac", "-b:a", job.get("bitrate", R.BITRATE), "-f", "mp4", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)

    def put(x):
        if voice.sr != sr and len(x):         # (both models give 24 kHz; just in case)
            x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * sr / voice.sr)), np.arange(len(x)), x)
        proc.stdin.write((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

    def silence(sec):
        return np.zeros(int(sec * sr), dtype=np.float32)

    skip = set()
    for w, s in (job.get("respell") or {}).items():
        skip.update(_words(w))
    done = 0
    try:
        put(silence(R.LEAD_IN))
        paras = chapter_units(ch, job)
        # read several paragraphs' units together (one batch on the card), write them in order
        k = 0
        while k < len(paras):
            group, n = [], 0
            while k < len(paras) and (not group or n < 8):
                group.append(paras[k])
                n += len(paras[k][1])
                k += 1
            if stopfile.exists():
                raise R.Stopped()
            flat = [u for _, us in group for u in us]
            takes = say_checked(voice, ears, flat, log, skip) if flat else []
            t = 0
            for gap, us in group:
                if gap:
                    put(silence(gap))
                for j, u in enumerate(us):
                    if j:
                        put(silence(0.22))
                    put(takes[t])
                    t += 1
                    done += len(u["orig"].split())
                if report:
                    report(done)
        put(silence(R.TAIL))
        proc.stdin.close()
        err = proc.stderr.read().decode("utf8", "ignore")
        if proc.wait() != 0:
            raise RuntimeError(f"Couldn't save chapter {i + 1}: {err[-300:]}")
        os.replace(tmp, dst)
    except BaseException:
        try:
            proc.kill()
            proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dst


def _speak(jobdir, order):
    """(In the gpu venv) read the chapters in this order, printing progress lines."""
    job = json.loads((Path(jobdir) / "job.json").read_text(encoding="utf8"))
    print(json.dumps({"m": "Getting the voice ready…"}), flush=True)
    voice = Voice(reader_of(job))
    ears = Ears()
    _note(jobdir, f"{reader_of(job)}: listening back {'on' if ears.rec else 'OFF (no speech model)'}")
    for i in order:
        if R.chapter_file(jobdir, i).exists():
            continue
        if (Path(jobdir) / "stop").exists():
            return 3
        try:
            speak_chapter(voice, ears, jobdir, i,
                          report=lambda w, i=i: print(json.dumps({"i": i, "w": w}), flush=True),
                          log=lambda m: _note(jobdir, m))
        except R.Stopped:
            return 3
        print(json.dumps({"done": i}), flush=True)
    return 0


def _note(jobdir, m):
    """Lines read again, kept with the job (relisten.txt) to see how often it happens."""
    try:
        with open(Path(jobdir) / "relisten.txt", "a", encoding="utf8") as f:
            f.write(time.strftime("%H:%M:%S ") + m + "\n")
    except OSError:
        pass


def worker_cmd(jobdir, order):
    return [str(PY), str(Path(__file__).resolve()), "speak", str(jobdir), ",".join(map(str, order))]


def worker_env():
    return _env()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fetch":
        _fetch(a[1])
        sys.exit(0)
    if a and a[0] == "speak":
        sys.exit(_speak(a[1], [int(x) for x in a[2].split(",") if x.strip()]))
    print("usage: readaloud_gpu.py fetch <reader> | speak <job folder> <chapters>")
    sys.exit(2)
