"""Books in other languages, Spanish and French first (1.17.30, as CleanView 1.18.80 and 1.18.81; the
owner, 2026-11-13: "ask clean view about the language", "update"). English is untouched: its own
listening model and word lists. For another language the word lists are that language's own
(cvlang.py, CleanView's file), CleanListen listens with the model that hears other languages (got
once), the AI helpers are told what they're reading, and the other filters lean on them."""
import importlib.machinery
import importlib.util
import json
import types
import zipfile

import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
import cleanview_ai as ai
import cvlang
import filters as F
from conftest import REPO, words

EVERY = ["strong", "moderate", "mild", "minced", "deity", "sexual", "orientation", "rude"]
ENGLISH = "What the hell, you idiot. Damn it, he is gay and talks about sex."
SPANISH = ("El año pasado fuimos a la playa. ¡Cállate, pendejo! ¿Qué diablos haces? Ese maricón "
           "habla de sexo todo el día. ¡Mierda! Dios mío, qué vergüenza. Repartió un folleto y "
           "le hicieron rayos X. Recogió una concha en la arena.")
FRENCH = "Putain, quel idiot ! Oh mon Dieu. Il a mis une baguette sur la table et la chatte dort."


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def found(text, cats=EVERY, **kw):
    ws = words(text)
    return [(" ".join(ws[i:j]), cat) for i, j, cat in E.find_language(ws, cats, **kw)]


def test_english_is_exactly_as_it_was_before_and_after_another_language():
    before = found(ENGLISH, lead_in_too=True)
    assert ("what the hell", "mild") in before and ("idiot", "rude") in before
    assert ("gay", "orientation") in before and ("sex", "sexual") in before
    assert E.use_language("es") == "es"
    # English lists aren't run on a Spanish book ("gay" is a Spanish word too)
    assert found(ENGLISH) == [("gay", "orientation")]
    assert E.use_language("en") == "en"
    assert found(ENGLISH, lead_in_too=True) == before
    assert E.use_language("klingon") == "en" and E.use_language(None) == "en"
    assert E.mask("damn") == "d***" and E.lang_file("transcript.json") == "transcript.json"


def test_spanish_words_by_our_groups_and_look_alikes_left_alone():
    E.use_language("es")
    got = dict(found(SPANISH))
    assert got == {"callate": "rude", "pendejo": "moderate", "que diablos": "mild",
                   "maricon": "orientation", "sexo": "sexual", "mierda": "moderate",
                   "dios mio": "deity"}
    # año (a year), vergüenza, folleto, rayos X and concha (a shell) are everyday words
    assert not {"año", "ano", "verguenza", "folleto", "rayos", "concha"} & set(got)
    assert words("año coño")[0] == "año"                    # ñ is kept; accents come off
    # only the groups ticked
    assert dict(found(SPANISH, ["rude"])) == {"callate": "rude"}
    assert dict(found(SPANISH, ["sexual", "orientation"])) == {"maricon": "orientation",
                                                                 "sexo": "sexual"}
    # your own words, always, as "mine"
    assert ("folleto", "mine") in found(SPANISH, [], mine=[("folleto",)])


def test_french_words():
    E.use_language("fr")
    got = dict(found(FRENCH))
    assert got == {"putain": "strong", "idiot": "rude", "oh mon dieu": "deity"}
    assert words("l'idiot")[0] == "idiot"                   # the joined-on "l'" comes off


def test_only_a_listed_word_may_be_muted_alone_and_words_are_starred():
    E.use_language("es")
    assert E.listed_word("pendejo", ["moderate"]) and E.listed_word("¡Mierda!", ["moderate"])
    assert not E.listed_word("pendejo", ["rude"])           # its group isn't ticked
    assert not E.listed_word("Grafi", EVERY)                # a misheard name
    assert E.mask("mierda") == "m*****" and E.mask("coño") == "c***"
    assert E.lang_file("transcript.json") == "transcript_es.json"


def test_the_language_file_is_cleanviews_and_on_the_update_list():
    files = json.loads((REPO / "version.json").read_text())["files"]
    assert "cvlang.py" in files
    assert list(cvlang.LANGS)[0] == "en" and {"es", "fr"} <= set(cvlang.LANGS)
    src = (REPO / "cvlang.py").read_text(encoding="utf8")
    lines = src.splitlines()
    assert "import cvcore" not in lines and "import cleanlisten" not in lines


