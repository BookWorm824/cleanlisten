"""Your own names for the ages and your own saved presets (the owner, 2026-11-18: "I may want to change the
kids to my youngest nieces name, and teen to my oldest niece name")."""
import filters as F


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", tmp_path / "none.json")
    return F.load()


def test_renamed_ages_keep_their_rules(tmp_path, monkeypatch):
    d = setup(tmp_path, monkeypatch)
    d["names"] = {"kids": "Lily", "teens": "Emma"}
    F.save(d)
    d = F.load()
    assert F.profiles(d)[:4] == [("young", "Young kids"), ("kids", "Lily"), ("teens", "Emma"), ("adults", "Adults")]
    assert F.profile_name("kids", d) == "Lily"
    d["ticks"]["kids"] = dict(F.PRESETS["kids"], drinking=False)
    F.save(d)
    F.fresh_young_ages()                      # "Lily" is still Kids: back to standard after a scan
    assert F.ticks(F.load(), "kids") == F.PRESETS["kids"]


def test_a_saved_preset_keeps_its_ticks(tmp_path, monkeypatch):
    d = setup(tmp_path, monkeypatch)
    mine = dict(F.PRESETS["kids"], magic=False, holiday=False)
    key = F.add_preset(d, "Grandma's car", mine, "kids")
    d["profile"] = key
    F.save(d)
    d = F.load()
    assert d["profile"] == key and F.profile_name(key, d) == "Grandma's car"
    assert F.ticks(d)["magic"] is False and F.standard_of(d, key)["magic"] is False
    d["ticks"][key]["drinking"] = False
    F.save(d)
    F.fresh_young_ages()                      # a preset of your own isn't reset
    assert F.ticks(F.load(), key)["drinking"] is False
    d = F.load()
    F.remove_preset(d, key)
    F.save(d)
    d = F.load()
    assert d["profile"] == "adults" and key not in dict(F.profiles(d))
