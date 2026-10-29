# CleanListen — handoff for Claude Code

CleanListen is a Windows desktop app that makes a "clean" copy of an audiobook the family owns.
It transcribes the audio on the PC, finds language and content the family doesn't want, shows
everything on a review screen, and saves new audio files with words muted and passages cut.
It was built in Claude chat sessions (Oct 2026) for **Lauren** (non-technical, Windows 11,
display scaling on) and her family, including a grandmother who listens on a **Yoto** player.
This file explains how it works, the family's rules, how releases ship, and what to improve.

Same repo, separate apps: **CleanRead** (ebooks, `cleanread.py` / `CleanRead.pyw`, built in
another chat) imports this engine. **CleanView** (movies/TV) has moved to its own repo
`BookWorm824/cleanview` with its own engine copy (`cvcore.py`); the old CleanView files here
still ship to CleanListen installs but aren't developed here.

---

## 1. Repo layout and what ships

| File | What it is |
|---|---|
| `cleanlisten.py` | The engine (~1900 lines): word lists, detectors, transcription, ebook alignment, local-AI helper, `analyze()`, `render()`, chapter split. Also has a CLI (`_cli`). |
| `CleanListen.pyw` | The tkinter app (~1700 lines, one `App` class): setup → working → review → done screens, Claude/ChatGPT setup, chat window, per-item "Ask Claude", All-text search, update/resume. Buttons: each page's one main step is the big bright green `Main.TButton` (Start cleaning, Save clean audiobook, Clean another book — a tester with poor sight missed a small one); a first step is `Go.TButton`; grey `Plain.TButton`s have an edge. CleanRead.pyw follows the same. The setup page must fit without scrolling (check with a screenshot). |
| `cleanlisten_claude.py` | Final check + chat through **Claude Code** (`claude -p`), **ChatGPT** (Codex) or **Gemini** (Antigravity CLI) on the user's own plan; the other two go through `HELPERS`. Holds the family's rules (`KIND_RULES`, `CAT_RULES`). |
| `cleanlisten_gpt.py` | ChatGPT through OpenAI's Codex CLI (adapted from CleanView). |
| `cleanlisten_gemini.py` | Gemini through Google's **Antigravity CLI** (`agy -p --output-format json --json-schema --sandbox`). Google replaced Gemini CLI with it for personal and Google One accounts on 2026-06-18. Built from Google's docs and tested with a faked `agy` only (`tests/test_gemini.py`); not yet tried on a real account. Requests over ~24k characters go in a file agy reads. Sign-in check is `agy models`. |
| `cleanlisten_learn.py` | Learning from the family's choices; exports ("Send what CleanListen learned", "Export what we refined"); findings spreadsheet. `send()` posts an export to the owner's inbox (the Google Apps Script shared with CleanView, `tools/cleanview_inbox.gs` in the CleanView repo) when `SEND_URL` is set (`CLEANLISTEN_INBOX` overrides it, for tests); while it's empty, or if sending fails, the app falls back to "saved in…, attach it in your chat with Claude". |
| `shared_learned.json` | Built-in knowledge every copy starts with (merged from exports — see §7). |
| `launcher.pyw` | Desktop shortcut target: checks GitHub for a newer `version.json`, downloads the listed files, swaps them in, starts the app (`view` → CleanView, `read` → CleanRead). |
| `shortcuts.py` | Creates the CleanView / CleanRead desktop icons. |
| `update.json` | `{"repo": "BookWorm824/cleanlisten", "branch": "main"}` |
| `version.json` | Version + **the list of files the launcher downloads**. Anything not listed never reaches users. |
| `installer/` | First-time install (PowerShell): Python venv, sherpa-onnx, ffmpeg, speech model, shortcut. |
| `tools/merge_learned.py` | Merges users' exported JSON into `shared_learned.json`. |
| `dev/` | Test helpers used during development (stand-in `claude`/`codex`/Ollama, test-audio generator, GUI test examples). Not shipped. |

Python 3.12 on the user's PC (private venv). Dependencies: `sherpa-onnx`, `numpy`,
`beautifulsoup4`, `pypdf`; tkinter; ffmpeg/ffprobe (BtbN "master-latest" build = ffmpeg 8).

## 2. On the user's PC

