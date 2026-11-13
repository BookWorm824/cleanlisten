"""ReadAloud — turn an ebook into an audiobook with a natural voice, free, on this PC."""
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
import readaloud as engine  # noqa: E402
import readaloud_gpu as gpu  # noqa: E402  (the graphics-card voices)
import freezes  # noqa: E402  (noticing a freeze or a crash, shared with CleanListen)
import filters as F  # noqa: E402  (only for the light / dark choice, kept with CleanListen's)
import logo as LOGO  # noqa: E402
import cvlook as look  # noqa: E402  (the drawn look: cards, switches, pill buttons; CleanView's)
import cllook as CL  # noqa: E402  (the step-by-step start page and light / dark, shared)

APP = "ReadAloud"
APP_DATA = engine.APP_DATA
SETTINGS = APP_DATA / "readaloud_settings.json"
SAVE_PLACES = APP_DATA / "save_places.json"     # CleanListen's chosen M4B folder (Audiobookshelf)
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
# CleanView's new look (the owner, 2026-11-13: "change read aloud to the style of the new cleanview.
# i know that tick boxes are diffent but bring the styling over"): the start page one step at a
# time, rounded cards and buttons, and light or dark, as CleanListen and CleanRead. Every colour is
# a name from cllook.py with a value for each look; `use_theme` sets them here (BG, CARD, INK, GO...),
# so a page reads the look in use. Never write a colour into a page: name it in cllook.py.
THEME = "light"


def use_theme(name):
    """Light or dark: sets every colour name in this module. Pages built after it are in that look."""
    global THEME
    THEME = CL.use_theme(name)
    globals().update(CL.colours())


use_theme("light")          # the saved choice is read when the window opens (App.__init__)
HEAD = CL.HEAD
BOOK_TYPES = [("Ebooks", "*.epub *.pdf *.txt *.docx"), ("All files", "*.*")]
VOICE_LABELS = [f"{name}  ·  {desc}" for _, _, name, desc, _ in engine.VOICES]
GPU_LABELS = [gpu.GPU_VOICES[v][0].replace(" - ", "  ·  ") for v in gpu.NARRATORS]
AI_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}


def _saved_ai():
    """The online AI chosen in CleanListen (Claude unless they picked another)."""
    try:
        import cleanlisten_claude as cc
        return cc.saved_provider()
    except Exception:
        return "claude"


def chime():
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
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


def play_wav(path):
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        open_path(path)


PAUSED = "Paused — press Resume to carry on."


def stop_playing():
    try:
        import winsound
        winsound.PlaySound(None, 0)
    except Exception:
        pass


def logo_png(px=128):
    """ReadAloud's logo as PNG bytes, the size nearest px, taken from readaloud.ico (its pictures
    are PNGs, which tk can show without PIL; as CleanView does). None if it can't be read."""
    import struct
    try:
        d = (HERE / "readaloud.ico").read_bytes()
        found = []
        for i in range(struct.unpack("<H", d[4:6])[0]):
            w, _, _, _, _, _, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
            if d[off:off + 4] == b"\x89PNG":
                found.append((abs((w or 256) - px), d[off:off + size]))
        return min(found)[1] if found else None
    except (OSError, struct.error):
        return None


