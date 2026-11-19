"""PDF -> ebook (CleanRead 1.17.74; the owner, 2026-11-19: "I have some old books that are pdfs but its
more just like images saved in a pdf, so isn't really optimized for reading").

Turns a PDF book into an EPUB with flowing text for a phone or e-reader:
- each page is read with the small PDF page reader `pypdfium2` (fetched once, ~3 MB, like the
  other add-ons; new installs get it from install.ps1). Windows' own PDF reader can't draw the
  Internet Archive's scans (their pages came out as grey smudges), so it isn't used.
- a page with real text uses that text and where each word sits on the page. A page that is only
  a picture (a scan) is drawn and read by **Windows' own text recognition** (Windows.Media.Ocr,
  built into Windows 10 and 11, offline, ~0.1 s a page), through one PowerShell helper that stays
  open for the whole book (`WinOcr`). Nothing else to download, no graphics card needed.
- the words' places on the page find the page numbers and running heads/feet (dropped), the
  paragraphs (an indented line, a short last line, a gap), words split at a line end ("ques-"
  "tions"; kept when the book writes "twenty-five" elsewhere), chapter headings ("Chapter 3",
  a lone big number, a big centred title followed by text), scene breaks, the contents page and
  the "Digitized by the Internet Archive" page (both dropped; the EPUB has its own contents).
- the first page becomes the cover when it's a picture; title and author come from the PDF's
  details (else the file name and a "by ..." line on the first pages).
What each page gave is kept in APP_DATA/pdf_ebooks/<book>/pages.jsonl, so Cancel and doing it again
carry on where it stopped.

`convert(pdf, ...)` -> {"out", "title", "author", "pages", "read_pages" (recognised from pictures),
"chapters", "paras", "sample", "seconds"}. `kind(pdf)` says quickly whether a PDF is pictures of
pages ("pictures"), has text ("text"), or can't be opened (None). Plain words in every error
(`ConvertError`); `Stopped` when cancelled.
"""
import base64
import hashlib
import html
import json
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
WORK = APP_DATA / "pdf_ebooks"
FORMAT = 1                 # what pages.jsonl holds; a new number reads every page again
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}      # no console window


class ConvertError(Exception):
    """Something to tell the user, in plain words."""


class Stopped(Exception):
    """Cancelled."""


# ---------------------------------------------------------------------------
# the PDF page reader (pypdfium2), fetched once
# ---------------------------------------------------------------------------
def _pip_python():
    """The venv's python.exe (the window runs as CleanRead.exe, a renamed pythonw.exe)."""
    for p in (Path(sys.prefix) / "Scripts" / "python.exe", Path(sys.executable).with_name("python.exe"),
              Path(sys.prefix) / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def reader(progress=None):
    """pypdfium2, getting it the first time (one small download)."""
    try:
        import pypdfium2
        return pypdfium2
    except ImportError:
        pass
    except Exception:
        raise ConvertError("Windows wouldn't let the PDF page reader start. Restart the computer and "
                           "try again.")
    if progress:
        progress(0.0, "Getting the PDF page reader (one time, about 3 MB)…")
    try:
        r = subprocess.run([_pip_python(), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "--no-input", "pypdfium2"], capture_output=True, text=True, timeout=600, **_NOWIN)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        raise ConvertError("Couldn't get the PDF page reader. Check the internet connection and try "
                           "again (it's only needed once).")
    import importlib
    importlib.invalidate_caches()
    try:
        import pypdfium2
        return pypdfium2
    except Exception:
        raise ConvertError("The PDF page reader didn't start. Close CleanRead, open it again and try again.")


def _open(pdfium, path):
    try:
        return pdfium.PdfDocument(str(path))
    except Exception as ex:
        low = str(ex).lower()
        if "password" in low:
            raise ConvertError("This PDF is locked with a password, so it can't be read.")
        if "not found" in low or "no such file" in low:
            raise ConvertError("The PDF wasn't found. Was it moved or renamed?")
        raise ConvertError("This PDF couldn't be opened. It may be damaged.")


def kind(path):
    """'pictures' (scanned pages with no text in them), 'text', or None (can't tell). Quick: looks
    at up to 12 pages spread through the book, with pypdf (already installed)."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        if r.is_encrypted and not r.decrypt(""):
            return None
        n = len(r.pages)
        if not n:
            return None
        picks = sorted({min(n - 1, round(i * (n - 1) / 11)) for i in range(12)}) if n > 12 else range(n)
        empty = 0
        for i in picks:
            letters = len(re.findall(r"[^\W\d_]", r.pages[i].extract_text() or ""))
            empty += letters < 30
        return "pictures" if empty >= 0.5 * len(picks) else "text"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Windows' own text recognition, through one PowerShell helper for the whole book
# ---------------------------------------------------------------------------
_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$lang = '__LANG__'
function Out1($o) { $j = ConvertTo-Json -Compress -Depth 6 $o
  [Console]::Out.WriteLine([regex]::Replace($j, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value }))
  [Console]::Out.Flush() }
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  $null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapEncoder, Windows.Foundation, ContentType = WindowsRuntime]
  $ms = [System.WindowsRuntimeSystemExtensions].GetMethods()
  $asT = ($ms | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $asA = ($ms | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
  function Await($op, [Type]$t) { $k = $asT.MakeGenericMethod($t).Invoke($null, @($op)); $k.Wait(-1) | Out-Null; $k.Result }
  function AwaitA($op) { $k = $asA.Invoke($null, @($op)); $k.Wait(-1) | Out-Null }
  $engine = $null
  if ($lang) { try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($lang)) } catch { } }
  if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if (-not $engine) { Out1 @{ error = 'no-language' }; exit 2 }
  Out1 @{ ready = $engine.RecognizerLanguage.LanguageTag; max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension }
} catch { Out1 @{ error = $_.Exception.Message }; exit 3 }
function Bitmap($path) {
  $f = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $s = Await ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $b = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $s.Dispose(); $b }
while ($null -ne ($cmd = [Console]::In.ReadLine())) {
  if (-not $cmd) { continue }
  $part = $cmd.Split('|')
  try {
    if ($part[0] -eq 'ocr') {
      $b = Bitmap $part[1]
      $r = Await ($engine.RecognizeAsync($b)) ([Windows.Media.Ocr.OcrResult])
      $lines = @()
      foreach ($l in $r.Lines) { $ws = @()
        foreach ($w in $l.Words) { $q = $w.BoundingRect; $ws += ,@($w.Text, [int]$q.X, [int]$q.Y, [int]$q.Width, [int]$q.Height) }
        $lines += ,$ws }
      $b.Dispose()
      Out1 @{ lines = $lines; angle = $r.TextAngle }
    } elseif ($part[0] -eq 'jpeg') {
      $b = Bitmap $part[1]
      $folder = Split-Path -Parent $part[2]
      $null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
      $fo = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($folder)) ([Windows.Storage.StorageFolder])
      $of = Await ($fo.CreateFileAsync((Split-Path -Leaf $part[2]), [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
      $os = Await ($of.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
      $e = Await ([Windows.Graphics.Imaging.BitmapEncoder]::CreateAsync([Windows.Graphics.Imaging.BitmapEncoder]::JpegEncoderId, $os)) ([Windows.Graphics.Imaging.BitmapEncoder])
      $e.SetSoftwareBitmap($b)
      AwaitA ($e.FlushAsync())
      $os.Dispose(); $b.Dispose()
      Out1 @{ done = 1 }
    }
  } catch { Out1 @{ fail = $_.Exception.Message } }
}
"""


class WinOcr:
    """Windows' text recognition, kept open for a whole book. read(png) -> [[(text, x, y, w, h)...]]
    in the picture's pixels, one list per line. Stops (kills the helper) when cancel() says so."""

    def __init__(self, language="en", cancel=None):
        if os.name != "nt":
            raise ConvertError("Reading pages that are pictures needs Windows 10 or 11.")
        self.cancel = cancel or (lambda: False)
        script = _PS.replace("__LANG__", re.sub(r"[^A-Za-z-]", "", language or ""))
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        WORK.mkdir(parents=True, exist_ok=True)
        self.log = open(WORK / "text_reader_log.txt", "w", encoding="utf8", errors="replace")
        try:
            self.p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                      text=True, encoding="utf8", errors="replace", **_NOWIN)
        except OSError:
            self.log.close()
            raise ConvertError("Windows' text reader couldn't be started on this PC.")
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        first = self._answer(timeout=90)
        if not first or "ready" not in first:
            why = (first or {}).get("error", "")
            self.close()
            if why == "no-language":
                raise ConvertError("Windows' text reader has no language set up on this PC. In Windows "
                                   "Settings, open Time & language > Language & region, add English, "
                                   "then try again.")
            raise ConvertError("Windows' text reader didn't start on this PC, so pages that are "
                               "pictures can't be read.")
        self.language = first["ready"]
        self.max_px = int(first.get("max") or 10000)

    def _pump(self):
        try:
            for line in self.p.stdout:
                self.q.put(line)
        except Exception:
            pass
        self.q.put(None)

    def _answer(self, timeout=300):
        end = time.time() + timeout
        while True:
            if self.cancel():
                self.close()
                raise Stopped()
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if time.time() > end:
                    return None
                continue
            if line is None:
                return None
            line = line.strip().lstrip("﻿")
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue

    def ask(self, cmd):
        try:
            self.p.stdin.write(cmd + "\n")
            self.p.stdin.flush()
        except (OSError, ValueError):
            raise ConvertError("Windows' text reader stopped. Try again.")

    def read(self, png):
        self.ask(f"ocr|{png}")
        return self.answer_lines()

    def answer_lines(self):
        a = self._answer()
        if a is None:
            raise ConvertError("Windows' text reader stopped. Try again.")
        if "fail" in a:
            return []
        lines = a.get("lines") or []
        # PowerShell turns a list of one into the thing itself: put them back
        if lines and isinstance(lines[0], list) and lines[0] and not isinstance(lines[0][0], list):
            lines = [lines]
        out = []
        for ln in lines:
            if ln and not isinstance(ln[0], list):
                ln = [ln]
            out.append([tuple(w) for w in ln if len(w) == 5 and str(w[0]).strip()])
        return [ln for ln in out if ln]

    def jpeg(self, src, dst):
        self.ask(f"jpeg|{src}|{dst}")
        a = self._answer(timeout=60)
        return bool(a and a.get("done"))

    def close(self):
        p = getattr(self, "p", None)
        if p and p.poll() is None:
            try:
                p.stdin.close()
            except Exception:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()
        try:
            self.log.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# a page as rows of words
