"""CleanRead — check what's in an ebook before your kids read it, or make a clean copy."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cleanread as engine  # noqa: E402
import filters as F
import logo as LOGO  # noqa: E402  (the filters, shared with CleanListen)
import cvlook as look  # noqa: E402  (the drawn look: cards, switches, pill buttons; CleanView's)
import cllook as CL  # noqa: E402  (the step-by-step start page, shared with CleanListen)
import freezes  # noqa: E402  (noticing a freeze or a crash, shared with CleanListen)


def chime():
    """The Windows "information" sound, so a question is heard like the other boxes
    (a yes/no box is silent on Windows; Jason missed the "Send it in now?" one)."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


APP = "CleanRead"


def app_version():
    try:
        return json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        return "?"
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
SETTINGS = APP_DATA / "cleanread_settings.json"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
# Light and dark (as CleanView 1.18.78; the owner, 2026-11-13: "ask cleann view aabout dark mode
# built. lets move that here also"). Every colour this window uses is a name from cllook.py with a
# value for each look; `use_theme` sets them here (BG, CARD, INK, GO...), so code that builds a
# page always reads the look in use. Never write a colour into a page: name it in cllook.py.
# The one main step on each page is a big green button (GO: the logo's green, ACCENT, the owner,
# 2026-11-09: "i want to stay consistent"); in CleanListen's list a book that is ready keeps a
# brighter green (READY_GREEN), so it looks different from a done one (ACCENT_DK).
THEME = "light"


def use_theme(name):
    """Light or dark: sets every colour name in this module. Pages built after it are in that look."""
    global THEME
    THEME = CL.use_theme(name)
    globals().update(CL.colours())


use_theme("light")          # the saved choice is read when the window opens (App.__init__)
HEAD = CL.HEAD


