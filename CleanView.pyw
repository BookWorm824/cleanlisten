"""CleanView — a simple window for cleaning up movies and TV episodes you own."""
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
import cleanview as engine  # noqa: E402

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
BG, CARD, INK, MUTED, ACCENT, ACCENT_DK, LINE = (
    "#F6F3EE", "#FFFFFF", "#23211F", "#6D6862", "#2F6F62", "#24574D", "#E3DED6")
CHIP = {"Nudity": "#B5523B", "Sex scene": "#9A3E66", "Violence": "#7A5A1E"}
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


def short(name, n=60):
    return name if len(name) <= n else name[:n - 1] + "…"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CleanView")
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(860 * scale), sw - 40)
        h = min(int(800 * scale), sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(w, int(660 * scale)), min(h, int(500 * scale)))
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(Path(__file__).resolve().parent / "cleanview.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.cancel_flag = False
        self.videos, self.outdir, self.jobs = [], None, []
        self._imgs = []
        self._style()
        self.page = None
        self.show_setup()
        self.after(100, self._poll)

    # ---------- look ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        s.configure("TCheckbutton", background=CARD, font=(FONT, 10))
        s.map("TCheckbutton", background=[("active", CARD)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 12, "bold"), padding=(22, 10), borderwidth=0)
        s.map("Accent.TButton", background=[("active", ACCENT_DK), ("disabled", "#A9C2BC")])
        s.configure("Plain.TButton", background="#ECE7E0", foreground=INK, padding=(14, 6),
                    borderwidth=0, font=(FONT, 10))
        s.map("Plain.TButton", background=[("active", "#E0D9CF")])
        s.configure("Small.TButton", background="#ECE7E0", foreground=INK, padding=(10, 3),
                    borderwidth=0, font=(FONT, 9))
        s.map("Small.TButton", background=[("active", "#E0D9CF")])
        s.configure("Green.Horizontal.TProgressbar", troughcolor="#E6E1DA",
                    background=ACCENT, bordercolor="#E6E1DA", lightcolor=ACCENT, darkcolor=ACCENT)

    def _new_page(self, title, subtitle=""):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        self._imgs = []
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=(20, 16))
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(12, 0))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(FONT, 20, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 11),
                     wraplength=740, justify="left").pack(anchor="w", pady=(2, 12))
        return self.page

    def _scroll_area(self, parent):
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
        p = self._new_page("CleanView", "Clean up a movie or TV episodes you own: mute bad "
                           "language and cut out nudity, sex scenes and violence.")
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(p, text="\u2713 " + upd.replace("CleanListen", "CleanListen & CleanView"),
                     bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10), padx=10, pady=6,
                     anchor="w").pack(fill="x", pady=(0, 8))
        try:
            ver = json.loads((Path(__file__).resolve().parent / "version.json").read_text())["version"]
            self.title(f"CleanView {ver}")
        except Exception:
            pass
        self.start_btn = ttk.Button(self.footer, text="Start cleaning", style="Accent.TButton",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")
        body = self._scroll_area(p)

        b1 = self._card(body, "1", "Movie or episodes")
        row = tk.Frame(b1, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose files…", style="Plain.TButton",
                   command=self.pick_files).pack(side="left")
        ttk.Button(row, text="Choose a folder of episodes…", style="Plain.TButton",
                   command=self.pick_folder).pack(side="left", padx=(8, 0))
        self.vid_lbl = tk.Label(b1, text="Nothing chosen yet", bg=CARD, fg=MUTED,
                                font=(FONT, 10), wraplength=640, justify="left")
        self.vid_lbl.pack(anchor="w", pady=(8, 0))
        tk.Label(b1, text="Works with DRM-free files: DVD and Blu-ray rips, home videos and "
                 "downloads without copy protection. If the movie has subtitles, they're used "
                 "to catch extra words and get cleaned too.", bg=CARD, fg=MUTED, font=(FONT, 9),
                 wraplength=640, justify="left").pack(anchor="w", pady=(6, 0))

        b2 = self._card(body, "2", "What to remove")
        self.opts = {}
        grid = tk.Frame(b2, bg=CARD)
        grid.pack(fill="x")
        items = [("swearing", "Swearing  (f-word, s-word, b-word…)", True),
                 ("mild", "Mild words  (damn, hell, crap)", True),
                 ("deity", "God's name used as a swear", True),
                 ("minced", "Soft substitutes  (gosh, heck, freaking)", False),
                 ("nudity", "Nudity", True),
                 ("sex", "Sex scenes", True),
                 ("violence", "Violence  (shootings, fights, screaming)", True)]
        for n, (key, label, on) in enumerate(items):
            v = tk.BooleanVar(value=on)
            self.opts[key] = v
            ttk.Checkbutton(grid, text=label, variable=v).grid(
                row=n % 4, column=n // 4, sticky="w", padx=(0, 26), pady=2)
        tk.Label(b2, text="Words are muted automatically. Scenes are listed for you to "
                 "check before anything is cut.", bg=CARD, fg=MUTED, font=(FONT, 9),
                 wraplength=640, justify="left").pack(anchor="w", pady=(8, 0))

        b3 = self._card(body, "3", "Save to")
        row = tk.Frame(b3, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Change…", style="Plain.TButton",
                   command=self.pick_out).pack(side="right")
        self.out_lbl = tk.Label(row, text="A “Clean” folder next to the video", bg=CARD,
                                fg=MUTED, font=(FONT, 10), wraplength=500, justify="left")
        self.out_lbl.pack(side="left")
        tk.Label(b3, text="Your original files are never changed.", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w", pady=(6, 0))
        self._refresh_labels()

    def _refresh_labels(self):
        if self.videos:
            dur = sum(engine.cl.probe_duration(v) for v in self.videos)
            first = short(Path(self.videos[0]).name, 70)
            extra = f"  … and {len(self.videos) - 1} more" if len(self.videos) > 1 else ""
            folder = os.path.normpath(str(Path(self.videos[0]).parent))
            n = len(self.videos)
            self.vid_lbl.config(text=f"{n} video{'s' if n != 1 else ''} · {fmt_len(dur)}   in  "
                                f"{folder}\n{first}{extra}", fg=INK)
            self.start_btn.config(state="normal")
            if not self.outdir:
                self.out_lbl.config(text=os.path.normpath(str(Path(self.videos[0]).parent / "Clean")),
                                    fg=INK)
        if self.outdir:
            self.out_lbl.config(text=os.path.normpath(self.outdir), fg=INK)

    def pick_files(self):
        exts = " ".join("*" + e for e in engine.VIDEO_EXTS)
        files = filedialog.askopenfilenames(title="Choose the movie or episodes",
                                            filetypes=[("Videos", exts), ("All files", "*.*")])
        if files:
            self.videos = sorted(files, key=natural_key)
            self.outdir = None
            self._refresh_labels()

    def pick_folder(self):
        d = filedialog.askdirectory(title="Choose the folder with the episodes in it")
        if not d:
            return
        folder = Path(d)
        files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in engine.VIDEO_EXTS
                 and "(Clean)" not in f.name]
        if not files:
            files = [f for sub in folder.iterdir() if sub.is_dir() and sub.name.lower() != "clean"
                     for f in sub.iterdir() if f.is_file() and f.suffix.lower() in engine.VIDEO_EXTS]
        if not files:
            messagebox.showinfo("CleanView", "No video files (MP4, MKV…) were found in that folder.")
            return
        self.videos = sorted((str(f) for f in files), key=natural_key)
        self.outdir = None
        self._refresh_labels()

    def pick_out(self):
        d = filedialog.askdirectory(title="Where should the clean copies go?")
        if d:
            self.outdir = d
            self._refresh_labels()

    # ---------- page 2: working ----------
    def start(self):
        self.groups = [g for g in ("swearing", "mild", "deity", "minced") if self.opts[g].get()]
        self.flags = {k: self.opts[k].get() for k in ("nudity", "sex", "violence")}
        if not self.groups and not any(self.flags.values()):
            messagebox.showinfo("CleanView", "Tick at least one thing to remove.")
            return
        if not self.outdir:
            self.outdir = str(Path(self.videos[0]).parent / "Clean")
        self.jobs = []
        for v in self.videos:
            key = hashlib.sha1(f"{v}:{os.path.getsize(v)}".encode()).hexdigest()[:16]
            self.jobs.append({"video": v, "work": APP_DATA / "views" / key, "analysis": None,
                              "error": None})
        self.cancel_flag = False
        self.show_working("Watching and listening…")
        threading.Thread(target=self._analyze_thread, daemon=True).start()

    def show_working(self, title):
        dur = sum(engine.cl.probe_duration(j["video"]) for j in self.jobs)
        n = len(self.jobs)
        what = f"These {n} videos are" if n > 1 else "This video is"
        p = self._new_page(title, f"{what} {fmt_len(dur)} long. You can "
                           "leave this running and come back — if you close the window, it "
                           "picks up where it left off next time.")
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=30)
        self.which = tk.Label(box, text="", bg=BG, fg=MUTED, font=(FONT, 10))
        self.which.pack(anchor="w", pady=(0, 6))
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000,
                                  length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=BG, fg=INK, font=(FONT, 12))
        self.status.pack(anchor="w", pady=(12, 0))
        self.cancel_btn = ttk.Button(self.footer, text="Cancel", style="Plain.TButton",
                                     command=self.cancel)
        self.cancel_btn.pack(side="right")

    def cancel(self):
        self.cancel_flag = True
        self.status.config(text="Stopping…")

    def _analyze_thread(self):
        try:
            missing = engine.tools_missing()
            if missing and (self.flags["nudity"] or self.flags["sex"] or self.flags["violence"]):
                self.q.put(("which", "Getting ready (one time only)"))
                engine.install_tools(progress=lambda f, m: self.q.put(("progress", f, m, "")))
            n = len(self.jobs)
            for k, j in enumerate(self.jobs):
                self.q.put(("which", (f"Video {k + 1} of {n}:  " if n > 1 else "") +
                            short(Path(j["video"]).name, 80)))
                try:
                    j["analysis"] = engine.analyze(
                        j["video"], j["work"], groups=self.groups,
                        find_nudity=self.flags["nudity"], find_sex=self.flags["sex"],
                        find_violence=self.flags["violence"],
                        progress=lambda f, m, k=k: self.q.put(("progress", (k + f) / n, m, "")),
                        log=lambda m: None, cancel=lambda: self.cancel_flag)
                except engine.VideoError as ex:
                    j["error"] = str(ex)
            self.q.put(("analyzed",))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except Exception as ex:
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _render_thread(self):
        try:
            todo = [j for j in self.jobs if j["analysis"]]
            encs = None
            if any(j["cuts"] for j in todo):
                self.q.put(("progress", 0.0, "Checking the fastest way to save video…", ""))
                encs = engine.working_encoders()
            results = []
            for k, j in enumerate(todo):
                self.q.put(("which", (f"Video {k + 1} of {len(todo)}:  " if len(todo) > 1 else "")
                            + short(Path(j["video"]).name, 80)))
                results.append(engine.render(
                    j["work"], self.outdir, j["cuts"], encoders=encs,
                    progress=lambda f, m, k=k: self.q.put(("progress", (k + f) / len(todo), m, "")),
                    log=lambda m: None, cancel=lambda: self.cancel_flag))
            self.q.put(("rendered", results))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except Exception as ex:
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                alive = getattr(self, "pb", None) is not None and self.pb.winfo_exists()
                if kind == "progress" and alive:
                    self.pb["value"] = int(max(0.0, min(1.0, msg[1])) * 1000)
                    self.status.config(text=msg[2])
                elif kind == "which" and alive:
                    self.which.config(text=msg[1])
                elif kind == "analyzed":
                    self.after_analyze()
                elif kind == "rendered":
                    self.show_done(msg[1])
                elif kind == "cancelled":
                    self.show_setup()
                elif kind == "preview_ready":
                    open_path(msg[1])
                elif kind == "preview_error":
                    messagebox.showerror("CleanView", msg[1])
                elif kind == "error":
                    try:
                        APP_DATA.mkdir(parents=True, exist_ok=True)
                        (APP_DATA / "cleanview_last_error.txt").write_text(msg[2], encoding="utf8")
                    except Exception:
                        pass
                    messagebox.showerror("CleanView ran into a problem", msg[1])
                    self.show_setup()
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def after_analyze(self):
        bad = [j for j in self.jobs if j["error"]]
        if bad:
            messagebox.showwarning("CleanView", "These couldn't be cleaned and will be skipped:\n\n" +
                                   "\n\n".join(j["error"] for j in bad))
        good = [j for j in self.jobs if j["analysis"]]
        if not good:
            self.show_setup()
            return
        if any(j["analysis"]["scenes"] for j in good):
            self.show_review()
        else:
            for j in good:
                j["cuts"] = []
            self.save()

    # ---------- page 3: review scenes ----------
    def show_review(self):
        good = [j for j in self.jobs if j["analysis"]]
        n = sum(len(j["analysis"]["scenes"]) for j in good)
        p = self._new_page(f"{n} scene{'s' if n != 1 else ''} to check",
                           "Checked scenes will be cut out. Untick any you want to keep. The "
                           "pictures are blurred on purpose — use Preview to watch a scene "
                           "in your video player if you're not sure.")
        inner = self._scroll_area(p)
        self.scene_vars = []
        multi = len(good) > 1
        for j in good:
            st = j["analysis"]
            if multi:
                tk.Label(inner, text=Path(j["video"]).name, bg=BG, fg=INK,
                         font=(FONT, 12, "bold"), anchor="w").pack(fill="x", padx=8, pady=(14, 0))
                if not st["scenes"]:
                    tk.Label(inner, text="Nothing to cut — language only.", bg=BG, fg=MUTED,
                             font=(FONT, 10)).pack(anchor="w", padx=8)
            for sc in st["scenes"]:
                self._scene_card(inner, j, sc)
        ttk.Button(self.footer, text="Save clean copies" if multi else "Save clean copy",
                   style="Accent.TButton", command=self._save_from_review).pack(side="right")
        tk.Label(self.footer, text=f"{sum(len(j['analysis']['mutes']) for j in good)} words "
                 "will be muted automatically.", bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(side="left")

    def _scene_card(self, parent, job, sc):
        card = tk.Frame(parent, bg=CARD, padx=14, pady=10, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", padx=8, pady=6)
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        v = tk.BooleanVar(value=sc.get("cut", True))
        self.scene_vars.append((v, job, sc))
        secs = sc["e"] - sc["s"]
        length = f"{secs / 60:.1f} min" if secs >= 60 else f"{secs:.0f} sec"
        ttk.Checkbutton(top, text=f"Cut   ·   {engine.cl.fmt_t(sc['s'])}   ·   {length}",
                        variable=v).pack(side="left")
        for k in sc["kind"]:
            tk.Label(top, text=k, bg=CHIP.get(k, ACCENT), fg="white", font=(FONT, 9, "bold"),
                     padx=8, pady=1).pack(side="left", padx=(10, 0))
        ttk.Button(top, text="Preview ▸", style="Small.TButton",
                   command=lambda: self.preview(job, sc)).pack(side="right")
        mid = tk.Frame(card, bg=CARD)
        mid.pack(fill="x", pady=(8, 0))
        for t in sc.get("thumbs", []):
            try:
                img = tk.PhotoImage(file=t)
            except tk.TclError:
                continue
            self._imgs.append(img)
            tk.Label(mid, image=img, bg=CARD, borderwidth=0).pack(side="left", padx=(0, 6))
        text = tk.Frame(mid, bg=CARD)
        text.pack(side="left", fill="both", expand=True, padx=(6, 0))
        if sc.get("why"):
            tk.Label(text, text="Found: " + sc["why"], bg=CARD, fg=INK, font=(FONT, 9),
                     wraplength=300, justify="left", anchor="w").pack(fill="x")
        said = sc.get("said") or "(no talking)"
        tk.Label(text, text="Said: " + (said if len(said) < 220 else said[:217] + "…"),
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=300, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

    def preview(self, job, sc):
        def go():
            try:
                self.q.put(("preview_ready", engine.make_preview(job["video"], sc["s"], sc["e"],
                                                                 job["work"])))
            except Exception as ex:
                self.q.put(("preview_error", str(ex)))
        threading.Thread(target=go, daemon=True).start()

    def _save_from_review(self):
        for j in self.jobs:
            j["cuts"] = []
        for v, j, sc in self.scene_vars:
            if v.get():
                j["cuts"].append(sc)
        self.save()

    def save(self):
        self.cancel_flag = False
        self.show_working("Saving the clean copy…")
        threading.Thread(target=self._render_thread, daemon=True).start()

    # ---------- page 4: done ----------
    def show_done(self, results):
        multi = len(results) > 1
        p = self._new_page("All done!", f"Your clean cop{'ies are' if multi else 'y is'} ready.")
        stats = tk.Frame(p, bg=BG)
        stats.pack(fill="x", pady=20)
        cm = sum(r["cut_minutes"] for r in results)
        removed = (f"{cm:.0f}", "minutes removed") if cm >= 1 else (f"{cm * 60:.0f}", "seconds removed")
        for big, small in [(str(sum(r["mutes"] for r in results)), "words muted"),
                           (str(sum(r["cuts"] for r in results)), "scenes cut"), removed]:
            box = tk.Frame(stats, bg=CARD, padx=24, pady=14, highlightbackground=LINE,
                           highlightthickness=1)
            box.pack(side="left", padx=(0, 12))
            tk.Label(box, text=big, bg=CARD, fg=ACCENT, font=(FONT, 26, "bold")).pack()
            tk.Label(box, text=small, bg=CARD, fg=MUTED, font=(FONT, 10)).pack()
        tk.Label(p, text=f"Saved in:  {os.path.normpath(results[0]['folder'])}", bg=BG, fg=INK,
                 font=(FONT, 10), wraplength=740, justify="left").pack(anchor="w", pady=(4, 4))
        tk.Label(p, text="Each clean copy has “(Clean)” in its name, with a report "
                 "beside it listing everything that was muted or cut.", bg=BG, fg=MUTED,
                 font=(FONT, 10), wraplength=740, justify="left").pack(anchor="w", pady=(0, 16))
        row = tk.Frame(p, bg=BG)
        row.pack(anchor="w")
        ttk.Button(row, text="Open folder", style="Accent.TButton",
                   command=lambda: open_path(results[0]["folder"])).pack(side="left")
        if not multi:
            ttk.Button(row, text="Play it", style="Plain.TButton",
                       command=lambda: open_path(results[0]["out"])).pack(side="left", padx=12)
        ttk.Button(self.footer, text="Clean another", style="Plain.TButton",
                   command=self.reset).pack(side="right")

    def reset(self):
        self.videos, self.outdir, self.jobs = [], None, []
        self.show_setup()


if __name__ == "__main__":
    App().mainloop()
