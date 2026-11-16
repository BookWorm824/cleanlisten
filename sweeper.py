"""The little cleaner on the cleaning screen's logo: CleanView's cvsweeper.py (CleanView 1.18.110),
shared by CleanListen, CleanRead and ReadAloud through logo.put_logo(..., sweeper=True) (the owner,
2026-11-15, asked whether the other apps should get him too: "Yes, all apps"). Only change from
CleanView's: `tile`, where the logo's tile is (CleanRead's is a little smaller).

CleanView's notes: (1.18.109). The owner, 2026-11-15: "would it
be possible to make a little cleaner man that roams around the logo with a broom while
cleaning", then of the mockups "B · bigger" "with d movement": a tenth of the logo's height,
wandering over the logo, stopping now and then to sweep with a puff of dust. 1.18.110 ("can
we make the cleaner walk a little more realistic. and make him pause with the cleaninig", "When
I press Pause"): knees that bend, feet that stay put on the ground while the body goes over
them, a bob in each step, a lean into each sweep, and while cleaning is paused he stands
leaning on his broom.

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
FAR_TROUSERS, FAR_SHOES = (34, 56, 96), (44, 32, 24)     # the leg further away, in shadow

# his walk, in his heights: legs from the hip, each half, and the hip's height standing
HIP, LEG = 0.425, 0.228
STRIDE = 0.36       # how far a foot goes back under him while it's on the ground
ON_GROUND = 0.6     # the part of each step a foot is on the ground (the rest it swings)
LIFT = 0.06         # how high a swinging foot is lifted
BOB = 0.015         # the body's rise and fall in a step
BLEND = 0.25        # seconds to change from walking to sweeping or standing, and back

# a pose: each foot (from under the hip, up is minus), the body lowered (dy), leaned forward
# (lean, radians) and the broom's angle from straight down (forward is plus)
STANDING = {"near": (0.06, 0.0), "far": (-0.05, 0.0), "dy": 0.0, "lean": 0.0, "broom": 0.6}


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


def _upper(x, y, pose, h):
    """From the body's own directions to the upper body's (lowered and leaned with the pose)."""
    lean, pivot = pose["lean"], -HIP * h
    c, s = math.cos(lean), math.sin(lean)
    y = y - pose["dy"] * h - pivot
    return c * x + s * y, -s * x + c * y + pivot


def broom_tip(h, pose):
    """Where the broom's bristles end, from his feet, facing right."""
    ang, lean, pivot = pose["broom"], pose["lean"], -HIP * h
    ux, uy = 0.1 * h + math.sin(ang) * 0.73 * h, -0.6 * h + math.cos(ang) * 0.73 * h - pivot
    c, s = math.cos(lean), math.sin(lean)
    return c * ux - s * uy, s * ux + c * uy + pivot + pose["dy"] * h


def _knee(hx, hy, fx, fy, leg):
    """Where the knee is, bending forward, for a hip and a foot."""
    d = min(math.hypot(fx - hx, fy - hy), 2 * leg - 1e-6)
    th, a = math.atan2(fy - hy, fx - hx), math.acos(d / (2 * leg))
    return hx + leg * math.cos(th - a), hy + leg * math.sin(th - a)


