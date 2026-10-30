"""The filters CleanListen and CleanRead both offer: the same as CleanView's, for books (Lauren,
2026-10-30: "CleanRead needs all the same filters as CleanListen and CleanView").

- SECTIONS: every box, grouped as in CleanView, with this family's book standard (the Adults
  ticks). Religion comes in parts (preaching, anger at God, prayers & verses).
- PROFILES / PRESETS: "Filtering for" Young kids, Kids, Teens or Adults, as in CleanView. Each
  remembers its own ticks.
- Your saved ticks and your own words to mute live in filters.json, shared by both apps, so
  CleanListen and CleanRead always filter the same way.
- FiltersWindow: the "Choose filters" window both apps open from their setup page.
"""
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
SAVED = APP_DATA / "filters.json"
OLD_CLEANREAD = APP_DATA / "cleanread_settings.json"   # CleanRead's ticks before 1.11.0

BG, CARD, INK, MUTED, ACCENT, LINE = "#F6F3EE", "#FFFFFF", "#23211F", "#5C5852", "#2F6F62", "#E3DED6"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

KISS_LEVELS = (("keep", "Keep"), ("passionate", "Cut passionate kisses"), ("all", "Cut all kisses"))
RELIGION_PARTS = (("preach", "Preaching"), ("anger", "Anger at God"), ("prayers", "Prayers & verses"))
# (heading, columns, [(key, label, ticked in this family's book standard)]). A kissing row is
# (key, label, level); "religion" gets its parts underneath.
SECTIONS = [
    ("Language", 1, [
        ("swearing", "Swearing  (f-word, s-word, b-word…)", True),
        ("mild", "Mild words  (damn, hell, crap, “screw you”)", True),
        ("deity", "God's name used as a swear", True),
        ("minced", "Soft substitutes  (gosh, heck, freaking)", False),
        ("sexual", "Sexual words  (sex, sexy…)", True),
        ("samesexwords", "Words about same-sex relationships  (gay, lesbian…)", True),
        ("rude", "Rude words kids copy  (stupid, dumb, idiot, shut up…)", False),
        ("refs", "Sexual references and innuendo", True),
        ("crude", "Crude humor  (toilet and gross-out jokes)", True),
        ("bully", "Bullying and mocking", False),
        ("disrespect", "Disrespect  (bratty, talking back, disobeying parents)", False),
        ("religion", "Religious content", True)]),
    ("Sex and nudity", 1, [
        ("nudity", "Nudity  (someone described naked)", False),
        ("implied", "Implied nudity  (under sheets, in towels, bare backs)", False),
        ("sex", "Sex scenes", True),
        ("immodest", "Immodest clothing  (swimsuits, underwear, sexy dancing)", False),
        ("sleeping", "Sleeping around  (casual sex, affairs)", False)]),
    ("Kissing and relationships", 1, [
        ("kiss", "Man & woman kissing", "keep"),
        ("kiss_ss", "Same-sex kissing", "passionate"),
        ("relationships", "Same-sex relationships  (flirting, talk and intimate scenes)", True),
        ("unmarried", "Unmarried couples living or sleeping together", False),
        ("flirt", "Flirting", False)]),
    ("Violence", 1, [
        ("violence", "Violence  (fights, shootings, attacks)", False),
        ("graphic", "Graphic violence  (blood, bloody wounds)", True),
        ("gore", "Gore  (insides showing, dismemberment)", True),
        ("disturbing", "Disturbing  (torture, executions, cruelty, bloody accidents)", False)]),
    ("Other", 2, [
        ("smoking", "Smoking", False), ("drinking", "Drinking alcohol", False),
        ("drugs", "Drug use", False),
        ("gestures", "Rude and sexual gestures  (the middle finger, crude motions)", False)]),
    ("Holidays and birthdays", 1, [
        ("holiday", "Holidays  (Christmas, Halloween, Easter, Valentine's Day, St. Patrick's Day)",
         False),
        ("birthday", "Candles on a birthday cake  (parties and cake are fine)", False)]),
    ("Magic and monsters", 1, [
        ("darkmagic", "Dark magic  (witchcraft, wizards, curses, the occult)", False),
        ("magic", "Magic  (spells, wands, potions, fairies)", False),
        ("vampires", "Vampires and werewolves", False)]),
]
BOXES = [key for _, _, items in SECTIONS for key, _, d in items if isinstance(d, bool)]
LEVELS = [key for _, _, items in SECTIONS for key, _, d in items if isinstance(d, str)]
LABELS = {key: label for _, _, items in SECTIONS for key, label, _ in items}
TOPICS = ("holiday", "birthday", "magic", "darkmagic", "vampires")
WORD_GROUPS = ("swearing", "mild", "deity", "minced", "sexual", "rude")

