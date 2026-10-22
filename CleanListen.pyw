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
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(p).name)]


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
        self.geometry("800x760")
        self.minsize(700, 700)
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(Path(__file__).resolve().parent / "icon.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.cancel_flag = False
        self.audio, self.ebook, self.outdir = [], None, None
        self.analysis, self.workdir = None, None
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
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(FONT, 20, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 11),
                     wraplength=700, justify="left").pack(anchor="w", pady=(2, 14))
        return self.page

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
            tk.Label(p, text="✓ " + upd, bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10),
                     padx=10, pady=6, anchor="w").pack(fill="x", pady=(0, 8))
        try:
            ver = json.loads((Path(__file__).resolve().parent / "version.json").read_text())["version"]
            self.title(f"CleanListen {ver}")
        except Exception:
            pass

        b1 = self._card(p, "1", "Audiobook")
        row = tk.Frame(b1, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose audio files…", style="Plain.TButton",
                   command=self.pick_audio).pack(side="left")
        self.audio_lbl = tk.Label(row, text="No files chosen yet", bg=CARD, fg=MUTED,
                                  font=(FONT, 10), wraplength=430, justify="left")
        self.audio_lbl.pack(side="left", padx=12)
        tk.Label(b1, text="MP3 or M4B. If the book comes in several parts, select them all.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(6, 0))

        b2 = self._card(p, "2", "Ebook", "optional — catches words the narrator mumbles")
        row = tk.Frame(b2, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose ebook…", style="Plain.TButton",
                   command=self.pick_ebook).pack(side="left")
        self.ebook_lbl = tk.Label(row, text="None", bg=CARD, fg=MUTED, font=(FONT, 10),
                                  wraplength=430, justify="left")
        self.ebook_lbl.pack(side="left", padx=12)
        tk.Label(b2, text="EPUB, PDF or TXT. Kindle books are locked and won't work.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(6, 0))

        b3 = self._card(p, "3", "What to remove")
        self.opts = {}
        grid = tk.Frame(b3, bg=CARD)
        grid.pack(fill="x")
        items = [("swearing", "Swearing  (f-word, s-word, b-word…)", True),
                 ("mild", "Mild words  (damn, hell, crap)", True),
                 ("deity", "God's name used as a swear", True),
                 ("minced", "Soft substitutes  (gosh, heck, freaking)", False),
                 ("sex", "Explicit sex scenes  (you'll review them first)", True)]
        for n, (key, label, on) in enumerate(items):
            v = tk.BooleanVar(value=on)
            self.opts[key] = v
            ttk.Checkbutton(grid, text=label, variable=v).grid(
                row=n % 3, column=n // 3, sticky="w", padx=(0, 26), pady=2)

        b4 = self._card(p, "4", "Save to")
        row = tk.Frame(b4, bg=CARD)
        row.pack(fill="x")
        self.out_lbl = tk.Label(row, text="A “Clean” folder next to the audiobook", bg=CARD,
                                fg=MUTED, font=(FONT, 10), wraplength=460, justify="left")
        self.out_lbl.pack(side="left")
        ttk.Button(row, text="Change…", style="Plain.TButton",
                   command=self.pick_out).pack(side="right")
        self.split_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(b4, text="Also split into chapter files  (for Yoto and players "
                        "that can't skip chapters)", variable=self.split_var).pack(anchor="w", pady=(8, 0))

        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        self.start_btn = ttk.Button(bar, text="Start cleaning", style="Accent.TButton",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")
        self._refresh_labels()

    def _refresh_labels(self):
        if self.audio:
            names = ", ".join(Path(a).name for a in self.audio[:3])
            more = f" + {len(self.audio) - 3} more" if len(self.audio) > 3 else ""
            dur = sum(engine.probe_duration(a) for a in self.audio)
            self.audio_lbl.config(text=f"{len(self.audio)} file(s) · {fmt_len(dur)}\n{names}{more}",
                                  fg=INK)
            self.start_btn.config(state="normal")
            if not self.outdir:
                self.out_lbl.config(text=str(Path(self.audio[0]).parent / "Clean"), fg=INK)
        if self.ebook:
            self.ebook_lbl.config(text=Path(self.ebook).name, fg=INK)
        if self.outdir:
            self.out_lbl.config(text=self.outdir, fg=INK)

    def pick_audio(self):
        exts = " ".join("*" + e for e in engine.AUDIO_EXTS)
        files = filedialog.askopenfilenames(title="Choose the audiobook file(s)",
                                            filetypes=[("Audiobooks", exts), ("All files", "*.*")])
        if files:
            self.audio = sorted(files, key=natural_key)
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
        groups = [g for g in ("swearing", "mild", "deity", "minced") if self.opts[g].get()]
        find_sex = self.opts["sex"].get()
        self.split_chapters = self.split_var.get()
        if not groups and not find_sex:
            messagebox.showinfo("CleanListen", "Tick at least one thing to remove.")
            return
        key = hashlib.sha1("|".join(f"{a}:{os.path.getsize(a)}" for a in self.audio)
                           .encode()).hexdigest()[:16]
        self.workdir = APP_DATA / "jobs" / key
        if not self.outdir:
            self.outdir = str(Path(self.audio[0]).parent / "Clean")
        self.show_working("Listening to the book…")
        self.cancel_flag = False
        threading.Thread(target=self._analyze_thread, args=(groups, find_sex), daemon=True).start()

    def show_working(self, title):
        dur = sum(engine.probe_duration(a) for a in self.audio) if self.audio else 0
        p = self._new_page(title, f"This book is {fmt_len(dur)} long. You can leave this running "
                           "and come back — closing the window pauses it, and it picks up "
                           "where it left off next time.")
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=40)
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000,
                                  length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=BG, fg=INK, font=(FONT, 12))
        self.status.pack(anchor="w", pady=(12, 0))
        self.cancel_btn = ttk.Button(p, text="Cancel", style="Plain.TButton", command=self.cancel)
        self.cancel_btn.pack(anchor="e", side="bottom")

    def cancel(self):
        self.cancel_flag = True
        self.status.config(text="Stopping after the current chunk…")

    def _analyze_thread(self, groups, find_sex):
        try:
            st = engine.analyze(
                self.audio, self.workdir, ebook=self.ebook, groups=groups, find_sex=find_sex,
                progress=lambda f, m: self.q.put(("progress", f, m)),
                log=lambda m: self.q.put(("log", m)),
                cancel=lambda: self.cancel_flag)
            self.q.put(("analyzed", st))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except Exception as ex:  # show the problem instead of dying silently
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _render_thread(self, cuts):
        try:
            res = engine.render(self.workdir, self.outdir, cuts,
                                progress=lambda f, m: self.q.put(("progress", f, m)),
                                log=lambda m: self.q.put(("log", m)),
                                chapters=self.split_chapters)
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
                    if self.analysis["scenes"]:
                        self.show_review()
                    else:
                        self.save([])
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

    # ---------- page 3: review scenes ----------
    def show_review(self):
        scenes = self.analysis["scenes"]
        n = len(scenes)
        p = self._new_page(f"{n} explicit scene{'s' if n != 1 else ''} found",
                           "Checked scenes will be cut out. Untick any that aren't really "
                           "explicit (for example, a crime scene) and they'll be kept.")
        if self.analysis.get("ebook_note"):
            tk.Label(p, text=self.analysis["ebook_note"], bg=BG, fg=MUTED,
                     font=(FONT, 9)).pack(anchor="w", pady=(0, 6))
        wrap = tk.Frame(p, bg=LINE)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        sb.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-2, "units"))
        self.bind_all("<Button-5>", lambda e: canvas.yview_scroll(2, "units"))

        self.scene_vars = []
        multi = len(self.analysis["parts"]) > 1
        for sc in scenes:
            card = tk.Frame(inner, bg=CARD, padx=14, pady=10, highlightbackground=LINE,
                            highlightthickness=1)
            card.pack(fill="x", padx=8, pady=6)
            v = tk.BooleanVar(value=sc.get("cut", True))
            self.scene_vars.append((v, sc))
            where = (f"Part {sc['part'] + 1} · " if multi else "") + engine.fmt_t(sc["s"])
            mins = (sc["e"] - sc["s"]) / 60
            length = f"{mins:.1f} min" if mins >= 1 else f"{sc['e'] - sc['s']:.0f} sec"
            ttk.Checkbutton(card, text=f"Cut this scene   ·   {where}   ·   {length}",
                            variable=v).pack(anchor="w")
            txt = tk.Text(card, wrap="word", height=min(7, 2 + len(sc["text"]) // 95),
                          font=(FONT, 10), bg="#FBFAF8", fg=INK, relief="flat",
                          padx=8, pady=6, borderwidth=0)
            txt.insert("1.0", sc["text"])
            txt.configure(state="disabled")
            txt.pack(fill="x", pady=(6, 0))

        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="Save clean audiobook", style="Accent.TButton",
                   command=lambda: self.save([sc for v, sc in self.scene_vars if v.get()])
                   ).pack(side="right")

    def save(self, cuts):
        self.unbind_all("<MouseWheel>")
        self.show_working("Saving the clean audiobook…")
        self.cancel_btn.destroy()
        threading.Thread(target=self._render_thread, args=(cuts,), daemon=True).start()

    # ---------- page 4: done ----------
    def show_done(self, res):
        p = self._new_page("All done!", "Your clean audiobook is ready.")
        stats = tk.Frame(p, bg=BG)
        stats.pack(fill="x", pady=20)
        cm = res["cut_minutes"]
        removed = (f"{cm:.0f}", "minutes removed") if cm >= 1 else (f"{cm * 60:.0f}", "seconds removed")
        for big, small in [(str(res["mutes"]), "words muted"),
                           (str(res["cuts"]), "scenes cut"), removed]:
            box = tk.Frame(stats, bg=CARD, padx=24, pady=14, highlightbackground=LINE,
                           highlightthickness=1)
            box.pack(side="left", padx=(0, 12))
            tk.Label(box, text=big, bg=CARD, fg=ACCENT, font=(FONT, 26, "bold")).pack()
            tk.Label(box, text=small, bg=CARD, fg=MUTED, font=(FONT, 10)).pack()
        tk.Label(p, text=f"Saved in:  {res['out']}", bg=BG, fg=INK, font=(FONT, 10),
                 wraplength=700, justify="left").pack(anchor="w", pady=(4, 6))
        ch = res.get("chapters")
        if ch:
            if ch["cards"] > 1:
                note = (f"Also split into {ch['tracks']} chapter files, in {ch['cards']} folders — "
                        f"one per Yoto card (each card holds up to 5 hours).")
            else:
                note = f"Also split into {ch['tracks']} chapter files, in the “Chapters” folder."
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
        ttk.Button(p, text="Clean another book", style="Plain.TButton",
                   command=self.reset).pack(anchor="e", side="bottom")

    def reset(self):
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.show_setup()


if __name__ == "__main__":
    App().mainloop()