# ---------------------------------------------------------------------------
# CleanListen: listening and checking
# ---------------------------------------------------------------------------
def _listen(tmp_path, monkeypatch, text, name="transcript.json", **kw):
    src = tmp_path / "book.mp3"
    src.write_bytes(b"")
    t, out = 0.0, []
    for w in text.split():
        out.append({"t": w, "s": round(t, 2), "e": round(t + 0.25, 2)})
        t += 0.3
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / name).write_text(json.dumps({str(src.resolve()): out}))
    monkeypatch.setattr(E, "probe_duration", lambda p: t)
    monkeypatch.setattr(E, "snap_edges", lambda part, s, e, est=False: (s, e))
    E.analyze([str(src)], str(work), groups=("swearing", "mild", "deity", "sexual", "rude"),
              find_sex=False, log=lambda m: None, **kw)
    return json.loads((work / "analysis.json").read_text())


def test_a_spanish_audiobook_is_checked_with_the_spanish_lists(tmp_path, monkeypatch):
    st = _listen(tmp_path, monkeypatch, SPANISH, "transcript_es.json", language="es")
    assert st["language"] == "es"
    got = {m["word_raw"] if "word_raw" in m else m["word"]: m["cat"] for m in st["mutes"]}
    assert set(got.values()) == {"rude", "moderate", "mild", "sexual", "deity"}
    assert len(st["mutes"]) == 6                # (same-sex words weren't ticked)
    assert [m["word"] for m in st["mutes"] if m["cat"] == "moderate"][0].startswith("p")


def test_an_english_audiobook_never_touches_the_other_model(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "get_language_model", lambda *a, **k: pytest.fail("not for English"))
    st = _listen(tmp_path, monkeypatch, ENGLISH)
    assert st["language"] == "en" and len(st["mutes"]) >= 3


def test_another_language_is_listened_to_with_its_own_model_and_kept_apart(tmp_path, monkeypatch):
    src = tmp_path / "libro.mp3"
    src.write_bytes(b"")
    work = tmp_path / "work"
    work.mkdir()
    # it was checked as English before: those words aren't used for Spanish
    (work / "transcript.json").write_text(json.dumps({str(src.resolve()): [
        {"t": "damn", "s": 0.0, "e": 0.3}]}))
    asked, loaded = [], []
    monkeypatch.setattr(E, "get_language_model", lambda say, cancel, log: asked.append(1))
    monkeypatch.setattr(E, "load_recognizer", lambda d, threads=None: loaded.append(d) or "rec")
    monkeypatch.setattr(E, "transcribe", lambda p, rec, prog=None, cancel=None: [
        {"t": "¡Mierda!", "s": 0.0, "e": 0.4}, {"t": "Vamos.", "s": 0.5, "e": 0.9}])
    monkeypatch.setattr(E, "probe_duration", lambda p: 1.0)
    monkeypatch.setattr(E, "snap_edges", lambda part, s, e, est=False: (s, e))
    st = E.analyze([str(src)], str(work), groups=("swearing",), find_sex=False,
                   log=lambda m: None, language="es")
    assert asked == [1] and loaded == [cvlang.model_dir()]
    assert (work / "transcript_es.json").exists()
    assert [m["cat"] for m in st["mutes"]] == ["moderate"]
    assert json.loads((work / "transcript.json").read_text())[str(src.resolve())][0]["t"] == "damn"


def _model(folder):
    folder.mkdir(parents=True)
    for f in cvlang.MODEL_FILES:
        (folder / f).write_bytes(b"model " + f.encode())


def test_the_model_is_copied_from_cleanview_when_it_has_it(tmp_path, monkeypatch):
    ours = tmp_path / "ours" / "models" / cvlang.MODEL_NAME
    monkeypatch.setenv("CLEANVIEW_MULTI_MODEL", str(ours))
    monkeypatch.setattr(E, "CLEANVIEW_MODELS", tmp_path / "cleanview" / "models")
    _model(tmp_path / "cleanview" / "models" / cvlang.MODEL_NAME)
    monkeypatch.setattr(cvlang, "install_model", lambda *a, **k: pytest.fail("no download needed"))
    said = []
    assert not cvlang.model_ready()
    E.get_language_model(lambda f, m: said.append(m), None, lambda m: None)
    assert cvlang.model_ready() and (ours / "tokens.txt").read_bytes() == b"model tokens.txt"
    assert said == ["Copying the listening model for other languages from CleanView…"]
    E.get_language_model(lambda f, m: pytest.fail("already here"))       # nothing to do now


def test_the_model_is_downloaded_once_otherwise_and_cancel_stops_it(tmp_path, monkeypatch):
    ours = tmp_path / "ours" / "models" / cvlang.MODEL_NAME
    monkeypatch.setenv("CLEANVIEW_MULTI_MODEL", str(ours))
    monkeypatch.setattr(E, "CLEANVIEW_MODELS", tmp_path / "no cleanview here")

    def download(progress=None, url=None):
        progress(0.5, "Getting the listening model for other languages (one time): 245 of 490 MB…")
        _model(ours)
    monkeypatch.setattr(cvlang, "install_model", download)
    said = []
    with pytest.raises(KeyboardInterrupt):
        E.get_language_model(lambda f, m: said.append(m), lambda: True)
    assert said == [] and not cvlang.model_ready()
    E.get_language_model(lambda f, m: said.append(m), lambda: False)
    assert cvlang.model_ready() and "245 of 490 MB" in said[0]