STANDARD = {key: d for _, _, items in SECTIONS for key, _, d in items}
STANDARD.update({"religion_preach": True, "religion_anger": True, "religion_prayers": False})

# "Filtering for": the same ages and standard ticks as CleanView's PRESETS (books keep their
# religion box ticked, the family's book standard; it's preaching and anger at God by default)
PROFILES = (("young", "Young kids"), ("kids", "Kids"), ("teens", "Teens"), ("adults", "Adults"))
_ALL = dict(STANDARD, **dict.fromkeys(BOXES, True), kiss="all", kiss_ss="all")
PRESETS = {
    "young": dict(_ALL),
    "kids": dict(_ALL, kiss="passionate"),
    "teens": dict(_ALL, rude=False, minced=False, crude=False, implied=False, kiss="passionate",
                  **dict.fromkeys(TOPICS, False)),
    "adults": dict(STANDARD),
}


def _upgrade(ticks):
    """Ticks saved by older versions: one box for smoking, drinking and drugs, "gory
    descriptions" meaning graphic and gore, the old strict religion box."""
    t = dict(ticks)
    if "substances" in t:
        for k in ("smoking", "drinking", "drugs"):
            t.setdefault(k, bool(t["substances"]))
    if "gore" in t:
        t.setdefault("graphic", t["gore"])
    if "religion_strict" in t:
        t.setdefault("religion_prayers", t["religion_strict"])
    return {k: v for k, v in t.items() if k in STANDARD}


def load():
    """{"profile", "ticks": {profile: {...}}, "mywords": [...]}. The first time, the Adults ticks
    start from what was ticked in CleanRead before (or the family's book standard)."""
    try:
        d = json.loads(SAVED.read_text(encoding="utf8"))
    except Exception:
        d = {}
        try:
            old = json.loads(OLD_CLEANREAD.read_text(encoding="utf8"))
            d["ticks"] = {"adults": _upgrade(old)}
        except Exception:
            pass
    d.setdefault("profile", "adults")
    if d["profile"] not in PRESETS:
        d["profile"] = "adults"
    d.setdefault("ticks", {})
    d["mywords"] = [str(w) for w in d.get("mywords") or [] if str(w).strip()]
    return d


def save(d):
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        tmp = SAVED.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf8")
        os.replace(tmp, SAVED)
    except OSError:
        pass


def ticks(d=None, profile=None):
    """The ticks for one age: its saved ones over its standard ones."""
    d = d or load()
    profile = profile or d["profile"]
    return dict(PRESETS[profile], **_upgrade(d["ticks"].get(profile, {})))


def anything_on(t):
    return any(t.get(k) for k in BOXES if k != "religion") or (
        t.get("religion") and any(t.get("religion_" + p) for p, _ in RELIGION_PARTS)) or any(
        t.get(k) in ("passionate", "all") for k in LEVELS)


def summary(t, mywords=()):
    """What's ticked, in a few words, for the setup page."""
    out = [LABELS[k].split("  (")[0] for k in BOXES if t.get(k) and k != "religion"]
    if t.get("religion"):
        parts = [lbl[0].lower() + lbl[1:] for p, lbl in RELIGION_PARTS if t.get("religion_" + p)]
        if parts:
            out.append("religious content (" + ", ".join(parts) + ")")
    for k in LEVELS:
        if t.get(k) in ("passionate", "all"):
            out.append(LABELS[k] + (" (passionate)" if t[k] == "passionate" else ""))
    if mywords:
        out.append(f"your own words ({len(mywords)})")
    if not out:
        return "Nothing is ticked yet."
    first = out[0][0].upper() + out[0][1:]
    return "Taking out: " + ", ".join([first] + [o[0].lower() + o[1:] if not o.startswith("God")
                                                 else o for o in out[1:]]) + "."


