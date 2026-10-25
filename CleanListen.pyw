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
HERE = Path(__file__).resolve().parent
RESUME = APP_DATA / "resume.json"     # your review, kept across an update or closing the window


def app_version():
    try:
        return json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        return "?"
BG, CARD, INK, MUTED, ACCENT, ACCENT_DK, LINE = (
    "#F6F3EE", "#FFFFFF", "#23211F", "#6D6862", "#2F6F62", "#24574D", "#E3DED6")
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"


def _yellow(note):
    """Notes shown in yellow: the item may not need removing (worth a look)."""
    return bool(re.search(r"fine|unsure|suggests|AI thinks|usually keep|Your call|just the word", note or ""))


def _marked_fine(it, key, note_key):
    """Left in the book because Claude/ChatGPT, the AI or what CleanListen learned says it's fine.
    These are hidden on the review screen unless you ask to see them."""
    if it.get(key, True):
        return False
    return bool(re.search(r": fine|Learned|usually keep|just the word|AI thinks", it.get(note_key) or ""))


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
        self.page_name = None
        self.show_setup()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore()

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
        s.configure("Bg.TCheckbutton", background=BG, font=(FONT, 10))
        s.map("Bg.TCheckbutton", background=[("active", BG)])
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
        self.page_name = "other"
        # "Check for updates" on every screen: updates and comes straight back to where you were
        self._upd_lbl = tk.Label(self.page, text=f"v{app_version()} \u00b7 Check for updates", bg=BG,
                                 fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        self._upd_lbl.place(relx=1.0, y=2, anchor="ne")
        self._upd_lbl.bind("<Button-1>", lambda e: self.check_updates())
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 11),
                     wraplength=700, justify="left").pack(anchor="w", pady=(2, 12))
        return self.page

    def _scroll_area(self, parent):
        """A vertically scrolling area that fills the remaining space."""
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self._canvas = canvas
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        self._inner = inner
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
            ttk.Button(self.footer, text="Re-check a book I've already done\u2026",
                       style="Plain.TButton", command=self.show_past).pack(side="left")
        ttk.Button(self.footer, text="Send what CleanListen learned\u2026", style="Plain.TButton",
                   command=self.share_learned).pack(side="left", padx=(8, 0))
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
                 ("bully", "Bullying  (taunts, name-calling)", False),
                 ("sexual", "Sexual words  (sex, sexy, horny\u2026)", True),
                 ("refs", "Sexual references  (cut sentences about sex)", True),
                 ("sex", "Explicit sex scenes  (cut whole scenes)", True),
                 ("flirt", "Flirting  (cut flirty sentences)", False),
                 ("gore", "Gory descriptions  (cut graphic passages)", True),
                 ("religion", "Religious content  (beliefs, preaching, anger at God)", True),
                 ("relationships", "Same-sex & non-traditional relationships", True)]
        left = 6  # language-type options on the left, content options on the right
        for n, (key, label, on) in enumerate(items):
            v = tk.BooleanVar(value=self.saved_opts.get(key, on))
            self.opts[key] = v
            ttk.Checkbutton(grid, text=label, variable=v).grid(
                row=n if n < left else n - left, column=0 if n < left else 1, sticky="w",
                padx=(0, 26), pady=2)
        self.ai_var = tk.BooleanVar(value=self.saved_opts.get("ai", True))
        ttk.Checkbutton(b3, text="AI helper  (double-checks every filter)",
                        variable=self.ai_var).pack(anchor="w", pady=(10, 0))
        tk.Label(b3, text="Catches what the word lists missed and unticks anything flagged by "
                 "mistake. Runs on your PC; the first time it downloads about 4 GB (shared with "
                 "CleanView). Adds time to each book.", bg=CARD, fg=MUTED, font=(FONT, 9),
                 wraplength=600, justify="left").pack(anchor="w", padx=(22, 0))
        self.claude_var = tk.BooleanVar(value=self.saved_opts.get("claude", False))
        ttk.Checkbutton(b3, text="Final check by Claude or ChatGPT  (reads the whole book and "
                        "checks everything)", variable=self.claude_var).pack(anchor="w", pady=(10, 0))
        tk.Label(b3, text="It reads every finding in context, unticks what isn't really an issue "
                 "and adds anything that was missed. Uses your own Claude or ChatGPT plan (set up "
                 "once). Only the book's words are sent, never the audio. Everything works without "
                 "it too.", bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=600,
                 justify="left").pack(anchor="w", padx=(22, 0))
        cc = self._cc()
        prow = tk.Frame(b3, bg=CARD)
        prow.pack(anchor="w", padx=(22, 0), pady=(4, 0))
        self.provider_var = tk.StringVar(value=cc.PROVIDER if cc else "claude")
        for val, label in (("claude", "Claude  (your Claude plan)"),
                           ("chatgpt", "ChatGPT  (your ChatGPT plan)")):
            tk.Radiobutton(prow, text=label, value=val, variable=self.provider_var, bg=CARD,
                           activebackground=CARD, font=(FONT, 9),
                           command=self._provider_changed).pack(side="left", padx=(0, 14))
        crow = tk.Frame(b3, bg=CARD)
        crow.pack(anchor="w", padx=(22, 0), pady=(4, 0), fill="x")
        self.claude_lbl = tk.Label(crow, text="Checking\u2026", bg=CARD, fg=MUTED,
                                   font=(FONT, 9))
        self.claude_lbl.pack(side="left")
        self.claude_btn = ttk.Button(crow, text="Set up / sign in", style="Plain.TButton",
                                     command=self.claude_setup)
        self.model_row = self._model_picker(b3, bg=CARD)
        self._provider_changed(first=True)

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

    # ---------- updates without losing your place ----------
    def _launcher(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("cl_launcher", str(HERE / "launcher.pyw"))
        spec = importlib.util.spec_from_loader("cl_launcher", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def check_updates(self):
        if getattr(self, "_updating", False):
            return
        if self.page_name == "working":
            messagebox.showinfo("CleanListen", "Let it finish first (or press Cancel), then check "
                                "for updates. Your review will be kept.")
            return
        self._updating = True
        self._upd_lbl.config(text="Checking for updates\u2026")

        def work():
            try:
                L = self._launcher()
                import urllib.request
                with urllib.request.urlopen(L.RAW + "version.json", timeout=10) as r:
                    remote = json.loads(r.read().decode("utf8"))
                if L._ver(remote["version"]) <= L._ver(app_version()):
                    self.q.put(("update_none", app_version()))
                    return
                self.q.put(("update_progress", f"Updating to {remote['version']}\u2026"))
                new = L.update()
                self.q.put(("updated", new or remote["version"]))
            except Exception as ex:
                self.q.put(("update_fail", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _update_msg(self, kind, val):
        self._updating = kind == "update_progress"
        lbl = getattr(self, "_upd_lbl", None)
        if kind == "update_progress":
            if lbl and lbl.winfo_exists():
                lbl.config(text=val)
        elif kind == "update_none":
            if lbl and lbl.winfo_exists():
                lbl.config(text=f"v{val} \u00b7 \u2713 You have the latest version")
        elif kind == "update_fail":
            if lbl and lbl.winfo_exists():
                lbl.config(text=f"v{app_version()} \u00b7 Check for updates")
            messagebox.showerror("CleanListen", f"Couldn't update right now ({val[:200]}). "
                                 "Try again in a few minutes.")
        elif kind == "updated":
            self._save_resume(note=f"CleanListen was updated to version {val}. Everything is just "
                                   "as you left it.")
            env = dict(os.environ, CLEANLISTEN_UPDATED=f"CleanListen was updated to version {val}.")
            try:
                subprocess.Popen([sys.executable, str(HERE / "CleanListen.pyw")], cwd=str(HERE), env=env)
            except Exception as ex:
                messagebox.showinfo("CleanListen", f"Updated to {val}. Close CleanListen and open it "
                                    f"again to finish ({ex}).")
                return
            self.destroy()

    def _save_resume(self, note=""):
        """Remember where you are (the review with all its ticks, or the book you picked)."""
        try:
            data = {"time": __import__("time").time(), "note": note, "audio": self.audio,
                    "ebook": self.ebook, "outdir": self.outdir, "saved_opts": self.saved_opts}
            if self.page_name == "review" and self.analysis and self.workdir:
                self._sync_ticks()
                self._save_analysis()
                data.update(page="review", workdir=str(self.workdir),
                            split=getattr(self, "split_chapters", False),
                            show_fine=bool(getattr(self, "show_fine", None) and self.show_fine.get()))
            elif self.audio:
                data["page"] = "setup"
            else:
                return
            APP_DATA.mkdir(parents=True, exist_ok=True)
            RESUME.write_text(json.dumps(data, indent=1), encoding="utf8")
        except Exception:
            pass

    def _restore(self):
        """Back where you were after an update (or after closing the window on the review)."""
        try:
            data = json.loads(RESUME.read_text(encoding="utf8"))
        except Exception:
            return
        try:
            RESUME.unlink()
        except OSError:
            pass
        import time as _t
        if _t.time() - data.get("time", 0) > 14 * 86400:
            return
        self.audio = [a for a in data.get("audio") or [] if Path(a).exists()]
        self.ebook = data.get("ebook")
        self.outdir = data.get("outdir")
        self.saved_opts = data.get("saved_opts") or {}
        self.resume_note = data.get("note") or "Picked up where you left off."
        if data.get("page") == "review" and data.get("workdir"):
            wd = Path(data["workdir"])
            try:
                self.analysis = json.loads((wd / "analysis.json").read_text())
            except Exception:
                self.analysis = None
            if self.analysis:
                self.workdir = wd
                self.split_chapters = data.get("split", False)
                self.show_fine = tk.BooleanVar(value=data.get("show_fine", False))
                self.show_review()
                return
        if self.audio:
            if data.get("note"):
                os.environ["CLEANLISTEN_UPDATED"] = data["note"]
            self.show_setup()

    def _on_close(self):
        if self.page_name == "review":
            self._save_resume()        # reopen straight onto this review
        self.destroy()

    # ---------- Claude ----------
    def _cc(self):
        try:
            import cleanlisten_claude as cc
            return cc
        except Exception:
            return None

    def _ai_name(self):
        cc = self._cc()
        return cc.name() if cc else "Claude"

    def _provider_changed(self, first=False):
        cc = self._cc()
        if not cc or not getattr(self, "provider_var", None):
            return
        cc.use(self.provider_var.get())
        self.claude_state = None
        if getattr(self, "model_row", None):
            if cc.PROVIDER == "claude":
                self.model_row.pack(anchor="w", padx=(22, 0), pady=(6, 0))
            else:
                self.model_row.pack_forget()
        self.claude_lbl.config(text="Checking\u2026", fg=MUTED)
        self.claude_btn.pack_forget()
        threading.Thread(target=self._claude_status_thread, daemon=True).start()

    def _claude_status_thread(self):
        cc = self._cc()
        prov = cc.PROVIDER if cc else "claude"
        st = cc.status(prov) if cc else "broken"
        self.q.put(("claude_status", st, prov))

    def share_learned(self):
        try:
            import cleanlisten_learn as learn
            path = learn.export()
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't save the file: {ex}")
            return
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')
        messagebox.showinfo(
            "CleanListen",
            f"Saved as \u201c{path.name}\u201d in {path.parent}.\n\n"
            "Attach that file in your chat with Claude and ask for it to be added to CleanListen. "
            "Once it's added, every copy of CleanListen gets what it learned with the next update.\n\n"
            "It has the sentences and words you (and Claude or ChatGPT) cut, muted or kept, and "
            "their notes. No audio.")

    def _show_claude_status(self, st, prov=None):
        cc = self._cc()
        if cc and prov and prov != cc.PROVIDER:
            return      # an answer about the other one; a newer check is on its way
        self.claude_state = st
        if not getattr(self, "claude_lbl", None) or not self.claude_lbl.winfo_exists():
            return
        N = self._ai_name()
        prog = "Codex (for ChatGPT)" if N == "ChatGPT" else "Claude Code"
        text = {"ok": f"\u2713 {N} is ready", "signed_out": f"{N} isn't signed in yet",
                "missing": f"{prog} isn't set up yet (one time, about a minute)",
                "broken": "Claude/ChatGPT files are missing \u2014 reopen CleanListen to update"}.get(st, st)
        self.claude_lbl.config(text=text, fg=ACCENT_DK if st == "ok" else "#8A5A00")
        if st in ("signed_out", "missing"):
            self.claude_btn.pack(side="left", padx=(10, 0))
        else:
            self.claude_btn.pack_forget()

    def claude_setup(self):
        cc = self._cc()
        if not cc:
            return
        N, prov = cc.name(), cc.PROVIDER
        self.claude_lbl.config(text=f"Setting up {N}\u2026 (a browser will open to sign in)")
        self.claude_btn.pack_forget()

        def work():
            try:
                cc.install(lambda f, m: None, provider=prov)
                cc.open_sign_in(provider=prov)
            except Exception as ex:
                self.q.put(("claude_status", f"Couldn't set up {N}: " + str(ex)[:120], prov))
                return
            import time as _t
            st = "signed_out"
            for _ in range(120):          # wait up to 10 minutes for the sign-in to finish
                _t.sleep(5)
                st = cc.status(prov)
                if st == "ok":
                    break
            self.q.put(("claude_status", st, prov))
        threading.Thread(target=work, daemon=True).start()

    def _model_picker(self, parent, bg):
        """A drop-down to choose the Claude model; the choice is remembered."""
        cc = self._cc()
        row = tk.Frame(parent, bg=bg)
        if not cc:
            return row
        names = dict(cc.MODELS)
        tk.Label(row, text="Claude model:", bg=bg, fg=INK, font=(FONT, 9)).pack(side="left")
        var = tk.StringVar(value=names[cc.get_model()])
        box = ttk.Combobox(row, textvariable=var, values=[n for _, n in cc.MODELS], state="readonly",
                           width=16, font=(FONT, 9))
        box.pack(side="left", padx=(6, 0))
        box.bind("<<ComboboxSelected>>", lambda e: cc.set_model(
            next(k for k, n in cc.MODELS if n == var.get())))
        return row

    def _sync_ticks(self):
        """Copy the review screen's ticks into the analysis (before Claude reads it)."""
        for v, sc in getattr(self, "scene_vars", []):
            if bool(v.get()) != bool(sc.get("cut", True)):
                sc["by_you"] = True          # Claude/ChatGPT never undo what you set
            sc["cut"] = bool(v.get())
        for v, m in getattr(self, "mute_vars", []):
            if bool(v.get()) != bool(m.get("on", True)):
                m["by_you"] = True
            m["on"] = bool(v.get())

    def _save_analysis(self):
        try:
            (self.workdir / "analysis.json").write_text(json.dumps(self.analysis, indent=1))
        except Exception:
            pass

    def claude_check(self):
        cc = self._cc()
        if not cc:
            messagebox.showerror("CleanListen", "Claude files are missing. Reopen CleanListen to update.")
            return
        self._sync_ticks()
        self.show_working("Claude is checking the book\u2026", quick="claude")
        self.cancel_flag = False

        def work():
            try:
                asr = engine.load_asr(self.workdir, self.analysis["parts"])
                cc.review(self.analysis, asr, progress=lambda f, m: self.q.put(("progress", f, m)),
                          cancel=lambda: self.cancel_flag)
                self.q.put(("claude_done",))
            except KeyboardInterrupt:
                self.q.put(("claude_done",))
            except Exception as ex:
                self.q.put(("claude_fail", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def open_chat(self):
        cc = self._cc()
        if not cc:
            messagebox.showerror("CleanListen", "Claude files are missing. Reopen CleanListen to update.")
            return
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_win.lift()
            return
        self._sync_ticks()
        try:
            self._ensure_chat()
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't open the chat ({ex}).")
            return
        w = tk.Toplevel(self)
        self.chat_win = w
        N = self._ai_name()
        w.title(f"Ask {N} about this book")
        w.configure(bg=BG)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        w.geometry(f"{int(620 * scale)}x{int(640 * scale)}")
        tk.Label(w, text=f"Ask {N}", bg=BG, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(w, text=f"{N} can read the whole book and everything CleanListen found. Ask it to "
                 "look for anything missed, or anything flagged that isn't really a problem, or tell "
                 "it what to change. Changes show up on your list right away, with an Undo button.",
                 bg=BG, fg=MUTED,
                 font=(FONT, 9), wraplength=int(580 * scale), justify="left").pack(anchor="w", padx=16)
        bottom = tk.Frame(w, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=16, pady=(6, 12))
        quick = tk.Frame(bottom, bg=BG)
        quick.pack(fill="x", pady=(0, 6))
        self.chat_changes = tk.Frame(w, bg=BG)
        self.chat_changes.pack(side="bottom", fill="x", padx=16)
        self.chat_log = tk.Text(w, wrap="word", font=(FONT, 10), bg=CARD, fg=INK, relief="flat",
                                padx=10, pady=8, height=10, width=20)
        self.chat_log.tag_configure("me", foreground=ACCENT_DK, font=(FONT, 10, "bold"))
        self.chat_log.tag_configure("them", foreground=INK)
        self.chat_log.tag_configure("info", foreground=MUTED, font=(FONT, 9, "italic"))
        self.chat_log.pack(fill="both", expand=True, padx=16, pady=8)
        self.chat_log.configure(state="disabled")
        entry_row = tk.Frame(bottom, bg=BG)
        entry_row.pack(fill="x")
        self.chat_entry = tk.Text(entry_row, height=3, wrap="word", font=(FONT, 10), width=20,
                                  relief="flat", highlightthickness=1, highlightbackground=LINE)
        self.chat_entry.pack(side="left", fill="x", expand=True)
        self.chat_send = ttk.Button(entry_row, text="Send", style="Accent.TButton",
                                    command=lambda: self._chat_send())
        self.chat_send.pack(side="left", padx=(8, 0))
        self.chat_entry.bind("<Return>", lambda e: (self._chat_send(), "break")[1])
        for label, q in (("Did it miss anything?", "Read through the whole book and the findings. "
                          "Did CleanListen miss anything my filters should remove?"),
                         ("Anything flagged by mistake?", "Look over every finding in context. Is "
                          "anything flagged that isn't really a problem under my rules?")):
            ttk.Button(quick, text=label, style="Plain.TButton",
                       command=lambda q=q: self._chat_send(q)).pack(side="left", padx=(0, 8))
        self._chat_say("info", f"Tip: {N} looks over the whole book every time you ask, so "
                               "answers can take a minute or two.")

    # ---------- ask about one passage or word, right on the review list ----------
    def _ensure_chat(self):
        cc = self._cc()
        if not cc:
            raise RuntimeError("Claude files are missing. Reopen CleanListen to update.")
        if getattr(self, "chat", None) is None or self.chat.st is not self.analysis:
            asr = engine.load_asr(self.workdir, self.analysis["parts"])
            self.chat = cc.Chat(self.analysis, asr, self.workdir)
        return self.chat

    def _ask_inline(self, holder, item, txt, link, kind):
        """A small box under that passage/word: type what you want, and it changes right away."""
        if getattr(link, "_open", False):
            return
        link._open = True
        N = self._ai_name()
        box = tk.Frame(holder, bg="#EEF5F3", padx=8, pady=6)
        box.pack(fill="x", pady=(4, 0), side="bottom" if kind == "W" else None)
        hint = ("Tip: highlight part of the text above first to point at it. " if txt is not None else "")
        tk.Label(box, text=hint + "e.g. \u201cjust cut the bed line\u201d, \u201ckeep this\u201d, "
                 "\u201cmute only that word\u201d", bg="#EEF5F3", fg=MUTED, font=(FONT, 8),
                 wraplength=640, justify="left").pack(anchor="w")
        row = tk.Frame(box, bg="#EEF5F3")
        row.pack(fill="x", pady=(2, 0))
        entry = ttk.Entry(row)
        entry.pack(side="left", fill="x", expand=True)
        status = tk.Label(box, text="", bg="#EEF5F3", fg=ACCENT_DK, font=(FONT, 9))

        def send(_e=None):
            q = entry.get().strip()
            if not q:
                return
            picked = ""
            if txt is not None:
                try:
                    picked = txt.get("sel.first", "sel.last").strip()
                except tk.TclError:
                    picked = ""
            btn.configure(state="disabled")
            status.config(text=f"{N} is reading\u2026")
            status.pack(anchor="w")
            self._sync_ticks()
            try:
                chat = self._ensure_chat()
            except Exception as ex:
                status.config(text=str(ex))
                return
            fid = ("P" if kind == "P" else "W") + str(item.get("id"))
            if kind == "P":
                what = (f"this passage on my list ({fid}): \"{item.get('text', '')}\"")
            else:
                what = (f"this muted word on my list ({fid}): \"{item.get('word_raw') or item.get('word')}\" in "
                        f"\"\u2026{item.get('ctx_raw', '')} {item.get('word_raw', '')} {item.get('ctx_after_raw', '')}\u2026\"")
            msg = (f"About {what}" + (f"\nI highlighted: \"{picked}\"" if picked else "") +
                   f"\n\n{q}\n\n(Make the change on my list for {fid} - or nearby sentences - as I ask.)")
            self._chat_history().append(("me", f"[about {fid}] " + q))

            def work():
                try:
                    ans, changes = chat.ask(msg)
                    self.q.put(("card_reply", item, ans, changes))
                except Exception as ex:
                    self.q.put(("card_reply", item, f"Sorry, that didn't work: {ex}", []))
            threading.Thread(target=work, daemon=True).start()
        btn = ttk.Button(row, text="Send", style="Plain.TButton", command=send)
        btn.pack(side="left", padx=(6, 0))
        entry.bind("<Return>", send)
        entry.focus_set()

    def _card_reply(self, item, ans, changes):
        import copy
        self._sync_ticks()
        a = self.analysis
        snapshot = (copy.deepcopy(a["scenes"]), copy.deepcopy(a["mutes"]))
        lines = [self.chat.describe(c) for c in changes] if changes else []
        n = self.chat.apply(changes) if changes else 0
        text = ans or "(no answer)"
        if n:
            text += "\nChanged: " + "; ".join(lines)
            self._undo = snapshot
        item["chat_answer"] = text
        self._chat_history().append(("them", text))
        self._chat_say("them", text)
        self._save_analysis()
        self.show_review(True, focus=item)

    def _undo_last(self):
        snap = getattr(self, "_undo", None)
        if not snap:
            return
        self.analysis["scenes"][:], self.analysis["mutes"][:] = snap
        self._undo = None
        self._chat_history().append(("info", "Undid the last change."))
        self._save_analysis()
        self.show_review(True)

    def _chat_history(self):
        a = self.analysis if self.analysis is not None else {}
        return a.setdefault("chat_history", [])

    def _chat_say(self, who, text):
        if not getattr(self, "chat_log", None) or not self.chat_log.winfo_exists():
            return
        self.chat_log.configure(state="normal")
        prefix = {"me": "You: ", "them": self._ai_name() + ": ", "info": ""}[who]
        self.chat_log.insert("end", prefix + text.strip() + "\n\n", who)
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

    def _chat_send(self, text=None):
        if str(self.chat_send.cget("state")) == "disabled":
            return
        q = (text or self.chat_entry.get("1.0", "end")).strip()
        if not q:
            return
        self.chat_entry.delete("1.0", "end")
        for c in self.chat_changes.winfo_children():
            c.destroy()
        self._chat_say("me", q)
        self._chat_history().append(("me", q))
        self._chat_say("info", f"{self._ai_name()} is reading the book\u2026")
        self.chat_send.configure(state="disabled")
        self._sync_ticks()

        def work():
            try:
                ans, changes = self.chat.ask(q)
                self.q.put(("chat_reply", ans, changes))
            except Exception as ex:
                self.q.put(("chat_reply", f"Sorry, that didn't work: {ex}", []))
        threading.Thread(target=work, daemon=True).start()

    def _chat_reply(self, ans, changes):
        if not getattr(self, "chat_win", None) or not self.chat_win.winfo_exists():
            return
        self.chat_send.configure(state="normal")
        self._chat_say("them", ans or "(no answer)")
        self._chat_history().append(("them", ans or ""))
        for c in self.chat_changes.winfo_children():
            c.destroy()
        if not changes:
            return
        # the chat changes the list right away (with an Undo), and the review screen updates
        import copy
        self._sync_ticks()
        a = self.analysis
        snapshot = (copy.deepcopy(a["scenes"]), copy.deepcopy(a["mutes"]))
        lines = [self.chat.describe(c) for c in changes]
        n = self.chat.apply(changes)
        self._save_analysis()
        self._undo = snapshot
        self.show_review(True)
        if not n:
            self._chat_say("info", "(Nothing on the list needed changing.)")
            return
        self._chat_say("info", f"Changed {n} thing{'s' if n != 1 else ''} on your list:\n" +
                       "\n".join("\u2022 " + ln for ln in lines))

        def undo():
            a["scenes"][:], a["mutes"][:] = snapshot
            self._undo = None
            self._save_analysis()
            self.show_review(True)
            for c in self.chat_changes.winfo_children():
                c.destroy()
            self._chat_say("info", "Undone \u2014 the list is back the way it was.")
        ttk.Button(self.chat_changes, text="Undo these changes", style="Plain.TButton",
                   command=undo).pack(anchor="w", pady=(4, 6))

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
            if (b["dir"] / "analysis.json").exists():
                ttk.Button(c, text="Export last results", style="Plain.TButton",
                           command=lambda b=b: self._export_past(b)).pack(side="right", padx=(0, 8))
            tk.Label(c, text=b["title"], bg=CARD, fg=INK, font=(FONT, 11, "bold"),
                     wraplength=520, justify="left").pack(anchor="w")
            n = len(b["audio"])
            meta = (f"{n} file{'s' if n != 1 else ''} · last run "
                    f"{_t.strftime('%b %d, %I:%M %p', _t.localtime(b['when']))}"
                    + (" · with ebook" if b["ebook"] else ""))
            tk.Label(c, text=meta, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

    def _export_past(self, b):
        try:
            a = json.loads((b["dir"] / "analysis.json").read_text(encoding="utf8"))
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't read the saved results ({ex}).")
            return
        self.export_findings(analysis=a, audio=b["audio"], outdir=b.get("outdir"))

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
        self.find_bully, self.find_flirt = self.opts["bully"].get(), self.opts["flirt"].get()
        self.use_ai = self.ai_var.get()
        self.use_claude = self.claude_var.get()
        self.split_chapters = self.split_var.get()
        if not groups and not (find_sex or self.find_refs or self.find_gore or self.find_religion
                               or self.find_relationships or self.find_crude
                               or self.find_bully or self.find_flirt):
            messagebox.showinfo("CleanListen", "Tick at least one thing to remove.")
            return
        self.saved_opts = {k: v.get() for k, v in self.opts.items()}
        self.saved_opts.update(ai=self.use_ai, split=self.split_chapters, claude=self.use_claude)
        if self.use_claude:
            cc = self._cc()
            state = getattr(self, "claude_state", None) or (cc.status() if cc else "broken")
            if state != "ok":
                if not messagebox.askyesno("CleanListen", f"{self._ai_name()} isn't set up or signed "
                                           "in yet, so the final check can't run.\n\nStart without "
                                           "it? (You can still run it from the review screen later.)"):
                    return
                self.use_claude = False
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
        if quick == "claude":
            sub = ("Claude is reading the whole book with everything that was found. Long books "
                   "take a few minutes. Cancel keeps the list as it was.")
        elif quick:
            sub = ("Already listened to, so this skips straight to checking. It takes a few "
                   "minutes (longer with the AI helper or Claude check on).")
        else:
            sub = (f"This book is {fmt_len(dur)} long. You can leave this running "
                   "and come back — closing the window pauses it, and it picks up "
                   "where it left off next time.")
        p = self._new_page(title, sub)
        self.page_name = "working"
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
                use_ai=self.use_ai, find_bully=self.find_bully, find_flirt=self.find_flirt,
                use_claude=getattr(self, "use_claude", False),
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
                    self.analysis["title"] = book_title(self.audio) if self.audio else ""
                    self.show_review()
                elif kind == "rendered":
                    self._saving = False
                    self.show_done(msg[1])
                elif kind in ("update_none", "update_fail", "update_progress", "updated"):
                    self._update_msg(kind, msg[1])
                elif kind == "claude_status":
                    self._show_claude_status(*msg[1:])
                elif kind == "claude_done":
                    self._save_analysis()
                    self.show_review()
                elif kind == "claude_fail":
                    messagebox.showerror("Claude check", msg[1])
                    self.show_review()
                elif kind == "card_reply":
                    self._card_reply(*msg[1:])
                elif kind == "chat_reply":
                    self._chat_reply(msg[1], msg[2])
                elif kind == "cancelled":
                    self.show_setup()
                elif kind == "error":
                    (self.workdir / "last_error.txt").parent.mkdir(parents=True, exist_ok=True)
                    (self.workdir / "last_error.txt").write_text(msg[2], encoding="utf8")
                    messagebox.showerror("CleanListen ran into a problem", msg[1])
                    if getattr(self, "_saving", False) and self.analysis:
                        self._saving = False
                        self.show_review()       # keep your review; just press Save again
                    else:
                        self.show_setup()
        except queue.Empty:
            pass
        self.after(150, self._poll)

    # ---------- page 3: review everything before saving ----------
    def _y_in_list(self, w):
        """How far down the review list a card/row sits (pixels from the top)."""
        y = 0
        inner = getattr(self, "_inner", None)
        while w is not None and w is not inner:
            y += w.winfo_y()
            w = w.master
        return y

    def show_review(self, keep_scroll=False, focus=None):
        """The review list. keep_scroll: redraw without moving - the list stays on the same
        passage you were looking at (focus: the passage/word you just asked about)."""
        anchor = None
        if keep_scroll and self.page_name == "review" and getattr(self, "_canvas", None):
            try:
                c, inner = self._canvas, self._inner
                h = max(1, inner.winfo_height())
                top = c.yview()[0] * h
                if focus is not None and id(focus) in getattr(self, "_item_widgets", {}):
                    w = self._item_widgets[id(focus)]
                    anchor = (id(focus), self._y_in_list(w) - top, c.yview()[0])
                else:   # the passage/word at the top of the view right now
                    best = None
                    for key, w in getattr(self, "_item_widgets", {}).items():
                        y = self._y_in_list(w)
                        if y <= top + 5 and (best is None or y > best[1]):
                            best = (key, y)
                    anchor = (best[0], best[1] - top, c.yview()[0]) if best else (None, 0, c.yview()[0])
            except Exception:
                anchor = None
        self._show_review()
        if anchor:
            # the new list takes a moment to lay out; put it back, then check again as it settles
            for delay in (10, 80, 250, 600):
                self.after(delay, lambda a=anchor: self._scroll_back(*a))

    def _scroll_back(self, key, offset, frac):
        try:
            c, inner = self._canvas, self._inner
            c.configure(scrollregion=c.bbox("all"))
            h = max(1, inner.winfo_height())
            w = getattr(self, "_item_widgets", {}).get(key)
            if w is not None and w.winfo_exists():
                c.yview_moveto(max(0.0, (self._y_in_list(w) - offset) / h))
            else:
                c.yview_moveto(frac)
        except Exception:
            pass

    def _show_review(self):
        a = self.analysis
        self._item_widgets = {}
        scenes, mutes = a["scenes"], a["mutes"]
        if not scenes and not mutes:
            sub = "Nothing to remove was found in this book."
        else:
            sub = "Everything ticked below will be removed. Untick anything you want to keep."
        p = self._new_page("Review before saving", sub)
        self.page_name = "review"
        note = getattr(self, "resume_note", None)
        if note:
            self.resume_note = None
            tk.Label(p, text="\u2713 " + note, bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10), padx=10,
                     pady=6, anchor="w").pack(fill="x", pady=(0, 8))
        for note in (a.get("claude_note"), a.get("learn_note"), a.get("ai_note"), a.get("ebook_note")):
            if note:
                tk.Label(p, text=note, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=720,
                         justify="left").pack(anchor="w", pady=(0, 4))
        N = self._ai_name()
        if a.get("sentences"):
            bar = tk.Frame(p, bg=BG)
            bar.pack(fill="x", pady=(2, 4))
            ttk.Button(bar, text=(f"Check everything with {N} again" if a.get("claude_checked")
                                  else f"Check everything with {N}"), style="Plain.TButton",
                       command=self.claude_check).pack(side="left")
            ttk.Button(bar, text=f"Ask {N}\u2026", style="Plain.TButton",
                       command=self.open_chat).pack(side="left", padx=(8, 0))
            cc = self._cc()
            if cc and cc.PROVIDER == "claude":
                self._model_picker(bar, bg=BG).pack(side="left", padx=(14, 0))
        # what's hidden: things Claude/ChatGPT (or what CleanListen learned) marked fine
        hidden = [x for x in scenes if _marked_fine(x, "cut", "ai_note")] + \
                 [x for x in mutes if _marked_fine(x, "on", "note")]
        bar2 = tk.Frame(p, bg=BG)
        bar2.pack(fill="x", pady=(0, 4))
        if not hasattr(self, "show_fine"):
            self.show_fine = tk.BooleanVar(value=False)
        if hidden:
            ttk.Checkbutton(bar2, text=f"Also show the {len(hidden)} marked fine (left in the book)",
                            variable=self.show_fine, style="Bg.TCheckbutton",
                            command=lambda: (self._sync_ticks(), self.show_review(True))).pack(side="left")
        if getattr(self, "_undo", None):
            ttk.Button(bar2, text=f"Undo {N}'s last change", style="Plain.TButton",
                       command=self._undo_last).pack(side="left", padx=(10, 0))
        if a.get("sentences"):
            ttk.Button(bar2, text="Search all text\u2026", style="Plain.TButton",
                       command=self.open_all_text).pack(side="right")
        ttk.Button(bar2, text="Findings spreadsheet", style="Plain.TButton",
                   command=self._open_findings).pack(side="right", padx=(0, 8))
        show_fine = self.show_fine.get()
        hidden_ids = set(id(x) for x in hidden) if not show_fine else set()
        self.summary_lbl = tk.Label(self.footer, text="", bg=BG, fg=MUTED, font=(FONT, 10))
        self.summary_lbl.pack(side="top", anchor="w", pady=(0, 6))
        btns = tk.Frame(self.footer, bg=BG)
        btns.pack(side="top", fill="x")
        ttk.Button(btns, text="Save clean audiobook", style="Accent.TButton",
                   command=self._save_from_review).pack(side="right")
        ttk.Button(btns, text="Re-check", style="Plain.TButton",
                   command=self.recheck_same).pack(side="right", padx=(0, 10))
        ttk.Button(btns, text="Export for Claude", style="Plain.TButton",
                   command=self.export_findings).pack(side="left")
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
                 ("crude", "Crude humor to cut"), ("bully", "Bullying to cut"),
                 ("flirt", "Flirting to cut"), ("added", "Added by you (or cut before)")]
        for kind, heading in kinds:
            items = [sc for sc in scenes if sc.get("kind", "sex") == kind and id(sc) not in hidden_ids]
            if not items:
                continue
            group_vars = []
            section(heading, len(items), group_vars)
            for sc in items:
                card = tk.Frame(body, bg=CARD, padx=14, pady=10, highlightbackground=LINE,
                                highlightthickness=1)
                self._item_widgets[id(sc)] = card
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
                    good = _yellow(sc["ai_note"])
                    tk.Label(top, text=sc["ai_note"], bg="#FFF4D6" if good else "#E3EFEC",
                             fg="#7A5A00" if good else ACCENT_DK, font=(FONT, 9),
                             padx=6).pack(side="right")
                if sc.get("claude_reason"):
                    tk.Label(card, text=a.get("reviewer", "Claude") + ": " + sc["claude_reason"], bg=CARD, fg=MUTED,
                             font=(FONT, 9, "italic"), wraplength=680, justify="left"
                             ).pack(anchor="w", pady=(4, 0))
                txt = tk.Text(card, wrap="word", width=20, height=min(7, 2 + len(sc["text"]) // 95),
                              font=(FONT, 10), bg="#FBFAF8", fg=INK, relief="flat",
                              padx=8, pady=6, borderwidth=0)
                txt.insert("1.0", sc["text"])
                txt.configure(state="disabled")
                txt.pack(fill="x", pady=(6, 0))
                if sc.get("chat_answer"):
                    tk.Label(card, text=f"{N}: " + sc["chat_answer"], bg="#EEF5F3", fg=ACCENT_DK,
                             font=(FONT, 9), wraplength=680, justify="left", padx=8, pady=4,
                             anchor="w").pack(fill="x", pady=(6, 0))
                if a.get("sentences"):
                    ask = tk.Label(card, text=f"Ask {N} about this\u2026", bg=CARD, fg=ACCENT,
                                   font=(FONT, 9, "underline"), cursor="hand2")
                    ask.pack(anchor="e", pady=(4, 0))
                    ask.bind("<Button-1>", lambda e, c=card, it=sc, t=txt, l=ask:
                             self._ask_inline(c, it, t, l, "P"))

        # words
        self.mute_vars = []
        shown_mutes = [m for m in mutes if id(m) not in hidden_ids]
        if shown_mutes:
            section("Words to mute", len(shown_mutes), self.mute_vars)
            box = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            box.pack(fill="x", pady=4)
            for n, m in enumerate(shown_mutes):
                row = tk.Frame(box, bg=CARD if n % 2 == 0 else "#FAF8F5", padx=10, pady=3)
                self._item_widgets[id(m)] = row
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
                if a.get("sentences"):
                    ask = tk.Label(row, text="Ask", bg=rbg, fg=ACCENT, font=(FONT, 9, "underline"),
                                   cursor="hand2", padx=4)
                    ask.pack(side="right")
                    ask.bind("<Button-1>", lambda e, c=box, it=m, l=ask, r=row:
                             self._ask_inline(r, it, None, l, "W"))
                if m.get("note"):
                    good = _yellow(m["note"])
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
                    if revealed and m.get("claude_reason"):
                        after += "   (" + self.analysis.get("reviewer", "Claude") + ": " + m["claude_reason"] + ")"
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

    def _open_findings(self):
        try:
            import cleanlisten_learn as learn
            path = learn.CSV_PATH
        except Exception:
            path = None
        if path and path.exists():
            open_path(str(path))
        else:
            messagebox.showinfo("CleanListen", "Nothing saved yet. Findings are saved each time "
                                "Claude or ChatGPT checks a book.")

    def open_all_text(self):
        """Every sentence of the book, with a search box: cut sentences or mute words by hand."""
        cc = self._cc()
        if not cc:
            return
        try:
            asr = engine.load_asr(self.workdir, self.analysis["parts"])
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't open the book's text ({ex}).")
            return
        a = self.analysis
        texts = cc.sentence_texts(a, asr)
        multi = len(a["parts"]) > 1
        rows = []
        for n, (wa, _) in enumerate(a["sentences"]):
            w0 = asr[wa]
            where = (f"Part {w0['part'] + 1} " if multi else "") + engine.fmt_t(w0["s"])
            rows.append((n, f"{where}   " + engine._masked_text(texts[n].split())))
        w = tk.Toplevel(self)
        w.title("All text")
        w.configure(bg=BG)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        w.geometry(f"{int(760 * scale)}x{int(600 * scale)}")
        tk.Label(w, text="All text", bg=BG, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(w, text="Every sentence in the book (swear words starred). Search, pick one or more "
                 "sentences (Ctrl-click for several), then cut them, or mute a word in one.",
                 bg=BG, fg=MUTED, font=(FONT, 9), wraplength=int(720 * scale),
                 justify="left").pack(anchor="w", padx=16)
        top = tk.Frame(w, bg=BG)
        top.pack(fill="x", padx=16, pady=6)
        tk.Label(top, text="Search:", bg=BG, fg=INK, font=(FONT, 10)).pack(side="left")
        q = tk.StringVar()
        ttk.Entry(top, textvariable=q).pack(side="left", fill="x", expand=True, padx=(6, 0))
        btns = tk.Frame(w, bg=BG)
        btns.pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        frame = tk.Frame(w, bg=BG)
        frame.pack(fill="both", expand=True, padx=16)
        lb = tk.Listbox(frame, selectmode="extended", font=(FONT, 10), activestyle="none",
                        relief="flat", highlightthickness=1, highlightbackground=LINE)
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        shown = []

        def refill(*_):
            terms = [engine.norm(t) for t in q.get().split() if engine.norm(t)]
            lb.delete(0, "end")
            shown.clear()
            for n, label in rows:
                if terms and not all(t in " ".join(engine.norm(x) for x in texts[n].split()) for t in terms):
                    continue
                shown.append(n)
                lb.insert("end", label)
        q.trace_add("write", refill)
        refill()

        def picked():
            return [shown[i] for i in lb.curselection()]

        def after_change(msg):
            self._save_analysis()
            self.show_review(True)
            status.config(text=msg)

        def cut():
            sel = picked()
            if not sel:
                return
            self._sync_ticks()
            runs = []
            for n in sorted(sel):
                if runs and n == runs[-1][1] + 1:
                    runs[-1][1] = n
                else:
                    runs.append([n, n])
            done = 0
            for x, y in runs:
                if cc._add_passage(a, asr, x, y, "added", True, "Added by you", "", src="you"):
                    a["scenes"][-1]["by_you"] = True
                    done += 1
            a["scenes"].sort(key=lambda z: (z["part"], z["s"]))
            after_change(f"Added {done} passage(s) to cut." if done else
                         "Those sentences are already in the list.")

        def mute():
            sel = picked()
            if len(sel) != 1:
                messagebox.showinfo("CleanListen", "Pick one sentence first.", parent=w)
                return
            from tkinter import simpledialog
            words = simpledialog.askstring("Mute a word", "Which word or words in that sentence "
                                           "should be muted? (type them exactly)", parent=w)
            if not words:
                return
            self._sync_ticks()
            if cc._add_word(a, asr, sel[0], words, "moderate", True, "Added by you", ""):
                for m in a["mutes"]:
                    if m.get("note") == "Added by you" and not m.get("by_you"):
                        m["by_you"] = True
                after_change(f"Muting \u201c{words}\u201d.")
            else:
                messagebox.showinfo("CleanListen", "Couldn't find those words in that sentence "
                                    "(or they're already muted).", parent=w)
        ttk.Button(btns, text="Cut selected sentences", style="Plain.TButton",
                   command=cut).pack(side="left")
        ttk.Button(btns, text="Mute a word in it\u2026", style="Plain.TButton",
                   command=mute).pack(side="left", padx=(8, 0))
        status = tk.Label(btns, text="", bg=BG, fg=ACCENT_DK, font=(FONT, 9))
        status.pack(side="left", padx=(12, 0))
        self.all_text_win = w

    def _update_summary(self):
        ns = sum(v.get() for v, _ in getattr(self, "scene_vars", []))
        nm = sum(v.get() for v, _ in getattr(self, "mute_vars", []))
        self.summary_lbl.config(text=f"{nm} word{'s' if nm != 1 else ''} muted \u00b7 "
                                     f"{ns} passage{'s' if ns != 1 else ''} cut")

    def export_findings(self, analysis=None, audio=None, outdir=None):
        """Write everything on the review screen (real words, not starred out,
        with what's ticked and the AI's notes) to a text file on the Desktop,
        so it can be sent to Claude to fix the filters."""
        from_screen = analysis is None
        a = self.analysis if from_screen else analysis
        audio = self.audio if from_screen else (audio or a.get("parts", []))
        outdir = self.outdir if from_screen else outdir
        try:
            ver = json.loads((Path(__file__).resolve().parent / "version.json").read_text())["version"]
        except Exception:
            ver = "?"
        title = book_title(audio) if audio else "book"
        multi = len(a["parts"]) > 1
        where = lambda x: (f"Part {x['part'] + 1} " if multi else "") + engine.fmt_t(x["s"])
        opts = (getattr(self, "saved_opts", {}) or {}) if from_screen else {}
        L = [f"CleanListen {ver} findings for: {title}",
             f"Exported {__import__('time').strftime('%Y-%m-%d %H:%M')}",
             "Filters ticked: " + (", ".join(k for k, v in opts.items() if v) or "(not recorded)"),
             f"Ebook used: {'yes' if a.get('ebook') else 'no'}"]
        for note in (a.get("claude_note"), a.get("ai_note"), a.get("ebook_note")):
            if note:
                L.append("Note: " + note)
        names = {"sex": "EXPLICIT SCENE", "ref": "SEXUAL REFERENCE", "gore": "GORE",
                 "religion": "RELIGION", "relationship": "RELATIONSHIP", "crude": "CRUDE HUMOR",
                 "bully": "BULLYING", "flirt": "FLIRTING"}
        class _V:  # stands in for a checkbox when exporting a saved result
            def __init__(self, on): self.on = on
            def get(self): return self.on
        if from_screen:     # everything, including what's hidden as "marked fine"
            self._sync_ticks()
            scene_vars = [(_V(sc.get("cut", True)), sc) for sc in a.get("scenes", [])]
            mute_vars = [(_V(m.get("on", True)), m) for m in a.get("mutes", [])]
        else:
            scene_vars = [(_V(sc.get("cut", True)), sc) for sc in a.get("scenes", [])]
            mute_vars = [(_V(m.get("on", True)), m) for m in a.get("mutes", [])]
        L += ["", f"===== PASSAGES TO CUT ({len(scene_vars)}) ====="]
        for n, (v, sc) in enumerate(scene_vars, 1):
            src = "Claude" if sc.get("claude") else ("AI" if sc.get("ai") else "word list")
            L.append(f"\n[{n}] {names.get(sc.get('kind', 'sex'), sc.get('kind', '?').upper())} · "
                     f"{where(sc)} · {sc['e'] - sc['s']:.0f} sec · found by {src} · "
                     f"{'TICKED (will cut)' if v.get() else 'unticked (kept)'}"
                     + (f" · {sc['ai_note']}" if sc.get("ai_note") else ""))
            if sc.get("claude_reason"):
                L.append("    Claude: " + sc["claude_reason"])
            L.append("    " + sc.get("text", "").strip())
        L += ["", f"===== WORDS TO MUTE ({len(mute_vars)}) ====="]
        for n, (v, m) in enumerate(mute_vars, 1):
            word = m.get("word_raw") or m.get("word", "")
            ctx = f"...{m.get('ctx_raw', m.get('ctx', ''))} [[{word}]] {m.get('ctx_after_raw', m.get('ctx_after', ''))}..."
            L.append(f"[{n}] {m.get('cat', '?')} · {where(m)} · "
                     f"{'TICKED' if v.get() else 'unticked'}"
                     + (f" · {m['note']}" if m.get("note") else "")
                     + (f" · Claude: {m['claude_reason']}" if m.get("claude_reason") else "")
                     + f"\n    {ctx}")
        L += ["", "(Real words are shown here so Claude can see exactly what was flagged.)"]
        text = "\n".join(L)
        safe = re.sub(r'[<>:"/\\|?*]', "", title)[:60].strip() or "book"
        dests = [Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop",
                 Path(os.environ.get("USERPROFILE", Path.home())) / "OneDrive" / "Desktop",
                 Path(outdir) if outdir else None, APP_DATA]
        for d in dests:
            if d is None:
                continue
            try:
                d.mkdir(parents=True, exist_ok=True)
                out = d / f"CleanListen findings - {safe}.txt"
                out.write_text(text, encoding="utf-8")
                break
            except Exception:
                continue
        else:
            messagebox.showerror("CleanListen", "Couldn't save the export file.")
            return
        try:
            if os.name == "nt":
                subprocess.Popen(f'explorer /select,"{out}"')
            else:
                open_path(str(out.parent))
        except Exception:
            pass
        messagebox.showinfo("CleanListen", f"Saved:\n{out}\n\nDrag this file into your chat with "
                            "Claude." + (" Your review screen is still here." if from_screen else ""))
        self.last_export = out

    def _save_from_review(self):
        self._sync_ticks()
        a = self.analysis
        cuts = [sc for sc in a["scenes"] if sc.get("cut", True)]
        mutes = [m for m in a["mutes"] if m.get("on", True)]
        self._save_analysis()
        try:   # learn from what you chose
            import cleanlisten_learn as learn
            learn.record(a)
        except Exception:
            pass
        self.save(cuts, mutes)

    def save(self, cuts, mutes):
        self._saving = True
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
        exp = tk.Frame(p, bg=CARD, padx=16, pady=12, highlightbackground=LINE, highlightthickness=1)
        exp.pack(fill="x", pady=(18, 0))
        tk.Label(exp, text="Help teach CleanListen", bg=CARD, fg=INK,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(exp, text="Saves one file with everything we refined on this book \u2014 what you "
                 "cut, kept and changed, Claude's reasons and your chat \u2014 so it can be added to "
                 "the knowledge every copy of CleanListen starts with. No audio.", bg=CARD, fg=MUTED,
                 font=(FONT, 9), wraplength=680, justify="left").pack(anchor="w", pady=(2, 8))
        ttk.Button(exp, text="Export what we refined\u2026", style="Accent.TButton",
                   command=self.export_refined).pack(anchor="w")
        ttk.Button(self.footer, text="Clean another book", style="Plain.TButton",
                   command=self.reset).pack(side="right")
        ttk.Button(self.footer, text="Re-check this book", style="Plain.TButton",
                   command=self.recheck_same).pack(side="right", padx=(0, 10))

    def export_refined(self):
        try:
            import cleanlisten_learn as learn
            path = learn.export_book(self.analysis, title=(self.analysis or {}).get("title", ""))
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't save the file: {ex}")
            return
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')
        messagebox.showinfo("CleanListen", f"Saved as \u201c{path.name}\u201d in {path.parent}.\n\n"
                            "Attach that file in your chat with Claude and ask for it to be added "
                            "to CleanListen. Every copy gets it with the next update.")

    def reset(self):
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.show_setup()


def _make_shortcut():
    # Adds the CleanView and CleanRead desktop shortcuts (they ship alongside CleanListen)
    try:
        import shortcuts
    except Exception:
        return
    for make in ("ensure_cleanview_shortcut", "ensure_cleanread_shortcut"):
        try:
            getattr(shortcuts, make)()
        except Exception:
            pass


if __name__ == "__main__":
    threading.Thread(target=_make_shortcut, daemon=True).start()
    App().mainloop()