# ---------------------------------------------------------------------------
def write_png(path, a):
    """A greyscale or RGB numpy picture as a PNG (no Pillow here)."""
    import numpy as np
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    ch = 1 if a.ndim == 2 else a.shape[2]
    rows = np.empty((h, 1 + w * ch), dtype=np.uint8)
    rows[:, 0] = 0
    rows[:, 1:] = a.reshape(h, w * ch)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    head = struct.pack(">IIBBBBB", w, h, 8, {1: 0, 3: 2}[ch], 0, 0, 0)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) +
                           chunk(b"IDAT", zlib.compress(rows.tobytes(), 1)) + chunk(b"IEND", b""))


def _render(page, path, long_side=2400, grey=True):
    """Draw a page as a PNG; returns the scale (pixels per point)."""
    w, h = page.get_size()
    scale = max(1.5, min(4.5, long_side / max(w, h, 1)))
    bm = page.render(scale=scale, grayscale=grey, rev_byteorder=True)     # RGB, not BGR
    a = bm.to_numpy()
    if a.ndim == 3:
        a = a[:, :, 0] if grey else a[:, :, :3]
    write_png(path, a)
    return scale


def _has_picture(page, pdfium):
    try:
        return any(True for _ in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=2))
    except Exception:
        return True


def _text_words(page):
    """The page's own text: [(text, x0, y0, x1, y1)] in points, top-down, in the PDF's order."""
    W, H = page.get_size()
    tp = page.get_textpage()
    out = []
    try:
        for k in range(tp.count_rects()):
            l, b, r, t = tp.get_rect(k)
            # pdfium writes a hyphen at a line end as \x02
            s = " ".join(tp.get_text_bounded(l, b, r, t).replace("\x02", "-").replace("￾", "-").split())
            if s:
                out.append((s, l, H - t, r, H - b))
    finally:
        tp.close()
    return out


def _gutter(words, W):
    """Where a page of two book pages side by side splits (a picture of an open book), or None."""
    if len(words) < 40:
        return None
    bins = 200
    cover = [0] * bins
    for _, x0, _, x1, _ in words:
        for b in range(max(0, int(x0 / W * bins)), min(bins, int(x1 / W * bins) + 1)):
            cover[b] += 1
    lo, hi = int(0.3 * bins), int(0.7 * bins)
    best, run, start = None, 0, 0
    for b in range(lo, hi):
        if cover[b] <= 0.01 * len(words):
            if run == 0:
                start = b
            run += 1
            if run >= 3 and (best is None or run > best[1]):
                best = (start, run)
        else:
            run = 0
    if not best:
        return None
    mid = (best[0] + best[1] / 2) / bins * W
    left = sum(1 for w in words if (w[1] + w[3]) / 2 < mid)
    if min(left, len(words) - left) < 0.2 * len(words):
        return None
    return mid


