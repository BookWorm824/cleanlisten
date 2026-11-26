"""The acting voice's card says, one size smaller than its description, that it takes much longer
(the owner, 2026-11-26: "it needs a note on the acting voice in 1 size smaller text that it
takes longer")."""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "ReadAloud.pyw").read_text(encoding="utf8")


def test_note_says_it_takes_longer():
    m = re.search(r'ACTING_NOTE = \((.*?)\)\n', SRC, re.S)
    assert m
    text = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    assert "longer" in text and "laptop" in text
    assert "Claude" not in text


def test_note_only_on_acting_and_one_size_smaller():
    block = SRC[SRC.index('if r == "acting":\n                # a note'):]
    block = block[:block.index("self.reader_cards[r] = card")]
    assert "text=ACTING_NOTE" in block
    assert "font=(FONT, 8)" in block            # the description under the name is 9
    assert "look.on_click(card.note" in block   # clicking the note picks the voice too
