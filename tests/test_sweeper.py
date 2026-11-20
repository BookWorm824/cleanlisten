"""CleanView's little cleaner on CleanListen's and CleanRead's working logo (1.17.49, with CleanView 1.18.110's walk and pause; the owner,
2026-11-15, asked whether the other apps should get CleanView's little cleaner: "Yes, all apps").
A tenth of the logo's height, wandering over the logo's tile and sweeping with puffs of dust."""
import datetime
import json
import math
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
        cap = np.array(w.wear["cap"][1])                                 # this week's cap
        self.assertTrue((np.abs(pic.astype(int) - cap).sum(axis=2) < 30).any())
        t = time.perf_counter()
        for _ in range(40):
            w.step(1 / sw.FPS)
            logo._to_png(sw.opaque(w.picture(back)[2]))
        self.assertLess((time.perf_counter() - t) / 40, 0.03)


class LifelikeWalk(unittest.TestCase):
    """CleanView 1.18.110-111's walk and push-broom tests, as they are there."""
    """1.18.110: "can we make the cleaner walk a little more realistic. and make him pause with
    the cleaninig", "When I press Pause"."""

    def test_a_foot_on_the_ground_stays_put(self):
        w = sw.Walker(384, random.Random(6))
        w.tx, w.ty = w.x + 300, w.y                         # a long walk to the right
        for _ in range(20):                                 # past any easing in
            w.step(1 / sw.FPS)
        planted = []
        for _ in range(60):
            w.step(1 / sw.FPS)
            fx, fy = w.shown["near"]
            planted.append((fy == 0.0, w.x + fx * w.h))
        runs, run = [], []
        for down, where in planted:
            if down:
                run.append(where)
            elif run:
                runs.append(run)
                run = []
        self.assertGreater(len(runs), 1)
        for run in runs:
            self.assertLess(max(run) - min(run), 0.5)       # under half a pixel: no sliding

    def test_knees_bend_and_feet_take_turns(self):
        ps = [sw.walking(i / 20) for i in range(20)]
        self.assertTrue(any(p["near"][1] < 0 for p in ps) and any(p["far"][1] < 0 for p in ps))
        self.assertFalse(any(p["near"][1] < 0 and p["far"][1] < 0 for p in ps))   # one at a time
        kx, ky = sw._knee(0, -sw.HIP * 38, 0, 0, sw.LEG * 38)
        self.assertGreater(kx, 0)                           # bent forward
        self.assertTrue(-sw.HIP * 38 < ky < 0)

    def test_poses_ease_into_each_other(self):
        w = sw.Walker(384, random.Random(7))
        w.step(0.05)
        before = w.shown["near"]
        w.paused = True
        w.step(0.05)
        self.assertNotEqual(w.shown["near"], sw.leaning(w.t)["near"])     # on its way
        for _ in range(10):
            w.step(0.05)
        self.assertEqual(w.shown, sw.leaning(w.t))
        self.assertNotEqual(before, w.shown["near"])

    def test_paused_he_stays_and_leans_on_his_broom(self):
        w = sw.Walker(384, random.Random(8))
        for _ in range(sw.FPS * 6):
            w.step(1 / sw.FPS)
        w.paused = True
        w.step(1 / sw.FPS)
        where, state = (w.x, w.y), w.state
        made = len(w.puffs)
        for _ in range(sw.FPS * 5):
            w.step(1 / sw.FPS)
            self.assertLessEqual(len(w.puffs), made)        # no new dust
        self.assertEqual((w.x, w.y, w.state), where + (state,))
        self.assertEqual((w.shown["head"], w.shown["grip"]),
                         (sw.leaning(0)["head"], sw.leaning(0)["grip"]))
        w.paused = False
        for _ in range(sw.FPS * 8):
            w.step(1 / sw.FPS)
        self.assertNotEqual((w.x, w.y), where)              # carries on after Resume


class PushBroomAndDetail(unittest.TestCase):
    """1.18.111: "can he have a push broom style. and can you make him a little more hd?"."""

    def test_pushes_it_along_in_front(self):
        for p in [sw.walking(i / 10) for i in range(10)] + [sw.sweeping(i / 10) for i in range(10)]:
            hx, bottom, top, grip, far = sw._broom(p, 38)
            self.assertGreater(hx, 0.4 * 38)                     # in front of him
            self.assertGreater(bottom[0], top[0])                # handle up and back to him
            self.assertLess(top[1], grip[1])
            for shoulder, hand in (((0.03, -0.71), grip), ((-0.04, -0.72), far)):
                sx, sy = sw._from_upper(shoulder[0] * 38, shoulder[1] * 38, p, 38)
                self.assertLess(math.hypot(hand[0] - sx, hand[1] - sy), 2 * sw.ARM * 38 * 1.1)

    def test_push_strokes_and_dust_out_in_front(self):
        heads = [sw.sweeping(t / 20)["head"] for t in range(40)]
        self.assertGreater(max(heads) - min(heads), 0.2)         # out and back
        w = sw.Walker(384, random.Random(9))
        for _ in range(sw.FPS * 60):
            w.step(1 / sw.FPS)
            for x, y, age in w.puffs:
                if age == 0:
                    self.assertGreater((x - w.x) * w.face, 0.6 * w.h)    # ahead of the broom

    def test_paused_the_broom_stands_up(self):
        hx, bottom, top, grip, far = sw._broom(sw.leaning(0), 38)
        self.assertLess(abs(top[0] - bottom[0]), abs(top[1] - bottom[1]) * 0.3)

    def test_more_detail(self):
        pic = sw.draw(np.full((60, 90, 3), 210, np.uint8), 30, 52, 38, sw.walking(0.25))
        near = lambda colour, tol=40: (np.abs(pic.astype(int) - colour).sum(axis=2) < tol).any()
        for colour in (sw.SHIRT, sw.OVERALLS, sw.SKIN, sw.BRASS, sw.EYE_WHITE, sw.HANDLE,
                       sw.BRISTLES, sw.HAIR):
            self.assertTrue(near(np.array(colour)), colour)
        self.assertTrue((pic.sum(axis=2) < 200).any())           # a dark outline
        sleeve = sw.draw(np.full((60, 90, 3), 210, np.uint8), 30, 52, 38, sw.walking(0.25))
        self.assertTrue(np.array_equal(pic, sleeve))             # the same every time


