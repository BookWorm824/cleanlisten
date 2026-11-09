"""CleanRead's big main button (Start cleaning / Start checking, Save clean copy, Clean another
book) is the same green as the logo and the green text (the owner, 2026-11-09: "the start cleaning
button is a different green than the main logo and other green text")."""
import importlib.machinery
import importlib.util
import io
from collections import Counter

from conftest import REPO


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def test_main_button_is_the_logo_green():
    cr = load("cr_same_green", "CleanRead.pyw")
    assert cr.GO == cr.ACCENT and cr.GO_DK == cr.ACCENT_DK


def test_the_logo_is_that_green_too():
    PIL = __import__("pytest").importorskip("PIL.Image")
    import logo
    png, _ = logo.logo_png("cleanread.ico", 128)
    im = PIL.open(io.BytesIO(png)).convert("RGBA")
    colours = Counter("#%02X%02X%02X" % p[:3] for p in getattr(im, "get_flattened_data", im.getdata)() if p[3] > 200)
    cr = load("cr_same_green2", "CleanRead.pyw")
    assert colours.most_common(1)[0][0] == cr.ACCENT.upper()


def test_cleanlisten_main_button_matches_too():
    # "i want to stay consistent" (the owner, 2026-11-09): CleanListen's main button is the same
    # green; a ready book in its list keeps the bright green so it looks different from a done one
    cl = load("cl_same_green", "CleanListen.pyw")
    cr = load("cr_same_green3", "CleanRead.pyw")
    assert cl.GO == cl.ACCENT == cr.GO and cl.GO_DK == cr.GO_DK and cl.GO_OFF == cr.GO_OFF
    assert cl.READY_GREEN != cl.ACCENT_DK
