"""CleanRead — check what's in an ebook before your kids read it, or make a clean copy."""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cleanread as engine  # noqa: E402
import filters as F  # noqa: E402  (the filters, shared with CleanListen)


def chime():
    """The Windows "information" sound, so a question is heard like the other boxes
    (a yes/no box is silent on Windows; Jason missed the "Send it in now?" one)."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


APP = "CleanRead"
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
SETTINGS = APP_DATA / "cleanread_settings.json"
BG, CARD, INK, MUTED, ACCENT, ACCENT_DK, LINE = (
    "#F6F3EE", "#FFFFFF", "#23211F", "#5C5852", "#2F6F62", "#24574D", "#E3DED6")
# The one main step on each page (start, Save clean copy, Clean another book) is a big
# bright green button, so it's easy to spot; grey buttons have an edge.
GO, GO_DK, BUTTON_EDGE = "#1E7E34", "#17652A", "#B9AFA2"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
CHIP = {"none": ("#EEF1EE", "#6D7A72"), "mentioned": ("#E6F0FA", "#2B5B8A"),
        "some": ("#FFF1D6", "#8A5A00"), "a lot": ("#FBE1DC", "#9A2F1F")}
BOOK_TYPES = [("Ebooks", "*.epub *.pdf *.txt"), ("All files", "*.*")]

STYLE = [("dash", "Replace with a dash  ( — )"), ("stars", "First letter and stars  (d***)"),
         ("remove", "Take the word out completely")]


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf8"))
    except Exception:
        return {}


def save_settings(d):
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(d, indent=1), encoding="utf8")
    except Exception:
        pass


def open_path(p):
    p = str(p)
    if os.name == "nt":
        os.startfile(p)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def show_in_folder(p):
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(str(p))])
    else:
        open_path(Path(p).parent)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(860 * scale), sw - 40)
        h = min(int(800 * scale), sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(w, int(640 * scale)), min(h, int(480 * scale)))
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(HERE / "cleanread.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.cancel_flag = False
        self.settings = load_settings()
        self.book_path = None
        self.book = None          # parsed book, kept while the same file is loaded
        self.mode = tk.StringVar(value=self.settings.get("mode", "check"))
        self.outdir = None
        self.report = None
        self.analysis = None
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
        s.configure("TRadiobutton", background=CARD, font=(FONT, 11, "bold"))
        s.map("TRadiobutton", background=[("active", CARD)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 12, "bold"), padding=(22, 10), borderwidth=0)
        s.map("Accent.TButton", background=[("active", ACCENT_DK), ("disabled", "#A9C2BC")])
        s.configure("Main.TButton", background=GO, foreground="white",
                    font=(FONT, 15, "bold"), padding=(28, 7), borderwidth=0)
        s.map("Main.TButton", background=[("active", GO_DK), ("disabled", "#A8C9B0")])
        s.configure("Go.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 11, "bold"), padding=(14, 5), borderwidth=0)
        s.map("Go.TButton", background=[("active", ACCENT_DK), ("disabled", "#A9C2BC")])
        edge = {"bordercolor": BUTTON_EDGE, "lightcolor": "#ECE7E0", "darkcolor": "#ECE7E0"}
        s.configure("Plain.TButton", background="#ECE7E0", foreground=INK, padding=(14, 6),
                    borderwidth=1, font=(FONT, 10), **edge)
        s.map("Plain.TButton", background=[("active", "#E0D9CF")])
        s.configure("Green.Horizontal.TProgressbar", troughcolor="#E6E1DA",
                    background=ACCENT, bordercolor="#E6E1DA", lightcolor=ACCENT, darkcolor=ACCENT)
        s.configure("TCombobox", padding=4)

    def _new_page(self, title, subtitle="", name=""):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=(20, 16))
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(12, 0))
        if name:                # which book this is (Jason: "you don't know what you've cleaned")
            tk.Label(self.page, text=name, bg=BG, fg=ACCENT_DK, font=(FONT, 16, "bold"),
                     wraplength=760, justify="left").pack(anchor="w", pady=(0, 2))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(FONT, 20, "bold"),
                 wraplength=760, justify="left").pack(anchor="w")
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
        self._canvas = canvas
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

    def _note(self, parent, text, bg=CARD):
        tk.Label(parent, text=text, bg=bg, fg=MUTED, font=(FONT, 9), wraplength=640,
                 justify="left").pack(anchor="w", padx=(22, 0))

    def _link(self, parent, text, cmd, bg=BG):
        l = tk.Label(parent, text=text, bg=bg, fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        l.bind("<Button-1>", lambda e: cmd())
        return l

    # ---------- page 1: choose a book and what to do ----------
    def show_setup(self):
        p = self._new_page(APP, "Check what's in a book before your kids read it, or make a clean "
                                "copy with the language and content you don't want taken out.")
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(p, text="✓ " + upd, bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10),
                     padx=10, pady=6, anchor="w").pack(fill="x", pady=(0, 8))
        try:
            ver = json.loads((HERE / "version.json").read_text())["version"]
            self.title(f"{APP} {ver}")
        except Exception:
            pass
        self.start_btn = ttk.Button(self.footer, text="", style="Main.TButton",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")
        body = self._scroll_area(p)

        b1 = self._card(body, "1", "Ebook", "EPUB, PDF or TXT — not copy-protected")
        row = tk.Frame(b1, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Choose ebook…", style="Go.TButton",
                   command=self.pick_book).pack(side="left")
        self.book_lbl = tk.Label(row, text="No book chosen yet", bg=CARD, fg=MUTED, font=(FONT, 10),
                                 wraplength=520, justify="left")
        self.book_lbl.pack(side="left", padx=12)

        b2 = self._card(body, "2", "What do you want to do?")
        for val, head, sub in (
                ("check", "Check the content",
                 "Reads the whole book and makes a report for parents: witches, dark magic, vampires, "
                 "werewolves, bullying, disrespect toward parents, romance, language and more — "
                 "with the actual sentences and where they are."),
                ("clean", "Make a clean copy",
                 "Marks out bad words and cuts the content you choose, using the same filters as "
                 "CleanListen and CleanView. You see everything before it's saved.")):
            ttk.Radiobutton(b2, text=head, value=val, variable=self.mode,
                            command=self._mode_changed).pack(anchor="w", pady=(4, 0))
            tk.Label(b2, text=sub, bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=640,
                     justify="left").pack(anchor="w", padx=(22, 0), pady=(0, 4))

        self.opt_host = tk.Frame(body, bg=BG)
        self.opt_host.pack(fill="x")
        self._build_options()
        self._refresh()

    def _mode_changed(self):
        self._save_opts()
        self._build_options()
        self._refresh()

    def _build_options(self):
        for w in self.opt_host.winfo_children():
            w.destroy()
        st = self.settings
        self._built_mode = self.mode.get()
        if self.mode.get() == "check":
            b3 = self._card(self.opt_host, "3", "Options")
            self.ai_var = tk.BooleanVar(value=st.get("check_ai", False))
            ttk.Checkbutton(b3, text="AI helper  (reads for what word lists can't spot)",
                            variable=self.ai_var).pack(anchor="w")
            self._note(b3, "Catches things like a child sneaking around or mocking their parents when "
                       "no warning words are used. Runs on your PC. Without it the check takes under "
                       "a minute; with it, the check takes longer (20–60 minutes for a novel).")
            return
        b3 = self._card(self.opt_host, "3", "What to take out")
        # the same filters as CleanListen and CleanView, chosen in their own window (filters.py)
        self.filter_card = F.FilterCard(b3, wrap=640)
        row = tk.Frame(b3, bg=CARD)
        row.pack(anchor="w", pady=(10, 0))
        tk.Label(row, text="How marked-out words look:", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.style_box = ttk.Combobox(row, state="readonly", width=30, values=[l for _, l in STYLE])
        self.style_box.current([k for k, _ in STYLE].index(st.get("style", "dash")))
        self.style_box.pack(side="left", padx=(8, 0))
        self.marker_var = tk.BooleanVar(value=st.get("marker", True))
        ttk.Checkbutton(b3, text="Show […] where something was cut  (so a jump in the story "
                        "makes sense)", variable=self.marker_var).pack(anchor="w", pady=(12, 0))
        self.ai_var = tk.BooleanVar(value=st.get("clean_ai", True))
        ttk.Checkbutton(b3, text="AI helper  (double-checks every filter)",
                        variable=self.ai_var).pack(anchor="w", pady=(6, 0))
        self._note(b3, "Catches what the word lists missed and unticks anything flagged by mistake. "
                   "Runs on your PC. The check takes longer with it on (20–60 minutes for a novel).")
        b4 = self._card(self.opt_host, "4", "Save to")
        row = tk.Frame(b4, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Change…", style="Plain.TButton", command=self.pick_out).pack(side="right")
        self.out_lbl = tk.Label(row, text="Next to the original book", bg=CARD, fg=MUTED,
                                font=(FONT, 10), wraplength=520, justify="left")
        self.out_lbl.pack(side="left")
        tk.Label(b4, text="The original is never changed. EPUB books stay EPUB (with “(Clean)” "
                 "added to the title); a PDF comes out as a plain EPUB; a TXT stays TXT.",
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=640, justify="left").pack(anchor="w", pady=(6, 0))

    def _refresh(self):
        if self.book_path:
            self.book_lbl.config(text=Path(self.book_path).name, fg=INK)
            self.start_btn.config(state="normal")
        self.start_btn.config(text="Check this book" if self.mode.get() == "check" else "Find what to remove")
        if self.mode.get() == "clean" and getattr(self, "out_lbl", None) and self.out_lbl.winfo_exists():
            if self.outdir:
                self.out_lbl.config(text=os.path.normpath(self.outdir), fg=INK)
            elif self.book_path:
                self.out_lbl.config(text=os.path.normpath(str(Path(self.book_path).parent)), fg=INK)

    def pick_book(self):
        f = filedialog.askopenfilename(title="Choose the ebook", filetypes=BOOK_TYPES)
        if f:
            if f != self.book_path:
                self.book = None
            self.book_path = f
            self.outdir = None
            self._refresh()

    def pick_out(self):
        d = filedialog.askdirectory(title="Where should the clean copy go?")
        if d:
            self.outdir = d
            self._refresh()

    def _save_opts(self):
        """Remember the ticks of the options card that is currently showing."""
        st = self.settings
        st["mode"] = self.mode.get()
        built = getattr(self, "_built_mode", None)
        try:
            if built == "check":
                st["check_ai"] = self.ai_var.get()
            elif built == "clean":
                st["style"] = STYLE[self.style_box.current()][0]
                st["marker"] = self.marker_var.get()
                st["clean_ai"] = self.ai_var.get()
        except (tk.TclError, AttributeError):
            pass
        save_settings(st)

    # ---------- working ----------
    def start(self):
        if not self.book_path:
            return
        mode = self.mode.get()
        if mode == "check":
            self._save_opts()
            self.show_working("Checking the book…", "Reading every sentence. " + (
                "The AI helper is on, so the check will take longer. You can leave it running."
                if self.ai_var.get() else "This takes under a minute."))
            threading.Thread(target=self._scan_thread, args=(self.ai_var.get(),), daemon=True).start()
            return
        ticks, mywords = self.filter_card.ticks(), self.filter_card.mywords()
        if not F.anything_on(ticks) and not mywords:
            messagebox.showinfo(APP, "Tick at least one thing to take out (Choose filters\u2026).")
            return
        opts = F.read_opts(ticks, mywords)
        opts["ai"] = self.ai_var.get()
        self.clean_opts = opts
        self.style = STYLE[self.style_box.current()][0]
        self.marker = self.marker_var.get()
        self._save_opts()
        self.show_working("Finding what to remove…", "Nothing is changed yet — you'll see "
                          "everything first." + (" The AI helper is on, so the check will take longer."
                                                 if opts["ai"] else ""))
        threading.Thread(target=self._analyze_thread, args=(opts,), daemon=True).start()

    def show_working(self, title, sub=""):
        p = self._new_page(title, sub)
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=40)
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000, length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=BG, fg=INK, font=(FONT, 12))
        self.status.pack(anchor="w", pady=(12, 0))
        self.cancel_flag = False
        self.cancel_btn = ttk.Button(self.footer, text="Cancel", style="Plain.TButton", command=self.cancel)
        self.cancel_btn.pack(side="right")

    def cancel(self):
        self.cancel_flag = True
        self.status.config(text="Stopping…")

    def _load_book(self):
        if self.book is None or str(self.book.path) != str(Path(self.book_path)):
            self.q.put(("progress", 0.01, "Opening the book…"))
            self.book = engine.Book(self.book_path)
        return self.book

    def _prog(self, f, m):
        self.q.put(("progress", f, m))

    def _scan_thread(self, use_ai):
        try:
            book = self._load_book()
            res = engine.scan(book, use_ai=use_ai, progress=self._prog, cancel=lambda: self.cancel_flag)
            html = engine.report_html(res)
            path = Path(self.book_path).with_name(Path(self.book_path).stem + " - Content Report.html")
            try:
                path.write_text(html, encoding="utf8")
            except OSError:
                path = APP_DATA / "reports" / path.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf8")
            res["report_path"] = str(path)
            self.q.put(("scanned", res))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except engine.BookError as ex:
            self.q.put(("error", str(ex), ""))
        except Exception as ex:
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _analyze_thread(self, opts):
        try:
            book = self._load_book()
            an = engine.analyze(book, opts, progress=self._prog, cancel=lambda: self.cancel_flag)
            self.q.put(("analyzed", an))
        except KeyboardInterrupt:
            self.q.put(("cancelled",))
        except engine.BookError as ex:
            self.q.put(("error", str(ex), ""))
        except Exception as ex:
            self.q.put(("error", str(ex), traceback.format_exc()))

    def _write_thread(self, cuts, mutes):
        try:
            book = self.book
            out = engine.clean_out_path(book, self.outdir)
            res = engine.write_clean(book, cuts, mutes, out, self.style, self.marker, progress=self._prog)
            rep = out.with_name(out.stem + " - what was removed.txt")
            try:
                rep.write_text(engine.removal_report(book, cuts, mutes, res), encoding="utf8")
                res["report"] = str(rep)
            except OSError:
                pass
            self.q.put(("written", res))
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
                elif kind == "scanned":
                    self.report = msg[1]
                    self.show_report()
                elif kind == "analyzed":
                    self.analysis = msg[1]
                    self.show_review()
                elif kind == "written":
                    self.show_done(msg[1])
                elif kind == "cancelled":
                    self.show_setup()
                elif kind == "sent":
                    if msg[2] is None:
                        messagebox.showinfo(APP, "Sent. Thank you!")
                    else:
                        self._saved_by_hand(msg[1], "Couldn't send it just now.\n\n")
                elif kind == "error":
                    if msg[2]:
                        try:
                            APP_DATA.mkdir(parents=True, exist_ok=True)
                            (APP_DATA / "cleanread_last_error.txt").write_text(msg[2], encoding="utf8")
                        except OSError:
                            pass
                    messagebox.showerror(f"{APP} ran into a problem", msg[1])
                    self.show_setup()
        except queue.Empty:
            pass
        self.after(150, self._poll)

    # ---------- page 2a: the content report ----------
    def show_report(self):
        r = self.report
        bits = [r.get("author") or "", f"{r['words']:,} words"]
        if r.get("grade"):
            bits.append(f"about a grade {r['grade']} reading level")
        p = self._new_page(r["title"] or "Content check", " · ".join(b for b in bits if b))
        for note in (r.get("ai_note"), r.get("learn_note")):
            if note:
                tk.Label(p, text=note, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=740,
                         justify="left").pack(anchor="w", pady=(0, 6))
        ttk.Button(self.footer, text="Open full report", style="Accent.TButton",
                   command=lambda: (self._write_report(r), open_path(r["report_path"]))).pack(side="right")
        ttk.Button(self.footer, text="Make a clean copy", style="Plain.TButton",
                   command=self._to_clean).pack(side="right", padx=(0, 10))
        ttk.Button(self.footer, text="Check another book", style="Plain.TButton",
                   command=self.reset).pack(side="left")
        ttk.Button(self.footer, text="Send what you marked…", style="Plain.TButton",
                   command=lambda: self.send_marks(r, "check")).pack(side="left", padx=(10, 0))
        body = self._scroll_area(p)
        tip = tk.Frame(body, bg="#E3EFEC", padx=12, pady=8)
        tip.pack(fill="x", pady=(0, 8))
        tk.Label(tip, text="Something here isn't a problem? Click “Not a problem” next to it. It's left "
                 "out of the report, and CleanRead remembers it next time. When you're done, click "
                 "“Send what you marked” so CleanRead can get better.", bg="#E3EFEC", fg=ACCENT_DK,
                 font=(FONT, 10), wraplength=720, justify="left").pack(anchor="w")
        tk.Label(body, text="The full report (with every sentence, printable) is saved as:\n"
                 + os.path.normpath(r["report_path"]), bg=BG, fg=MUTED, font=(FONT, 9),
                 justify="left", wraplength=740).pack(anchor="w", pady=(0, 8))

        for kind, c in r["cats"].items():
            c["kind"] = kind
        all_cats = list(r["cats"].values())
        lang = []
        for cat, label in engine.LANG_CATS:
            c = r["lang"].get(cat)
            lang.append(c if c else {"label": label, "count": 0, "rating": "none", "items": [],
                                     "chapters_list": [], "group": "Language"})
            lang[-1]["group"] = "Language"
            lang[-1]["lang"] = True
            lang[-1]["kind"] = "word"
        none_found = []
        for grp in engine.SCAN_GROUPS:
            cats = lang if grp == "Language" else [c for c in all_cats if c["group"] == grp]
            found = [c for c in cats if c["items"]]
            none_found += [c["label"] for c in cats if not c["items"]]
            if not found:
                continue
            tk.Label(body, text=grp, bg=BG, fg=INK, font=(FONT, 13, "bold")).pack(anchor="w", pady=(14, 4))
            for c in found:
                self._report_row(body, c)
        if none_found:
            tk.Label(body, text="Not found in this book", bg=BG, fg=INK,
                     font=(FONT, 13, "bold")).pack(anchor="w", pady=(18, 4))
            tk.Label(body, text=", ".join(none_found), bg=BG, fg=MUTED, font=(FONT, 10),
                     wraplength=740, justify="left").pack(anchor="w")
        tk.Label(body, text="This is a guide, not a guarantee: a theme can be there without the words "
                 "that flag it, and a flagged sentence may be harmless in context — that's why the "
                 "sentences are shown.", bg=BG, fg=MUTED, font=(FONT, 9), wraplength=740,
                 justify="left").pack(anchor="w", pady=(18, 0))

    def _report_row(self, parent, c):
        outer = tk.Frame(parent, bg=LINE)
        outer.pack(fill="x", pady=3)
        card = tk.Frame(outer, bg=CARD, padx=14, pady=8)
        card.pack(fill="x", padx=1, pady=1)
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        chip = tk.Label(top, bg=CARD, font=(FONT, 9, "bold"), padx=8)
        chip.pack(side="right")
        count = tk.Label(top, bg=CARD, fg=MUTED, font=(FONT, 10), padx=10)
        count.pack(side="right")
        left = tk.Frame(top, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=c["label"], bg=CARD, fg=INK, font=(FONT, 11, "bold")).pack(anchor="w")
        where_lbl = tk.Label(left, bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=560, justify="left")
        where_lbl.pack(anchor="w")

        def show_counts():
            engine.recount(c)
            bg, fg = CHIP[c["rating"]]
            chip.config(text=engine.RATING_LABEL[c["rating"]], bg=bg, fg=fg)
            fine = len(c["items"]) - c["count"]
            count.config(text=str(c["count"]) + (f"  (+{fine} not a problem)" if fine else ""))
            chs = c.get("chapters_list") or []
            where = ", ".join(chs[:8]) + (f" and {len(chs) - 8} more" if len(chs) > 8 else "")
            where_lbl.config(text="Where: " + where if where else "")

        show_counts()
        c["_changed"] = lambda: (show_counts(), self._report_changed(self.report))
        holder = tk.Frame(card, bg=CARD)
        state = {"open": False}
        link = self._link(card, "Show examples", lambda: toggle(), bg=CARD)
        link.pack(anchor="w", pady=(4, 0))

        def toggle():
            state["open"] = not state["open"]
            link.config(text="Hide examples" if state["open"] else "Show examples")
            if not state["open"]:
                holder.pack_forget()
                return
            if not holder.winfo_children():
                self._fill_examples(holder, c)
            holder.pack(fill="x", pady=(6, 0))

    def _fill_examples(self, holder, c, start=0):
        items = c["items"]
        for it in items[start:start + 12]:
            self._example(holder, c, it)
        left = len(items) - start - 12
        if left > 0:
            more = self._link(holder, f"Show more ({left} left)", lambda: None, bg=CARD)
            more.bind("<Button-1>", lambda e: (more.destroy(), self._fill_examples(holder, c, start + 12)))
            more.pack(anchor="w", pady=(8, 0))

    def _example(self, holder, c, it):
        head = tk.Frame(holder, bg=CARD)
        head.pack(fill="x", pady=(6, 0))
        tk.Label(head, text=it["where"] + (f"   · {it['ai']}" if it.get("ai") else ""),
                 bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left")
        mark = self._link(head, "", lambda: flip(), bg=CARD)
        mark.pack(side="right")
        if c.get("lang"):
            text = f"…{it['before']} {it['word']} {it['after']}…"
            hl = [(len(it["before"]) + 2, len(it["before"]) + 2 + len(it["word"]))]
            raw = f"{it['before_raw']} {it['word_raw']} {it['after_raw']}"
        else:
            text, hl = it["text"], it.get("hl") or []
            raw = it.get("raw") or it["text"]
        t = tk.Text(holder, wrap="word", width=20, height=1, font=(FONT, 10), bg="#FBFAF8", fg=INK,
                    relief="flat", padx=8, pady=4, borderwidth=0, highlightthickness=0)
        t.tag_configure("w", background="#F3E3DF", foreground="#8A3B2E", font=(FONT, 10, "bold"))
        t.insert("1.0", text)
        for a, b in hl:
            t.tag_add("w", f"1.0+{a}c", f"1.0+{b}c")
        lines = max(1, min(8, len(text) // 88 + 1 + text.count("\n")))
        t.configure(state="disabled", height=lines)
        t.pack(fill="x")

        def show():
            fine = it.get("fine")
            mark.config(text="✓ Not a problem  ·  Undo" if fine else "Not a problem",
                        fg=MUTED if fine else ACCENT)
            t.configure(fg="#A49E96" if fine else INK)
            t.tag_configure("w", background="#EEEAE4" if fine else "#F3E3DF",
                            foreground="#A49E96" if fine else "#8A3B2E")

        def flip():
            it["fine"] = not it.get("fine")
            engine.learn_marks([(c["kind"], it.get("key"), raw, it["fine"])])
            show()
            c["_changed"]()

        show()

    def _report_changed(self, r):
        """Rewrite the saved report a moment after the last "Not a problem" click."""
        if getattr(self, "_rewrite_job", None):
            self.after_cancel(self._rewrite_job)
        self._rewrite_job = self.after(800, lambda: self._write_report(r))

    def _write_report(self, r):
        if getattr(self, "_rewrite_job", None):
            self.after_cancel(self._rewrite_job)
        self._rewrite_job = None
        try:
            Path(r["report_path"]).write_text(engine.report_html(r), encoding="utf8")
        except OSError:
            pass

    # ---------- sending what you marked ----------
    def send_marks(self, found, mode):
        try:
            path = engine.export_marks(found, mode)
        except Exception as ex:
            messagebox.showerror(APP, f"Couldn't save the file: {ex}")
            return
        try:
            import cleanlisten_learn as learn
        except Exception:
            learn = None
        if learn and learn.send_url() and (chime() or messagebox.askyesno(
                APP, "Send it in now?\n\nIt has the sentences and words CleanRead found and what you "
                "marked, so CleanRead can get better. Not the whole book.")):
            def go():
                try:
                    learn.send(path, "refined")
                    self.q.put(("sent", path, None))
                except Exception as ex:
                    self.q.put(("sent", path, ex))
            threading.Thread(target=go, daemon=True).start()
            return
        self._saved_by_hand(path)

    def _saved_by_hand(self, path, why=""):
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')
        messagebox.showinfo(
            APP, why + f"Saved as “{path.name}” in {path.parent}.\n\n"
            "Send that file to whoever set up CleanRead for you, or attach it in a chat with "
            "Claude and ask for it to be added to CleanRead.\n\nIt has the sentences and words "
            "CleanRead found and what you marked. Not the whole book.")

    def _to_clean(self):
        self.mode.set("clean")
        self.settings["mode"] = "clean"
        self.show_setup()

    # ---------- page 2b: review before saving ----------
    def show_review(self):
        a = self.analysis
        cuts, mutes = a["cuts"], a["mutes"]
        sub = ("Nothing to remove was found in this book." if not cuts and not mutes else
               "Everything ticked below will be taken out. Untick anything you want to keep: "
               "CleanRead remembers it next time.")
        p = self._new_page("Review before saving", sub, name=a.get("title", ""))
        for note in (a.get("ai_note"), a.get("learn_note")):
            if note:
                tk.Label(p, text=note, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=740,
                         justify="left").pack(anchor="w", pady=(0, 4))
        ttk.Button(self.footer, text="Save clean copy", style="Main.TButton",
                   command=self._save_from_review).pack(side="right")
        ttk.Button(self.footer, text="Back", style="Plain.TButton",
                   command=self.show_setup).pack(side="right", padx=(0, 10))
        ttk.Button(self.footer, text="Send what you marked…", style="Plain.TButton",
                   command=self._send_from_review).pack(side="right", padx=(0, 10))
        self.summary_lbl = tk.Label(self.footer, text="", bg=BG, fg=MUTED, font=(FONT, 10))
        self.summary_lbl.pack(side="left")
        body = self._scroll_area(p)

        def section(title, count, var_list):
            head = tk.Frame(body, bg=BG)
            head.pack(fill="x", pady=(10, 4))
            tk.Label(head, text=f"{title}  ({count})", bg=BG, fg=INK, font=(FONT, 13, "bold")).pack(side="left")
            if count > 1:
                links = tk.Frame(head, bg=BG)
                links.pack(side="right")
                for label, val in (("Tick all", True), ("Untick all", False)):
                    self._link(links, label, lambda v=val: ([x.set(v) for x, _ in var_list],
                                                            self._update_summary())).pack(side="left", padx=6)

        self.cut_vars = []
        order = ["sex", "nudity", "implied", "immodest", "ref", "sleeping", "unmarried", "kiss",
                 "kiss_ss", "flirt", "relationship", "violence", "graphic", "gore", "disturbing",
                 "religion", "crude", "bully", "disrespect", "smoking", "drinking", "drugs", "gestures",
                 "holiday", "birthday", "magic", "darkmagic", "vampires"]
        for kind in order:
            items = [c for c in cuts if c["kind"] == kind]
            if not items:
                continue
            group = []
            section(engine.CLEAN_LABELS[kind] + " to cut", len(items), group)
            for c in items:
                card = tk.Frame(body, bg=CARD, padx=14, pady=10, highlightbackground=LINE,
                                highlightthickness=1)
                card.pack(fill="x", pady=4)
                v = tk.BooleanVar(value=c.get("cut", True))
                self.cut_vars.append((v, c))
                group.append((v, c))
                size = (f"{len(c['paras'])} paragraph{'s' if len(c['paras']) != 1 else ''}" if c.get("paras")
                        else f"{len(c['sents'])} sentence{'s' if len(c['sents']) != 1 else ''}")
                top = tk.Frame(card, bg=CARD)
                top.pack(fill="x")
                ttk.Checkbutton(top, text=f"Cut this   ·   {c['where']}   ·   {size}",
                                variable=v, command=self._update_summary).pack(side="left")
                if c.get("ai_note"):
                    soft = c["ai_note"] in ("AI thinks this one is fine", "AI suggests", "You kept this before",
                                           "Kept by families before")
                    tk.Label(top, text=c["ai_note"], bg="#FFF4D6" if soft else "#E3EFEC",
                             fg="#7A5A00" if soft else ACCENT_DK, font=(FONT, 9), padx=6).pack(side="right")
                txt = tk.Text(card, wrap="word", width=20, height=min(7, 2 + len(c["text"]) // 95),
                              font=(FONT, 10), bg="#FBFAF8", fg=INK, relief="flat", padx=8, pady=6,
                              borderwidth=0)
                txt.insert("1.0", c["text"])
                txt.configure(state="disabled")
                txt.pack(fill="x", pady=(6, 0))

        self.mute_vars = []
        if mutes:
            section("Words to mark out", len(mutes), self.mute_vars)
            box = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            box.pack(fill="x", pady=4)
            for n, m in enumerate(mutes):
                row = tk.Frame(box, bg=CARD if n % 2 == 0 else "#FAF8F5", padx=10, pady=3)
                row.pack(fill="x")
                rbg = row.cget("bg")
                v = tk.BooleanVar(value=m.get("on", True))
                self.mute_vars.append((v, m))
                ttk.Checkbutton(row, variable=v, command=self._update_summary).pack(side="left")
                tk.Label(row, text=m["where"], bg=rbg, fg=MUTED, font=(FONT, 9), width=22,
                         anchor="w").pack(side="left")
                show = tk.Label(row, text="Show", bg=rbg, fg=ACCENT, font=(FONT, 9, "underline"),
                                cursor="hand2", padx=6)
                show.pack(side="right")
                if m.get("note"):
                    soft = m["note"].startswith(("AI thinks", "AI suggests", "probably", "You kept"))
                    tk.Label(row, text=m["note"], bg="#FFF4D6" if soft else "#E3EFEC",
                             fg="#7A5A00" if soft else ACCENT_DK, font=(FONT, 8), padx=4).pack(side="right")
                line = tk.Text(row, wrap="word", width=20, height=1, font=(FONT, 10), bg=rbg, fg=MUTED,
                               relief="flat", borderwidth=0, highlightthickness=0, cursor="arrow")
                line.tag_configure("w", background="#F3E3DF", foreground="#8A3B2E", font=(FONT, 10, "bold"))

                def fill(t=line, m=m, revealed=False):
                    before = m["ctx_raw" if revealed else "ctx"]
                    word = m["word_raw" if revealed else "word"]
                    after = m["ctx_after_raw" if revealed else "ctx_after"]
                    t.configure(state="normal")
                    t.delete("1.0", "end")
                    if before:
                        t.insert("end", "…" + before + " ")
                    t.insert("end", f" {word} ", "w")
                    if after:
                        t.insert("end", " " + after + "…")
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
        nc = sum(v.get() for v, _ in getattr(self, "cut_vars", []))
        nm = sum(v.get() for v, _ in getattr(self, "mute_vars", []))
        self.summary_lbl.config(text=f"{nm} word{'s' if nm != 1 else ''} marked out · "
                                     f"{nc} cut{'s' if nc != 1 else ''}")

    def _send_from_review(self):
        """Send the ticks as they are now (nothing is saved or learned yet)."""
        an = dict(self.analysis)
        an["cuts"] = [dict(c, cut=v.get()) for v, c in self.cut_vars]
        an["mutes"] = [dict(m, on=v.get()) for v, m in self.mute_vars]
        self.send_marks(an, "clean")

    def _save_from_review(self):
        # what you ticked or unticked yourself is remembered for next time
        marks = []
        for v, c in self.cut_vars:
            if v.get() != c.get("cut", True):
                marks.append((c["kind"], c.get("key"), c.get("raw") or c["text"], not v.get()))
            c["cut"] = v.get()
        for v, m in self.mute_vars:
            if v.get() != m.get("on", True):
                marks.append(("word", m.get("key"), f"{m['ctx_raw']} {m['word_raw']} {m['ctx_after_raw']}",
                              not v.get()))
            m["on"] = v.get()
        engine.learn_marks(marks)
        cuts = [c for v, c in self.cut_vars if v.get()]
        mutes = [m for v, m in self.mute_vars if v.get()]
        self.show_working("Saving the clean copy…")
        self.cancel_btn.destroy()
        threading.Thread(target=self._write_thread, args=(cuts, mutes), daemon=True).start()

    # ---------- page 3: done ----------
    def show_done(self, res):
        p = self._new_page("All done!", "Your clean copy is ready. The original book wasn't changed.")
        stats = tk.Frame(p, bg=BG)
        stats.pack(fill="x", pady=20)
        for big, small in [(str(res["mutes"]), "words marked out"), (str(res["cut_sents"]), "sentences cut"),
                           (str(res["cut_paras"]), "paragraphs cut")]:
            box = tk.Frame(stats, bg=CARD, padx=24, pady=14, highlightbackground=LINE, highlightthickness=1)
            box.pack(side="left", padx=(0, 12))
            tk.Label(box, text=big, bg=CARD, fg=ACCENT, font=(FONT, 26, "bold")).pack()
            tk.Label(box, text=small, bg=CARD, fg=MUTED, font=(FONT, 10)).pack()
        tk.Label(p, text=f"Saved as:  {os.path.normpath(res['out'])}", bg=BG, fg=INK, font=(FONT, 10),
                 wraplength=740, justify="left").pack(anchor="w", pady=(4, 6))
        tk.Label(p, text="To read it on a Kindle, send the EPUB with Amazon's Send to Kindle (email, app "
                 "or website). Kobo, Apple Books, Google Play Books and most reading apps open EPUB directly.",
                 bg=BG, fg=MUTED, font=(FONT, 9), wraplength=740, justify="left").pack(anchor="w", pady=(0, 16))
        row = tk.Frame(p, bg=BG)
        row.pack(anchor="w")
        ttk.Button(row, text="Clean another book", style="Main.TButton",
                   command=self.reset).pack(side="left")
        ttk.Button(row, text="Show in folder", style="Plain.TButton",
                   command=lambda: show_in_folder(res["out"])).pack(side="left", padx=(14, 0))
        if res.get("report"):
            ttk.Button(row, text="See what was removed", style="Plain.TButton",
                       command=lambda: open_path(res["report"])).pack(side="left", padx=(10, 0))
        if self.analysis:
            an = self.analysis
            self._link(p, "Help CleanRead get better: send what you changed…",
                       lambda: self.send_marks(an, "clean")).pack(anchor="w", pady=(18, 0))

    def reset(self):
        self.book_path, self.book, self.outdir, self.report, self.analysis = None, None, None, None, None
        self.show_setup()


if __name__ == "__main__":
    App().mainloop()
