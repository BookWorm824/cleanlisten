"""Young kids and Kids go back to their standard ticks after every scan; Teens and Adults keep what was
changed (the owner, via CleanView 1.18.134: "can we make it so teen and adult remember their ticks, but
after every scan kids and young kids go back to defaault")."""
import filters as F


def test_kids_and_young_kids_go_back_teens_and_adults_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", tmp_path / "none.json")
    d = F.load()
    for p in ("young", "kids", "teens", "adults"):
        d["ticks"][p] = dict(F.PRESETS[p], drinking=False)
    d["profile"] = "kids"
    F.save(d)
    assert F.ticks(F.load(), "kids")["drinking"] is False

    class Panel:
        def __init__(self):
            self.got = None

        def fresh(self, d):
            self.got = d
    panel = Panel()
    F.fresh_young_ages(panel)
    after = F.load()
    assert F.ticks(after, "kids") == F.PRESETS["kids"] and F.ticks(after, "young") == F.PRESETS["young"]
    assert F.ticks(after, "teens")["drinking"] is False and F.ticks(after, "adults")["drinking"] is False
    assert panel.got is not None and "kids" not in panel.got["ticks"]
    assert after["profile"] == "kids"
