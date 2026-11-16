"""The little cleaner on the cleaning screen's logo: CleanView's cvsweeper.py (CleanView 1.18.109),
shared by CleanListen, CleanRead and ReadAloud through logo.put_logo(..., sweeper=True) (the owner,
2026-11-15, asked whether the other apps should get him too: "Yes, all apps"). Only change from
CleanView's: `tile`, where the logo's tile is (CleanRead's is a little smaller).

CleanView's notes: (1.18.109). The owner, 2026-11-15: "would it
be possible to make a little cleaner man that roams around the logo with a broom while
cleaning", then of the mockups "B · bigger" "with d movement": a tenth of the logo's height,
wandering over the logo, stopping now and then to sweep with a puff of dust.

numpy draws him (smooth edges at any size, the way cvlook draws); `Walker` decides where he
goes (no Tk, so tests can run it); `Sweeper` shows him on a Tk canvas over the logo. The canvas
shows the logo on the page's background as one picture (`backdrop`) and him as a small second
picture cut from it with him drawn in, moved each frame."""
import math
import random
import time

import numpy as np

SIZE = 0.1          # his height, as a share of the logo's ("B · bigger": 1/10)
SPEED = 0.85        # how fast he walks, his heights a second
FPS = 20
PUFF_LIFE = 0.8     # seconds a puff of dust lasts
BOX = (-0.8, 0.8, -1.15, 0.25)   # the picture around him, in his heights from his feet
TILE = (20 / 512, 492 / 512)     # where the logo's tile is, as shares of its width (CleanView's)

TROUSERS, SHOES, OVERALLS, COLLAR = (46, 74, 122), (58, 42, 32), (59, 110, 168), (242, 209, 107)
SKIN, CAP, EYE, HANDLE, BRISTLES = (241, 194, 125), (200, 69, 58), (35, 33, 31), (139, 90, 43), (217, 164, 65)
ARM, DUST = (47, 92, 143), (150, 140, 128)


def backdrop(logo, bg):
    """The logo (h x w x 4 uint8) on the background colour ("#rrggbb"), h x w x 3 uint8."""
    bg = np.array([int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], float)
    a = logo[..., 3:4] / 255.0
    return np.clip(logo[..., :3] * a + bg * (1 - a) + 0.5, 0, 255).astype(np.uint8)


def opaque(rgb):
    """h x w x 3 uint8 as h x w x 4 with every pixel solid (for cvlook.photo)."""
    return np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])


# ---------- drawing ----------
def _cover(d):
    """How much of each pixel a shape covers, from the distance to its edge (inside < 0)."""
    return np.clip(0.5 - d, 0, 1)


def _capsule(x, y, ax, ay, bx, by, r):
    dx, dy = bx - ax, by - ay
    t = np.clip(((x - ax) * dx + (y - ay) * dy) / max(1e-9, dx * dx + dy * dy), 0, 1)
    return np.hypot(x - ax - t * dx, y - ay - t * dy) - r


def _circle(x, y, cx, cy, r):
    return np.hypot(x - cx, y - cy) - r


