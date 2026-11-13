"""Books in other languages (the owner, 2026-11-13, after CleanView's "Language spoken in the
video": "yes. language capabilty and the new drop down menu"): the book's language is told from its
own words, read by the Quick voice with that language's voices and pronunciations; and the chosen
reader's voice choices open right under its own row of reader cards."""
import importlib.util
import os
import time

import pytest

from conftest import REPO

os.environ["READALOUD_FAKE_VOICE"] = "1"
import readaloud as R  # noqa: E402

SPANISH = ("Era tarde cuando por fin llegó la carta. La leí dos veces, de pie junto a la ventana, y "
           "luego me senté y me reí, porque después de todos esos años había sido tan simple. ¿Qué "
           "más podía hacer? Él no lo sabía, y yo tampoco.")
FRENCH = ("Il était tard quand la lettre est enfin arrivée. Je l'ai lue deux fois, debout près de la "
          "fenêtre, puis je me suis assise et j'ai ri, parce que après toutes ces années, cela avait "
          "été si simple. Elle ne savait pas pourquoi.")


def _ch(text):
    return [{"paras": [["p", text]] * 3}]


def test_the_language_is_told_from_the_books_own_words():
    assert R.guess_language(_ch(SPANISH)) == "es"
    assert R.guess_language(_ch(FRENCH)) == "fr"
    assert R.guess_language(_ch("It was late when the letter came, and she read it twice by the "
                                "window before she sat down and laughed at all of it. " * 3)) == "en"
    assert R.guess_language(_ch("Hola.")) == "en"           # too little to tell


def test_each_language_has_its_own_voices():
    assert R.voices_for("en") == R.VOICES
    assert [v[0] for v in R.voices_for("es")] == ["ef_dora", "em_alex"]
    assert [v[0] for v in R.voices_for("pt")] == ["pf_dora", "pm_alex"]
    assert all(R.voice_language(v[0]) == lang for lang in R.LANGS for v in R.voices_for(lang))
    for v in R.OTHER_VOICES:                                 # the model's own speaker numbers
        assert R.VOICE[v[0]] == v


def test_spanish_sentences_and_quotes():
    assert R.sentences("Llegó tarde. ¿Qué hora es? Él no sabía.") == ["Llegó tarde.", "¿Qué hora es?",
                                                                      "Él no sabía."]
    assert R.speakable("« Bonjour », dit-il.") == '"Bonjour", dit-il.'


def test_a_spanish_job_reads_with_the_spanish_voice(tmp_path, monkeypatch):
    from test_readaloud import make_epub
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    story = [("Capítulo uno", [SPANISH] * 4), ("Capítulo dos", [SPANISH] * 4)]
    b = R.load_book(make_epub(tmp_path / "libro.epub", story))
    assert b["language"] == "es"
    seen = []
    real = R.voice_engine
    monkeypatch.setattr(R, "voice_engine", lambda accent="us", *a, **k: (seen.append(accent), real(accent, *a, **k))[1])
    jd = R.start_job(b, "ef_dora", 1.0, [0], tmp_path / "out.m4b", {"language": "es"})
    R.speak_chapter(jd, 0)
    assert seen and set(seen) == {"es"}
    assert R.voice_label({"voice": "ef_dora"}) == "Dora voice"


@pytest.fixture
def window(tmp_path, monkeypatch):
    import filters as F
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    spec = importlib.util.spec_from_file_location("ReadAloudLang", REPO / "ReadAloud.pyw")
    win = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(win)
    monkeypatch.setattr(win, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(win, "APP_DATA", tmp_path)
    monkeypatch.setattr(win.engine, "JOBS", tmp_path / "jobs")
    w = win.freezes.Watch
    monkeypatch.setattr(win.freezes, "Watch", lambda root, app, folder, prefix="": w(root, app, tmp_path, prefix))
    app = win.App()
    app.settings = {"reader": "acting"}
    app.show_setup()
    yield win, app
    app.destroy()


def _pump(app, sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        app.update()


def test_the_voices_open_under_the_chosen_readers_own_row(window):
    win, app = window
    app.steps_page.go(2)
    _pump(app)
    row = lambda w: int(w.grid_info()["row"])
    assert app._reader() == "acting" and row(app.reader_detail) == 1      # under the first row
    app.reader_var.set("kokoro")                                          # the Quick voice: row 2
    _pump(app)
    assert row(app.reader_cards["kokoro"]) == 2 and row(app.reader_detail) == 3
    app.reader_var.set("steady")
    _pump(app)
    assert row(app.reader_detail) == 1


def test_a_spanish_book_uses_the_quick_voice_and_no_director(window, tmp_path):
    win, app = window
    from test_readaloud import make_epub
    story = [("Capítulo uno", [SPANISH] * 4), ("Capítulo dos", [SPANISH] * 4)]
    b = win.engine.load_book(make_epub(tmp_path / "libro.epub", story))
    app.q.put(("book", str(tmp_path / "libro.epub"), b, None))
    _pump(app, 0.6)
    assert app._lang() == "es" and app._reader() == "kokoro"
    assert not app.reader_cards["acting"].winfo_ismapped() or not app.reader_cards["acting"].grid_info()
    assert app.voice_box.cget("values")[0].startswith("Dora")
    assert app._voice_id() == "ef_dora"
    said = [r[3].cget("text") for r in app.steps_page.rows]
    assert said[1] == "Quick, in Spanish" and said[2] == "English books only"
    assert not app.director_more.winfo_ismapped() and not app.director_card.winfo_ismapped()
    assert app.settings["reader"] == "acting"          # her choice for English books is kept
    jobs = []
    monkey = win.engine.start_job
    win.engine.start_job = lambda *a: (jobs.append(a), monkey(*a))[1]
    app.run_job = lambda *a: None
    try:
        app.start()
    finally:
        win.engine.start_job = monkey
    book, voice, speed, ids, out, extra = jobs[0]
    assert voice == "ef_dora" and extra.get("language") == "es" and "director" not in extra
    # back to English: the reader chosen for English books, and the director again
    app.lang_var.set("en")
    app._lang_changed()
    _pump(app)
    assert app._reader() == "acting" and app.reader_cards["acting"].grid_info()
    assert app.steps_page.rows[2][3].cget("text") != "English books only"
    app.steps_page.go(3)
    _pump(app)
    assert app.director_card.winfo_ismapped() and not app.director_lang.winfo_ismapped()
