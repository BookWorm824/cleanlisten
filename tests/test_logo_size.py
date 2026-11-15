"""The logo on the working page is 50% bigger, 192 px instead of 128 (the owner, 2026-11-15: "lets make it
50% larger on screen"), shrunk smoothly from the icon's 256-px picture."""
import unittest

import logo


class LogoSize(unittest.TestCase):
    def test_working_logo_is_half_again_as_big(self):
        self.assertEqual(logo.WORKING_LOGO, 192)

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

    def test_tk_picture_is_192_wide(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display ({e})")
        try:
            root.withdraw()
            for ico in ("icon.ico", "cleanread.ico"):
                img = logo.logo_image(ico, logo.WORKING_LOGO)
                self.assertEqual((img.width(), img.height()), (192, 192), ico)
                img = logo.logo_image(ico, 128)        # the done page keeps its size
                self.assertEqual(img.width(), 128, ico)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