def _rows(lines):
    """Lines of words [(text, x0, y0, x1, y1)] -> rows {"t", "x0", "y0", "x1", "y1", "h"}: lines on
    the same level ("4" and "Vermilion" in a running head) are one row, left to right."""
    rows = []
    for ws in lines:
        ws = sorted(ws, key=lambda w: w[1])
        rows.append({"ws": ws, "x0": ws[0][1], "x1": max(w[3] for w in ws),
                     "y0": min(w[2] for w in ws), "y1": max(w[4] for w in ws)})
    rows.sort(key=lambda r: (r["y0"] + r["y1"]) / 2)
    merged = []
    def level(m, r):
        hm, hr = m["y1"] - m["y0"], r["y1"] - r["y0"]
        if min(m["y1"], r["y1"]) - max(m["y0"], r["y0"]) > 0.5 * min(hm, hr):
            return True
        # a dash the hidden text keeps as a speck of its own, a little off the line
        small, big = (r, m) if hr < hm else (m, r)
        hb = big["y1"] - big["y0"]
        c = (small["y0"] + small["y1"]) / 2
        return small["y1"] - small["y0"] < 0.5 * hb and big["y0"] - 0.3 * hb <= c <= big["y1"]

    def apart(m, r):
        return all(w[3] <= v[1] + 1 or w[1] >= v[3] - 1 for w in m["ws"] for v in r["ws"])

    for r in rows:
        m = next((m for m in merged[-2:][::-1] if level(m, r) and apart(m, r)), None)
        if m:
            m["ws"] = sorted(m["ws"] + r["ws"], key=lambda w: w[1])
            m["x0"], m["x1"] = min(m["x0"], r["x0"]), max(m["x1"], r["x1"])
            m["y0"], m["y1"] = min(m["y0"], r["y0"]), max(m["y1"], r["y1"])
            continue
        merged.append(r)
    out = []
    for r in merged:
        parts, prev = [], None
        for w in r["ws"]:
            if prev is not None:
                gap = w[1] - prev[3]
                hgt = max(1.0, prev[4] - prev[2])
                if gap > 0.12 * hgt or prev[0].endswith(" "):
                    parts.append(" ")
            parts.append(w[0].strip())
            prev = w
        hs = sorted(w[4] - w[2] for w in r["ws"])
        out.append({"t": "".join(parts).strip(), "x0": round(r["x0"], 1), "x1": round(r["x1"], 1),
                    "y0": round(r["y0"], 1), "y1": round(r["y1"], 1),
                    # the tallest words (a capital, a "y" below the line): the size of the print
                    "h": round(hs[-1] if len(hs) < 4 else hs[-2], 1)})
    return [r for r in out if r["t"]]


def _lines_from_text(words):
    """The PDF's words, in its own order, as lines: a new line where the next word goes back left
    or to another level."""
    lines = []
    for w in words:
        if lines:
            p = lines[-1][-1]
            over = min(p[4], w[4]) - max(p[2], w[2])
            if w[1] >= p[1] - 1 and over > 0.4 * min(p[4] - p[2], w[4] - w[2]):
                lines[-1].append(w)
                continue
        lines.append([w])
    return lines


def _page_rows(words_or_lines, W, from_lines=False):
    """Rows of a page, split into two book pages when it's a picture of an open book."""
    flat = [w for ln in words_or_lines for w in ln] if from_lines else list(words_or_lines)
    mid = _gutter(flat, W)
    groups = []
    if mid is None:
        groups.append(words_or_lines)
    else:
        for side in (0, 1):
            keep = lambda w: ((w[1] + w[3]) / 2 < mid) == (side == 0)   # noqa: E731
            if from_lines:
                g = [[w for w in ln if keep(w)] for ln in words_or_lines]
                groups.append([ln for ln in g if ln])
            else:
                groups.append([w for w in words_or_lines if keep(w)])
    rows = []
    for g in groups:
        rows.extend(_rows(g if from_lines else _lines_from_text(g)))
    return rows


# ---------------------------------------------------------------------------
# reading every page (kept, so a second go carries on)
# ---------------------------------------------------------------------------
def _key(path):
    p = Path(path)
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{FORMAT}".encode("utf8")).hexdigest()[:16]


def _fmt_left(sec):
    if sec < 50:
        return "less than a minute left"
    m = round(sec / 60)
    if m < 60:
        return f"about {m} minute{'s' if m != 1 else ''} left"
    h, m = divmod(m, 60)
    return f"about {h} hour{'s' if h != 1 else ''} {m} min left"


def read_pages(path, progress=None, cancel=None, language="en", workdir=None):
    """[{"i", "w", "h", "src": "text"/"ocr"/"none", "pic": bool, "rows": [...]}] for every page."""
    say = progress or (lambda f, m: None)
    stop = cancel or (lambda: False)
    pdfium = reader(say)
    doc = _open(pdfium, path)
    work = Path(workdir) if workdir else WORK / _key(path)
    work.mkdir(parents=True, exist_ok=True)
    store = work / "pages.jsonl"
    done = {}
    if store.exists():
        for line in store.read_text("utf8", "ignore").splitlines():
            try:
                d = json.loads(line)
                done[d["i"]] = d
            except (ValueError, KeyError):
                pass
    n = len(doc)
    if not n:
        raise ConvertError("This PDF has no pages.")
    ocr = None
    t0, timed = time.time(), 0
    try:
        with open(store, "a", encoding="utf8") as out:
            for i in range(n):
                if stop():
                    raise Stopped()
                if i in done:
                    continue
                page = doc[i]
                try:
                    W, H = page.get_size()
                    words = _text_words(page)
                    letters = sum(len(re.findall(r"[^\W\d_]", w[0])) for w in words)
                    pic = _has_picture(page, pdfium)
                    if letters >= 30 or (words and not pic):
                        d = {"src": "text", "rows": _page_rows(words, W)}
                    elif pic:
                        if ocr is None:
                            say(i / n * 0.92, "Starting Windows' text reader…")
                            ocr = WinOcr(language, stop)
                        # its own picture file: Windows keeps the last one open a little while
                        png = work / f"page{i}.png"
                        scale = _render(page, png, long_side=2400)
                        lines = ocr.read(str(png))
                        _tidy(work, keep=png)
                        lines = [[(t, x / scale, y / scale, (x + w) / scale, (y + h) / scale)
                                  for t, x, y, w, h in ln] for ln in lines]
                        d = {"src": "ocr", "rows": _page_rows(lines, W, from_lines=True)}
                    else:
                        d = {"src": "none", "rows": []}
                    d.update(i=i, w=round(W, 1), h=round(H, 1), pic=bool(pic))
                finally:
                    page.close()
                done[i] = d
                out.write(json.dumps(d, ensure_ascii=False) + "\n")
                out.flush()
                timed += 1
                left = n - i - 1
                rate = (time.time() - t0) / timed
                what = "Reading the words on page" if d["src"] == "ocr" else "Reading page"
                msg = f"{what} {i + 1} of {n}"
                if timed >= 4 and left:
                    msg += " · " + _fmt_left(rate * left)
                say((i + 1) / n * 0.92, msg)
    finally:
        if ocr is not None:
            ocr.close()
        _tidy(work)
    return doc, [done[i] for i in range(n)]


