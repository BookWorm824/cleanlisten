"""A heads-up when a book probably won't be enjoyable cleaned (the owner, 2026-11-18: "if I uploaded the book
twilight, CleanListen would clean up the book, but the whole book is about Vampires - thats the main story
line - CleanListen would still give the option to continue with the save but have a heads up flag")."""
import cleanlisten as E


def test_a_topic_all_through_the_book():
    hu = E.heads_up([("vampires", i / 35, 0.0005) for i in range(35)], hours=12)
    assert [h["kind"] for h in hu] == ["vampires"] and "Vampires & werewolves run all through" in hu[0]["text"]


def test_brief_mentions_and_one_part_are_not_flagged():
    assert E.heads_up([("religion", i / 181, 0.0002) for i in range(181)], hours=12) == []   # brief, spread
    assert E.heads_up([("violence", 0.5, 0.002)] * 20, hours=12) == []                        # one part, 4%
    assert E.heads_up([("vampires", i / 10, 0.0005) for i in range(10)], hours=12) == []      # a few mentions


def test_a_long_share_or_lots_of_bad_language():
    assert E.heads_up([("sex", 0.3, 0.06), ("sex", 0.6, 0.06)], hours=10)[0]["kind"] == "sex"   # 12% of it
    hu = E.heads_up([], hours=8, words=400)
    assert hu and hu[0]["kind"] == "words" and "50 words" in hu[0]["text"]
    assert E.heads_up([], hours=8, words=100) == []


def test_a_scanned_audiobook_counts_only_what_is_ticked():
    st = {"parts": ["a.mp3"], "duration": 36000.0, "mutes": [],
          "scenes": [{"kind": "vampires", "part": 0, "s": i * 900.0, "e": i * 900.0 + 5, "cut": True}
                     for i in range(40)]}
    assert [h["kind"] for h in E.listen_heads_up(st)] == ["vampires"]
    for s in st["scenes"]:
        s["cut"] = False                     # only suggested: no heads-up
    assert E.listen_heads_up(st) == []
