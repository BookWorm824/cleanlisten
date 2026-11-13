"""The filters in sections by topic, as tiles (CleanView 1.18.77's look; the owner, 2026-11-13: "the ui
also feels clunky and dated, can you make it feel classy (all of them)", "B, step by step"; and when
the sections were designed: "a main box for each category to tick all if wanted, but if only some of
the subcategories are wanted just those can be ticked. vid angel had a system like that", Medical its
own section). Each tile has a switch for the whole section (on, off, or pale for some), "3 of 5 on"
or "Off", and "Choose ›", which opens its tick boxes under the tiles, one section at a time. Both
CleanListen and CleanRead show them on the page, built by filters.build_boxes()."""
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
    f = tk.Frame(root, bg="#F6F3EE")
    f.pack()
    p = F.FilterPanel(f)
    root.update()
    return p


def link_text(p, name):
    """The words of a tile's "Choose" link."""
    switch = p.heads[name][0]
    tile_body = switch.master.master
    low = [w for w in tile_body.winfo_children() if isinstance(w, tk.Frame)][-1]
    return [w for w in low.winfo_children() if hasattr(w, "label")][0].label.cget("text")


def test_every_filter_in_a_section_same_keys_as_before():
    assert [h for h, _, _ in F.SECTIONS] == SECTIONS
    keys = [k for _, _, items in F.SECTIONS for k, _, _ in items]
    assert len(keys) == len(set(keys)) == len(F.STANDARD) - 3     # the religion parts aside
    assert set(F.PRESETS["young"]) == set(F.STANDARD)
    assert [k for k, _, _ in F.SECTIONS[4][2]] == ["medical"]     # Medical on its own
    assert set(F.SECTION_ICONS) == set(SECTIONS)


def test_counts_and_the_three_looks(root, saved):
    p = panel(root)
    switch, count, tick_all, show = p.heads["Medical"]
    p.vars["medical"].set(False)
    assert count.cget("text") == "Off" and switch.state == "off"
    p.vars["medical"].set(True)
    assert count.cget("text") == "1 of 1 on" and switch.state == "on"
    switch, count, tick_all, show = p.heads["Violence"]
    p.vars["violence"].set(False)
    p.vars["gore"].set(True)
    assert switch.state == "some" and "of 4 on" in count.cget("text")


def test_the_switch_goes_some_all_none_with_the_kissing_choices(root, saved):
    p = panel(root)
    switch, count, tick_all, show = p.heads["Romance and relationships"]
    p.vars["kiss"].set("Keep")
    p.vars["flirt"].set(False)
    switch.click()                                  # some on: all
    assert p.vars["kiss"].get() == p.vars["kiss_ss"].get() == "Cut all kisses"
    assert all(p.vars[k].get() for k in ("sleeping", "unmarried", "relationships", "flirt"))
    assert count.cget("text") == "6 of 6 on" and switch.state == "on"
    switch.click()                                  # all on: none
    assert p.vars["kiss"].get() == p.vars["kiss_ss"].get() == "Keep"
    assert not any(p.vars[k].get() for k in ("sleeping", "unmarried", "relationships", "flirt"))
    assert count.cget("text") == "Off" and switch.state == "off"
    t = F.ticks(F.load())                           # kept for the age, as always
    assert t["kiss"] == "keep" and not t["flirt"]


def test_religion_counts_with_its_parts(root, saved):
    p = panel(root)
    switch, count, tick_all, show = p.heads["Faith, holidays and magic"]
    for k in ("religion", "holiday", "birthday", "darkmagic", "magic", "vampires"):
        p.vars[k].set(False)
    p.vars["religion"].set(True)
    for part, _ in F.RELIGION_PARTS:
        p.vars["religion_" + part].set(False)
    assert count.cget("text") == "Off"              # religion with no part on takes nothing out
    tick_all()
    assert all(p.vars["religion_" + part].get() for part, _ in F.RELIGION_PARTS)
    assert count.cget("text") == "6 of 6 on"


def test_counts_follow_the_age_and_reset_to_standard(root, saved):
    p = panel(root)
    p.profile.set("young")
    p._profile_changed()
    root.update()
    assert p.heads["Medical"][1].cget("text") == "1 of 1 on"
    p.profile.set("adults")
    p._profile_changed()
    root.update()
    assert p.heads["Medical"][1].cget("text") == "Off"
    p.vars["medical"].set(True)
    p.standard()
    assert p.heads["Medical"][1].cget("text") == "Off"


def test_one_section_open_at_a_time_and_remembered(root, saved):
    p = panel(root)
    assert not F.load().get("open_sections")                # all closed the first time
    assert link_text(p, "Violence") == "Choose ›"
    p.heads["Violence"][3](True)
    p._folded()
    assert link_text(p, "Violence") == "Hide ‹" and F.load()["open_sections"] == ["Violence"]
    p.heads["Medical"][3](True)                             # opening another closes the first
    p._folded()
    assert link_text(p, "Violence") == "Choose ›" and link_text(p, "Medical") == "Hide ‹"
    assert F.load()["open_sections"] == ["Medical"]
    p2 = panel(root)                                        # next time (and in the other app)
    assert link_text(p2, "Medical") == "Hide ‹" and link_text(p2, "Violence") == "Choose ›"


def test_both_apps_show_them_on_the_page():
    from conftest import REPO
    for app in ("CleanListen.pyw", "CleanRead.pyw"):
        src = (REPO / app).read_text(encoding="utf8")
        assert "F.FilterPanel(sp.pane(" in src and "CL.StepPage(" in src, app