`%LOCALAPPDATA%\CleanListen\`
- `app\` — the program files above, plus `bin\ffmpeg.exe`, `models\sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8\`
- `venv\` — private Python
- `jobs\<sha1 of file paths+sizes>\` — one folder per book:
  `transcript.json` (word timings per file — reused, so re-checking skips listening),
  `analysis.json` (everything found + the family's ticks, see §4), `job.json` (audio list,
  ebook, output folder, title), `claude_chat\` (book.txt + findings.txt for the chat),
  `save_error.txt`, `last_error.txt`
- `learned.json` (what this PC learned), `claude_findings\*.json` + `claude_findings.csv`
- `settings.json` (`claude_model`, `reviewer` = claude|chatgpt), `resume.json` (reopen onto the
  same review after an update or after closing the window)

Claude Code / Codex / Antigravity CLI are installed per-user by the app's "Set up / sign in"
button and use the family's **own plan** (no API keys; `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY` / `GOOGLE_API_KEY` are removed from the child environment on purpose).

## 3. The pipeline (`analyze()` then `render()`)

1. **Transcribe** each file with sherpa-onnx Parakeet TDT (30 s chunks, 2 s overlap) → words with
   times. Saved per file, resumable.
2. **Ebook (optional)**: EPUB/PDF/TXT aligned to the transcript (unique 4-gram anchors + LIS +
   difflib) to catch misheard words and use paragraph edges.
3. **Word lists** (`find_language`): categories `strong, moderate, mild, deity, minced, sexual`
   (`CATS`, also masked by CleanView/CleanRead) + `orientation` (`EXTRA_CATS`, CleanListen only)
   + `rude` ("Rude words kids copy" box, off by default; `KID_CATS`, kept out of `ALL_CATS` so
   CleanRead doesn't star them), plus phrases (`PHRASES`: "oh my god", "screw you", "slept with
   someone", "eff you", "shut up"…). Since 1.8.0 the lists carry CleanView's TV/film additions
   (slurs, "sweet-ass", "sumbitch", "pussy"…) with guards for everyday uses (`INNOCENT_NEXT` /
   `INNOCENT_PREV`: "Moby Dick", "summa cum laude", "he jerks the door open"), plus slang for a
   man's private parts muted as swearing only in slang phrases (`body_slang`: "grow some stones",
   "has the balls to", "kicked in the nuts", "grow a pair"; just that word), and fruit and
   vegetables for body parts in the same way (`fruit_slang`, `FRUIT_SLANG`: "check out those
   melons", "pop her cherry", "kneed him in the grapes"; never "cherry pie" or "these melons are
   ripe"; same phrases as CleanView's `cvcore.BODY_SLANG`). Lauren also wants
   "yanking your chain" (whole phrase, moderate), "sheesh" (minced) and slang for touching
   yourself ("jerking off", "rub one out"; `OFF_SAFE_NEXT` keeps "jerked off the road").
   "Bull" for bullshit is mild, only after "that's", "load of", "cut the"... or before
   "shit"/"crap" (`bull_swear`, as CleanView's; "bull riding", "a bull market" are left alone).
   In audio mutes (`analyze`) a swear's lead-in goes too: "what the hell", "where in the heck"
   (`find_language(..., lead_in_too=True)`, swearing groups only; off for CleanRead and
   context starring), plus "what the f / eff / fudge" as phrases.
   Mute edges snap to silence (`snap_edges`).
4. **Passage detectors**: explicit sex (`sex_score`, needs 2+ explicit words), gore (`gore_score`),
   religion (`religion_score`, `blames_god`, `invokes_providence`, `strict_religion_hit`) — window scoring, then edges trimmed to heavy
   sentences. Sentence filters: sexual references, relationships (`relationship_hit`,
   `same_sex_flirt`), crude (`crude_hit`), bullying (`bully_hit`), flirting (`flirt_hit`), and
   the "For young kids" topics (`TOPICS`, `topic_hit`, `TOPIC_WORDS`; `analyze(find_topics=)`):
   holidays (Christmas, Halloween, Valentine's, Easter, St. Patrick's Day: one box), candles on
   a birthday cake (only the candles: parties and cake are fine), magic, dark magic (wizards
   count as dark magic, Lauren 2026-10-29), vampires and werewolves. Same lists
   as CleanView's LINE_WORDS, plus "blew out the candles" (books are past tense) and not
   "Rudolph" on its own (a name in one of Lauren's books). Thanksgiving is fine.
5. **AI helper on the PC** (`ai_assist`, Ollama gemma3:4b via `cleanview_ai.py`): reads in
   chunks, quotes what it flags, verifies each find. **Weak** — in real books it flagged hundreds
   of false positives. Since 1.6.7 it is **skipped when the Claude/ChatGPT check is on**; on its
   own it skips relationships and its finds start unticked unless the word lists back them up
   (`_ai_backed`). It may only untick listed words that can be innocent (`INNOCENT_WORDS`).
6. **Learned choices** (`cleanlisten_learn.apply`): sentences the family kept/cut before, words
   muted in context, shared knowledge.
7. **Final check** (`cleanlisten_claude.review`, optional): the whole book in ~30k-word sections
   as numbered sentences + every finding (P = passage, W = word) + the family's rules + past
   examples → JSON per finding: `remove | keep | just_the_word | trim` (+ confidence, reason), plus
   missed passages/words. `apply_review` applies it (rules in §5). Things the family changed by
   hand (`by_you`) are never overridden.
8. **Review screen**: everything grouped by type with checkboxes; "▶ Play" on every passage and
   word (`engine.extract_clip` writes `preview0/1.wav` in APP_DATA, played with `winsound`);
   "Show:" filter (`REVIEW_VIEWS`: everything to remove / only the ones to decide / only ticked /
   everything incl. marked fine; marked-fine items hidden by default; kept across resume as
   `view`); "Jump to" links per group; per-item "Ask Claude about this…" (highlight text,
   type a request, list updates in place with Undo); "Ask Claude…" chat window (changes apply
   live); "Search all text…" to cut/mute by hand; exports and the Claude model under "More".
9. **Render**: per file, ffmpeg `volume=0:enable='between(t,a,b)+…'` for mutes and
   `aselect='not(…)',asetpts` for cuts, from a filter file (`-/filter:a`, fallbacks
   `-filter_script:a`, inline `-filter:a`), written to `~saving~ name` then swapped in. Output in a
   `Clean` folder next to the book (multi-disc books: one `Clean` beside the disc folders, files
   prefixed with the disc name). Optional chapter split for Yoto: MP3 tracks ≤60 min on one
   continuous timeline across files, in a `Chapters` folder.

## 4. Data model (analysis.json)

`parts` (absolute audio paths, in play order), `sentences` ([first_word, last_word] indexes into
the flattened transcript — `load_asr()` rebuilds it), `filters` ({cats, kinds}), `scenes`
(passages), `mutes` (words), notes (`claude_note`, `learn_note`, `ai_note`, `ebook_note`),
`chat_history`, `reviewer`, `title`.

- **scene**: `id, kind (sex|ref|gore|religion|relationship|crude|bully|flirt|holiday|birthday|
  magic|darkmagic|added), part, s, e,
  text, cut` + optional `ai, claude, learned, by_you, trimmed, ai_note, claude_reason,
  claude_verdict, chat_answer`
- **mute**: `id, part, s, e, cat, src (audio|ebook|ai|claude), i, j, word/ctx/ctx_after` (starred)
  + `word_raw/ctx_raw/ctx_after_raw` (real), `on` + optional `note, by_you, claude_reason,
  claude_verdict`

## 5. The family's rules (the spec)

**Owner's standing rule: every change to words, phrases, guards or filters goes into all three
apps** (CleanListen, CleanView and CleanRead). CleanRead uses this engine, so a change here
reaches it; CleanView has its own copy in `cvcore.py` (`BookWorm824/cleanview`), so make the
same change there or tell the CleanView session. Differences on purpose: CleanView mutes whole
body-slang phrases ("grow some stones") where CleanListen mutes just the word; CleanView
removes sexual talk as whole lines instead of single sexual words; CleanView mutes "thank god"
as God's name, where CleanListen leaves it to the strict religion filter. CleanView's
`tests/test_cleanlisten_words.py` reads this repo's `cleanlisten.py` and fails on any other
difference.

Source of truth for Claude/ChatGPT: `KIND_RULES` / `CAT_RULES` in `cleanlisten_claude.py`. In
plain words, learned from Lauren directly and from her exported reviews:

- **The f-word is a hard line.** Every listed swear/sexual word is muted every time — in a
  denial ("it's not sexual"), a question or a quote — unless it has an innocent meaning right
  there (`INNOCENT_WORDS`: hell the place, bloody = covered in blood, ass = donkey, gay =
  cheerful, screw something in, craps the game…) or the narrator didn't actually say it.
- **"Thank God" is fine.** "Oh my God", "Jesus Christ", "God knows (what)" as exclamations are muted.
- **Romance and kissing are fine**, as are beds and sheets. Only explicit sex is cut.
- **Mentions vs. content:** a sentence that only *mentions* that someone slept with someone /
  made love / watched porn **stays** with just that phrase muted; sentences that describe or dwell
  on sex, desire or innuendo are cut.
- **Cut as little as possible:** never a whole paragraph for one line (use `trim` or
  `just_the_word`).
- **Gore:** she's fine with mystery-level violence (even one sentence with a split skull). Only
  prolonged, very graphic description is cut. Doubtful gore → left in.
- **Religion is strict:** cut preaching/teaching, scripture read as part of it, statements of
  belief/testimony ("There is a God, and He listens"), doubting whether God exists or cares, and
  anger/blame/mocking of God. Keep brief prayers, grace, thanking God, church. Doubtful religion →
  **cut**. Any faith counts (Catholic, Buddhist, Hindu, Muslim, Jewish, pagan…; their words are in
  `RELIGION_TERMS`), and so does Providence spoken of as God ("Providence only knows"), but not
  the city.
  **Strict religion** (setup tick under Religious content, off by default, `strict_religion` in
  `analyze()` and `st["filters"]`): also cuts any sentence with a sincere religious mention
  (`strict_religion_hit`): "thank God", "God bless", prayers, verses, "Amen", someone in heaven.
  Generic words (prayed, church, grace, faith, soul) and swear-like "oh my God" are left to the
  other filters. Claude gets `STRICT_RELIGION_RULE`; the AI on the PC doesn't second-guess these.
- **Same-sex and non-traditional relationships** (incl. same-sex flirting, throuples, open
  marriage…) are cut, and orientation words (gay, lesbian…) muted; man-and-woman is fine.
- **Off by default:** soft substitutes (gosh, heck…), bullying, flirting, and the "For young
  kids" boxes (holidays, birthday candles, magic, dark magic, vampires & werewolves; CleanView
  ticks them for its kids' profiles, CleanListen has no profiles). The setup page must still
  fit: they sit in two rows under the word boxes (`KID_TOPICS` gives each box's place).
- Soft swears include "good grief", "for Pete's sake", "holy cow"/"holy moly" (Lauren: not
  fine; "holy water", "the Holy Bible" are), "gee" and "know squat" (`squat_swear`). "Thank the
  Lord" is left to the strict religion filter, like "thank God".
- She does **not** want things split per Yoto card — all chapter files in one folder.

## 6. Releasing (users update automatically)

The launcher compares `version.json` on `main` with the installed one at every start (and the
in-app "Check for updates" link does the same and reopens the same review).

1. `git pull` first — other chats (CleanRead) push to this repo too. Never upload stale copies.
2. Bump `version.json` (`_ver` compares dotted integers, e.g. 1.6.10 > 1.6.9) and **keep every
   app's files in `files`** (dropping one silently stops it updating for users).
3. Don't rename/remove engine functions CleanRead uses (see its imports: word lists,
   `find_language`, scorers, `relationship_hit`, `crude_hit`, `bully_hit`, `flirt_hit`,
   `read_ebook`, `AI_TYPES`…). Don't add categories to `CATS` that the other apps shouldn't mask.
4. **Be careful with `launcher.pyw`** — it's in the update list, and a broken launcher can't
   update itself again (it only `compile()`-checks .py/.pyw files before swapping).
5. Push to `main`, then verify each listed file at the commit-pinned raw URL
   (`raw.githubusercontent.com/BookWorm824/cleanlisten/<sha>/<file>`); the unpinned URL lags a few
   minutes.
6. Commit messages so far: `Version X.Y.Z: <plain summary>`.

## 7. Learning from the family (the feedback loop)

After saving a book, "Export what we refined…" writes
`CleanListen refined - <book> <date>.json` (every item with final decision, origin, notes,
Claude's reasons, chat, plus the PC's `learned.json`). Lauren sends these in. To use one:

1. Study it: where did she overrule the filters/Claude? (`origin == "you"`, `removed`, `note`).
   Two have been processed so far ("Bring Me Back", "If I Run"); they produced the 1.6.7/1.6.8
   rule changes in §5.
2. Merge: `python tools/merge_learned.py shared_learned.json "<file>"`, then drop bad
   "fine in this phrase" entries (`cleanlisten_learn._may_be_fine`).
3. Adjust `KIND_RULES` / `CAT_RULES` / word lists if a pattern shows up, and release.

## 8. Testing

`tests/` is a pytest suite (not shipped; not in `version.json`). Run it before every release:
`python -m pip install numpy pytest` once, then `python -m pytest` in the repo folder (~1 s).
- `test_words.py`: word lists, `find_language`, `may_untick_word`, and the engine names
  CleanRead/CleanView import (renaming one fails here).
- `test_detectors.py`: sex/gore/religion scores, relationship/flirt/bully/crude hits, against
  the §5 rules. Known false alarms from Lauren's kept sentences are `xfail(strict=True)`: when
  one gets fixed, pytest reports XPASS as a failure, so remove its mark.
- `test_apply_review.py`: every `apply_review` verdict path, plus `review()` with `run` stubbed.
- `test_smoke.py`: `analyze()` on a generated tone with a ready-made `transcript.json` (no
  speech model), then `render()`; checks the mute is silent and the cut shortens the file, and
  that `extract_clip` (the Play button) cuts the right stretch.
  Needs ffmpeg on PATH or in the installed app's `bin`, else skipped.
`conftest.py` points `LOCALAPPDATA` at a temp folder, so tests never touch the real app data.
The GUI has no automated tests. On Windows it was checked by loading `CleanListen.pyw` with a
made-up analysis, faking `winsound`, and grabbing the window with Pillow's `ImageGrab`
(like `dev/gui_test_*.py`, which use Xvfb on Linux).

Before the suite, development used Linux + Xvfb (`xvfb-run -s "-screen 0 1600x1000x24 -dpi 144"`) to drive the
tkinter app from scripts and screenshot it. `dev/` has:
- `fakeclaude/claude`, `fakeclaude/codex` — stand-ins for Claude Code / Codex that read the
  prompt and return schema-shaped JSON (put the folder first on `PATH`).
- `fakeai/cleanview_ai.py` — stand-in for the Ollama helper (put first on `sys.path`).
- `make_test_audio.py` — builds a test chapter with sherpa-onnx TTS (Piper voice from the
  sherpa-onnx `tts-models` release).
- `gui_test_*.py` — examples of scripted GUI runs (set `LOCALAPPDATA` to a temp folder).
The real Claude/ChatGPT and the Windows-only behaviour (installer, Explorer, scroll timing,
console windows) could not be tested in development — Lauren tests on her PC.

## 9. Known weak spots and ideas (roughly by value)

1. **Tests (started, see §8).** Still to do: use the refined exports themselves as labelled
   fixtures (cut/kept by Lauren, per kind), and tests for `cleanlisten_learn` and chapter split.
2. **Measure accuracy.** Build an evaluation script over refined exports: precision/recall of the
   word lists, detectors and the Claude prompt against Lauren's final decisions. Use it before
   changing rules.
3. **`CleanListen.pyw` is one 1700-line class** with patch-on-patch growth (review screen,
   chat, inline ask, update/resume). Split into modules (screens, chat, review list) and make
   the review list incremental instead of rebuilding the whole page on every change (that's why
   scroll-position restore was needed).
4. **The PC AI helper (gemma3:4b) is mostly noise.** Decide whether to keep it (maybe only as a
   no-Claude fallback with a better model) or remove it and its 4 GB download.
5. **Claude check cost/latency on long books**: sections run one after another; consider
   running sections in parallel, caching per-section answers by hash, and reusing them when only
   a few ticks changed.
6. **Sentence boundaries come from ASR punctuation**; very long run-on "sentences" make cuts too
   big. Consider splitting on pauses too.
7. **Mute precision**: edges snap to silence or pad ±0.12 s; occasionally clips a neighbouring
   word. Forced alignment could tighten it.
8. **Installer pulls ffmpeg "master-latest"** — options change under us (ffmpeg 8 removed
   `-filter_script`). Pin a release.
9. **Engine shared by copy-paste with CleanView** (`cvcore.py`) — filter fixes don't reach both.
   A shared package (or CleanView importing this engine) would keep them in sync.
10. **Ebook alignment** isn't exercised much yet; check it on a real EPUB + audiobook pair.

## 10. Working with Lauren

She's busy, direct and not a programmer. Explain in plain words, one step at a time; say what
changed and what she needs to do ("click Check for updates"). She tests on her PC and sends
screenshots or refined exports. Don't guess about her rules — they're in §5, and when an export
shows a new pattern, say what you inferred so she can correct it.
