"""The drawn look of the Clean apps (CleanView 1.18.77; the owner, 2026-11-12: "the ui also
feels clunky and dated, can you make it feel classy (all of them)", then "B, step by step").

Tk's canvas can't smooth edges, so rounded shapes are drawn here with numpy as PNG images
(Tk 8.6 reads PNG itself; no Pillow needed) and the words go on top as ordinary Tk text.
Pieces: rounded cards (`Card`), pill buttons (`Pill`), on/off switches (`Switch`, also
half-on for "some"), a segmented choice (`Segmented`), option cards (`OptionCard`), icon
badges (`Badge`, Windows' own icon font) and tick-box images (`tick_images`).

Sizes are given as pixels at normal size on a 96 dpi screen and grow with the PC's scaling
and the app's text size (`px`). Colours come from `use(...)`, once, before anything is
drawn. Standard library, tkinter and numpy only, so it works in every app's venv."""
import base64
import struct
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import zlib

import numpy as np

ICON_FONT = "Segoe MDL2 Assets"        # on Windows 10 and 11
ICONS = {"folder": "", "video": "", "check": "", "next": "",
         "back": "", "refresh": "", "send": "", "text": "",
         "mute": "", "eye": "", "heart": "", "warning": "",
         "health": "", "smile": "", "cup": "", "star": "",
         "music": "", "pc": "", "chat": "", "cloud": "",
         "spark": "", "down": "", "close": "", "info": "", "sun": "", "moon": ""}

C = dict(bg="#F6F3EE", card="#FFFFFF", ink="#22201E", muted="#77716A", faint="#A39C93",
         line="#E6E0D7", accent="#2F6F62", accent_dk="#245A4F", tint="#EAF2EF",
         side="#EFEAE2", soft="#FBFAF7", off="#D8D1C6", some="#8FB5AC")


# the smaller parts' colours, so a dark look can change them too
C.update(tick_off="#FFFFFF", tick_edge="#9C958B", dim_fill="#F1EEEA", dim_edge="#CFC9C1",
         dim_on="#A9C2BC", disabled="#A9C2BC", bar="#D3CBC0", bar_hover="#B7AEA2")


def use(**colours):
    C.update({k: v for k, v in colours.items() if v})


def px(widget, n):
    """n pixels at normal size on a 96 dpi screen, in this widget's pixels (follows the
    PC's scaling and the app's text size, which both go through Tk's scaling)."""
    return max(1, round(n * widget.winfo_fpixels("1p") * 0.75))


# ---------- drawing ----------
def _rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], float)


def png(rgba):
    """PNG bytes of an h x w x 4 uint8 array."""
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def photo(master, rgba, into=None):
    """A Tk image of the array (or drawn into an existing one, which keeps its name)."""
    data = base64.b64encode(png(rgba))
    if into is not None:
        into.configure(width=0, height=0)
        into.configure(data=data, format="png")
        return into
    return tk.PhotoImage(master=master, data=data, format="png")


def _cover(w, h, r, inset=0.0, x0=0.0, y0=0.0, bw=None, bh=None):
    """How much of each pixel a rounded rectangle covers (0-1, smooth edges)."""
    bw = w if bw is None else bw
    bh = h if bh is None else bh
    y, x = np.mgrid[0:h, 0:w].astype(float) + 0.5
    cx, cy = x0 + bw / 2, y0 + bh / 2
    rr = max(0.0, min(r, bw / 2, bh / 2) - inset)
    qx = np.abs(x - cx) - (bw / 2 - inset - rr)
    qy = np.abs(y - cy) - (bh / 2 - inset - rr)
    d = (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) +
         np.minimum(np.maximum(qx, qy), 0) - rr)
    return np.clip(0.5 - d, 0, 1)


def _lines(w, h, pts, width):
    """How much of each pixel a line through pts (pixel positions) covers."""
    y, x = np.mgrid[0:h, 0:w].astype(float) + 0.5
    d = np.full((h, w), 1e9)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        vx, vy = bx - ax, by - ay
        t = np.clip(((x - ax) * vx + (y - ay) * vy) / max(1e-9, vx * vx + vy * vy), 0, 1)
        d = np.minimum(d, np.hypot(x - ax - t * vx, y - ay - t * vy))
    return np.clip(width / 2 + 0.5 - d, 0, 1)


