"""The logo on the working page is 50% bigger, 192 px instead of 128 (the owner, 2026-11-15: "lets make it
50% larger on screen"), shrunk smoothly from the icon's 256-px picture."""
import unittest

import logo


class LogoSize(unittest.TestCase):
    def test_working_logo_is_three_times_the_old_size(self):
        # 128, then 192 ("50% larger"), then 384 ("double from where it is"), the owner, 2026-11-15
        self.assertEqual(logo.WORKING_LOGO, 384)

    def test_enlarged_smoothly_past_the_icons_biggest_picture(self):
        for ico in ("icon.ico", "cleanread.ico"):
            png, w = logo.logo_png(ico, logo.WORKING_LOGO)
            self.assertEqual(w, 256, ico)              # the biggest there is
            big = logo._resize(logo._png_rgba(png), 384)
            self.assertEqual(big.shape, (384, 384, 4), ico)
            self.assertEqual(big[0, 0, 3], 0, ico)     # corners still see-through
            self.assertGreater(big[192, 192, 3], 250, ico)
            # smooth, not blocky: neighbouring columns aren't just repeats in threes
            row = big[192, :, 3].astype(int)
            self.assertTrue(any(row[i] != row[i + 1] and row[i] not in (0, 255) for i in range(383)), ico)
            # an edge pixel of the tile isn't darker than the tile (see-through weighting)
            solid = big[..., 3] == 255
            dark = big[..., :3].astype(int).sum(-1)[(big[..., 3] > 30) & ~solid].min()
            self.assertGreater(dark, 0.6 * big[..., :3].astype(int).sum(-1)[solid].min(), ico)

    def test_smooth_shrink_from_the_icons(self):
        for ico in ("icon.ico", "cleanread.ico"):
            png, w = logo.logo_png(ico, logo.WORKING_LOGO)
            self.assertEqual(w, 256, ico)
            big = logo._png_rgba(png)
            self.assertEqual(big.shape, (256, 256, 4), ico)
            small = logo._shrink(big, 192)
            self.assertEqual(small.shape, (192, 192, 4), ico)
            again = logo._png_rgba(logo._to_png(small))
            self.assertTrue((again == small).all(), ico)
            # the see-through corners stay see-through, the middle stays solid
            self.assertEqual(small[0, 0, 3], 0, ico)
            self.assertGreater(small[96, 96, 3], 200, ico)

    def test_tk_picture_is_384_wide(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display ({e})")
        try:
            root.withdraw()
            for ico in ("icon.ico", "cleanread.ico"):
                img = logo.logo_image(ico, logo.WORKING_LOGO)
                self.assertEqual((img.width(), img.height()), (384, 384), ico)
                img = logo.logo_image(ico, 128)        # the done page keeps its size
                self.assertEqual(img.width(), 128, ico)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
