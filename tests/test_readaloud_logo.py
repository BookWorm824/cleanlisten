"""ReadAloud's logo (the owner, 2026-11-15, as CleanView 1.18.107):
- bigger on the working and done pages ("50% larger", then "double from where it is"): logo.py's
  WORKING_LOGO, resized smoothly, as CleanListen's and CleanRead's;
- the slight 3D look ("E · All of it"): lit from above, keeping the yellow signal (the flat one is
  kept as tools/readaloud_flat.ico, made again with tools/icon_3d_colour.py)."""
import io
import sys
import tkinter as tk

import pytest

from conftest import REPO
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


def test_the_working_and_done_pages_show_it_bigger(window):
    win, app = window
    big = win.LOGO.WORKING_LOGO
    assert big >= 192
    room = tk.Toplevel(app)
    room.attributes("-alpha", 0.0)                  # see-through, as the window
    room.geometry(f"{big + 120}x{big + 120}+-3000+-3000")
    lbl = app._logo(room)
    _pump(app, 0.4)
    assert big <= lbl.winfo_reqwidth() < big + 8    # all of it when there's room
    room.geometry("300x300")
    _pump(app, 0.4)
    assert lbl.winfo_reqwidth() < 300               # smaller, not cut off, when there isn't
    room.destroy()
    src = (REPO / "ReadAloud.pyw").read_text("utf8")
    # no little cleaner in ReadAloud (the owner, 2026-11-25: "it doent clean just read. he needs gone")
    assert "sweeper=True)" not in src.replace("def _logo(self, parent, sweeper=False)", "")
    assert src.count("self._logo(p)") == 3                   # reading, done and converting pages


def test_the_little_cleaner_sweeps_it_while_reading_and_leans_while_paused(window):
    # CleanView's little cleaner (the owner, 2026-11-15: "Yes, all apps"), through logo.py
    win, app = window
    big = win.LOGO.WORKING_LOGO
    room = tk.Toplevel(app)
    room.attributes("-alpha", 0.0)                  # see-through, as the window
    room.geometry(f"{big + 120}x{big + 120}+-3000+-3000")
    cv = app._logo(room, sweeper=True)
    _pump(app, 0.6)
    assert isinstance(cv, tk.Canvas) and cv.sweeper.running
    assert big <= cv.winfo_reqwidth() < big + 8

    class FakeMaker:
        paused = False
    app.maker = FakeMaker()
    assert cv.sweeper.paused() is False
    app.maker.paused = True
    assert cv.sweeper.paused() is True              # he leans on his broom
    app.maker = None
    assert cv.sweeper.paused() is False
    room.geometry("300x300")
    _pump(app, 0.4)
    assert cv.winfo_reqwidth() < 300                # smaller with the room, he with it
    room.destroy()
    _pump(app, 0.2)
    assert not cv.sweeper.running                   # stops by himself when the page goes
    plain = tk.Toplevel(app)
    plain.attributes("-alpha", 0.0)
    plain.geometry(f"{big + 120}x{big + 120}+-3000+-3000")
    assert isinstance(app._logo(plain), tk.Label)    # the done page: just the logo
    plain.destroy()


def _pic(ico, size=256):
    np = pytest.importorskip("numpy")
    PIL = pytest.importorskip("PIL.Image")
    sys.path.insert(0, str(REPO / "tools"))
    import icon_3d_colour as I
    return np.asarray(PIL.open(io.BytesIO(I.read_ico(ico)[size])).convert("RGBA")).astype(float)


def test_the_icon_has_the_3d_look_and_keeps_its_yellow():
    np = pytest.importorskip("numpy")
    flat, new = _pic(REPO / "tools" / "readaloud_flat.ico"), _pic(REPO / "readaloud.ico")
    assert (new[..., 3] == flat[..., 3]).all()                  # the same shape
    tile = (np.linalg.norm(flat[..., :3] - [47, 111, 98], axis=-1) < 8) & (flat[..., 3] == 255)
    rows = np.nonzero(tile.any(axis=1))[0]
    top = new[rows[0] + 8][tile[rows[0] + 8]][:, :3].mean(0)
    bottom = new[rows[-1] - 8][tile[rows[-1] - 8]][:, :3].mean(0)
    assert top.sum() > bottom.sum() * 1.3                       # lit from above
    yellow = (np.linalg.norm(flat[..., :3] - [255, 214, 102], axis=-1) < 10) & (flat[..., 3] == 255)
    got = new[yellow][:, :3].mean(0)
    assert got[0] > 220 and got[1] > 180 and got[2] < 140        # still yellow, not grey
    assert sorted(__import__("icon_3d_colour").read_ico(REPO / "readaloud.ico")) == [16, 24, 32, 48, 64, 128, 256]


def test_the_sharp_512_logo_is_shipped_and_used():
    import json
    import logo
    assert logo.BIG_LOGOS["readaloud.ico"] == "readaloud_logo.png"
    assert "readaloud_logo.png" in json.loads((REPO / "version.json").read_text("utf8"))["files"]
    pic = _pic_png(REPO / "readaloud_logo.png")
    assert pic.shape == (512, 512, 4)
    yellow = (abs(pic[..., 0] - 255) < 40) & (abs(pic[..., 1] - 214) < 40) & (pic[..., 2] < 140)
    assert yellow.sum() > 2000                                  # the signal is still yellow


def _pic_png(path):
    np = pytest.importorskip("numpy")
    PIL = pytest.importorskip("PIL.Image")
    return np.asarray(PIL.open(path).convert("RGBA")).astype(float)