def _paint(base, cover, colour):
    a = cover[..., None]
    return base * (1 - a) + _rgb(colour) * a


def shape(w, h, r, fill, bg, edge=None, edge_w=1.0):
    """A rounded rectangle on bg (RGBA, solid): fill inside, an edge of edge_w pixels."""
    img = np.empty((h, w, 3))
    img[...] = _rgb(bg)
    if edge:
        img = _paint(img, _cover(w, h, r), edge)
        img = _paint(img, _cover(w, h, r, inset=edge_w), fill)
    else:
        img = _paint(img, _cover(w, h, r), fill)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.clip(np.round(img), 0, 255)
    out[..., 3] = 255
    return out


def tick_image(n, gap, state, ink=None):
    """A tick box n pixels square (with a see-through gap after it): "off", "on", "off_dim",
    "on_dim" or "some" (a dash)."""
    w = n + gap
    fill, edge, mark = {"off": (C["tick_off"], C["tick_edge"], None),
                        "on": (C["accent"], C["accent"], "#FFFFFF"),
                        "off_dim": (C["dim_fill"], C["dim_edge"], None),
                        "on_dim": (C["dim_on"], C["dim_on"], "#FFFFFF"),
                        "some": (C["accent"], C["accent"], "#FFFFFF")}[state]
    r = n * 0.24
    rgb = np.zeros((n, w, 3))
    alpha = _cover(w, n, r, bw=n)
    rgb = _paint(rgb, alpha, edge)
    rgb = _paint(rgb, _cover(w, n, r, inset=max(1.0, n / 13), bw=n), fill)
    if mark and state == "some":
        d = max(2.0, n / 7)
        rgb = _paint(rgb, _lines(w, n, [(n * 0.28, n / 2), (n * 0.72, n / 2)], d), mark)
    elif mark:
        rgb = _paint(rgb, _lines(w, n, [(n * 0.25, n * 0.53), (n * 0.43, n * 0.71),
                                        (n * 0.76, n * 0.32)], max(1.8, n / 7.5)), mark)
    out = np.zeros((n, w, 4), np.uint8)
    out[..., :3] = np.clip(np.round(rgb / np.maximum(alpha, 1e-6)[..., None]), 0, 255)
    out[..., 3] = np.round(alpha * 255)
    return out


