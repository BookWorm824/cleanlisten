"""Merge 'CleanListen learned <date>.json' files (from the "Send what CleanListen
learned" button) and 'CleanListen refined - <book> <date>.json' files (from "Export what
we refined" after a book) into the app's shared_learned.json, which ships with updates.

    python tools/merge_learned.py shared_learned.json "CleanListen learned 2026-10-24.json" [...]

Sentences the person cut (or Claude/ChatGPT said to cut, unless the person kept them)
and sentences they kept (or Claude/ChatGPT said were fine, unless they cut them).
Phrases where a word was fine ("dinner at hell") and words muted in context are
added too. Later files win over earlier ones on conflicts.
"""
import json
import sys

MAX = 1500


def add(lst, items, drop=()):
    for t in items:
        if t in drop:
            continue
        if t in lst:
            lst.remove(t)
        lst.append(t)
    del lst[:-MAX]


def merge(shared, export):
    for k in ("cut", "kept", "ok_words", "word_mutes"):
        shared.setdefault(k, [])
    shared.setdefault("cut_for", {})
    d = export.get("learned", {})
    mine_c, mine_k = d.get("cut", []), d.get("kept", [])
    cut = mine_c + [t for t in d.get("claude_cut", []) if t not in mine_k]
    kept = mine_k + [t for t in d.get("claude_kept", []) if t not in mine_c]
    shared["kept"] = [t for t in shared["kept"] if t not in cut]
    shared["cut"] = [t for t in shared["cut"] if t not in kept]
    add(shared["cut"], cut)
    # which filter each sentence was cut for, so it's only cut again when that filter is on
    shared["cut_for"].update({t: k for t, k in d.get("cut_for", {}).items() if t in cut})
    shared["cut_for"] = {t: k for t, k in shared["cut_for"].items() if t in set(shared["cut"])}
    add(shared["kept"], kept)
    add(shared["ok_words"], d.get("claude_ok_words", []))
    known = {e[0] for e in shared["word_mutes"]}
    shared["word_mutes"] += [e for e in d.get("word_mutes", []) if e and e[0] not in known]
    del shared["word_mutes"][:-MAX]
    return len(cut) + len(kept)


if __name__ == "__main__":
    target = sys.argv[1]
    shared = json.load(open(target, encoding="utf8"))
    for f in sys.argv[2:]:
        n = merge(shared, json.load(open(f, encoding="utf8")))
        print(f"{f}: {n} sentences merged")
    json.dump(shared, open(target, "w", encoding="utf8"), indent=1, ensure_ascii=False)
    print(f"now: {len(shared['cut'])} cut, {len(shared['kept'])} kept, "
          f"{len(shared['ok_words'])} fine-in-context phrases, {len(shared['word_mutes'])} words in context")
