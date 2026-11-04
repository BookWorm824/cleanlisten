"""Dropping a file from File Explorer on a window (dropfiles.py): a real window gets the same
message Windows sends for a drop."""
import os
import time

import pytest

import dropfiles

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows' own drag and drop")


def _drop(hwnd, paths):
    """Post a WM_DROPFILES with these paths, as Explorer does."""
    import ctypes
    from ctypes import wintypes
    k32, user32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    class DROPFILES(ctypes.Structure):
        _fields_ = [("pFiles", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]
    names = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    size = ctypes.sizeof(DROPFILES) + len(names)
    h = k32.GlobalAlloc(0x0042, size)               # GHND (moveable, zeroed)
    p = k32.GlobalLock(h)
    df = DROPFILES(ctypes.sizeof(DROPFILES), 10, 10, False, True)
    ctypes.memmove(p, ctypes.byref(df), ctypes.sizeof(DROPFILES))
    ctypes.memmove(p + ctypes.sizeof(DROPFILES), names, len(names))
    k32.GlobalUnlock(h)
    assert user32.PostMessageW(hwnd, dropfiles.WM_DROPFILES, h, 0)


def test_a_dropped_picture_reaches_the_window(tmp_path):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        zone = tk.Frame(root, width=200, height=80)
        zone.pack()
        got = []
        assert dropfiles.accept(zone, got.append)
        pic = tmp_path / "Grace Ford cover ü.jpg"
        pic.write_bytes(b"x")
        _drop(zone.winfo_id(), [str(pic), str(tmp_path / "second.png")])
        end = time.time() + 5
        while not got and time.time() < end:
            root.update()
            time.sleep(0.02)
        assert got == [[str(pic), str(tmp_path / "second.png")]]
        # the window still works as before
        zone.config(width=220)
        root.update()
    finally:
        root.destroy()