def groups(t):
    """The word-list groups to mute (for CleanListen's engine)."""
    return [g for g in WORD_GROUPS if t.get(g)] + (["orientation"] if t.get("samesexwords") else [])


def listen_kwargs(t, mywords=()):
    """The ticks as cleanlisten.analyze() arguments (besides groups)."""
    parts = [p for p, _ in RELIGION_PARTS if t.get("religion_" + p)] if t.get("religion") else []
    return dict(
        find_sex=bool(t.get("sex")), find_refs=bool(t.get("refs")),
        find_graphic=bool(t.get("graphic")), find_gore=bool(t.get("gore")),
        find_religion=bool(parts), religion_parts=parts, strict_religion="prayers" in parts,
        find_relationships=bool(t.get("relationships")), find_crude=bool(t.get("crude")),
        find_bully=bool(t.get("bully")), find_disrespect=bool(t.get("disrespect")),
        find_flirt=bool(t.get("flirt")), find_topics=[k for k in TOPICS if t.get(k)],
        more=[k for k in ("sleeping", "unmarried", "nudity", "implied", "immodest", "violence",
                          "disturbing", "smoking", "drinking", "drugs", "gestures") if t.get(k)],
        kiss=t.get("kiss", "keep"), kiss_ss=t.get("kiss_ss", "keep"), mine=own_phrases(mywords))


def own_phrases(lines):
    import cleanlisten
    return cleanlisten.own_phrases(lines)


def read_opts(t, mywords=()):
    """The ticks as CleanRead's opts."""
    return dict(t, mywords=list(mywords))


