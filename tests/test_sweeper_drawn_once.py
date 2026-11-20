"""The little man drawn once and moved (1.17.94; the owner, 2026-11-20, checking a book in CleanRead
without the AI helper: "the littleman on the logo did this and didn't move, the whole app also froze
for a bit before showing what was found"). Drawing him took hundreds of small steps, each waiting its
turn while the check ran, so a frame took 4 seconds; now each pose is drawn once, see-through, and
the window plays a third of a second of frames at a time by itself."""
import random
import time
import tkinter as tk

import numpy as np
import pytest

import logo
import sweeper as SW


def test_see_through_looks_the_same_as_drawn():
    pic = logo.logo_rgba("cleanread.ico", 384)
    back = SW.backdrop(logo._resize(pic, 384), "#1B1C1E")
    w = SW.Walker(back.shape[0], rng=random.Random(3), tile=logo._tile(pic))
    for _ in range(40):
        w.step(0.07)
        x0, y0, x1, y1 = w.box()
        real = back[y0:y1, x0:x1].copy()
        SW.draw(real, w.x - x0, w.y - y0, w.h, w.shown, w.face, wear=w.wear)
        rgba = SW.see_through(lambda p: SW.draw(p, w.x - x0, w.y - y0, w.h, w.shown, w.face, wear=w.wear),
                              real.shape)
        a = rgba[..., 3:4] / 255.0
        over = back[y0:y1, x0:x1] * (1 - a) + rgba[..., :3] * a
        assert np.abs(over - real).max() <= 3


def test_every_pose_drawn():
    pics = SW.all_pictures(34.0, SW.outfit())
    keys = {(m, i, f) for m, n in SW.PHASES.items() for i in range(n) for f in (1, -1)}
    assert keys | {("puff", k) for k in range(SW.PUFF_STEPS)} == set(pics)
    for rgba, left, top in pics.values():
        assert rgba.shape[2] == 4 and rgba[..., 3].max() > 0


def test_pose_key_follows_him():
    w = SW.Walker(384, rng=random.Random(1))
    seen = set()
    for _ in range(200):
        w.step(1 / 15)
        m, i, f = SW.pose_key(w)
        assert m == w.mode() and 0 <= i < SW.PHASES[m] and f == w.face
        seen.add((m, i))
    assert len({i for m, i in seen if m == "walk"}) > 5      # a whole step, not one pose


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no screen to draw on ({ex})")
    r.geometry("900x800")
    yield r
    r.destroy()


def pump(root, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def test_on_the_page_he_is_moved_not_drawn(root, monkeypatch):
    def no(*a, **k):
        raise AssertionError("drawn again")
    page = tk.Frame(root, bg="#1B1C1E")
    page.pack(fill="both", expand=True)
    cv = logo.put_logo(page, "cleanread.ico", "#1B1C1E", logo.WORKING_LOGO, sweeper=True)
    sw = cv.sweeper
    assert sw.drawn_once and sw.pictures
    monkeypatch.setattr(SW, "draw", no)                    # no drawing once he's going
    monkeypatch.setattr(SW.Walker, "picture", no)
    pump(root, 0.3)
    first, images = cv.coords(sw.item), set()
    for _ in range(20):
        pump(root, 0.1)
        images.add(cv.itemcget(sw.item, "image"))
    assert cv.coords(sw.item) != first                     # he moved
    assert len(images) > 2                                 # and his pose changed
    page.destroy()                                         # the page changed: he stops
    assert not sw.running
    pump(root, 0.5)
