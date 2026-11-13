"""The new look's shared parts for CleanListen and CleanRead (the owner, 2026-11-13, via CleanView
1.18.77: "the ui also feels clunky and dated, can you make it feel classy (all of them)"; a repaint
wasn't it ("that just looks like you changed colors"), she chose "B, step by step").

- `style(root, s, ...)`: the ttk widgets in the drawn look (rounded buttons, thin scroll bars, a
  rounded progress bar, soft fields, smooth tick boxes), using cvlook.py as it is in CleanView.
- `StepPage`: a start page one step at a time: the steps listed down the left on a soft panel (each
  saying what's chosen; clicking one goes to it), the step itself on the right, and Back, "Next:
  <step>" and the main green button along the bottom."""
import base64
import os
import tkinter as tk
from tkinter import ttk

import cvlook as look

HEAD = "Segoe UI Semibold" if os.name == "nt" else "DejaVu Sans"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

# Light and dark (as CleanView 1.18.78; the owner, 2026-11-13: "ask cleann view aabout dark mode
# built. lets move that here also"; there: "yes it should be optional", "just light dark button
# option. no windows choice"). Every colour the windows use has a name here and a value for each
# look. `use_theme(name)` sets the drawn pieces' colours; an app then takes the names into its own
# module (`globals().update(CL.colours())`), so code that builds a page always reads the look in
# use. Never write a colour as a literal in a page: name it here. Light is the look as it was.
LIGHT = dict(
    BG="#F6F3EE", CARD="#FFFFFF", INK="#23211F", MUTED="#5C5852", ACCENT="#2F6F62",
    ACCENT_DK="#24574D", LINE="#E3DED6", BUTTON_EDGE="#B9AFA2", SIDE="#EFEAE2", TINT="#EAF2EF",
    SOFT="#FBFAF7", FAINT="#A39C93",
    TINT_EDGE="#CFE0DB",                                  # the edge of a green note
    YELLOW="#FFF4D6", YELLOW_INK="#7A5A00",               # "AI suggests": worth a look
    AMBER="#8A5A00", FAIL="#A3362B", READY_GREEN="#1E7E34",
    DISABLED="#A9C2BC", GREY="#ECE7E0", GREY_HOVER="#E0D9CF", TROUGH="#E6E1DA",
    PLAIN_DIM="#F4F1EC", PLAIN_EDGE="#D9D2C7", RING="#CFC6B8", SOFT_EDGE="#DCD4C7",
    WORD_BG="#F3E3DF", WORD_INK="#8A3B2E", SHADE="#FAF8F5", QUOTE="#FBFAF8",
    FINE_BG="#EEEAE4", FINE_INK="#A49E96",                # an example marked "Not a problem"
    CHIP_NONE=("#EEF1EE", "#6D7A72"), CHIP_MENTIONED=("#E6F0FA", "#2B5B8A"),
    CHIP_SOME=("#FFF1D6", "#8A5A00"), CHIP_LOT=("#FBE1DC", "#9A2F1F"),
    PIECES=dict(off="#D8D1C6", some="#8FB5AC", tick_off="#FFFFFF", tick_edge="#9C958B",
                dim_fill="#F1EEEA", dim_edge="#CFC9C1", dim_on="#A9C2BC", bar="#D3CBC0",
                bar_hover="#B7AEA2"))
DARK = dict(
    BG="#1B1C1E", CARD="#27292C", INK="#ECE9E4", MUTED="#A39E96", ACCENT="#3F9482",
    ACCENT_DK="#4FA896", LINE="#3A3D41", BUTTON_EDGE="#4C4F54", SIDE="#141517", TINT="#20332E",
    SOFT="#202225", FAINT="#7C7872",
    TINT_EDGE="#33574E",
    YELLOW="#3D3420", YELLOW_INK="#E6C777",
    AMBER="#E6B45A", FAIL="#F28D76", READY_GREEN="#5BC47A",
    DISABLED="#33504A", GREY="#303236", GREY_HOVER="#3B3E43", TROUGH="#35383C",
    PLAIN_DIM="#2B2D31", PLAIN_EDGE="#4C4F54", RING="#585B61", SOFT_EDGE="#46494E",
    WORD_BG="#4C2B27", WORD_INK="#F2AA9A", SHADE="#2B2D31", QUOTE="#202225",
    FINE_BG="#303236", FINE_INK="#7C7872",
    CHIP_NONE=("#2B2F2D", "#9AA89F"), CHIP_MENTIONED=("#1F2F40", "#8DB8E6"),
    CHIP_SOME=("#3D3420", "#E6C777"), CHIP_LOT=("#4C2B27", "#F2AA9A"),
    PIECES=dict(off="#4C4F54", some="#35675C", tick_off="#27292C", tick_edge="#7A7E85",
                dim_fill="#2B2D31", dim_edge="#4C4F54", dim_on="#33504A", bar="#4C4F54",
                bar_hover="#63676E"))
