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

APP = "ReadAloud"
APP_DATA = engine.APP_DATA
SETTINGS = APP_DATA / "readaloud_settings.json"
SAVE_PLACES = APP_DATA / "save_places.json"     # CleanListen's chosen M4B folder (Audiobookshelf)
BG, CARD, INK, MUTED, ACCENT, ACCENT_DK, LINE = (
    "#F6F3EE", "#FFFFFF", "#23211F", "#5C5852", "#2F6F62", "#24574D", "#E3DED6")
GO, GO_DK, BUTTON_EDGE = "#1E7E34", "#17652A", "#B9AFA2"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
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
        return f"{max(1, m)} minutes"
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
        self.watch = freezes.Watch(self, APP, APP_DATA, "readaloud_")
        self.watch.start()
        self.after(100, self._poll)

    # ---------- look ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        s.configure("TCheckbutton", background=CARD, font=(FONT, 10))
        s.configure("Card.TRadiobutton", background=CARD, font=(FONT, 10))
        s.map("Card.TRadiobutton", background=[("active", CARD)])
        s.map("TCheckbutton", background=[("active", CARD)])
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
        s.configure("Small.TButton", background="#ECE7E0", foreground=INK, padding=(8, 1),
                    borderwidth=1, font=(FONT, 9), **edge)
        s.map("Small.TButton", background=[("active", "#E0D9CF")])
        s.configure("Green.Horizontal.TProgressbar", troughcolor="#E6E1DA",
                    background=ACCENT, bordercolor="#E6E1DA", lightcolor=ACCENT, darkcolor=ACCENT)
        s.configure("TCombobox", padding=4)

    def destroy(self):
        if getattr(self, "watch", None):
            self.watch.stop()
        super().destroy()

    def _new_page(self, title, subtitle="", name=""):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = title
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=(20, 16))
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(12, 0))
        if name:
            tk.Label(self.page, text=name, bg=BG, fg=ACCENT_DK, font=(FONT, 16, "bold"),
                     wraplength=760, justify="left").pack(anchor="w", pady=(0, 2))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(FONT, 20, "bold"),
                 wraplength=760, justify="left").pack(anchor="w")
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 11),
                     wraplength=740, justify="left").pack(anchor="w", pady=(2, 12))
        return self.page

    def _logo(self, parent):
        """The logo in the middle of the empty space below (Jason: "a lot of dead space")."""
        import base64
        png = logo_png(128)
        try:
            img = tk.PhotoImage(data=base64.b64encode(png).decode()) if png else None
        except tk.TclError:
            img = None
        if img is None:
            return
        self._logo_img = img
        mid = tk.Frame(parent, bg=BG)
        mid.pack(fill="both", expand=True)
        tk.Label(mid, image=img, bg=BG).place(relx=0.5, rely=0.45, anchor="center")

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
        if step:
            tk.Label(top, text=step, bg=ACCENT, fg="white", font=(FONT, 10, "bold"),
                     width=2).pack(side="left", padx=(0, 10))
        tk.Label(top, text=heading, bg=CARD, fg=INK, font=(FONT, 12, "bold")).pack(side="left")
        if note:
            tk.Label(top, text=note, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=8)
        body = tk.Frame(c, bg=CARD)
        body.pack(fill="x", pady=(8, 0), padx=(32 if step else 0, 0))
        return body

    def _note(self, parent, text, bg=CARD, pad=0):
        tk.Label(parent, text=text, bg=bg, fg=MUTED, font=(FONT, 9), wraplength=640,
                 justify="left").pack(anchor="w", padx=(pad, 0))

    def _link(self, parent, text, cmd, bg=CARD):
        lbl = tk.Label(parent, text=text, bg=bg, fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        lbl.bind("<Button-1>", lambda e: cmd())
        return lbl

    # ---------- page 1: the book, the voice, the chapters ----------
    def show_setup(self):
        p = self._new_page(APP, "Turns an ebook into an audiobook, read by a natural-sounding voice. "
                                "Free, and it all happens on this computer.")
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:
            tk.Label(p, text="✓ " + upd, bg="#E3EFEC", fg=ACCENT_DK, font=(FONT, 10),
                     padx=10, pady=6, anchor="w").pack(fill="x", pady=(0, 8))
        try:
            ver = json.loads((HERE / "version.json").read_text())["version"]
            self.title(f"{APP} {ver}")
        except Exception:
            pass
        self.start_btn = ttk.Button(self.footer, text="Make audiobook", style="Main.TButton",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")
        body = self._scroll_area(p)
        st = self.settings

        for jobdir, job, got, n in engine.unfinished_jobs()[:2]:
            c = self._card(body, "", f"Resume “{job.get('title', 'your book')}”?")
            self._note(c, f"{got} of {n} chapters were read aloud before it stopped "
                          f"({engine.voice_label(job)}).")
            row = tk.Frame(c, bg=CARD)
            row.pack(anchor="w", pady=(8, 0))
            ttk.Button(row, text="Resume", style="Go.TButton",
                       command=lambda d=jobdir, j=job: self.resume(d, j)).pack(side="left")
            ttk.Button(row, text="Forget it", style="Plain.TButton",
                       command=lambda d=jobdir: self.forget(d)).pack(side="left", padx=8)

        # 1. the book
        b1 = self._card(body, "1", "Ebook", "EPUB, PDF, Word or TXT — not copy-protected")
        row = tk.Frame(b1, bg=CARD)
        row.pack(fill="x")
        self.cover_lbl = tk.Label(row, bg=CARD)
        self.cover_lbl.pack(side="left", padx=(0, 12))
        col = tk.Frame(row, bg=CARD)
        col.pack(side="left", fill="x", expand=True)
        ttk.Button(col, text="Choose ebook…", style="Go.TButton", command=self.pick_book).pack(anchor="w")
        self.book_lbl = tk.Label(col, text="No book chosen yet", bg=CARD, fg=MUTED, font=(FONT, 10),
                                 wraplength=520, justify="left")
        self.book_lbl.pack(anchor="w", pady=(6, 0))
        self._note(b1, "Want it clean? Make a clean copy in CleanRead first, then choose that copy here. "
                       "Kindle books are copy-protected and can't be read.")

        # 2. the voice: which reader (Lauren chooses by book), then which voice
        b2 = self._card(body, "2", "Voice")
        self.reader_var = tk.StringVar(value=st.get("reader") if st.get("reader") in gpu.READERS else "acting")
        for r in gpu.READER_ORDER:
            name, desc = gpu.READERS[r][:2]
            hint = "" if r == "kokoro" else "  (graphics card)"
            ttk.Radiobutton(b2, text=f"{name}{'  (best)' if r == 'acting' else ''}  —  {desc}{hint}",
                            value=r, variable=self.reader_var, command=self._reader_changed,
                            style="Card.TRadiobutton").pack(anchor="w")
        self.reader_row = tk.Frame(b2, bg=CARD)
        self.reader_row.pack(fill="x", pady=(4, 6), padx=(22, 0))
        self.reader_lbl = tk.Label(self.reader_row, text="", bg=CARD, fg=MUTED, font=(FONT, 9),
                                   wraplength=560, justify="left")
        self.reader_lbl.pack(anchor="w")
        self.setup_btn = ttk.Button(self.reader_row, text="Set up", style="Go.TButton", command=self.set_up_reader)
        row = tk.Frame(b2, bg=CARD)
        row.pack(fill="x")
        self.voice_box = ttk.Combobox(row, state="readonly", width=46, values=VOICE_LABELS)
        self.voice_box.pack(side="left")
        self.voice_box.bind("<<ComboboxSelected>>", lambda e: self._remember())
        self.hear_btn = ttk.Button(row, text="▶ Hear it", style="Go.TButton", command=self.hear)
        self.hear_btn.pack(side="left", padx=(10, 0))
        ttk.Button(row, text="■ Stop", style="Small.TButton", command=stop_playing).pack(side="left", padx=6)
        row2 = tk.Frame(b2, bg=CARD)
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="Reading speed:", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.speed_box = ttk.Combobox(row2, state="readonly", width=14, values=list(engine.SPEEDS))
        names = list(engine.SPEEDS)
        self.speed_box.current(names.index(st.get("speed")) if st.get("speed") in names else 1)
        self.speed_box.pack(side="left", padx=8)
        self.speed_box.bind("<<ComboboxSelected>>", lambda e: (self._remember(), self._book_text()))
        self.sample_lbl = tk.Label(b2, text="Press ▶ Hear it to listen to a few sentences of your book.",
                                   bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=640, justify="left")
        self.sample_lbl.pack(anchor="w", pady=(6, 0))
        self._reader_changed(remember=False)

        # 3. the reading director (readaloud_ai): Claude / ChatGPT / Gemini go through the book first
        bd = self._card(body, "3", "Reading director", "optional, uses your own Claude or ChatGPT plan")
        row = tk.Frame(bd, bg=CARD)
        row.pack(anchor="w")
        self.director_var = tk.BooleanVar(value=st.get("director", True))
        ttk.Checkbutton(row, text="Have", variable=self.director_var,
                        command=self._director_changed).pack(side="left")
        self.ai_box = ttk.Combobox(row, state="readonly", width=9, values=list(AI_NAMES.values()))
        saved = st.get("ai") if st.get("ai") in AI_NAMES else _saved_ai()
        self.ai_box.current(list(AI_NAMES).index(saved))
        self.ai_box.pack(side="left", padx=4)
        self.ai_box.bind("<<ComboboxSelected>>", lambda e: self._director_changed())
        tk.Label(row, text="go through the book first and direct the reading", bg=CARD, fg=INK,
                 font=(FONT, 10)).pack(side="left")
        self._note(bd, "It takes out what shouldn't be read aloud (page numbers, headings at the top of "
                       "pages, jacket text, scanning mistakes), works out who is speaking and how each part "
                       "should be read (the feeling of each line for the Qwen acting voice, slower, "
                       "faster, pauses), and looks up how to say the names. It adds about 10 minutes "
                       "before the reading starts, and you get a list of everything it changed.", pad=22)
        self.cast_var = tk.BooleanVar(value=st.get("cast", False))
        self.cast_check = ttk.Checkbutton(bd, text="Give the characters their own voices  (men and women "
                                          "in the story; the narrator keeps the voice above)",
                                          variable=self.cast_var, command=self._remember)
        self.cast_check.pack(anchor="w", pady=(8, 0))
        srow = tk.Frame(bd, bg=CARD)
        srow.pack(anchor="w", pady=(6, 0))
        self.ai_status = tk.Label(srow, text="", bg=CARD, fg=MUTED, font=(FONT, 9))
        self.ai_status.pack(side="left")
        self.ai_btn = ttk.Button(srow, text="Set up / sign in", style="Small.TButton", command=self._sign_in)
        self.ai_ok = None
        self._director_changed(check=True)

        # 4. the chapters
        b3 = self._card(body, "4", "What to read")
        self.ch_host = tk.Frame(b3, bg=CARD)
        self.ch_host.pack(fill="x")
        tk.Label(self.ch_host, text="Choose a book first.", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(anchor="w")

        # 4. where it goes
        b4 = self._card(body, "5", "Save to")
        row = tk.Frame(b4, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Change…", style="Plain.TButton", command=self.pick_folder).pack(side="right")
        self.out_lbl = tk.Label(row, text="Next to the ebook", bg=CARD, fg=MUTED, font=(FONT, 10),
                                wraplength=520, justify="left")
        self.out_lbl.pack(side="left")
        places = load_json(SAVE_PLACES)
        self.folder = st.get("folder") or places.get("m4b_dir") or None
        self.abs_var = tk.BooleanVar(value=st.get("abs", bool(places.get("abs"))))
        ttk.Checkbutton(b4, text="Put it in Audiobookshelf's folders  (Author \\ Series \\ Book 2 - Title)",
                        variable=self.abs_var, command=self._abs_changed).pack(anchor="w", pady=(10, 0))
        self.abs_row = tk.Frame(b4, bg=CARD)
        tk.Label(self.abs_row, text="Series:", bg=CARD, font=(FONT, 10)).pack(side="left")
        self.series_var = tk.StringVar()
        ttk.Entry(self.abs_row, textvariable=self.series_var, width=28).pack(side="left", padx=(6, 14))
        tk.Label(self.abs_row, text="Book number:", bg=CARD, font=(FONT, 10)).pack(side="left")
        self.number_var = tk.StringVar()
        ttk.Entry(self.abs_row, textvariable=self.number_var, width=6).pack(side="left", padx=6)
        self.mp3_var = tk.BooleanVar(value=st.get("mp3", False))
        self.mp3_check = ttk.Checkbutton(b4, text="Also make MP3 chapter files  (for a Yoto or an older player)",
                                         variable=self.mp3_var, command=self._remember)
        self.mp3_check.pack(anchor="w", pady=(8, 0))
        self._note(b4, "The audiobook is one M4B file with chapters and the book's cover. It plays in "
                       "Audiobookshelf, Apple Books, BookPlayer, Smart AudioBook Player and VLC.")
        self._abs_changed()
        if self.book:
            self._show_book()

    # ---------- which reader ----------
    def _reader(self):
        try:
            return self.reader_var.get()
        except (tk.TclError, AttributeError):
            return "kokoro"

    def _voice_id(self):
        i = max(0, self.voice_box.current())
        return gpu.NARRATORS[i] if gpu.is_gpu(self._reader()) else engine.VOICES[i][0]

    def _reader_changed(self, remember=True):
        r = self._reader()
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
            self.reader_lbl.config(text=self.gpu_ok[1], fg="#9A2F1F")
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
        self.cast_check.config(state="normal" if on else "disabled")
        self.ai_box.config(state="readonly" if on else "disabled")
        self._remember()
        self.ai_btn.pack_forget()
        if not on:
            self.ai_status.config(text="")
            return
        ai = list(AI_NAMES)[self.ai_box.current()]
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
        ai = list(AI_NAMES)[self.ai_box.current()]
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
            self.abs_row.pack(anchor="w", pady=(6, 0), before=self.mp3_check)
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
            st["ai"] = list(AI_NAMES)[self.ai_box.current()]
            st["cast"] = self.cast_var.get()
        except (tk.TclError, AttributeError, IndexError):
            pass
        if self.folder:
            st["folder"] = self.folder
        save_settings(st)

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
        self.chapter_vars = [tk.BooleanVar(value=c["read"]) for c in b["chapters"]]
        self.ch_summary = tk.Label(self.ch_host, bg=CARD, fg=INK, font=(FONT, 10), wraplength=640,
                                   justify="left")
        self.ch_summary.pack(anchor="w")
        top = tk.Frame(self.ch_host, bg=CARD)
        top.pack(fill="x", pady=(4, 0))
        self.ch_toggle = self._link(top, "Show the chapters ▾", self._toggle_chapters)
        self.ch_toggle.pack(side="left")
        self.ch_box = tk.Frame(self.ch_host, bg=CARD)
        self.ch_open = False
        self._book_text()
        self._show_folder()

    def _toggle_chapters(self):
        """The chapter list is folded away (a novel has 30+), so the page fits."""
        self.ch_open = not self.ch_open
        self.ch_toggle.config(text="Hide the chapters ▴" if self.ch_open else "Show the chapters ▾")
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
                self.sample_lbl.config(text=f"Couldn't play the voice: {ex}", fg="#9A2F1F")
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
                why = f"The {name} voice is still being set up. Wait for it to finish (it shows under 2. Voice)."
            elif self.gpu_ok is None:
                why = "ReadAloud is still checking the graphics card. Try again in a moment."
            elif not self.gpu_ok[0]:
                why = f"The {name} voice can't be used yet:\n\n{self.gpu_ok[1]}"
            else:
                why = (f"The {name} voice needs a one-time setup first: press the green Set up button "
                       "under 2. Voice.")
            messagebox.showinfo(APP, why + "\n\nOr choose the Quick voice, which works on any computer.")
            return
        extra = {"mp3": self.mp3_var.get(), "reader": reader}
        if self.director_var.get():
            ai = list(AI_NAMES)[self.ai_box.current()]
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
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=30)
        self.pb = ttk.Progressbar(box, style="Green.Horizontal.TProgressbar", maximum=1000, length=640)
        self.pb.pack(fill="x")
        self.status = tk.Label(box, text="Starting…", bg=BG, fg=INK, font=(FONT, 12), wraplength=740,
                               justify="left")
        self.status.pack(anchor="w", pady=(12, 0))
        self.left_lbl = tk.Label(box, text="Working out how long it will take…", bg=BG, fg=MUTED,
                                 font=(FONT, 11))
        self.left_lbl.pack(anchor="w", pady=(4, 0))
        try:
            reader = json.loads((Path(jobdir) / "job.json").read_text(encoding="utf8")).get("reader", "kokoro")
        except Exception:
            reader = "kokoro"
        how = (f"Reading with the {gpu.READERS[reader][0]} voice on the graphics card. Each line is "
               "listened to and read again if a word came out wrong." if gpu.is_gpu(reader) else
               f"Reading {n} chapter{'s' if n > 1 else ''} at a time.")
        tk.Label(box, text=how, bg=BG, fg=MUTED, font=(FONT, 11), wraplength=740,     # Jason: "bigger"
                 justify="left").pack(anchor="w", pady=(16, 0))
        self._logo(p)
        self.stop_btn = ttk.Button(self.footer, text="Stop for now", style="Plain.TButton", command=self.stop)
        self.stop_btn.pack(side="right")
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
        tk.Label(p, text=f"{f.name}\n{hours_text(res['hours'])} · {res['chapters']} chapters",
                 bg=BG, fg=INK, font=(FONT, 12), justify="left").pack(anchor="w", pady=(12, 4))
        tk.Label(p, text=os.path.normpath(str(f.parent)), bg=BG, fg=MUTED, font=(FONT, 10),
                 wraplength=740, justify="left").pack(anchor="w")
        if res.get("report"):
            row0 = tk.Frame(p, bg=BG)
            row0.pack(anchor="w", pady=(8, 0))
            self._link(row0, "See what the reading director left out and changed",
                       lambda: open_path(res["report"]), bg=BG).pack(side="left")
        if res.get("mp3_dir"):
            tk.Label(p, text=f"MP3 chapter files: {os.path.normpath(res['mp3_dir'])}", bg=BG, fg=MUTED,
                     font=(FONT, 10), wraplength=740, justify="left").pack(anchor="w", pady=(6, 0))
        row = tk.Frame(p, bg=BG)
        row.pack(anchor="w", pady=20)
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
            if ai != list(AI_NAMES)[self.ai_box.current()]:
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
                self.ai_status.config(text=f"Couldn't set up {name}: {st[6:]}", fg="#9A2F1F")
                self.ai_btn.pack(side="left", padx=8)
            else:
                self.ai_ok = False
                self.ai_status.config(text=f"{name} isn't set up on this computer yet." if st == "missing"
                                      else f"{name} isn't signed in.", fg="#9A2F1F")
                self.ai_btn.pack(side="left", padx=8)
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
                self.sample_lbl.config(text="Couldn't play the voice: " + msg[1], fg="#9A2F1F")
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
