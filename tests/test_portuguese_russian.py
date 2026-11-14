"""Portuguese and Russian in CleanListen and CleanRead (1.17.36, as CleanView 1.18.88; the owner,
2026-11-13: asked about the book apps, "both"). Russian is the first language in another alphabet,
so the places that only knew English letters were fixed: CleanRead's word pattern (a Russian book
had no words at all) and the keys that remember a line (every Russian line was an empty one)."""
import json
import zipfile

import pytest

import cleanlisten as E
import cleanlisten_learn as L
import cleanread as R
import cvlang
import filters as F
from conftest import words

PORTUGUESE = ("A chuva caiu a noite toda. Tomás gritou: merda, que porra foi essa? O irmão respondeu: "
              "cala a boca, seu idiota. Meu Deus, disse a avó, aquele filho da puta levou o dinheiro. "
              "Ele comprou pão e foi para casa.")
RUSSIAN = ("Дождь шёл всю ночь над старой фермой. Фома крикнул: блядь, что это было? Брат ответил: "
           "заткнись, ты идиот. Боже мой, сказала бабушка, эта сука забрала все деньги. Потом они "
           "поели горячий суп.")
EVERY = ["strong", "moderate", "mild", "minced", "deity", "sexual", "orientation", "rude"]


def found(text, cats=EVERY):
    ws = words(text)
    return [(" ".join(ws[i:j]), cat) for i, j, cat in E.find_language(ws, cats)]


def test_both_are_on_the_list_and_in_the_drop_down():
    assert list(cvlang.LANGS) == ["en", "es", "fr", "pt", "ru"]
    assert cvlang.LANGS["pt"] == "Portuguese" and cvlang.LANGS["ru"] == "Russian"


def test_portuguese_words_by_our_groups():
    E.use_language("pt")
    got = dict(found(PORTUGUESE))
    assert got["merda"] == "moderate" and got["idiota"] == "rude" and got["meu deus"] == "deity"
    assert got["puta"] == "strong" and "porra" in got
    assert words("Foda-se, cala-te.") == ["fodase", "calate"]          # a hyphen joins
    assert not {"chuva", "pao", "casa", "dinheiro"} & set(got)


def test_russian_words_by_our_groups():
    E.use_language("ru")
    got = dict(found(RUSSIAN))
    assert got["блядь"] == "strong" and got["идиот"] == "rude" and got["сука"] == "moderate"
    assert got["заткнись"] == "rude" and got["боже мой"] == "deity"
    assert words("Ёлки шёл") == ["елки", "шел"]                         # ё is read as е
    assert E.mask("блядь") == "б****"
    assert E.listed_word("сука", ["moderate"]) and not E.listed_word("бабушка", EVERY)


def test_english_is_as_it_was():
    assert found("What the hell, you idiot.") == [("hell", "mild"), ("idiot", "rude")]
    assert found(RUSSIAN) == []
    assert R.item_key("Damn it, Tom.") == "damn it tom" and L.norm("Damn it, Tom.") == "damn it tom"


def test_cleanread_sees_russian_words_at_all():
    assert R.WORD_RE.findall("Блядь, ты идиот! Ёлки-палки.") == ["Блядь", "ты", "идиот", "Ёлки-палки"]
    # English words, bleeps and grawlixes as before
    assert R.WORD_RE.findall('He said "damn", f***ing #@$%.') == ["He", "said", "damn", "f***ing", "#@$%"]


def test_a_russian_line_is_remembered_as_itself_not_as_nothing():
    E.use_language("ru")
    assert R.item_key("Блядь, ты идиот!") == "блядь ты идиот"
    assert L.norm("Заткнись, ты идиот!") == "заткнись ты идиот"
    assert R.item_key("Шёл дождь.") != R.item_key("Брат ответил.")
    E.use_language("en")
    assert R.item_key("Блядь, ты идиот!") == ""        # (English keeps only a-z, as it always did)