def tick_images(widget, ticks=None):
    """The five tick-box images at this text size (drawn into `ticks` if given)."""
    n = max(14, px(widget, 17))
    gap = max(6, n // 2)
    ticks = ticks if ticks is not None else {}
    for k in ("off", "on", "off_dim", "on_dim", "some"):
        ticks[k] = photo(widget, tick_image(n, gap, k), into=ticks.get(k))
    return ticks


def text_width(font, text):
    return tkfont.Font(font=font).measure(text)


# ---------- pieces ----------
def on_click(widget, fn):
    """fn(event) when the mouse is pressed on the widget and let go on it. Letting go alone
    isn't a click: the second click of a double-click in the file box lands on whatever is
    under it in the window, and pressing a button then sliding off it means "no"."""
    def press(e):
        widget._pressed = True

    def release(e):
        was, widget._pressed = getattr(widget, "_pressed", False), False
        if was and 0 <= e.x < widget.winfo_width() and 0 <= e.y < widget.winfo_height():
            fn(e)
    widget.bind("<ButtonPress-1>", press, add="+")
    widget.bind("<ButtonRelease-1>", release, add="+")


class Pill(tk.Canvas):
    """A rounded button. kind: "primary" (green), "secondary" (white with an edge) or
    "quiet" (no fill until the mouse is over it). Works like a ttk.Button for what the
    apps use: config(text=, state=, command=), cget("text"/"state"), invoke()."""

    def __init__(self, parent, text="", command=None, kind="primary", icon=None, after=None,
                 size=11, bg=None, pad=(20, 9), bold=True):
        self._bg = bg or parent.cget("bg")
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._command, self._kind = text, command, kind
        self._icon, self._after, self._size, self._pad = icon, after, size, pad
        self._bold, self._state, self._hover, self._img = bold, "normal", False, None
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        on_click(self, lambda e: self.invoke())
        self._draw()

    def _colours(self):
        k, hov, off = self._kind, self._hover, self._state == "disabled"
        if k == "primary":
            fill = C["disabled"] if off else C["accent_dk"] if hov else C["accent"]
            return fill, None, "#FFFFFF"
        if k == "secondary":
            return (C["tint"] if hov and not off else C["card"]), C["line"], \
                (C["faint"] if off else C["ink"])
        return (C["side"] if hov and not off else self._bg), None, \
            (C["faint"] if off else C["muted"] if not hov else C["ink"])

    def _draw(self):
        self.delete("all")
        font = ("Segoe UI Semibold" if self._bold else "Segoe UI", self._size)
        ifont = (ICON_FONT, max(8, self._size - 2))
        tw = text_width(font, self._text)
        iw = text_width(ifont, ICONS.get(self._icon, "")) + px(self, 8) if self._icon else 0
        aw = text_width(ifont, ICONS.get(self._after, "")) + px(self, 8) if self._after else 0
        line = tkfont.Font(font=font).metrics("linespace")
        padx, pady = px(self, self._pad[0]), px(self, self._pad[1])
        w, h = tw + iw + aw + 2 * padx, line + 2 * pady
        fill, edge, fg = self._colours()
        self.configure(width=w, height=h)
        self._img = photo(self, shape(w, h, h / 2, fill, self._bg, edge))
        self.create_image(0, 0, image=self._img, anchor="nw")
        x = padx
        if self._icon:
            self.create_text(x, h / 2, text=ICONS[self._icon], font=ifont, fill=fg, anchor="w")
            x += iw
        self.create_text(x, h / 2, text=self._text, font=font, fill=fg, anchor="w")
        if self._after:
            self.create_text(x + tw + px(self, 8), h / 2 + 1, text=ICONS[self._after],
                             font=ifont, fill=fg, anchor="w")

    def _set_hover(self, on):
        if self._hover != on:
            self._hover = on
            self._draw()

    def invoke(self):
        if self._state != "disabled" and self._command:
            return self._command()

    def configure(self, cnf=None, **kw):
        cnf = dict(cnf or {}, **kw)
        mine = False
        for k in ("text", "state", "command", "kind"):
            if k in cnf:
                setattr(self, "_" + k, cnf.pop(k))
                mine = True
        if self._state == "disabled":
            super().configure(cursor="")
        else:
            super().configure(cursor="hand2")
        out = super().configure(cnf) if cnf else None
        if mine:
            self._draw()
        return out

    config = configure

    def cget(self, key):
        if key in ("text", "state", "command", "kind"):
            return getattr(self, "_" + key)
        return super().cget(key)


class Switch(tk.Canvas):
    """An on/off switch, drawn half-on (pale) for "some". With a variable it follows a
    BooleanVar both ways; otherwise set(state) draws it and clicking calls command."""

    def __init__(self, parent, variable=None, command=None, bg=None):
        self._bg = bg or parent.cget("bg")
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, cursor="hand2")
        self.var, self._command, self.state, self._img = variable, command, "off", None
        on_click(self, lambda e: self.click())
        if variable is not None:
            variable.trace_add("write", lambda *_: self._follow())
            self._follow()
        else:
            self._draw()

    def _follow(self):
        if self.winfo_exists():
            self.set("on" if self.var.get() else "off")

    def set(self, state):
        self.state = state
        self._draw()

    def click(self):
        if self.var is not None:
            self.var.set(not self.var.get())
        if self._command:
            self._command()

    def _draw(self):
        self.delete("all")
        w, h = px(self, 40), px(self, 22)
        self.configure(width=w, height=h)
        fill = {"on": C["accent"], "some": C["some"]}.get(self.state, C["off"])
        img = shape(w, h, h / 2, fill, self._bg)
        k = h - 2 * px(self, 3)
        x0 = w - px(self, 3) - k if self.state != "off" else px(self, 3)
        rgb = img[..., :3].astype(float)
        rgb = _paint(rgb, _cover(w, h, k / 2, x0=x0, y0=px(self, 3), bw=k, bh=k), "#FFFFFF")
        img[..., :3] = np.clip(np.round(rgb), 0, 255)
        self._img = photo(self, img)
        self.create_image(0, 0, image=self._img, anchor="nw")