def _tidy(work, keep=None):
    """Remove the page pictures already read (one still open in Windows waits for next time)."""
    for f in Path(work).glob("page*.png"):
        if f != keep:
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# rows -> paragraphs and chapters
# ---------------------------------------------------------------------------
PAGE_NO = re.compile(r"^[\[(]?\s*(\d{1,4}|[ivxlc]{1,7})\s*[\])]?$", re.I)
CHAPTER = re.compile(r"^(chapter|part|book)\s+([\dIVXLC]+|one|two|three|four|five|six|seven|eight|nine|ten|"
                     r"eleven|twelve|[a-z]+teen|twenty[\w-]*|thirty[\w-]*|forty[\w-]*|fifty[\w-]*)\b[.:]?\s*(.{0,60})$"
                     r"|^(prologue|epilogue|introduction|foreword|preface|afterword)\b[.:]?\s*(.{0,40})$", re.I)
NUMBER_WORD = re.compile(r"^(\d{1,3}|[IVXLC]{1,7}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
                         r"twelve|[a-z]+teen|twenty[\w-]*|thirty[\w-]*|forty[\w-]*|fifty[\w-]*)\.?$", re.I)
END = re.compile(r"[.!?…:\"'”’)\]]$")
BREAK = re.compile(r"^[\s*#~•·.—–-]{1,15}$")
JACKET = re.compile(r"continued\s*(on|from)\s*(the\s*)?(front|back)\s*flap", re.I)
ARCHIVE = re.compile(r"internet\s*archive|archive\.org|digitized\s+by|funding\s+from", re.I)
CONTENTS = re.compile(r"^\s*(table\s+of\s+)?contents\s*$", re.I)


def _letters(s):
    return re.sub(r"[^a-z]", "", s.lower())


def _num(tok):
    tok = tok.strip("[]().,")
    if tok.isdigit():
        return int(tok)
    return None


def _median(xs, default=0.0):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else default


def _junk(t):
    """Specks and smudges read as letters ("H)LL/SAJVH/TNEY", ". ' ,")."""
    toks = t.split()
    if not toks:
        return True
    if BREAK.match(t):
        return False
    good = sum(1 for k in toks if re.fullmatch(r"[\"'“‘(\[]*[A-Za-zÀ-ɏ][a-zà-ɏ'’-]*"
                                              r"[.,;:!?\"'”’)\]—…-]*|[\"'(“]*\d[\d,.:]*[.,;:!?)\"'”]*"
                                              r"|[A-ZÀ-Þ'’-]+[.,;:!?]*|&|[—–-]+", k))
    if len(re.findall(r"[^\W\d_]", t)) < 2 and not NUMBER_WORD.match(t):
        return True
    if re.search(r"(\w)\1{4,}", t):              # "llllllllllllillll"
        return True
    return good < 0.5 * len(toks) or (len(toks) <= 3 and good < len(toks) and len(t) < 12)


def _page_numbers(pages):
    """The usual (printed page number - page index), from numbers at the top or bottom of pages."""
    seen = {}
    for p in pages:
        rows = p["rows"]
        for r in rows[:2] + rows[-2:]:
            toks = r["t"].split()
            for tok in (toks[0], toks[-1]) if toks else ():
                v = _num(tok)
                if v is not None and 0 < v < 3000:
                    seen[v - p["i"]] = seen.get(v - p["i"], 0) + 1
    if not seen:
        return None
    off, count = max(seen.items(), key=lambda kv: kv[1])
    return off if count >= 3 else None


def _strip_heads(pages):
    """Drop page numbers and running heads/feet. Marks each page's "head" (it had a running head)."""
    off = _page_numbers(pages)
    keys = {}
    for p in pages:
        rows = p["rows"]
        for r in rows[:1] + rows[-1:]:
            k = _letters(r["t"])
            if 2 <= len(k) <= 70 and len(r["t"].split()) <= 10:
                keys[k] = keys.get(k, 0) + 1
    repeated = {k for k, c in keys.items() if c >= 3}
    heads = {}              # the running heads, without their page numbers: the title, the author...
    # where the top and bottom lines of a full page sit: page numbers and heads are there, not lower
    # down (Chapter 1's "1" on the book's page 1 was taken for its page number)
    full = [p for p in pages if len(p["rows"]) >= 10]
    top_at = _median([p["rows"][0]["y0"] / p["h"] for p in full], 0.08)
    foot_at = _median([p["rows"][-1]["y0"] / p["h"] for p in full], 0.9)

    def page_no(tok, i):
        v = _num(tok)
        if v is None:
            return False
        return off is not None and abs(v - (i + off)) <= 1

    for p in pages:
        rows, i = p["rows"], p["i"]
        p["head"] = False
        if len(rows) < 2:
            y = rows[0]["y0"] / p["h"] if rows else 0.5
            if rows and PAGE_NO.match(rows[0]["t"]) and (page_no(rows[0]["t"], i) or off is None)                     and (y <= top_at + 0.06 or y >= foot_at - 0.04):
                p["rows"] = []
            continue
        pitch = _median([b["y0"] - a["y0"] for a, b in zip(rows, rows[1:])], 12)
        for end in ("top", "bottom"):
            for _ in range(2):
                if not rows:
                    break
                r = rows[0] if end == "top" else rows[-1]
                edge = (r["y0"] / p["h"] <= top_at + 0.06) if end == "top" else (r["y0"] / p["h"] >= foot_at - 0.04)
                if not edge:
                    break
                nxt = rows[1] if end == "top" and len(rows) > 1 else (rows[-2] if len(rows) > 1 else None)
                t = r["t"]
                toks = t.split()
                apart = nxt is None or abs((nxt["y0"] if end == "top" else r["y0"]) -
                                           (r["y0"] if end == "top" else nxt["y0"])) > 1.15 * pitch
                lone = PAGE_NO.match(t) is not None
                numbered = len(toks) <= 10 and (page_no(toks[0], i) or page_no(toks[-1], i))
                rep = _letters(t) in repeated and len(toks) <= 10
                drop = False
                if lone and (page_no(t, i) or (off is None and apart) or end == "bottom"):
                    drop = True
                elif (numbered or rep) and apart:
                    drop = True
                    p["head"] = p["head"] or end == "top"
                    words = [w for w in toks if not page_no(w, i)]
                    if words:
                        said = " ".join(words)
                        heads[said] = heads.get(said, 0) + 1
                if not drop:
                    break
                rows.remove(r)
        p["rows"] = rows
    return heads


