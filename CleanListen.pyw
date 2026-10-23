"""CleanListen — a simple window for cleaning up audiobooks you own."""
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanlisten as engine  # noqa: E402

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
BG, CARD, INK, MUTED, ACCENT, ACCENT_DK, LINE = (
    "#F6F3EE", "#FFFFFF", "#23211F", "#6D6862", "#2F6F62", "#24574D", "#E3DED6")
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"


def natural_key(p):
    """Sort by folder, then file, with numbers in numeric order, so a book in
    Disc 1, Disc 2... folders plays disc by disc (not every disc's track 01 first)."""
    q = Path(p)
    return [[int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", part)]
            for part in (str(q.parent), q.name)]


def _legacy_key(p):
    # the order older versions used; only for finding the saved transcript of a
    # book that was already listened to, so it isn't transcribed again
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(p).name)]


def job_key(files):
    return hashlib.sha1("|".join(f"{a}:{os.path.getsize(a)}" for a in files)
                        .encode()).hexdigest()[:16]


def book_title(files):
    """A readable name for a book: its folder, or the folder above the discs."""
    parents = {str(Path(f).parent) for f in files}
    first = Path(files[0])
    return (first.parent.parent.name if len(parents) > 1 else first.parent.name) or first.stem


def past_books():
    """Books already listened to (saved transcript covers every file and the
    files are still there), newest first. Works for jobs from older versions too."""
    out = []
    jobs = APP_DATA / "jobs"
    if not jobs.exists():
        return out
    for d in jobs.iterdir():
        tfile = d / "transcript.json"
        if not tfile.exists():
            continue
        try:
            info = {}
            for name in ("job.json", "analysis.json"):
                if (d / name).exists():
                    info = {**json.loads((d / name).read_text(encoding="utf8")), **info}
            parts = info.get("audio") or info.get("parts") or list(json.loads(tfile.read_text()).keys())
            heard = set(json.loads(tfile.read_text()).keys())
            parts = sorted(parts, key=natural_key)
            if not parts or not all(Path(p).exists() for p in parts):
                continue
            if not all(str(Path(p).resolve()) in heard for p in parts):
                continue  # listening never finished; it'll resume if started normally
            stamp = max((d / n).stat().st_mtime for n in ("job.json", "analysis.json", "transcript.json")
                        if (d / n).exists())
            ebook = info.get("ebook")
            out.append({"audio": parts, "ebook": ebook if ebook and Path(ebook).exists() else None,
                        "outdir": info.get("outdir"), "title": info.get("title") or book_title(parts),
                        "when": stamp, "dir": d})
        except Exception:
            continue
    # the same book can have two job folders (old + new file order); keep the newest
    seen, uniq = set(), []
    for b in sorted(out, key=lambda b: -b["when"]):
        k = tuple(sorted(str(Path(p).resolve()) for p in b["audio"]))
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return uniq


def fmt_len(sec):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{h} hr {m} min" if h else f"{m} min"