def draw(picture, fx, fy, h, pose=None, face=1, shadow=True):
    """Draw him into picture (h x w x 3 uint8, changed in place) with his feet at (fx, fy) and
    the pose (`STANDING` if none), facing right (face 1) or left (-1)."""
    pose = pose or STANDING
    H, W = picture.shape[:2]
    y, x = np.mgrid[0:H, 0:W].astype(float) + 0.5
    x, y = (x - fx) * face, y - fy                     # his own directions, feet at 0, 0
    ux, uy = _upper(x, y, pose, h)                     # the upper body's
    lw = max(1.3, 0.075 * h)
    hip = -HIP * h + pose["dy"] * h
    ang = pose["broom"]
    hx, hy = 0.1 * h, -0.6 * h
    sa, ca = math.sin(ang), math.cos(ang)
    ex, ey = hx + sa * 0.58 * h, hy + ca * 0.58 * h

    def turned(u, v):                                  # the bristles, along the handle
        return ex + u * ca + v * sa, ey - u * sa + v * ca
    parts = []
    for leg, trousers, shoes in (("far", FAR_TROUSERS, FAR_SHOES), ("near", TROUSERS, SHOES)):
        footx, footy = pose[leg][0] * h, pose[leg][1] * h
        kx, ky = _knee(0, hip, footx, footy, LEG * h)
        parts.append((np.minimum(_capsule(x, y, 0, hip, kx, ky, lw * 0.75),
                                 _capsule(x, y, kx, ky, footx, footy, lw * 0.7)), trousers))
        parts.append((_capsule(x, y, footx - 0.02 * h, footy, footx + 0.07 * h, footy, lw * 0.65),
                      shoes))
    parts += [
        (_box(ux, uy, -0.14 * h, 0.14 * h, -0.78 * h, -0.38 * h, 0.07 * h), OVERALLS),
        (_box(ux, uy, -0.09 * h, 0.09 * h, -0.78 * h, -0.72 * h), COLLAR),
        (_circle(ux, uy, 0, -0.88 * h, 0.12 * h), SKIN),
        (np.maximum(_circle(ux, uy, 0, -0.9 * h, 0.128 * h), uy + 0.9 * h), CAP),
        (_box(ux, uy, 0, 0.21 * h, -0.915 * h, -0.875 * h), CAP),
        (_circle(ux, uy, 0.06 * h, -0.87 * h, max(0.4, 0.018 * h)), EYE),
        (_capsule(ux, uy, hx - sa * 0.12 * h, hy - ca * 0.12 * h, ex, ey, lw / 2), HANDLE),
        (_polygon(ux, uy, [turned(-0.05 * h, -0.01 * h), turned(0.05 * h, -0.01 * h),
                           turned(0.11 * h, 0.15 * h), turned(-0.11 * h, 0.15 * h)]), BRISTLES),
        (_capsule(ux, uy, 0, -0.72 * h, hx, hy, lw * 0.6), ARM),
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
def _ease(u):
    return (1 - math.cos(math.pi * min(1.0, max(0.0, u)))) / 2


def _mix(a, b, k):
    """The pose part way (k, 0-1) from a to b."""
    out = {}
    for key in a:
        if isinstance(a[key], tuple):
            out[key] = tuple(p + (q - p) * k for p, q in zip(a[key], b[key]))
        else:
            out[key] = a[key] + (b[key] - a[key]) * k
    return out


def walking(p):
    """The pose p of the way through a step (0-1): each foot on the ground going back under
    him for ON_GROUND of it, then lifted and swung forward; the other foot half a step on."""
    def foot(q):
        if q < ON_GROUND:
            return STRIDE / 2 - STRIDE * q / ON_GROUND, 0.0
        u = (q - ON_GROUND) / (1 - ON_GROUND)
        return -STRIDE / 2 + STRIDE * _ease(u), -LIFT * math.sin(math.pi * u)
    up = BOB * math.cos(4 * math.pi * (p - ON_GROUND / 2))     # highest over each foot
    return {"near": foot(p), "far": foot((p + 0.5) % 1), "dy": -up, "lean": 0.06,
            "broom": 0.75 + 0.08 * math.sin(4 * math.pi * p)}


def sweeping(t):
    """Feet apart, knees bent a little, leaning into each stroke of the broom."""
    s = math.sin(t * 13)
    return {"near": (0.1, 0.0), "far": (-0.08, 0.0), "dy": 0.025 + 0.012 * s,
            "lean": 0.1 + 0.06 * s, "broom": 0.6 + 0.32 * s}


def leaning(t):
    """Paused: standing, the broom upright beside him, breathing."""
    return {"near": (0.05, 0.0), "far": (-0.04, 0.0), "dy": 0.004 * math.sin(t * 2.2),
            "lean": -0.02, "broom": 0.12}


class Walker:
    """Wanders over a logo n pixels across: walks to a spot, sweeps a while (a puff of dust at
    the end of each stroke), picks another. `paused` (cleaning is paused): he stops where he is
    and leans on his broom until it's let go."""

    def __init__(self, n, rng=None, tile=None):
        self.rng = rng or random.Random()
        self.n = n
        self.tile = tile or TILE
        self.x, self.y = n * 0.42, n * 0.62
        self.face, self.p, self.t = 1, 0.0, 0.0
        self.state, self.timer, self.last_puff = "walk", 0.0, -1.0
        self.paused = False
        self.puffs = []
        self.pick()
        self._mode, self._blend = self.mode(), 1.0
        self._from = self.shown = self.target()

    @property
    def h(self):
        return max(12.0, self.n * SIZE)

    def mode(self):
        return "pause" if self.paused else self.state

    def target(self):
        m = self.mode()
        return walking(self.p) if m == "walk" else sweeping(self.t) if m == "sweep" else leaning(self.t)

    def pose(self):
        """What he looks like now: the pose for what he's doing, eased in after a change."""
        return self.target() if self._blend >= 1 else _mix(self._from, self.target(), _ease(self._blend))

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

    def _changed(self):
        if self.mode() != self._mode:
            self._from, self._blend, self._mode = self.shown, 0.0, self.mode()

    def step(self, dt):
        self.t += dt
        self.puffs = [(x, y, a + dt) for x, y, a in self.puffs if a + dt < PUFF_LIFE]
        self._changed()                          # paused or let go since the last step
        if self.paused:
            pass
        elif self.state == "walk":
            speed = SPEED * self.h
            # a step takes as long as the body takes to go over a foot on the ground, so the
            # feet don't slide
            self.p = (self.p + dt * speed / (STRIDE * self.h / ON_GROUND)) % 1
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
            if (self._blend >= 1 and self.timer > PUFF_LIFE * 0.6
                    and math.sin(self.t * 13) > 0.95 and self.t - self.last_puff > 0.3):
                self.last_puff = self.t
                bx, by = broom_tip(self.h, sweeping(self.t))
                self.puffs.append((self.x + bx * self.face, self.y + by, 0.0))
            if self.timer <= 0:
                self.state = "walk"
        self._changed()
        self._blend = min(1.0, self._blend + dt / BLEND)
        self.shown = self.pose()

    def box(self):
        """The picture around him (x0, y0, x1, y1), whole pixels, inside the logo."""
        h, (a, b, c, d) = self.h, BOX
        x0, y0 = max(0, int(self.x + a * h)), max(0, int(self.y + c * h))
        return x0, y0, min(self.n, int(math.ceil(self.x + b * h))), min(self.n, int(math.ceil(self.y + d * h)))

    def picture(self, back):
        """(x0, y0, the backdrop there with him and his dust drawn in)."""
        x0, y0, x1, y1 = self.box()
        pic = back[y0:y1, x0:x1].copy()
        draw(pic, self.x - x0, self.y - y0, self.h, self.shown, self.face)
        draw_puffs(pic, self.puffs, self.h, x0, y0)
        return x0, y0, pic


# ---------- on the screen ----------
class Sweeper:
    """Him on a Tk canvas that shows `back` (the backdrop) at 0, 0. Stops by itself when the
    canvas goes (the page changed) and draws nothing while it isn't on the screen. paused():
    whether cleaning is paused now, asked every frame (he leans on his broom meanwhile)."""

    def __init__(self, canvas, back, photo, paused=None, tile=None):
        self.canvas, self.back, self.photo = canvas, back, photo     # photo(rgba, into) -> image
        self.paused = paused
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
            if self.paused is not None:
                self.walker.paused = bool(self.paused())
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