def hours_text(h):
    m = int(round(h * 60))
    if m < 60:
        return f"{max(1, m)} minute{'s' if m > 1 else ''}"
    hh, mm = divmod(m, 60)
    return f"{hh} hour{'s' if hh > 1 else ''}" + (f" {mm} minutes" if mm else "")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(860 * scale), sw - 40)
        h = min(int(820 * scale), sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(w, int(640 * scale)), min(h, int(480 * scale)))
        try:                        # light or dark, before anything is drawn (shared with CleanListen)
            use_theme(F.load().get("theme"))
        except Exception:
            use_theme("light")
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(HERE / "readaloud.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.settings = load_json(SETTINGS)
        self.book = None
        self.book_path = None
        self.chapter_vars = []
        self.folder = None
        self.maker = None
        self.cover_img = None
        self._cover = None
        self.done_jobdir = None
        self.busy_sample = False
        self.gpu_ok = None            # (ok, message) once checked
        self.installing = None        # the reader being set up
        # each book being made has a number; Stop for now moves it on, so the page goes home at once
        # and anything the stopped book still says afterwards is ignored (Lauren, 2026-11-09: "it
        # taking a while to actually cancel and go back to home screen")
        self.job = 0
        self.ending = []              # (worker thread, stopping thread) of books told to stop
        threading.Thread(target=lambda: self.q.put(("gpu_check", gpu.gpu_check())), daemon=True).start()
        self._style()
        self.page = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_setup()
        self.after(50, lambda: CL.title_bar(self))
        self.watch = freezes.Watch(self, APP, APP_DATA, "readaloud_")
        self.watch.start()
        self.after(100, self._poll)

    # ---------- look ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        s.configure("TCheckbutton", background=CARD, foreground=INK, font=(FONT, 10))
        s.map("TCheckbutton", background=[("active", CARD)])
        s.configure("Main.TButton", background=GO, foreground="white",
                    font=(HEAD, 13), padding=(26, 9), borderwidth=0)
        s.map("Main.TButton", background=[("active", GO_DK), ("disabled", GO_OFF)])
        s.configure("Go.TButton", background=ACCENT, foreground="white",
                    font=(HEAD, 11), padding=(18, 7), borderwidth=0)
        s.map("Go.TButton", background=[("active", ACCENT_DK), ("disabled", DISABLED)])
        s.configure("Plain.TButton", padding=(18, 7), font=(FONT, 10))
        s.configure("Small.TButton", padding=(10, 3), font=(FONT, 9))
        s.configure("TCombobox", padding=4)
        # the drawn look: rounded buttons, thin scroll bars, a rounded progress bar, soft fields
        # and smooth tick boxes with a real tick
        CL.style(self, s)

    def destroy(self):
        if getattr(self, "watch", None):
            self.watch.stop()
        super().destroy()

    def _px(self, n):
        return look.px(self, n)

    def _new_page(self, title, subtitle="", name=""):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = title
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        X = self._px
        self.steps_page = None
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=X(34), pady=(X(22), X(16)))
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(X(10), 0))
        tk.Frame(self.footer, bg=LINE, height=1).pack(side="top", fill="x", pady=(0, X(12)))
        if name:
            tk.Label(self.page, text=name, bg=BG, fg=ACCENT, font=(HEAD, 11),
                     wraplength=X(760), justify="left").pack(anchor="w", pady=(0, X(2)))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(HEAD, 21),
                 wraplength=X(760), justify="left").pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 10),
                     wraplength=X(740), justify="left").pack(anchor="w", pady=(X(4), X(14)))
        return self.page

    def _logo(self, parent):
        """The logo in the middle of the empty space below (Jason: "a lot of dead space")."""
        LOGO.put_logo(parent, "readaloud.ico", BG)

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
        inner._canvas = canvas
        return inner

    def _note(self, parent, text, bg=None, pad=0, fg=None):
        tk.Label(parent, text=text, bg=bg or CARD, fg=fg or MUTED, font=(FONT, 9), wraplength=self._px(560),
                 justify="left").pack(anchor="w", padx=(pad, 0))

    def _link(self, parent, text, cmd, bg=None):
        lbl = tk.Label(parent, text=text, bg=bg or CARD, fg=ACCENT, font=(HEAD, 9), cursor="hand2")
        look.on_click(lbl, lambda e: cmd())
        lbl.bind("<Enter>", lambda e: lbl.config(font=(HEAD, 9, "underline")))
        lbl.bind("<Leave>", lambda e: lbl.config(font=(HEAD, 9)))
        return lbl

    def _heading(self, parent, text, sub=""):
        tk.Label(parent, text=text, bg=CARD, fg=INK, font=(HEAD, 11), anchor="w").pack(anchor="w")
        if sub:
            tk.Label(parent, text=sub, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", justify="left",
                     wraplength=self._px(540)).pack(anchor="w", pady=(self._px(2), 0))

    # ---------- page 1: the book, the voice, the director, the chapters, where it goes ----------
    # One step at a time, as CleanView 1.18.77 ("B, step by step"): the steps down the left, each
    # saying what's chosen; one step on the right; Back / Next; Make audiobook always there.
    STEPS = [("Ebook", "Choose the book to read aloud. The original is never changed."),
             ("Voice", "Who reads the book, and how fast."),
             ("Reading director", "Claude, ChatGPT or Gemini goes through the book first and directs "
                                  "the reading. Optional."),
             ("What to read", "The parts nobody wants read aloud (contents, copyright pages) are "
                              "already left out."),
             ("Save to", "Where the audiobook goes.")]

    def _step_summary(self, n):
        """What's chosen in step n, in a few words, for the list on the left."""
        if n == 1:
            return self.book["title"] if self.book else "No book chosen yet"
        if n == 2:
            return gpu.READERS[self._reader()][0]
        if n == 3:
            return AI_NAMES[self._ai()] if self.director_var.get() else "Off"
        if n == 4:
            if not self.book:
                return "Choose a book first"
            k, total = len(self._chosen()), len(self.book["chapters"])
            return f"All {total} parts" if k == total else f"{k} of {total} parts"
        if self.folder:
            return Path(self.folder).name or str(self.folder)
        return "Next to the ebook"

    def _refresh_steps(self):
        sp = getattr(self, "steps_page", None)
        if sp is not None:
            sp.refresh()

    def _theme_var(self):
        self.theme_var = tk.StringVar(value=THEME)
        return self.theme_var

    def _set_theme(self, name=None):
        """Light or dark, from the choice under the steps: the start page is built again in that
        look, keeping what's chosen and the step. Kept for next time, with CleanListen's and
        CleanRead's choice (filters.json)."""
        name = "dark" if (name or self.theme_var.get()) == "dark" else "light"
        if name == THEME:
            return
        self._remember()
        try:
            d = F.load()
            d["theme"] = name
            F.save(d)
        except Exception:
            pass
        typed = (self.series_var.get(), self.number_var.get())
        step = getattr(getattr(self, "steps_page", None), "now", 1)
        use_theme(name)
        self.configure(bg=BG)
        self._style()                       # the ttk styles and tick boxes in that look
        CL.title_bar(self)
        self.show_setup(step=step)
        if self.book:
            self.series_var.set(typed[0])
            self.number_var.set(typed[1])

    def show_setup(self, step=1):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = APP
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        X = self._px
        p = self.page = tk.Frame(self, bg=BG)
        p.pack(fill="both", expand=True)
        try:
            ver = json.loads((HERE / "version.json").read_text())["version"]
            self.title(f"{APP} {ver}")
        except Exception:
            pass
        st = self.settings
        sp = self.steps_page = CL.StepPage(
            self, p, APP, LOGO.logo_png("readaloud.ico", X(40))[0], self.STEPS, self._step_summary,
            ("Make audiobook", self.start), done=lambda i: i == 1 and bool(self.book),
            scroll_area=self._scroll_area, start=step, theme=(self._theme_var(), self._set_theme))
        self.footer = sp.nav
        self.start_btn = sp.main_btn
        self.start_btn.config(state="disabled")
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(sp.top, text="✓ " + upd, bg=TINT, fg=ACCENT_DK, font=(FONT, 10),
                     padx=X(12), pady=X(7), anchor="w").pack(fill="x", pady=(0, X(12)))
        # a book that was stopped: above every step, as CleanView's "Pick up where I left off"
        for jobdir, job, got, n in engine.unfinished_jobs()[:2]:
            c = look.Card(sp.top, fill=TINT, edge=TINT_EDGE, radius=14, pad=(18, 12))
            c.pack(fill="x", pady=(0, X(12)))
            words = tk.Frame(c.body, bg=TINT)
            words.pack(side="left", fill="x", expand=True)
            tk.Label(words, text=f"Resume “{job.get('title', 'your book')}”?", bg=TINT, fg=INK,
                     font=(HEAD, 11), anchor="w", justify="left", wraplength=X(380)).pack(anchor="w")
            tk.Label(words, text=f"{got} of {n} chapters were read aloud before it stopped "
                                 f"({engine.voice_label(job)}).", bg=TINT, fg=MUTED, font=(FONT, 9),
                     anchor="w", justify="left", wraplength=X(380)).pack(anchor="w", pady=(X(2), 0))
            look.Pill(c.body, "Resume", lambda d=jobdir, j=job: self.resume(d, j), size=10,
                      pad=(18, 8)).pack(side="right")
            look.Pill(c.body, "Forget it", lambda d=jobdir: self.forget(d), kind="quiet", size=10,
                      pad=(14, 8)).pack(side="right", padx=(0, X(6)))

        # ----- step 1: the book
        drop = look.Card(sp.pane(1), fill=SOFT, edge=SOFT_EDGE, radius=16, pad=(20, 18))
        drop.pack(fill="x", padx=(0, X(4)))
        look.Badge(drop.body, "folder", size=54, icon_size=20).pack(side="left")
        words = tk.Frame(drop.body, bg=SOFT)
        words.pack(side="left", fill="x", expand=True, padx=(X(16), X(12)))
        tk.Label(words, text="Choose an ebook", bg=SOFT, fg=INK, font=(HEAD, 13), anchor="w").pack(anchor="w")
        tk.Label(words, text="EPUB, PDF, Word or TXT — not copy-protected.", bg=SOFT, fg=MUTED,
                 font=(FONT, 9), anchor="w", wraplength=X(260), justify="left").pack(anchor="w", pady=(X(2), 0))
        look.Pill(drop.body, "Choose ebook…", self.pick_book, size=12, pad=(22, 11)).pack(side="right")
        row = tk.Frame(sp.pane(1), bg=BG)
        row.pack(fill="x", pady=(X(14), 0))
        self.cover_lbl = tk.Label(row, bg=BG)
        self.cover_lbl.pack(side="left", padx=(0, X(14)))
        self.book_lbl = tk.Label(row, text="No book chosen yet", bg=BG, fg=MUTED, font=(FONT, 10),
                                 wraplength=X(460), justify="left", anchor="w")
        self.book_lbl.pack(side="left", anchor="w")
        tk.Label(sp.pane(1), text="Want it clean? Make a clean copy in CleanRead first, then choose that "
                 "copy here. Kindle books are copy-protected and can't be read.", bg=BG, fg=FAINT,
                 font=(FONT, 9), wraplength=X(560), justify="left").pack(anchor="w", pady=(X(14), 0))

        # ----- step 2: the voice: which reader (Lauren chooses by book), then which voice
        self.reader_var = tk.StringVar(value=st.get("reader") if st.get("reader") in gpu.READERS else "acting")
        self._shown_reader = None
        choices = tk.Frame(sp.pane(2), bg=BG)
        choices.pack(fill="x")
        for c in range(2):
            choices.columnconfigure(c, weight=1, uniform="reader")
        for k, r in enumerate(gpu.READER_ORDER):
            name, desc = gpu.READERS[r][:2]
            card = look.OptionCard(choices, r, self.reader_var, name + ("  (best)" if r == "acting" else ""),
                                   desc + ("" if r == "kokoro" else "  On the graphics card."),
                                   icon="pc" if r == "kokoro" else "music")
            card.sub.config(wraplength=X(200))
            card.grid(row=k // 2, column=k % 2, sticky="nsew", padx=(0, X(10)), pady=(0, X(10)))
        self.reader_var.trace_add("write", lambda *_: self.after_idle(self._reader_picked))
        b = sp.card(2, top=2)
        self.reader_row = tk.Frame(b, bg=CARD)
        self.reader_row.pack(fill="x")
        self.reader_lbl = tk.Label(self.reader_row, text="", bg=CARD, fg=MUTED, font=(FONT, 9),
                                   wraplength=X(540), justify="left")
        self.reader_lbl.pack(anchor="w")
        self.setup_btn = look.Pill(self.reader_row, "Set up", self.set_up_reader, size=10, pad=(18, 8))
        b = sp.card(2, top=12)
        self._heading(b, "Voice")
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x", pady=(X(8), 0))
        self.voice_box = ttk.Combobox(row, state="readonly", width=42, values=VOICE_LABELS)
        self.voice_box.pack(side="left")
        self.voice_box.bind("<<ComboboxSelected>>", lambda e: self._remember())
        self.hear_btn = look.Pill(row, "▶ Hear it", self.hear, size=10, pad=(16, 7))
        self.hear_btn.pack(side="left", padx=(X(10), 0))
        look.Pill(row, "■ Stop", stop_playing, kind="quiet", size=10, pad=(12, 7)).pack(side="left", padx=X(4))
        row2 = tk.Frame(b, bg=CARD)
        row2.pack(fill="x", pady=(X(10), 0))
        tk.Label(row2, text="Reading speed", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.speed_box = ttk.Combobox(row2, state="readonly", width=14, values=list(engine.SPEEDS))
        names = list(engine.SPEEDS)
        self.speed_box.current(names.index(st.get("speed")) if st.get("speed") in names else 1)
        self.speed_box.pack(side="left", padx=X(10))
        self.speed_box.bind("<<ComboboxSelected>>", lambda e: (self._remember(), self._book_text()))
        self.sample_lbl = tk.Label(b, text="Press ▶ Hear it to listen to a few sentences of your book.",
                                   bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=X(540), justify="left")
        self.sample_lbl.pack(anchor="w", pady=(X(8), 0))
        self._reader_changed(remember=False)

        # ----- step 3: the reading director (readaloud_ai): Claude / ChatGPT / Gemini go through it first
        self.director_var = tk.BooleanVar(value=st.get("director", True))
        b = sp.card(3)
        CL.switch_row(b, self.director_var, "Have a reading director go through the book first",
                      "It takes out what shouldn't be read aloud (page numbers, headings at the top of "
                      "pages, jacket text, scanning mistakes), works out who is speaking and how each "
                      "part should be read (the feeling of each line for the Qwen acting voice, slower, "
                      "faster, pauses), and looks up how to say the names. It adds about 10 minutes "
                      "before the reading starts, and you get a list of everything it changed. Uses "
                      "your own Claude, ChatGPT or Gemini plan.",
                      command=self._director_changed).pack(fill="x")
        self.director_more = tk.Frame(sp.pane(3), bg=BG)
        saved = st.get("ai") if st.get("ai") in AI_NAMES else _saved_ai()
        self.ai_var = tk.StringVar(value=saved if saved in AI_NAMES else "claude")
        b = look.Card(self.director_more, radius=14, pad=(18, 14))
        b.pack(fill="x", padx=(0, X(4)), pady=(X(12), 0))
        self._heading(b.body, "Who directs it")
        look.Segmented(b.body, list(AI_NAMES.items()), self.ai_var, command=self._director_changed,
                       bg=CARD, size=10).pack(anchor="w", pady=(X(8), 0))
        srow = tk.Frame(b.body, bg=CARD)
        srow.pack(anchor="w", fill="x", pady=(X(8), 0))
        self.ai_status = tk.Label(srow, text="", bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=X(400),
                                  justify="left")
        self.ai_status.pack(side="left")
        self.ai_btn = look.Pill(srow, "Set up / sign in", self._sign_in, kind="secondary", size=9,
                                pad=(14, 6))
        self.ai_ok = None
        self.cast_var = tk.BooleanVar(value=st.get("cast", False))
        b = look.Card(self.director_more, radius=14, pad=(18, 14))
        b.pack(fill="x", padx=(0, X(4)), pady=(X(12), 0))
        CL.switch_row(b.body, self.cast_var, "Give the characters their own voices",
                      "Men and women in the story each get a voice; the narrator keeps the voice you "
                      "chose.", command=self._remember).pack(fill="x")
        self._director_changed(check=True)

        # ----- step 4: the chapters
        b = sp.card(4)
        self.ch_host = tk.Frame(b, bg=CARD)
        self.ch_host.pack(fill="x")
        tk.Label(self.ch_host, text="Choose a book first.", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(anchor="w")

        # ----- step 5: where it goes
        b = sp.card(5)
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x")
        look.Pill(row, "Change…", self.pick_folder, kind="secondary", size=10, pad=(16, 8)).pack(side="right")
        self.out_lbl = tk.Label(row, text="Next to the ebook", bg=CARD, fg=MUTED, font=(FONT, 10),
                                wraplength=X(400), justify="left")
        self.out_lbl.pack(side="left")
        places = load_json(SAVE_PLACES)
        self.folder = st.get("folder") or places.get("m4b_dir") or None
        self.abs_var = tk.BooleanVar(value=st.get("abs", bool(places.get("abs"))))
        b = sp.card(5, top=12)
        CL.switch_row(b, self.abs_var, "Put it in Audiobookshelf's folders",
                      "Author \\ Series \\ Book 2 - Title", command=self._abs_changed).pack(fill="x")
        self.abs_row = tk.Frame(b, bg=CARD)
        tk.Label(self.abs_row, text="Series", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.series_var = tk.StringVar()
        ttk.Entry(self.abs_row, textvariable=self.series_var, width=26).pack(side="left", padx=(X(8), X(16)))
        tk.Label(self.abs_row, text="Book number", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.number_var = tk.StringVar()
        ttk.Entry(self.abs_row, textvariable=self.number_var, width=6).pack(side="left", padx=X(8))
        self.mp3_var = tk.BooleanVar(value=st.get("mp3", False))
        b = sp.card(5, top=12)
        self.mp3_check = CL.switch_row(b, self.mp3_var, "Also make MP3 chapter files",
                                       "For a Yoto or an older player.", command=self._remember)
        self.mp3_check.pack(fill="x")
        tk.Label(sp.pane(5), text="The audiobook is one M4B file with chapters and the book's cover. It "
                 "plays in Audiobookshelf, Apple Books, BookPlayer, Smart AudioBook Player and VLC.",
                 bg=BG, fg=FAINT, font=(FONT, 9), wraplength=X(560), justify="left").pack(anchor="w", pady=(X(14), 0))
        self._abs_changed()
        if self.book:
            self._show_book()
        sp.go(step)

    # ---------- which reader ----------
    def _reader(self):
        try:
            return self.reader_var.get()
        except (tk.TclError, AttributeError):
            return "kokoro"

    def _voice_id(self):
        i = max(0, self.voice_box.current())
        return gpu.NARRATORS[i] if gpu.is_gpu(self._reader()) else engine.VOICES[i][0]

    def _reader_picked(self):
        """A voice card was clicked (not the window choosing the Quick voice for a PC without a card)."""
        if getattr(self, "reader_lbl", None) and self.reader_lbl.winfo_exists() and \
                self._reader() != self._shown_reader:
            self._reader_changed()

    def _ai(self):
        try:
            v = self.ai_var.get()
        except (tk.TclError, AttributeError):
            v = ""
        return v if v in AI_NAMES else "claude"

    def _reader_changed(self, remember=True):
        r = self._reader()
        self._shown_reader = r
        st = self.settings
        if gpu.is_gpu(r):
            self.voice_box.config(values=GPU_LABELS)
            v = st.get("gpu_voice")
            self.voice_box.current(gpu.NARRATORS.index(v) if v in gpu.NARRATORS else 0)
        else:
            self.voice_box.config(values=VOICE_LABELS)
            keys = [v[0] for v in engine.VOICES]
            self.voice_box.current(keys.index(st.get("voice")) if st.get("voice") in keys else 0)
        if remember:
            self._remember()
        self._show_reader()
        self._book_text()
        self._refresh_steps()

    def _show_reader(self):
        if not (getattr(self, "reader_lbl", None) and self.reader_lbl.winfo_exists()):
            return
        r = self._reader()
        self.setup_btn.pack_forget()
        if not gpu.is_gpu(r):
            self.reader_lbl.config(text="The quickest: about 2 hours for a 10-hour book.", fg=MUTED)
            return
        speed = f"About {10 / gpu.READERS[r][2]:.0f} hours for a 10-hour book (start it at night)."
        if self.installing:
            return                                          # the setup is showing its progress
        if self.gpu_ok is None:
            self.reader_lbl.config(text="Checking the graphics card…", fg=MUTED)
        elif not self.gpu_ok[0]:
            self.reader_lbl.config(text=self.gpu_ok[1], fg=FAIL)
        elif gpu.ready(r):
            self.reader_lbl.config(text="✓ Ready.  " + speed, fg=ACCENT_DK)
        else:
            # Set up gets all the new voices at once (Lauren had to press it for each), so the size
            # is for all of them
            self.reader_lbl.config(text=f"Needs a one-time download of about {gpu.setup_all_size_gb():.0f} GB "
                                        f"before its first book.  {speed}", fg=INK)
            self.setup_btn.pack(anchor="w", pady=(6, 0))

    def set_up_reader(self):
        r = self._reader()
        if self.installing:
            return
        self.installing = r
        self.setup_btn.pack_forget()
        self.reader_lbl.config(text="Starting the setup… (you can choose the book meanwhile)", fg=INK)
        self.start_btn.config(state="disabled")

        def go():
            try:
                with freezes.awake():       # a download of several GB: the PC doesn't go to sleep meanwhile
                    # all the new voices in one go, the chosen one first
                    gpu.install_all(r, lambda f, m: self.q.put(("setup_msg", r, f, m)))
                self.q.put(("setup_done", r, ""))
            except Exception as ex:
                self.q.put(("setup_done", r, str(ex)))
        threading.Thread(target=go, daemon=True).start()

    def _director_changed(self, check=True):
        on = self.director_var.get()
        if on:
            self.director_more.pack(fill="x")
        else:
            self.director_more.pack_forget()
        self._remember()
        self._refresh_steps()
        self.ai_btn.pack_forget()
        if not on:
            self.ai_status.config(text="")
            return
        ai = self._ai()
        self.ai_status.config(text=f"Checking that {AI_NAMES[ai]} is set up…", fg=MUTED)
        self.ai_ok = None

        def go():
            try:
                import cleanlisten_claude as cc
                st = cc.status(ai)
            except Exception:
                st = "missing"
            self.q.put(("ai_status", ai, st))
        if check:
            threading.Thread(target=go, daemon=True).start()

    def _sign_in(self):
        ai = self._ai()
        self.ai_status.config(text=f"Setting up {AI_NAMES[ai]}… (a window or your browser may open)", fg=INK)

        def go():
            try:
                import cleanlisten_claude as cc
                cc.install(provider=ai)
                cc.open_sign_in(ai)
                self.q.put(("ai_status", ai, "signing_in"))
            except Exception as ex:
                self.q.put(("ai_status", ai, "error:" + str(ex)[:200]))
        threading.Thread(target=go, daemon=True).start()

    def _abs_changed(self):
        if self.abs_var.get():
            self.abs_row.pack(anchor="w", pady=(self._px(10), 0))
        else:
            self.abs_row.pack_forget()
        self._remember()
        self._show_folder()

    def _remember(self):
        st = self.settings
        try:
            st["reader"] = self._reader()
            if gpu.is_gpu(st["reader"]):
                st["gpu_voice"] = gpu.NARRATORS[self.voice_box.current()]
            else:
                st["voice"] = engine.VOICES[self.voice_box.current()][0]
            st["speed"] = self.speed_box.get()
            st["abs"] = self.abs_var.get()
            st["mp3"] = self.mp3_var.get()
            st["director"] = self.director_var.get()
            st["ai"] = self._ai()
            st["cast"] = self.cast_var.get()
        except (tk.TclError, AttributeError, IndexError):
            pass
        if self.folder:
            st["folder"] = self.folder
        save_settings(st)
        self._refresh_steps()

    def _show_folder(self):
        if not getattr(self, "out_lbl", None) or not self.out_lbl.winfo_exists():
            return
        if self.folder:
            self.out_lbl.config(text=os.path.normpath(self.folder), fg=INK)
        elif self.book_path:
            self.out_lbl.config(text=os.path.normpath(str(Path(self.book_path).parent)), fg=INK)

    def pick_folder(self):
        d = filedialog.askdirectory(title="Where should the audiobook go?",
                                    initialdir=self.folder or None)
        if d:
            self.folder = d
            self._remember()
            self._show_folder()

    def pick_book(self):
        f = filedialog.askopenfilename(title="Choose the ebook", filetypes=BOOK_TYPES)
        if not f:
            return
        self.book_lbl.config(text="Opening the book…", fg=MUTED)
        self.start_btn.config(state="disabled")

        def go():
            try:
                book = engine.load_book(f)
                if not book.get("cover"):
                    engine.cover_online(book)
                cover = self._cover_png(book)
                self.q.put(("book", f, book, cover))
            except engine.BookError as ex:
                self.q.put(("book_error", str(ex), ""))
            except Exception as ex:
                self.q.put(("book_error", f"This book couldn't be opened ({ex}).", traceback.format_exc()))
        threading.Thread(target=go, daemon=True).start()

    def _cover_png(self, book):
        """A small PNG of the cover for the page (tkinter can't show a JPEG)."""
        if not book.get("cover"):
            return None
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            src = APP_DATA / ("readaloud_cover" + book["cover_ext"])
            src.write_bytes(book["cover"])
            dst = APP_DATA / "readaloud_cover_small.png"
            r = subprocess.run([engine.tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vf",
                                "scale=-2:120", "-frames:v", "1", str(dst)], capture_output=True,
                               **engine._NOWIN)
            return str(dst) if r.returncode == 0 and dst.exists() else None
        except Exception:
            return None

    def _show_book(self):
        b = self.book
        try:
            self.cover_img = tk.PhotoImage(file=self._cover) if self._cover else None
        except Exception:
            self.cover_img = None
        self.cover_lbl.config(image=self.cover_img or "")
        self.series_var.set(b.get("series", ""))
        self.number_var.set(b.get("number", ""))
        for w in self.ch_host.winfo_children():
            w.destroy()
        # the same book shown again (light / dark, or back from the voice step): its ticks are kept
        keep = [v.get() for v in self.chapter_vars] if getattr(self, "_ticks_book", None) is b and \
            len(self.chapter_vars) == len(b["chapters"]) else [c["read"] for c in b["chapters"]]
        self._ticks_book = b
        self.chapter_vars = [tk.BooleanVar(value=v) for v in keep]
        self.ch_summary = tk.Label(self.ch_host, bg=CARD, fg=INK, font=(FONT, 10), wraplength=self._px(540),
                                   justify="left")
        self.ch_summary.pack(anchor="w")
        top = tk.Frame(self.ch_host, bg=CARD)
        top.pack(fill="x", pady=(4, 0))
        self.ch_toggle = self._link(top, "Show the chapters  ▾", self._toggle_chapters)
        self.ch_toggle.pack(side="left")
        self.ch_box = tk.Frame(self.ch_host, bg=CARD)
        self.ch_open = False
        self._book_text()
        self._show_folder()

    def _toggle_chapters(self):
        """The chapter list is folded away (a novel has 30+), so the page fits."""
        self.ch_open = not self.ch_open
        self.ch_toggle.config(text="Hide the chapters  ▴" if self.ch_open else "Show the chapters  ▾")
        if not self.ch_open:
            self.ch_box.pack_forget()
            return
        for w in self.ch_box.winfo_children():
            w.destroy()
        top = tk.Frame(self.ch_box, bg=CARD)
        top.pack(fill="x", pady=(6, 4))
        self._link(top, "Tick all", lambda: self._tick_all(True)).pack(side="left")
        self._link(top, "Untick all", lambda: self._tick_all(False)).pack(side="left", padx=12)
        speed = engine.SPEEDS.get(self.speed_box.get(), 1.0)
        for c, v in zip(self.book["chapters"], self.chapter_vars):
            mins = max(1, round(engine.estimate_hours(c["words"], speed) * 60))
            ttk.Checkbutton(self.ch_box, text=f"{c['title'][:70]}   ({mins} min)", variable=v,
                            command=self._book_text).pack(anchor="w")
        self.ch_box.pack(fill="x")

    def _tick_all(self, on):
        for v in self.chapter_vars:
            v.set(on)
        self._book_text()

    def _chosen(self):
        return [i for i, v in enumerate(self.chapter_vars) if v.get()]

    def _book_text(self):
        b = self.book
        if not b or not self.book_lbl.winfo_exists():
            return
        words = sum(b["chapters"][i]["words"] for i in self._chosen())
        hrs = engine.estimate_hours(words, engine.SPEEDS.get(self.speed_box.get(), 1.0))
        make = gpu.hours_to_make(hrs, self._reader())
        by = f"\nby {b['author']}" if b.get("author") else ""
        series = f"\n{b['series']}" + (f", book {b['number']}" if b.get("number") else "") if b.get("series") else ""
        self.book_lbl.config(text=f"{b['title']}{by}{series}\n\nAbout {hours_text(hrs)} of listening; "
                                  f"about {hours_text(make)} to make" if words else f"{b['title']}{by}\n\nNothing ticked to read.", fg=INK,
                             font=(FONT, 10))
        self.start_btn.config(state="normal" if words and not self.installing else "disabled")
        self._refresh_steps()
        if getattr(self, "ch_summary", None) and self.ch_summary.winfo_exists():
            n, chosen = len(b["chapters"]), len(self._chosen())
            off = [c["title"] for c, v in zip(b["chapters"], self.chapter_vars) if not v.get()]
            text = f"All {n} parts of the book will be read." if not off else \
                f"{chosen} of {n} parts will be read. Left out: " + ", ".join("“" + (t if len(t) <= 45 else t[:42].rstrip() + "…") + "”" for t in off[:4]) \
                + (f" and {len(off) - 4} more" if len(off) > 4 else "") + "."
            if off and len(off) == sum(not c["read"] for c in b["chapters"]) and \
                    all(not c["read"] for c, v in zip(b["chapters"], self.chapter_vars) if not v.get()):
                text += " (They look like the contents, copyright or other pages nobody wants read aloud.)"
            self.ch_summary.config(text=text)

    # ---------- hearing a voice ----------
    def hear(self):
        if self.busy_sample:
            return
        self._remember()
        voice = self._voice_id()
        speed = engine.SPEEDS.get(self.speed_box.get(), 1.0)
        if gpu.is_gpu(self._reader()):
            # the new voices take a minute to start: play the voice's own clip straight away
            stop_playing()
            dst = APP_DATA / "readaloud_sample.wav"
            try:
                subprocess.run([engine.tool("ffmpeg"), "-y", "-v", "error", "-i", str(gpu.voice_clip(voice)),
                                "-filter:a", f"atempo={speed}", str(dst)], capture_output=True, timeout=30,
                               **engine._NOWIN)
                self.sample_lbl.config(text=f"Playing {gpu.GPU_VOICES[voice][0].split(' - ')[0]}. In the book, "
                                            "this voice reads with the feeling of each line.", fg=MUTED)
                play_wav(dst)
            except Exception as ex:
                self.sample_lbl.config(text=f"Couldn't play the voice: {ex}", fg=FAIL)
            return
        text = engine.sample_text(self.book) if self.book else engine.sample_text({"chapters": []})
        self.busy_sample = True
        self.hear_btn.config(state="disabled")
        self.sample_lbl.config(text="Getting the voice ready…", fg=INK)
        stop_playing()

        def go():
            try:
                if not engine.have_model():
                    engine.get_model(lambda f, m: self.q.put(("sample_msg", m)))
                self.q.put(("sample_msg", "Getting the voice ready…"))
                dst = APP_DATA / "readaloud_sample.wav"
                engine.sample_wav(text, voice, speed, dst)
                self.q.put(("sample", str(dst), voice))
            except Exception as ex:
                self.q.put(("sample_error", str(ex), traceback.format_exc()))
        threading.Thread(target=go, daemon=True).start()

    # ---------- making it ----------
    def _out_file(self):
        b = dict(self.book, series=self.series_var.get().strip(), number=self.number_var.get().strip())
        folder = self.folder or str(Path(self.book_path).parent)
        return engine.out_path(b, folder, self.abs_var.get()), b

    def start(self):
        if not self.book:
            return
        ids = self._chosen()
        if not ids:
            return
        self._remember()
        out, b = self._out_file()
        if out.exists() and not messagebox.askyesno(
                APP, f"“{out.name}” is already in that folder.\n\nReplace it with the new one?"):
            return
        voice = self._voice_id()
        speed = engine.SPEEDS.get(self.speed_box.get(), 1.0)
        reader = self._reader()
        if gpu.is_gpu(reader) and not gpu.ready(reader):
            chime()
            name = gpu.READERS[reader][0]
            if self.installing:
                why = f"The {name} voice is still being set up. Wait for it to finish (it shows on the Voice step)."
            elif self.gpu_ok is None:
                why = "ReadAloud is still checking the graphics card. Try again in a moment."
            elif not self.gpu_ok[0]:
                why = f"The {name} voice can't be used yet:\n\n{self.gpu_ok[1]}"
            else:
                why = (f"The {name} voice needs a one-time setup first: press the green Set up button "
                       "on the Voice step.")
            messagebox.showinfo(APP, why + "\n\nOr choose the Quick voice, which works on any computer.")
            return
        extra = {"mp3": self.mp3_var.get(), "reader": reader}
        if self.director_var.get():
            ai = self._ai()
            if self.ai_ok is False:
                chime()
                if not messagebox.askyesno(APP, f"{AI_NAMES[ai]} isn't set up on this computer, so it can't go "
                                                "through the book.\n\nMake the audiobook without it?"):
                    return
            else:
                extra.update(director=ai, cast=self.cast_var.get())
        try:
            jobdir = engine.start_job(b, voice, speed, ids, out, extra)
        except OSError as ex:
            messagebox.showerror(APP, f"Couldn't get started: {ex}")
            return
        stop_playing()
        self.run_job(jobdir, b["title"])

    def resume(self, jobdir, job):
        self.run_job(jobdir, job.get("title", ""))

    def forget(self, jobdir):
        chime()
        if messagebox.askyesno(APP, "Forget this book? What was read aloud so far is deleted."):
            engine.clean_up(jobdir)
            self.show_setup()

    def run_job(self, jobdir, title):
        n, threads = engine.workers_for_pc()
        p = self._new_page("Narrating the book…",
                           "You can keep using your computer while it reads. If you need to stop, "
                           "it carries on from where it was next time you open ReadAloud.", name=title)
        X = self._px
        card = look.Card(p, radius=14, pad=(24, 22))
        card.pack(fill="x", pady=(X(10), 0))
        box = card.body
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000, length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=CARD, fg=INK, font=(FONT, 12), wraplength=X(700),
                               justify="left")
        self.status.pack(anchor="w", pady=(X(14), 0))
        self.left_lbl = tk.Label(box, text="Working out how long it will take…", bg=CARD, fg=MUTED,
                                 font=(FONT, 11))
        self.left_lbl.pack(anchor="w", pady=(X(4), 0))
        try:
            reader = json.loads((Path(jobdir) / "job.json").read_text(encoding="utf8")).get("reader", "kokoro")
        except Exception:
            reader = "kokoro"
        how = (f"Reading with the {gpu.READERS[reader][0]} voice on the graphics card. Each line is "
               "listened to and read again if a word came out wrong." if gpu.is_gpu(reader) else
               f"Reading {n} chapter{'s' if n > 1 else ''} at a time.")
        tk.Label(p, text=how, bg=BG, fg=MUTED, font=(FONT, 11), wraplength=X(740),     # Jason: "bigger"
                 justify="left").pack(anchor="w", pady=(X(16), 0))
        self._logo(p)
        self.stop_btn = ttk.Button(self.footer, text="Stop for now", style="Plain.TButton", command=self.stop)
        self.stop_btn.pack(side="right")
        # Pause beside it (the owner, 2026-11-12): the reading freezes where it is until Resume
        self.pause_btn = ttk.Button(self.footer, text="Pause", style="Plain.TButton", command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=(0, 10))
        self.job_title = title
        self.job += 1
        job = self.job

        def tell(*msg):
            self.q.put(("for_job", job, msg))
        self.maker = engine.Maker(jobdir, lambda f, m, left=None: tell("progress", f, m, left))
        maker = self.maker
        before = [w for w, _ in self.ending if w.is_alive()]

        def go():
            try:
                # a book told to stop may still be finishing its last bit: wait for it, so two never
                # read the same chapters or share the graphics card
                if before:
                    tell("progress", 0, "Waiting for the last book to finish stopping…", None)
                    for w in before:
                        w.join()
                # hours of reading, often left overnight: the PC doesn't go to sleep meanwhile (a
                # CleanRead book left overnight paused 9 hours while Windows slept, 2026-11-09).
                # The director, every chapter and putting the audiobook together all run in here
                with freezes.awake():
                    res = maker.run()
                tell("made", res)
            except engine.Stopped:
                tell("stopped")
            except Exception as ex:
                tell("error", str(ex), traceback.format_exc())
        self.worker = threading.Thread(target=go, daemon=True)
        self.worker.start()

    def toggle_pause(self):
        m = self.maker
        if not m:
            return
        if m.paused:
            m.resume()
            self.pause_btn.config(text="Pause")
            self.status.config(text=getattr(self, "last_status", "") or "Carrying on…")
            self.left_lbl.config(text="")
        else:
            m.pause()
            self.pause_btn.config(text="Resume")
            self.status.config(text=PAUSED)
            self.left_lbl.config(text="")
        if getattr(self, "watch", None):
            self.watch.doing["status"] = self.status.cget("text")

    def stop(self):
        """Stop for now: back to the first page at once. The book stops in the background (a chapter
        or the reading director can take a while to finish); what's read so far is kept, and it shows
        under "Resume"."""
        if not self.maker:
            return
        maker, self.maker = self.maker, None
        self.job += 1                       # anything the stopped book says from now on is ignored
        ender = threading.Thread(target=maker.stop, daemon=True)
        ender.start()
        self.ending = [(w, e) for w, e in self.ending if w.is_alive() or e.is_alive()]
        self.ending.append((self.worker, ender))
        self.book = None
        self.show_setup()

    def on_close(self):
        if self.installing and not self.maker:
            chime()
            if not messagebox.askyesno(APP, "The new voice is still being set up. Close anyway? (It starts "
                                            "again next time you press Set up.)"):
                return
        if self.maker:
            chime()
            if not messagebox.askyesno(APP, "Stop making the audiobook for now?\n\nWhat's been read "
                                            "so far is kept, and it carries on from there next time "
                                            "you open ReadAloud."):
                return
            self.maker.stop()
        for w, e in self.ending:            # a book told to stop: let it close its reading programs
            e.join(timeout=30)
        stop_playing()
        self.destroy()

    def show_done(self, res):
        self.maker = None
        chime()
        p = self._new_page("Your audiobook is ready", name=self.job_title)
        f = Path(res["file"])
        X = self._px
        card = look.Card(p, radius=14, pad=(24, 20))
        card.pack(fill="x", pady=(X(14), 0))
        c = card.body
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x")
        look.Badge(top, "check", size=40, fill=ACCENT, fg="white", circle=True).pack(side="left", anchor="n")
        words = tk.Frame(top, bg=CARD)
        words.pack(side="left", fill="x", expand=True, padx=(X(14), 0))
        tk.Label(words, text=f.name, bg=CARD, fg=INK, font=(HEAD, 12), wraplength=X(600),
                 justify="left", anchor="w").pack(anchor="w")
        tk.Label(words, text=f"{hours_text(res['hours'])} · {res['chapters']} chapters", bg=CARD, fg=MUTED,
                 font=(FONT, 10), anchor="w").pack(anchor="w", pady=(X(2), 0))
        tk.Label(words, text=os.path.normpath(str(f.parent)), bg=CARD, fg=FAINT, font=(FONT, 9),
                 wraplength=X(600), justify="left", anchor="w").pack(anchor="w", pady=(X(2), 0))
        if res.get("mp3_dir"):
            tk.Label(words, text=f"MP3 chapter files: {os.path.normpath(res['mp3_dir'])}", bg=CARD,
                     fg=FAINT, font=(FONT, 9), wraplength=X(600), justify="left").pack(anchor="w", pady=(X(2), 0))
        if res.get("report"):
            self._link(words, "See what the reading director left out and changed",
                       lambda: open_path(res["report"])).pack(anchor="w", pady=(X(8), 0))
        row = tk.Frame(c, bg=CARD)
        row.pack(anchor="w", pady=(X(16), 0), padx=(X(54), 0))
        ttk.Button(row, text="▶ Play it", style="Go.TButton", command=lambda: open_path(f)).pack(side="left")
        ttk.Button(row, text="Show in folder", style="Plain.TButton",
                   command=lambda: show_in_folder(f)).pack(side="left", padx=10)
        ttk.Button(self.footer, text="Make another", style="Main.TButton",
                   command=self.another).pack(side="right")
        self._logo(p)
        try:   # the chapter files aren't needed once the audiobook is made
            engine.clean_up(Path(self.done_jobdir))
        except Exception:
            pass

    def another(self):
        self.book = None
        self.book_path = None
        self.chapter_vars = []
        self.show_setup()

    # ---------- messages from the work threads ----------
    def _poll(self):
        freezes.drain(self, self.q, self._handle, self._poll_error, self.watch)

    def _poll_error(self, details):
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            (APP_DATA / "readaloud_last_error.txt").write_text(details, encoding="utf8")
        except OSError:
            pass

    def _handle(self, msg):
        if msg[0] == "for_job":
            if msg[1] != self.job:
                return                      # from a book that was stopped: it's not on screen any more
            msg = msg[2]
        kind = msg[0]
        if kind == "progress" and getattr(self, "pb", None) and self.pb.winfo_exists():
            self.pb["value"] = int(msg[1] * 1000)
            self.last_status = msg[2]
            if self.maker and self.maker.paused:
                return                      # it still says Paused until Resume
            self.status.config(text=msg[2])
            if msg[3] is not None:
                self.left_lbl.config(text=engine.fmt_left(msg[3]).capitalize())
            if getattr(self, "watch", None):
                self.watch.doing["status"] = msg[2]
        elif kind == "book":
            self.book_path, self.book, self._cover = msg[1], msg[2], msg[3]
            if self.page and getattr(self, "book_lbl", None) and self.book_lbl.winfo_exists():
                self._show_book()
        elif kind == "book_error":
            self._poll_error(msg[2]) if msg[2] else None
            if getattr(self, "book_lbl", None) and self.book_lbl.winfo_exists():
                self.book_lbl.config(text="No book chosen yet" if not self.book else self.book_lbl.cget("text"),
                                     fg=MUTED)
            messagebox.showerror(APP, msg[1])
        elif kind == "ai_status":
            if not (getattr(self, "ai_status", None) and self.ai_status.winfo_exists()):
                return
            ai, st = msg[1], msg[2]
            if ai != self._ai():
                return
            name = AI_NAMES[ai]
            self.ai_btn.pack_forget()
            if st == "ok":
                self.ai_ok = True
                self.ai_status.config(text=f"✓ {name} is ready.", fg=ACCENT_DK)
            elif st == "signing_in":
                self.ai_ok = None
                self.ai_status.config(text=f"Sign in to {name} in the window that opened, then come back here.",
                                      fg=INK)
                self.after(20000, lambda: self._director_changed())
            elif st.startswith("error:"):
                self.ai_ok = False
                self.ai_status.config(text=f"Couldn't set up {name}: {st[6:]}", fg=FAIL)
                self.ai_btn.pack(side="left", padx=self._px(10))
            else:
                self.ai_ok = False
                self.ai_status.config(text=f"{name} isn't set up on this computer yet." if st == "missing"
                                      else f"{name} isn't signed in.", fg=FAIL)
                self.ai_btn.pack(side="left", padx=self._px(10))
        elif kind == "gpu_check":
            self.gpu_ok = msg[1]
            # no graphics card for the new voices (Lauren's sister?): start on the Quick one, unless
            # a reader was chosen before
            if not self.gpu_ok[0] and not self.settings.get("reader") and getattr(self, "reader_var", None):
                try:
                    self.reader_var.set("kokoro")
                    self._reader_changed(remember=False)
                except tk.TclError:
                    pass
            self._show_reader()
        elif kind == "setup_msg":
            if getattr(self, "reader_lbl", None) and self.reader_lbl.winfo_exists() and gpu.is_gpu(self._reader()):
                self.reader_lbl.config(text=f"Setting up ({int(msg[2] * 100)}%): {msg[3]}", fg=INK)
        elif kind == "setup_done":
            self.installing = None
            if msg[2]:
                self._poll_error(msg[2])
                chime()
                messagebox.showerror(APP, "The voice couldn't be set up:" + chr(10) * 2 + msg[2][:700])
            else:
                chime()
            if getattr(self, "reader_lbl", None) and self.reader_lbl.winfo_exists():
                self._show_reader()
                self._book_text()
        elif kind == "sample_msg":
            if self.sample_lbl.winfo_exists():
                self.sample_lbl.config(text=msg[1], fg=INK)
        elif kind == "sample":
            self.busy_sample = False
            if self.hear_btn.winfo_exists():
                self.hear_btn.config(state="normal")
                name = engine.VOICE[msg[2]][2]
                self.sample_lbl.config(text=f"Playing {name}. Press ■ Stop to stop it, or pick another "
                                            "voice and press ▶ Hear it.", fg=MUTED)
            play_wav(msg[1])
        elif kind == "sample_error":
            self.busy_sample = False
            self._poll_error(msg[2])
            if self.hear_btn.winfo_exists():
                self.hear_btn.config(state="normal")
                self.sample_lbl.config(text="Couldn't play the voice: " + msg[1], fg=FAIL)
        elif kind == "made":
            self.done_jobdir = self.maker.jobdir if self.maker else None
            self.show_done(msg[1])
        elif kind == "stopped":
            self.maker = None
            self.book = None
            self.show_setup()
        elif kind == "error":
            self.maker = None
            self._poll_error(msg[2])
            chime()
            messagebox.showerror(APP, f"Something went wrong:\n\n{msg[1][:600]}\n\nWhat was read so far "
                                      "is kept. Press Resume to try again.")
            self.book = None
            self.show_setup()


def _fix_shortcut():
    # put the ReadAloud icon right if it leads somewhere else (the installed copy only)
    try:
        import shortcuts
        shortcuts.ensure_readaloud_shortcut()
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=_fix_shortcut, daemon=True).start()
    App().mainloop()
