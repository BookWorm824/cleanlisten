"""Learning from your choices (cleanlisten_learn): what's cut again in later books."""
import json
import sys
from pathlib import Path

import pytest

import cleanlisten as E
import cleanlisten_learn as L

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import merge_learned  # noqa: E402

LONG = "The minister preached about heaven for an hour."
SHORT = "What do you think?"


@pytest.fixture
def learned(tmp_path, monkeypatch):
    """A fresh learned.json and an empty shared file."""
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    monkeypatch.setattr(L, "APP_DATA", tmp_path)
    shared = {"cut": [], "kept": [], "ok_words": [], "word_mutes": [], "cut_for": {}}
    monkeypatch.setattr(L, "_shared", shared)
    return shared


def book(*sentences, kinds=("religion",)):
    """A later book: its words, sentence spans, and what learning added to it."""
    asr, spans = [], []
    for s in sentences:
        a = len(asr)
        asr += [{"t": w} for w in s.split()]
        spans.append((a, len(asr) - 1))
    st = {"sentences": spans, "scenes": [], "mutes": [], "filters": {"kinds": list(kinds)}}
    added = []
    L.apply(st, asr, lambda a, b, kind, on, note: added.append(a) or True)
    return added


def test_short_learned_sentences_are_not_cut_again(learned):
    # a cut passage is learned sentence by sentence; "What do you think?" mustn't follow
    L.record({"scenes": [{"kind": "religion", "cut": True, "text": f"{LONG} {SHORT}"}]})
    assert book("Hello there.", SHORT, LONG) == [2]


def test_shared_sentences_are_cut_again_only_when_their_filter_is_on(learned):
    learned["cut"] = [L.norm(LONG)]
    learned["cut_for"] = {L.norm(LONG): "religion"}
    assert book(LONG, kinds=["religion"]) == [0]
    assert book(LONG, kinds=["gore"]) == []


def test_your_cut_sentences_remember_their_filter(learned):
    L.record({"scenes": [{"kind": "religion", "cut": True, "text": LONG}]})
    assert L.load()["cut_for"] == {L.norm(LONG): "religion"}
    assert book(LONG, kinds=["sex"]) == []
    assert book(LONG, kinds=["religion"]) == [0]


def test_sentences_without_a_filter_count_for_every_filter(learned):
    learned["cut"] = [L.norm(LONG)]          # older shared lines have no "cut_for"
    assert book(LONG, kinds=["gore"]) == [0]


def test_merging_an_export_keeps_each_sentences_filter():
    shared = {"cut": [], "kept": [], "ok_words": [], "word_mutes": []}
    export = {"learned": {"cut": [L.norm(LONG)], "kept": [], "cut_for": {L.norm(LONG): "religion"}}}
    merge_learned.merge(shared, export)
    assert shared["cut_for"] == {L.norm(LONG): "religion"}


def test_learning_knows_every_passage_filter():
    assert L.KINDS == set(E.AI_TYPES)


def test_send_what_we_refined_exports_the_review_as_it_is(learned, tmp_path):
    st = {"scenes": [{"kind": "religion", "cut": False, "by_you": True, "text": LONG}], "mutes": []}
    path = L.export_book(st, title="Test book", dest_dir=tmp_path)
    items = json.loads(path.read_text("utf8"))["items"]
    assert [(i["removed"], i["origin"]) for i in items] == [(False, "you")]