def open_path(p):
    if os.name == "nt":
        os.startfile(p)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CleanListen")
        # Size the window for this screen. Windows display scaling (125%, 150%)
        # makes everything larger, so scale up but never taller than the screen.
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(820 * scale), sw - 40)
        h = min(int(780 * scale), sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(w, int(640 * scale)), min(h, int(480 * scale)))
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(Path(__file__).resolve().parent / "icon.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.cancel_flag = False
        self.audio, self.ebook, self.outdir = [], None, None
        self.analysis, self.workdir = None, None
        self.saved_opts = {}   # filter ticks, kept when re-checking a book
        self._style()
        self.page = None
        self.show_setup()
        self.after(100, self._poll)

    # ---------- look ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        s.configure("Card.TFrame", background=CARD)
        s.configure("TCheckbutton", background=CARD, font=(FONT, 10))
        s.map("TCheckbutton", background=[("active", CARD)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 12, "bold"), padding=(22, 10), borderwidth=0)
        s.map("Accent.TButton", background=[("active", ACCENT_DK), ("disabled", "#A9C2BC")])
        s.configure("Plain.TButton", background="#ECE7E0", foreground=INK, padding=(14, 6),
                    borderwidth=0, font=(FONT, 10))
        s.map("Plain.TButton", background=[("active", "#E0D9CF")])
        s.configure("Green.Horizontal.TProgressbar", troughcolor="#E6E1DA",
                    background=ACCENT, bordercolor="#E6E1DA", lightcolor=ACCENT, darkcolor=ACCENT)

    def _new_page(self, title, subtitle=""):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=(20, 16))
        # Buttons live in a footer packed first, so they always stay visible
        # even when the window is short.
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(12, 0))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(FONT, 20, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 11),
                     wraplength=700, justify="left").pack(anchor="w", pady=(2, 12))
        return self.page

    def _scroll_area(self, parent):
        """A vertically scrolling area that fills the remaining space."""
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def refresh(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            needs = inner.winfo_reqheight() > canvas.winfo_height() + 2
            if needs and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")
            elif not needs and sb.winfo_ismapped():
                sb.pack_forget()

        inner.bind("<Configure>", refresh)
        canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(win, width=e.width), refresh()))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)

        def wheel(delta):
            if inner.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(delta, "units")

        self.bind_all("<MouseWheel>", lambda e: wheel(int(-e.delta / 120)))
        self.bind_all("<Button-4>", lambda e: wheel(-2))
        self.bind_all("<Button-5>", lambda e: wheel(2))
        return inner

    def _card(self, parent, step, heading, note=""):
        outer = tk.Frame(parent, bg=LINE)
        outer.pack(fill="x", pady=6)
        c = tk.Frame(outer, bg=CARD, padx=16, pady=12)
        c.pack(fill="x", padx=1, pady=1)
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=step, bg=ACCENT, fg="white", font=(FONT, 10, "bold"),
                 width=2).pack(side="left", padx=(0, 10))
        tk.Label(top, text=heading, bg=CARD, fg=INK, font=(FONT, 12, "bold")).pack(side="left")
        if note:
            tk.Label(top, text=note, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=8)
        body = tk.Frame(c, bg=CARD)
        body.pack(fill="x", pady=(8, 0), padx=(32, 0))
        return body

    # ---------- page 1: setup ----------
    def show_setup(self):
        p = self._new_page("CleanListen", "Clean up an audiobook you own: mute bad language "
                           "and remove explicit scenes.")
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(p, text="\u2713 " + upd, bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10),
                     padx=10, pady=6, anchor="w").pack(fill="x", pady=(0, 8))
        try:
            ver = json.loads((Path(__file__).resolve().parent / "version.json").read_text())["version"]
            self.title(f"CleanListen {ver}")
        except Exception:
            pass
        self.start_btn = ttk.Button(self.footer, text="Start cleaning", style="Accent.TButton",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")
        try:
            have_past = bool(past_books())
        except Exception:
            have_past = False
        if have_past:
            ttk.Button(self.footer, text="Re-check a book I've already done…",
                       style="Plain.TButton", command=self.show_past).pack(side="left")
        body = self._scroll_area(p)
        self.heard_lbl = tk.Label(body, text="", bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10),
                                  padx=10, pady=6, anchor="w", justify="left", wraplength=680)

        b1 = self._card(body, "1", "Audiobook")
        self.b1_outer = b1.master.master
        row = tk.Frame(b1, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose folder\u2026", style="Plain.TButton",
                   command=self.pick_folder).pack(side="left")
        ttk.Button(row, text="Choose files\u2026", style="Plain.TButton",
                   command=self.pick_audio).pack(side="left", padx=(8, 0))
        self.audio_lbl = tk.Label(b1, text="No audiobook chosen yet", bg=CARD, fg=MUTED,
                                  font=(FONT, 10), wraplength=620, justify="left")
        self.audio_lbl.pack(anchor="w", pady=(8, 0))

        b2 = self._card(body, "2", "Ebook", "optional \u2014 catches words the narrator mumbles")
        row = tk.Frame(b2, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose ebook\u2026", style="Plain.TButton",
                   command=self.pick_ebook).pack(side="left")
        self.ebook_lbl = tk.Label(row, text="None", bg=CARD, fg=MUTED, font=(FONT, 10),
                                  wraplength=480, justify="left")
        self.ebook_lbl.pack(side="left", padx=12)

        b3 = self._card(body, "3", "What to remove")
        self.opts = {}
        grid = tk.Frame(b3, bg=CARD)
        grid.pack(fill="x")
        items = [("swearing", "Swearing  (f-word, s-word, b-word\u2026)", True),
                 ("mild", "Mild words  (damn, hell, crap)", True),
                 ("deity", "God's name used as a swear", True),
                 ("minced", "Soft substitutes  (gosh, heck, freaking)", False),
                 ("crude", "Crude humor  (toilet & gross-out jokes)", True),
                 ("sexual", "Sexual words  (sex, sexy, horny\u2026)", True),
                 ("refs", "Sexual references  (cut sentences about sex)", True),
                 ("sex", "Explicit sex scenes  (cut whole scenes)", True),
                 ("gore", "Gory descriptions  (cut graphic passages)", True),
                 ("religion", "Religious content  (beliefs, preaching, anger at God)", True),
                 ("relationships", "Same-sex & non-traditional relationships", True)]
        for n, (key, label, on) in enumerate(items):
            v = tk.BooleanVar(value=self.saved_opts.get(key, on))
            self.opts[key] = v
            ttk.Checkbutton(grid, text=label, variable=v).grid(
                row=n if n < 5 else n - 5, column=0 if n < 5 else 1, sticky="w",
                padx=(0, 26), pady=2)
        self.ai_var = tk.BooleanVar(value=self.saved_opts.get("ai", True))
        ttk.Checkbutton(b3, text="AI helper  (double-checks every filter)",
                        variable=self.ai_var).pack(anchor="w", pady=(10, 0))
        tk.Label(b3, text="Catches what the word lists missed and unticks anything flagged by "
                 "mistake. Runs on your PC; the first time it downloads about 4 GB (shared with "
                 "CleanView). Adds time to each book.", bg=CARD, fg=MUTED, font=(FONT, 9),
                 wraplength=600, justify="left").pack(anchor="w", padx=(22, 0))

        b4 = self._card(body, "4", "Save to")
        row = tk.Frame(b4, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Change\u2026", style="Plain.TButton",
                   command=self.pick_out).pack(side="right")
        self.out_lbl = tk.Label(row, text="A \u201cClean\u201d folder next to the audiobook", bg=CARD,
                                fg=MUTED, font=(FONT, 10), wraplength=480, justify="left")
        self.out_lbl.pack(side="left")
        self.split_var = tk.BooleanVar(value=self.saved_opts.get("split", False))
        ttk.Checkbutton(b4, text="Also split into chapter files  (for Yoto and players "
                        "that can't skip chapters)", variable=self.split_var).pack(anchor="w", pady=(8, 0))
        self._refresh_labels()

    def _refresh_labels(self):
        if self.audio:
            dur = sum(engine.probe_duration(a) for a in self.audio)
            first = Path(self.audio[0]).name
            if len(first) > 70:
                first = first[:67] + "\u2026"
            extra = f"  \u2026 and {len(self.audio) - 1} more" if len(self.audio) > 1 else ""
            folder = os.path.normpath(str(Path(self.audio[0]).parent))
            self.audio_lbl.config(text=f"{len(self.audio)} file{'s' if len(self.audio) != 1 else ''}"
                                  f" \u00b7 {fmt_len(dur)}   in  {folder}\n{first}{extra}", fg=INK)
            self.start_btn.config(state="normal")
            if not self.outdir:
                self.out_lbl.config(text=os.path.normpath(str(Path(self.audio[0]).parent / "Clean")),
                                    fg=INK)
        if self.ebook:
            self.ebook_lbl.config(text=Path(self.ebook).name, fg=INK)
        if self.outdir:
            self.out_lbl.config(text=os.path.normpath(self.outdir), fg=INK)
        heard = bool(self.audio) and self._already_heard()
        if heard:
            self.heard_lbl.config(text="✓ This book has already been listened to, so the "
                                  "listening step is skipped — it goes straight to checking. "
                                  "Change the ticks below if you like, then press Re-check.")
            self.heard_lbl.pack(fill="x", pady=(0, 6), before=self.b1_outer)
            self.start_btn.config(text="Re-check this book")
        else:
            self.heard_lbl.pack_forget()
            self.start_btn.config(text="Start cleaning")

    def _job_dirs(self):
        new = APP_DATA / "jobs" / job_key(sorted(self.audio, key=natural_key))
        old = APP_DATA / "jobs" / job_key(sorted(self.audio, key=_legacy_key))
        return new, old

    def _already_heard(self):
        try:
            want = {str(Path(p).resolve()) for p in self.audio}
            for d in self._job_dirs():
                t = d / "transcript.json"
                if t.exists() and want <= set(json.loads(t.read_text()).keys()):
                    return True
        except Exception:
            pass
        return False

    # ---------- re-check a book that was already listened to ----------
    def show_past(self):
        p = self._new_page("Re-check a book", "These books were already listened to, so "
                           "re-checking skips the slow listening step. Pick one, adjust the ticks, "
                           "and press Re-check.")
        ttk.Button(self.footer, text="Back", style="Plain.TButton",
                   command=self.show_setup).pack(side="left")
        body = self._scroll_area(p)
        import time as _t
        for b in past_books():
            outer = tk.Frame(body, bg=LINE)
            outer.pack(fill="x", pady=4)
            c = tk.Frame(outer, bg=CARD, padx=14, pady=10)
            c.pack(fill="x", padx=1, pady=1)
            ttk.Button(c, text="Re-check", style="Plain.TButton",
                       command=lambda b=b: self._load_past(b)).pack(side="right")
            tk.Label(c, text=b["title"], bg=CARD, fg=INK, font=(FONT, 11, "bold"),
                     wraplength=520, justify="left").pack(anchor="w")
            n = len(b["audio"])
            meta = (f"{n} file{'s' if n != 1 else ''} · last run "
                    f"{_t.strftime('%b %d, %I:%M %p', _t.localtime(b['when']))}"
                    + (" · with ebook" if b["ebook"] else ""))
            tk.Label(c, text=meta, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

    def _load_past(self, b):
        self.audio = list(b["audio"])
        self.ebook = b["ebook"]
        self.outdir = b["outdir"] or None
        if not self.outdir:
            parents = {str(Path(f).parent) for f in self.audio}
            first = Path(self.audio[0])
            self.outdir = str((first.parent.parent if len(parents) > 1 else first.parent) / "Clean")
        self.analysis = None
        self.show_setup()

    def recheck_same(self):
        """Back to the start screen with the same book loaded and the same ticks."""
        self.analysis = None
        self.show_setup()

    def pick_folder(self):
        d = filedialog.askdirectory(title="Choose the folder with the audiobook in it")
        if not d:
            return
        folder = Path(d)
        files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in engine.AUDIO_EXTS]
        if not files:  # look one level down (some downloads unzip into a subfolder)
            files = [f for sub in folder.iterdir() if sub.is_dir() and sub.name.lower() != "clean"
                     for f in sub.iterdir() if f.is_file() and f.suffix.lower() in engine.AUDIO_EXTS]
        if not files:
            messagebox.showinfo("CleanListen", "No audio files (MP3, M4B\u2026) were found in that folder.")
            return
        self.audio = sorted((str(f) for f in files), key=natural_key)
        books = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in (".epub", ".pdf"))
        if books and not self.ebook:
            self.ebook = str(books[0])
        self.outdir = str(folder / "Clean")  # next to all the discs, not inside Disc 1
        self._refresh_labels()

    def pick_audio(self):
        exts = " ".join("*" + e for e in engine.AUDIO_EXTS)
        files = filedialog.askopenfilenames(title="Choose the audiobook file(s)",
                                            filetypes=[("Audiobooks", exts), ("All files", "*.*")])
        if files:
            self.audio = sorted(files, key=natural_key)
            self.outdir = None
            self._refresh_labels()

    def pick_ebook(self):
        f = filedialog.askopenfilename(title="Choose the ebook",
                                       filetypes=[("Ebooks", "*.epub *.pdf *.txt"), ("All files", "*.*")])
        if f:
            self.ebook = f
            self._refresh_labels()

    def pick_out(self):
        d = filedialog.askdirectory(title="Where should the clean audiobook go?")
        if d:
            self.outdir = d
            self._refresh_labels()

    # ---------- page 2: working ----------
    def start(self):
        groups = [g for g in ("swearing", "mild", "deity", "minced", "sexual") if self.opts[g].get()]
        find_sex = self.opts["sex"].get()
        self.find_refs, self.find_gore = self.opts["refs"].get(), self.opts["gore"].get()
        self.find_religion = self.opts["religion"].get()
        self.find_relationships = self.opts["relationships"].get()
        if self.find_relationships:
            groups.append("orientation")  # also mute gay, lesbian, homosexual... one word at a time
        self.find_crude = self.opts["crude"].get()
        self.use_ai = self.ai_var.get()
        self.split_chapters = self.split_var.get()
        if not groups and not (find_sex or self.find_refs or self.find_gore or self.find_religion
                               or self.find_relationships or self.find_crude):
            messagebox.showinfo("CleanListen", "Tick at least one thing to remove.")
            return
        self.saved_opts = {k: v.get() for k, v in self.opts.items()}
        self.saved_opts.update(ai=self.use_ai, split=self.split_chapters)
        heard = self._already_heard()
        self.workdir, old_dir = self._job_dirs()
        if not (self.workdir / "transcript.json").exists() and (old_dir / "transcript.json").exists():
            self.workdir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(old_dir / "transcript.json", self.workdir / "transcript.json")
        if not self.outdir:
            self.outdir = str(Path(self.audio[0]).parent / "Clean")
        try:  # remember the book so it can be re-checked later from the list
            self.workdir.mkdir(parents=True, exist_ok=True)
            (self.workdir / "job.json").write_text(json.dumps(
                {"audio": self.audio, "ebook": self.ebook, "outdir": self.outdir,
                 "title": book_title(self.audio)}, indent=1), encoding="utf8")
        except Exception:
            pass
        self.show_working("Checking the book…" if heard else "Listening to the book…",
                          quick=heard)
        self.cancel_flag = False
        threading.Thread(target=self._analyze_thread, args=(groups, find_sex), daemon=True).start()

    def show_working(self, title, quick=False):
        dur = sum(engine.probe_duration(a) for a in self.audio) if self.audio else 0
        if quick:
            sub = ("Already listened to, so this skips straight to checking. It takes a few "
                   "minutes (longer with the AI helper on).")
        else:
            sub = (f"This book is {fmt_len(dur)} long. You can leave this running "
                   "and come back — closing the window pauses it, and it picks up "
                   "where it left off next time.")
        p = self._new_page(title, sub)
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=40)
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000,
                                  length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=BG, fg=INK, font=(FONT, 12))
        self.status.pack(anchor="w", pady=(12, 0))
        self.cancel_btn = ttk.Button(self.footer, text="Cancel", style="Plain.TButton", command=self.cancel)
        self.cancel_btn.pack(side="right")

    def cancel(self):
        self.cancel_flag = True
        self.status.config(text="Stopping after the current chunk…")

    def _analyze_thread(self, groups, find_sex):
        try:
            st = engine.analyze(
                self.audio, self.workdir, ebook=self.ebook, groups=groups, find_sex=find_sex,
                find_refs=self.find_refs, find_gore=self.find_gore, find_religion=self.find_religion,
                find_relationships=self.find_relationships, find_crude=self.find_crude,
                use_ai=self.use_ai,
                progress=lambda f, m: self.q.put(("progress", f, m)),
                log=lambda m: self.q.put(("log", m)),
                cancel=lambda: self.cancel_flag)
            self.q.put(("analyzed", st))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except Exception as ex:  # show the problem instead of dying silently
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _render_thread(self, cuts, mutes):
        try:
            res = engine.render(self.workdir, self.outdir, cuts,
                                progress=lambda f, m: self.q.put(("progress", f, m)),
                                log=lambda m: self.q.put(("log", m)),
                                chapters=self.split_chapters, mutes=mutes)
            self.q.put(("rendered", res))
        except Exception as ex:
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress" and getattr(self, "pb", None) and self.pb.winfo_exists():
                    self.pb["value"] = int(msg[1] * 1000)
                    self.status.config(text=msg[2])
                elif kind == "analyzed":
                    self.analysis = msg[1]
                    self.show_review()
                elif kind == "rendered":
                    self.show_done(msg[1])
                elif kind == "cancelled":
                    self.show_setup()
                elif kind == "error":
                    (self.workdir / "last_error.txt").parent.mkdir(parents=True, exist_ok=True)
                    (self.workdir / "last_error.txt").write_text(msg[2], encoding="utf8")
                    messagebox.showerror("CleanListen ran into a problem", msg[1])
                    self.show_setup()
        except queue.Empty:
            pass
        self.after(150, self._poll)

    # ---------- page 3: review everything before saving ----------
    def show_review(self):
        a = self.analysis
        scenes, mutes = a["scenes"], a["mutes"]
        if not scenes and not mutes:
            sub = "Nothing to remove was found in this book."
        else:
            sub = "Everything ticked below will be removed. Untick anything you want to keep."
        p = self._new_page("Review before saving", sub)
        for note in (a.get("ai_note"), a.get("ebook_note")):
            if note:
                tk.Label(p, text=note, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=720,
                         justify="left").pack(anchor="w", pady=(0, 4))
        ttk.Button(self.footer, text="Save clean audiobook", style="Accent.TButton",
                   command=self._save_from_review).pack(side="right")
        ttk.Button(self.footer, text="Re-check", style="Plain.TButton",
                   command=self.recheck_same).pack(side="right", padx=(0, 10))
        self.summary_lbl = tk.Label(self.footer, text="", bg=BG, fg=MUTED, font=(FONT, 10))
        self.summary_lbl.pack(side="left")
        body = self._scroll_area(p)
        multi = len(a["parts"]) > 1
        where = lambda x: (f"Part {x['part'] + 1} \u00b7 " if multi else "") + engine.fmt_t(x["s"])

        def section(title, count, var_list):
            head = tk.Frame(body, bg=BG)
            head.pack(fill="x", pady=(10, 4))
            tk.Label(head, text=f"{title}  ({count})", bg=BG, fg=INK,
                     font=(FONT, 13, "bold")).pack(side="left")
            if count > 1:
                links = tk.Frame(head, bg=BG)
                links.pack(side="right")
                for label, val in (("Tick all", True), ("Untick all", False)):
                    l = tk.Label(links, text=label, bg=BG, fg=ACCENT, font=(FONT, 9, "underline"),
                                 cursor="hand2")
                    l.pack(side="left", padx=6)
                    l.bind("<Button-1>", lambda e, v=val: ([x.set(v) for x, _ in var_list],
                                                            self._update_summary()))

        # passages, grouped by kind
        self.scene_vars = []
        kinds = [("sex", "Explicit scenes to cut"), ("ref", "Sexual references to cut"),
                 ("gore", "Gory descriptions to cut"), ("religion", "Religious content to cut"),
                 ("relationship", "Same-sex & non-traditional relationships to cut"),
                 ("crude", "Crude humor to cut")]
        for kind, heading in kinds:
            items = [sc for sc in scenes if sc.get("kind", "sex") == kind]
            if not items:
                continue
            group_vars = []
            section(heading, len(items), group_vars)
            for sc in items:
                card = tk.Frame(body, bg=CARD, padx=14, pady=10, highlightbackground=LINE,
                                highlightthickness=1)
                card.pack(fill="x", pady=4)
                v = tk.BooleanVar(value=sc.get("cut", True))
                self.scene_vars.append((v, sc))
                group_vars.append((v, sc))
                secs = sc["e"] - sc["s"]
                length = f"{secs / 60:.1f} min" if secs >= 60 else f"{secs:.0f} sec"
                top = tk.Frame(card, bg=CARD)
                top.pack(fill="x")
                ttk.Checkbutton(top, text=f"Cut this   \u00b7   {where(sc)}   \u00b7   {length}",
                                variable=v, command=self._update_summary).pack(side="left")
                if sc.get("ai_note"):
                    good = sc["ai_note"] in ("AI thinks this one is fine", "AI suggests")
                    tk.Label(top, text=sc["ai_note"], bg="#FFF4D6" if good else "#E3EFEC",
                             fg="#7A5A00" if good else ACCENT_DK, font=(FONT, 9),
                             padx=6).pack(side="right")
                txt = tk.Text(card, wrap="word", width=20, height=min(7, 2 + len(sc["text"]) // 95),
                              font=(FONT, 10), bg="#FBFAF8", fg=INK, relief="flat",
                              padx=8, pady=6, borderwidth=0)
                txt.insert("1.0", sc["text"])
                txt.configure(state="disabled")
                txt.pack(fill="x", pady=(6, 0))

        # words
        self.mute_vars = []
        if mutes:
            section("Words to mute", len(mutes), self.mute_vars)
            box = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            box.pack(fill="x", pady=4)
            for n, m in enumerate(mutes):
                row = tk.Frame(box, bg=CARD if n % 2 == 0 else "#FAF8F5", padx=10, pady=3)
                row.pack(fill="x")
                rbg = row.cget("bg")
                v = tk.BooleanVar(value=m.get("on", True))
                self.mute_vars.append((v, m))
                ttk.Checkbutton(row, variable=v, command=self._update_summary).pack(side="left")
                tk.Label(row, text=where(m), bg=rbg, fg=MUTED, font=(FONT, 9), width=16,
                         anchor="w").pack(side="left")
                # "Show" reveals the real word and its sentence; hidden (starred) by default
                show = tk.Label(row, text="Show", bg=rbg, fg=ACCENT, font=(FONT, 9, "underline"),
                                cursor="hand2", padx=6)
                if m.get("word_raw"):
                    show.pack(side="right")
                if m.get("note"):
                    good = m["note"].startswith(("AI thinks", "AI suggests"))
                    tk.Label(row, text=m["note"], bg="#FFF4D6" if good else "#E3EFEC",
                             fg="#7A5A00" if good else ACCENT_DK, font=(FONT, 8),
                             padx=4).pack(side="right")
                elif m.get("src", "audio") != "audio":
                    tk.Label(row, text="from ebook", bg=rbg, fg=ACCENT, font=(FONT, 8)).pack(side="right")
                # the line of text wraps to fit the window, with the muted word highlighted
                line = tk.Text(row, wrap="word", width=20, height=1, font=(FONT, 10), bg=rbg,
                               fg=MUTED, relief="flat", borderwidth=0, highlightthickness=0,
                               cursor="arrow")
                line.tag_configure("w", background="#F3E3DF", foreground="#8A3B2E",
                                   font=(FONT, 10, "bold"))

                def fill(t=line, m=m, revealed=False):
                    before = m.get("ctx_raw" if revealed else "ctx", "")
                    word = m.get("word_raw" if revealed else "word", "")
                    after = m.get("ctx_after_raw" if revealed else "ctx_after", "")
                    t.configure(state="normal")
                    t.delete("1.0", "end")
                    if before:
                        t.insert("end", "\u2026" + before + " ")
                    t.insert("end", f" {word} ", "w")
                    if after:
                        t.insert("end", " " + after + "\u2026")
                    n_chars = len(before) + len(word) + len(after)
                    t.configure(state="disabled", height=1 if n_chars < 70 else 2)

                def toggle(_e=None, t=line, m=m, lbl=show, state={"on": False}):
                    state["on"] = not state["on"]
                    fill(t, m, state["on"])
                    lbl.configure(text="Hide" if state["on"] else "Show")

                show.bind("<Button-1>", toggle)
                fill()
                line.pack(side="left", fill="x", expand=True)
        self._update_summary()

    def _update_summary(self):
        ns = sum(v.get() for v, _ in getattr(self, "scene_vars", []))
        nm = sum(v.get() for v, _ in getattr(self, "mute_vars", []))
        self.summary_lbl.config(text=f"{nm} word{'s' if nm != 1 else ''} muted \u00b7 "
                                     f"{ns} passage{'s' if ns != 1 else ''} cut")

    def _save_from_review(self):
        cuts = [sc for v, sc in self.scene_vars if v.get()]
        mutes = [m for v, m in self.mute_vars if v.get()]
        self.save(cuts, mutes)

    def save(self, cuts, mutes):
        self.show_working("Saving the clean audiobook\u2026")
        self.cancel_btn.destroy()
        threading.Thread(target=self._render_thread, args=(cuts, mutes), daemon=True).start()

    # ---------- page 4: done ----------
    def show_done(self, res):
        p = self._new_page("All done!", "Your clean audiobook is ready.")
        stats = tk.Frame(p, bg=BG)
        stats.pack(fill="x", pady=20)
        cm = res["cut_minutes"]
        removed = (f"{cm:.0f}", "minutes removed") if cm >= 1 else (f"{cm * 60:.0f}", "seconds removed")
        for big, small in [(str(res["mutes"]), "words muted"),
                           (str(res["cuts"]), "passages cut"), removed]:
            box = tk.Frame(stats, bg=CARD, padx=24, pady=14, highlightbackground=LINE,
                           highlightthickness=1)
            box.pack(side="left", padx=(0, 12))
            tk.Label(box, text=big, bg=CARD, fg=ACCENT, font=(FONT, 26, "bold")).pack()
            tk.Label(box, text=small, bg=CARD, fg=MUTED, font=(FONT, 10)).pack()
        tk.Label(p, text=f"Saved in:  {res['out']}", bg=BG, fg=INK, font=(FONT, 10),
                 wraplength=700, justify="left").pack(anchor="w", pady=(4, 6))
        ch = res.get("chapters")
        if ch:
            note = f"Also split into {ch['tracks']} chapter files, in the \u201cChapters\u201d folder."
            tk.Label(p, text=note, bg=BG, fg=INK, font=(FONT, 10), wraplength=700,
                     justify="left").pack(anchor="w", pady=(0, 16))
        else:
            tk.Frame(p, bg=BG, height=10).pack()
        row = tk.Frame(p, bg=BG)
        row.pack(anchor="w")
        ttk.Button(row, text="Open folder", style="Accent.TButton",
                   command=lambda: open_path(res["out"])).pack(side="left")
        ttk.Button(row, text="See what was removed", style="Plain.TButton",
                   command=lambda: open_path(str(Path(res["out"]) / "CleanListen report.txt"))
                   ).pack(side="left", padx=12)
        ttk.Button(self.footer, text="Clean another book", style="Plain.TButton",
                   command=self.reset).pack(side="right")
        ttk.Button(self.footer, text="Re-check this book", style="Plain.TButton",
                   command=self.recheck_same).pack(side="right", padx=(0, 10))

    def reset(self):
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.show_setup()


def _make_shortcut():
    # Adds the CleanView desktop shortcut (CleanView ships alongside CleanListen)
    try:
        import shortcuts
        shortcuts.ensure_cleanview_shortcut()
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=_make_shortcut, daemon=True).start()
    App().mainloop()
