"""Text size (as CleanView's, the owner 2026-11-14) and the kissing buttons saying "Cut"
(as CleanView 1.18.103)."""
import tkinter as tk

import pytest

import filters as F


def test_sizes_and_wrapping():
    assert list(F.TEXT_SIZES) == ["Normal", "Larger", "Largest"]
    assert F.text_size({}) == "Normal"
    assert F.text_size({"text_size": "Huge"}) == "Normal"
    assert F.text_size({"text_size": "Largest"}) == "Largest"


def test_apply_scales_tk_and_wrap_widths():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        root.withdraw()
        base = float(root.tk.call("tk", "scaling"))
        F.apply_text_size(root, "Largest", base)
        assert float(root.tk.call("tk", "scaling")) == pytest.approx(base * 1.3, rel=0.01)
        assert F.wrap(500) == 650
        F.apply_text_size(root, "Normal", base)
        assert float(root.tk.call("tk", "scaling")) == pytest.approx(base, rel=0.01)
        assert F.wrap(500) == 500
    finally:
        F.apply_text_size(root, "Normal", base)
        root.destroy()


def test_kissing_buttons_say_cut():
    assert [F.KISS_SHORT[full] for _, full in F.KISS_LEVELS] == ["Keep", "Cut passionate", "Cut all kisses"]
    assert [k for k, _ in F.KISS_LEVELS] == ["keep", "passionate", "all"]     # what's saved is as before