def test_the_report_says_which_language(tmp_path, monkeypatch):
    src = (REPO / "cleanlisten.py").read_text(encoding="utf8")
    assert 'head.append(f"Cleaned as a {cvlang.name(lang)} audiobook' in src
    assert 'lang = use_language(st.get("language"))' in src       # saving uses the book's lists


# ---------------------------------------------------------------------------
# The AI helpers are told what they're reading
# ---------------------------------------------------------------------------
class Reply:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"message": {"content": json.dumps(self.d)}}).encode()


def test_the_ai_helper_on_this_pc_is_told_the_language(monkeypatch):
    sent = []
    monkeypatch.setattr(ai, "_api", lambda path, payload, timeout=300: (
        sent.append(payload["messages"][0]["content"]), Reply({"flags": []}))[1])
    ai.chat("Read this.")
    E.use_language("fr")
    ai.chat("Read this.")
    assert sent[0] == "Read this."
    assert sent[1].startswith("Read this. The dialogue is in French.") and "never translated" in sent[1]


def test_claude_chatgpt_and_gemini_are_told_the_language(monkeypatch):
    seen = []
    helper = types.SimpleNamespace(ask=lambda prompt, schema, system=None, **k: (
        seen.append(system), ({"ok": True}, "s1"))[1])
    monkeypatch.setattr(cc, "PROVIDER", "chatgpt")
    monkeypatch.setattr(cc, "_helper", lambda p: (helper, RuntimeError))
    cc.run("p", "You check a book.")
    E.use_language("es")
    cc.run("p", "You check a book.")
    assert seen[0] == "You check a book."
    assert seen[1].startswith("You check a book. The dialogue is in Spanish.")


# ---------------------------------------------------------------------------
# CleanRead
# ---------------------------------------------------------------------------
def test_a_spanish_ebook_is_read_with_the_spanish_lists_and_marked_out(tmp_path):
    p = tmp_path / "libro.txt"
    p.write_text("Capítulo 1\n\n" + SPANISH + "\n\nEl año nuevo llegó. ¡Coño!\n", encoding="utf8")
    book = R.Book(p, "es")
    assert book.language == "es" and cvlang.LANG == "es"
    opts = dict(F.PRESETS["young"])
    an = R.analyze(book, opts)
    cats = sorted(m["cat"] for m in an["mutes"])
    assert "strong" in cats and "moderate" in cats and "rude" in cats and "deity" in cats
    hit = {book.paras[m["para"]].text[m["a"]:m["b"]].lower() for m in an["mutes"]}
    assert {"coño", "pendejo", "mierda", "cállate"} <= hit and "año" not in hit
    out = tmp_path / "limpio.txt"
    R.write_clean(book, [], an["mutes"], out)
    clean = out.read_text(encoding="utf8")
    assert "pendejo" not in clean and "Mierda" not in clean and "Coño" not in clean
    assert "El año pasado fuimos a la playa." in clean and "vergüenza" in clean


def test_an_english_ebook_is_read_as_before_after_a_spanish_one(tmp_path):
    es = tmp_path / "libro.txt"
    es.write_text(SPANISH, encoding="utf8")
    R.Book(es, "es")
    en = tmp_path / "book.txt"
    en.write_text("Chapter 1\n\n" + ENGLISH + " The café was closed.\n", encoding="utf8")
    book = R.Book(en)
    assert book.language == "en" and cvlang.LANG == "en"
    an = R.analyze(book, dict(F.PRESETS["young"]))
    assert {m["cat"] for m in an["mutes"]} >= {"mild", "rude"}
    assert "cafe" in book.wn                      # English still takes accents off its own way


def _epub(path, body, n=40):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
        z.writestr("OEBPS/c.opf", '<package><manifest><item id="a" href="a.xhtml" '
                   'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/>'
                   '</spine></package>')
        z.writestr("OEBPS/a.xhtml", "<html><body>" + "".join(f"<p>{body}</p>" for _ in range(n))
                   + "</body></html>")


