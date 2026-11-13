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

import cvlook as look

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"
SAVED = APP_DATA / "filters.json"
OLD_CLEANREAD = APP_DATA / "cleanread_settings.json"   # CleanRead's ticks before 1.11.0

BG, CARD, INK, MUTED, ACCENT, LINE = "#F6F3EE", "#FFFFFF", "#23211F", "#5C5852", "#2F6F62", "#E3DED6"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

KISS_LEVELS = (("keep", "Keep"), ("passionate", "Cut passionate kisses"), ("all", "Cut all kisses"))
RELIGION_PARTS = (("preach", "Preaching"), ("anger", "Anger at God"), ("prayers", "Prayers & verses"))
# (heading, columns, [(key, label, ticked in this family's book standard)]). A kissing row is
# (key, label, level); "religion" gets its parts underneath. In sections by topic, each with a box
# that ticks all of it and folding away to one line, as CleanView 1.18.74 (the owner, 2026-11-12:
# "send a message to the other 3 programs to create the redone tick boxes like the clean view
# format"; when it was designed: "a main box for each category to tick all if wanted, but if only
# some of the subcategories are wanted just those can be ticked. vid angel had a system like that",
# "maybe not as long", "lets make medical anything its own category"). Same keys as before.
SECTIONS = [
    ("Bad language", 1, [
        ("swearing", "Swearing  (f-word, s-word, b-word…)", True),
        ("mild", "Mild words  (damn, hell, crap, “screw you”)", True),
        ("deity", "God's name used as a swear", True),
        ("minced", "Soft substitutes  (gosh, heck, freaking)", False),
        ("sexual", "Sexual words  (sex, sexy…)", True),
        ("rude", "Rude words kids copy  (stupid, dumb, idiot, shut up…)", False),
        ("samesexwords", "Words about same-sex relationships  (gay, lesbian…)", True)]),
    ("Sex and nudity", 1, [
        ("refs", "Sexual references and innuendo", True),
        ("sex", "Sex scenes", True),
        ("nudity", "Nudity  (someone described naked)", False),
        ("implied", "Implied nudity  (under sheets, in towels, bare backs)", False),
        ("immodest", "Immodest clothing  (swimsuits, underwear, sexy dancing)", False),
        ("gestures", "Rude and sexual gestures  (the middle finger, crude motions)", False)]),
    ("Romance and relationships", 1, [
        ("kiss", "Man & woman kissing", "keep"),
        ("kiss_ss", "Same-sex kissing", "passionate"),
        ("sleeping", "Sleeping around  (casual sex, affairs)", False),
        ("unmarried", "Unmarried couples living or sleeping together", False),
        ("relationships", "Same-sex relationships  (flirting, talk and intimate scenes)", True),
        ("flirt", "Flirting", False)]),
    ("Violence", 1, [
        ("violence", "Violence  (fights, shootings, attacks)", False),
        ("graphic", "Graphic violence  (blood, bloody wounds)", True),
        ("gore", "Gore  (insides showing, dismemberment)", True),
        ("disturbing", "Disturbing  (torture, executions, cruelty, bloody accidents)", False)]),
    ("Medical", 1, [
        ("medical", "Medical  (surgery, autopsies, coroner and doctor talk, wounds being treated, "
                    "needles)", False)]),
    ("Attitude", 1, [
        ("bully", "Bullying and mocking", False),
        ("disrespect", "Disrespect  (bratty, talking back, disobeying parents)", False),
        ("crude", "Crude humor  (toilet and gross-out jokes)", True)]),
    ("Smoking, drinking and drugs", 3, [
        ("smoking", "Smoking", False), ("drinking", "Drinking alcohol", False),
        ("drugs", "Drug use", False)]),
    ("Faith, holidays and magic", 1, [
        ("religion", "Religious content", True),
        ("holiday", "Holidays  (Christmas, Halloween, Easter, Valentine's Day, St. Patrick's Day)",
         False),
        ("birthday", "Candles on a birthday cake  (parties and cake are fine)", False),
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
    if "gore" in t or "graphic" in t:
        # saved before the Medical box (1.17.21): it follows gory descriptions until you tick it
        t.setdefault("medical", bool(t.get("gore") or t.get("graphic")))
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
                          "disturbing", "medical", "smoking", "drinking", "drugs", "gestures")
              if t.get(k)],
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


SECTION_ICONS = {"Bad language": "mute", "Sex and nudity": "eye", "Romance and relationships": "heart",
                 "Violence": "warning", "Medical": "health", "Attitude": "smile",
                 "Smoking, drinking and drugs": "cup", "Faith, holidays and magic": "star"}
KISS_SHORT = {"Keep": "Keep", "Cut passionate kisses": "Passionate", "Cut all kisses": "All kisses"}
HEAD_FONT = "Segoe UI Semibold" if os.name == "nt" else "DejaVu Sans"


def _hex(widget, colour):
    """A colour as #RRGGBB (a plain window's own is a name like SystemButtonFace)."""
    try:
        return "#%02X%02X%02X" % tuple(c // 257 for c in widget.winfo_rgb(colour))
    except tk.TclError:
        return BG


def _is_on(v):
    val = v.get()
    return val != "Keep" if isinstance(val, str) else bool(val)


def build_boxes(parent, cur, mywords, on_change=None, padx=0, wrap=560, opened=None,
                on_fold=None, heads=None, scroll_to=None):
    """Every filter, in sections by topic as in CleanView 1.18.77, packed into `parent`: a grid of
    tiles, each with its icon, its name, a switch for the whole section (on, off, or pale for
    some), "3 of 5 on" or "Off", and "Choose ›". Choose opens that section's tick boxes in a card
    under the tiles (one section at a time) and outlines its tile in green.
    opened: the set of open section names (changed in place; on_fold() is called after).
    heads: a dict filled with name -> (switch, count label, tick_all, show) for tests.
    scroll_to(widget): asked to bring the opened section into view.
    Returns (vars, words box). on_change() is called whenever a tick or a choice changes."""
    on_change = on_change or (lambda: None)
    on_fold = on_fold or (lambda: None)
    opened = set() if opened is None else opened
    heads = {} if heads is None else heads
    C = look.C
    # the look in use (light or dark), not this module's light colours
    CARD, INK, MUTED, LINE, ACCENT = C["card"], C["ink"], C["muted"], C["line"], C["accent"]
    bg = _hex(parent, parent.cget("bg"))
    X = lambda n: look.px(parent, n)          # noqa: E731
    vars_ = {}
    words = None
    tiles = tk.Frame(parent, bg=bg)
    tiles.pack(fill="x", padx=padx, pady=(X(6), 0))
    for c in range(3):
        tiles.columnconfigure(c, weight=1, uniform="tiles")
    detail = look.Card(parent, radius=14, pad=(18, 14), bg=bg)
    dhead = tk.Frame(detail.body, bg=CARD)
    dhead.pack(fill="x", pady=(0, X(8)))
    dname = tk.Label(dhead, text="", bg=CARD, fg=INK, font=(HEAD_FONT, 12), anchor="w")
    dname.pack(side="left")
    dbody = tk.Frame(detail.body, bg=CARD)
    dbody.pack(fill="x")
    shows = {}
    if len(opened) > 1:                     # one at a time now
        keep = sorted(opened)[0]
        opened.clear()
        opened.add(keep)
    for n_sec, (heading, cols, items) in enumerate(SECTIONS):
        tile = look.Card(tiles, radius=14, pad=(13, 11))
        tile.grid(row=n_sec // 3, column=n_sec % 3, sticky="nsew", padx=(0, X(10)), pady=(0, X(10)))
        top = tk.Frame(tile.body, bg=CARD)
        top.pack(fill="x")
        badge = look.Badge(top, SECTION_ICONS.get(heading, "star"), size=30)
        badge.pack(side="left", anchor="n")
        switch = look.Switch(top)
        switch.pack(side="right", anchor="n", pady=(X(4), 0))
        name = tk.Label(tile.body, text=heading, bg=CARD, fg=INK, font=(HEAD_FONT, 10), anchor="w",
                        justify="left", wraplength=X(150), cursor="hand2")
        name.pack(fill="x", pady=(X(8), 0))
        low = tk.Frame(tile.body, bg=CARD)
        low.pack(fill="x", side="bottom", pady=(X(4), 0))
        count = tk.Label(low, text="", bg=CARD, fg=MUTED, font=(FONT, 9))
        count.pack(side="left")
        body = tk.Frame(dbody, bg=CARD)
        grid = tk.Frame(body, bg=CARD)
        grid.pack(fill="x")
        got, parts = [], {}            # the section's own choices; religion's parts (by its name)
        ctl = {}                       # this section's "Choose" link (made below)
        n = 0
        for key, label, default in items:
            if isinstance(default, str):            # a kissing level
                row = tk.Frame(grid, bg=CARD)
                row.grid(row=n, column=0, columnspan=cols, sticky="w", pady=X(3))
                tk.Label(row, text=label, bg=CARD, fg=INK, font=(FONT, 10), width=20,
                         anchor="w").pack(side="left")
                v = tk.StringVar(value=dict(KISS_LEVELS).get(cur.get(key), "Keep"))
                vars_[key] = v
                got.append(v)
                look.Segmented(row, [(full, KISS_SHORT[full]) for _, full in KISS_LEVELS], v,
                               size=9).pack(side="left")
                n += cols
                continue
            v = tk.BooleanVar(value=bool(cur.get(key)))
            vars_[key] = v
            got.append(v)
            ttk.Checkbutton(grid, text=label, variable=v).grid(
                row=n // cols, column=n % cols, sticky="w", padx=(0, X(24)), pady=X(2))
            n += 1
            if key == "religion":                   # its parts (Jason)
                row = tk.Frame(grid, bg=CARD)
                row.grid(row=n // cols, column=0, columnspan=cols, sticky="w", padx=(X(24), 0))
                boxes = []
                for p, plabel in RELIGION_PARTS:
                    pv = tk.BooleanVar(value=bool(cur.get("religion_" + p)))
                    vars_["religion_" + p] = pv
                    parts[str(v)] = parts.get(str(v), []) + [pv]
                    boxes.append(ttk.Checkbutton(row, text=plabel, variable=pv))
                    boxes[-1].pack(side="left", padx=(0, X(10)))
                show_parts = lambda *_, bs=boxes, rv=v: [b.state(["!disabled"] if rv.get() else
                                                                 ["disabled"]) for b in bs]
                v.trace_add("write", show_parts)
                show_parts()
                n += cols
        if heading == "Bad language":
            tk.Label(body, text="Your own words and phrases to mark out or mute  (one per line, "
                     "for every age)", bg=CARD, fg=INK, font=(HEAD_FONT, 10)).pack(
                         anchor="w", pady=(X(12), X(4)))
            words = tk.Text(body, height=4, font=(FONT, 10), wrap="none", relief="flat",
                            borderwidth=0, highlightthickness=1, highlightbackground=LINE,
                            highlightcolor=ACCENT, bg=C["soft"], fg=INK, insertbackground=INK,
                            padx=X(8), pady=X(6))
            words.insert("1.0", "\n".join(mywords))
            words.pack(fill="x")
            words.bind("<KeyRelease>", lambda e: on_change())
            words.bind("<FocusOut>", lambda e: on_change())
            tk.Label(body, text="Taken out wherever they come up, the whole phrase: for example "
                     "\u201cgrow some stones\u201d. Whole words only, so \u201cstones\u201d on "
                     "its own wouldn't touch \u201cmilestones\u201d.", bg=CARD, fg=MUTED,
                     font=(FONT, 9), wraplength=X(wrap - 40), justify="left").pack(
                         anchor="w", pady=(X(4), 0))

        def on(v, parts=parts):
            # religion counts as on only with at least one of its parts
            return _is_on(v) and (str(v) not in parts or any(p.get() for p in parts[str(v)]))

        def refresh(*_, got=got, switch=switch, count=count, badge=badge, on=on):
            if not switch.winfo_exists():
                return
            k = sum(on(v) for v in got)
            switch.set("on" if k == len(got) else "off" if k == 0 else "some")
            count.config(text=f"{k} of {len(got)} on" if k else "Off")
            badge.set(fill=C["tint"] if k else C["side"], fg=C["accent"] if k else C["faint"])

        def tick_all(_=None, got=got, parts=parts, on=on):
            want = not all(on(v) for v in got)
            for v in got:
                v.set(("Cut all kisses" if want else "Keep") if isinstance(v.get(), str) else want)
                if want:
                    for p in parts.get(str(v), ()):
                        p.set(True)

        def show(opening, heading=heading, body=body, tile=tile, ctl=ctl):
            if opening:
                for t, other in shows.items():
                    if t != heading:
                        other(False)
                body.pack(fill="x")
                dname.config(text=heading)
                detail.pack(fill="x", padx=(padx, X(10)), pady=(X(2), X(6)))
                opened.clear()
                opened.add(heading)
            else:
                body.pack_forget()
                if heading in opened:
                    opened.discard(heading)
                    detail.pack_forget()
            tile.recolour(edge=C["accent"] if opening else C["line"], edge_w=2.0 if opening else 1.0)
            ctl["more"].label.config(text="Hide \u2039" if opening else "Choose \u203a")

        def flip(_=None, heading=heading, show=show):
            opening = heading not in opened
            show(opening)
            on_fold()
            if opening and scroll_to:
                parent.after(50, lambda: scroll_to(dname))
        ctl["more"] = look.link(low, "Choose \u203a", flip, size=9)
        ctl["more"].pack(side="right")
        switch._command = tick_all
        for w in (badge, name):
            look.on_click(w, flip)
        for v in got + [p for ps in parts.values() for p in ps]:
            v.trace_add("write", refresh)
        refresh()
        shows[heading] = show
        heads[heading] = (switch, count, tick_all, show)

    def all_done():
        for sh in shows.values():
            sh(False)
        on_fold()
    look.link(dhead, "Done", all_done, size=9).pack(side="right")
    for t in list(opened):
        if t in shows:
            shows[t](True)
    for v in vars_.values():
        v.trace_add("write", lambda *_: on_change())
    return vars_, words


def read_boxes(vars_, words):
    """(ticks, own words) from build_boxes()' tick boxes."""
    t = {k: (next(key for key, n in KISS_LEVELS if n == v.get()) if k in LEVELS else v.get())
         for k, v in vars_.items()}
    mine = [ln.strip() for ln in words.get("1.0", "end").splitlines() if ln.strip()] if words else []
    return t, mine


class FilterPanel:
    """Every filter on the page itself, as in CleanView: "Filtering for" (the ages, one rounded
    choice) and the sections as tiles. Every change is kept at once, for the age chosen;
    CleanListen and CleanRead show the same ticks."""

    def __init__(self, parent, on_change=None, wrap=560, scroll_to=None):
        self.d = load()
        self.on_change = on_change or (lambda: None)
        self.scroll_to = scroll_to
        MUTED = look.C["muted"]             # the look in use (light or dark)
        bg = _hex(parent, parent.cget("bg"))
        X = lambda n: look.px(parent, n)          # noqa: E731
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        self.profile = tk.StringVar(value=self.d["profile"])
        look.Segmented(row, PROFILES, self.profile, command=self._profile_changed).pack(side="left")
        self.std = look.link(row, "Reset to standard", self.standard, size=9)
        self.std.pack(side="right", padx=(0, X(10)))
        tk.Label(parent, text="Each age remembers its own choices. CleanListen and CleanRead share "
                 "them.", bg=bg, fg=MUTED, font=(FONT, 9), wraplength=X(wrap),
                 justify="left").pack(anchor="w", pady=(X(8), 0))
        self.wrap = wrap
        self.body = tk.Frame(parent, bg=bg)
        self.body.pack(fill="x", pady=(X(4), 0))
        self._build()

    def _build(self):
        self._quiet = True
        for w in self.body.winfo_children():
            w.destroy()
        self.heads = {}
        self.vars, self.words = build_boxes(self.body, ticks(self.d), self.d["mywords"],
                                            self._changed, padx=0, wrap=self.wrap,
                                            opened=self._opened(), on_fold=self._folded,
                                            heads=self.heads, scroll_to=self.scroll_to)
        self._quiet = False

    def _opened(self):
        """The sections open last time (shared by both apps), changed in place."""
        self._open = set(self.d.get("open_sections") or [])
        return self._open

    def _folded(self):
        self.d["open_sections"] = sorted(self._open)
        save(self.d)

    def _changed(self):
        if self._quiet:
            return
        t, mine = read_boxes(self.vars, self.words)
        self.d["ticks"][self.d["profile"]] = t
        self.d["mywords"] = mine
        save(self.d)
        self.on_change()

    def _profile_changed(self):
        if self.d["profile"] == self.profile.get() and getattr(self, "vars", None):
            return
        self.d["profile"] = self.profile.get()
        save(self.d)
        self._build()
        self.on_change()

    def standard(self):
        std = PRESETS[self.d["profile"]]
        self._quiet = True
        for k, v in self.vars.items():
            v.set(dict(KISS_LEVELS)[std[k]] if k in LEVELS else bool(std[k]))
        self._quiet = False
        self._changed()

    def ticks(self):
        return ticks(self.d)

    def mywords(self):
        if self.words is not None and self.words.winfo_exists():
            self._changed()
        return list(self.d["mywords"])


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
        self._open = set(d.get("open_sections") or [])
        self.heads = {}
        self.vars, self.words = build_boxes(body, cur, d["mywords"], opened=self._open,
                                            heads=self.heads)
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
        self.d["ticks"][self.d["profile"]], self.d["mywords"] = read_boxes(self.vars, self.words)
        self.d["open_sections"] = sorted(self._open)
        self.grab_release()
        self.destroy()
        self.on_done()