class Segmented(tk.Canvas):
    """One of a few choices, side by side in a rounded tray (the chosen one raised in
    white). Follows a StringVar both ways; command is called after a click."""

    def __init__(self, parent, options, variable, command=None, bg=None, size=10, tray=None):
        self._bg = bg or parent.cget("bg")
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, cursor="hand2")
        self.options, self.var, self._command, self._size = options, variable, command, size
        self._tray = tray               # the tray's colour (else the side panel's)
        self._spots, self._img = [], None
        on_click(self, self._click)
        variable.trace_add("write", lambda *_: self.winfo_exists() and self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        font = ("Segoe UI Semibold", self._size)
        line = tkfont.Font(font=font).metrics("linespace")
        pad, gap, inner = px(self, 4), px(self, 2), px(self, 16)
        widths = [text_width(font, label) + 2 * inner for _, label in self.options]
        h = line + 2 * px(self, 7) + 2 * pad
        w = sum(widths) + gap * (len(widths) - 1) + 2 * pad
        self.configure(width=w, height=h)
        rgb = shape(w, h, h / 2, self._tray or C["side"], self._bg)[..., :3].astype(float)
        x, self._spots = pad, []
        for (value, label), bw in zip(self.options, widths):
            if value == self.var.get():
                rgb = _paint(rgb, _cover(w, h, (h - 2 * pad) / 2, x0=x, y0=pad, bw=bw,
                                         bh=h - 2 * pad), C["line"])
                rgb = _paint(rgb, _cover(w, h, (h - 2 * pad) / 2, inset=1, x0=x, y0=pad,
                                         bw=bw, bh=h - 2 * pad), C["card"])
            self._spots.append((x, x + bw, value, label))
            x += bw + gap
        img = np.empty((h, w, 4), np.uint8)
        img[..., :3] = np.clip(np.round(rgb), 0, 255)
        img[..., 3] = 255
        self._img = photo(self, img)
        self.create_image(0, 0, image=self._img, anchor="nw")
        for x0, x1, value, label in self._spots:
            on = value == self.var.get()
            self.create_text((x0 + x1) / 2, h / 2, text=label, font=font,
                             fill=C["ink"] if on else C["muted"])

    def _click(self, e):
        for x0, x1, value, _ in self._spots:
            if x0 <= e.x <= x1:
                if self.var.get() != value:
                    self.var.set(value)
                if self._command:
                    self._command()
                return


class Card(tk.Canvas):
    """A rounded card holding a frame (`.body`) that grows with what's put in it."""

    def __init__(self, parent, fill=None, edge=None, radius=14, pad=(18, 16), bg=None,
                 edge_w=1.0, width=None):
        self._bg = bg or parent.cget("bg")
        # Tall to start with: the canvas only sizes what it holds once that can be seen, and
        # that sizing is what tells the card how tall to be (`_fit`).
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0,
                         height=px(parent, 220))
        self.fill = fill or C["card"]
        self.edge = C["line"] if edge is None else edge
        self.edge_w, self.radius, self._img, self._size = edge_w, radius, None, None
        self.padx, self.pady = px(self, pad[0]), px(self, pad[1])
        self.body = tk.Frame(self, bg=self.fill)
        self._win = self.create_window(self.padx, self.pady, window=self.body, anchor="nw")
        if width:                       # side by side: a set width (else it fills its row)
            self.configure(width=px(self, width))
        self.body.bind("<Configure>", self._fit)
        self.bind("<Configure>", self._redraw)

    def _fit(self, _=None):
        want = self.body.winfo_reqheight() + 2 * self.pady
        if int(self.cget("height")) != want:
            self.configure(height=want)

    def _redraw(self, e=None):
        """Only the four corners are pictures; the straight parts are plain rectangles, so a
        card thousands of pixels tall (a long list of lines) costs no more than a small one."""
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self.itemconfigure(self._win, width=max(1, w - 2 * self.padx))
        if self._size == (w, h, self.fill, self.edge, self.edge_w, self._bg):
            return
        self._size = (w, h, self.fill, self.edge, self.edge_w, self._bg)
        r = max(1, min(px(self, self.radius), w // 2 - 1, h // 2 - 1))
        n = 2 * r + 2
        full = shape(n, n, r, self.fill, self._bg, self.edge or None, self.edge_w)
        k = r + 1
        self._img = [photo(self, full[:k, :k]), photo(self, full[:k, n - k:]),
                     photo(self, full[n - k:, :k]), photo(self, full[n - k:, n - k:])]
        self.delete("bgimg")
        ew = int(round(self.edge_w)) if self.edge else 0
        rect = lambda x0, y0, x1, y1, c: self.create_rectangle(
            x0, y0, x1, y1, fill=c, width=0, tags="bgimg")
        if ew:
            rect(k, 0, w - k, h, self.edge)
            rect(0, k, w, h - k, self.edge)
        rect(k, ew, w - k, h - ew, self.fill)
        rect(ew, k, w - ew, h - k, self.fill)
        for img, x, y, a in ((self._img[0], 0, 0, "nw"), (self._img[1], w, 0, "ne"),
                             (self._img[2], 0, h, "sw"), (self._img[3], w, h, "se")):
            self.create_image(x, y, image=img, anchor=a, tags="bgimg")
        self.tag_lower("bgimg")

    def recolour(self, fill=None, edge=None, edge_w=None):
        """New colours (the frame inside and every plain widget on it follow)."""
        old = self.fill
        self.fill = fill or self.fill
        self.edge = self.edge if edge is None else edge
        self.edge_w = edge_w or self.edge_w
        if self.fill != old:
            def walk(w):
                try:
                    if w.cget("bg") == old:
                        w.configure(bg=self.fill)
                except tk.TclError:
                    pass
                for c in w.winfo_children():
                    walk(c)
            walk(self.body)
            for w in self._all(self.body):
                if isinstance(w, (Pill, Switch, Segmented, Badge)):
                    w._bg = self.fill
                    w.configure(bg=self.fill)
                    w._draw()
        self._redraw()

    @staticmethod
    def _all(w):
        out = [w]
        for c in w.winfo_children():
            out += Card._all(c)
        return out

    def clickable(self, fn):
        """Clicking anywhere on the card (but not on a button or switch in it) calls fn."""
        for w in [self] + self._all(self.body):
            if not isinstance(w, (Pill, Switch, Segmented)) and not getattr(w, "_own_click",
                                                                             False):
                on_click(w, lambda e: fn())
                try:
                    w.configure(cursor="hand2")
                except tk.TclError:
                    pass


class Badge(tk.Canvas):
    """An icon from Windows' icon font on a small rounded square (or circle)."""

    def __init__(self, parent, icon, size=32, fill=None, fg=None, bg=None, circle=False,
                 icon_size=None, text=None, edge=None):
        self._bg = bg or parent.cget("bg")
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0)
        self.icon, self.size, self.fill, self.fg = icon, size, fill, fg
        self.circle, self.icon_size, self.text, self.edge = circle, icon_size, text, edge
        self._img = None
        self._draw()

    def set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def _draw(self):
        self.delete("all")
        n = px(self, self.size)
        self.configure(width=n, height=n)
        self._img = photo(self, shape(n, n, n / 2 if self.circle else n * 0.3,
                                      self.fill or C["tint"], self._bg, self.edge, 1.5))
        self.create_image(0, 0, image=self._img, anchor="nw")
        if self.text is not None:
            self.create_text(n / 2, n / 2, text=self.text, fill=self.fg or C["accent"],
                             font=("Segoe UI Semibold", max(7, round(self.size / 3.2))))
        else:
            self.create_text(n / 2, n / 2 + 1, text=ICONS.get(self.icon, self.icon),
                             fill=self.fg or C["accent"],
                             font=(ICON_FONT, self.icon_size or max(8, round(self.size / 2.7))))


class OptionCard(Card):
    """One choice of several, as a card: a title, a line under it, outlined in green with a
    tick when chosen. Follows a StringVar both ways."""

    def __init__(self, parent, value, variable, title, sub="", bg=None, icon=None):
        super().__init__(parent, radius=12, pad=(14, 11), bg=bg)
        self.value, self.var = value, variable
        top = tk.Frame(self.body, bg=self.fill)
        top.pack(fill="x")
        if icon:
            Badge(top, icon, size=28).pack(side="left", padx=(0, px(self, 10)))
        words = tk.Frame(top, bg=self.fill)
        words.pack(side="left", fill="x", expand=True)
        self.title = tk.Label(words, text=title, bg=self.fill, fg=C["ink"], anchor="w",
                              font=("Segoe UI Semibold", 11))
        self.title.pack(anchor="w")
        self.sub = tk.Label(words, text=sub, bg=self.fill, fg=C["muted"], anchor="w",
                            font=("Segoe UI", 9), justify="left")
        self.sub.pack(anchor="w")
        self.mark = tk.Label(top, text="", bg=self.fill, fg=C["accent"],
                             font=(ICON_FONT, 11))
        self.mark.pack(side="right", anchor="n")
        self.clickable(lambda: self.var.set(self.value))
        variable.trace_add("write", lambda *_: self.winfo_exists() and self.show())
        self.show()

    def show(self):
        on = self.var.get() == self.value
        self.recolour(fill=C["tint"] if on else C["card"], edge=C["accent"] if on else C["line"],
                      edge_w=2.0 if on else 1.0)
        self.mark.config(text=ICONS["check"] if on else "")


def link(parent, text, command, icon=None, size=10, fg=None, bold=True, bg=None):
    """Words to click (green, no underline until the mouse is over them)."""
    bg = bg or parent.cget("bg")
    f = tk.Frame(parent, bg=bg, cursor="hand2")
    font = ("Segoe UI Semibold" if bold else "Segoe UI", size)
    if icon:
        tk.Label(f, text=ICONS[icon], bg=bg, fg=fg or C["accent"],
                 font=(ICON_FONT, max(8, size - 1))).pack(side="left", padx=(0, 6))
    lbl = tk.Label(f, text=text, bg=bg, fg=fg or C["accent"], font=font, cursor="hand2")
    lbl.pack(side="left")
    for w in [f] + list(f.winfo_children()):
        on_click(w, lambda e: command())
        w.bind("<Enter>", lambda e: lbl.config(font=font + ("underline",)))
        w.bind("<Leave>", lambda e: lbl.config(font=font))
    f.label = lbl
    return f


def chip(parent, text, colour, size=8, bg=None):
    """A small rounded label on a colour (a scene's kind: "Kiss", "Violence")."""
    bg = bg or parent.cget("bg")
    font = ("Segoe UI Semibold", size)
    c = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
    w = text_width(font, text) + 2 * px(c, 9)
    h = tkfont.Font(font=font).metrics("linespace") + 2 * px(c, 2)
    c.configure(width=w, height=h)
    c._img = photo(c, shape(w, h, h / 2, colour, bg))
    c.create_image(0, 0, image=c._img, anchor="nw")
    c.create_text(w / 2, h / 2, text=text, font=font, fill="#FFFFFF")
    return c


# ---------- the apps' ttk widgets in the same look ----------
# Tk stretches a ttk picture by repeating its middle, one copy at a time. With a middle one
# pixel wide a 150-pixel button took 150 copies for each of its rows, and the review page's 18
# buttons took 2.5 seconds to draw (the owner, 2026-11-13: asking Claude a question froze the
# window, "not responding", while the page was drawn again). The pictures are this much wider
# now, so the middle is repeated a few times; `_slim` keeps the piece's smallest size as it was.
STRETCH = 64


def _corner_img(r, fill, bg, edge=None, edge_w=1.0, w=None, h=None):
    """A rounded rectangle, solid, for a ttk image element whose border is r+1 (the middle
    stretches, the corners stay round): 2r+3 high and STRETCH wider than that (or w x h)."""
    w = w or 2 * r + 3 + STRETCH
    h = h or 2 * r + 3
    return shape(w, h, r, fill, bg, edge, edge_w)


def _slim(r):
    """The smallest size of a piece drawn with _corner_img(r, ...): as small as its corners
    allow, not the picture's own width."""
    return {"width": 2 * r + 3, "height": 2 * r + 3}


BUTTON_LOOKS = {}      # ttk button style -> (fill, hover, disabled fill, edge, disabled text)


def round_buttons(root, looks):
    """Every ttk.Button whose style is in looks (e.g. {"Accent.TButton": ("#2F6F62", ...)})
    is drawn as a rounded button. Its corners are painted the colour of what it sits on, so
    when one is shown it's given a variant of its style made for that colour (the variants
    keep the style's own font, padding and text colour)."""
    BUTTON_LOOKS.update(looks)
    root._round_made = getattr(root, "_round_made", {})
    if not getattr(root, "_round_bound", False):        # once, however often styles are set
        root._round_bound = True
        root.bind_class("TButton", "<Map>", lambda e: _round_one(root, e.widget), add="+")


def _plain_bg(w):
    """The colour behind widget w (the nearest plain Tk widget's background)."""
    m = w.master
    while m is not None:
        try:
            return m.cget("bg")
        except tk.TclError:
            m = m.master
    return C["bg"]


def _round_one(root, w):
    try:
        style = w.cget("style") or "TButton"
    except tk.TclError:
        return
    base = style.split(".", 1)[1] if style.startswith("on_") else style
    if base not in BUTTON_LOOKS:
        return
    bg = _plain_bg(w)
    try:
        bg = "#%02X%02X%02X" % tuple(c // 257 for c in w.winfo_rgb(bg))
    except tk.TclError:
        bg = C["bg"]
    s = ttk.Style(root)
    scale = round(w.winfo_fpixels("1p") * 100)
    name = f"on_{bg[1:]}_{scale}.{base}"
    if name not in root._round_made:
        fill, hover, dim, edge, _ = BUTTON_LOOKS[base]
        font = tkfont.Font(root=root, font=s.lookup(base, "font") or ("Segoe UI", 10))
        pad = s.lookup(base, "padding") or (8, 4)      # a tuple, or "8 4" from Tcl
        pad = [int(float(str(x))) for x in (pad.split() if isinstance(pad, str) else pad)]
        pady = pad[1] if len(pad) > 1 else pad[0]
        h = font.metrics("linespace") + 2 * pady
        r = max(4, int(h * 0.5) - 1)
        imgs = [photo(root, _corner_img(r, c, bg, edge if c != dim else None))
                for c in (fill, hover, dim)]
        el = name.replace(".", "_") + "_bg"
        s.element_create(el, "image", imgs[0], ("disabled", imgs[2]), ("pressed", imgs[1]),
                         ("active", imgs[1]), border=r + 1, padding=0, sticky="nsew",
                         **_slim(r))
        s.layout(name, [(el, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        root._round_made[name] = imgs
    if style != name:
        w.configure(style=name)


def _same_images(root, name, arrays, extra):
    """The images kept under root.<name>, drawn again from arrays (a new look redraws them
    in place: a ttk element can't be made twice). Returns (images, extra, first time?)."""
    old = getattr(root, name, None)
    if old:
        for img, arr in zip(old[0], arrays):
            photo(root, arr, into=img)
        return old[0], old[1], False
    imgs = [photo(root, arr) for arr in arrays]
    setattr(root, name, (imgs, extra))
    return imgs, extra, True


def style_scrollbars(root, s):
    """Thin scroll bars with a rounded grip and no arrows."""
    n = (getattr(root, "_round_bars", None) or (None, px(root, 10)))[1]
    imgs, n, first = _same_images(root, "_round_bars", [
        _corner_img(n // 2 - 1, c, C["bg"], w=n, h=3 * n) for c in (C["bar"], C["bar_hover"])], n)
    if first:
        s.element_create("Round.thumb", "image", imgs[0], ("active", imgs[1]),
                         ("pressed", imgs[1]), border=n // 2, padding=0, sticky="nsew")
        s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "sticky": "ns", "children": [("Round.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", troughcolor=C["bg"], background=C["bg"],
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"], width=n,
                arrowsize=n, gripcount=0)


def style_tabs(root, s):
    """Notebook tabs as rounded pills: the chosen one on the card colour with an edge."""
    font = tkfont.Font(root=root, font=("Segoe UI Semibold", 10))
    r = (getattr(root, "_round_tabs", None) or
         (None, int((font.metrics("linespace") + 2 * px(root, 8)) / 2) - 1))[1]
    imgs, r, first = _same_images(root, "_round_tabs", [_corner_img(r, *c) for c in (
        (C["bg"], C["bg"]), (C["card"], C["bg"], C["line"]), (C["side"], C["bg"]))], r)
    if first:
        s.element_create("Round.tab", "image", imgs[0], ("selected", imgs[1]),
                         ("active", imgs[2]), border=r + 1, padding=0, sticky="nsew",
                         **_slim(r))
        s.layout("TNotebook.Tab", [("Round.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 0, 0, 8),
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
    s.configure("TNotebook.Tab", padding=(px(root, 18), px(root, 8)),
                font=("Segoe UI Semibold", 10), foreground=C["muted"], background=C["bg"])
    s.map("TNotebook.Tab", foreground=[("selected", C["ink"])],
          expand=[("selected", (0, 0, 0, 0))])


def style_progress(root, s, name, bg=None):
    """A rounded progress bar in the accent colour on a soft tray (bg: what it sits on)."""
    n = (getattr(root, "_round_progress", None) or (None, px(root, 12)))[1]
    r = n // 2 - 1
    imgs, n, first = _same_images(root, "_round_progress", [
        _corner_img(r, C["side"], bg or C["bg"], w=3 * n, h=n),
        _corner_img(r, C["accent"], C["side"], w=3 * n, h=n)], n)
    if first:
        s.element_create("Round.trough", "image", imgs[0], border=r + 1, padding=0,
                         sticky="nsew")
        s.element_create("Round.pbar", "image", imgs[1], border=r + 1, padding=0, sticky="nsew")
        s.layout(name, [("Round.trough", {"sticky": "nswe", "children": [
            ("Round.pbar", {"side": "left", "sticky": "ns"})]})])
    s.configure(name, thickness=n)


def style_dropdown(root, s, name="Round.TCombobox", bg=None):
    """A drop-down list's box with rounded corners, for a ttk.Combobox given style=name: the
    card colour with a soft edge (green while it's the one being used), a quiet arrow. bg:
    the colour it sits on (the card colour unless told)."""
    r = (getattr(root, "_round_drop", None) or (None, max(4, px(root, 9))))[1]
    on = bg or C["card"]
    imgs, r, first = _same_images(root, "_round_drop", [
        _corner_img(r, C["card"], on, edge) for edge in (C["line"], C["accent"])], r)
    if first:
        # the arrow and the words sit inside the edge (the arrow's own box would paint over it)
        s.element_create("Round.dropfield", "image", imgs[0], ("focus", imgs[1]),
                         border=r + 1, padding=(px(root, 6), 2, px(root, 4), 2), sticky="nsew",
                         **_slim(r))
        s.layout(name, [("Round.dropfield", {"sticky": "nswe", "children": [
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])
    s.configure(name, padding=(px(root, 6), px(root, 5)), arrowsize=px(root, 12),
                arrowcolor=C["muted"], foreground=C["ink"], background=C["card"],
                fieldbackground=C["card"], bordercolor=C["card"], lightcolor=C["card"],
                darkcolor=C["card"], selectbackground=C["card"], selectforeground=C["ink"],
                insertcolor=C["ink"])
    s.map(name, background=[("readonly", C["card"]), ("active", C["card"])],
          fieldbackground=[("readonly", C["card"])], foreground=[("readonly", C["ink"])],
          arrowcolor=[("active", C["ink"])], bordercolor=[("focus", C["card"])],
          lightcolor=[("focus", C["card"])], darkcolor=[("focus", C["card"])],
          selectbackground=[("readonly", C["card"])], selectforeground=[("readonly", C["ink"])])


def style_fields(s):
    """Text boxes and drop-down lists: white, a soft edge, green when typing in them."""
    for st in ("TEntry", "TCombobox"):
        s.configure(st, fieldbackground=C["card"], background=C["card"], bordercolor=C["line"],
                    lightcolor=C["card"], darkcolor=C["card"], arrowcolor=C["muted"],
                    foreground=C["ink"], insertcolor=C["ink"], padding=(6, 4))
        s.map(st, bordercolor=[("focus", C["accent"])], lightcolor=[("focus", C["card"])],
              fieldbackground=[("readonly", C["card"])],
              background=[("readonly", C["card"]), ("active", C["card"])])
