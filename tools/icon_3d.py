"""Give an app's flat logo the slight 3D look the owner picked (2026-11-15, look "E · All of it,
lightly": soft light from above, a faint light top edge, and the white picture shaded a little
and raised a little by a soft shadow). For a logo that is a coloured rounded tile with a white
picture on it, as CleanView's, CleanListen's and CleanRead's are.

Then "the logo doesn't really look difffernt", "mock the same style just more": of 1.6, 2.2
and 2.8 times as strong she picked 2.2 ("4 is goood"), `MORE`.

usage: python tools/icon_3d.py <flat.ico> <out.ico> [<logo.png>]

Works from the .ico's biggest PNG (256 px); every size in the new .ico is shrunk smoothly from
that. <logo.png> is the same look at 512 px, for showing the logo bigger than 256 in the app
(the flat picture enlarged twice with its edges kept sharp, `enlarge`, then the look). Keep the
flat one (e.g. tools/<app>_flat.ico) so the look can be made again or changed. numpy only."""
import struct
import sys
import zlib

import numpy as np

SIZES = (16, 24, 32, 48, 64, 128, 256)
TOP, BOTTOM = 1.28, 0.80      # the tile's colour times this at its top and its bottom
RIM, RIM_WIDTH = 0.45, 4      # the light top edge: how white at the very top, pixels wide (at 256)
SHADOW, SHADOW_DROP, SHADOW_BLUR = 0.35, 3, 3.0
PICTURE_SHADE = 0.15          # the picture's bottom is this much of the way to the tile's colour
MORE = 2.2                    # all of the above this many times as strong (the owner's pick)


def read_ico(path):
    """{size: PNG bytes} of the PNG pictures in an .ico."""
    with open(path, "rb") as fh:
        d = fh.read()
    out = {}
    for i in range(struct.unpack("<H", d[4:6])[0]):
        w, _, _, _, _, _, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
        if d[off:off + 4] == b"\x89PNG":
            out[w or 256] = d[off:off + size]
    return out


def png_rgba(png):
    """h x w x 4 uint8 of an 8-bit RGBA PNG without interlacing."""
    i, idat = 8, b""
    while i < len(png):
        n, kind = struct.unpack(">I4s", png[i:i + 8])
        data = png[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", data)
            assert (depth, ctype, lace) == (8, 6, 0), "needs an 8-bit RGBA PNG"
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
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += row
        prev = row
    return np.frombuffer(bytes(out), np.uint8).reshape(h, w, 4)


def png(rgba):
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def shrink(rgba, n):
    """n x n by averaging, weighted by how see-through each pixel is."""
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


def blur(m, sigma):
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    m = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 0, m)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 1, m)


def erode(m, n):
    for _ in range(n):
        p = np.pad(m, 1)
        m = np.minimum.reduce([p[1:-1, 1:-1], p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
    return m


def three_d(rgba, more=MORE):
    """The look on a flat logo (h x w x 4 uint8, a tile with a white picture); `more` makes
    every part of it that many times as strong (1 is look E as first picked)."""
    TOP, BOTTOM = 1 + (globals()["TOP"] - 1) * more, 1 - (1 - globals()["BOTTOM"]) * more
    RIM, RIM_WIDTH = min(0.9, globals()["RIM"] * more), globals()["RIM_WIDTH"] * more
    SHADOW = min(0.8, globals()["SHADOW"] * more)
    SHADOW_DROP, SHADOW_BLUR = globals()["SHADOW_DROP"] * more, globals()["SHADOW_BLUR"] * more
    PICTURE_SHADE = min(0.4, globals()["PICTURE_SHADE"] * more)
    h, w = rgba.shape[:2]
    s = h / 256
    f = rgba.astype(float)
    A = f[..., 3] / 255
    rgb = f[..., :3]
    lum = rgb @ [0.299, 0.587, 0.114]
    solid = A > 0.99
    base = np.median(rgb[solid & (lum <= np.percentile(lum[solid], 50))], axis=0)
    base_lum = base @ [0.299, 0.587, 0.114]
    P = np.clip((lum - base_lum) / (255 - base_lum), 0, 1) * (A > 0)    # how much is picture
    ys = np.nonzero(A.max(axis=1) > 0.5)[0]
    t = np.clip((np.arange(h) - ys[0]) / max(1, ys[-1] - ys[0]), 0, 1)[:, None]
    tile = base[None, None, :] * (TOP + (BOTTOM - TOP) * t)[..., None] * np.ones((1, w, 1))
    rim = np.clip(erode(A, round(3 * s)) - erode(A, round((3 + RIM_WIDTH) * s)), 0, 1)
    tile += (255 - tile) * (rim * RIM * np.clip(1 - 2 * t, 0, 1))[..., None]
    sh = np.roll(blur(P, SHADOW_BLUR * s), round(SHADOW_DROP * s), axis=0) * SHADOW
    tile = tile * (1 - sh[..., None]) + (base * 0.24)[None, None, :] * sh[..., None]
    py = np.nonzero(P.max(axis=1) > 0.5)[0]
    pt = np.clip((np.arange(h) - py[0]) / max(1, py[-1] - py[0]), 0, 1)[:, None, None]
    pic = 255 + (base[None, None, :] - 255) * PICTURE_SHADE * pt
    out = tile * (1 - P[..., None]) + pic * P[..., None]
    return np.clip(np.dstack([out, f[..., 3]]) + 0.5, 0, 255).astype(np.uint8)


def write_ico(path, big):
    pics = [png(big if n == big.shape[0] else shrink(big, n)) for n in SIZES]
    head = struct.pack("<HHH", 0, 1, len(pics))
    off, dirs = 6 + 16 * len(pics), b""
    for n, p in zip(SIZES, pics):
        dirs += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(p), off)
        off += len(p)
    with open(path, "wb") as fh:
        fh.write(head + dirs + b"".join(pics))


def enlarge(rgba, k=2):
    """A flat tile-and-white-picture logo k times as big with its edges kept sharp: how much is
    tile (alpha) and how much is picture are enlarged smoothly, then their soft edges narrowed k
    times, so an edge is as soft as it was in pixels. The tile's colour is the median's."""
    f = rgba.astype(float)
    A = f[..., 3] / 255
    lum = f[..., :3] @ [0.299, 0.587, 0.114]
    solid = A > 0.99
    base = np.median(f[..., :3][solid & (lum <= np.percentile(lum[solid], 50))], axis=0)
    bl = base @ [0.299, 0.587, 0.114]
    P = np.clip((lum - bl) / (255 - bl), 0, 1) * (A > 0)

    def up(m):
        n = m.shape[0]
        x = (np.arange(n * k) + 0.5) / k - 0.5
        i0 = np.clip(np.floor(x).astype(int), 0, n - 1)
        i1, fx = np.clip(i0 + 1, 0, n - 1), np.clip(x - np.floor(x), 0, 1)
        m = m[i0] * (1 - fx)[:, None] + m[i1] * fx[:, None]
        m = m[:, i0] * (1 - fx)[None, :] + m[:, i1] * fx[None, :]
        return np.clip((m - 0.5) * k + 0.5, 0, 1)
    A2, P2 = up(A), up(P)
    rgb = base * (1 - P2[..., None]) + 255 * P2[..., None]
    return np.clip(np.dstack([rgb, A2 * 255]) + 0.5, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    flat = png_rgba(read_ico(sys.argv[1])[256])
    write_ico(sys.argv[2], three_d(flat))
    if len(sys.argv) > 3:
        with open(sys.argv[3], "wb") as fh:
            fh.write(png(three_d(enlarge(flat))))
    print("ok")
