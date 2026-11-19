"""A hen's "Cuck-cuck-cuck-cur-r-r-cuck-k-k!" (Beatrix Potter's The Tale of Jemima Puddle-Duck) isn't the slang
"cuck" (found when re-checking the free classics, 2026-11-19)."""
import cleanlisten as E


def found(text):
    ws = [w for w in (E.norm(t) for t in text.replace("‑", " ").replace("-", " ").split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ["sexual"])]


def test_the_hen_is_left():
    assert not found("“Cuck‑cuck‑cuck‑cur‑r‑r‑cuck‑k‑k!”")
    assert not found("The hen said cuck cuck and ran off.")


def test_the_slang_still_counts():
    assert found("Don't be such a cuck.") == ["cuck"]