def _measure(pages):
    """Each page's text edges (L, R), and the book's character width, line pitch and row height."""
    cws, hs, pitches = [], [], []
    for p in pages:
        rows = p["rows"]
        widths = sorted(r["x1"] - r["x0"] for r in rows)
        full = widths[int(len(widths) * 0.8)] if widths else 0
        long_rows = [r for r in rows if r["x1"] - r["x0"] >= 0.88 * full and len(r["t"]) >= 25]
        if len(long_rows) >= 3:
            p["L"] = _median([r["x0"] for r in long_rows])
            p["R"] = _median([r["x1"] for r in long_rows])
            cws.extend((r["x1"] - r["x0"]) / len(r["t"]) for r in long_rows)
            hs.extend(r["h"] for r in long_rows)
            pitches.extend(b["y0"] - a["y0"] for a, b in zip(rows, rows[1:])
                           if b in long_rows and a in long_rows)
    book = {"cw": _median(cws, 5.0), "h": _median(hs, 10.0), "pitch": _median(pitches, 14.0)}
    # pages with too few full lines (chapter openings, short pages) borrow from a page like them
    known = [p for p in pages if "L" in p]
    for p in pages:
        if "L" not in p:
            same = [q for q in known if q["i"] % 2 == p["i"] % 2] or known
            near = min(same, key=lambda q: abs(q["i"] - p["i"])) if same else None
            if near:
                p["L"], p["R"] = near["L"] * p["w"] / near["w"], near["R"] * p["w"] / near["w"]
            else:
                p["L"] = min((r["x0"] for r in p["rows"]), default=0)
                p["R"] = max((r["x1"] for r in p["rows"]), default=p["w"])
    # a ragged right edge (not lined up): a short line doesn't end a paragraph there. For the
    # book, and for a page set differently (a paperback's teaser page)
    rag = total = 0
    for p in pages:
        n = k = 0
        for r in p["rows"]:
            if len(r["t"]) >= 25:
                n += 1
                k += (p["R"] - r["x1"]) > 2.5 * book["cw"]
        p["ragged"] = n >= 5 and k > 0.35 * n
        steps = [b["y0"] - a["y0"] for a, b in zip(p["rows"], p["rows"][1:]) if b["y0"] > a["y0"]]
        # this page's line spacing, when it's set more widely than the book (a teaser page)
        p["pitch"] = max(book["pitch"], _median(steps)) if len(steps) >= 6 else book["pitch"]
        rag, total = rag + k, total + n
    book["ragged"] = total > 0 and rag > 0.35 * total
    return book


def _vocab(pages):
    """How often each word is in the book, leaving out the last word of a line when the next line
    starts in small letters (it may be half a word: "un" "doubtedly") and that next line's first word."""
    words = {}
    flat = [r["t"].split() for p in pages for r in p["rows"]]

    def low(toks):
        return bool(toks) and toks[0][:1].islower()
    for n, toks in enumerate(flat):
        use = list(toks)
        if n and flat[n - 1] and low(toks):
            use = use[1:]
        if n + 1 < len(flat) and low(flat[n + 1]) and use and use[-1] == toks[-1]:
            use = use[:-1]
        for k in use:
            k = k.strip(".,;:!?\"'()[]“”‘’—").lower()
            if k:
                words[k] = words.get(k, 0) + 1
    return words


PREFIXES = ("re", "un", "de", "pre", "con", "com", "dis", "in", "ex", "pro")
# words that start a hyphenated word: "self-" "forgetfulness" keeps its hyphen
FIRST_HALVES = {"self", "half", "well", "ill", "great", "grand", "step", "non", "semi", "all", "so", "good",
                "old", "far", "full", "new", "long", "twenty", "thirty", "forty", "fifty", "sixty",
                "seventy", "eighty", "ninety", "brother", "sister", "mother", "father", "son",
                "daughter", "ever", "never", "first", "second", "third", "middle", "low", "high"}


def _joiner(vocab):
    """join(line so far, next line, full) -> one text, mending a word split at the line end."""
    try:
        sys.path.insert(0, str(HERE))
        import readaloud
        extra = readaloud.known_words()       # ReadAloud's word lists, when its voice is set up
    except Exception:
        extra = set()

    def count(w):
        return vocab.get(w, 0) + (2 if w in extra else 0)

    def join(a, b, full=False):
        if not a:
            return b
        if a.endswith(("—", "–")) or b.startswith(("—", "–")):
            return a + b
        n = re.match(r"([a-zà-ɏ]+)", b)
        m = re.search(r"([A-Za-zÀ-ɏ]+)[-­]$", a)
        if m and n:
            x, y = m.group(1).lower(), n.group(1)
            if count(x + y):
                return a[:-1] + b
            if f"{x}-{y}" in vocab or x in FIRST_HALVES or (count(x) and count(y) and len(x) >= 3
                                                            and len(y) >= 3 and x not in PREFIXES):
                return a + b                 # a real hyphen: "twenty-five", "high-heeled"
            return a[:-1] + b
        # a full line ending in part of a word whose hyphen was lost (the Internet Archive's
        # hidden text: "gambling town un" "doubtedly")
        m = re.search(r"(?<![\w'’-])([a-z]+)$", a)
        if full and m and n:
            x, y = m.group(1), n.group(1)
            # both halves never seen as words in the book ("shat" "tering"), or a start that isn't
            # one ("un" "doubtedly", "re" "turned")
            if count(x + y) or (not count(x) and not count(y)) or (x in PREFIXES and not count(x)):
                return a + b
        return a + " " + b
    return join


def _title_case(s):
    small = {"a", "an", "the", "and", "but", "or", "of", "to", "in", "on", "at", "by", "for", "with"}
    out = []
    for k, w in enumerate(s.split()):
        core = w.strip("\"'“”.,:;!?()")
        if re.fullmatch(r"[IVXLC]+", core) and len(core) <= 6 and k > 0:
            out.append(w)
        elif k and core.lower() in small:
            out.append(w.lower())
        else:
            lead = len(w) - len(w.lstrip("\"'“‘("))
            out.append(w[:lead] + w[lead:lead + 1].upper() + w[lead + 1:].lower())
    return " ".join(out)


def _heading_text(t):
    t = " ".join(t.split())
    letters = re.sub(r"[^A-Za-z]", "", t)
    return _title_case(t) if letters and letters.isupper() and len(letters) > 3 else t


def _centred(r, L, R, cw):
    i, o = r["x0"] - L, R - r["x1"]
    return i > 1.5 * cw and o > 1.5 * cw and abs(i - o) < max(2.5 * cw, 0.12 * (R - L))


def _tidy_text(t):
    t = " ".join(t.split())
    t = re.sub(r"\s*(—+)\s*", r"\1", t)            # "him— the veil", "all —pretty"
    return t