# ---------------------------------------------------------------------------
# The setup page's "What to remove" card, and the "Choose filters" window
# ---------------------------------------------------------------------------
class FilterCard:
    """"Filtering for" (the ages), what's ticked in a few words, and "Choose filters…".
    on_change() is called when the ticks change."""

    def __init__(self, parent, on_change=None, wrap=640):
        self.d = load()
        self.on_change = on_change or (lambda: None)
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Filtering for:", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        self.profile = tk.StringVar(value=self.d["profile"])
        for key, label in PROFILES:
            tk.Radiobutton(row, text=label, value=key, variable=self.profile, bg=CARD,
                           activebackground=CARD, font=(FONT, 10),
                           command=self._profile_changed).pack(side="left", padx=(8, 0))
        self.lbl = tk.Label(parent, text="", bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=wrap,
                            justify="left", anchor="w")
        self.lbl.pack(fill="x", pady=(4, 4))
        bottom = tk.Frame(parent, bg=CARD)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Choose filters…", style="Plain.TButton",
                   command=self.open).pack(side="left")
        tk.Label(bottom, text="Each age remembers its own ticks. CleanListen and CleanRead share them.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=10)
        self._refresh()

    def ticks(self):
        return ticks(self.d)

    def mywords(self):
        return list(self.d["mywords"])

    def _refresh(self):
        self.lbl.config(text=summary(self.ticks(), self.d["mywords"]))

    def _profile_changed(self):
        self.d["profile"] = self.profile.get()
        save(self.d)
        self._refresh()
        self.on_change()

    def open(self):
        FiltersWindow(self.lbl.winfo_toplevel(), self.d, self._done)

    def _done(self):
        save(self.d)
        self._refresh()
        self.on_change()


class FiltersWindow(tk.Toplevel):
    """Every filter, grouped as in CleanView. Changes are kept for the age chosen."""

    def __init__(self, master, d, on_done):
        super().__init__(master)
        self.d, self.on_done = d, on_done
        name = dict(PROFILES)[d["profile"]]
        self.title(f"Choose filters — {name}")
        self.configure(bg=BG)
        try:
            scale = float(master.tk.call("tk", "scaling")) / 1.333
        except Exception:
            scale = 1.0
        w, h = int(700 * scale), int(min(760 * scale, master.winfo_screenheight() * 0.85))
        x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
        y = max(0, master.winfo_rooty() + (master.winfo_height() - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.transient(master)
        cur = ticks(d)
        self.vars = {}
        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=10)
        ttk.Button(foot, text="Done", style="Main.TButton", command=self._done).pack(side="right")
        ttk.Button(foot, text=f"Back to the standard ticks for {name}", style="Plain.TButton",
                   command=self._standard).pack(side="left")
        tk.Label(self, text=f"What to take out — {name}", bg=BG, fg=INK,
                 font=(FONT, 15, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(self, text="Bad words are marked out or muted; everything else is listed for you "
                 "to check before anything is cut.", bg=BG, fg=MUTED, font=(FONT, 9),
                 wraplength=640, justify="left").pack(anchor="w", padx=16, pady=(0, 6))
        body = self._scroll()
        for heading, cols, items in SECTIONS:
            card = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            card.pack(fill="x", padx=16, pady=4)
            tk.Label(card, text=heading, bg=CARD, fg=INK, font=(FONT, 11, "bold")).pack(
                anchor="w", padx=12, pady=(6, 2))
            grid = tk.Frame(card, bg=CARD)
            grid.pack(fill="x", padx=12, pady=(0, 8))
            n = 0
            for key, label, default in items:
                if isinstance(default, str):            # a kissing level
                    row = tk.Frame(grid, bg=CARD)
                    row.grid(row=n, column=0, columnspan=cols, sticky="w", pady=1)
                    tk.Label(row, text=label, bg=CARD, fg=INK, font=(FONT, 10), width=20,
                             anchor="w").pack(side="left")
                    v = tk.StringVar(value=dict(KISS_LEVELS).get(cur.get(key), "Keep"))
                    self.vars[key] = v
                    ttk.Combobox(row, textvariable=v, values=[n_ for _, n_ in KISS_LEVELS],
                                 state="readonly", width=22).pack(side="left")
                    n += cols
                    continue
                v = tk.BooleanVar(value=bool(cur.get(key)))
                self.vars[key] = v
                ttk.Checkbutton(grid, text=label, variable=v).grid(
                    row=n // cols, column=n % cols, sticky="w", padx=(0, 24), pady=1)
                n += 1
                if key == "religion":                   # its parts (Jason)
                    row = tk.Frame(grid, bg=CARD)
                    row.grid(row=n // cols, column=0, columnspan=cols, sticky="w", padx=(24, 0))
                    boxes = []
                    for p, plabel in RELIGION_PARTS:
                        pv = tk.BooleanVar(value=bool(cur.get("religion_" + p)))
                        self.vars["religion_" + p] = pv
                        boxes.append(ttk.Checkbutton(row, text=plabel, variable=pv))
                        boxes[-1].pack(side="left", padx=(0, 10))
                    show = lambda *_, bs=boxes, rv=v: [b.state(["!disabled"] if rv.get() else
                                                               ["disabled"]) for b in bs]
                    v.trace_add("write", show)
                    show()
                    n += cols
            if heading == "Language":
                tk.Label(card, text="Your own words and phrases to mark out or mute  (one per line, "
                         "for every age)", bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w", padx=12)
                self.words = tk.Text(card, height=4, font=(FONT, 10), wrap="none", relief="solid",
                                     borderwidth=1, highlightthickness=0, padx=6, pady=4)
                self.words.insert("1.0", "\n".join(d["mywords"]))
                self.words.pack(fill="x", padx=12)
                tk.Label(card, text="Taken out wherever they come up, the whole phrase: for example "
                         "“grow some stones”. Whole words only, so “stones” on "
                         "its own wouldn't touch “milestones”.", bg=CARD, fg=MUTED,
                         font=(FONT, 9), wraplength=600, justify="left").pack(anchor="w", padx=12,
                                                                              pady=(2, 8))
        self.protocol("WM_DELETE_WINDOW", self._done)
        self.grab_set()

    def _scroll(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def wheel(e):
            canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.num == 4 else 1), "units")
            return "break"                 # not the page behind
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(seq, wheel)
        self.canvas = canvas
        return inner

    def _standard(self):
        std = PRESETS[self.d["profile"]]
        for k, v in self.vars.items():
            v.set(dict(KISS_LEVELS)[std[k]] if k in LEVELS else bool(std[k]))

    def _done(self):
        t = {}
        for k, v in self.vars.items():
            t[k] = next(key for key, n in KISS_LEVELS if n == v.get()) if k in LEVELS else v.get()
        self.d["ticks"][self.d["profile"]] = t
        self.d["mywords"] = [ln.strip() for ln in self.words.get("1.0", "end").splitlines() if ln.strip()]
        self.grab_release()
        self.destroy()
        self.on_done()