def _box(x, y, x0, x1, y0, y1, r=0.0):
    cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    r = min(r, hw, hh)
    qx, qy = np.abs(x - cx) - (hw - r), np.abs(y - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def _polygon(x, y, pts):
    """A convex polygon's edge distance (close enough for small shapes)."""
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    d = None
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        nx, ny = by - ay, ax - bx
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln, ny / ln
        if (cx - ax) * nx + (cy - ay) * ny > 0:      # point the normal outwards
            nx, ny = -nx, -ny
        e = (x - ax) * nx + (y - ay) * ny
        d = e if d is None else np.maximum(d, e)
    return d


def _blur(m, r):
    """A quick soft blur (two box blurs each way)."""
    r = max(1, int(round(r)))
    for axis in (0, 1, 0, 1):
        p = np.pad(m, [(r, r) if a == axis else (0, 0) for a in (0, 1)], mode="constant")
        c = np.cumsum(p, axis=axis)
        c = np.concatenate([np.zeros_like(c.take([0], axis=axis)), c], axis=axis)
        n = m.shape[axis]
        m = (c.take(range(2 * r + 1, 2 * r + 1 + n), axis=axis) - c.take(range(0, n), axis=axis)) / (2 * r + 1)
    return m


def broom_tip(h, sweep):
    """Where the broom's bristles end, from his feet, facing right."""
    ang = 0.6 + sweep * 0.32
    hx, hy = 0.1 * h, -0.6 * h
    return hx + math.sin(ang) * 0.73 * h, hy + math.cos(ang) * 0.73 * h


def draw(picture, fx, fy, h, walk=0.0, sweep=0.0, face=1, shadow=True):
    """Draw him into picture (h x w x 3 uint8, changed in place) with his feet at (fx, fy):
    walk is how far through his steps (radians), sweep the broom's swing (-1 to 1), face 1 for
    right, -1 for left."""
    H, W = picture.shape[:2]
    y, x = np.mgrid[0:H, 0:W].astype(float) + 0.5
    x, y = (x - fx) * face, y - fy                     # his own directions, feet at 0, 0
    lw = max(1.3, 0.075 * h)
    hip, sw = -0.42 * h, math.sin(walk) * 0.45
    ang = 0.6 + sweep * 0.32
    hx, hy = 0.1 * h, -0.6 * h
    sa, ca = math.sin(ang), math.cos(ang)
    ex, ey = hx + sa * 0.58 * h, hy + ca * 0.58 * h

    def turned(u, v):                                  # the bristles, along the handle
        return ex + u * ca + v * sa, ey - u * sa + v * ca
    parts = []
    for k in (1, -1):
        a = sw * k
        footx, footy = math.sin(a) * 0.4 * h, hip + math.cos(a) * 0.4 * h
        parts.append((_capsule(x, y, 0, hip, footx, footy, lw * 0.75), TROUSERS))
        parts.append((_capsule(x, y, footx - 0.02 * h, footy, footx + 0.07 * h, footy, lw * 0.65), SHOES))
    parts += [
        (_box(x, y, -0.14 * h, 0.14 * h, -0.78 * h, -0.38 * h, 0.07 * h), OVERALLS),
        (_box(x, y, -0.09 * h, 0.09 * h, -0.78 * h, -0.72 * h), COLLAR),
        (_circle(x, y, 0, -0.88 * h, 0.12 * h), SKIN),
        (np.maximum(_circle(x, y, 0, -0.9 * h, 0.128 * h), y + 0.9 * h), CAP),
        (_box(x, y, 0, 0.21 * h, -0.915 * h, -0.875 * h), CAP),
        (_circle(x, y, 0.06 * h, -0.87 * h, max(0.4, 0.018 * h)), EYE),
        (_capsule(x, y, hx - sa * 0.12 * h, hy - ca * 0.12 * h, ex, ey, lw / 2), HANDLE),
        (_polygon(x, y, [turned(-0.05 * h, -0.01 * h), turned(0.05 * h, -0.01 * h),
                         turned(0.11 * h, 0.15 * h), turned(-0.11 * h, 0.15 * h)]), BRISTLES),
        (_capsule(x, y, 0, -0.72 * h, hx, hy, lw * 0.6), ARM),
    ]
    out = picture.astype(float)
    if shadow:
        ground = _cover((np.hypot(x / (0.22 * h), y / (0.06 * h)) - 1) * 0.06 * h)
        out *= 1 - 0.18 * ground[..., None]
        whole = np.zeros((H, W))
        for d, _ in parts:
            whole = np.maximum(whole, _cover(d))
        halo = _blur(whole, max(1.0, 0.04 * h))         # a soft dark edge, to stand out
        out *= 1 - 0.28 * np.clip(halo * 1.6, 0, 1)[..., None]
    for d, colour in parts:
        c = _cover(d)[..., None]
        out = out * (1 - c) + np.array(colour, float) * c
    picture[:] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return picture


def draw_puffs(picture, puffs, h, ox=0.0, oy=0.0):
    """Puffs of dust: (x, y, age) each, x and y less ox, oy in this picture."""
    if not puffs:
        return picture
    H, W = picture.shape[:2]
    y, x = np.mgrid[0:H, 0:W].astype(float) + 0.5
    out = picture.astype(float)
    for px, py, age in puffs:
        a = 0.55 * max(0.0, 1 - age / PUFF_LIFE)
        for i in range(3):
            c = _cover(_circle(x, y, px - ox + (i - 1) * h * 0.12 * (1 + age),
                               py - oy - age * h * 0.25 - (i % 2) * 2,
                               (0.05 + age * 0.08) * h))[..., None] * a
            out = out * (1 - c) + np.array(DUST, float) * c
    picture[:] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return picture


# ---------- where he goes ----------
class Walker:
    """Wanders over a logo n pixels across: walks to a spot, sweeps a while (a puff of dust at
    the end of each stroke), picks another spot."""

    def __init__(self, n, rng=None, tile=None):
        self.rng = rng or random.Random()
        self.n = n
        self.tile = tile or TILE
        self.x, self.y = n * 0.42, n * 0.62
        self.face, self.walk, self.t = 1, 0.0, 0.0
        self.state, self.timer, self.last_puff = "walk", 0.0, -1.0
        self.puffs = []
        self.pick()

    @property
    def h(self):
        return max(12.0, self.n * SIZE)

    def bounds(self):
        """Where his feet may go: over the logo's tile, his head and broom kept on it."""
        t0, t1 = self.n * self.tile[0], self.n * self.tile[1]
        return t0 + 0.16 * self.n, t1 - 0.16 * self.n, t0 + 0.21 * self.n, t1 - 0.1 * self.n

    def pick(self):
        x0, x1, y0, y1 = self.bounds()
        self.tx, self.ty = self.rng.uniform(x0, x1), self.rng.uniform(y0, y1)

    def resize(self, n):
        k = n / self.n
        self.n = n
        self.x, self.y, self.tx, self.ty = self.x * k, self.y * k, self.tx * k, self.ty * k
        self.puffs = [(x * k, y * k, a) for x, y, a in self.puffs]

    @property
    def sweep(self):
        return math.sin(self.t * 13) if self.state == "sweep" else math.sin(self.t * 5) * 0.4

    def step(self, dt):
        self.t += dt
        self.puffs = [(x, y, a + dt) for x, y, a in self.puffs if a + dt < PUFF_LIFE]
        if self.state == "walk":
            speed = SPEED * self.h
            self.walk += dt * speed / (0.22 * self.h)
            dx, dy = self.tx - self.x, self.ty - self.y
            d = math.hypot(dx, dy)
            if d <= speed * dt:
                self.x, self.y = self.tx, self.ty
                self.state, self.timer = "sweep", 1.4 + self.rng.random()
                self.pick()
            else:
                self.x += dx / d * speed * dt
                self.y += dy / d * speed * dt
                if abs(dx) > 1:
                    self.face = 1 if dx > 0 else -1
        else:
            self.timer -= dt
            # a puff at the end of a stroke, none in the last moments (they'd be left behind)
            if (self.timer > PUFF_LIFE * 0.6 and math.sin(self.t * 13) > 0.95
                    and self.t - self.last_puff > 0.3):
                self.last_puff = self.t
                bx, by = broom_tip(self.h, math.sin(self.t * 13))
                self.puffs.append((self.x + bx * self.face, self.y + by, 0.0))
            if self.timer <= 0:
                self.state = "walk"

    def box(self):
        """The picture around him (x0, y0, x1, y1), whole pixels, inside the logo."""
        h, (a, b, c, d) = self.h, BOX
        x0, y0 = max(0, int(self.x + a * h)), max(0, int(self.y + c * h))
        return x0, y0, min(self.n, int(math.ceil(self.x + b * h))), min(self.n, int(math.ceil(self.y + d * h)))

    def picture(self, back):
        """(x0, y0, the backdrop there with him and his dust drawn in)."""
        x0, y0, x1, y1 = self.box()
        pic = back[y0:y1, x0:x1].copy()
        draw(pic, self.x - x0, self.y - y0, self.h, 0.0 if self.state == "sweep" else self.walk,
             self.sweep, self.face)
        draw_puffs(pic, self.puffs, self.h, x0, y0)
        return x0, y0, pic


# ---------- on the screen ----------
class Sweeper:
    """Him on a Tk canvas that shows `back` (the backdrop) at 0, 0. Stops by itself when the
    canvas goes (the page changed) and draws nothing while it isn't on the screen."""

    def __init__(self, canvas, back, photo, tile=None):
        self.canvas, self.back, self.photo = canvas, back, photo     # photo(rgba, into) -> image
        self.walker = Walker(back.shape[0], tile=tile)
        self.img = None
        self.item = None
        self.when = None
        self.running = False
        self.top = canvas.winfo_toplevel()
        self.next = None                       # the next frame's `after`
        canvas.bind("<Destroy>", lambda e: self.stop(), add="+")

    def start(self):
        if not self.running:
            self.running, self.when = True, time.monotonic()
            self._tick()

    def stop(self):
        self.running = False
        if self.next is not None:
            try:
                self.top.after_cancel(self.next)
            except Exception:
                pass
            self.next = None

    def set_backdrop(self, back):
        self.back = back
        self.walker.resize(back.shape[0])

    def _tick(self):
        self.next = None
        if not self.running:
            return
        try:
            if not self.canvas.winfo_exists():
                self.running = False
                return
            now = time.monotonic()
            self.walker.step(min(0.1, now - self.when))
            self.when = now
            if self.canvas.winfo_ismapped() and self.canvas.winfo_toplevel().state() != "iconic":
                x0, y0, pic = self.walker.picture(self.back)
                self.img = self.photo(opaque(pic), self.img)
                if self.item is None:
                    self.item = self.canvas.create_image(x0, y0, image=self.img, anchor="nw")
                else:
                    self.canvas.coords(self.item, x0, y0)
                    self.canvas.tag_raise(self.item)
            # the window's after, not the canvas's: the canvas's goes with it
            self.next = self.top.after(1000 // FPS, self._tick)
        except Exception:          # never let him break the cleaning screen
            self.running = False