class AnOutfitEachWeek(unittest.TestCase):
    """1.18.123 (the owner, 2026-11-17: "one a week i want his clothes colors to be changed",
    "all" of the choices, "they can be random choices from there", "so the outfits look
    different")."""
    MONDAY = datetime.date(2026, 11, 16)

    def weeks(self, n=300):
        return [sw.outfit(self.MONDAY + datetime.timedelta(weeks=i)) for i in range(n)]

    def test_the_same_all_week_and_new_on_monday(self):
        days = [sw.outfit(self.MONDAY + datetime.timedelta(days=i)) for i in range(7)]
        self.assertTrue(all(d == days[0] for d in days))
        self.assertNotEqual(sw.outfit(self.MONDAY + datetime.timedelta(days=7)), days[0])
        self.assertEqual(sw.outfit(datetime.date(2027, 3, 3)), sw.outfit(datetime.date(2027, 3, 3)))

    def test_every_part_changes_each_week(self):
        ws = self.weeks()
        for a, b in zip(ws, ws[1:]):
            for part in ("shirt", "pants", "shoes", "cap"):
                self.assertNotEqual(a[part], b[part], part)

    def test_all_her_choices_come_round(self):
        ws = self.weeks()
        for part, choices in (("shirt", sw.SHIRTS), ("pants", sw.PANTS),
                              ("shoes", sw.SHOES_ALL), ("cap", sw.CAPS)):
            self.assertEqual({w[part] for w in ws}, set(choices), part)
        self.assertEqual((len(sw.SHIRTS), len(sw.PANTS), len(sw.SHOES_ALL), len(sw.CAPS)),
                         (10, 10, 5, 7))

    def test_the_shirt_stands_out_from_the_pants(self):
        for w in self.weeks():
            self.assertGreaterEqual(math.dist(w["shirt"][1], w["pants"][1]), sw.SHIRT_APART)

    def test_quick_years_from_now(self):
        t = time.perf_counter()
        sw.outfit(datetime.date(2036, 11, 17))
        self.assertLess(time.perf_counter() - t, 0.2)

    def test_drawn_in_it(self):
        wear = {"shirt": sw.SHIRTS[1], "pants": sw.PANTS[2], "shoes": sw.SHOES_ALL[2],
                "cap": sw.CAPS[5]}
        pic = sw.draw(np.full((60, 90, 3), 30, np.uint8), 30, 52, 38, sw.walking(0.25), wear=wear)
        near = lambda colour, tol=40: (np.abs(pic.astype(int) - colour).sum(axis=2) < tol).any()
        for part in ("shirt", "pants", "shoes", "cap"):
            self.assertTrue(near(np.array(wear[part][1])), part)
        self.assertFalse(near(np.array(sw.CAP)))                 # not his red cap
        self.assertFalse(near(np.array(sw.OVERALLS)))            # nor his blue overalls

    def test_the_walker_wears_this_weeks(self):
        self.assertEqual(sw.Walker(384).wear, sw.outfit())


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

    def test_each_app_has_its_own_taskbar_name(self):
        # as CleanView 1.18.111: the taskbar shows the window's logo, not a blank file symbol
        for name, ident in (("CleanListen.pyw", "BookWorm824.CleanListen"), ("CleanRead.pyw", "BookWorm824.CleanRead")):
            text = (REPO / name).read_text(encoding="utf8")
            self.assertIn(f'TASKBAR_ID = "{ident}"', text, name)
            init = text[text.index("class App(tk.Tk):"):]
            self.assertLess(init.index("own_taskbar_id()"), init.index("super().__init__()"), name)

    def test_both_working_pages_ask_for_him_and_he_ships(self):
        for name in ("CleanListen.pyw", "CleanRead.pyw"):
            text = (REPO / name).read_text(encoding="utf8")
            self.assertIn("LOGO.WORKING_LOGO, sweeper=True", text, name)
        self.assertIn("sweeper.py", json.loads((REPO / "version.json").read_text())["files"])


if __name__ == "__main__":
    unittest.main()
