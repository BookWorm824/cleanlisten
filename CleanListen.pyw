"""CleanListen — a simple window for cleaning up audiobooks you own."""
import copy
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanlisten as engine  # noqa: E402
import filters as F  # noqa: E402  (the filters, shared with CleanRead)
import logo as LOGO  # noqa: E402  (the logo in a page's empty space)
import cvlook as look  # noqa: E402  (the drawn look: cards, switches, pill buttons; CleanView's)
import cllook as CL  # noqa: E402  (the step-by-step start page, shared with CleanRead)
import freezes  # noqa: E402  (noticing a freeze or a crash, shared with CleanRead)
import bookqueue as BQ  # noqa: E402  (several books at once, each in its own worker)
import dropfiles  # noqa: E402  (dropping the cover picture on the window)

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
HERE = Path(__file__).resolve().parent
RESUME = APP_DATA / "resume.json"     # your review, kept across an update or closing the window
LEFT = APP_DATA / "left_review.json"  # a review you went "Back to start" from, to pick up again
QUEUE = APP_DATA / "queue.json"       # the books on the "Your books" page (bookqueue.py)
# the review list in blocks (Windows draws no window taller than 32,767 px); see _scroll_area
BLOCK_ITEMS = 40
WORDS_PER_BOX = 50
# where the chapter files and the M4B go when not the usual place (kept for the next book)
PLACES = APP_DATA / "save_places.json"


def cover_thumbnail(pic, size=72):
    """A small PNG of a cover picture (tkinter shows PNG, not JPG), kept in CleanListen's own
    folder (never next to the picture: that may be the book's folder)."""
    try:
        st = Path(pic).stat()
        key = hashlib.sha1(f"{pic}|{st.st_size}|{st.st_mtime}|{size}".encode()).hexdigest()[:16]
    except OSError:
        return None
    dst = APP_DATA / "covers" / "small" / f"{key}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        engine.run([engine._tool("ffmpeg"), "-y", "-v", "error", "-i", str(pic), "-vf",
                    f"scale={size}:{size}:force_original_aspect_ratio=decrease", "-frames:v", "1",
                    str(dst)], capture_output=True)
    return str(dst) if dst.exists() else None


