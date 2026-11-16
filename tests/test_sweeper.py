"""CleanView's little cleaner on CleanListen's and CleanRead's working logo (1.17.49, with CleanView 1.18.110's walk and pause; the owner,
2026-11-15, asked whether the other apps should get CleanView's little cleaner: "Yes, all apps").
A tenth of the logo's height, wandering over the logo's tile and sweeping with puffs of dust."""
import json
import random
import time
import tkinter as tk
import unittest
from pathlib import Path

import numpy as np

import logo
import sweeper as sw

REPO = Path(__file__).resolve().parent.parent
RED = np.array(sw.CAP)


def back_of(ico, n=384, bg="#F6F3EE"):
    pic = logo.logo_rgba(ico, n)
    return sw.backdrop(logo._resize(pic, n), bg), logo._tile(pic)


class Walking(unittest.TestCase):
    def test_a_tenth_of_the_logo(self):
        self.assertEqual(sw.SIZE, 0.1)
        self.assertAlmostEqual(sw.Walker(384).h, 38.4)

    def test_each_logos_tile_is_found(self):
        _, t = back_of("icon.ico")
        self.assertAlmostEqual(t[0] * 512, 20, delta=1.5)
        self.assertAlmostEqual(t[1] * 512, 492, delta=1.5)
        _, t = back_of("cleanread.ico")
        self.assertAlmostEqual(t[0] * 512, 28, delta=1.5)
        self.assertAlmostEqual(t[1] * 512, 484, delta=1.5)

    def test_stays_on_the_logo_and_sweeps(self):
        for ico in ("icon.ico", "cleanread.ico"):
            back, tile = back_of(ico)
            w = sw.Walker(384, random.Random(1), tile=tile)
            x0, x1, y0, y1 = w.bounds()
            self.assertGreaterEqual(x0 - 0.16 * 384, tile[0] * 384 - 1e-6)
            states, faces, puffs = set(), set(), 0
            for _ in range(sw.FPS * 120):                       # two minutes
                w.step(1 / sw.FPS)
                self.assertTrue(x0 - 1e-6 <= w.x <= x1 + 1e-6 and y0 - 1e-6 <= w.y <= y1 + 1e-6)
                bx0, by0, bx1, by1 = w.box()
                self.assertTrue(0 <= bx0 < bx1 <= 384 and 0 <= by0 < by1 <= 384)
                states.add(w.state)
                faces.add(w.face)
                puffs = max(puffs, len(w.puffs))
            self.assertEqual(states, {"walk", "sweep"}, ico)
            self.assertEqual(faces, {1, -1}, ico)
            self.assertGreater(puffs, 0, ico)

    def test_drawn_on_the_logo_quickly(self):
        back, tile = back_of("cleanread.ico")
        w = sw.Walker(384, random.Random(4), tile=tile)
        x0, y0, pic = w.picture(back)
        under = back[y0:y0 + pic.shape[0], x0:x0 + pic.shape[1]]
        changed = np.abs(pic.astype(int) - under).max(axis=2) > 3
        self.assertTrue(changed.any())
        self.assertTrue((np.abs(pic.astype(int) - RED).sum(axis=2) < 30).any())   # his red cap
        t = time.perf_counter()
        for _ in range(40):
            w.step(1 / sw.FPS)
            logo._to_png(sw.opaque(w.picture(back)[2]))
        self.assertLess((time.perf_counter() - t) / 40, 0.03)


class OnTheWorkingPage(unittest.TestCase):
    def test_sweeps_the_logo_and_stops_with_the_page(self):
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display ({e})")
        try:
            root.geometry("900x800")
            page = tk.Frame(root, bg="#F6F3EE")
            page.pack(fill="both", expand=True)
            cv = logo.put_logo(page, "cleanread.ico", "#F6F3EE", logo.WORKING_LOGO, sweeper=True)
            self.assertIsInstance(cv, tk.Canvas)
            sweep = cv.sweeper
            self.assertTrue(sweep.running)
            self.assertAlmostEqual(sweep.walker.tile[0] * 512, 28, delta=1.5)

            def pump(secs):
                end = time.monotonic() + secs
                while time.monotonic() < end:
                    root.update()
                    time.sleep(0.01)
            pump(0.5)
            self.assertIsNotNone(sweep.item)
            first = cv.coords(sweep.item)
            pump(2.0)
            self.assertNotEqual(cv.coords(sweep.item), first)            # he moved
            self.assertEqual(sweep.walker.n, cv.size)
            root.geometry("700x330")                                     # less room
            pump(0.6)
            self.assertLess(cv.size, 384)
            self.assertEqual(sweep.walker.n, cv.size)
            self.assertEqual(sweep.back.shape[0], cv.size)
            page.destroy()                                               # the page changed
            self.assertFalse(sweep.running)
            self.assertIsNone(sweep.next)          # nothing left waiting (it upset others in CleanView)
            pump(0.3)
            self.assertFalse(sweep.running)
            # paused: he stands leaning on his broom (CleanView 1.18.110), and walks on when let go
            held = [True]
            page2 = tk.Frame(root, bg="#F6F3EE")
            page2.pack(fill="both", expand=True)
            cv2 = logo.put_logo(page2, "icon.ico", "#F6F3EE", logo.WORKING_LOGO, sweeper=True, paused=lambda: held[0])
            pump(0.6)
            self.assertTrue(cv2.sweeper.walker.paused)
            spot = (cv2.sweeper.walker.x, cv2.sweeper.walker.y)
            pump(0.6)
            self.assertEqual((cv2.sweeper.walker.x, cv2.sweeper.walker.y), spot)
            held[0] = False
            pump(0.4)
            self.assertFalse(cv2.sweeper.walker.paused)
            page2.destroy()
            # the small logo elsewhere stays a plain picture
            lbl = logo.put_logo(tk.Frame(root), "cleanread.ico", "#F6F3EE", 128, sweeper=True)
            self.assertIsInstance(lbl, tk.Label)
        finally:
            root.destroy()

    def test_both_working_pages_ask_for_him_and_he_ships(self):
        for name in ("CleanListen.pyw", "CleanRead.pyw"):
            text = (REPO / name).read_text(encoding="utf8")
            self.assertIn("LOGO.WORKING_LOGO, sweeper=True", text, name)
        self.assertIn("sweeper.py", json.loads((REPO / "version.json").read_text())["files"])


if __name__ == "__main__":
    unittest.main()