THEME = "light"
P = dict(LIGHT)                 # the look in use, by name


def use_theme(name):
    """Light or dark: sets the drawn pieces' colours and `P`. Returns "light" or "dark". Pages
    built after this (and an app's own names, taken with colours()) are in that look."""
    global THEME
    THEME = "dark" if name == "dark" else "light"
    P.clear()
    P.update(DARK if THEME == "dark" else LIGHT)
    look.use(bg=P["BG"], card=P["CARD"], ink=P["INK"], muted=P["MUTED"], accent=P["ACCENT"],
             accent_dk=P["ACCENT_DK"], line=P["LINE"], side=P["SIDE"], tint=P["TINT"],
             soft=P["SOFT"], faint=P["FAINT"], disabled=P["DISABLED"], **P["PIECES"])
    return THEME


def colours():
    """The look in use, for an app's own module names: BG, CARD, INK..., and GO for the main
    button."""
    out = {k: v for k, v in P.items() if k != "PIECES"}
    out.update(GO=P["ACCENT"], GO_DK=P["ACCENT_DK"], GO_OFF=P["DISABLED"])
    return out


def title_bar(root):
    """The window's own title bar dark with the dark look (Windows 10 and 11). Where Windows
    can't, nothing happens."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1 if THEME == "dark" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
        # the bar is only drawn again when the frame changes: say it has
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except Exception:
        pass


use_theme("light")


def short(text, n):
    text = str(text or "")
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def style(root, s, greens=("Accent.TButton", "Main.TButton", "Go.TButton"),
          whites=("Plain.TButton", "Small.TButton"), progress="Green.Horizontal.TProgressbar",
          checks=("TCheckbutton",)):
    """Round the app's ttk buttons (green ones filled, the others white with a soft edge), and
    give it thin scroll bars, a rounded progress bar, soft fields and smooth tick boxes. Call
    after the app's own s.configure(...) lines, with look.use(...) already called."""
    C = look.C
    green = (C["accent"], C["accent_dk"], P["DISABLED"], None, "#FFFFFF")
    white = (C["card"], C["tint"], P["PLAIN_DIM"], P["PLAIN_EDGE"], C["faint"])
    for name in whites:               # the card colour with a soft edge: flat, so the picture shows
        s.configure(name, background=C["card"], foreground=C["ink"], borderwidth=0)
        s.map(name, background=[("active", C["tint"])], foreground=[("disabled", C["faint"])])
    # drop-down lists and typed text in the look too
    root.option_add("*TCombobox*Listbox.background", C["card"])
    root.option_add("*TCombobox*Listbox.foreground", C["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*Text.insertBackground", C["ink"])          # the typing cursor
    look.round_buttons(root, {**{g: green for g in greens}, **{w: white for w in whites}})
    look.style_scrollbars(root, s)
    look.style_progress(root, s, progress, bg=C["card"])
    look.style_fields(s)
    s.map("TCombobox", foreground=[("readonly", C["ink"])], selectforeground=[("readonly", C["ink"])],
          selectbackground=[("readonly", C["card"])])
    first = not hasattr(root, "_look_ticks")
    root._look_ticks = look.tick_images(root, None if first else root._look_ticks)
    if first:
        t = root._look_ticks
        try:
            s.element_create("Look.indicator", "image", t["off"],
                             ("selected", "disabled", t["on_dim"]), ("disabled", t["off_dim"]),
                             ("selected", t["on"]), sticky="")
        except tk.TclError:
            pass
        for name in checks:
            s.layout(name, [("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Look.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])


def card(parent, fill=None, edge=None, radius=12, pad=(14, 10), edge_w=1.0, width=None):
    """A rounded card for a list (a found passage, a book, the words): look.Card, fitted to what's
    in it even while it's out of view. (A card only hears its size once it can be seen, so far down
    a long list it would stay at its tall starting height and the list would jump when scrolled.)"""
    c = look.Card(parent, fill=fill, edge=edge, radius=radius, pad=pad, edge_w=edge_w, width=width)

    def fit():
        if c.winfo_exists():
            c._fit()
    for ms in (1, 60, 400):
        c.after(ms, fit)
    return c


def switch_row(parent, variable, title, sub="", wrap=470, command=None, bg=None):
    """An on/off switch with a heading and a line under it (a yes/no choice). Returns the frame."""
    bg = bg or parent.cget("bg")
    X = lambda n: look.px(parent, n)          # noqa: E731
    row = tk.Frame(parent, bg=bg)
    sw = look.Switch(row, variable, command=command, bg=bg)
    sw.pack(side="left", anchor="n", pady=(X(2), 0))
    words = tk.Frame(row, bg=bg)
    words.pack(side="left", fill="x", expand=True, padx=(X(14), 0))
    head = tk.Label(words, text=title, bg=bg, fg=look.C["ink"], font=(HEAD, 10), anchor="w",
                    justify="left", wraplength=X(wrap), cursor="hand2")
    head.pack(anchor="w")
    look.on_click(head, lambda e: sw.click())
    if sub:
        tk.Label(words, text=sub, bg=bg, fg=look.C["muted"], font=(FONT, 9), wraplength=X(wrap),
                 justify="left", anchor="w").pack(anchor="w", pady=(X(2), 0))
    row.switch = sw
    return row


class StepPage:
    """The start page, one step at a time.

    steps: [(title, line under the title)]; summary(n) -> what's chosen in step n, for the list on
    the left; done(n) -> True to show a tick on step n; main: (text, command) of the green button;
    links: [(text, command, icon)] quiet links under the list of steps; scroll_area(parent) -> the
    app's own scrolling frame. Put each step's widgets in `pane(n)` (1-based), then call `go(n)`."""

    def __init__(self, app, parent, name, logo_png, steps, summary, main, links=(), done=None,
                 scroll_area=None, start=1, theme=None):
        """theme: (StringVar "light"/"dark", command) for the Light / Dark choice under the steps."""
        self.app, self.steps, self.summary, self.done = app, list(steps), summary, done
        X = self.X = lambda n: look.px(app, n)      # noqa: E731
        C = look.C
        SIDE, FAINT = C["side"], C["faint"]
        self.now = start
        side = tk.Frame(parent, bg=SIDE, width=X(232))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDE)
        brand.pack(fill="x", padx=X(22), pady=(X(26), X(20)))
        self._imgs = []
        logo = None
        if logo_png:
            try:
                logo = tk.PhotoImage(master=app, data=base64.b64encode(logo_png).decode())
                while logo.width() > X(52):
                    logo = logo.subsample(2)
            except tk.TclError:
                logo = None
        if logo is not None:
            self._imgs.append(logo)
            tk.Label(brand, image=logo, bg=SIDE).pack(side="left", padx=(0, X(10)))
        tk.Label(brand, text=name, bg=SIDE, fg=C["ink"], font=(HEAD, 15)).pack(side="left")
        self.rows = []
        for i, (title, _) in enumerate(self.steps, 1):
            card = look.Card(side, fill=SIDE, edge="", radius=12, pad=(12, 9))
            card.pack(fill="x", padx=X(14), pady=X(2))
            row = card.body
            badge = look.Badge(row, None, size=26, circle=True, text=str(i))
            badge.pack(side="left", padx=(0, X(12)))
            words = tk.Frame(row, bg=SIDE)
            words.pack(side="left", fill="x", expand=True)
            label = tk.Label(words, text=title, bg=SIDE, fg=C["muted"], font=(HEAD, 10), anchor="w")
            label.pack(anchor="w")
            said = tk.Label(words, text="", bg=SIDE, fg=FAINT, font=(FONT, 9), anchor="w")
            said.pack(anchor="w")
            card.clickable(lambda i=i: self.go(i))
            self.rows.append((card, badge, label, said))
        extras = tk.Frame(side, bg=SIDE)
        extras.pack(side="bottom", fill="x", padx=X(24), pady=(0, X(20)))
        self.links = {}
        if theme:                       # light or dark
            look.Segmented(extras, [("light", "Light"), ("dark", "Dark")], theme[0],
                           command=theme[1], size=9, tray=C["bg"]).pack(anchor="w", pady=(0, X(8)))
        for text, command, icon in links:
            ln = look.link(extras, text, command, icon=icon, size=9, fg=C["muted"], bold=False)
            ln.label.config(wraplength=X(150), justify="left")
            ln.pack(anchor="w", pady=X(3))
            self.links[text] = ln

        main_f = self.main = tk.Frame(parent, bg=C["bg"])
        main_f.pack(side="left", fill="both", expand=True, padx=(X(34), X(30)), pady=(X(22), 0))
        self.footer = tk.Frame(main_f, bg=C["bg"])
        self.footer.pack(side="bottom", fill="x")
        tk.Frame(self.footer, bg=C["line"], height=1).pack(fill="x")
        nav = self.nav = tk.Frame(self.footer, bg=C["bg"])
        nav.pack(fill="x", pady=(X(14), X(18)))
        self.main_btn = look.Pill(nav, main[0], main[1], after="next", size=12, pad=(24, 11))
        self.main_btn.pack(side="right")
        self.next_btn = look.Pill(nav, "Next", lambda: self.go(self.now + 1), kind="secondary",
                                  after="next", size=11, pad=(20, 10))
        self.back_btn = look.Pill(nav, "Back", lambda: self.go(self.now - 1), kind="quiet",
                                  icon="back", size=11, pad=(16, 10))
        self.top = tk.Frame(main_f, bg=C["bg"])          # notes above the step (an update, a review kept)
        self.top.pack(fill="x")
        self.tag = tk.Label(main_f, text="", bg=C["bg"], fg=C["accent"], font=(HEAD, 8), anchor="w")
        self.tag.pack(anchor="w")
        self.title = tk.Label(main_f, text="", bg=C["bg"], fg=C["ink"], font=(HEAD, 21), anchor="w")
        self.title.pack(anchor="w", pady=(X(2), 0))
        self.sub = tk.Label(main_f, text="", bg=C["bg"], fg=C["muted"], font=(FONT, 10), anchor="w",
                            justify="left", wraplength=X(560))
        self.sub.pack(anchor="w", pady=(X(4), X(14)))
        if scroll_area is not None:
            self.inner = scroll_area(main_f)
        else:
            self.inner = tk.Frame(main_f, bg=C["bg"])
            self.inner.pack(fill="both", expand=True)
        self.panes = []
        for n in range(1, len(self.steps) + 1):
            f = tk.Frame(self.inner, bg=C["bg"])
            f._step_no = n
            self.panes.append(f)

    def pane(self, n):
        return self.panes[n - 1]

    def card(self, n, fill=None, edge=None, pad=(18, 14), top=0):
        """A rounded card in step n; returns the frame to put things in."""
        c = look.Card(self.pane(n), fill=fill, edge=edge, radius=14, pad=pad)
        c.pack(fill="x", padx=(0, self.X(4)), pady=(self.X(top), 0))
        return c.body

    def go(self, n):
        """Show step n, and only that step."""
        n = max(1, min(len(self.steps), n))
        self.now = n
        if not self.panes or not self.panes[0].winfo_exists():
            return
        for i, pane in enumerate(self.panes, 1):
            if i == n:
                pane.pack(fill="x")
            else:
                pane.pack_forget()
        title, sub = self.steps[n - 1]
        self.tag.config(text=f"STEP {n} OF {len(self.steps)}")
        self.title.config(text=title)
        self.sub.config(text=sub)
        canvas = getattr(self.inner, "_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(0)
        if n > 1:
            self.back_btn.pack(side="left")
        else:
            self.back_btn.pack_forget()
        if n < len(self.steps):
            self.next_btn.config(text=f"Next: {self.steps[n][0]}")
            self.next_btn.pack(side="right", padx=(0, self.X(10)))
        else:
            self.next_btn.pack_forget()
        self.refresh()

    def refresh(self):
        """The list on the left: which step is showing, what's chosen in each, a tick when done."""
        if not self.rows or not self.rows[0][0].winfo_exists():
            return
        C = look.C
        for i, (card, badge, label, said) in enumerate(self.rows, 1):
            current = i == self.now
            card.recolour(fill=C["card"] if current else C["side"], edge=C["line"] if current else "")
            if self.done and self.done(i):
                badge.set(icon="check", text=None, fill=C["accent"], fg="#FFFFFF", edge=None)
            else:
                badge.set(icon=None, text=str(i), fill=card.fill,
                          fg=C["accent"] if current else C["muted"],
                          edge=C["accent"] if current else P["RING"])
            label.config(fg=C["ink"] if current else C["muted"])
            try:
                said.config(text=short(self.summary(i), 28))
            except Exception:
                said.config(text="")
