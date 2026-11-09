"""The check says where the AI ran and how fast it read (the owner, 2026-11-09: find out what her
PC does before changing anything to make the AI faster). Only reported: nothing else changes."""
import io
import json
import time

import cleanread as R


class FakeAI:
    MODEL = "gemma3:4b"

    def __init__(self, ps):
        self.ps = ps

    def _api(self, path, payload=None, timeout=10):
        assert path == "/api/ps"
        if isinstance(self.ps, Exception):
            raise self.ps
        return io.BytesIO(json.dumps(self.ps).encode())


def model(size, vram, name="gemma3:4b"):
    return {"models": [{"name": name, "model": name, "size": size, "size_vram": vram}]}


def test_where_the_ai_ran():
    assert R.where_ai_ran(FakeAI(model(4e9, 4e9))) == "graphics"
    assert R.where_ai_ran(FakeAI(model(4e9, 0))) == "processor"
    assert R.where_ai_ran(FakeAI(model(4e9, 1e9))) == "part"
    assert R.where_ai_ran(FakeAI({"models": []})) is None
    assert R.where_ai_ran(FakeAI(ConnectionError("no Ollama"))) is None
    # another model is loaded too: the one CleanRead uses counts
    both = {"models": model(6e9, 0, "qwen3:8b")["models"] + model(4e9, 4e9)["models"]}
    assert R.where_ai_ran(FakeAI(both)) == "graphics"


def test_the_speed_line_in_plain_words():
    assert R.speed_note({"fresh": 400, "fresh_time": 80.0, "where": "graphics"}) == \
        " The AI ran on the graphics card and read about 300 sentences a minute."
    assert R.speed_note({"fresh": 400, "fresh_time": 1200.0, "where": "processor"}) == \
        " The AI ran on the processor only and read about 20 sentences a minute."
    assert R.speed_note({"fresh": 400, "fresh_time": 1200.0, "where": None}) == \
        " The AI read about 20 sentences a minute."
    assert R.speed_note({"fresh": 0, "fresh_time": 0.0, "where": None}) == \
        " It reused what it had already read in this book."
    assert R.speed_note({}) == ""


def test_the_check_and_find_notes_carry_it(tmp_path, monkeypatch):
    class AI(FakeAI):
        def ensure_ai(self, progress=None):
            pass

        def chat(self, prompt, schema=None, timeout=300):
            time.sleep(0.02)                # a measurable time, even on a busy PC
            return {"flags": []} if "numbered sentences" in prompt else {"fits": False}
    ai = AI(model(4e9, 0))
    monkeypatch.setattr(R, "_ai", lambda: ai)
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join("The wind blew across the fields. Anna fed the chickens." for _ in range(40)),
                 encoding="utf8")
    book = R.Book(str(p))
    res = R.scan(book, use_ai=True)
    assert "The AI ran on the processor only and read about" in res["ai_note"]
    again = R.scan(book, use_ai=True)
    assert again["ai_note"].endswith("It reused what it had already read in this book.")
    an = R.analyze(book, {"refs": True, "ai": True})
    assert "The AI ran on the processor only and read about" in an["ai_note"]