def test_a_russian_ebook_through_cleanread(tmp_path):
    p = tmp_path / "kniga.txt"
    p.write_text("Глава 1\n\n" + RUSSIAN + "\n", encoding="utf8")
    book = R.Book(p, "ru")
    assert len(book.words) > 30 and "блядь" in book.wn
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = {book.paras[m["para"]].text[m["a"]:m["b"]].lower() for m in an["mutes"]}
    assert {"блядь", "идиот", "сука", "заткнись"} <= hit and "бабушка" not in hit
    out = tmp_path / "chistaya.txt"
    R.write_clean(book, [], an["mutes"], out)
    clean = out.read_text(encoding="utf8")
    assert "блядь" not in clean and "сука" not in clean
    assert "Дождь шёл всю ночь над старой фермой." in clean and "горячий суп" in clean


def test_a_portuguese_ebook_through_cleanread(tmp_path):
    p = tmp_path / "livro.txt"
    p.write_text("Capítulo 1\n\n" + PORTUGUESE + "\n", encoding="utf8")
    book = R.Book(p, "pt")
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = {book.paras[m["para"]].text[m["a"]:m["b"]].lower() for m in an["mutes"]}
    assert {"merda", "idiota", "puta"} <= hit and "pão" not in hit


def test_a_portuguese_audiobook_is_checked_with_its_lists(tmp_path, monkeypatch):
    src = tmp_path / "livro.mp3"
    src.write_bytes(b"")
    t, out = 0.0, []
    for w in PORTUGUESE.split():
        out.append({"t": w, "s": round(t, 2), "e": round(t + 0.25, 2)})
        t += 0.3
    work = tmp_path / "work"
    work.mkdir()
    (work / "transcript_pt.json").write_text(json.dumps({str(src.resolve()): out}))
    monkeypatch.setattr(E, "probe_duration", lambda p: t)
    monkeypatch.setattr(E, "snap_edges", lambda part, s, e, est=False: (s, e))
    st = E.analyze([str(src)], str(work), groups=("swearing", "mild", "deity", "rude"),
                   find_sex=False, log=lambda m: None, language="pt")
    assert st["language"] == "pt" and len(st["mutes"]) >= 5


def _epub(path, body, n=40):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
        z.writestr("OEBPS/c.opf", '<package><manifest><item id="a" href="a.xhtml" '
                   'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/>'
                   '</spine></package>')
        z.writestr("OEBPS/a.xhtml", "<html><body>" + "".join(f"<p>{body}</p>" for _ in range(n))
                   + "</body></html>")


@pytest.mark.parametrize("lang, text", [
    ("pt", "O velho sentou-se na cadeira e olhou pela janela, mas não viu ninguém na rua. As crianças "
           "tinham ido com a mãe para comprar uma casa no campo, como sempre, e ele ficou sozinho."),
    ("ru", "Старик сел на стул и посмотрел в окно, но никого не увидел на улице. Дети ушли с матерью "
           "покупать дом в деревне, как всегда, и он остался один."),
    ("es", "El viejo se sentó en la silla y miró por la ventana, pero no vio a nadie en la calle. Los "
           "niños se habían ido con su madre para comprar una casa en el campo, como siempre.")])
def test_the_language_is_guessed_from_the_books_own_words(tmp_path, lang, text):
    _epub(tmp_path / "book.epub", text)
    assert E.guess_language(tmp_path / "book.epub") == lang
    (tmp_path / "book.txt").write_text("\n\n".join([text] * 20), encoding="utf8")
    assert E.guess_language(tmp_path / "book.txt") == lang


def test_a_language_with_no_lists_is_left_for_her_to_choose(tmp_path):
    uk = "Старий сів на стілець і подивився у вікно, але нікого не побачив на вулиці. Діти пішли з матір'ю."
    (tmp_path / "uk.txt").write_text("\n\n".join([uk] * 20), encoding="utf8")
    assert E.guess_language(tmp_path / "uk.txt") is None                 # Ukrainian