def test_the_language_is_guessed_from_the_books_own_words(tmp_path):
    es = ("El viejo se sentó en la silla y miró por la ventana, pero no vio a nadie en la calle. "
          "Los niños se habían ido con su madre para comprar una casa en el campo, como siempre.")
    fr = ("Le vieil homme était assis dans la cuisine et il regardait les enfants qui jouaient "
          "avec une balle sur la place. Elle ne voulait pas partir pour la ville, et je vous le dis.")
    en = ("The old man sat in the chair and looked out of the window, but he did not see anyone. "
          "She had gone to the house with her mother, and they were not back for a long time.")
    for name, text, want in (("es", es, "es"), ("fr", fr, "fr"), ("en", en, "en")):
        _epub(tmp_path / f"{name}.epub", text)
        assert E.guess_language(tmp_path / f"{name}.epub") == want
        (tmp_path / f"{name}.txt").write_text("\n\n".join([text] * 20), encoding="utf8")
        assert E.guess_language(tmp_path / f"{name}.txt") == want
    (tmp_path / "short.txt").write_text("Hola.", encoding="utf8")
    assert E.guess_language(tmp_path / "short.txt") is None           # too little to tell
    assert E.guess_language(tmp_path / "book.pdf") is None            # not looked into
    assert E.guess_language(tmp_path / "missing.epub") is None
    de = "Der alte Mann saß in der Küche und sah die Kinder, die mit dem Ball auf dem Platz spielten."
    (tmp_path / "de.txt").write_text("\n\n".join([de] * 20), encoding="utf8")
    assert E.guess_language(tmp_path / "de.txt") is None              # no lists for it


# ---------------------------------------------------------------------------
# The windows
# ---------------------------------------------------------------------------
class Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def test_cleanread_sets_the_language_from_the_book_and_reads_it_again(tmp_path, monkeypatch):
    m = load("lang_cleanread", "CleanRead.pyw")
    es = tmp_path / "libro.txt"
    es.write_text("\n\n".join([SPANISH] * 20), encoding="utf8")
    en = tmp_path / "book.txt"
    en.write_text("\n\n".join([ENGLISH + " The dog and the cat sat with her for the day."] * 20),
                  encoding="utf8")
    me = types.SimpleNamespace(book=None, book_path=None, outdir=None, language="en",
                               lang_var=Var("en"), steps_page=None, mode=Var("clean"), sent=[])
    me._refresh = lambda: None
    me._set_language = lambda code: m.App._set_language(me, code)
    me._send = lambda job, msg: me.sent.append(msg)
    monkeypatch.setattr(m.filedialog, "askopenfilename", lambda **k: str(es))
    m.App.pick_book(me)
    assert me.language == "es" and me.lang_var.get() == "es"
    assert m.App._step_summary(me, 1) == "libro.txt · Spanish"
    book = m.App._load_book(me, 1, str(es))
    assert book.language == "es"
    me.book = book
    me.lang_var.set("en")                       # she says it's English after all
    m.App._language_chosen(me)
    again = m.App._load_book(me, 1, str(es))
    assert again is not book and again.language == "en"
    # the next book is English again without her doing anything
    me.lang_var.set("es")
    m.App._language_chosen(me)
    monkeypatch.setattr(m.filedialog, "askopenfilename", lambda **k: str(en))
    m.App.pick_book(me)
    assert me.language == "en" and m.App._step_summary(me, 1) == "book.txt"


def test_cleanlisten_keeps_the_language_with_the_book_and_starts_new_books_in_english(tmp_path):
    m = load("lang_cleanlisten", "CleanListen.pyw")
    es = tmp_path / "libro.txt"
    es.write_text("\n\n".join([SPANISH] * 20), encoding="utf8")
    me = types.SimpleNamespace(saved_opts={}, lang_var=Var("en"), steps_page=None, ebook=None,
                               audio=["a.mp3"])
    me._set_language = lambda code: m.App._set_language(me, code)
    me.lang_var.set("fr")
    m.App._language_chosen(me)
    assert me.saved_opts["language"] == "fr"
    assert m.App._step_summary(me, 1) == "1 file chosen · French"
    m.App._language_of_new_book(me)             # another book: English unless its ebook says so
    assert me.saved_opts["language"] == "en" and me.lang_var.get() == "en"
    assert m.App._step_summary(me, 1) == "1 file chosen"
    me.ebook = str(es)
    m.App._language_of_new_book(me)
    assert me.saved_opts["language"] == "es" and me.lang_var.get() == "es"
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert 'if lang != "en":                # English is checked exactly as it always was' in src
    assert 'self.filter_args["language"] = lang' in src
    assert 'engine.use_language((self.analysis or {}).get("language"))' in src


@pytest.mark.parametrize("app, words_", [
    ("CleanListen.pyw", "Language the book is read in"),
    ("CleanRead.pyw", "Language the book is written in")])
def test_both_start_pages_have_the_choice(app, words_):
    src = (REPO / app).read_text(encoding="utf8")
    assert words_ in src and "cvlang.LANGS.items()" in src and "look.Segmented(b, list(" in src
