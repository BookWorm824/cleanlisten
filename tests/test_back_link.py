"""CleanRead's working screen has a Back button by Pause and Cancel (the owner, 2026-11-25: "it
should have a back button", "put it down by pause cancel"). It goes back to the start page, the
same as Cancel."""
import inspect

from test_cancel_at_once import load


def test_the_working_screen_has_a_back_button_by_pause_and_cancel():
    cr = load("cr_back_button", "CleanRead.pyw")
    src = inspect.getsource(cr.App.show_working)
    assert 'self.back_btn = ttk.Button(self.footer, text="\u2190 Back"' in src
    assert "command=self.cancel)" in src.split("self.back_btn")[1]
    assert src.index("self.cancel_btn") < src.index("self.pause_btn") < src.index("self.back_btn")
