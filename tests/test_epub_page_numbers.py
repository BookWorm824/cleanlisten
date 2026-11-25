"""An epub's list of the printed book's page numbers ("8", "9", "10"... in the table of contents'
pageList) isn't a list of chapters (the owner, Truth Be Told, 2026-11-25: 'when it finds something
it say in"50". i think that means page fifty. but it just has a number but doesn't say page').
Now a find says "Chapter 2, page 3", and Read-aloud's chapters are the real ones, in order."""
import zipfile

import cleanread as R

CONTAINER = """<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
OPF = """<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Pages</dc:title></metadata>
<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine></package>"""


def nav(n, label, src):
    return (f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{label}</text></navLabel>'
            f'<content src="{src}"/></navPoint>')


def page(n, src):
    return (f'<pageTarget id="p{n}" value="{n}" type="normal"><navLabel><text>{n}</text></navLabel>'
            f'<content src="{src}"/></pageTarget>')


NCX = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
       '<navMap>' + nav(1, "Chapter 1", "c1.xhtml") + nav(2, "Chapter 2", "c2.xhtml") + '</navMap>'
       '<pageList>' + page(1, "c1.xhtml#p1") + page(2, "c1.xhtml#p2") + page(3, "c2.xhtml#p3") +
       page(4, "c2.xhtml#p4") + '</pageList></ncx>')


def chapter(title, a, b):
    return (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><body>'
            f'<h1>{title}</h1><p><span id="p{a}"/>The rain fell on page {a}.</p>'
            f'<p>Anna fed the chickens before school.</p>'
            f'<p><span id="p{b}"/>The bus was late on page {b}.</p><p>They ate soup for lunch.</p></body></html>')


def make(tmp_path):
    p = tmp_path / "pages.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF)
        z.writestr("toc.ncx", NCX)
        z.writestr("c1.xhtml", chapter("Chapter 1", 1, 2))
        z.writestr("c2.xhtml", chapter("Chapter 2", 3, 4))
    return p


def para_with(book, text):
    return next(q for q, p in enumerate(book.paras) if text in p.text)


def test_a_find_says_the_chapter_and_the_page(tmp_path):
    book = R.Book(str(make(tmp_path)))
    where = book.where(para_with(book, "page 3"))
    assert where.startswith("Chapter 2, page 3 · ") and "In “" not in where
    assert book.chapter_of_para(para_with(book, "page 4")) == "Chapter 2"
    assert book.where(para_with(book, "page 2")).startswith("Chapter 1, page 2 · ")


def test_read_aloud_has_the_real_chapters_in_order(tmp_path):
    import readaloud as RA
    got = RA.load_book(str(make(tmp_path)))
    chapters = got["chapters"] if isinstance(got, dict) else got
    assert [c["title"] for c in chapters] == ["Chapter 1", "Chapter 2"]
    text = " ".join(t for c in chapters for _, t in c["paras"])
    assert text.index("page 1") < text.index("page 2") < text.index("page 3") < text.index("page 4")


def test_a_book_without_page_numbers_is_as_before(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Chapter 1\n\nThe rain fell.\n\nChapter 2\n\nThe bus was late.", encoding="utf8")
    book = R.Book(str(p))
    assert book.where(para_with(book, "bus")).startswith("Chapter 2 · ")
