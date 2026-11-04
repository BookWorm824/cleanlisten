"""Dropping files from File Explorer onto a tkinter widget, with Windows' own drag and drop
(WM_DROPFILES), so nothing extra needs installing (the updater can't install packages).

    dropfiles.accept(widget, on_drop)     # on_drop(list_of_paths), called on the window's thread

Lauren, 2026-11-04: "have where I can drag and drop the cover photo".
"""
import os

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

_api = None


def _windows():
    """The Windows functions, set up once (None off Windows)."""
    global _api
    if _api is None and os.name == "nt":
        import ctypes
        from ctypes import wintypes
        user32, shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("shell32")
        lresult = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM)
        set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        set_long.restype = ctypes.c_void_p
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = lresult
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p,
                                           wintypes.UINT]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        _api = {"ctypes": ctypes, "user32": user32, "shell32": shell32, "proc_type": proc_type,
                "set_long": set_long}
    return _api


def dropped_files(hdrop):
    """The paths in a WM_DROPFILES message's handle."""
    api = _windows()
    ctypes, shell32 = api["ctypes"], api["shell32"]
    files = []
    for i in range(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)):
        size = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
        buf = ctypes.create_unicode_buffer(size)
        shell32.DragQueryFileW(hdrop, i, buf, size)
        files.append(buf.value)
    return files


def accept(widget, on_drop):
    """Let files be dropped on this widget (and its children, each needs its own call). Returns
    False where it can't (not Windows, or Windows said no): the Choose button still works."""
    api = _windows()
    if not api:
        return False
    try:
        widget.update_idletasks()          # its window exists
        hwnd = widget.winfo_id()
        old, pending = [], []

        # Runs inside Tk's own handling of the message, so it must not call tkinter (that waits
        # for a lock Tk is holding): it only notes the files, and poll() hands them over.
        def proc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                try:
                    pending.append(dropped_files(wp))
                except Exception:
                    pass
                finally:
                    api["shell32"].DragFinish(wp)
                return 0
            return api["user32"].CallWindowProcW(old[0], h, msg, wp, lp)

        def poll():
            try:
                if not widget.winfo_exists():
                    return
            except Exception:
                return
            while pending:
                files = pending.pop(0)
                if files:
                    try:
                        on_drop(files)
                    except Exception:
                        pass
            widget.after(150, poll)

        callback = api["proc_type"](proc)
        old.append(api["set_long"](hwnd, GWLP_WNDPROC,
                                   api["ctypes"].cast(callback, api["ctypes"].c_void_p)))
        if not old[0]:
            return False
        widget._drop_callback = callback   # kept alive as long as the widget
        api["shell32"].DragAcceptFiles(hwnd, True)
        poll()
        return True
    except Exception:
        return False
