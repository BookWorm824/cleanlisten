"""The program's logo in the empty part of a page (Jason, 2026-11-07: "I was just looking at a lot
of dead space ... the logo of the program in the middle"), as in CleanView 1.18.23. The picture
is taken out of the program's .ico (its pictures are PNGs, which tk shows without PIL)."""
import base64
import struct
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent

WORKING_LOGO = 192      # the logo on the working page, pixels (was 128; the owner, 2026-11-15:
                        # "lets make it 50% larger on screen", as CleanView 1.18.107)


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


def _png_rgba(png):
    """An h x w x 4 uint8 array of an 8-bit RGBA PNG without interlacing (the icon's), or None."""
    import zlib
    import numpy as np
    try:
        if png[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        i, idat, w, h = 8, b"", 0, 0
        while i < len(png):
            n, kind = struct.unpack(">I4s", png[i:i + 8])
            data = png[i + 8:i + 8 + n]
            if kind == b"IHDR":
                w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", data)
                if (depth, ctype, lace) != (8, 6, 0):
                    return None
            elif kind == b"IDAT":
                idat += data
            i += 12 + n
        raw, stride = zlib.decompress(idat), w * 4
        out, prev = bytearray(), bytearray(stride)
        for y in range(h):
            f, row = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
            for x in range(stride):
                a = row[x - 4] if x >= 4 else 0
                b, c = prev[x], (prev[x - 4] if x >= 4 else 0)
                if f == 1:
                    row[x] = (row[x] + a) & 255
                elif f == 2:
                    row[x] = (row[x] + b) & 255
                elif f == 3:
                    row[x] = (row[x] + (a + b) // 2) & 255
                elif f == 4:
                    q = a + b - c
                    pa, pb, pc = abs(q - a), abs(q - b), abs(q - c)
                    row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            out += row
            prev = row
        return np.frombuffer(bytes(out), np.uint8).reshape(h, w, 4)
    except Exception:
        return None


def _shrink(rgba, n):
    """The picture made n x n by averaging (weighted by how see-through each pixel is)."""
    import numpy as np
    h, w = rgba.shape[:2]

    def weights(size):
        m = np.zeros((n, size))
        for j in range(n):
            a, b = j * size / n, (j + 1) * size / n
            for k in range(int(a), min(size, int(np.ceil(b)))):
                m[j, k] = min(b, k + 1) - max(a, k)
        return m / m.sum(axis=1, keepdims=True)
    ry, rx = weights(h), weights(w)
    f = rgba.astype(float)
    alpha = ry @ f[..., 3] @ rx.T
    rgb = np.stack([ry @ (f[..., c] * f[..., 3]) @ rx.T for c in range(3)], -1)
    rgb = rgb / np.maximum(alpha, 1e-6)[..., None]
    return np.clip(np.dstack([rgb, alpha]) + 0.5, 0, 255).astype(np.uint8)


def _to_png(rgba):
    """PNG bytes of an h x w x 4 uint8 array."""
    import zlib
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def logo_image(ico, px=128):
    """A tk picture of the logo px wide, shrunk smoothly from a bigger picture in the .ico (tk
    itself only shrinks by dropping pixels); if that fails, the old way (nearest size, or every
    other pixel). None if there's no picture."""
    png, w = logo_png(ico, px)
    if not png:
        return None
    if w != px:
        try:
            big = _png_rgba(png)
            if big is not None and big.shape[0] >= px:
                return tk.PhotoImage(data=base64.b64encode(_to_png(_shrink(big, px))).decode(),
                                     format="png")
        except (tk.TclError, ValueError, ImportError):
            pass
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
