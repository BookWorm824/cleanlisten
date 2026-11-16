"""ReadAloud's logo in the taskbar, as CleanView 1.18.111 (the owner, 2026-11-16, on another
computer: "the logo on the windows bar when it is open was a pic of a random file symbol thing").
ReadAloud's window has its own taskbar name, so Windows shows the logo the window carries rather
than the icon of the program it runs under."""
import os

import pytest

from conftest import REPO
from test_readaloud_look import window  # noqa: F401  (the window, see-through)


def process_taskbar_id():
    import ctypes
    from ctypes import wintypes
    out = wintypes.LPWSTR()
    shell = ctypes.windll.shell32
    if shell.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(out)) != 0:
        return None
    try:
        return out.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_its_own_taskbar_name_and_the_logo_on_the_window(window):
    import ctypes
    from ctypes import wintypes
    win, app = window
    assert win.TASKBAR_ID == "BookWorm824.ReadAloud"
    assert process_taskbar_id() == win.TASKBAR_ID          # set as the window was made
    user = ctypes.windll.user32
    user.SendMessageW.restype = wintypes.HANDLE
    user.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    app.update()
    hwnd = user.GetParent(app.winfo_id()) or app.winfo_id()
    assert user.SendMessageW(hwnd, 0x7F, 1, 96)            # WM_GETICON: the window carries a logo


def test_it_comes_before_the_window():
    src = (REPO / "ReadAloud.pyw").read_text("utf8")
    init = src[src.index("class App(tk.Tk):"):]
    assert init.index("own_taskbar_id()") < init.index("super().__init__()")