def load_places():
    try:
        d = json.loads(PLACES.read_text(encoding="utf8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_places(d):
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        PLACES.write_text(json.dumps(d, indent=1), encoding="utf8")
    except OSError:
        pass


def chime():
    """The Windows "information" sound, so a question is heard like the other boxes
    (a yes/no box is silent on Windows; Jason missed the "Send it in now?" one)."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def app_version():
    try:
        return json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        return "?"
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


def _to_decide(it, key, note_key):
    """Worth a look: left unticked for you to decide, or the checker wasn't sure."""
    return not it.get(key, True) or bool(re.search(r"unsure|suggests|questioned|Your call",
                                                   it.get(note_key) or ""))


# the review screen's "Show:" choices
REVIEW_VIEWS = (("list", "Everything to remove"), ("decide", "Only the ones to decide"),
                ("ticked", "Only what's ticked"), ("all", "Everything, even what's marked fine"))
# passage groups on the review screen: kind, heading, short name for "Jump to"
REVIEW_KINDS = (("sex", "Explicit scenes to cut", "Explicit"),
                ("ref", "Sexual references to cut", "Sexual references"),
                ("gore", "Gore to cut", "Gore"),
                ("religion", "Religious content to cut", "Religious"),
                ("relationship", "Same-sex & non-traditional relationships to cut", "Relationships"),
                ("crude", "Crude humor to cut", "Crude humor"), ("bully", "Bullying to cut", "Bullying"),
                ("disrespect", "Disrespect to cut", "Disrespect"),
                ("graphic", "Graphic violence to cut", "Graphic"),
                ("violence", "Violence to cut", "Violence"),
                ("disturbing", "Disturbing violence to cut", "Disturbing"),
                ("medical", "Medical scenes to cut", "Medical"),
                ("nudity", "Nudity to cut", "Nudity"), ("implied", "Implied nudity to cut", "Implied"),
                ("immodest", "Immodest clothing to cut", "Immodest"),
                ("flirt", "Flirting to cut", "Flirting"), ("kiss", "Man & woman kissing to cut", "Kissing"),
                ("kiss_ss", "Same-sex kissing to cut", "Same-sex kissing"),
                ("sleeping", "Sleeping around & affairs to cut", "Sleeping around"),
                ("unmarried", "Unmarried couples together to cut", "Unmarried"),
                ("smoking", "Smoking to cut", "Smoking"), ("drinking", "Drinking to cut", "Drinking"),
                ("drugs", "Drug use to cut", "Drugs"), ("gestures", "Rude gestures to cut", "Gestures"),
                ("holiday", "Holidays to cut", "Holidays"),
                ("birthday", "Candles on a birthday cake to cut", "Birthday candles"),
                ("magic", "Magic to cut", "Magic"), ("darkmagic", "Dark magic to cut", "Dark magic"),
                ("vampires", "Vampires & werewolves to cut", "Vampires"),
                ("added", "Added by you (or cut before)", "Added"))
CAT_LABELS = {"strong": "swearing", "moderate": "swearing", "mild": "mild word", "deity": "God's name",
              "minced": "soft swear", "sexual": "sexual word", "orientation": "orientation",
              "rude": "rude word", "mine": "your own word"}


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


# folders that hold all sorts of things, never one book (a book sitting straight in Downloads
# was called "Downloads": Jason, 2026-11-06)
NOT_BOOK_FOLDERS = {"downloads", "desktop", "documents", "my documents", "music", "audiobooks",
                    "audible", "onedrive", "temp", "tmp"}


def book_title(files):
    """A readable name for a book: the file's own name for one file ("My Book" for My Book.m4b),
    the folder's name for a folder of chapter files, the folder above Disc 1, Disc 2..."""
    files = [Path(f) for f in files]
    first = files[0]
    parents = {str(f.parent) for f in files}
    if len(files) == 1:
        return first.stem
    if len(parents) > 1 and first.parent.parent.name.lower() not in NOT_BOOK_FOLDERS:
        return first.parent.parent.name or first.stem
    if len(parents) == 1 and first.parent.name.lower() not in NOT_BOOK_FOLDERS:
        return first.parent.name or first.stem
    # chapter files loose in Downloads: "My Book - Part 01.mp3" -> "My Book"
    bare = {re.sub(r"[\s_-]*(part|pt|disc|cd|chapter|ch)?[\s_.-]*\d+$", "", f.stem, flags=re.I).strip()
            for f in files}
    return bare.pop() if len(bare) == 1 and "" not in bare else first.stem


def fix_title(title, files):
    """A name saved by 1.16.1 or older, which called a book "Downloads" (or "Desktop"...) because
    it sat straight in that folder: the right name instead. Any other name is kept as it is."""
    try:
        files = [Path(f) for f in files or []]
        if not files:
            return title
        old = (files[0].parent.parent.name if len({str(f.parent) for f in files}) > 1
               else files[0].parent.name)
        if title and title == old and old.lower() in NOT_BOOK_FOLDERS and title != book_title(files):
            return book_title(files)
    except Exception:
        pass
    return title


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
                        "outdir": info.get("outdir"),
                        "title": fix_title(info.get("title"), parts) or book_title(parts),
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
        h = min(int(880 * scale), sh - 90)
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
        use_theme(F.load().get("theme"))      # light or dark, before anything is drawn
        self.configure(bg=BG)
        self.after(50, lambda: CL.title_bar(self))
        # the books being prepared, ready to review or saving (the "Your books" page); each
        # runs in its own worker process, so one book's trouble never stops the window
        self.books = BQ.BookQueue(QUEUE)
        for j in self.books.jobs:   # names saved by 1.16.1 and older ("Downloads")
            j["title"] = fix_title(j.get("title"), j.get("audio"))
        self.books.resume()
        self.workers = BQ.Workers(lambda key, msg: self.q.put(("job", key, msg)))
        self.review_key = None   # the book in the queue whose review is open
        self._open_rows, self._rows = set(), {}
        self._style()
        self.page = None
        self.page_name = None
        self.show_setup()
        self.watch = freezes.Watch(self, 'CleanListen', APP_DATA, '')
        self.watch.start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore()
        if self.page_name != "review" and not self.audio and self.books.jobs:
            self.show_queue()       # back to your books, and they carry on
        self.after(300, self._run_queue)

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
        s.map("Accent.TButton", background=[("active", ACCENT_DK), ("disabled", DISABLED)])
        s.configure("Main.TButton", background=GO, foreground="white",
                    font=(FONT, 15, "bold"), padding=(28, 7), borderwidth=0)
        s.map("Main.TButton", background=[("active", GO_DK), ("disabled", GO_OFF)])
        s.configure("Go.TButton", background=ACCENT, foreground="white",
                    font=(FONT, 11, "bold"), padding=(14, 4), borderwidth=0)
        s.map("Go.TButton", background=[("active", ACCENT_DK), ("disabled", DISABLED)])
        s.configure("Bg.TCheckbutton", background=BG, font=(FONT, 10))
        s.map("Bg.TCheckbutton", background=[("active", BG)])
        edge = {"bordercolor": BUTTON_EDGE, "lightcolor": GREY, "darkcolor": GREY}
        s.configure("Plain.TButton", background=GREY, foreground=INK, padding=(14, 6),
                    borderwidth=1, font=(FONT, 10), **edge)
        s.map("Plain.TButton", background=[("active", GREY_HOVER)])
        s.configure("Plain.TMenubutton", background=GREY, foreground=INK, padding=(14, 6),
                    borderwidth=1, font=(FONT, 10), arrowcolor=INK, **edge)
        s.map("Plain.TMenubutton", background=[("active", GREY_HOVER)])
        s.configure("Green.Horizontal.TProgressbar", troughcolor=TROUGH,
                    background=ACCENT, bordercolor=TROUGH, lightcolor=ACCENT, darkcolor=ACCENT)
        # the drawn look (the owner, 2026-11-13, as CleanView 1.18.77): rounded buttons, thin scroll
        # bars, a rounded progress bar, soft fields and smooth tick boxes with a real tick
        CL.style(self, s, checks=("TCheckbutton", "Bg.TCheckbutton"))

    def destroy(self):
        self._stop_books()
        if getattr(self, "watch", None):     # stops the freeze watcher; the crash log is closed
            self.watch.stop()
        super().destroy()

    def _stop_books(self):
        """The window is closing (or updating): the books being worked on stop after the bit
        they're on and carry on from there next time (bookqueue.BookQueue.resume)."""
        if getattr(self, "workers", None) and self.workers.procs:
            self.workers.stop_all()
        if getattr(self, "books", None):
            self.books.save()

    def _new_page(self, title, subtitle="", name=""):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = title
        self._stop_playing()
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=(20, 10))
        # Buttons live in a footer packed first, so they always stay visible
        # even when the window is short.
        self.footer = tk.Frame(self.page, bg=BG)
        self.footer.pack(side="bottom", fill="x", pady=(8, 0))
        tk.Frame(self.footer, bg=LINE, height=1).pack(side="top", fill="x", pady=(0, self._px(10)))
        if name:                # which book this is (Jason: "you don't know what you've cleaned")
            tk.Label(self.page, text=name, bg=BG, fg=ACCENT, font=(HEAD, 11),
                     wraplength=560, justify="left").pack(anchor="w", pady=(0, 2))
        tk.Label(self.page, text=title, bg=BG, fg=INK, font=(HEAD, 21)).pack(anchor="w")
        self.page_name = "other"
        # "Check for updates" on every screen: updates and comes straight back to where you were
        self._upd_lbl = tk.Label(self.page, text=f"v{app_version()} \u00b7 Check for updates", bg=BG,
                                 fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
        self._upd_lbl.place(relx=1.0, y=2, anchor="ne")
        self._upd_lbl.bind("<Button-1>", lambda e: self.check_updates())
        self._books_lbl = None
        if getattr(self, "books", None) is not None and self.books.jobs:
            self._books_lbl = tk.Label(self.page, text="", bg=BG, fg=ACCENT, font=(FONT, 10, "bold underline"),
                                       cursor="hand2")
            self._books_lbl.place(relx=1.0, y=24, anchor="ne")
            self._books_lbl.bind("<Button-1>", lambda e: self._to_books())
            self._show_books_count()
        if subtitle:
            tk.Label(self.page, text=subtitle, bg=BG, fg=MUTED, font=(FONT, 10),
                     wraplength=700, justify="left").pack(anchor="w", pady=(4, 12))
        return self.page

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

    def _scroll_area(self, parent, stacked=False):
        """A vertically scrolling area that fills the remaining space. Returns the frame to put
        things in, or with stacked=True a function that returns the block to put the next thing
        in (block(new=True) starts a new one). Windows can't draw a window taller than 32,767
        pixels, so a long review list in one frame went blank part way down (Sweetbriar Cottage,
        2026-11-05: 290 passages); stacked, it's blocks of at most BLOCK_ITEMS, one under another."""
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self._canvas = canvas
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        blocks = []          # (frame, canvas item), top to bottom
        pending = {}

        def add_block():
            f = tk.Frame(canvas, bg=BG)
            item = canvas.create_window((0, 0), window=f, anchor="nw",
                                        width=max(1, canvas.winfo_width()))
            blocks.append((f, item))
            f.bind("<Configure>", refresh)
            return f

        last = {}

        def layout():
            """Put the blocks one under another. Blocks out of view don't say when their size
            changes, so this also runs whenever the view moves (cheap when nothing changed)."""
            pending.pop("job", None)
            if not canvas.winfo_exists():
                return
            width, view_h = max(1, canvas.winfo_width()), canvas.winfo_height()
            pos, y = [], 0
            for f, _ in blocks:
                pos.append(y)
                y += f.winfo_reqheight()
            if last.get("key") == (pos, y, width, view_h):
                return
            last["key"] = (pos, y, width, view_h)
            for (f, item), top in zip(blocks, pos):
                canvas.coords(item, 0, top)
                canvas.itemconfigure(item, width=width)
            canvas.configure(scrollregion=(0, 0, width, y))
            # keep the view inside the list: when it gets shorter (the cards settle to their
            # size), Tk can leave the view past its end, with nothing drawn there
            if canvas.canvasy(0) > max(0, y - view_h):
                canvas.yview_moveto(max(0, y - view_h) / max(1, y))
            needs = y > view_h + 2
            if needs and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")
            elif not needs and sb.winfo_ismapped():
                sb.pack_forget()

        def refresh(_=None):
            if "job" not in pending:
                pending["job"] = canvas.after_idle(layout)

        def scrolled(*a):
            sb.set(*a)
            refresh()

        def keep_up():
            # (sizes change without an event out of view; this catches them)
            if canvas.winfo_exists():
                layout()
                canvas.after(300, keep_up)

        inner = add_block()
        self._inner = inner
        inner._canvas = canvas
        canvas.bind("<Configure>", refresh)
        canvas.configure(yscrollcommand=scrolled)
        if stacked:
            canvas.after(300, keep_up)
        canvas.pack(side="left", fill="both", expand=True)

        def wheel(delta):
            if self._list_height() > canvas.winfo_height():
                canvas.yview_scroll(delta, "units")

        self.bind_all("<MouseWheel>", lambda e: wheel(int(-e.delta / 120)))
        self.bind_all("<Button-4>", lambda e: wheel(-2))
        self.bind_all("<Button-5>", lambda e: wheel(2))
        if not stacked:
            return inner

        def block(new=False):
            f = blocks[-1][0]
            if new and f.winfo_children() or len(f.winfo_children()) >= BLOCK_ITEMS:
                f = add_block()
            return f
        return block

    def _list_height(self):
        """How tall everything in the scrolling area is (all its blocks)."""
        try:
            box = self._canvas.bbox("all")
            return max(1, box[3] - min(0, box[1])) if box else 1
        except Exception:
            return 1

    # ---------- page 1: setup, one step at a time ----------
    # The owner, 2026-11-13 (CleanView 1.18.77's "B, step by step"): the steps down the left, each
    # saying what's chosen, one step on the right, Back / Next, and the green button always there.
    STEPS = [("Audiobook", "Choose the book to clean. Your original files are never changed."),
             ("What to remove", "Bad words are muted; everything else is listed for you to check "
                                "before anything is cut."),
             ("Extra checks", "Optional helpers that catch what the word lists miss."),
             ("Save to", "Where the clean audiobook goes, and what else to make.")]

    def _theme_var(self):
        self.theme_var = tk.StringVar(value=THEME)
        return self.theme_var

    # ---------- the language the book is read in ----------

    def _language_chosen(self, *_):
        """Kept with the book's other choices (saved_opts), so checking it again keeps it."""
        self.saved_opts["language"] = engine.cvlang.known(self.lang_var.get())
        sp = getattr(self, "steps_page", None)
        if sp is not None:
            sp.refresh()

    def _set_language(self, code):
        self.saved_opts["language"] = engine.cvlang.known(code)
        var = getattr(self, "lang_var", None)
        if var is not None and var.get() != self.saved_opts["language"]:
            try:
                var.set(self.saved_opts["language"])
            except tk.TclError:
                pass

    def _language_of_new_book(self):
        """A newly chosen book starts as English, or as its ebook's language when that's plain,
        so Spanish left from the last book is never used on an English one by accident."""
        self._set_language((engine.guess_language(self.ebook) if self.ebook else None) or "en")

    def _keep_for_rebuild(self):
        """The start page's choices that are only read when Start is pressed, kept while the page
        is built again (a new look)."""
        try:
            self.saved_opts.update(ai=self.ai_var.get(), claude=self.claude_var.get(),
                                   split=self.split_var.get(), m4b=self.m4b_var.get())
            self.author = self.author_var.get()
            self.series, self.series_no = self.series_var.get(), self.series_no_var.get()
        except (AttributeError, tk.TclError):
            pass

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

    def _step_summary(self, n):
        """What's chosen in step n, in a few words, for the list on the left."""
        if n == 1:
            k = len(self.audio or ())
            lang = engine.cvlang.known(self.saved_opts.get("language"))
            return ("No audiobook chosen yet" if not k else "1 file chosen" if k == 1 else
                    f"{k} files chosen") + (
                        "" if lang == "en" else " \u00b7 " + engine.cvlang.name(lang))
        if n == 2:
            card = getattr(self, "filter_card", None)
            return dict(F.PROFILES).get(card.profile.get(), "") if card else ""
        if n == 3:
            ai = getattr(self, "ai_var", None) is not None and self.ai_var.get()
            final = getattr(self, "claude_var", None) is not None and self.claude_var.get()
            return ("AI helper and final check" if ai and final else "AI helper" if ai else
                    "Final check" if final else "Off")
        if self.outdir:
            return Path(self.outdir).name or str(self.outdir)
        return "A Clean folder next to it"

    def show_setup(self, step=1):
        if getattr(self, "watch", None):
            self.watch.doing["page"] = "CleanListen"
        self._stop_playing()
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        if self.page:
            self.page.destroy()
        X = self._px
        p = self.page = tk.Frame(self, bg=BG)
        p.pack(fill="both", expand=True)
        self.page_name = "other"
        self._books_lbl = None
        try:
            have_past = bool(past_books())
        except Exception:
            have_past = False
        links = [(f"v{app_version()} \u00b7 Check for updates", self.check_updates, "refresh")]
        if have_past:
            links.append(("Re-check a book I've already done\u2026", self.show_past, "back"))
        links.append(("Send what CleanListen learned\u2026", self.share_learned, "send"))
        sp = self.steps_page = CL.StepPage(
            self, p, "CleanListen", LOGO.logo_png("icon.ico", X(40))[0], self.STEPS,
            self._step_summary, ("Start cleaning", self.start), links=links,
            done=lambda i: i == 1 and bool(self.audio), scroll_area=self._scroll_area, start=step,
            theme=(self._theme_var(), self._set_theme))
        self.footer = sp.nav
        self.start_btn = sp.main_btn
        self.start_btn.config(state="disabled")
        self._upd_lbl = sp.links[links[0][0]].label
        upd = os.environ.pop("CLEANLISTEN_UPDATED", None)
        if upd:         # said for a few seconds, then gone (as CleanView 1.18.84)
            self.updated_note = CL.said_briefly(tk.Label(
                sp.top, text="\u2713 " + upd, bg=TINT, fg=ACCENT_DK, font=(FONT, 10),
                padx=X(12), pady=X(7), anchor="w"))
            self.updated_note.pack(fill="x", pady=(0, X(10)))

        def bar(text, button, command, bold=False):
            box = look.Card(sp.top, fill=TINT, edge=TINT_EDGE, radius=12, pad=(16, 9))
            box.pack(fill="x", pady=(0, X(10)))
            tk.Label(box.body, text=text, bg=TINT, fg=ACCENT_DK, anchor="w", justify="left",
                     font=(HEAD if bold else FONT, 10), wraplength=X(380)).pack(side="left")
            look.Pill(box.body, button, command, kind="secondary", size=10, pad=(16, 7)).pack(
                side="right")
        left = self._left_review()
        if left:
            bar("Your review of \u201c" + (left.get("title") or "a book") + "\u201d is kept.",
                "Pick up where I left off", self._pick_up)
        if self.books.jobs:   # the books already added: back to them with one click
            self._drop_books_link()
            ready = self.books.count(BQ.READY)
            busy = len(self.books.unfinished()) - ready
            bits = ([f"{ready} ready to review"] if ready else []) + (
                [f"{busy} being worked on"] if busy else [])
            bar("Your books: " + (", ".join(bits) if bits else "all saved") + ".",
                "See your books", self.show_queue, bold=bool(ready))
        self._show_books_count()
        self.start_hint = tk.Label(sp.nav, text="Choose an audiobook first", bg=BG, fg=MUTED,
                                   font=(FONT, 9))
        self.start_hint.pack(side="right", padx=(0, X(10)))

        # ----- step 1: the audiobook
        p1 = sp.pane(1)
        self.heard_lbl = tk.Label(p1, text="", bg=TINT, fg=ACCENT_DK, font=(FONT, 10),
                                  padx=X(12), pady=X(7), anchor="w", justify="left",
                                  wraplength=X(540))
        drop = look.Card(p1, fill=SOFT, edge=SOFT_EDGE, radius=16, pad=(20, 18))
        drop.pack(fill="x", padx=(0, X(4)))
        self.b1_outer = drop
        look.Badge(drop.body, "folder", size=54, icon_size=20).pack(side="left")
        words = tk.Frame(drop.body, bg=SOFT)
        words.pack(side="left", fill="x", expand=True, padx=(X(16), X(12)))
        tk.Label(words, text="Choose an audiobook", bg=SOFT, fg=INK, font=(HEAD, 13),
                 anchor="w").pack(anchor="w")
        tk.Label(words, text="A folder of its files, or the files themselves.", bg=SOFT, fg=MUTED,
                 font=(FONT, 9), anchor="w", wraplength=X(200), justify="left").pack(
                     anchor="w", pady=(X(2), 0))
        look.Pill(drop.body, "Choose files\u2026", self.pick_audio, kind="secondary", size=11,
                  pad=(18, 10)).pack(side="right")
        look.Pill(drop.body, "Choose folder\u2026", self.pick_folder, size=11,
                  pad=(18, 10)).pack(side="right", padx=(0, X(8)))
        self.audio_lbl = tk.Label(p1, text="No audiobook chosen yet", bg=BG, fg=MUTED,
                                  font=(FONT, 10), wraplength=X(560), justify="left", anchor="w")
        self.audio_lbl.pack(anchor="w", pady=(X(12), 0))
        b = sp.card(1, top=14)
        look.Badge(b, "text", size=30).pack(side="left", anchor="n")
        words = tk.Frame(b, bg=CARD)
        words.pack(side="left", fill="x", expand=True, padx=(X(14), X(12)))
        tk.Label(words, text="Ebook  (optional)", bg=CARD, fg=INK, font=(HEAD, 10),
                 anchor="w").pack(anchor="w")
        self.ebook_lbl = tk.Label(words, text="catches words the narrator mumbles", bg=CARD,
                                  fg=MUTED, font=(FONT, 9), wraplength=X(330), justify="left",
                                  anchor="w")
        self.ebook_lbl.pack(anchor="w", pady=(X(2), 0))
        look.Pill(b, "Choose ebook\u2026", self.pick_ebook, kind="secondary", size=10,
                  pad=(16, 8)).pack(side="right")
        # the language the book is read in (1.17.30, as CleanView's "Language spoken in the
        # video"; the owner, 2026-11-13: "ask clean view about the language", "update"):
        # English as always, or another one, with its own word lists
        b = sp.card(1, top=10)
        look.Badge(b, "chat", size=30).pack(side="left", anchor="n")
        words = tk.Frame(b, bg=CARD)
        words.pack(side="left", fill="x", expand=True, padx=(X(14), X(12)))
        tk.Label(words, text="Language the book is read in", bg=CARD, fg=INK, font=(HEAD, 10),
                 anchor="w").pack(anchor="w")
        tk.Label(words, text="For another language CleanListen uses that language's own word "
                 "lists, and the other filters lean on the AI helper. The first time, it gets a "
                 f"listening model for it (one time, about {engine.cvlang.MODEL_MB} MB).",
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=X(300), justify="left",
                 anchor="w").pack(anchor="w", pady=(X(2), 0))
        self.lang_var = tk.StringVar(value=engine.cvlang.known(self.saved_opts.get("language")))
        # a drop-down list, so more languages don't crowd the page (as CleanView 1.18.85)
        self.language_box = CL.dropdown(b, self.lang_var, engine.cvlang.LANGS,
                                        command=self._language_chosen)
        self.language_box.pack(side="right")

        # ----- step 2: what to remove (the same filters as CleanRead and CleanView)
        self.filter_card = F.FilterPanel(sp.pane(2), on_change=sp.refresh, wrap=560,
                                         scroll_to=self._scroll_to)

        # ----- step 3: extra checks
        self.ai_var = tk.BooleanVar(value=self.saved_opts.get("ai", True))
        CL.switch_row(sp.card(3), self.ai_var, "AI helper on this PC  (double-checks every filter)",
                      "Catches what the word lists miss. Downloads about 4 GB the first time. "
                      "Works alongside the final check.", command=sp.refresh).pack(fill="x")
        b4 = sp.card(3, top=12)
        self.claude_var = tk.BooleanVar(value=self.saved_opts.get("claude", False))
        CL.switch_row(b4, self.claude_var,
                      "Final check by Claude, ChatGPT or Gemini  (reads the whole book)",
                      "Uses your own plan. Only the book's words are sent, never the audio.",
                      command=sp.refresh).pack(fill="x")
        cc = self._cc()
        # which one, sign-in and model: only shown while the final check is on
        self.claude_more = tk.Frame(b4, bg=CARD)
        prow = tk.Frame(self.claude_more, bg=CARD)
        prow.pack(anchor="w", padx=(X(54), 0), pady=(X(10), 0), fill="x")
        self.provider_var = tk.StringVar(value=cc.PROVIDER if cc else "claude")
        look.Segmented(prow, [("claude", "Claude"), ("chatgpt", "ChatGPT"), ("gemini", "Gemini")],
                       self.provider_var, command=self._provider_changed, size=9).pack(side="left")
        crow = tk.Frame(self.claude_more, bg=CARD)
        crow.pack(anchor="w", padx=(X(54), 0), pady=(X(6), 0), fill="x")
        self.claude_lbl = tk.Label(crow, text="Checking\u2026", bg=CARD, fg=MUTED,
                                   font=(FONT, 9))
        self.claude_lbl.pack(side="left")
        self.claude_btn = ttk.Button(crow, text="Set up / sign in", style="Plain.TButton",
                                     command=self.claude_setup)
        self.model_row = self._model_picker(prow, bg=CARD)
        self._provider_changed(first=True)
        self.claude_var.trace_add("write", lambda *_: self._show_claude_more())
        self._show_claude_more()

        # ----- step 4: where it goes
        b5 = sp.card(4)
        row = tk.Frame(b5, bg=CARD)
        row.pack(fill="x")
        ttk.Button(row, text="Change…", style="Plain.TButton",
                   command=self.pick_out).pack(side="right")
        self.out_lbl = tk.Label(row, text="A “Clean” folder next to the audiobook", bg=CARD,
                                fg=MUTED, font=(FONT, 10), wraplength=480, justify="left")
        self.out_lbl.pack(side="left")
        self.split_var = tk.BooleanVar(value=self.saved_opts.get("split", False))
        self.split_chk = ttk.Checkbutton(b5, text="Also split into chapter files  (for Yoto and "
                                         "players that can't skip chapters)",
                                         variable=self.split_var, command=self._places_shown)
        self.split_chk.pack(anchor="w", pady=(6, 0))
        # where they go: the usual place, or a folder they choose (Lauren, 2026-11-04)
        places = load_places()
        self.chapters_dir = places.get("chapters_dir") or None
        self.m4b_dir = places.get("m4b_dir") or None
        self.chap_box = tk.Frame(b5, bg=CARD)
        self.chap_lbl = self._place_row(self.chap_box, "chapters")
        # one M4B with the cover and chapters, as AudiobookConverter made from the chapter files
        self.m4b_var = tk.BooleanVar(value=self.saved_opts.get("m4b", False))
        ttk.Checkbutton(b5, text="Also make one M4B with the cover and chapters  (for phones "
                        "and audiobook apps)", variable=self.m4b_var,
                        command=self._m4b_shown).pack(anchor="w", pady=(4, 0))
        self.m4b_box = tk.Frame(b5, bg=CARD)
        # the cover: drop a picture on this box from File Explorer, or choose one
        zone = tk.Frame(self.m4b_box, bg=CARD, highlightthickness=1, highlightbackground=LINE,
                        padx=8, pady=6)
        zone.pack(fill="x", pady=(4, 0))
        self.cover_img_lbl = tk.Label(zone, bg=CARD)     # the picture found online, small
        self.cover_lbl = tk.Label(zone, text="", bg=CARD, fg=MUTED, font=(FONT, 10), anchor="w",
                                  wraplength=360, justify="left")
        self.cover_lbl.pack(side="left")
        ttk.Button(zone, text="Choose a picture\u2026", style="Plain.TButton",
                   command=self.pick_cover).pack(side="right")
        self._can_drop = any([dropfiles.accept(w, self._cover_dropped)
                              for w in (zone, self.cover_lbl, self.cover_img_lbl)])
        # no cover in the book or its folder: look it up online (Lauren, 2026-11-04)
        self.cover_online_var = tk.BooleanVar(value=bool(places.get("cover_online", True)))
        ttk.Checkbutton(self.m4b_box, text="When the book has no cover, find one online  (by its "
                        "title and author)",
                        variable=self.cover_online_var,
                        command=self._online_changed).pack(anchor="w", pady=(4, 0))
        row = tk.Frame(self.m4b_box, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        tk.Label(row, text="Author:", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(side="left")
        self.author_var = tk.StringVar(value=getattr(self, "author", "") or "")
        author_entry = ttk.Entry(row, textvariable=self.author_var, width=40)
        author_entry.pack(side="left", padx=(8, 0))
        # a new author: look for the cover again (not on every key press)
        author_entry.bind("<FocusOut>", lambda e: self._cover_refresh())
        author_entry.bind("<Return>", lambda e: self._cover_refresh())
        self.m4b_place_lbl = self._place_row(self.m4b_box, "m4b")
        # an Audiobookshelf library: Author > Series > Book 2 - Title (its scanner reads them)
        self.abs_var = tk.BooleanVar(value=bool(places.get("abs", True)))
        self.abs_chk = ttk.Checkbutton(self.m4b_box, text="Make Author \u203a Series \u203a Book "
                                       "folders in it  (the way Audiobookshelf likes)",
                                       variable=self.abs_var, command=self._abs_changed)
        self.series_row = tk.Frame(self.m4b_box, bg=CARD)
        tk.Label(self.series_row, text="Series:", bg=CARD, fg=MUTED,
                 font=(FONT, 10)).pack(side="left")
        self.series_var = tk.StringVar(value=getattr(self, "series", "") or "")
        ttk.Entry(self.series_row, textvariable=self.series_var, width=26).pack(side="left",
                                                                                padx=(8, 12))
        tk.Label(self.series_row, text="Book number:", bg=CARD, fg=MUTED,
                 font=(FONT, 10)).pack(side="left")
        self.series_no_var = tk.StringVar(value=getattr(self, "series_no", "") or "")
        ttk.Entry(self.series_row, textvariable=self.series_no_var, width=5).pack(side="left",
                                                                                 padx=(8, 0))
        self.abs_lbl = tk.Label(self.m4b_box, text="", bg=CARD, fg=MUTED, font=(FONT, 9),
                                wraplength=480, justify="left", anchor="w")
        for v in (self.series_var, self.series_no_var, self.author_var):
            v.trace_add("write", lambda *_: self._abs_preview())
        self._m4b_shown()
        self._refresh_labels()
        sp.go(step)

    def _m4b_shown(self):
        if self.m4b_var.get():
            self.m4b_box.pack(anchor="w", fill="x", padx=(26, 0))
        else:
            self.m4b_box.pack_forget()
        self._places_shown()

    # ---------- where the chapter files and the M4B go ----------
    def _place_row(self, parent, which):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        lbl = tk.Label(row, text="", bg=CARD, fg=INK, font=(FONT, 10), anchor="w",
                       wraplength=330, justify="left")
        lbl.pack(side="left")
        lbl.usual_btn = ttk.Button(row, text="Usual place", style="Plain.TButton",
                                   command=lambda: self._set_place(which, None))
        lbl.usual_btn.pack(side="right", padx=(6, 0))
        ttk.Button(row, text="Change\u2026", style="Plain.TButton",
                   command=lambda: self._pick_place(which)).pack(side="right")
        return lbl

    def _pick_place(self, which):
        title = ("Where should the chapter files go? (Each book gets its own folder in it.)"
                 if which == "chapters" else
                 "Where should the M4B go? (Your Audiobookshelf library folder, say.)")
        d = filedialog.askdirectory(title=title, initialdir=getattr(self, which + "_dir") or None)
        if d:
            self._set_place(which, d)

    def _set_place(self, which, d):
        setattr(self, which + "_dir", d or None)
        self._keep_places()
        self._places_shown()

    def _keep_places(self):
        save_places({"chapters_dir": getattr(self, "chapters_dir", None),
                     "m4b_dir": getattr(self, "m4b_dir", None),
                     "abs": bool(self.abs_var.get()) if getattr(self, "abs_var", None) else True,
                     "cover_online": (bool(self.cover_online_var.get())
                                      if getattr(self, "cover_online_var", None) else True)})

    def _online_changed(self):
        self._keep_places()
        self._cover_refresh()

    def _online_lookup(self):
        """Look for this book's cover online, in the background (once per book and author).
        Returns its state: {"done", "res", "thumb"}."""
        name = engine.strip_number(getattr(self, "_name_for_book", ""),
                                   engine._number(self.series_no_var.get()))
        author = self.author_var.get().strip()
        want = (tuple(self.audio or ()), name, author)
        st = getattr(self, "_online", None)
        if st and st["want"] == want:
            return st
        st = {"want": want, "done": False, "res": None, "thumb": None}
        self._online = st

        def work():
            try:
                res = engine.find_cover_online(name, author, APP_DATA / "covers",
                                               log=lambda m: None)
                if res:
                    st["thumb"] = cover_thumbnail(res["file"])
                st["res"] = res
            except Exception:
                pass
            st["done"] = True
        threading.Thread(target=work, daemon=True, name="cover lookup").start()
        self.after(300, lambda: self._wait_online(st))
        return st

    def _wait_online(self, st):
        if st is not getattr(self, "_online", None):
            return                      # another book (or author) since
        if not st["done"]:
            self.after(300, lambda: self._wait_online(st))
            return
        self._cover_refresh()

    def _online_file(self):
        """The cover found online for the book on the start page, if there is one."""
        st = getattr(self, "_online", None)
        if (st and st["done"] and st["res"] and st["want"][0] == tuple(self.audio or ())
                and self.cover_online_var.get()):
            return st["res"]["file"]
        return None

    def _abs_changed(self):
        self._keep_places()
        self._places_shown()

    def _book_name(self):
        return getattr(self, "_name_for_book", "") or "the book's name"

    def _places_shown(self):
        """Show where the chapter files and the M4B will go, and the Audiobookshelf choices."""
        lbl = getattr(self, "chap_lbl", None)
        if not lbl or not lbl.winfo_exists():
            return
        if self.split_var.get():
            self.chap_box.pack(anchor="w", fill="x", padx=(26, 0), after=self.split_chk)
        else:
            self.chap_box.pack_forget()
        self._chapters_text()
        m = self.m4b_place_lbl
        m.config(text="M4B goes in: " + (os.path.normpath(self.m4b_dir) if self.m4b_dir
                                          else "the clean folder"))
        m.usual_btn.config(state="normal" if self.m4b_dir else "disabled")
        for w in (self.abs_chk, self.series_row, self.abs_lbl):
            w.pack_forget()
        if self.m4b_dir:
            self.abs_chk.pack(anchor="w", pady=(4, 0))
            if self.abs_var.get():
                self.series_row.pack(anchor="w", fill="x", pady=(4, 0), padx=(22, 0))
                self.abs_lbl.pack(anchor="w", fill="x", pady=(2, 0), padx=(22, 0))
        self._abs_preview()

    def _chapters_text(self):
        lbl = self.chap_lbl
        if self.chapters_dir:
            # as render() names it: the book, without its number in the series
            name = engine.safe_name(engine.strip_number(
                self._book_name(), engine._number(self.series_no_var.get())))
            lbl.config(text="Chapter files go in: " + os.path.normpath(
                str(Path(self.chapters_dir) / name)))
        else:
            lbl.config(text="Chapter files go in: a “Chapters” folder in the clean folder")
        lbl.usual_btn.config(state="normal" if self.chapters_dir else "disabled")

    def _abs_preview(self):
        if getattr(self, "chap_lbl", None) and self.chap_lbl.winfo_exists():
            self._chapters_text()
        lbl = getattr(self, "abs_lbl", None)
        if not lbl or not lbl.winfo_exists() or not self.m4b_dir:
            return
        series, no = self.series_var.get().strip(), self.series_no_var.get().strip()
        title = getattr(self, "_name_for_book", "") or "Book name"
        home = engine.abs_folder(self.m4b_dir, title, self.author_var.get().strip(), series, no)
        file = engine.safe_name(engine.strip_number(title, engine._number(no))) + ".m4b"
        lbl.config(text="It's saved as:  " + os.path.normpath(str(home / file))
                   + ("" if self.author_var.get().strip() or not series
                      else "\n(Fill in the author, or it goes in \u201cUnknown Author\u201d.)"))

    def _places_for_job(self):
        """What a new book's row needs to know about where its files go."""
        split, m4b = getattr(self, "split_chapters", False), getattr(self, "make_m4b", False)
        places = load_places()
        chapters_dir = getattr(self, "chapters_dir", places.get("chapters_dir")) or None
        m4b_dir = getattr(self, "m4b_dir", places.get("m4b_dir")) or None
        abs_on = getattr(self, "abs_layout", places.get("abs", True))
        return {"chapters_dir": chapters_dir if split else None,
                "m4b_dir": m4b_dir if m4b else None,
                "abs": bool(m4b and m4b_dir and abs_on),
                "series": getattr(self, "series", "") or "",
                "series_no": getattr(self, "series_no", "") or "",
                # saving looks it up then if the start page hadn't found it yet
                "cover_online": bool(self.cover_online_var.get()
                                     if getattr(self, "cover_online_var", None)
                                     else places.get("cover_online", True))}

    def _cover_dropped(self, files):
        pics = [f for f in files if Path(f).suffix.lower() in engine.IMAGE_EXTS and Path(f).is_file()]
        if not pics:
            chime()
            messagebox.showinfo("CleanListen", "That isn't a picture CleanListen can use for the "
                                "cover. Drop a JPG or PNG picture.")
            return
        self.cover_pick = pics[0]
        self._cover_refresh()

    def _cover_refresh(self):
        """Say which cover picture the M4B gets (and fill in the author for a new book)."""
        lbl = getattr(self, "cover_lbl", None)
        if not lbl or not lbl.winfo_exists():
            return
        key = tuple(self.audio or ())
        if key != getattr(self, "_cover_for", None):
            self._cover_for = key
            self.cover_pick = None
            self.author_var.set(engine.book_author(self.audio) if self.audio else "")
            # "...\Grace Ford Series\#2 Nearly Safe": series "Grace Ford", book 2
            series, no = engine.guess_series(self.audio) if self.audio else ("", "")
            self.series_var.set(series)
            self.series_no_var.set(no)
            try:
                self._name_for_book = engine.m4b_title(self.audio) if self.audio else ""
            except Exception:
                self._name_for_book = book_title(self.audio) if self.audio else ""
        online = None
        if getattr(self, "cover_pick", None):
            text = f"Cover: {Path(self.cover_pick).name}"
        elif not self.audio:
            text = "Cover: the book's own picture, when it has one"
        else:
            found = engine.find_cover(self.audio)
            text = ("Cover: the picture inside the book" if found and found[0] == "book" else
                    f"Cover: {Path(found[1]).name}" if found else
                    "No cover picture found. Choose one, or it's made without one.")
            if not found and self.cover_online_var.get():
                st = self._online_lookup()
                r = st["res"]
                if not st["done"]:
                    text = "No cover in the book. Looking for one online…"
                elif r:
                    text = (f"Cover: found on {r['source']}: “{r['title']}”"
                            + (f" by {r['author']}" if r["author"] else ""))
                    online = st
                else:
                    text = ("No cover picture found, here or online. Choose one, or it's made "
                            "without one.")
        self._show_thumb(online["thumb"] if online else None)
        if getattr(self, "_can_drop", False):
            text += "\nOr drag a picture here from a folder to use that one."
        lbl.config(text=text, fg=INK if self.audio else MUTED)
        self._places_shown()

    def _show_thumb(self, path):
        """The small picture of the cover found online (none otherwise)."""
        lbl = self.cover_img_lbl
        img = None
        if path:
            try:
                img = tk.PhotoImage(file=path)
            except tk.TclError:
                img = None
        if img:
            lbl.config(image=img)
            lbl.image = img
            if not lbl.winfo_ismapped():
                lbl.pack(side="left", padx=(0, 10), before=self.cover_lbl)
        else:
            lbl.config(image="")
            lbl.image = None
            lbl.pack_forget()

    def choose_cover(self, parts, workdir, on_pick, now=""):
        """A window with every picture that could be the cover: each one inside the book (when
        two got in by accident, both show), the ones in its folder, or another (Choose, or drag
        it here). Clicking one calls on_pick(path)."""
        win = tk.Toplevel(self)
        win.title("Choose the cover")
        win.configure(bg=BG, padx=16, pady=12)
        win.transient(self)
        tk.Label(win, text="Choose the cover", bg=BG, fg=INK,
                 font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(win, text=(f"Now: {now}.  " if now else "") + "Click a picture to use it, or drag "
                 "one here from a folder.", bg=BG, fg=MUTED, font=(FONT, 9), wraplength=560,
                 justify="left").pack(anchor="w", pady=(2, 8))
        grid = tk.Frame(win, bg=BG)
        grid.pack(fill="both", expand=True)
        status = tk.Label(grid, text="Looking for pictures\u2026", bg=BG, fg=MUTED, font=(FONT, 10))
        status.grid(row=0, column=0, sticky="w")
        found = {}

        def pick(f):
            if win.winfo_exists():
                win.destroy()
            on_pick(f)

        def dropped(files):
            pics = [f for f in files if Path(f).suffix.lower() in engine.IMAGE_EXTS and Path(f).is_file()]
            if pics:
                pick(pics[0])
            else:
                messagebox.showinfo("CleanListen", "That isn't a picture CleanListen can use for "
                                    "the cover. Drop a JPG or PNG picture.", parent=win)

        def work():
            try:
                pics = engine.book_pictures(parts, Path(workdir) / "pictures")
                for p in pics:
                    p["thumb"] = cover_thumbnail(p["file"], 120)
            except Exception:
                pics = []
            found["pics"] = pics

        def show():
            if not win.winfo_exists():
                return
            if "pics" not in found:
                win.after(200, show)
                return
            status.destroy()
            if not found["pics"]:
                tk.Label(grid, text="There are no pictures in the book or its folder. Choose one, "
                         "or drag one here.", bg=BG, fg=MUTED, font=(FONT, 10)).grid(row=0, column=0)
            for i, p in enumerate(found["pics"]):
                img = None
                if p.get("thumb"):
                    try:
                        img = tk.PhotoImage(file=p["thumb"])
                    except tk.TclError:
                        img = None
                b = tk.Button(grid, text=p["label"], image=img, compound="top", wraplength=130,
                              bg=CARD, fg=INK, activebackground=CARD, activeforeground=INK,
                              relief="flat", cursor="hand2", font=(FONT, 9), padx=6, pady=6,
                              command=lambda f=p["file"]: pick(f))
                b.image = img
                b.grid(row=i // 4, column=i % 4, padx=6, pady=6, sticky="n")
                dropfiles.accept(b, dropped)
        threading.Thread(target=work, daemon=True, name="cover pictures").start()
        win.after(200, show)
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", pady=(10, 0))

        def other():
            f = filedialog.askopenfilename(parent=win, title="Choose the cover picture",
                                           filetypes=[("Pictures", "*.jpg *.jpeg *.png"),
                                                      ("All files", "*.*")])
            if f:
                pick(f)
        ttk.Button(row, text="Choose another picture\u2026", style="Plain.TButton",
                   command=other).pack(side="left")
        ttk.Button(row, text="Cancel", style="Plain.TButton", command=win.destroy).pack(side="right")
        for w in (win, grid, status):
            dropfiles.accept(w, dropped)
        return win

    def pick_cover(self):
        f = filedialog.askopenfilename(title="Choose the cover picture",
                                       filetypes=[("Pictures", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        if f:
            self.cover_pick = f
            self._cover_refresh()

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
            self._stop_books()       # they carry on in the new version
            env = dict(os.environ, CLEANLISTEN_UPDATED=f"CleanListen was updated to version {val}.",
                       CLEANLISTEN_UPDATE_DONE="1")
            try:   # through the new launcher, so what's new in it works now (its own name, say)
                subprocess.Popen([sys.executable, str(HERE / "launcher.pyw")], cwd=str(HERE), env=env)
            except Exception as ex:
                messagebox.showinfo("CleanListen", f"Updated to {val}. Close CleanListen and open it "
                                    f"again to finish ({ex}).")
                return
            self.destroy()

    def _save_resume(self, note="", path=RESUME):
        """Remember where you are (the review with all its ticks, or the book you picked)."""
        try:
            data = {"time": __import__("time").time(), "note": note, "audio": self.audio,
                    "ebook": self.ebook, "outdir": self.outdir, "saved_opts": self.saved_opts,
                    "cover": getattr(self, "cover_pick", None),
                    "author": (self.author_var.get().strip() if getattr(self, "author_var", None)
                               and self.page_name == "setup" else getattr(self, "author", ""))}
            on_setup = getattr(self, "series_var", None) and self.page_name == "setup"
            data.update(series=self.series_var.get().strip() if on_setup else
                        getattr(self, "series", ""),
                        series_no=self.series_no_var.get().strip() if on_setup else
                        getattr(self, "series_no", ""))
            if self.page_name == "review" and self.analysis and self.workdir:
                self._sync_ticks()
                self._save_analysis()
                data.update(page="review", workdir=str(self.workdir), job=self.review_key,
                            split=getattr(self, "split_chapters", False),
                            m4b=getattr(self, "make_m4b", False),
                            view=getattr(self, "view_mode", "list"))
            elif self.audio:
                data["page"] = "setup"
            else:
                return
            data["title"] = (self.analysis or {}).get("title") or (book_title(self.audio)
                                                                    if self.audio else "")
            APP_DATA.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1), encoding="utf8")
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
        self.cover_pick = data.get("cover") if data.get("cover") and Path(data["cover"]).exists() else None
        self.author = data.get("author") or ""
        self.series, self.series_no = data.get("series") or "", data.get("series_no") or ""
        self._cover_for = tuple(self.audio)
        self.resume_note = data.get("note") or "Picked up where you left off."
        if data.get("page") == "review" and data.get("workdir"):
            wd = Path(data["workdir"])
            try:
                self.analysis = json.loads((wd / "analysis.json").read_text())
            except Exception:
                self.analysis = None
            if self.analysis:
                self.workdir = wd
                job = self.books.find(data.get("job") or "")
                self.review_key = job["key"] if job else None
                self.split_chapters = data.get("split", False)
                self.make_m4b = data.get("m4b", False)
                # (older versions saved show_fine: True meant "show everything")
                self.view_mode = data.get("view") or ("all" if data.get("show_fine") else "list")
                self.show_review()
                return
        if self.audio:
            if data.get("note"):
                os.environ["CLEANLISTEN_UPDATED"] = data["note"]
            self.show_setup()

    def _back_to_start(self):
        """Leave the review without saving an audiobook (Jason, 2026-10-30: a parent may only
        want to see what's in a book). The review is kept: the book stays on "Your books" as
        ready to review, ticks and all."""
        self._sync_ticks()
        self._learn_choices()            # checking without saving still teaches it (Jason)
        try:
            self._queue_this_review()
        except BQ.Busy:
            pass
        self._leave_review()
        self.show_queue()

    def _left_review(self):
        """The review you went back to the start from, if it can still be opened."""
        import time as _t
        try:
            data = json.loads(LEFT.read_text(encoding="utf8"))
            if (data.get("page") == "review" and _t.time() - data.get("time", 0) <= 14 * 86400
                    and (Path(data["workdir"]) / "analysis.json").exists()):
                return data
        except Exception:
            pass
        return None

    def _pick_up(self):
        try:
            os.replace(LEFT, RESUME)
        except OSError:
            return
        self._restore()

    def _on_close(self):
        n = len(self.books.running())
        if n:
            chime()
            if not messagebox.askyesno(
                    "CleanListen", f"CleanListen is still working on {n} book{'s' if n > 1 else ''}. "
                    "Close it anyway?\n\nThey'll carry on from where they got to when you open "
                    "CleanListen again."):
                return
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
        """What CleanListen calls whichever of Claude, ChatGPT or Gemini is helping: "AI",
        everywhere but where one is chosen and set up (1.17.34, as CleanView 1.18.86; the owner,
        2026-11-13: "instead of saying "claude" say "Ai"", and of the book apps: "yes")."""
        return engine.AI

    def _provider(self):
        """Its own name (Claude, ChatGPT or Gemini): only for the step where it's chosen and
        set up, and the messages that send you there."""
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
                self.model_row.pack(side="left", padx=(6, 0))
            else:
                self.model_row.pack_forget()
        self.claude_lbl.config(text="Checking\u2026", fg=MUTED)
        self.claude_btn.pack_forget()
        threading.Thread(target=self._claude_status_thread, daemon=True).start()

    def _show_claude_more(self):
        if self.claude_var.get():
            self.claude_more.pack(anchor="w", fill="x")
        else:
            self.claude_more.pack_forget()

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
        self._send_or_save(path, "learned")

    def _show_claude_status(self, st, prov=None):
        cc = self._cc()
        if cc and prov and prov != cc.PROVIDER:
            return      # an answer about the other one; a newer check is on its way
        self.claude_state = st
        if not getattr(self, "claude_lbl", None) or not self.claude_lbl.winfo_exists():
            return
        N = self._provider()
        prog = {"ChatGPT": "Codex (for ChatGPT)",
                "Gemini": "Antigravity CLI (for Gemini)"}.get(N, "Claude Code")
        text = {"ok": f"\u2713 {N} is ready", "signed_out": f"{N} isn't signed in yet",
                "missing": f"{prog} isn't set up yet (one time, about a minute)",
                "broken": f"{N} files are missing \u2014 reopen CleanListen to update"}.get(st, st)
        self.claude_lbl.config(text=text, fg=ACCENT_DK if st == "ok" else AMBER)
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
        self.show_working("The AI is checking the book\u2026", quick="claude")
        self.claude_job = job = getattr(self, "claude_job", 0) + 1
        self.cancel_flag = False
        # Claude works on a copy: Cancel goes straight back to the list as it was (the owner,
        # 2026-11-09: Cancel took a while), and a cancelled check's answer is dropped
        work_on, workdir = copy.deepcopy(self.analysis), self.workdir

        def work():
            stopped = lambda: self.cancel_flag or self.claude_job != job   # noqa: E731
            try:
                asr = engine.load_asr(workdir, work_on["parts"])
                cc.review(work_on, asr, progress=lambda f, m: None if stopped() else self.q.put(
                    ("progress", f, m)), cancel=stopped)
                if not stopped():
                    self.q.put(("claude_done", job, work_on))
            except KeyboardInterrupt:
                pass
            except Exception as ex:
                if not stopped():
                    self.q.put(("claude_fail", str(ex), job))
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
        tk.Label(w, text="The AI can read the whole book and everything CleanListen found. Ask it to "
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
                                  bg=CARD, fg=INK, insertbackground=INK, highlightcolor=ACCENT,
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
        self._chat_say("info", "Tip: the AI looks over the whole book every time you ask, so "
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
        box = tk.Frame(holder, bg=TINT, padx=8, pady=6)
        box.pack(fill="x", pady=(4, 0), side="bottom" if kind == "W" else None)
        hint = ("Tip: highlight part of the text above first to point at it. " if txt is not None else "")
        tip = tk.Label(box, text=hint + "e.g. \u201cjust cut the bed line\u201d, \u201ckeep "
                       "this\u201d, \u201cmute only that word\u201d", bg=TINT, fg=MUTED,
                       font=(FONT, 8), wraplength=640, justify="left", anchor="w")
        tip.pack(anchor="w")
        CL.fit_text(tip, box, margin=20)                    # the box's width, less its padding
        row = tk.Frame(box, bg=TINT)
        row.pack(fill="x", pady=(2, 0))
        entry = ttk.Entry(row)
        entry.pack(side="left", fill="x", expand=True)
        status = tk.Label(box, text="", bg=TINT, fg=ACCENT_DK, font=(FONT, 9), wraplength=640,
                          justify="left", anchor="w")
        CL.fit_text(status, box, margin=20)

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
            status.config(text="The AI is reading\u2026")
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
                    ans, changes, kept = chat.ask(msg)
                    self.q.put(("card_reply", item, ans, changes, kept))
                except Exception as ex:
                    self.q.put(("card_reply", item, f"Sorry, that didn't work: {ex}", [], []))
            threading.Thread(target=work, daemon=True).start()
        btn = ttk.Button(row, text="Send", style="Plain.TButton", command=send)
        btn.pack(side="left", padx=(6, 0))
        entry.bind("<Return>", send)
        entry.focus_set()

    def _card_reply(self, item, ans, changes, kept=()):
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
        self._will_remember(kept)
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

    def _will_remember(self, kept):
        """Say what the chat will keep in mind for later checks (Jason, 2026-10-30)."""
        for note, everywhere in kept or ():
            text = ("\u2713 CleanListen will remember" +
                    (" for every book" if everywhere else " for this book") + ": " + note)
            self._chat_history().append(("info", text))
            self._chat_say("info", text)

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
        self._chat_say("info", "The AI is reading the book\u2026")
        self.chat_send.configure(state="disabled")
        self._sync_ticks()

        def work():
            try:
                ans, changes, kept = self.chat.ask(q)
                self.q.put(("chat_reply", ans, changes, kept))
            except Exception as ex:
                self.q.put(("chat_reply", f"Sorry, that didn't work: {ex}", [], []))
        threading.Thread(target=work, daemon=True).start()

    def _chat_reply(self, ans, changes, kept=()):
        if not getattr(self, "chat_win", None) or not self.chat_win.winfo_exists():
            return
        self.chat_send.configure(state="normal")
        self._chat_say("them", ans or "(no answer)")
        self._chat_history().append(("them", ans or ""))
        self._will_remember(kept)
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
        self._cover_refresh()
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
            self.start_hint.pack_forget()
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
                                  "Change what to remove if you like, then press “Re-check this book”.")
            self.heard_lbl.pack(fill="x", pady=(0, 6), before=self.b1_outer)
            self.start_btn.config(text="Re-check this book")
        else:
            self.heard_lbl.pack_forget()
            self.start_btn.config(text="Start cleaning")
        sp = getattr(self, "steps_page", None)
        if sp is not None:
            sp.refresh()

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
            outer = CL.card(body)                 # rounded (the new look, 2026-11-13)
            outer.pack(fill="x", pady=4)
            c = outer.body
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
        """Back to the start screen with the same book loaded and the same ticks (the
        re-check replaces the book's row on "Your books")."""
        self.review_key = None
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
        self._language_of_new_book()
        self._refresh_labels()

    def pick_audio(self):
        exts = " ".join("*" + e for e in engine.AUDIO_EXTS)
        files = filedialog.askopenfilenames(title="Choose the audiobook file(s)",
                                            filetypes=[("Audiobooks", exts), ("All files", "*.*")])
        if files:
            self.audio = sorted(files, key=natural_key)
            self.outdir = None
            self._language_of_new_book()
            self._refresh_labels()

    def pick_ebook(self):
        f = filedialog.askopenfilename(title="Choose the ebook",
                                       filetypes=[("Ebooks", "*.epub *.pdf *.txt"), ("All files", "*.*")])
        if f:
            self.ebook = f
            lang = engine.guess_language(f)     # the ebook says what language the book is in
            if lang:
                self._set_language(lang)
            self._refresh_labels()

    def pick_out(self):
        d = filedialog.askdirectory(title="Where should the clean audiobook go?")
        if d:
            self.outdir = d
            self._refresh_labels()

    # ---------- page 2: working ----------
    def start(self):
        ticks, mywords = self.filter_card.ticks(), self.filter_card.mywords()
        groups = F.groups(ticks)
        lang = engine.use_language(self.lang_var.get())    # her own words are read in it too
        self.filter_args = F.listen_kwargs(ticks, mywords)
        if lang != "en":                # English is checked exactly as it always was
            self.filter_args["language"] = lang
        self.use_ai = self.ai_var.get()
        self.use_claude = self.claude_var.get()
        self.split_chapters = self.split_var.get()
        self.make_m4b = self.m4b_var.get()
        self.author = self.author_var.get().strip()
        self.series = self.series_var.get().strip()
        self.series_no = self.series_no_var.get().strip()
        self.abs_layout = self.abs_var.get()
        if self.make_m4b and self.m4b_dir and self.abs_layout and self.series_no and \
                not engine._number(self.series_no):
            messagebox.showinfo("CleanListen", "The book number should be just a number, like 2 "
                                "(or 2.5). Fix it, or leave it empty.")
            return
        if not F.anything_on(ticks) and not mywords:
            messagebox.showinfo("CleanListen", "Tick at least one thing to remove (Choose filters\u2026).")
            return
        self.saved_opts = dict(ticks, profile=self.filter_card.profile.get())
        self.saved_opts.update(ai=self.use_ai, split=self.split_chapters, claude=self.use_claude,
                               m4b=self.make_m4b, language=lang)
        if self.use_claude:
            cc = self._cc()
            state = getattr(self, "claude_state", None) or (cc.status() if cc else "broken")
            if state != "ok":
                chime()
                if not messagebox.askyesno("CleanListen", f"{self._provider()} isn't set up or signed "
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
        try:
            dur = sum(engine.probe_duration(a) for a in self.audio)
        except Exception:
            dur = 0
        spec = {"audio": list(self.audio), "ebook": self.ebook, "outdir": self.outdir,
                "title": book_title(self.audio), "workdir": str(self.workdir), "groups": groups,
                "filter_args": self.filter_args, "use_ai": self.use_ai,
                "use_claude": self.use_claude, "split": self.split_chapters,
                "m4b": self.make_m4b,
                "cover": getattr(self, "cover_pick", None) or self._online_file(),
                "author": self.author or None, **self._places_for_job(),
                "opts": dict(self.saved_opts), "summary": F.summary(ticks, mywords),
                "profile": dict(F.PROFILES).get(self.saved_opts.get("profile"), ""),
                "heard": heard, "length": dur}
        try:
            self.books.add(spec)
        except BQ.Busy:
            messagebox.showinfo("CleanListen", "This book is being worked on right now. Wait for "
                                "it to finish (or press Cancel on it), then try again.")
            self.show_queue()
            return
        # the book becomes a row on "Your books"; the start page is free for the next one
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.cover_pick, self.author = None, ""
        self._run_queue()
        self.show_queue()

    def show_working(self, title, quick=False):
        dur = sum(engine.probe_duration(a) for a in self.audio) if self.audio else 0
        if quick == "claude":
            sub = ("The AI is reading the whole book with everything that was found. Long books "
                   "take a few minutes. Cancel keeps the list as it was.")
        elif quick:
            sub = ("Already listened to, so this skips straight to checking. It takes a few "
                   "minutes (longer with the AI helper or the final check on).")
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
        LOGO.put_logo(p, "icon.ico", BG)          # the empty space (Jason, 2026-11-07)

    def cancel(self):
        """The working page is only used by the Claude check now: back to the list at once,
        as it was (2026-11-09)."""
        self.cancel_flag = True
        self.claude_job = getattr(self, "claude_job", 0) + 1
        self.show_review()

    def _poll(self):
        """From now on freezes.drain runs the queue: a flood of messages can't keep the window
        busy, and one bad message can't stop it updating (Jason, 2026-11-03)."""
        freezes.drain(self, self.q, self._handle, self._poll_error, self.watch)

    def _poll_error(self, details):
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            (APP_DATA / "last_error.txt").write_text(details, encoding="utf8")
        except OSError:
            pass

    def _handle(self, msg):
        kind = msg[0]
        if kind == "progress" and getattr(self, "pb", None) and self.pb.winfo_exists():
            self.pb["value"] = int(msg[1] * 1000)
            self.status.config(text=msg[2])
        elif kind == "job":
            self._job_msg(msg[1], msg[2])
        elif kind in ("update_none", "update_fail", "update_progress", "updated"):
            self._update_msg(kind, msg[1])
        elif kind == "claude_status":
            self._show_claude_status(*msg[1:])
        elif kind == "sent":
            self._sent(msg[1], msg[2])
        elif kind == "claude_done":
            if msg[1] == getattr(self, "claude_job", None) and self.page_name == "working":
                self.analysis = msg[2]
                self._save_analysis()
                self.show_review()
        elif kind == "claude_fail":
            if msg[2] == getattr(self, "claude_job", None) and self.page_name == "working":
                messagebox.showerror("AI check", msg[1])
                self.show_review()
        elif kind == "play":
            self._play_ready(*msg[1:])
        elif kind == "play_fail":
            if getattr(self, "_playing", None) is msg[1]:
                self._stop_playing()
                messagebox.showerror("CleanListen", msg[2])
        elif kind == "card_reply":
            self._card_reply(*msg[1:])
        elif kind == "chat_reply":
            self._chat_reply(*msg[1:])
        elif kind == "cancelled":
            self.show_setup()
        elif kind == "error":
            (self.workdir / "last_error.txt").parent.mkdir(parents=True, exist_ok=True)
            (self.workdir / "last_error.txt").write_text(msg[2], encoding="utf8")
            messagebox.showerror("CleanListen ran into a problem", BQ.plain_error(msg[1]))
            self.show_setup()

    # ---------- "Your books": the queue ----------
    def _to_books(self):
        """From another page to "Your books" (a review in progress is kept as it is)."""
        if self.page_name == "review":
            self._back_to_start()
        else:
            self.show_queue()

    def _show_books_count(self):
        """The "Your books" link on other pages, and the window's title, say what's ready."""
        ready = self.books.count(BQ.READY)
        busy = self.books.count(BQ.PREPARING, BQ.WAITING, BQ.SAVING, BQ.SAVE_WAITING)
        bits = ([f"{ready} ready to review"] if ready else []) + ([f"{busy} in progress"] if busy else [])
        lbl = getattr(self, "_books_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.config(text="Your books" + (" · " + ", ".join(bits) if bits else "") + " ▸")
        title = f"CleanListen {app_version()}" + (f" · {ready} ready to review" if ready else "")
        if self.title() != title:
            self.title(title)

    def _drop_books_link(self):
        if getattr(self, "_books_lbl", None) is not None:
            self._books_lbl.destroy()
            self._books_lbl = None

    def _run_queue(self):
        """Start the next books, up to "Books at once" (saving first, then preparing)."""
        changed = False
        for job in self.books.to_start():
            task = "save" if job["step"] == BQ.SAVE_WAITING else "prepare"
            try:
                self.workers.start(job, task, BQ.threads_each(self.books.at_once))
                self.books.started(job["key"])
            except Exception as ex:
                self.books.started(job["key"])
                self.books.handle(job["key"], {"error": f"It couldn't start ({ex})."})
            changed = True
        if changed:
            self._books_changed()

    def _books_changed(self):
        if self.page_name == "queue":
            self.show_queue()
        else:
            self._show_books_count()

    def _job_msg(self, key, msg):
        what = self.books.handle(key, msg)
        job = self.books.find(key)
        if what == "progress" and job:
            r = self._rows.get(key)
            if self.page_name == "queue" and r and r["status"].winfo_exists():
                r["status"].config(text=self._job_status(job))
                if r.get("pb") is not None:
                    r["pb"]["value"] = int(job["frac"] * 1000)
        elif what == "step":
            if job and job["step"] in (BQ.READY, BQ.DONE):
                chime()                   # a book is ready to review, or saved
            self._run_queue()
            self._books_changed()

    def _job_status(self, job):
        step = job["step"]
        if step == BQ.READY and job.get("found"):
            f = job["found"]
            w, n = f.get("words", 0), f.get("passages", 0)
            return (f"Ready to review · {w} word{'s' if w != 1 else ''} to mute, "
                    f"{n} passage{'s' if n != 1 else ''} to cut")
        if step == BQ.DONE and job.get("result"):
            r = job["result"]
            cm = r.get("cut_minutes", 0)
            gone = f" ({cm:.0f} min removed)" if cm >= 1 else (f" ({cm * 60:.0f} sec removed)" if cm else "")
            return (f"✓ Saved · {r.get('mutes', 0)} words muted, "
                    f"{r.get('cuts', 0)} passages cut{gone}")
        if step == BQ.FAILED:
            return "Ran into a problem: " + BQ.plain_error(job.get("error"))
        if step in BQ.RUNNING and getattr(self, "workers", None) and self.workers.paused(job["key"]):
            return "Paused \u2014 press Resume to carry on."
        return job.get("status") or BQ.STATUS.get(step, "")

    def _pause_book(self, key):
        """Pause or carry on with one book (its worker and what it started are frozen)."""
        if self.workers.paused(key):
            self.workers.resume(key)
        elif not self.workers.pause(key):
            messagebox.showinfo("CleanListen", "That book couldn't be paused right now.")
        self.show_queue()

    def show_queue(self):
        keep = None      # redrawn when a book moves on: stay where you were in a long list
        if self.page_name == "queue" and getattr(self, "_canvas", None):
            try:
                keep = self._canvas.yview()[0]
            except tk.TclError:
                keep = None
        p = self._new_page("Your books", "Each book is listened to and checked here, a few at a "
                           "time. When one says “Ready to review”, press Review. You can add "
                           "more books at any time.")
        self.page_name = "queue"
        self._rows = {}
        self._drop_books_link()
        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="Books at once:", bg=BG, fg=INK, font=(FONT, 10)).pack(side="left")
        n_var = tk.StringVar(value=str(self.books.at_once))
        box = ttk.Combobox(top, values=[str(n) for n in BQ.AT_ONCE_CHOICES], width=3,
                           state="readonly", textvariable=n_var, font=(FONT, 10))
        box.pack(side="left", padx=(6, 0))
        box.bind("<<ComboboxSelected>>", lambda e: self._set_at_once(int(n_var.get())))
        gb = BQ.memory_gb()
        low = (f" This PC has {gb:.0f} GB of memory, so 1 at a time is safest."
               if 0 < gb < BQ.LOW_MEMORY_GB else "")
        tk.Label(top, text="More at once finishes a pile of books sooner, but each one takes "
                 "longer. With the final check on, it also uses up your Claude, ChatGPT or "
                 "Gemini plan's limits faster." + low, bg=BG, fg=MUTED, font=(FONT, 9),
                 wraplength=560, justify="left").pack(side="left", padx=(12, 0))
        ttk.Button(self.footer, text="Add another book" if self.books.jobs else "Add a book",
                   style="Main.TButton", command=self._add_book).pack(side="right")
        if self.books.count(BQ.DONE):
            ttk.Button(self.footer, text="Clear saved books", style="Plain.TButton",
                       command=self._clear_done).pack(side="left")
        body = self._scroll_area(p)
        if not self.books.jobs:
            tk.Label(body, text="No books yet. Press “Add a book” to choose one.", bg=BG,
                     fg=MUTED, font=(FONT, 11)).pack(anchor="w", pady=20)
        for job in self.books.jobs:
            self._book_row(body, job)
        self._show_books_count()
        if keep:
            canvas = self._canvas
            self.after(30, lambda: canvas.winfo_exists() and canvas.yview_moveto(keep))

    def _book_row(self, parent, job):
        key, step = job["key"], job["step"]
        ready = step == BQ.READY
        outer = CL.card(parent, edge=READY_GREEN if ready else LINE, edge_w=2.0 if ready else 1.0,
                        pad=(16, 12))
        outer.pack(fill="x", pady=4, padx=(0, self._px(4)))
        c = outer.body
        btns = tk.Frame(c, bg=CARD)
        btns.pack(side="right", anchor="n", padx=(10, 0))
        if ready:
            ttk.Button(btns, text="Review", style="Go.TButton",
                       command=lambda: self.review_job(key)).pack(side="left")
        elif step == BQ.DONE and (job.get("result") or {}).get("out"):
            ttk.Button(btns, text="Open folder", style="Go.TButton",
                       command=lambda: open_path(job["result"]["out"])).pack(side="left")
        elif step in (BQ.FAILED, BQ.STOPPED):
            ttk.Button(btns, text="Try again", style="Go.TButton",
                       command=lambda: self._retry(key)).pack(side="left")
            if job.get("m4b") and job.get("task") == "save":
                ttk.Button(btns, text="Change cover\u2026", style="Plain.TButton",
                           command=lambda: self._change_job_cover(key)).pack(side="left",
                                                                            padx=(8, 0))
        if step in BQ.RUNNING and self.workers.alive(key):
            # Pause beside Cancel (the owner, 2026-11-12, as CleanView 1.18.66)
            paused = self.workers.paused(key)
            ttk.Button(btns, text="Resume" if paused else "Pause", style="Plain.TButton",
                       command=lambda: self._pause_book(key)).pack(side="left", padx=(8, 0))
        if step in (BQ.WAITING, BQ.PREPARING, BQ.SAVE_WAITING, BQ.SAVING):
            ttk.Button(btns, text="Cancel", style="Plain.TButton",
                       command=lambda: self._cancel_book(key)).pack(side="left", padx=(8, 0))
        else:
            ttk.Button(btns, text="Remove", style="Plain.TButton",
                       command=lambda: self._remove_book(key)).pack(side="left", padx=(8, 0))
        left = tk.Frame(c, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=job.get("title") or "Book", bg=CARD, fg=INK, font=(FONT, 12, "bold"),
                 wraplength=360, justify="left", anchor="w").pack(anchor="w")
        summ = (f"For {job['profile']}. " if job.get("profile") else "") + (job.get("summary") or "")
        short = summ if len(summ) <= 80 else summ[:77].rsplit(" ", 1)[0] + "…"
        if short:
            tk.Label(left, text=short, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w",
                     wraplength=360, justify="left").pack(anchor="w")
        color = {BQ.READY: READY_GREEN, BQ.DONE: ACCENT_DK, BQ.FAILED: FAIL}.get(step, INK)
        status = tk.Label(left, text=self._job_status(job), bg=CARD, fg=color,
                          font=(FONT, 10, "bold" if step in (BQ.READY, BQ.DONE) else "normal"),
                          wraplength=360, justify="left", anchor="w")
        status.pack(anchor="w", pady=(4, 0))
        pb = None
        if step in (BQ.WAITING, BQ.PREPARING, BQ.SAVE_WAITING, BQ.SAVING):
            pb = ttk.Progressbar(left, style="Green.Horizontal.TProgressbar", maximum=1000)
            pb.pack(fill="x", pady=(4, 0))
            pb["value"] = int(job.get("frac", 0) * 1000)
        self._rows[key] = {"status": status, "pb": pb}
        is_open = key in self._open_rows
        more = tk.Label(left, text=("▾ Less" if is_open else "▸ More"), bg=CARD, fg=ACCENT,
                        font=(FONT, 9, "underline"), cursor="hand2")
        more.pack(anchor="w", pady=(4, 0))
        more.bind("<Button-1>", lambda e: self._flip_row(key))
        if is_open:
            self._row_details(left, job)

        def fit(e):     # the row's words wrap to its width (fixed widths ran under the scrollbar)
            labels = [w for w in left.winfo_children() if isinstance(w, tk.Label)]
            for f in left.winfo_children():
                if isinstance(f, tk.Frame):
                    labels += [w for w in f.winfo_children() if isinstance(w, tk.Label)]
            for w in labels:
                if int(w.cget("wraplength") or 0):
                    w.config(wraplength=max(200, e.width - 8))
        left.bind("<Configure>", fit)

    def _row_details(self, parent, job):
        d = tk.Frame(parent, bg=CARD)
        d.pack(fill="x", pady=(4, 0))
        n = len(job.get("audio") or [])
        lines = [f"{n} file{'s' if n != 1 else ''}"
                 + (f" · {fmt_len(job['length'])}" if job.get("length") else "")
                 + (" · with ebook" if job.get("ebook") else "")
                 + (" · already listened to, so only the checking is done again"
                    if job.get("heard") else "")]
        if job.get("summary"):
            lines.append((f"For {job['profile']}. " if job.get("profile") else "") + job["summary"])
        extra = (["AI helper on this PC"] if job.get("use_ai") else []) + (
            ["final check by " + self._ai_name()] if job.get("use_claude") else [])
        lines.append("Extra checks: " + (", ".join(extra) if extra else "none"))
        if job.get("outdir"):
            also = [w for w, on in (("chapter files", job.get("split")), ("one M4B", job.get("m4b"))) if on]
            lines.append("Saves to: " + os.path.normpath(job["outdir"])
                         + (f"  (and {' and '.join(also)})" if also else ""))
        res = job.get("result") or {}
        if not res and job.get("m4b") and job.get("cover"):
            lines.append("M4B cover: " + self._cover_name(job["cover"]))
        if not res and job.get("split") and job.get("chapters_dir"):
            lines.append("Chapter files go in: " + os.path.normpath(job["chapters_dir"]))
        if not res and job.get("m4b") and job.get("m4b_dir"):
            lines.append("M4B goes in: " + os.path.normpath(job["m4b_dir"])
                         + ("  (Audiobookshelf folders)" if job.get("abs") else ""))
        if res.get("chapters"):
            where = (res["chapters"].get("folders") or [""])[0]
            lines.append(f"Also split into {res['chapters']['tracks']} chapter files, in "
                         + (os.path.normpath(where) if where else "the \u201cChapters\u201d folder")
                         + ".")
        if res.get("m4b"):
            bk = res["m4b"]
            lines.append(f"One M4B: \u201c{Path(bk['file']).name}\u201d, {bk['chapters']} chapters"
                         + ((", with the cover" + (f" from {bk['cover_from']}"
                                                  if bk.get("cover_from") else ""))
                            if bk.get("cover") else ", no cover picture")
                         + ", in " + os.path.normpath(str(Path(bk["file"]).parent)) + ".")
        if (job.get("found") or {}).get("claude_note"):
            lines.append(engine.plain_ai(job["found"]["claude_note"]))
        for line in lines:
            tk.Label(d, text=line, bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=360,
                     justify="left", anchor="w").pack(anchor="w")
        row = tk.Frame(d, bg=CARD)
        row.pack(anchor="w", pady=(6, 0))
        if job["step"] == BQ.DONE and (job.get("result") or {}).get("out"):
            out = job["result"]["out"]
            ttk.Button(row, text="See what was removed", style="Plain.TButton",
                       command=lambda: open_path(str(Path(out) / "CleanListen report.txt"))
                       ).pack(side="left", padx=(0, 8))
            ttk.Button(row, text="Send what we refined…", style="Plain.TButton",
                       command=lambda: self._refined_for(job)).pack(side="left", padx=(0, 8))
        if job["step"] in (BQ.WAITING, BQ.SAVE_WAITING) and self.books.jobs.index(job) > 0:
            ttk.Button(row, text="Move up", style="Plain.TButton",
                       command=lambda: self._move_book(job["key"], -1)).pack(side="left")

    def _flip_row(self, key):
        self._open_rows ^= {key}
        self.show_queue()

    def _set_at_once(self, n):
        self.books.set_at_once(n)
        self._run_queue()

    def _add_book(self):
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.show_setup()

    def _retry(self, key):
        self.books.retry(key)
        self._run_queue()
        self.show_queue()

    def _cancel_book(self, key):
        job = self.books.find(key)
        if not job:
            return
        saving = job["step"] in (BQ.SAVING, BQ.SAVE_WAITING)
        if job["step"] in BQ.RUNNING:
            chime()
            if not messagebox.askyesno("CleanListen", f"Stop {'saving' if saving else 'working on'} "
                                       f"“{job.get('title', 'this book')}”?" + (
                                           "" if saving else "\n\nWhat it has listened to so far is "
                                           "kept. Try again carries on from there.")):
                return
            self.workers.stop(key, wait=1.0 if saving else 8.0)
        self.books.stop(key)
        self._run_queue()
        self.show_queue()

    def _remove_book(self, key):
        self.workers.resume(key)
        self.books.remove(key)
        self._open_rows.discard(key)
        self.show_queue()

    def _move_book(self, key, by):
        self.books.move(key, by)
        self.show_queue()

    def _clear_done(self):
        self.books.clear_finished()
        self.show_queue()

    def _refined_for(self, job):
        try:
            a = json.loads((Path(job["workdir"]) / "analysis.json").read_text())
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't read that book's review ({ex}).")
            return
        a["title"] = job.get("title") or a.get("title", "")
        keep = self.analysis
        self.analysis = a
        try:
            self.export_refined()
        finally:
            self.analysis = keep

    def review_job(self, key):
        """Open a ready book's review (one at a time, on the usual review page)."""
        job = self.books.find(key)
        if not job or job["step"] != BQ.READY:
            return
        try:
            a = json.loads((Path(job["workdir"]) / "analysis.json").read_text())
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't open this book's review ({ex}). "
                                 "Press Remove, then add the book again.")
            return
        a["title"] = job.get("title") or a.get("title", "")
        self.analysis = a
        self.audio, self.ebook, self.outdir = list(job["audio"]), job.get("ebook"), job["outdir"]
        self.workdir = Path(job["workdir"])
        self.split_chapters = job.get("split", False)
        self.make_m4b = job.get("m4b", False)
        self.cover_pick, self.author = job.get("cover"), job.get("author") or ""
        self.saved_opts = dict(job.get("opts") or self.saved_opts)
        self.review_key = key
        self.view_mode = "list"
        self.show_review()

    def _queue_this_review(self):
        """The book whose review is open, as a row on "Your books" (a review from before the
        queue, or picked up again, has none yet)."""
        job = self.books.find(self.review_key or "")
        if job is None:
            a = self.analysis or {}
            opts = self.saved_opts or {}
            parts = list(self.audio or a.get("parts", []))
            spec = {"audio": parts, "ebook": self.ebook,
                    "outdir": self.outdir or str(Path(parts[0]).parent / "Clean"),
                    "title": a.get("title") or book_title(parts),
                    "workdir": str(self.workdir), "groups": a.get("groups", []), "filter_args": {},
                    "split": getattr(self, "split_chapters", False), "opts": dict(opts),
                    "m4b": getattr(self, "make_m4b", False),
                    "cover": getattr(self, "cover_pick", None),
                    "author": getattr(self, "author", "") or None, **self._places_for_job(),
                    "summary": F.summary(opts) if F.anything_on(opts) else "",
                    "profile": dict(F.PROFILES).get(opts.get("profile"), ""),
                    "length": a.get("duration", 0), "task": "save"}
            job = self.books.add_ready(spec)
            self.review_key = job["key"]
        return job

    def _leave_review(self):
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_win.destroy()
        self.review_key = None
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.cover_pick, self.author = None, ""

    # ---------- page 3: review everything before saving ----------
    def _y_in_list(self, w):
        """How far down the review list a card/row sits (pixels from the top), across the
        list's blocks."""
        y = 0
        canvas = getattr(self, "_canvas", None)
        while w is not None and w.master is not None and w.master is not canvas:
            y += w.winfo_y()
            w = w.master
        if w is not None and canvas is not None:
            try:
                item = next(i for i in canvas.find_all() if canvas.type(i) == "window"
                            and canvas.itemcget(i, "window") == str(w))
                y += int(canvas.coords(item)[1])
            except (StopIteration, tk.TclError, IndexError):
                pass
        return y

    def show_review(self, keep_scroll=False, focus=None):
        """The review list. keep_scroll: redraw without moving - the list stays on the same
        passage you were looking at (focus: the passage/word you just asked about)."""
        engine.use_language((self.analysis or {}).get("language"))   # this book's word lists
        anchor = None
        if keep_scroll and self.page_name == "review" and getattr(self, "_canvas", None):
            try:
                c = self._canvas
                h = self._list_height()
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
            c = self._canvas
            h = self._list_height()
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
        self._sections = []
        scenes, mutes = a["scenes"], a["mutes"]
        if not scenes and not mutes:
            sub = "Nothing to remove was found in this book."
        else:
            sub = ("Everything ticked below will be removed. Untick anything you want to keep. "
                   "▶ Play lets you hear it first.")
        p = self._new_page("Review before saving", sub, name=a.get("title", ""))
        self.page_name = "review"
        note = getattr(self, "resume_note", None)
        if note:
            self.resume_note = None
            self.updated_note = CL.said_briefly(tk.Label(
                p, text="✓ " + note, bg=TINT, fg=ACCENT_DK, font=(FONT, 10), padx=10, pady=6,
                anchor="w"))
            self.updated_note.pack(fill="x", pady=(0, 8))
        # what the checks said, folded to one line ("More" shows all of it)
        notes = [n for n in (engine.plain_ai(a.get("claude_note")), a.get("learn_note"),
                             a.get("ai_note"), a.get("ebook_note")) if n]
        if notes:
            nrow = tk.Frame(p, bg=BG)
            nrow.pack(fill="x", pady=(0, 4))
            full, first = "\n".join(notes), notes[0]
            short = first if len(first) <= 115 else first[:112].rsplit(" ", 1)[0] + "…"
            nlbl = tk.Label(nrow, text=full if getattr(self, "_notes_open", False) else short, bg=BG,
                            fg=MUTED, font=(FONT, 9), wraplength=660, justify="left")
            nlbl.pack(side="left", anchor="w")
            if full != short:
                more = tk.Label(nrow, text="Less" if getattr(self, "_notes_open", False) else "More",
                                bg=BG, fg=ACCENT, font=(FONT, 9, "underline"), cursor="hand2")
                more.pack(side="left", anchor="n", padx=(6, 0))

                def flip(_e=None):
                    self._notes_open = not getattr(self, "_notes_open", False)
                    nlbl.config(text=full if self._notes_open else short)
                    more.config(text="Less" if self._notes_open else "More")
                more.bind("<Button-1>", flip)
        N = self._ai_name()
        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", pady=(2, 6))
        if a.get("sentences"):
            ttk.Button(bar, text=f"Ask {N}…", style="Plain.TButton",
                       command=self.open_chat).pack(side="left")
            ttk.Button(bar, text=(f"Check again with {N}" if a.get("claude_checked")
                                  else f"Check everything with {N}"), style="Plain.TButton",
                       command=self.claude_check).pack(side="left", padx=(8, 0))
        if getattr(self, "_undo", None):
            ttk.Button(bar, text="Undo the AI's last change", style="Plain.TButton",
                       command=self._undo_last).pack(side="left", padx=(8, 0))
        # the things used now and then go in one menu
        more_btn = ttk.Menubutton(bar, text="More", style="Plain.TMenubutton", width=6)
        menu = tk.Menu(more_btn, tearoff=0, font=(FONT, 10), bg=CARD, fg=INK,
                       activebackground=ACCENT, activeforeground="white")
        # (this list is for your chat with Claude, the one who works on CleanListen, so it
        # still says so, as "Drag this file into your chat with Claude" does)
        menu.add_command(label="Save a list of everything for Claude…", command=self.export_findings)
        menu.add_command(label="Open the AI's findings for this book (spreadsheet)",
                         command=lambda: self._open_findings(this_book=True))
        menu.add_command(label="Open the AI's findings for every book (spreadsheet)",
                         command=self._open_findings)
        cc = self._cc()
        if cc and cc.PROVIDER == "claude":
            models = tk.Menu(menu, tearoff=0, font=(FONT, 10), bg=CARD, fg=INK,
                             activebackground=ACCENT, activeforeground="white", selectcolor=INK)
            self._model_var = tk.StringVar(value=cc.get_model())
            for key, label in cc.MODELS:
                models.add_radiobutton(label=label, value=key, variable=self._model_var,
                                       command=lambda k=key: cc.set_model(k))
            menu.add_separator()
            menu.add_cascade(label="Claude model", menu=models)
        more_btn["menu"] = menu
        more_btn.pack(side="right")
        if a.get("sentences"):
            ttk.Button(bar, text="Search all text…", style="Plain.TButton",
                       command=self.open_all_text).pack(side="right", padx=(0, 8))

        # which items to show; things Claude/ChatGPT (or what CleanListen learned) marked fine
        # stay in the book and are hidden unless you ask for everything
        view = getattr(self, "view_mode", "list")
        hidden_fine = ([x for x in scenes if _marked_fine(x, "cut", "ai_note")] +
                       [x for x in mutes if _marked_fine(x, "on", "note")])

        def shown(x, key, note_key):
            if view == "all":
                return True
            if _marked_fine(x, key, note_key):
                return False
            if view == "decide":
                return _to_decide(x, key, note_key)
            if view == "ticked":
                return bool(x.get(key, True))
            return True
        vrow = tk.Frame(p, bg=BG)
        vrow.pack(fill="x", pady=(0, 2))
        tk.Label(vrow, text="Show:", bg=BG, fg=INK, font=(FONT, 10)).pack(side="left")
        labels = dict(REVIEW_VIEWS)
        vvar = tk.StringVar(value=labels.get(view, labels["list"]))
        vbox = ttk.Combobox(vrow, textvariable=vvar, values=[lbl for _, lbl in REVIEW_VIEWS],
                            state="readonly", width=34, font=(FONT, 10))
        vbox.pack(side="left", padx=(6, 0))

        def pick(_e=None):
            self._sync_ticks()
            self.view_mode = next(k for k, lbl in REVIEW_VIEWS if lbl == vvar.get())
            self.show_review()
        vbox.bind("<<ComboboxSelected>>", pick)
        if hidden_fine and view != "all":
            tk.Label(vrow, text=f"{len(hidden_fine)} marked fine (left in the book) not shown", bg=BG,
                     fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(10, 0))
        jump = tk.Frame(p, bg=BG)
        jump.pack(fill="x", pady=(2, 0))

        if getattr(self, "make_m4b", False):
            # choose the M4B's cover here too, without starting over (2026-11-05)
            crow = tk.Frame(self.footer, bg=BG)
            crow.pack(side="top", fill="x", pady=(0, 4))
            self.review_cover_lbl = tk.Label(crow, text="", bg=BG, fg=MUTED, font=(FONT, 10))
            self.review_cover_lbl.pack(side="left")
            ch = tk.Label(crow, text="Change cover\u2026", bg=BG, fg=ACCENT,
                          font=(FONT, 10, "underline"), cursor="hand2")
            ch.pack(side="left", padx=(8, 0))
            ch.bind("<Button-1>", lambda e: self._change_review_cover())
            self._show_review_cover()
        self.summary_lbl = tk.Label(self.footer, text="", bg=BG, fg=INK, font=(FONT, 10))
        self.summary_lbl.pack(side="top", anchor="w", pady=(0, 6))
        row = tk.Frame(self.footer, bg=BG)
        row.pack(fill="x")
        ttk.Button(row, text="Save clean audiobook", style="Main.TButton",
                   command=self._save_from_review).pack(side="right")
        ttk.Button(row, text="Change filters & re-check", style="Plain.TButton",
                   command=self.recheck_same).pack(side="right", padx=(0, 10))
        # a way out without saving (Jason): the review is kept to pick up again
        ttk.Button(row, text="\u25c0 My books", style="Plain.TButton",
                   command=self._back_to_start).pack(side="left")
        # send it in now, without saving the audiobook first (the ticks as they are now count)
        ttk.Button(row, text="Send what we refined…", style="Plain.TButton",
                   command=self._send_report_now).pack(side="left", padx=(8, 0))
        body = self._scroll_area(p, stacked=True)     # body(): the block for the next thing
        multi = len(a["parts"]) > 1
        # "at 0:12:34" (how far into the book), so it isn't read as a clock (Jason, 2026-11-03)
        where = lambda x: (f"Part {x['part'] + 1}, " if multi else "") + "at " + engine.fmt_t(x["s"])

        def section(title, short, count, var_list):
            head = tk.Frame(body(), bg=BG)
            head.pack(fill="x", pady=(10, 4))
            self._sections.append((short, count, head))
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

        def link(parent, text, bg, command, padx=0):
            l = tk.Label(parent, text=text, bg=bg, fg=ACCENT, font=(FONT, 9, "underline"),
                         cursor="hand2", padx=padx)
            l.bind("<Button-1>", lambda e: command(l))
            return l

        def fit(t):
            """Make a text box exactly as tall as its wrapped lines (at most 8)."""
            try:
                n = t.count("1.0", "end", "displaylines")
                want = max(1, min(8, int((n[0] if isinstance(n, tuple) else n) or 1)))
                if int(t.cget("height")) != want:
                    t.configure(height=want)
            except (tk.TclError, ValueError):
                pass

        # passages, grouped by kind
        self.scene_vars = []
        for kind, heading, short in REVIEW_KINDS:
            items = [sc for sc in scenes if sc.get("kind", "sex") == kind and shown(sc, "cut", "ai_note")]
            if not items:
                continue
            group_vars = []
            section(heading, short, len(items), group_vars)
            for sc in items:
                rc = CL.card(body())
                self._item_widgets[id(sc)] = rc
                rc.pack(fill="x", pady=4, padx=(0, self._px(4)))
                card = rc.body
                v = tk.BooleanVar(value=sc.get("cut", True))
                self.scene_vars.append((v, sc))
                group_vars.append((v, sc))
                secs = sc["e"] - sc["s"]
                length = f"{secs / 60:.1f} min" if secs >= 60 else f"{secs:.0f} sec"
                top = tk.Frame(card, bg=CARD)
                top.pack(fill="x")
                ttk.Checkbutton(top, text=f"Cut this   ·   {where(sc)}   ·   {length}",
                                variable=v, command=self._update_summary).pack(side="left")
                link(top, "▶ Play", CARD, lambda l, it=sc: self._play(it, l)).pack(side="left", padx=(16, 0))
                if sc.get("ai_note"):
                    good = _yellow(sc["ai_note"])
                    tk.Label(top, text=engine.plain_ai(sc["ai_note"]), bg=YELLOW if good else TINT,
                             fg=YELLOW_INK if good else ACCENT_DK, font=(FONT, 9),
                             padx=6).pack(side="right")
                if sc.get("claude_reason"):
                    tk.Label(card, text=engine.AI + ": " + sc["claude_reason"], bg=CARD,
                             fg=MUTED, font=(FONT, 9, "italic"), wraplength=680, justify="left"
                             ).pack(anchor="w", pady=(4, 0))
                txt = tk.Text(card, wrap="word", width=20, height=min(8, 1 + len(sc["text"]) // 95),
                              font=(FONT, 10), bg=QUOTE, fg=INK, relief="flat",
                              padx=8, pady=6, borderwidth=0)
                txt.insert("1.0", sc["text"])
                txt.configure(state="disabled")
                txt.pack(fill="x", pady=(6, 0))
                txt.bind("<Configure>", lambda e, t=txt: fit(t))
                if sc.get("chat_answer"):
                    said = tk.Label(card, text=f"{N}: " + sc["chat_answer"], bg=TINT,
                                    fg=ACCENT_DK, font=(FONT, 9), wraplength=680, justify="left",
                                    padx=8, pady=4, anchor="w")
                    said.pack(fill="x", pady=(6, 0))
                    CL.fit_text(said, said, margin=20)      # its own width, less its padding
                if a.get("sentences"):
                    link(card, f"Ask {N} about this…", CARD,
                         lambda l, c=card, it=sc, t=txt: self._ask_inline(c, it, t, l, "P")
                         ).pack(anchor="e", pady=(4, 0))

        # words
        self.mute_vars = []
        shown_mutes = [m for m in mutes if shown(m, "on", "note")]
        if shown_mutes:
            section("Words to mute", "Words", len(shown_mutes), self.mute_vars)
            for n, m in enumerate(shown_mutes):
                if n % WORDS_PER_BOX == 0:     # (a box of its own every so many words)
                    rc = CL.card(body(new=True), pad=(8, 8))
                    rc.pack(fill="x", padx=(0, self._px(4)),
                            pady=(4 if n == 0 else 0, 4 if n + WORDS_PER_BOX >= len(shown_mutes) else 0))
                    box = rc.body
                row = tk.Frame(box, bg=CARD if n % 2 == 0 else SHADE, padx=10, pady=3)
                self._item_widgets[id(m)] = row
                row.pack(fill="x")
                rbg = row.cget("bg")
                v = tk.BooleanVar(value=m.get("on", True))
                self.mute_vars.append((v, m))
                ttk.Checkbutton(row, variable=v, command=self._update_summary).pack(side="left")
                tk.Label(row, text=where(m), bg=rbg, fg=MUTED, font=(FONT, 9), width=18 if multi else 10,
                         anchor="w").pack(side="left")
                tk.Label(row, text=CAT_LABELS.get(m.get("cat"), m.get("cat") or ""), bg=rbg, fg=MUTED,
                         font=(FONT, 8), width=12, anchor="w").pack(side="left")
                # "Show" reveals the real word and its sentence; hidden (starred) by default
                show = tk.Label(row, text="Show", bg=rbg, fg=ACCENT, font=(FONT, 9, "underline"),
                                cursor="hand2", padx=6)
                if m.get("word_raw"):
                    show.pack(side="right")
                if a.get("sentences"):
                    link(row, "Ask", rbg, lambda l, it=m, r=row: self._ask_inline(r, it, None, l, "W"),
                         padx=4).pack(side="right")
                link(row, "▶ Play", rbg, lambda l, it=m: self._play(it, l), padx=4).pack(side="right")
                if m.get("note"):
                    good = _yellow(m["note"])
                    tk.Label(row, text=engine.plain_ai(m["note"]), bg=YELLOW if good else TINT,
                             fg=YELLOW_INK if good else ACCENT_DK, font=(FONT, 8),
                             padx=4).pack(side="right")
                elif m.get("src", "audio") != "audio":
                    tk.Label(row, text="from ebook", bg=rbg, fg=ACCENT, font=(FONT, 8)).pack(side="right")
                # the line of text wraps to fit the window, with the muted word highlighted
                line = tk.Text(row, wrap="word", width=20, height=1, font=(FONT, 10), bg=rbg,
                               fg=MUTED, relief="flat", borderwidth=0, highlightthickness=0,
                               cursor="arrow")
                line.tag_configure("w", background=WORD_BG, foreground=WORD_INK,
                                   font=(FONT, 10, "bold"))

                def fill(t=line, m=m, revealed=False):
                    before = m.get("ctx_raw" if revealed else "ctx", "")
                    word = m.get("word_raw" if revealed else "word", "")
                    after = m.get("ctx_after_raw" if revealed else "ctx_after", "")
                    if revealed and m.get("claude_reason"):
                        after += "   (" + engine.AI + ": " + m["claude_reason"] + ")"
                    t.configure(state="normal")
                    t.delete("1.0", "end")
                    if before:
                        t.insert("end", "…" + before + " ")
                    t.insert("end", f" {word} ", "w")
                    if after:
                        t.insert("end", " " + after + "…")
                    t.configure(state="disabled")
                    fit(t)

                def toggle(_e=None, t=line, m=m, lbl=show, state={"on": False}):
                    state["on"] = not state["on"]
                    fill(t, m, state["on"])
                    lbl.configure(text="Hide" if state["on"] else "Show")

                show.bind("<Button-1>", toggle)
                fill()
                line.pack(side="left", fill="x", expand=True)
                line.bind("<Configure>", lambda e, t=line: fit(t))
        if not self._sections and (scenes or mutes):
            tk.Label(body(), text="Nothing to show here. Choose “Everything to remove” next to Show.",
                     bg=BG, fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=20)

        # jump straight to a group (long books have hundreds of items)
        if len(self._sections) > 1:
            tk.Label(jump, text="Jump to:", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
            for short, count, head in self._sections:
                link(jump, f"{short} ({count})", BG, lambda l, h=head: self._jump_to(h),
                     padx=5).pack(side="left")
        else:
            jump.pack_forget()
        self._update_summary()

    def _jump_to(self, widget):
        c = self._canvas

        def go():
            if widget.winfo_exists() and c.winfo_exists():
                c.update_idletasks()
                c.yview_moveto(max(0.0, (self._y_in_list(widget) - 4) / self._list_height()))
        go()
        # cards coming into view settle to their size and shift the list: aim again
        for delay in (120, 400, 900):
            self.after(delay, go)

    def _open_findings(self, this_book=False):
        """Claude's findings as a spreadsheet: this book's (Jason, 2026-11-07, in CleanView: "it
        had every movie"), or every book's, newest first."""
        try:
            import cleanlisten_learn as learn
            path = learn.CSV_PATH
            if this_book:
                path = learn.book_csv((self.analysis or {}).get("title", ""))
                if path is None:
                    messagebox.showinfo("CleanListen", "Nothing saved for this book yet. Findings "
                                        "are saved each time Claude, ChatGPT or Gemini checks it.")
                    return
        except Exception:
            path = None
        if path and path.exists():
            open_path(str(path))
        else:
            messagebox.showinfo("CleanListen", "Nothing saved yet. Findings are saved each time "
                                "Claude, ChatGPT or Gemini checks a book.")

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
                        bg=CARD, fg=INK, selectbackground=ACCENT, selectforeground="white",
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

    # ---------- listen to a passage or word ----------
    def _play(self, item, link):
        """Play that part of the book, with a second either side. Click again to stop."""
        was = getattr(self, "_playing", None)
        self._stop_playing()
        if was is item:
            return
        self._playing, self._play_link = item, link
        link.config(text="■ Stop")
        self._play_n = getattr(self, "_play_n", 0) + 1     # two files: never overwrite the one playing
        dst = APP_DATA / f"preview{self._play_n % 2}.wav"
        path = self.analysis["parts"][item["part"]]

        def work():
            try:
                APP_DATA.mkdir(parents=True, exist_ok=True)
                a, b = engine.extract_clip(path, item["s"], item["e"], dst)
                self.q.put(("play", item, str(dst), b - a))
            except Exception as ex:
                self.q.put(("play_fail", item, str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _play_ready(self, item, wav, secs):
        if getattr(self, "_playing", None) is not item:
            return             # stopped (or another one started) while the clip was being made
        try:
            import winsound
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except ImportError:
            open_path(wav)
        token = self._play_n
        self.after(int(secs * 1000) + 300, lambda: self._play_n == token and self._stop_playing())

    def _stop_playing(self):
        if getattr(self, "_playing", None) is None:
            return
        self._playing = None
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except ImportError:
            pass
        link = getattr(self, "_play_link", None)
        if link is not None and link.winfo_exists():
            link.config(text="▶ Play")

    def _update_summary(self):
        """What saving will do: the ticks on screen, plus items the "Show" choice hides."""
        a = self.analysis or {}
        on_screen = {id(sc): v.get() for v, sc in getattr(self, "scene_vars", [])}
        on_screen.update({id(m): v.get() for v, m in getattr(self, "mute_vars", [])})
        cuts = [sc for sc in a.get("scenes", []) if on_screen.get(id(sc), sc.get("cut", True))]
        nm = sum(1 for m in a.get("mutes", []) if on_screen.get(id(m), m.get("on", True)))
        ns, secs = len(cuts), sum(sc["e"] - sc["s"] for sc in cuts)
        removed = (f" ({secs / 60:.1f} min removed)" if secs >= 60 else
                   f" ({secs:.0f} sec removed)" if secs else "")
        self.summary_lbl.config(text=f"Saving will mute {nm} word{'s' if nm != 1 else ''} and cut "
                                     f"{ns} passage{'s' if ns != 1 else ''}{removed}")

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
             "Filters ticked: " + (", ".join(k for k, v in opts.items() if v not in (False, None, "keep"))
                                   or "(not recorded)"),
             f"Ebook used: {'yes' if a.get('ebook') else 'no'}"]
        for note in (a.get("claude_note"), a.get("ai_note"), a.get("ebook_note")):
            if note:
                L.append("Note: " + note)
        names = {"sex": "EXPLICIT SCENE", "ref": "SEXUAL REFERENCE", "gore": "GORE",
                 "religion": "RELIGION", "relationship": "RELATIONSHIP", "crude": "CRUDE HUMOR",
                 "bully": "BULLYING", "disrespect": "DISRESPECT", "flirt": "FLIRTING",
                 "kiss": "KISSING", "kiss_ss": "SAME-SEX KISSING", "sleeping": "SLEEPING AROUND",
                 "unmarried": "UNMARRIED COUPLE", "graphic": "GRAPHIC VIOLENCE",
                 "violence": "VIOLENCE", "disturbing": "DISTURBING", "medical": "MEDICAL",
                 "nudity": "NUDITY",
                 "implied": "IMPLIED NUDITY", "immodest": "IMMODEST CLOTHING", "smoking": "SMOKING",
                 "drinking": "DRINKING", "drugs": "DRUGS", "gestures": "RUDE GESTURE",
                 "holiday": "HOLIDAY",
                 "birthday": "BIRTHDAY CANDLES", "magic": "MAGIC", "darkmagic": "DARK MAGIC",
                 "vampires": "VAMPIRES & WEREWOLVES"}
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

    def _cover_name(self, path):
        if not path:
            return "the book's own picture (or one found for it)"
        name = Path(path).name
        if name.startswith("online cover"):
            return "the picture found online"
        m = re.match(r"picture (\d+) in the book", Path(path).stem)
        if m:
            return f"picture {m.group(1)} in the book"
        return name

    def _show_review_cover(self):
        lbl = getattr(self, "review_cover_lbl", None)
        if lbl and lbl.winfo_exists():
            lbl.config(text="M4B cover: " + self._cover_name(getattr(self, "cover_pick", None)))

    def _change_review_cover(self):
        parts = list(self.audio or (self.analysis or {}).get("parts", []))

        def picked(f):
            self.cover_pick = f
            job = self.books.find(getattr(self, "review_key", None) or "")
            if job is not None:
                job["cover"] = f
                self.books.save()
            self._show_review_cover()
        self.choose_cover(parts, self.workdir, picked,
                          now=self._cover_name(getattr(self, "cover_pick", None)))

    def _change_job_cover(self, key):
        """A book whose saving stopped: choose its cover, then Try again (nothing is listened
        to or checked again)."""
        job = self.books.find(key)
        if not job:
            return

        def picked(f):
            job["cover"] = f
            self.books.save()
            self.show_queue()
        self.choose_cover(job.get("audio") or [], job["workdir"], picked,
                          now=self._cover_name(job.get("cover")))

    def _save_from_review(self):
        """Save: the ticks go into the book's analysis, and saving waits its turn on "Your
        books" (bookrunner.save reads them), so you can review the next book meanwhile."""
        self._sync_ticks()
        self._learn_choices()            # (also writes the ticks to analysis.json)
        try:
            job = self._queue_this_review()
        except BQ.Busy:
            messagebox.showinfo("CleanListen", "This book is being checked again right now. Wait "
                                "for that to finish, then review it again.")
            return
        if getattr(self, "make_m4b", False) and getattr(self, "cover_pick", None):
            job["cover"] = self.cover_pick       # (chosen on the review page)
        self.books.reviewed(job["key"])
        self._leave_review()
        self._run_queue()
        self.show_queue()

    def _learn_choices(self):
        """Learn from what you chose (each choice counted once, however often you leave the
        review and come back), and keep the marks that say so with the review."""
        try:
            import cleanlisten_learn as learn
            learn.record(self.analysis)
        except Exception:
            pass
        self._save_analysis()

    def _send_report_now(self):
        """"Send what we refined" from the review page, before the clean audiobook is saved."""
        self._sync_ticks()
        self._save_analysis()
        self.export_refined()

    def export_refined(self):
        try:
            import cleanlisten_learn as learn
            path = learn.export_book(self.analysis, title=(self.analysis or {}).get("title", ""))
        except Exception as ex:
            messagebox.showerror("CleanListen", f"Couldn't save the file: {ex}")
            return
        self._send_or_save(path, "refined")

    def _send_or_save(self, path, kind):
        """Offer to send an exported file in. If there's no inbox yet, she says no, or
        sending fails, show where it was saved and how to send it by hand."""
        import cleanlisten_learn as learn
        if learn.send_url() and (chime() or messagebox.askyesno(
                "CleanListen", "Send it in now?\n\nIt has the sentences and words you and the "
                "AI cut, muted or kept, and their notes. No audio.")):
            def go():
                try:
                    learn.send(path, kind)
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
            "CleanListen", why + f"Saved as \u201c{path.name}\u201d in {path.parent}.\n\n"
            "Attach that file in your chat with Claude and ask for it to be added to CleanListen. "
            "Every copy gets it with the next update.\n\nIt has the sentences and words you and "
            "the AI cut, muted or kept, and their notes. No audio.")

    def _sent(self, path, ex):
        if ex is None:
            messagebox.showinfo("CleanListen", "Sent. Thank you!")
        else:
            self._saved_by_hand(path, "Couldn't send it just now.\n\n")

    def reset(self):
        self.audio, self.ebook, self.outdir, self.analysis = [], None, None, None
        self.show_setup()


def _make_shortcut():
    # Adds the CleanRead and ReadAloud desktop shortcuts (they ship alongside CleanListen), and
    # points an old CleanView icon CleanListen made at the real CleanView (its own program now)
    try:
        import shortcuts
    except Exception:
        return
    for make in ("ensure_cleanread_shortcut", "ensure_readaloud_shortcut", "fix_cleanview_shortcut"):
        try:
            getattr(shortcuts, make)()
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
    threading.Thread(target=_make_shortcut, daemon=True).start()
    threading.Thread(target=_ollama_off_at_startup, daemon=True).start()
    App().mainloop()
    _ollama_stop_later()