def build(pages, cover_page=None, info=None):
    """Pages of rows -> sections [{"title", "paras": [[kind, text]], "front"}]; kind "p" a paragraph,
    "c" a centred line, "h" a heading inside a section, "b" a scene break. "front" is what comes
    before the first chapter (title page, copyright...)."""
    pages = [dict(p, rows=[dict(r) for r in p["rows"]]) for p in pages]
    for p in pages:
        if cover_page is not None and p["i"] == cover_page:
            p["rows"] = []
        p["rows"] = [r for r in p["rows"] if not _junk(r["t"]) and r["y1"] > 0 and r["y0"] < p["h"]]
        if any(ARCHIVE.search(r["t"]) for r in p["rows"]) and len(p["rows"]) < 20:
            p["rows"] = []
    # the book jacket's flaps: their words go in the ebook's description, not in the book
    jacket = []
    for p in pages:
        if any(JACKET.search(r["t"]) for r in p["rows"]):
            jacket += [r["t"] for r in p["rows"] if not JACKET.search(r["t"]) and len(r["t"]) > 25]
            p["rows"] = []
    heads = _strip_heads(pages)
    # the contents pages: the EPUB has its own
    in_toc = False
    for p in pages:
        rows = p["rows"]
        if rows and any(CONTENTS.match(r["t"]) for r in rows[:2]):
            p["rows"], in_toc = [], True
            continue
        if in_toc:
            numbered = sum(1 for r in rows if re.search(r"(\d+|[ivxlc]+)$", r["t"], re.I))
            if rows and numbered >= 0.5 * len(rows):
                p["rows"] = []
                continue
            in_toc = False
    book = _measure(pages)
    cw, pitch, body_h = book["cw"], book["pitch"], book["h"]
    for p in pages:          # specks: a stray quote mark above the page, a hyphen on its own
        p["rows"] = [r for r in p["rows"] if not (r["h"] < 0.45 * body_h and len(r["t"].strip()) <= 3)]
    if info is not None:
        info.update(heads=heads, body_h=body_h)
    join = _joiner(_vocab(pages))
    if info is not None:
        blurb = ""
        for t in jacket:
            blurb = join(blurb, t) if blurb else t
        info["description"] = _tidy_text(blurb)
    # chapter openings: in a book with running heads, a page without one whose text starts lower
    # down, and the story carries on with heads on the next page (the hidden text of scanned books
    # often lacks the chapter's number)
    with_rows = [p for p in pages if p["rows"]]
    has_heads = sum(1 for p in with_rows if p["head"]) >= 0.3 * max(1, len(with_rows))
    full_pages = [p for p in with_rows if len(p["rows"]) >= 10 and p["head"]] or \
        [p for p in with_rows if len(p["rows"]) >= 10]
    top_at = _median([p["rows"][0]["y0"] / p["h"] for p in full_pages], 0.1)
    next_head = {}
    following = None
    for p in reversed(pages):
        next_head[p["i"]] = following
        if p["rows"]:
            following = p["head"]

    sections = [{"title": "", "paras": [], "front": True}]
    cur = {"text": "", "kind": None}

    def flush():
        if cur["text"].strip():
            sections[-1]["paras"].append([cur["kind"] or "p", _tidy_text(cur["text"])])
        cur["text"], cur["kind"] = "", None

    def add_block(kind, text):
        flush()
        if kind == "b" and (not sections[-1]["paras"] or sections[-1]["paras"][-1][0] == "b"):
            return
        sections[-1]["paras"].append([kind, _tidy_text(text)])

    def new_section(title):
        flush()
        if sections[-1]["paras"] or sections[-1].get("front") is False:
            sections.append({"title": title, "paras": [], "front": False})
        else:
            sections[-1].update(title=title, front=False)

    prev = None          # the last paragraph row (any page)
    for p in pages:
        rows, L, R = p["rows"], p["L"], p["R"]
        width = max(1.0, R - L)
        ragged = book["ragged"] or p.get("ragged", False)
        opening = (has_heads and not p["head"] and bool(next_head[p["i"]]) and len(rows) >= 3
                   and rows[0]["y0"] / p["h"] > top_at + 0.12)
        k = 0
        while k < len(rows):
            r = rows[k]
            t = r["t"]
            indent, short = r["x0"] - L, R - r["x1"]
            big = r["h"] > 1.5 * body_h
            centred = _centred(r, L, R, cw)
            top = r["y0"] < p["h"] * 0.45
            prose_after = sum(1 for q in rows[k + 1:k + 8] if q["x1"] - q["x0"] > 0.8 * width) >= 2
            may_open = not has_heads or (not p["head"] and next_head[p["i"]])
            # ----- a chapter heading
            m = CHAPTER.match(t)
            lone = (NUMBER_WORD.match(t) and (centred or big) and len(t) <= 12 and r["h"] >= 0.8 * body_h
                    and (t[:1].isdigit() or not t.islower() or big))
            gaps = p.get("pitch", pitch)
            alone = (k == 0 or prev is None or (r["y0"] - rows[k - 1]["y1"]) > 0.8 * gaps
                     or (k + 1 < len(rows) and rows[k + 1]["y0"] - r["y1"] > 0.8 * gaps))
            if (m and (centred or big or alone) and len(t) <= 70) or (lone and top and may_open) or \
                    (big and centred and top and prose_after and may_open and len(t.split()) <= 10):
                title = _heading_text(t)
                if lone and not m:
                    title = "Chapter " + t.rstrip(".")
                k += 1
                extra = 0
                while k < len(rows) and extra < 2:       # the chapter's name on the next line(s)
                    q = rows[k]
                    if (_centred(q, L, R, cw) or q["h"] > 1.5 * body_h) and len(q["t"]) <= 60 \
                            and not END.search(q["t"].rstrip(".")):
                        title += (": " if extra == 0 and not CHAPTER.match(q["t"]) else " ") + _heading_text(q["t"])
                        k += 1
                        extra += 1
                    else:
                        break
                new_section(title)
                opening = False
                prev = None
                continue
            # ----- a scene break: a row of stars, or a wide gap in the middle of a page
            if BREAK.match(t) and len(t.replace(" ", "")) <= 9:
                add_block("b", "* * *")
                prev = None
                k += 1
                continue
            if opening:                  # a chapter opening with no heading the PDF could give
                new_section("")
                opening = False
                prev = None
            same_page = prev is not None and prev["page"] is p
            gap = (r["y0"] - prev["y0"]) / p.get("pitch", pitch) if same_page else 1.0
            if same_page and gap > 2.6 and cur["text"]:
                flush()
                add_block("b", "* * *")
            # ----- a centred line (a title page, a letter's signature, a short heading)
            after_c = bool(sections[-1]["paras"]) and sections[-1]["paras"][-1][0] == "c" and not cur["text"]
            if centred and len(t) < 0.75 * width / cw and (big or not END.search(t) or len(t.split()) <= 4
                                                          or after_c):
                flush()
                sections[-1]["paras"].append(["h" if big else "c", _tidy_text(t)])
                prev = None
                k += 1
                continue
            # ----- a paragraph line
            starts = (prev is None or (indent > 1.2 * cw and indent < 0.4 * width)
                      or (same_page and gap > 1.6)
                      or (prev["short"] > (0.35 * width if ragged else 2.5 * cw)
                          and (not ragged or END.search(prev["t"]))))
            if starts:
                flush()
                cur["text"] = t
            else:
                cur["text"] = join(cur["text"], t, full=prev["short"] < 1.5 * cw)
            prev = {"page": p, "y0": r["y0"], "short": short, "t": t}
            k += 1
    flush()
    out = []
    for s in sections:
        paras = s["paras"]
        while paras and paras[-1][0] == "b":
            paras.pop()
        while paras and paras[0][0] == "b":
            paras.pop(0)
        if paras:
            out.append({"title": s["title"], "paras": paras, "front": s.get("front", False)})
    # chapters numbered in order: the numbers in old scans are often missing or misread ("xiil")
    n = 0
    for s in out:
        if s["front"]:
            continue
        t = s["title"]
        m = CHAPTER.match(t) if t else None
        if not t or NUMBER_WORD.match(t) or (m and m.group(1) and m.group(1).lower() == "chapter"):
            n += 1
            name = (m.group(3) or "").strip(" .:-") if m and m.group(1) else ""
            s["title"] = f"Chapter {n}" + (f": {name}" if name else "")
    return out


