"""CleanView is its own program now (BookWorm824/cleanview, installed with "Install CleanView.bat").

This file used to be an old copy of it that shipped with CleanListen. A "CleanView" icon that
CleanListen made still opens this file (through CleanListen's launcher), so it opens the real
CleanView instead and fixes the icon, or says how to get CleanView.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortcuts  # noqa: E402

MISSING = ("CleanView is its own program now, with its own icon.\n\n"
           "To get it, run “Install CleanView” from the CleanView setup folder. If you "
           "don't have that folder, ask the person who gave you CleanListen.")


def main():
    opened = shortcuts.open_cleanview()
    try:
        shortcuts.fix_cleanview_shortcut()
    except Exception:
        pass
    if not opened:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("CleanView", MISSING, parent=root)
        root.destroy()


if __name__ == "__main__":
    main()
