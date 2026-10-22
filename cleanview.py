#!/usr/bin/env python3
"""
CleanView engine — mute bad language and cut nudity, sex scenes and violence
out of movie and TV files you own. Shares CleanListen's speech model, word
lists and tools. Used by the CleanView app; can also run from a command line:

  python cleanview.py analyze WORKDIR VIDEO [--no-nudity] [--no-sex] [--no-violence]
  python cleanview.py render  WORKDIR OUTDIR
  python cleanview.py visualscan VIDEO OUT.json      (internal: runs in its own process)
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cleanlisten as cl  # noqa: E402  (speech model, word lists, ffmpeg helpers)

SR = cl.SR
VIDEO_EXTS = (".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg",
              ".ts", ".m2ts", ".mts", ".vob", ".flv", ".3gp")
TAG_NAME = "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
TAG_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/audio-tagging-models/{TAG_NAME}.tar.bz2"
TAG_DIR = HERE / "models" / TAG_NAME
VISUAL_FPS = 2.0


# ---------------------------------------------------------------------------
# One-time tools: the picture checker (NudeNet) and the sound-event model
# ---------------------------------------------------------------------------
def _venv_python():
    exe = Path(sys.executable)
    py = exe.with_name("python.exe") if os.name == "nt" else exe
    return str(py if py.exists() else exe)


def nudity_model():
    spec = importlib.util.find_spec("nudenet")
    if not spec or not spec.origin:
        return None
    p = Path(spec.origin).parent / "320n.onnx"
    return p if p.exists() else None


def tools_missing():
    """What still needs downloading (empty list = ready)."""
    need = []
    if not importlib.util.find_spec("onnxruntime") or not nudity_model():
        need.append("picture checker")
    if not (TAG_DIR / "model.int8.onnx").exists():
        need.append("sound checker")
    return need


def install_tools(progress=None, log=print):
    say = progress or (lambda f, m: None)
    if not importlib.util.find_spec("onnxruntime") or not nudity_model():
        say(0.05, "Getting the picture checker (one time, about 60 MB)…")
        py = _venv_python()
        for args in (["onnxruntime"], ["--no-deps", "nudenet"]):
            r = cl.run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *args],
                       capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("Couldn't download the picture checker. Check your internet "
                                   "connection and try again.\n\n" + r.stderr[-600:])
        importlib.invalidate_caches()
    if not (TAG_DIR / "model.int8.onnx").exists():
        say(0.6, "Getting the sound checker (one time, about 45 MB)…")
        TAG_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".tar.bz2", dir=TAG_DIR.parent)
        os.close(fd)
        try:
            urllib.request.urlretrieve(TAG_URL, tmp)
            with tarfile.open(tmp, "r:bz2") as tf:
                for m in tf.getmembers():
                    name = Path(m.name).name
                    if name in ("model.int8.onnx", "class_labels_indices.csv") and m.isfile():
                        with tf.extractfile(m) as src, open(TAG_DIR / (name + ".part"), "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.replace(TAG_DIR / (name + ".part"), TAG_DIR / name)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not (TAG_DIR / "model.int8.onnx").exists():
            raise RuntimeError("The sound checker download looked wrong. Try again.")
    say(1.0, "Ready.")


# ---------------------------------------------------------------------------
# Looking inside the video file
# ---------------------------------------------------------------------------
TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}


class VideoError(Exception):
    pass


def probe(path):
    r = cl.run([cl._tool("ffprobe"), "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(path)], capture_output=True, text=True, encoding="utf8",
               errors="replace")
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        info = {}
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    name = Path(path).name
    if any((s.get("codec_tag_string") or "").lower() in ("drmi", "drms", "encv", "enca")
           for s in streams) or "encrypt" in (r.stderr or "").lower():
        raise VideoError(f"{name} is copy-protected (DRM), so it can't be cleaned. This works with "
                         "DRM-free files, like DVD or Blu-ray rips and home videos.")
    vids = [s for s in streams if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    if not vids:
        raise VideoError(f"{name} has no video in it.")
    if not auds:
        raise VideoError(f"{name} has no sound in it.")

    def lang(s):
        return ((s.get("tags") or {}).get("language") or "").lower()

    def title(s):
        return ((s.get("tags") or {}).get("title") or "").lower()

    def audio_rank(s):
        d = s.get("disposition") or {}
        return ("comment" in title(s) or d.get("comment") or d.get("visual_impaired"),
                lang(s) not in ("", "eng", "en", "und"), not d.get("default"), s["index"])

    audio = sorted(auds, key=audio_rank)[0]
    subs = []
    for s in streams:
        if s.get("codec_type") != "subtitle" or s.get("codec_name") not in TEXT_SUBS:
            continue
        d = s.get("disposition") or {}
        subs.append({"index": s["index"], "lang": lang(s), "title": title(s),
                     "forced": bool(d.get("forced")) or "forced" in title(s),
                     "sdh": bool(d.get("hearing_impaired")) or "sdh" in title(s)})

    def num(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    dur = num(fmt.get("duration")) or num(vids[0].get("duration")) or num(audio.get("duration"))
    return {"path": str(path), "duration": dur, "start": num(fmt.get("start_time")),
            "video": {"index": vids[0]["index"], "codec": vids[0].get("codec_name"),
                      "width": vids[0].get("width"), "height": vids[0].get("height")},
            "audio": {"index": audio["index"], "channels": int(audio.get("channels") or 2),
                      "codec": audio.get("codec_name"), "lang": lang(audio),
                      "bit_rate": int(num(audio.get("bit_rate")))},
            "subs": subs, "audio_tracks": len(auds)}


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------
def _srt_time(s):
    h, m, rest = s.strip().replace(".", ",").split(":")
    sec, ms = (rest.split(",") + ["0"])[:2]
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = block.strip().split("\n")
        k = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if k is None:
            continue
        try:
            a, b = lines[k].split("-->")
            s, e = _srt_time(a), _srt_time(b.strip().split(" ")[0])
        except (ValueError, IndexError):
            continue
        body = "\n".join(lines[k + 1:])
        body = re.sub(r"\{[^}]*\}", "", body)        # ASS styling
        body = re.sub(r"<[^>]+>", "", body)          # <i>, <font>
        body = body.replace("\\N", "\n").strip()
        if body:
            cues.append({"s": s, "e": e, "text": body})
    return cues


def find_subtitles(path, info, workdir):
    """Best English subtitles: a matching .srt next to the video, else a text
    track inside it. Returns (cues, description) or ([], "")."""
    p = Path(path)
    sidecars = sorted(f for f in p.parent.iterdir() if f.is_file() and f.suffix.lower() == ".srt"
                      and f.name.lower().startswith(p.stem.lower()))
    sidecars.sort(key=lambda f: (not re.search(r"\.(en|eng|english)\b", f.name.lower()),
                                 "forced" in f.name.lower(), len(f.name)))
    for f in sidecars:
        if "forced" in f.name.lower():
            continue
        raw = f.read_bytes()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                cues = parse_srt(raw.decode(enc))
                break
            except UnicodeDecodeError:
                cues = []
        if len(cues) > 5:
            return cues, f"subtitles from {f.name}"
    tracks = [s for s in info["subs"] if not s["forced"] and s["lang"] in ("", "eng", "en", "und")]
    best = []
    for s in sorted(tracks, key=lambda s: (s["lang"] not in ("eng", "en"), not s["sdh"])):
        out = Path(workdir) / f"sub_{s['index']}.srt"
        if not out.exists():
            r = cl.run([cl._tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-map",
                        f"0:{s['index']}", "-f", "srt", str(out)], capture_output=True)
            if r.returncode != 0:
                continue
        cues = parse_srt(out.read_text("utf8", "replace"))
        if len(cues) > max(5, len(best)):
            best = cues
            if s["sdh"] or len(tracks) == 1:
                break
    return best, ("subtitles inside the video" if best else "")


SPOKEN_STRIP = re.compile(r"\[[^\]]*\]|\([^)]*\)|^[A-Z][A-Z .'-]{1,20}:|^\s*-\s*|♪", re.M)
SDH_VIOLENCE = re.compile(r"gun|shot|scream|explo|punch|stab|groan|grunt|gasp|shriek|thud|"
                          r"fight|struggl|body falls|bones? crack|blood|machine gun", re.I)
SDH_SEX = re.compile(r"moan|pant|sexual|climax|orgasm|kissing passionately|bed creak", re.I)


def spoken_words(text):
    """Words actually said in a cue (no [sound tags], (notes) or SPEAKER: labels)."""
    return SPOKEN_STRIP.sub(" ", text).split()


# ---------------------------------------------------------------------------
# Listening (dialogue) and the sound-event scan
# ---------------------------------------------------------------------------
def _audio_cmd(path, info, dialogue):
    a = info["audio"]
    mix = ["-af", "pan=mono|c0=FC"] if dialogue and a["channels"] >= 5 else ["-ac", "1"]
    return [cl._tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", f"0:{a['index']}",
            "-vn", "-sn", *mix, "-ar", str(SR), "-f", "f32le", "-"]


def _stream_chunks(cmd, chunk, overlap, cancel=None):
    """Yield (offset_seconds, samples, is_last) from ffmpeg's raw output."""
    proc = cl.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    C, O = int(chunk * SR), int(overlap * SR)
    buf, offset, eof = np.zeros(0, dtype=np.float32), 0.0, False
    try:
        while True:
            if cancel and cancel():
                raise KeyboardInterrupt
            while not eof and len(buf) < C:
                data = proc.stdout.read((C - len(buf)) * 4)
                if not data:
                    eof = True
                    break
                data = data[: len(data) // 4 * 4]
                buf = np.concatenate([buf, np.frombuffer(data, dtype=np.float32)])
            last = eof and len(buf) <= C
            yield offset, buf[:C], last
            if last:
                break
            buf = buf[C - O:]
            offset += (C - O) / SR
    finally:
        proc.kill()
        proc.wait()


def transcribe(path, info, rec, progress=None, cancel=None, chunk=30.0, overlap=2.0):
    def go(dialogue):
        out, first = [], True
        for offset, seg, last in _stream_chunks(_audio_cmd(path, info, dialogue), chunk, overlap, cancel):
            if len(seg) > SR * 0.2:
                s = rec.create_stream()
                s.accept_waveform(SR, seg)
                rec.decode_stream(s)
                lo = offset + (overlap / 2 if not first else -1)
                hi = offset + chunk - overlap / 2 if not last else 1e12
                out.extend(w for w in cl.tokens_to_words(s.result, offset) if lo <= w["s"] < hi)
            first = False
            if progress:
                progress(offset + len(seg) / SR)
        return out

    words = go(True)
    if not words and info["audio"]["channels"] >= 5:
        words = go(False)  # no centre (dialogue) channel after all: use the full mix
    return words


# label -> weight. Violence is judged by sound (gunfire, explosions,
# screaming, blows); there is no reliable way to "see" gore on a home PC.
VIOLENCE_SOUNDS = {"Gunshot, gunfire": 1.0, "Machine gun": 1.0, "Fusillade": 1.0,
                   "Artillery fire": 0.8, "Explosion": 0.7, "Screaming": 0.8,
                   "Battle cry": 0.5, "Slap, smack": 0.5, "Whack, thwack": 0.5,
                   "Smash, crash": 0.25}
INTIMATE_SOUNDS = {"Breathing": 0.6, "Pant": 0.8, "Gasp": 0.5, "Sigh": 0.4,
                   "Wail, moan": 0.8, "Groan": 0.5}
TRACKED = list(VIOLENCE_SOUNDS) + [k for k in INTIMATE_SOUNDS if k not in VIOLENCE_SOUNDS]
SOUND_WIN, SOUND_HOP = 3.0, 1.5


def load_tagger(threads=None):
    import sherpa_onnx
    threads = threads or max(1, min(4, (os.cpu_count() or 2)))
    cfg = sherpa_onnx.AudioTaggingConfig(
        model=sherpa_onnx.AudioTaggingModelConfig(ced=str(TAG_DIR / "model.int8.onnx"),
                                                  num_threads=threads),
        labels=str(TAG_DIR / "class_labels_indices.csv"), top_k=5)
    return sherpa_onnx.AudioTagging(cfg)


def sound_scan(path, info, tagger, progress=None, cancel=None):
    """Probabilities of the tracked sounds in 3-second windows every 1.5 s.
    Returns {"t": [...window starts], "p": [[...per TRACKED label]]}."""
    ts, rows = [], []
    for offset, seg, last in _stream_chunks(_audio_cmd(path, info, False), SOUND_WIN,
                                            SOUND_WIN - SOUND_HOP, cancel):
        if len(seg) < SR * 0.5:
            continue
        s = tagger.create_stream()
        s.accept_waveform(SR, seg)
        got = {e.name: e.prob for e in tagger.compute(s, top_k=527)}
        ts.append(round(offset, 2))
        rows.append([round(float(got.get(k, 0.0)), 3) for k in TRACKED])
        if progress:
            progress(offset + len(seg) / SR)
    return {"labels": TRACKED, "t": ts, "p": rows}


# ---------------------------------------------------------------------------
# The picture scan (runs in its own process so its libraries never clash
# with the speech model's)
# ---------------------------------------------------------------------------
NUDE_CLASSES = ["FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED",
                "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED",
                "ANUS_EXPOSED", "FEET_EXPOSED", "BELLY_COVERED", "FEET_COVERED",
                "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE", "BELLY_EXPOSED",
                "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED",
                "BUTTOCKS_COVERED"]
NUDITY = {"FEMALE_BREAST_EXPOSED": 0.5, "FEMALE_GENITALIA_EXPOSED": 0.45,
          "MALE_GENITALIA_EXPOSED": 0.45, "BUTTOCKS_EXPOSED": 0.5, "ANUS_EXPOSED": 0.45}
SKIN = {"MALE_BREAST_EXPOSED": 0.45, "BELLY_EXPOSED": 0.45, "ARMPITS_EXPOSED": 0.45}
KEEP = list(NUDITY) + list(SKIN)


def _visual_scan_here(path, out_json, fps=VISUAL_FPS):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, min(6, (os.cpu_count() or 2) - 1))
    sess = ort.InferenceSession(str(nudity_model()), opts, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    cols = [NUDE_CLASSES.index(k) for k in KEEP]
    cmd = [cl._tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:v:0", "-an", "-sn",
           "-vf", f"fps={fps},scale=320:320:force_original_aspect_ratio=decrease,"
                  "pad=320:320:0:0:black,format=bgr24", "-f", "rawvideo", "-"]  # same channel order NudeNet itself feeds the model
    proc = cl.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size, batch, n, out = 320 * 320 * 3, 8, 0, []
    try:
        while True:
            frames = []
            for _ in range(batch):
                data = proc.stdout.read(size)
                if len(data) < size:
                    break
                frames.append(np.frombuffer(data, dtype=np.uint8).reshape(320, 320, 3))
            if not frames:
                break
            x = np.stack(frames).astype(np.float32).transpose(0, 3, 1, 2) / 255.0
            y = sess.run(None, {name: x})[0]          # (batch, 4 + 18, anchors)
            best = y[:, 4:, :].max(axis=2)            # best score per class per frame
            for row in best:
                out.append([round(float(row[c]), 3) for c in cols])
            n += len(frames)
            print(f"P {n / fps:.1f}", flush=True)
            if len(frames) < batch:
                break
    finally:
        proc.kill()
        proc.wait()
    Path(out_json).write_text(json.dumps({"fps": fps, "classes": KEEP, "scores": out}))


def visual_scan(path, out_json, progress=None, cancel=None):
    cmd = [_venv_python(), str(HERE / "cleanview.py"), "visualscan", str(path), str(out_json)]
    errf = Path(out_json).with_suffix(".err.txt")
    with open(errf, "w", encoding="utf8") as err:
        proc = cl.popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            for line in proc.stdout:
                if cancel and cancel():
                    proc.kill()
                    raise KeyboardInterrupt
                if line.startswith("P ") and progress:
                    progress(float(line[2:]))
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
    if proc.returncode != 0 or not Path(out_json).exists():
        raise RuntimeError("The picture check failed:\n" + errf.read_text("utf8", "replace")[-800:])
    return json.loads(Path(out_json).read_text())


# ---------------------------------------------------------------------------
# Turning scan results into scenes
# ---------------------------------------------------------------------------
def _group(times, gap):
    """Group sorted times into runs where neighbours are <= gap apart."""
    runs = []
    for t in times:
        if runs and t - runs[-1][-1] <= gap:
            runs[-1].append(t)
        else:
            runs.append([t])
    return runs


def nudity_scenes(vis, start_off=0.0):
    if not vis or not vis["scores"]:
        return [], []
    fps, cls = vis["fps"], vis["classes"]
    nude_i = [cls.index(k) for k in NUDITY]
    skin_i = [cls.index(k) for k in SKIN]
    hits, strong, skin = [], {}, []
    for n, row in enumerate(vis["scores"]):
        t = start_off + n / fps
        best = max((row[i] / NUDITY[cls[i]], cls[i]) for i in nude_i)
        if best[0] >= 1.0:
            hits.append(t)
            strong[t] = row[cls.index(best[1])]
        if any(row[i] >= SKIN[cls[i]] for i in skin_i):
            skin.append(t)
    scenes = []
    for run_ in _group(hits, 5.0):
        # a single weak frame on its own is usually a false alarm (a bare shoulder)
        if len(run_) == 1 and strong[run_[0]] < 0.7:
            continue
        scenes.append({"s": max(0.0, run_[0] - 1.5), "e": run_[-1] + 1.5, "kind": ["Nudity"],
                       "why": f"nudity seen in {len(run_)} picture check{'s' if len(run_) > 1 else ''}"})
    return scenes, skin


def violence_scenes(snd, cues):
    if not snd or not snd["t"]:
        return []
    labels = snd["labels"]
    vi = [(labels.index(k), w) for k, w in VIOLENCE_SOUNDS.items()]
    flagged, why = [], {}
    for t, row in zip(snd["t"], snd["p"]):
        score = sum(row[i] * w for i, w in vi)
        if score >= 0.45:
            flagged.append(t)
            top = max(vi, key=lambda iw: row[iw[0]] * iw[1])
            why.setdefault(t, labels[top[0]].split(",")[0].lower())
    # SDH subtitles often describe violence: [gunshot], [screaming], [grunts]
    for c in cues:
        tags = " ".join(a or b for a, b in re.findall(r"\[([^\]]*)\]|\(([^)]*)\)", c["text"]))
        if tags and SDH_VIOLENCE.search(tags):
            for t in np.arange(c["s"], max(c["s"], c["e"] - SOUND_WIN) + 0.01, SOUND_HOP):
                flagged.append(round(float(t), 2))   # the whole time the tag is on screen
            why.setdefault(round(float(c["s"]), 2), tags.lower()[:30])
    flagged.sort()
    scenes = []
    for run_ in _group(flagged, 8.0):
        span = run_[-1] - run_[0]
        if len(run_) < 3 and span < 3:   # one bang or slap isn't a violent scene
            continue
        kinds = []
        for t in run_:
            w = why.get(t)
            if w and w not in kinds:
                kinds.append(w)
        scenes.append({"s": max(0.0, run_[0] - 1.0), "e": run_[-1] + SOUND_WIN + 1.0,
                       "kind": ["Violence"], "why": ", ".join(kinds[:4])})
    return scenes


def sex_scenes(snd, cues, asr_n, asr, skin, nude):
    """Sex scenes without visible nudity: intimate sounds together with bare
    skin on screen, SDH tags like [moaning], or explicit dialogue."""
    marks = []
    if snd and snd["t"]:
        labels = snd["labels"]
        ii = [(labels.index(k), w) for k, w in INTIMATE_SOUNDS.items()]
        intimate = [t for t, row in zip(snd["t"], snd["p"])
                    if sum(row[i] * w for i, w in ii) >= 0.5]
        skin_set = sorted(skin + [s["s"] for s in nude])
        import bisect
        for run_ in _group(intimate, 4.5):
            if run_[-1] - run_[0] < 6:
                continue
            k = bisect.bisect_left(skin_set, run_[0] - 10)
            if k < len(skin_set) and skin_set[k] <= run_[-1] + 10:
                marks.append((run_[0], run_[-1] + SOUND_WIN, "intimate sounds with bare skin"))
    for c in cues:
        if any(SDH_SEX.search(t) for t in re.findall(r"\[([^\]]*)\]", c["text"])):
            marks.append((c["s"], c["e"], "subtitles describe it"))
    # explicit dialogue (same scoring CleanListen uses for books)
    k = 0
    while k < len(asr):
        j = k
        while j < len(asr) and asr[j]["s"] - asr[k]["s"] < 60:
            j += 1
        if cl.sex_score(asr_n[k:j]) >= cl.SEX_WINDOW_SCORE:
            hits = [x for x in range(k, j) if cl.is_explicit([asr_n[x]])]
            marks.append((asr[hits[0]]["s"] - 2, asr[hits[-1]]["e"] + 2, "explicit dialogue"))
        k = j if j > k else k + 1
    marks.sort()
    scenes = []
    for s, e, w in marks:
        if scenes and s - scenes[-1]["e"] <= 10:
            scenes[-1]["e"] = max(scenes[-1]["e"], e)
            if w not in scenes[-1]["why"]:
                scenes[-1]["why"] += ", " + w
        else:
            scenes.append({"s": max(0.0, s - 1.0), "e": e + 1.0, "kind": ["Sex scene"], "why": w})
    return scenes


def merge_scenes(scenes):
    out = []
    for sc in sorted(scenes, key=lambda x: x["s"]):
        if out and sc["s"] <= out[-1]["e"] + 2.0:
            o = out[-1]
            o["e"] = max(o["e"], sc["e"])
            o["kind"] += [k for k in sc["kind"] if k not in o["kind"]]
            o["why"] = "; ".join(x for x in (o["why"], sc["why"]) if x)
        else:
            out.append(dict(sc, kind=list(sc["kind"])))
    return out


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------
def analyze(path, workdir, groups=("swearing", "mild", "deity"), find_nudity=True,
            find_sex=True, find_violence=True, progress=None, log=print, cancel=None,
            model_dir=cl.DEFAULT_MODEL, threads=None):
    """progress(fraction 0..1, message). Saves and returns workdir/analysis.json."""
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    path = str(Path(path).resolve())
    say = progress or (lambda f, m: None)
    info = probe(path)
    dur = info["duration"] or 1.0
    cats = [c for g in groups for c in cl.GROUPS[g]]
    t_start = time.time()

    def eta(frac_done):
        el = time.time() - t_start
        if frac_done < 0.03 or el < 20:
            return "estimating time…"
        return f"about {max(1, el / frac_done * (1 - frac_done) / 60):.0f} min left"

    # weights of each step in the progress bar
    W_ASR, W_SND = 0.45, 0.10
    W_VIS = 0.40 if (find_nudity or find_sex) else 0.0
    total_w = W_ASR + W_SND + W_VIS
    base = {"asr": 0.0, "snd": W_ASR / total_w, "vis": (W_ASR + W_SND) / total_w}

    tfile = work / "transcript.json"
    if tfile.exists():
        asr = json.loads(tfile.read_text())
    else:
        say(0.0, "Loading the listening model…")
        rec = load_recognizer(model_dir, threads)

        def p_asr(sec):
            f = min(1.0, sec / dur) * W_ASR / total_w
            say(f * 0.97, f"Listening to the dialogue · {eta(f)}")
        asr = transcribe(path, info, rec, p_asr, cancel)
        tfile.write_text(json.dumps(asr))
        del rec
    log(f"Heard {len(asr)} words")
    for w in asr:
        w["n"], w["part"] = cl.norm(w["t"]), 0
    asr_n = [w["n"] for w in asr]

    snd = None
    if find_violence or find_sex:
        sfile = work / "sounds.json"
        if sfile.exists():
            snd = json.loads(sfile.read_text())
        else:
            say(base["snd"] * 0.97, "Listening for fights, gunfire and other sounds…")
            tagger = load_tagger()

            def p_snd(sec):
                f = base["snd"] + min(1.0, sec / dur) * W_SND / total_w
                say(f * 0.97, f"Listening for fights, gunfire and other sounds · {eta(f)}")
            snd = sound_scan(path, info, tagger, p_snd, cancel)
            sfile.write_text(json.dumps(snd))

    vis = None
    if find_nudity or find_sex:
        vfile = work / "pictures.json"
        if vfile.exists():
            vis = json.loads(vfile.read_text())
        else:
            say(base["vis"] * 0.97, "Watching the picture for nudity…")

            def p_vis(sec):
                f = base["vis"] + min(1.0, sec / dur) * W_VIS / total_w
                say(f * 0.97, f"Watching the picture for nudity · {eta(f)}")
            vis = visual_scan(path, vfile, p_vis, cancel)

    say(0.97, "Finding language…")
    cues, sub_note = find_subtitles(path, info, work)
    mutes = [{"s": asr[i]["s"], "e": asr[j - 1]["e"], "cat": cat, "src": "audio",
              "word": " ".join(cl.mask(asr[k]["t"]) for k in range(i, j)),
              "ctx": " ".join(asr[k]["t"] for k in range(max(0, i - 6), i))}
             for i, j, cat in cl.find_language(asr_n, cats)]
    if cues and cats:
        sw, sw_cue = [], []
        for ci, c in enumerate(cues):
            for w in spoken_words(c["text"]):
                if cl.norm(w):
                    sw.append(w)
                    sw_cue.append(ci)
        sn = [cl.norm(w) for w in sw]
        mapping = cl.align(sn, asr_n) if asr_n else [None] * len(sn)
        added = 0
        for i, j, cat in cl.find_language(sn, cats):
            t = cl.est_time(i, mapping, asr) if asr else None
            if t:
                s, e, exact = t[0], t[1], t[2]
                if j - i > 1:
                    t2 = cl.est_time(j - 1, mapping, asr)
                    if t2:
                        e = max(e, t2[1])
                src = "subtitles" if exact else "subtitles-estimated"
            else:
                # fall back on the subtitle's own timing: place the word by its
                # position in the line and mute generously around it
                c = cues[sw_cue[i]]
                words_in = [k for k, ci in enumerate(sw_cue) if ci == sw_cue[i]]
                frac = (words_in.index(i) + 0.5) / max(1, len(words_in))
                mid = c["s"] + (c["e"] - c["s"]) * frac
                s, e = max(c["s"], mid - 0.7), min(c["e"], mid + 0.7 + 0.3 * (j - i - 1))
                src = "subtitles-estimated"
            if any(m["s"] - 0.8 <= s <= m["e"] + 0.8 for m in mutes):
                continue
            mutes.append({"s": round(s, 3), "e": round(e, 3), "cat": cat, "src": src,
                          "word": " ".join(cl.mask(w) for w in sw[i:j]),
                          "ctx": " ".join(sw[max(0, i - 6):i])})
            added += 1
        sub_note = f"Checked against {sub_note}: caught {added} extra word(s)."
        log(sub_note)
    elif cats:
        sub_note = "No subtitles found, so language was found by listening only."
    mutes.sort(key=lambda m: m["s"])
    say(0.98, "Fine-tuning mute timing…")
    for m in mutes:
        m["s"], m["e"] = cl.snap_edges(path, m["s"], m["e"], wide=m["src"] != "audio")

    say(0.99, "Putting the scene list together…")
    nude, skin = nudity_scenes(vis) if vis else ([], [])
    scenes = []
    if find_nudity:
        scenes += nude
    if find_violence:
        scenes += violence_scenes(snd, cues)
    if find_sex:
        scenes += sex_scenes(snd, cues, asr_n, asr, skin, nude)
    scenes = merge_scenes(scenes)
    for n, sc in enumerate(scenes, 1):
        sc["id"], sc["cut"] = n, True
        sc["e"] = min(sc["e"], dur)
        sc["s"], sc["e"] = round(sc["s"], 2), round(sc["e"], 2)
        said = [w["t"] for w in asr if sc["s"] <= w["s"] <= sc["e"]]
        sc["said"] = " ".join(said[:80]) + (" …" if len(said) > 80 else "")
    make_thumbs(path, scenes, work)

    st = {"path": path, "info": info, "groups": list(groups), "mutes": mutes, "scenes": scenes,
          "cues": cues, "sub_note": sub_note, "duration": dur, "words": len(asr),
          "checked": {"nudity": find_nudity, "sex": find_sex, "violence": find_violence}}
    (work / "analysis.json").write_text(json.dumps(st, indent=1))
    say(1.0, "Done.")
    return st


def load_recognizer(model_dir=cl.DEFAULT_MODEL, threads=None):
    return cl.load_recognizer(model_dir, threads)


def make_thumbs(path, scenes, work):
    """Three heavily blurred stills per scene, so you can tell scenes apart
    without seeing anything you don't want to."""
    d = Path(work) / "thumbs"
    d.mkdir(exist_ok=True)
    for sc in scenes:
        sc["thumbs"] = []
        for k in range(3):
            t = sc["s"] + (sc["e"] - sc["s"]) * (k + 1) / 4
            out = d / f"{sc['id']}_{k}.png"
            r = cl.run([cl._tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
                        "-map", "0:v:0", "-frames:v", "1", "-vf",
                        "scale=24:-2,scale=180:-2:flags=bilinear,boxblur=6:2,format=rgb24", str(out)], capture_output=True)
            if r.returncode == 0 and out.exists():
                sc["thumbs"].append(str(out))


def make_preview(path, s, e, workdir):
    """A short copy of one scene to look at in your own video player."""
    out = Path(workdir) / f"preview_{int(s)}.mkv"
    if not out.exists():
        start = max(0.0, s - 2)
        r = cl.run([cl._tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(path),
                    "-t", f"{e - start + 1:.2f}", "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                    str(out)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("Couldn't make the preview:\n" + r.stderr[-400:])
    return str(out)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
ENCODERS = [
    ("h264_nvenc", ["-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-pix_fmt", "yuv420p"]),
    ("h264_qsv", ["-global_quality", "22", "-preset", "medium", "-pix_fmt", "nv12"]),
    ("h264_amf", ["-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22", "-qp_b", "24",
                  "-pix_fmt", "yuv420p"]),
    ("libx264", ["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]),
]


def working_encoders():
    """Hardware video encoders that actually work on this PC, fastest first;
    libx264 (always works, slower) last."""
    ok = []
    for name, args in ENCODERS[:-1]:
        r = cl.run([cl._tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=320x240:d=0.3", "-c:v", name, *args, "-f", "null", "-"],
                   capture_output=True)
        if r.returncode == 0:
            ok.append((name, args))
    return ok + [ENCODERS[-1]]


def _ranges(rs, off):
    return "+".join(f"between(t,{s + off:.3f},{e + off:.3f})" for s, e in rs)


def _removed_expr(cuts, off):
    return "+".join(f"gte(T,{e + off:.3f})*{e - s:.3f}" for s, e in cuts) or "0"


def _merge(rs):
    out = []
    for s, e in sorted(rs):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


def _shift(t, cuts):
    removed = sum(min(e, t) - s for s, e in cuts if s < t)
    return max(0.0, t - removed)


def clean_cues(cues, cats, mutes, cuts):
    """Subtitles for the clean copy: language blanked, cut scenes dropped,
    times moved up to match."""
    out = []
    for c in cues:
        if any(s <= c["s"] and c["e"] <= e for s, e in cuts):
            continue
        s, e = c["s"], c["e"]
        for cs, ce in cuts:
            if cs < e and ce > s:          # partly inside a cut: keep the part outside
                if cs > s:
                    e = min(e, cs)
                else:
                    s = max(s, ce)
        if e - s < 0.3:
            continue
        text = c["text"]
        if cats:
            toks = re.split(r"(\s+)", text)
            idx = [k for k, tk in enumerate(toks) if tk.strip()]
            normed = [cl.norm(toks[k]) for k in idx]
            for i, j, _ in cl.find_language(normed, cats):
                for q in range(i, j):
                    tk = toks[idx[q]]
                    lead = re.match(r"^\W*", tk).group(0)
                    trail = re.search(r"\W*$", tk).group(0)
                    toks[idx[q]] = lead + "—" + trail
            text = "".join(toks)
        out.append({"s": _shift(s, cuts), "e": _shift(e, cuts), "text": text})
    return out


def _fmt_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def write_srt(cues, dst):
    Path(dst).write_text("\n".join(f"{n}\n{_fmt_srt(c['s'])} --> {_fmt_srt(c['e'])}\n{c['text']}\n"
                                   for n, c in enumerate(cues, 1)), encoding="utf8")


def render(workdir, outdir, cuts=None, progress=None, log=print, cancel=None, encoders=None):
    """Write the clean copy. cuts: list of {"s","e"} (default: scenes with cut=True)."""
    work = Path(workdir)
    st = json.loads((work / "analysis.json").read_text())
    if cuts is None:
        cuts = [c for c in st["scenes"] if c.get("cut")]
    say = progress or (lambda f, m: None)
    info = st["info"]
    src = Path(st["path"])
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    dur = st["duration"]
    off = info.get("start", 0.0)
    cut_rs = _merge((max(0.0, c["s"]), min(dur, c["e"])) for c in cuts)
    mute_rs = _merge((m["s"], m["e"]) for m in st["mutes"])
    reencode = bool(cut_rs)
    mp4 = reencode or src.suffix.lower() in (".mp4", ".m4v", ".mov")
    dst = out / f"{src.stem} (Clean){'.mp4' if mp4 else '.mkv'}"

    cats = [c for g in st["groups"] for c in cl.GROUPS[g]]
    subs = clean_cues(st["cues"], cats, mute_rs, cut_rs) if st["cues"] else []
    srt = None
    if subs:
        srt = work / "clean.srt"
        write_srt(subs, srt)

    a = info["audio"]
    afilt = ["aresample"]   # copes with files whose speaker layout changes mid-stream
    if mute_rs:
        afilt.append(f"volume=volume=0:enable='{_ranges(mute_rs, off)}'")
    if cut_rs:
        afilt.append(f"aselect='not({_ranges(cut_rs, off)})',"
                     f"asetpts='PTS-({_removed_expr(cut_rs, off)})/TB'")
    (work / "afilter.txt").write_text(",".join(afilt))
    (work / "vfilter.txt").write_text(
        f"select='not({_ranges(cut_rs, off)})',setpts='PTS-({_removed_expr(cut_rs, off)})/TB'"
        if cut_rs else "null")
    abr = "448k" if a["channels"] > 2 else "192k"
    if a["bit_rate"]:
        abr = str(min(max(a["bit_rate"], 128000), 640000 if a["channels"] > 2 else 320000))

    encs = (encoders or working_encoders()) if reencode else [("copy", [])]
    expected = max(1.0, dur - sum(e - s for s, e in cut_rs))
    tmp = dst.with_name(dst.stem + ".partial" + dst.suffix)

    def build(vname, vargs, new_style):
        def fopt(kind):  # ffmpeg 7+ spells it "-/filter:a"; older builds "-filter_script:a"
            return f"-/filter:{kind}" if new_style else f"-filter_script:{kind}"
        cmd = [cl._tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
               "-i", str(src)]
        if srt:
            cmd += ["-i", str(srt)]
        cmd += ["-map", f"0:{info['video']['index']}", "-map", f"0:{a['index']}"]
        if srt:
            cmd += ["-map", "1:0", "-c:s", "mov_text" if mp4 else "srt",
                    "-metadata:s:s:0", "language=eng"]
        ch = a["channels"]
        cmd += [fopt("a"), str(work / "afilter.txt"), "-c:a", "aac", "-b:a", abr,
                "-ac", str(ch if ch in (1, 2, 6, 8) else 2)]
        if reencode:
            cmd += [fopt("v"), str(work / "vfilter.txt"), "-c:v", vname, *vargs, "-fps_mode", "vfr"]
        else:
            cmd += ["-c:v", "copy"]
            if mp4 and info["video"]["codec"] == "hevc":
                cmd += ["-tag:v", "hvc1"]
        cmd += ["-map_metadata", "0", "-map_chapters", "-1" if reencode else "0"]
        if mp4:
            cmd += ["-movflags", "+faststart"]
        return cmd + [str(tmp)]

    def attempt(cmd, label):
        say(0.0, label + "…")
        errf = work / "render_err.txt"
        with open(errf, "w", encoding="utf8") as err:
            proc = cl.popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
            t0 = time.time()
            try:
                for line in proc.stdout:
                    if cancel and cancel():
                        raise KeyboardInterrupt
                    if line.startswith("out_time_us="):
                        try:
                            sec = int(line.split("=")[1]) / 1e6
                        except ValueError:
                            continue
                        f = min(0.99, max(0.0, sec / expected))
                        el = time.time() - t0
                        left = f" · about {el / f * (1 - f) / 60:.0f} min left" if f > 0.03 and el > 15 else "…"
                        say(f, label + left)
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if proc.returncode == 0:
            os.replace(tmp, dst)
            return True, ""
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, errf.read_text("utf8", "replace")

    done, last_err = False, ""
    for vname, vargs in encs:
        label = "Saving the clean copy" + (" (using your graphics card)"
                                          if vname.endswith(("nvenc", "qsv", "amf")) else "")
        for new_style in (True, False):
            done, last_err = attempt(build(vname, vargs, new_style), label)
            if done or ("Unrecognized option" not in last_err and "Option not found" not in last_err):
                break
        if done:
            break
        log(f"{vname} didn't work, trying the next way: {last_err[-200:]}")
    if not done:
        raise RuntimeError(f"Couldn't save the clean copy of {src.name}:\n{last_err[-800:]}")

    if srt:
        shutil.copyfile(srt, dst.with_suffix(".en.srt"))
    removed = sum(e - s for s, e in cut_rs)
    rep = [f"CleanView report — {src.name}", "=" * 40,
           f"{len(st['mutes'])} words/phrases muted, {len(cut_rs)} scenes cut "
           f"({removed / 60:.1f} minutes removed)."]
    if st.get("sub_note"):
        rep.append(st["sub_note"])
    if info.get("audio_tracks", 1) > 1:
        rep.append("Only the main soundtrack was kept (other languages and commentary "
                   "weren't cleaned, so they were left out).")
    rep.append("")
    events = [(m["s"], f"muted  {m['word']}" + ("" if m["src"] == "audio" else "   (caught by subtitles)"))
              for m in st["mutes"]]
    events += [(c["s"], f"CUT {c['e'] - c['s']:.0f} seconds  {' + '.join(c.get('kind') or ['scene'])}"
                        f"  ({c.get('why', '')})") for c in cuts]
    rep += [f"  {cl.fmt_t(t)}  {txt}" for t, txt in sorted(events)]
    (out / f"{src.stem} - CleanView report.txt").write_text("\n".join(rep) + "\n", encoding="utf8")
    say(1.0, "Saved.")
    log(f"Saved {dst}")
    return {"mutes": len(st["mutes"]), "cuts": len(cut_rs), "cut_minutes": removed / 60,
            "out": str(dst), "folder": str(out)}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyze")
    an.add_argument("workdir")
    an.add_argument("video")
    an.add_argument("--groups", default="swearing,mild,deity")
    an.add_argument("--no-nudity", action="store_true")
    an.add_argument("--no-sex", action="store_true")
    an.add_argument("--no-violence", action="store_true")
    rn = sub.add_parser("render")
    rn.add_argument("workdir")
    rn.add_argument("outdir")
    vs = sub.add_parser("visualscan")
    vs.add_argument("video")
    vs.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "visualscan":
        _visual_scan_here(a.video, a.out)
    elif a.cmd == "analyze":
        st = analyze(a.video, a.workdir, [g for g in a.groups.split(",") if g], not a.no_nudity,
                     not a.no_sex, not a.no_violence,
                     progress=lambda f, m: print(f"[{f * 100:3.0f}%] {m}", flush=True))
        print(f"{st['words']} words; {len(st['mutes'])} to mute; {len(st['scenes'])} scenes flagged")
    else:
        print(render(a.workdir, a.outdir, progress=lambda f, m: print(f"[{f * 100:3.0f}%] {m}", flush=True)))


if __name__ == "__main__":
    _cli()