# ---------------------------------------------------------------------------
# title, author, cover
# ---------------------------------------------------------------------------
def _clean_title(raw, path):
    t = " ".join(str(raw or "").split())
    t = re.sub(r"^(Microsoft (Word|PowerPoint)|Word|Writer|Untitled)\s*-\s*", "", t, flags=re.I)
    t = re.sub(r"\.(docx?|odt|rtf|pdf|txt)$", "", t, flags=re.I)
    if not t or t.lower() in ("untitled", "document", "microsoft word") or re.fullmatch(r"[\w-]*\d{4,}[\w-]*", t):
        t = Path(path).stem
        t = re.sub(r"[_.]+", " ", t)
        t = re.sub(r"\b\d{2,}\b$", "", t).strip(" -")
    t = " ".join(t.split())
    if t and t[0].isupper() and t[1:] == t[1:].lower() and len(t.split()) > 1 or t.islower() or t.isupper():
        t = _title_case(t)
    return t or Path(path).stem


def _clean_author(a):
    """"Whitney, Phyllis A., 1903-2008" -> "Phyllis A. Whitney"."""
    a = re.sub(r",?\s*\d{4}\s*-\s*(\d{4})?\.?\s*$", "", " ".join(str(a or "").split())).strip(" ,")
    a = re.sub(r"\s*\(.*?\)\s*$", "", a)
    m = re.fullmatch(r"([^,]+),\s*([^,]+)", a)
    return f"{m.group(2)} {m.group(1)}" if m else a


def _meta(doc):
    try:
        m = doc.get_metadata_dict(skip_empty=True)
    except Exception:
        m = {}
    return m.get("Title", ""), m.get("Author", "")


NAME = re.compile(r"^[A-Z][a-z'’.-]*\.?(\s+[A-Z][a-z'’.-]*\.?){1,3}$")


def _name_case(t):
    return " ".join(w[:1].upper() + w[1:] if w[:1].islower() else w for w in _heading_text(t).split())


def _from_pages(pages, info, path):
    """(title, author) from the book itself when the PDF's details have none: the big print on
    the first pages (the title page), checked against the running heads ("4 Vermilion",
    "Phyllis A. Whitney 5"), and a "by ..." line."""
    heads = sorted(((c, t) for t, c in (info.get("heads") or {}).items() if c >= 4), reverse=True)
    body_h = info.get("body_h") or 10
    big, middling = [], []
    for p in pages[:14]:
        for r in p["rows"]:
            if 1.3 * body_h <= r["h"] < 2 * body_h and NAME.match(_name_case(r["t"].strip())):
                middling.append((p["i"], r["t"].strip()))
            t = r["t"].strip()
            if r["h"] >= 2 * body_h and len(_letters(t)) >= 3 and not _junk(t) and not NUMBER_WORD.match(t) \
                    and not CHAPTER.match(t):
                big.append((r["h"], t))
    title = author = ""
    head_keys = {_letters(t): t for _, t in heads}
    for _, t in sorted(big, reverse=True):
        if _letters(t) in head_keys:
            title = _heading_text(t)
            break
    if not title:
        stem = _letters(Path(path).stem)
        for _, t in heads:
            if _letters(t) and _letters(t) in stem and not NAME.match(t):
                title = _heading_text(t)
                break
    for p in pages[:10]:
        for r in p["rows"][:14]:
            m = re.match(r"^by\s+([A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*){1,3})$", r["t"].strip(), re.I)
            if m:
                author = _name_case(m.group(1))
                break
        if author:
            break
    if not author:
        for _, t in heads:
            if NAME.match(_name_case(t)) and _letters(t) != _letters(title):
                author = _name_case(t)
                break
    if not author and title:     # on the title page, the big print that's a name
        for _, t in sorted(big, reverse=True):
            if _letters(t) != _letters(title) and NAME.match(_name_case(t)):
                author = _name_case(t)
                break
    if not author and title:     # or a name in print a little bigger than the story's
        where = next((p["i"] for p in pages[:14] for r in p["rows"] if _letters(r["t"]) == _letters(title)), None)
        author = next((_name_case(t) for i, t in middling if i == where and _letters(t) != _letters(title)), "")
    return title, author


def _cover(doc, pages, work, ocr_open):
    """The first page as a picture (JPEG through Windows when it can), when it's a picture page."""
    if not pages or not pages[0].get("pic"):
        return None, None
    if sum(1 for r in pages[0]["rows"] if len(r["t"]) >= 25) >= 6:      # a page of text, not a cover
        return None, None
    page = doc[0]
    try:
        png = Path(work) / "cover.png"
        _render(page, png, long_side=1600, grey=False)
    except Exception:
        return None, None
    finally:
        page.close()
    if os.name == "nt":
        try:
            o = ocr_open()
            try:
                jpg = Path(work) / "cover.jpg"
                if o.jpeg(str(png), str(jpg)) and jpg.exists() and jpg.stat().st_size > 1000:
                    return jpg.read_bytes(), "jpg"
            finally:
                o.close()
        except (ConvertError, Stopped):
            pass
        except Exception:
            pass
    return png.read_bytes(), "png"


# ---------------------------------------------------------------------------
# the EPUB
# ---------------------------------------------------------------------------
CSS = """body { margin: 0 4%; line-height: 1.45; }
h1, h2 { text-align: center; margin: 2.5em 0 1.2em; font-weight: normal; }
h1 { font-size: 1.6em; } h2 { font-size: 1.3em; } h3 { text-align: center; font-size: 1.1em; }
p { margin: 0; text-indent: 1.3em; text-align: justify; }
p.first, h2 + p, h3 + p, hr + p { text-indent: 0; }
p.c { text-align: center; text-indent: 0; margin: 0.4em 0; }
hr { border: none; text-align: center; margin: 1em 0; }
hr:after { content: "* * *"; }
.cover { text-align: center; margin: 0; padding: 0; }
.cover img { max-width: 100%; max-height: 100%; }
"""


