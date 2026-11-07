"""The program's logo in the empty part of a page (Jason, 2026-11-07: "I was just looking at a lot
of dead space ... the logo of the program in the middle"), as in CleanView 1.18.23. The picture
is taken out of the program's .ico (its pictures are PNGs, which tk shows without PIL)."""
import base64
import struct
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent


def logo_png(ico, px=128):
    """(PNG bytes, width) of the .ico's picture that is the smallest one at least px wide (else
    the biggest), or (None, 0) if it can't be read."""
    try:
        d = (HERE / ico).read_bytes()
        found = []
        for i in range(struct.unpack("<H", d[4:6])[0]):
            w, _, _, _, _, _, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
            if d[off:off + 4] == b"\x89PNG":
                found.append((w or 256, d[off:off + size]))
        if not found:
            return None, 0
        big = [f for f in found if f[0] >= px]
        w, png = min(big) if big else max(found)
        return png, w
    except (OSError, struct.error, ValueError):
        return None, 0


def logo_image(ico, px=128):
    """A tk picture of the logo about px wide (a bigger picture is shrunk), or None."""
    png, w = logo_png(ico, px)
    if not png:
        return None
    try:
        img = tk.PhotoImage(data=base64.b64encode(png).decode())
    except tk.TclError:
        return None
    step = max(1, round(w / px))
    return img.subsample(step) if step > 1 else img


def put_logo(parent, ico, bg, px=128):
    """The logo in the middle of the room left in `parent` (packed last, filling what's left).
    Returns the label, or None if there's no picture."""
    img = logo_image(ico, px)
    if img is None:
        return None
    mid = tk.Frame(parent, bg=bg)
    mid.pack(fill="both", expand=True)
    lbl = tk.Label(mid, image=img, bg=bg)
    lbl.image = img                 # keep the picture alive
    lbl.place(relx=0.5, rely=0.45, anchor="center")
    return lbl
