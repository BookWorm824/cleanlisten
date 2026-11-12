"""The filters in sections by topic, each with a box that ticks or unticks all of it and folding away
to one line, as CleanView 1.18.74 (the owner, 2026-11-12: "send a message to the other 3 programs to
create the redone tick boxes like the clean view format"; when designed: "a main box for each
category to tick all if wanted, but if only some of the subcategories are wanted just those can be
ticked. vid angel had a system like that", "maybe not as long", Medical its own section). Both
CleanListen's "Choose filters" window and CleanRead's page are built by filters.build_boxes()."""
import tkinter as tk

import pytest

import filters as F

SECTIONS = ["Bad language", "Sex and nudity", "Romance and relationships", "Violence", "Medical",
            "Attitude", "Smoking, drinking and drugs", "Faith, holidays and magic"]


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no screen to draw on ({ex})")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", tmp_path / "none.json")
    monkeypatch.setattr(F, "APP_DATA", tmp_path)
    return tmp_path


def panel(root):
    f = tk.Frame(root)
    f.pack()
    p = F.FilterPanel(f)
    root.update()
    return p


def test_every_filter_in_a_section_same_keys_as_before():
    assert [h for h, _, _ in F.SECTIONS] == SECTIONS
    keys = [k for _, _, items in F.SECTIONS for k, _, _ in items]
    assert len(keys) == len(set(keys)) == len(F.STANDARD) - 3     # the religion parts aside
    assert set(F.PRESETS["young"]) == set(F.STANDARD)
    assert [k for k, _, _ in F.SECTIONS[4][2]] == ["medical"]     # Medical on its own
    smoking = F.SECTIONS[SECTIONS.index("Smoking, drinking and drugs")]
    assert smoking[1] == 3 and all(cols == 1 for h, cols, _ in F.SECTIONS if h != smoking[0])


def test_counts_and_the_three_looks(root, saved):
    p = panel(root)
    imgs = F.head_images(root)
    master, count, tick_all, show = p.heads["Medical"]
    p.vars["medical"].set(False)
    assert count.cget("text") == "0 of 1 ticked" and str(master.cget("image")) == str(imgs["off"])
    p.vars["medical"].set(True)
    assert count.cget("text") == "1 of 1 ticked" and str(master.cget("image")) == str(imgs["on"])
    master, count, tick_all, show = p.heads["Violence"]
    p.vars["violence"].set(False)
    p.vars["gore"].set(True)
    assert str(master.cget("image")) == str(imgs["some"]) and "of 4 ticked" in count.cget("text")


def test_tick_all_goes_some_all_none_with_the_kissing_menus(root, saved):
    p = panel(root)
    master, count, tick_all, show = p.heads["Romance and relationships"]
    p.vars["kiss"].set("Keep")
    p.vars["flirt"].set(False)
    tick_all()                                      # some ticked: all
    assert p.vars["kiss"].get() == p.vars["kiss_ss"].get() == "Cut all kisses"
    assert all(p.vars[k].get() for k in ("sleeping", "unmarried", "relationships", "flirt"))
    assert count.cget("text") == "6 of 6 ticked"
    tick_all()                                      # all ticked: none
    assert p.vars["kiss"].get() == p.vars["kiss_ss"].get() == "Keep"
    assert not any(p.vars[k].get() for k in ("sleeping", "unmarried", "relationships", "flirt"))
    assert count.cget("text") == "0 of 6 ticked"
    t = F.ticks(F.load())                           # kept for the age, as always
    assert t["kiss"] == "keep" and not t["flirt"]


def test_religion_counts_with_its_parts(root, saved):
    p = panel(root)
    master, count, tick_all, show = p.heads["Faith, holidays and magic"]
    for k in ("religion", "holiday", "birthday", "darkmagic", "magic", "vampires"):
        p.vars[k].set(False)
    p.vars["religion"].set(True)
    for part, _ in F.RELIGION_PARTS:
        p.vars["religion_" + part].set(False)
    assert count.cget("text") == "0 of 6 ticked"    # religion with no part ticked takes nothing out
    tick_all()
    assert all(p.vars["religion_" + part].get() for part, _ in F.RELIGION_PARTS)
    assert count.cget("text") == "6 of 6 ticked"


def test_counts_follow_the_age_and_back_to_standard(root, saved):
    p = panel(root)
    p.profile.set("young")
    p._profile_changed()
    root.update()
    assert p.heads["Medical"][1].cget("text") == "1 of 1 ticked"
    p.profile.set("adults")
    p._profile_changed()
    root.update()
    assert p.heads["Medical"][1].cget("text") == "0 of 1 ticked"
    p.vars["medical"].set(True)
    p.standard()
    assert p.heads["Medical"][1].cget("text") == "0 of 1 ticked"


def test_folded_at_first_and_open_ones_remembered(root, saved):
    p = panel(root)
    head = p.heads["Violence"]
    assert not F.load().get("open_sections")                # all folded the first time
    # "Choose which…" opens it; it stays open next time (and in the other app)
    more = head[0].master.winfo_children()[-1]
    assert more.cget("text") == "Choose which…"
    root.deiconify()                    # a click only reaches a window that's showing
    root.update()
    more.event_generate("<Button-1>", x=2, y=2)
    root.update()
    assert more.cget("text") == "Hide" and F.load()["open_sections"] == ["Violence"]
    p2 = panel(root)
    assert p2.heads["Violence"][0].master.winfo_children()[-1].cget("text") == "Hide"
    assert p2.heads["Medical"][0].master.winfo_children()[-1].cget("text") == "Choose which…"


def test_cleanlistens_window_remembers_them_too(root, saved):
    d = F.load()
    d["open_sections"] = ["Medical"]
    w = F.FiltersWindow(root, d, lambda: None)
    root.update()
    assert w.heads["Medical"][0].master.winfo_children()[-1].cget("text") == "Hide"
    w.heads["Attitude"][3](True)
    w._done()
    assert d["open_sections"] == ["Attitude", "Medical"]