def _xhtml(title, body, lang):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{lang}" xml:lang="{lang}"><head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
            f'<link rel="stylesheet" type="text/css" href="style.css"/></head>\n<body>\n{body}\n</body></html>')


def write_epub(out, title, author, sections, cover=None, cover_ext="jpg", lang="en", description=""):
    """An EPUB 3 (with an EPUB 2 contents file too, for older e-readers)."""
    lang = lang or "en"
    uid = "urn:uuid:" + hashlib.sha1(f"{title}|{author}|{sum(len(s['paras']) for s in sections)}".encode()).hexdigest()
    uid = uid[:17] + "-" + uid[17:21] + "-" + uid[21:25] + "-" + uid[25:29] + "-" + uid[29:41]
    docs = []                  # (file name, title, xhtml)
    if cover:
        docs.append(("cover.xhtml", "Cover", _xhtml(title, f'<div class="cover"><img src="cover.{cover_ext}" '
                                                           f'alt="{html.escape(title)}"/></div>', lang)))
    for n, s in enumerate(sections, 1):
        name = s["title"] or ("Beginning" if s.get("front") else f"Part {n}")
        if s.get("front") and not s["title"]:
            name = "Title page" if any(k in ("c", "h") for k, _ in s["paras"][:6]) else "Beginning"
        parts = [] if s.get("front") and not s["title"] else [f"<h2>{html.escape(name)}</h2>"]
        first = True
        for kind, text in s["paras"]:
            t = html.escape(text, quote=False)
            if kind == "b":
                parts.append("<hr/>")
                first = True
            elif kind == "h":
                parts.append(f"<h3>{t}</h3>")
                first = True
            elif kind == "c":
                parts.append(f'<p class="c">{t}</p>')
            else:
                parts.append(f'<p class="first">{t}</p>' if first else f"<p>{t}</p>")
                first = False
        docs.append((f"part{n:03d}.xhtml", name, _xhtml(name, "\n".join(parts), lang)))
    reading = [d for d in docs if d[0] != "cover.xhtml"]
    nav = _xhtml("Contents", '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + "".join(
        f'<li><a href="{f}">{html.escape(t)}</a></li>' for f, t, _ in reading) + "</ol></nav>", lang)
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{html.escape(title)}</text></docTitle><navMap>'
           + "".join(f'<navPoint id="n{k}" playOrder="{k}"><navLabel><text>{html.escape(t)}</text></navLabel>'
                     f'<content src="{f}"/></navPoint>' for k, (f, t, _) in enumerate(reading, 1))
           + "</navMap></ncx>")
    media = "image/jpeg" if cover_ext == "jpg" else "image/png"
    items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
             '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
             '<item id="css" href="style.css" media-type="text/css"/>']
    if cover:
        items.append(f'<item id="cover-image" href="cover.{cover_ext}" media-type="{media}" properties="cover-image"/>')
    for f, _, _ in docs:
        items.append(f'<item id="{f.split(".")[0]}" href="{f}" media-type="application/xhtml+xml"/>')
    spine = "".join(f'<itemref idref="{f.split(".")[0]}"/>' for f, _, _ in docs)
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           'unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="uid">{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
           + (f'<dc:creator>{html.escape(author)}</dc:creator>' if author else "")
           + f'<dc:language>{html.escape(lang)}</dc:language>'
           + (f'<dc:description>{html.escape(description)}</dc:description>' if description else "")
           + f'<meta property="dcterms:modified">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>'
           + ('<meta name="cover" content="cover-image"/>' if cover else "")
           + f'<dc:contributor>CleanRead (from a PDF)</dc:contributor></metadata><manifest>{"".join(items)}</manifest>'
           f'<spine toc="ncx">{spine}</spine></package>')
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    out = Path(out)
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        if cover:
            z.writestr(f"OEBPS/cover.{cover_ext}", cover, compress_type=zipfile.ZIP_STORED)
        for f, _, x in docs:
            z.writestr("OEBPS/" + f, x, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, out)
    return out


def out_path(pdf, folder=None):
    """Next to the PDF, with the same name (an older one CleanRead made is replaced)."""
    pdf = Path(pdf)
    return (Path(folder) if folder else pdf.parent) / (pdf.stem + ".epub")


def convert(pdf, out=None, progress=None, cancel=None, language="en"):
    say = progress or (lambda f, m: None)
    started = time.time()
    pdf = Path(pdf)
    if not pdf.exists():
        raise ConvertError("The PDF wasn't found. Was it moved or renamed?")
    work = WORK / _key(pdf)
    try:
        doc, pages = read_pages(pdf, say, cancel, language, work)
    except (ConvertError, Stopped):
        raise
    except MemoryError:
        raise ConvertError("The computer ran out of memory. Close other programs and try again.")
    except OSError as ex:
        if getattr(ex, "errno", None) == 28:
            raise ConvertError("The computer is out of disk space. Free some up and try again.")
        raise
    try:
        say(0.93, "Putting the pages together into chapters…")
        cover, cover_ext = _cover(doc, pages, work, lambda: WinOcr(language, cancel))
        info = {}
        sections = build(pages, cover_page=0 if cover else None, info=info)
        if not sections:
            raise ConvertError("No words were found in this PDF, even after reading the pictures of "
                               "its pages.")
        raw_title, raw_author = _meta(doc)
        page_title, page_author = _from_pages(pages, info, pdf)
        title = _clean_title(raw_title, pdf) if raw_title.strip() or not page_title else page_title
        author = _clean_author(raw_author) or page_author
    finally:
        try:
            doc.close()
        except Exception:
            pass
    say(0.97, "Saving the ebook…")
    target = Path(out) if out else out_path(pdf)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_epub(target, title, author, sections, cover, cover_ext or "jpg", language,
                   info.get("description", ""))
    except OSError:
        target = Path.home() / "Documents" / target.name
        target.parent.mkdir(parents=True, exist_ok=True)
        write_epub(target, title, author, sections, cover, cover_ext or "jpg", language,
                   info.get("description", ""))
    body = [s for s in sections if not s.get("front")] or sections
    sample = [t for k, t in body[0]["paras"] if k == "p"][:3]
    say(1.0, "Done")
    return {"out": str(target), "title": title, "author": author, "pages": len(pages),
            "read_pages": sum(1 for p in pages if p["src"] == "ocr"),
            "chapters": sum(1 for s in sections if not s.get("front")),
            "paras": sum(len(s["paras"]) for s in sections),
            "first_chapter": body[0]["title"], "sample": sample,
            "seconds": round(time.time() - started)}


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Turn a PDF book into an EPUB")
    ap.add_argument("pdf")
    ap.add_argument("--out")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    res = convert(a.pdf, a.out, lambda f, m: print(f"  {f * 100:5.1f}%  {m}", file=sys.stderr, flush=True),
                  language=a.lang)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _cli()