def chip(rating):
    """A rating chip's (background, words) colours in the look in use."""
    return {"none": CHIP_NONE, "mentioned": CHIP_MENTIONED, "some": CHIP_SOME,
            "a lot": CHIP_LOT}[rating]


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
        self.job = 0              # the check/find being worked on; Cancel moves on (2026-11-09)
        self.paused = False       # Pause on the working page (2026-11-12)
        self.settings = load_settings()
        use_theme(F.load().get("theme"))      # light or dark, before anything is drawn
        self.configure(bg=BG)
        self.book_path = None
        self.book = None          # parsed book, kept while the same file is loaded
        self.mode = tk.StringVar(value=self.settings.get("mode", "check"))
        self.outdir = None
        self.report = None
        self.analysis = None
        self._style()
        self.page = None
        self.show_setup()
        self.after(50, lambda: CL.title_bar(self))
        self.watch = freezes.Watch(self, 'CleanRead', APP_DATA, 'cleanread_')
        self.watch.start()
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
        s.map("Accent.TButton", background=[("active", ACCENT_DK), ("disabled", DISABLED)])
        s.configure("Main.TButton", background=GO, foreground="white",
                    font=(FONT, 15, "bold"), padding=(28, 7), borderwidth=0)
        s.map("Main.TButton", background=[("active", GO_DK), ("disabled", GO_OFF)])
        s.configure("Go.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 11, "bold"), padding=(14, 5), borderwidth=0)
        s.map("Go.TButton", background=[("active", ACCENT_DK), ("disabled", DISABLED)])
        edge = {"bordercolor": BUTTON_EDGE, "lightcolor": GREY, "darkcolor": GREY}
        s.configure("Plain.TButton", background=GREY, foreground=INK, padding=(14, 6),
                    borderwidth=1, font=(FONT, 10), **edge)
        s.map("Plain.TButton", background=[("active", GREY_HOVER)])
        s.configure("Small.TButton", background=GREY, foreground=INK, padding=(8, 1),
                    borderwidth=1, font=(FONT, 9), **edge)
        s.map("Small.TButton", background=[("active", GREY_HOVER)])
        s.configure("Green.Horizontal.TProgressbar", troughcolor=TROUGH,
                    background=ACCENT, bordercolor=TROUGH, lightcolor=ACCENT, darkcolor=ACCENT)
        s.configure("TCombobox", padding=4)
        # the drawn look (the owner, 2026-11-13, as CleanView 1.18.77): rounded buttons, thin scroll
        # bars, a rounded progress bar, soft fields and smooth tick boxes with a real tick
        CL.style(self, s)

    def destroy(self):
        if getattr(self, "watch", None):     # stops the freeze watcher; the crash log is closed
            self.watch.stop()
        super().destroy()

    def _new_page(self, title, subtitle="", name=""):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = title
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        X = self._px
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=X(34), pady=(X(22), X(16)))
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(X(10), 0))
        tk.Frame(self.footer, bg=LINE, height=1).pack(side="top", fill="x", pady=(0, X(12)))
        self.name_lbl = None
        if name:                # which book this is (Jason: "you don't know what you've cleaned")
            self.name_lbl = tk.Label(self.page, text=name, bg=BG, fg=ACCENT, font=(HEAD, 11),
                                     wraplength=760, justify="left")
            self.name_lbl.pack(anchor="w", pady=(0, X(2)))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(HEAD, 21),
                 wraplength=760, justify="left").pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 10),
                     wraplength=740, justify="left").pack(anchor="w", pady=(X(4), X(14)))
        # the version and "Check for updates" on every page, as in CleanListen (Jason,
        # 2026-11-06: "Clean read doesn't have anything on top that says current version")
        self._page_title = title
        self._upd_lbl = tk.Label(self.page, text=f"v{app_version()} \u00b7 Check for updates",
                                 bg=BG, fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        self._upd_lbl.place(relx=1.0, y=2, anchor="ne")
        self._upd_lbl.bind("<Button-1>", lambda e: self.check_updates())
        return self.page

    # ---------- updates (CleanRead is updated with CleanListen, by the launcher) ----------
    def _launcher(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("cr_launcher", str(HERE / "launcher.pyw"))
        spec = importlib.util.spec_from_loader("cr_launcher", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def _busy(self):
        return bool(getattr(self, "pb", None) and self.pb.winfo_exists())

    def check_updates(self):
        if getattr(self, "_updating", False):
            return
        if self._busy():
            messagebox.showinfo(APP, "Let it finish first (or press Cancel), then check for updates.")
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
        threading.Thread(target=work, daemon=True, name="check for updates").start()

    def _update_msg(self, kind, val):
        self._updating = kind == "update_progress"
        lbl = getattr(self, "_upd_lbl", None)
        here = lbl is not None and lbl.winfo_exists()
        if kind == "update_progress" and here:
            lbl.config(text=val)
        elif kind == "update_none" and here:
            lbl.config(text=f"v{val} \u00b7 \u2713 You have the latest version")
        elif kind == "update_fail":
            if here:
                lbl.config(text=f"v{app_version()} \u00b7 Check for updates")
            messagebox.showerror(APP, f"Couldn't update right now ({val[:200]}). Try again in a "
                                 "few minutes.")
        elif kind == "updated":
            if getattr(self, "_page_title", APP) != APP and not messagebox.askyesno(
                    APP, f"CleanRead {val} is ready. It opens again on the first page. "
                    "Open it now?\n\n(Press No to keep working; it's used next time you open "
                    "CleanRead.)"):
                if here:
                    lbl.config(text=f"v{val} is ready \u00b7 opens next time")
                return
            env = dict(os.environ, CLEANLISTEN_UPDATED=f"CleanRead was updated to version {val}.",
                       CLEANLISTEN_UPDATE_DONE="1")
            try:
                subprocess.Popen([sys.executable, str(HERE / "launcher.pyw"), "read"], cwd=str(HERE),
                                 env=env)
            except Exception as ex:
                messagebox.showinfo(APP, f"Updated to {val}. Close CleanRead and open it again to "
                                    f"finish ({ex}).")
                return
            self.destroy()

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
        inner._canvas = canvas
        return inner

    def _px(self, n):
        return look.px(self, n)

    def _scroll_to(self, w):
        """Scroll the page w is on so w can be seen."""
        inner = w                       # the scroll area's own frame (a look.Card is a canvas too)
        while inner is not None and getattr(inner, "_canvas", None) is None:
            inner = inner.master
        if inner is None:
            return
        self.update_idletasks()
        h = inner.winfo_height()
        if h > 0:
            inner._canvas.yview_moveto(max(0.0, (w.winfo_rooty() - inner.winfo_rooty() - 120) / h))

    def _note(self, parent, text, bg=None):
        tk.Label(parent, text=text, bg=bg or CARD, fg=MUTED, font=(FONT, 9), wraplength=640,
                 justify="left").pack(anchor="w", padx=(22, 0))

    def _link(self, parent, text, cmd, bg=None):
        l = tk.Label(parent, text=text, bg=bg or BG, fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        l.bind("<Button-1>", lambda e: cmd())
        return l

    # ---------- page 1: choose a book and what to do, one step at a time ----------
    # The owner, 2026-11-13 (CleanView 1.18.77's "B, step by step"): the steps down the left, each
    # saying what's chosen, one step on the right, Back / Next, and the green button always there.
    def _steps(self):
        first = [("Ebook", "Choose the book. The original is never changed."),
                 ("What to do", "Check what's in a book before your kids read it, or make a clean "
                                "copy with the language and content you don't want taken out.")]
        if self.mode.get() == "check":
            return first + [("AI helper", "It reads for what word lists can't spot. Optional.")]
        return first + [("What to take out", "Bad words are marked out; everything else is listed "
                                             "for you to check before anything is cut."),
                        ("Options", "How the clean copy looks, and the AI helper."),
                        ("Save to", "Where the clean copy goes.")]

    def _theme_var(self):
        self.theme_var = tk.StringVar(value=THEME)
        return self.theme_var

    def _step_summary(self, n):
        """What's chosen in step n, in a few words, for the list on the left."""
        check = self.mode.get() == "check"
        if n == 1:
            return Path(self.book_path).name if self.book_path else "No book chosen yet"
        if n == 2:
            return "Check the content" if check else "Make a clean copy"
        ai = getattr(self, "ai_var", None)
        ai = "AI helper on" if ai is not None and ai.get() else "AI helper off"
        if check:
            return ai
        if n == 3:
            card = getattr(self, "filter_card", None)
            return dict(F.PROFILES).get(card.profile.get(), "") if card else ""
        if n == 4:
            return ai
        if self.outdir:
            return Path(self.outdir).name or str(self.outdir)
        return "Next to the book"

    def show_setup(self, step=1):
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_win.destroy()
        if getattr(self, "watch", None):
            self.watch.doing["page"] = APP
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        X = self._px
        p = self.page = tk.Frame(self, bg=BG)
        p.pack(fill="both", expand=True)
        self.name_lbl = None
        self._page_title = APP
        try:
            ver = json.loads((HERE / "version.json").read_text())["version"]
            self.title(f"{APP} {ver}")
        except Exception:
            pass
        st = self.settings
        check = self.mode.get() == "check"
        sp = self.steps_page = CL.StepPage(
            self, p, APP, LOGO.logo_png("cleanread.ico", X(40))[0], self._steps(),
            self._step_summary, ("Start checking" if check else "Start cleaning", self.start),
            links=[(f"v{app_version()} \u00b7 Check for updates", self.check_updates, "refresh")],
            done=lambda i: i == 1 and bool(self.book_path), scroll_area=self._scroll_area,
            start=step, theme=(self._theme_var(), self._set_theme))
        self.footer = sp.nav
        self.start_btn = sp.main_btn
        self.start_btn.config(state="disabled")
        self._upd_lbl = next(iter(sp.links.values())).label
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(sp.top, text="\u2713 " + upd, bg=TINT, fg=ACCENT_DK, font=(FONT, 10),
                     padx=X(12), pady=X(7), anchor="w").pack(fill="x", pady=(0, X(12)))

        # ----- step 1: the book
        drop = look.Card(sp.pane(1), fill=SOFT, edge=SOFT_EDGE, radius=16, pad=(20, 18))
        drop.pack(fill="x", padx=(0, X(4)))
        look.Badge(drop.body, "folder", size=54, icon_size=20).pack(side="left")
        words = tk.Frame(drop.body, bg=SOFT)
        words.pack(side="left", fill="x", expand=True, padx=(X(16), X(12)))
        tk.Label(words, text="Choose an ebook", bg=SOFT, fg=INK, font=(HEAD, 13),
                 anchor="w").pack(anchor="w")
        tk.Label(words, text="EPUB, PDF or TXT \u2014 not copy-protected.", bg=SOFT, fg=MUTED,
                 font=(FONT, 9), anchor="w", wraplength=X(260), justify="left").pack(
                     anchor="w", pady=(X(2), 0))
        self.choose_btn = look.Pill(drop.body, "Choose ebook\u2026", self.pick_book, size=12,
                                    pad=(22, 11))
        self.choose_btn.pack(side="right")
        self.book_lbl = tk.Label(sp.pane(1), text="No book chosen yet", bg=BG, fg=MUTED,
                                 font=(FONT, 10), wraplength=X(560), justify="left", anchor="w")
        self.book_lbl.pack(anchor="w", pady=(X(12), 0))

        # ----- step 2: check it, or make a clean copy
        mv = tk.StringVar(value=self.mode.get())

        def chosen(*_):
            if mv.get() != self.mode.get():
                self.mode.set(mv.get())
                self.after_idle(self._mode_changed)
        mv.trace_add("write", chosen)
        choices = tk.Frame(sp.pane(2), bg=BG)
        choices.pack(fill="x")
        for c in range(2):
            choices.columnconfigure(c, weight=1, uniform="mode")
        for n, (val, head, sub, icon) in enumerate((
                ("check", "Check the content",
                 "Reads the whole book and makes a report for parents: witches, dark magic, "
                 "vampires, bullying, disrespect toward parents, romance, language and more, with "
                 "the actual sentences and where they are.", "info"),
                ("clean", "Make a clean copy",
                 "Marks out bad words and cuts the content you choose, using the same filters as "
                 "CleanListen and CleanView. You see everything before it's saved.", "spark"))):
            card = look.OptionCard(choices, val, mv, head, sub, icon=icon)
            card.sub.config(wraplength=X(210))
            card.grid(row=0, column=n, sticky="nsew", padx=(0, X(10)), pady=(0, X(10)))
        self._mode_var = mv

        self._built_mode = self.mode.get()
        if check:
            # ----- step 3 (checking): the AI helper
            self.ai_var = tk.BooleanVar(value=st.get("check_ai", False))
            CL.switch_row(sp.card(3), self.ai_var,
                          "AI helper  (reads for what word lists can't spot)",
                          "Catches things like a child sneaking around or mocking their parents "
                          "when no warning words are used. Runs on your PC. Without it the check "
                          "takes under a minute; with it, the check takes longer (20\u201360 minutes "
                          "for a novel).", command=sp.refresh).pack(fill="x")
        else:
            # ----- step 3 (a clean copy): the same filters as CleanListen and CleanView
            self.filter_card = F.FilterPanel(sp.pane(3), on_change=sp.refresh, wrap=560,
                                             scroll_to=self._scroll_to)
            # ----- step 4: how it looks, and the AI helper
            b = sp.card(4)
            row = tk.Frame(b, bg=CARD)
            row.pack(anchor="w", fill="x")
            tk.Label(row, text="How marked-out words look", bg=CARD, fg=INK,
                     font=(HEAD, 10)).pack(side="left")
            self.style_box = ttk.Combobox(row, state="readonly", width=30,
                                          values=[label for _, label in STYLE])
            self.style_box.current([k for k, _ in STYLE].index(st.get("style", "dash")))
            self.style_box.pack(side="left", padx=(X(12), 0))
            self.marker_var = tk.BooleanVar(value=st.get("marker", True))
            CL.switch_row(sp.card(4, top=12), self.marker_var,
                          "Show [\u2026] where something was cut",
                          "So a jump in the story makes sense.").pack(fill="x")
            self.ai_var = tk.BooleanVar(value=st.get("clean_ai", True))
            CL.switch_row(sp.card(4, top=12), self.ai_var,
                          "AI helper  (double-checks every filter)",
                          "Catches what the word lists missed and unticks anything flagged by "
                          "mistake. Runs on your PC. The check takes longer with it on "
                          "(20\u201360 minutes for a novel).", command=sp.refresh).pack(fill="x")
            # ----- step 5: where the clean copy goes
            b = sp.card(5)
            row = tk.Frame(b, bg=CARD)
            row.pack(fill="x")
            look.Pill(row, "Change\u2026", self.pick_out, kind="secondary", size=10,
                      pad=(16, 8)).pack(side="right")
            self.out_lbl = tk.Label(row, text="Next to the original book", bg=CARD, fg=MUTED,
                                    font=(FONT, 10), wraplength=X(400), justify="left")
            self.out_lbl.pack(side="left")
            tk.Label(sp.pane(5), text="The original is never changed. EPUB books stay EPUB (with "
                     "\u201c(Clean)\u201d added to the title); a PDF comes out as a plain EPUB; a TXT "
                     "stays TXT.", bg=BG, fg=FAINT, font=(FONT, 9), wraplength=X(560),
                     justify="left").pack(anchor="w", pady=(X(14), 0))
        self._refresh()
        sp.go(step)

    def _mode_changed(self):
        self._save_opts()
        self.show_setup(step=2)

    def _keep_for_rebuild(self):
        self._save_opts()

    # ---------- light or dark ----------
    def _set_theme(self, name=None):
        """Light or dark, from the choice under the steps: the start page is built again in that
        look, keeping what's chosen and the step. Kept for next time, for CleanListen and CleanRead."""
        name = "dark" if (name or self.theme_var.get()) == "dark" else "light"
        if name == THEME:
            return
        self._keep_for_rebuild()
        d = F.load()
        d["theme"] = name
        F.save(d)
        use_theme(name)
        self.configure(bg=BG)
        self._style()                       # the ttk styles and tick boxes in that look
        CL.title_bar(self)
        self.show_setup(step=getattr(getattr(self, "steps_page", None), "now", 1))


    def _refresh(self):
        if self.book_path:
            self.book_lbl.config(text=Path(self.book_path).name, fg=INK)
            self.start_btn.config(state="normal")
        # the same words as CleanView and CleanListen (Jason, 2026-11-06: "The other 2 say
        # start cleaning"); checking only makes a report, so it says that
        self.start_btn.config(text="Start checking" if self.mode.get() == "check" else "Start cleaning")
        if self.mode.get() == "clean" and getattr(self, "out_lbl", None) and self.out_lbl.winfo_exists():
            if self.outdir:
                self.out_lbl.config(text=os.path.normpath(self.outdir), fg=INK)
            elif self.book_path:
                self.out_lbl.config(text=os.path.normpath(str(Path(self.book_path).parent)), fg=INK)
        sp = getattr(self, "steps_page", None)
        if sp is not None:
            sp.refresh()

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
            threading.Thread(target=self._scan_thread, args=(self.job, self.book_path, self.ai_var.get()),
                             daemon=True).start()
            return
        ticks, mywords = self.filter_card.ticks(), self.filter_card.mywords()
        if not F.anything_on(ticks) and not mywords:
            messagebox.showinfo(APP, "Tick at least one thing to take out (under \u201cWhat to take "
                                "out\u201d).")
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
        threading.Thread(target=self._analyze_thread, args=(self.job, self.book_path, opts),
                         daemon=True).start()

    def _book_name(self):
        if self.book is not None and str(self.book.path) == str(Path(self.book_path or "")):
            return self.book.title
        return Path(self.book_path).stem if self.book_path else ""

    def show_working(self, title, sub=""):
        p = self._new_page(title, sub, name=self._book_name())
        card = look.Card(p, radius=14, pad=(24, 22))
        card.pack(fill="x", pady=self._px(26))
        box = card.body
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000, length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=CARD, fg=INK, font=(FONT, 11))
        self.status.pack(anchor="w", pady=(self._px(12), 0))
        self.job += 1
        self.paused = False
        self.cancel_btn = ttk.Button(self.footer, text="Cancel", style="Plain.TButton", command=self.cancel)
        self.cancel_btn.pack(side="right")
        # Pause beside Cancel (the owner, 2026-11-12, as CleanView 1.18.66: "should we have a pause
        # buton next to the cancel button when a check is happening", "yes build it")
        self.pause_btn = ttk.Button(self.footer, text="Pause", style="Plain.TButton",
                                    command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=(0, 10))
        LOGO.put_logo(p, "cleanread.ico", BG)     # the empty space (Jason, 2026-11-07)

    def toggle_pause(self):
        """Pause or carry on. The check waits at its next step (a question the AI is already
        answering is finished first), and the PC may sleep meanwhile."""
        self.paused = not self.paused
        if getattr(self, "pause_btn", None) and self.pause_btn.winfo_exists():
            self.pause_btn.config(text="Resume" if self.paused else "Pause")
        if getattr(self, "status", None) and self.status.winfo_exists():
            self.status.config(text="Paused \u2014 press Resume to carry on." if self.paused
                               else getattr(self, "_last_status", "Carrying on\u2026"))

    def _stop_or_wait(self, job):
        """The work's "stop?" question: True once this check was cancelled; while paused, it
        waits here, letting the PC sleep."""
        if self.paused and self.job == job:
            nap = freezes.awake()
            nap.__exit__(None, None, None)          # the PC may sleep while paused
            try:
                while self.paused and self.job == job:
                    time.sleep(0.2)
            finally:
                nap.__enter__()
        return self.job != job

    def cancel(self):
        """Back to the start page at once (the owner, 2026-11-09: it took a while). The work
        stops by itself at its next step; what it was doing (opening the book, waiting for the
        AI) can't be cut short, but nothing it sends after this is used."""
        self.paused = False
        self.job += 1
        self.show_setup()

    def _send(self, job, msg):
        """A message from job number `job`; _handle drops it if that job was cancelled."""
        self.q.put(("for_job", job, msg))

    def _load_book(self, job, path):
        book = self.book
        if book is None or str(book.path) != str(Path(path)):
            self._send(job, ("progress", 0.01, "Opening the book…"))
            book = engine.Book(path)
            self._send(job, ("loaded", book))     # kept as self.book only if not cancelled
        return book

    def _prog(self, f, m):
        self.q.put(("progress", f, m))

    def _scan_thread(self, job, path, use_ai):
        with freezes.awake():      # the PC doesn't go to sleep meanwhile (2026-11-09)
            self._scan(job, path, use_ai)

    def _scan(self, job, path, use_ai):
        send = lambda msg: self._send(job, msg)   # noqa: E731
        try:
            book = self._load_book(job, path)
            res = engine.scan(book, use_ai=use_ai, progress=lambda f, m: send(("progress", f, m)),
                              cancel=lambda: self._stop_or_wait(job))
            html = engine.report_html(res)
            rpath = Path(path).with_name(Path(path).stem + " - Content Report.html")
            try:
                rpath.write_text(html, encoding="utf8")
            except OSError:
                rpath = APP_DATA / "reports" / rpath.name
                rpath.parent.mkdir(parents=True, exist_ok=True)
                rpath.write_text(html, encoding="utf8")
            res["report_path"] = str(rpath)
            send(("scanned", res))
        except KeyboardInterrupt:
            pass                    # cancelled: the start page is already showing
        except engine.BookError as ex:
            send(("error", str(ex), ""))
        except Exception as ex:
            send(("error", str(ex), traceback.format_exc()))

    def _analyze_thread(self, job, path, opts):
        with freezes.awake():      # the PC doesn't go to sleep meanwhile (2026-11-09)
            self._analyze(job, path, opts)

    def _analyze(self, job, path, opts):
        send = lambda msg: self._send(job, msg)   # noqa: E731
        try:
            book = self._load_book(job, path)
            an = engine.analyze(book, opts, progress=lambda f, m: send(("progress", f, m)),
                                cancel=lambda: self._stop_or_wait(job))
            send(("analyzed", an))
        except KeyboardInterrupt:
            pass                    # cancelled: the start page is already showing
        except engine.BookError as ex:
            send(("error", str(ex), ""))
        except Exception as ex:
            send(("error", str(ex), traceback.format_exc()))

    def _write_thread(self, cuts, mutes):
        with freezes.awake():      # the PC doesn't go to sleep meanwhile (2026-11-09)
            self._write(cuts, mutes)

    def _write(self, cuts, mutes):
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
        """From now on freezes.drain runs the queue: a flood of messages can't keep the window
        busy, and one bad message can't stop it updating (Jason, 2026-11-03)."""
        freezes.drain(self, self.q, self._handle, self._poll_error, self.watch)

    def _poll_error(self, details):
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            (APP_DATA / "cleanread_last_error.txt").write_text(details, encoding="utf8")
        except OSError:
            pass

    def _handle(self, msg):
        kind = msg[0]
        if kind == "for_job":       # from a check or find: dropped if it was cancelled
            if msg[1] != self.job:
                return
            msg = msg[2]
            kind = msg[0]
            if kind == "loaded":
                self.book = msg[1]
                msg, kind = ("named", msg[1].title), "named"
        if kind in ("update_none", "update_fail", "update_progress", "updated"):
            self._update_msg(kind, msg[1])
            return
        if kind == "progress" and getattr(self, "pb", None) and self.pb.winfo_exists():
            self.pb["value"] = int(msg[1] * 1000)
            self._last_status = msg[2]
            if not self.paused:             # "Paused" stays until Resume
                self.status.config(text=msg[2])
        elif kind == "named" and getattr(self, "name_lbl", None) and self.name_lbl.winfo_exists():
            self.name_lbl.config(text=msg[1])
        elif kind == "chat_reply":
            self._chat_reply(*msg[1:])
        elif kind == "scanned":
            self.report = msg[1]
            self.show_report()
        elif kind == "analyzed":
            self.analysis = msg[1]
            self.show_review()
        elif kind == "written":
            self.show_done(msg[1])
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

    # ---------- page 2a: the content report ----------
    def show_report(self, keep_place=False):
        r = self.report
        place = self._canvas.yview()[0] if keep_place and getattr(self, "_canvas", None) else 0
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
        if r["cats"] or any(c["items"] for c in r["lang"].values()):
            ttk.Button(self.footer, text=f"Ask {self._ai_name()}…", style="Plain.TButton",
                       command=lambda: self.open_chat("check")).pack(side="left", padx=(10, 0))
        body = self._scroll_area(p)
        tip = tk.Frame(body, bg=TINT, padx=12, pady=8)
        tip.pack(fill="x", pady=(0, 8))
        # Jason, 2026-11-03: "It says send what you marked. But I can't mark anything" - say
        # where the button is
        tk.Label(tip, text="Something here isn't a problem? Click “Show examples” under it, then the "
                 "“Not a problem” button beside a sentence (or “None of these are a problem”). Or "
                 f"press “Ask {self._ai_name()}” beside it (or at the bottom) and tell it in your own words. What "
                 "you mark is left out of the report, and CleanRead remembers it next time. When "
                 "you're done, click “Send what you marked” so CleanRead can get better.",
                 bg=TINT, fg=ACCENT_DK, font=(FONT, 10), wraplength=720,
                 justify="left").pack(anchor="w")
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
        if place:
            self.update_idletasks()
            self._canvas.yview_moveto(place)

    def _report_row(self, parent, c):
        outer = CL.card(parent, pad=(14, 8))          # rounded (the new look, 2026-11-13)
        outer.pack(fill="x", pady=3)
        card = outer.body
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
            bg, fg = chip(c["rating"])
            chip.config(text=engine.RATING_LABEL[c["rating"]], bg=bg, fg=fg)
            fine = len(c["items"]) - c["count"]
            count.config(text=str(c["count"]) + (f"  (+{fine} not a problem)" if fine else ""))
            chs = c.get("chapters_list") or []
            where = ", ".join(chs[:8]) + (f" and {len(chs) - 8} more" if len(chs) > 8 else "")
            where_lbl.config(text="Found in: " + where if where else "")

        show_counts()
        c["_changed"] = lambda: (show_counts(), self._report_changed(self.report))
        holder = tk.Frame(card, bg=CARD)
        state = {"open": False}
        links = tk.Frame(card, bg=CARD)
        links.pack(anchor="w", pady=(4, 0))
        link = self._link(links, "Show examples", lambda: toggle(), bg=CARD)
        link.pack(side="left")
        self._link(links, f"Ask {self._ai_name()} about these", bg=CARD,
                   cmd=lambda: self.open_chat("check", ("heading", c))).pack(side="left", padx=(16, 0))

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
        if start == 0:
            c["_shows"] = []
            if len(items) > 1:
                def all_fine():
                    on = not all(it.get("fine") for it in items)
                    marks = []
                    for it in items:
                        if bool(it.get("fine")) != on:
                            it["fine"] = on
                            marks.append((c["kind"], it.get("key"), self._item_raw(c, it), on))
                    engine.learn_marks(marks)
                    for show in c["_shows"]:
                        show()
                    every.config(text=self._all_fine_text(items))
                    c["_changed"]()
                every = ttk.Button(holder, text=self._all_fine_text(items), style="Small.TButton",
                                   command=all_fine)
                every.pack(anchor="w", pady=(2, 2))
        for it in items[start:start + 12]:
            self._example(holder, c, it)
        left = len(items) - start - 12
        if left > 0:
            more = self._link(holder, f"Show more ({left} left)", lambda: None, bg=CARD)
            more.bind("<Button-1>", lambda e: (more.destroy(), self._fill_examples(holder, c, start + 12)))
            more.pack(anchor="w", pady=(8, 0))

    @staticmethod
    def _all_fine_text(items):
        return ("\u2713 None of these are a problem  ·  Undo" if all(it.get("fine") for it in items)
                else "None of these are a problem")

    @staticmethod
    def _item_raw(c, it):
        if c.get("lang"):
            return f"{it['before_raw']} {it['word_raw']} {it['after_raw']}"
        return it.get("raw") or it["text"]

    def _example(self, holder, c, it):
        head = tk.Frame(holder, bg=CARD)
        head.pack(fill="x", pady=(8, 0))
        # a real button on the left, where it's seen (Jason couldn't find the old link at the right)
        mark = ttk.Button(head, text="", style="Small.TButton", command=lambda: flip())
        mark.pack(side="left")
        self._link(head, f"Ask {self._ai_name()}", bg=CARD,
                   cmd=lambda: self.open_chat("check", ("finding", c, it))).pack(side="left", padx=(8, 0))
        tk.Label(head, text=it["where"] + (f"   · {it['ai']}" if it.get("ai") else ""),
                 bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left", padx=(8, 0))
        raw = self._item_raw(c, it)
        if c.get("lang"):
            text = f"…{it['before']} {it['word']} {it['after']}…"
            hl = [(len(it["before"]) + 2, len(it["before"]) + 2 + len(it["word"]))]
        else:
            text, hl = it["text"], it.get("hl") or []
        t = tk.Text(holder, wrap="word", width=20, height=1, font=(FONT, 10), bg=QUOTE, fg=INK,
                    relief="flat", padx=8, pady=4, borderwidth=0, highlightthickness=0)
        t.tag_configure("w", background=WORD_BG, foreground=WORD_INK, font=(FONT, 10, "bold"))
        t.insert("1.0", text)
        for a, b in hl:
            t.tag_add("w", f"1.0+{a}c", f"1.0+{b}c")
        lines = max(1, min(8, len(text) // 88 + 1 + text.count("\n")))
        t.configure(state="disabled", height=lines)
        t.pack(fill="x")

        def show():
            fine = it.get("fine")
            if not mark.winfo_exists():
                return
            mark.config(text="✓ Not a problem  ·  Undo" if fine else "Not a problem")
            t.configure(fg=FINE_INK if fine else INK)
            t.tag_configure("w", background=FINE_BG if fine else WORD_BG,
                            foreground=FINE_INK if fine else WORD_INK)

        def flip():
            it["fine"] = not it.get("fine")
            engine.learn_marks([(c["kind"], it.get("key"), raw, it["fine"])])
            show()
            c["_changed"]()

        c.setdefault("_shows", []).append(show)
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
    def show_review(self, keep_place=False):
        a = self.analysis
        place = self._canvas.yview()[0] if keep_place and getattr(self, "_canvas", None) else 0
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
        if cuts or mutes:
            ttk.Button(self.footer, text=f"Ask {self._ai_name()}…", style="Plain.TButton",
                       command=self.open_chat).pack(side="right", padx=(0, 10))
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
                 "kiss_ss", "flirt", "relationship", "violence", "graphic", "gore", "disturbing", "medical",
                 "religion", "crude", "bully", "disrespect", "smoking", "drinking", "drugs", "gestures",
                 "holiday", "birthday", "magic", "darkmagic", "vampires"]
        for c in cuts:          # what was found, so what you change yourself is remembered
            c.setdefault("cut0", c.get("cut", True))
        for m in mutes:
            m.setdefault("on0", m.get("on", True))
        for kind in order:
            items = [c for c in cuts if c["kind"] == kind]
            if not items:
                continue
            group = []
            section(engine.CLEAN_LABELS[kind] + " to cut", len(items), group)
            for c in items:
                rc = CL.card(body)
                rc.pack(fill="x", pady=4)
                card = rc.body
                v = tk.BooleanVar(value=c.get("cut", True))
                self.cut_vars.append((v, c))
                group.append((v, c))
                size = (f"{len(c['paras'])} paragraph{'s' if len(c['paras']) != 1 else ''}" if c.get("paras")
                        else "part of a sentence" if c.get("part")
                        else f"{len(c['sents'])} sentence{'s' if len(c['sents']) != 1 else ''}")
                top = tk.Frame(card, bg=CARD)
                top.pack(fill="x")
                ttk.Checkbutton(top, text=f"Cut this   ·   {c['where']}   ·   {size}",
                                variable=v, command=self._update_summary).pack(side="left")
                self._link(top, f"Ask {self._ai_name()}", bg=CARD,
                           cmd=lambda c=c: self.open_chat("clean", ("cut", c))).pack(side="right", padx=(8, 0))
                if c.get("ai_note"):
                    soft = c["ai_note"] in ("AI thinks this one is fine", "AI suggests", "You kept this before",
                                           "Kept by families before", "Kept by chat")
                    tk.Label(top, text=c["ai_note"], bg=YELLOW if soft else TINT,
                             fg=YELLOW_INK if soft else ACCENT_DK, font=(FONT, 9), padx=6).pack(side="right")
                shown = len(c["text"]) + len(c.get("before", "")) + len(c.get("after", ""))
                txt = tk.Text(card, wrap="word", width=20, height=min(7, 2 + shown // 95),
                              font=(FONT, 10), bg=QUOTE, fg=INK, relief="flat", padx=8, pady=6,
                              borderwidth=0)
                if c.get("part"):       # the rest of the sentence stays: grey, the cut part in red
                    txt.tag_configure("keep", foreground=MUTED)
                    txt.tag_configure("cut", background=WORD_BG, foreground=WORD_INK)
                    def gap(s):         # no space before a comma or full stop
                        return "" if not s or s[0] in ",.;:!?…”’)" else " "
                    before, after = c.get("before", ""), c.get("after", "")
                    txt.insert("1.0", before + (gap(c["text"]) if before else ""), "keep")
                    txt.insert("end", c["text"], "cut")
                    txt.insert("end", gap(after) + after, "keep")
                else:
                    txt.insert("1.0", c["text"])
                txt.configure(state="disabled")
                txt.pack(fill="x", pady=(6, 0))

        self.mute_vars = []
        if mutes:
            section("Words to mark out", len(mutes), self.mute_vars)
            rc = CL.card(body, pad=(8, 8))
            rc.pack(fill="x", pady=4)
            box = rc.body
            for n, m in enumerate(mutes):
                row = tk.Frame(box, bg=CARD if n % 2 == 0 else SHADE, padx=10, pady=3)
                row.pack(fill="x")
                rbg = row.cget("bg")
                v = tk.BooleanVar(value=m.get("on", True))
                self.mute_vars.append((v, m))
                ttk.Checkbutton(row, variable=v, command=self._update_summary).pack(side="left")
                # wraps: "Chapter One · 10% of the way through the book" was cut off at 22 letters
                tk.Label(row, text=m["where"], bg=rbg, fg=MUTED, font=(FONT, 9), width=24,
                         wraplength=170, justify="left", anchor="w").pack(side="left")
                ask = self._link(row, "Ask", bg=rbg, cmd=lambda m=m: self.open_chat("clean", ("word", m)))
                ask.config(padx=4)
                ask.pack(side="right")
                show = tk.Label(row, text="Show", bg=rbg, fg=ACCENT, font=(FONT, 9, "underline"),
                                cursor="hand2", padx=6)
                show.pack(side="right")
                if m.get("note"):
                    soft = m["note"].startswith(("AI thinks", "AI suggests", "probably", "You kept"))
                    tk.Label(row, text=m["note"], bg=YELLOW if soft else TINT,
                             fg=YELLOW_INK if soft else ACCENT_DK, font=(FONT, 8), padx=4).pack(side="right")
                line = tk.Text(row, wrap="word", width=20, height=1, font=(FONT, 10), bg=rbg, fg=MUTED,
                               relief="flat", borderwidth=0, highlightthickness=0, cursor="arrow")
                line.tag_configure("w", background=WORD_BG, foreground=WORD_INK, font=(FONT, 10, "bold"))

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
        if place:
            self.update_idletasks()
            self._canvas.yview_moveto(place)

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
            if v.get() != c.get("cut0", c.get("cut", True)):
                marks.append((c["kind"], c.get("key"), c.get("raw") or c["text"], not v.get()))
            c["cut"] = v.get()
        for v, m in self.mute_vars:
            if v.get() != m.get("on0", m.get("on", True)):
                marks.append(("word", m.get("key"), f"{m['ctx_raw']} {m['word_raw']} {m['ctx_after_raw']}",
                              not v.get()))
            m["on"] = v.get()
        engine.learn_marks(marks)
        cuts = [c for v, c in self.cut_vars if v.get()]
        mutes = [m for v, m in self.mute_vars if v.get()]
        self.show_working("Saving the clean copy…")
        self.cancel_btn.destroy()
        self.pause_btn.destroy()          # quick, and nothing to stop it at
        threading.Thread(target=self._write_thread, args=(cuts, mutes), daemon=True).start()

    # ---------- ask Claude about the cuts (Jason, 2026-11-03: "like the view one") ----------
    def _ai_name(self):
        try:
            import cleanlisten_claude as cc
            return cc.name(cc.saved_provider())
        except Exception:
            return "Claude"

    def _sync_ticks(self):
        for v, c in getattr(self, "cut_vars", []):
            c["cut"] = v.get()
        for v, m in getattr(self, "mute_vars", []):
            m["on"] = v.get()

    def open_chat(self, mode="clean", about=None):
        """mode "clean": the review page's cuts; "check": the book-check page's findings.
        about: one item the next message is about (the "Ask Claude" link beside it)."""
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_win.lift()
            if about:
                self._ask_about(about)
            return
        try:
            import cleanlisten_claude as cc
        except Exception:
            messagebox.showerror(APP, "The Claude files are missing. Open CleanListen once so it can "
                                 "update, then try again.")
            return
        cc.use(cc.saved_provider())
        N = cc.name()
        if cc.status() != "ok":
            messagebox.showinfo(APP, f"{N} isn't set up on this computer yet.\n\nOpen CleanListen and "
                                f"press “Sign in to {N}” once, then come back here.")
            return
        self._sync_ticks()
        data = self.report if mode == "check" else self.analysis
        if getattr(self, "chat", None) is None or self.chat.an is not data:
            try:
                if self.book is None:
                    self.book = engine.Book(self.book_path)
                self.chat = (engine.CheckChat if mode == "check" else engine.Chat)(
                    self.book, data, APP_DATA / "cleanread_chat")
            except Exception as ex:
                messagebox.showerror(APP, f"Couldn't open the chat ({ex}).")
                return
        w = tk.Toplevel(self)
        self.chat_win = w
        w.title(f"Ask {N} about this book")
        w.configure(bg=BG)
        try:
            w.iconbitmap(str(HERE / "cleanread.ico"))
        except Exception:
            pass
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        w.geometry(f"{int(600 * scale)}x{int(620 * scale)}")
        tk.Label(w, text=f"Ask {N}", bg=BG, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(w, text=(f"{N} reads the whole book and everything CleanRead found. Tell it what "
                          "isn't a problem (“the flying is a dream, not magic”, “angels are fine”). It "
                          "marks those right away, and it remembers what you tell it for next time."
                          if mode == "check" else
                          f"{N} reads the whole book and everything CleanRead plans to take out. Tell it "
                          "what's fine and what isn't (“drinking at dinner is fine”, “just cut the part "
                          "about the gun”). It changes your list right away, and it remembers what you "
                          "tell it for next time."), bg=BG, fg=MUTED, font=(FONT, 9),
                 wraplength=int(560 * scale), justify="left").pack(anchor="w", padx=16)
        bottom = tk.Frame(w, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=16, pady=(6, 12))
        quick = tk.Frame(bottom, bg=BG)
        quick.pack(fill="x", pady=(0, 6))
        self.chat_undo = ttk.Button(quick, text="Undo the last change", style="Plain.TButton",
                                    command=self._undo_chat)
        self.chat_log = tk.Text(w, wrap="word", font=(FONT, 10), bg=CARD, fg=INK, relief="flat",
                                padx=10, pady=8, height=10, width=20)
        self.chat_log.tag_configure("me", foreground=ACCENT_DK, font=(FONT, 10, "bold"))
        self.chat_log.tag_configure("them", foreground=INK)
        self.chat_log.tag_configure("info", foreground=MUTED, font=(FONT, 9, "italic"))
        self.chat_log.pack(fill="both", expand=True, padx=16, pady=8)
        self.chat_log.configure(state="disabled")
        row = tk.Frame(bottom, bg=BG)
        row.pack(fill="x")
        self.chat_entry = tk.Text(row, height=3, wrap="word", font=(FONT, 10), width=20,
                                  bg=CARD, fg=INK, insertbackground=INK, highlightcolor=ACCENT,
                                  relief="flat", highlightthickness=1, highlightbackground=LINE)
        self.chat_entry.pack(side="left", fill="x", expand=True)
        self.chat_send = ttk.Button(row, text="Send", style="Go.TButton", command=lambda: self._chat_send())
        self.chat_send.pack(side="left", padx=(8, 0))
        self.chat_entry.bind("<Return>", lambda e: (self._chat_send(), "break")[1])
        quick_asks = ((("What isn't really a problem?", "Look over every finding in context. Which "
                        "ones aren't really a problem? Mark those not a problem."),) if mode == "check" else
                      (("Anything cut that's fine?", "Look over every cut and word in context. Is "
                        "anything ticked that isn't really a problem under my filters? Untick those."),
                       ("Did it miss anything?", "Read through the whole book. Did CleanRead miss "
                        "anything my filters should take out?")))
        for label, q in quick_asks:
            ttk.Button(quick, text=label, style="Plain.TButton",
                       command=lambda q=q: self._chat_send(q)).pack(side="left", padx=(0, 8))
        for who, text in data.get("chat_history", []):
            self._chat_say(who, text)
        self._chat_say("info", f"Tip: {N} looks over the whole book every time you ask, so answers "
                               "can take a minute or two.")
        self.chat_entry.focus_set()
        if about:
            self._ask_about(about)

    def _ask_about(self, about):
        """The next message is about this one (Jason: "ask claude under each line"): the chat is
        told which it is, so they only type the question."""
        kind, *rest = about
        if kind == "finding":
            c, it = rest
            n = next((k for k, (_, _, x) in enumerate(self.chat.items, 1) if x is it), None)
            raw = " ".join(self.chat._raw(it).split())
            shown, said = (raw, f"this finding on my list (F{n}), under “{c['label']}”, {it.get('where', '')}: "
                                f"\"{raw}\"")
        elif kind == "heading":
            c = rest[0]
            ns = [f"F{k}" for k, (_, _, x) in enumerate(self.chat.items, 1) if any(x is y for y in c["items"])]
            shown, said = (f"everything under “{c['label']}”",
                           f"everything under “{c['label']}” on my list ({', '.join(ns)})")
        elif kind == "cut":
            c = rest[0]
            raw = " ".join((c.get("raw") or c["text"]).split())
            shown, said = raw, f"this cut on my list (C{c['id']}), {c['where']}: \"{raw}\""
        else:
            m = rest[0]
            shown = f"…{m['ctx_raw']} {m['word_raw']} {m['ctx_after_raw']}…"
            said = f"this marked-out word on my list (W{m['id']}): \"{m['word_raw']}\" in \"{shown}\""
        words = engine.E._masked_text(shown.split()).split()      # swear words starred
        self._chat_about = said
        self._chat_say("info", "Your next message is about: “" + " ".join(words[:16]) +
                       ("…" if len(words) > 16 else "") + "” — type your question below.")
        self.chat_entry.focus_set()

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
        self._chat_say("me", q)
        self.chat.an.setdefault("chat_history", []).append(("me", q))
        self._chat_say("info", f"{self._ai_name()} is reading the book…")
        self.chat_send.configure(state="disabled")
        self._sync_ticks()
        chat = self.chat
        about, self._chat_about = getattr(self, "_chat_about", None), None
        if about:
            q = f"About {about}\n\n{q}\n\n(Make any change on my list for that one as I ask.)"

        def work():
            try:
                self.q.put(("chat_reply",) + chat.ask(q))
            except Exception as ex:
                self.q.put(("chat_reply", f"Sorry, that didn't work: {ex}", [], []))
        threading.Thread(target=work, daemon=True).start()

    def _chat_reply(self, ans, changes, kept):
        import copy
        a = self.chat.an
        a.setdefault("chat_history", []).append(("them", ans or ""))
        done = []
        check = isinstance(self.chat, engine.CheckChat)
        if changes and (a is self.report if check else a is self.analysis):
            self._sync_ticks()
            snap = ([(it, it.get("fine")) for _, _, it in self.chat.items] if check else
                    (copy.deepcopy(a["cuts"]), copy.deepcopy(a["mutes"])))
            done = self.chat.apply(changes)
            if done:
                self._undo = snap
        lines = [ans or "(no answer)"]
        if done:
            lines.append("Changed on your list: " + "; ".join(done) + ".")
        for note, everywhere in kept or ():
            lines.append("✓ CleanRead will remember" + (" for every book" if everywhere else
                                                               " for this book") + ": " + note)
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_send.configure(state="normal")
            self._chat_say("them", lines[0])
            for ln in lines[1:]:
                self._chat_say("info", ln)
            if done:
                self.chat_undo.pack(side="right")
        for ln in lines[1:]:
            a["chat_history"].append(("info", ln))
        if done:
            self._chat_redraw()

    def _chat_redraw(self):
        """Show the chat's changes on the page it's about."""
        if isinstance(self.chat, engine.CheckChat):
            if self.report is self.chat.an and getattr(self, "_canvas", None) and self._canvas.winfo_exists():
                self._report_changed(self.report)
                self.show_report(keep_place=True)
        elif getattr(self, "summary_lbl", None) and self.summary_lbl.winfo_exists():
            self.show_review(keep_place=True)

    def _undo_chat(self):
        snap = getattr(self, "_undo", None)
        if not snap:
            return
        if isinstance(self.chat, engine.CheckChat):
            marks = []
            for it, fine in snap:
                if bool(it.get("fine")) != bool(fine):
                    it["fine"] = fine
                    kind = next(k for k, _, x in self.chat.items if x is it)
                    marks.append((kind, it.get("key"), self.chat._raw(it), bool(fine)))
            engine.learn_marks(marks)
        else:
            self.analysis["cuts"][:], self.analysis["mutes"][:] = snap
        self._undo = None
        self.chat_undo.pack_forget()
        self._chat_say("info", "Undid the last change.")
        self._chat_redraw()

    # ---------- page 3: done ----------
    def show_done(self, res):
        p = self._new_page("All done!", "Your clean copy is ready. The original book wasn't changed.")
        stats = tk.Frame(p, bg=BG)
        stats.pack(fill="x", pady=20)
        for big, small in [(str(res["mutes"]), "words marked out"),
                           (str(res["cut_sents"] + res.get("cut_parts", 0)), "sentences cut or shortened"),
                           (str(res["cut_paras"]), "paragraphs cut")]:
            rc = CL.card(stats, radius=14, pad=(20, 14), width=220)
            rc.pack(side="left", padx=(0, 12))
            box = rc.body
            tk.Label(box, text=big, bg=CARD, fg=ACCENT, font=(HEAD, 26)).pack()
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
        LOGO.put_logo(p, "cleanread.ico", BG)

    def reset(self):
        self.chat = None
        self.book_path, self.book, self.outdir, self.report, self.analysis = None, None, None, None, None
        self.show_setup()


def _fix_shortcut():
    # put the CleanRead icon right if it leads somewhere else (the installed copy only)
    try:
        import shortcuts
        shortcuts.ensure_cleanread_shortcut()
        shortcuts.ensure_readaloud_shortcut()
    except Exception:
        pass


def _ollama_off_at_startup():
    # Ollama only while the apps are open (2026-11-05): not started with Windows (the installed
    # copy only, so a test copy never changes the PC)
    try:
        import ollama_care
        import shortcuts
        if shortcuts.installed_copy():
            ollama_care.autostart_off()
    except Exception:
        pass


def _ollama_stop_later():
    # closing: stop Ollama once no CleanView, CleanListen or CleanRead uses it
    try:
        import ollama_care
        import shortcuts
        if shortcuts.installed_copy():
            ollama_care.stop_later()
    except Exception:
        pass


if __name__ == "__main__":
    import threading
    threading.Thread(target=_fix_shortcut, daemon=True).start()
    threading.Thread(target=_ollama_off_at_startup, daemon=True).start()
    App().mainloop()
    _ollama_stop_later()
