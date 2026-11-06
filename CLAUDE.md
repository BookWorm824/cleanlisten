# CleanListen — handoff for Claude Code

CleanListen is a Windows desktop app that makes a "clean" copy of an audiobook the family owns.
It transcribes the audio on the PC, finds language and content the family doesn't want, shows
everything on a review screen, and saves new audio files with words muted and passages cut.
It was built in Claude chat sessions (Oct 2026) for **Lauren** (non-technical, Windows 11,
display scaling on) and her family, including a grandmother who listens on a **Yoto** player.
This file explains how it works, the family's rules, how releases ship, and what to improve.

Same repo, separate apps: **CleanRead** (ebooks, `cleanread.py` / `CleanRead.pyw`, built in
another chat) imports this engine. **ReadAloud** (ebook -> audiobook, `readaloud.py` /
`ReadAloud.pyw`, §11) uses CleanRead's book reader and this engine's M4B helpers.
**CleanView** (movies/TV) has moved to its own repo
`BookWorm824/cleanview` with its own engine copy (`cvcore.py`) and its own install. The old
copy that shipped here is gone (1.9.6): CleanListen used to make a "CleanView" icon for it with
the same name as the real one's, and on one PC it won, so Jason got the October version.
`CleanView.pyw` here is now only a hand-over: an old icon still opens it, and it starts the
real CleanView (`shortcuts.open_cleanview`), repoints the icon (`fix_cleanview_shortcut`), or
says how to install CleanView. `cleanview_ai.py` stays: CleanListen and CleanRead use it.

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
| `launcher.pyw` | Desktop shortcut target: checks GitHub for a newer `version.json`, downloads the listed files, swaps them in, starts the app (`read` → CleanRead; `view` → the CleanView hand-over). First it starts itself again as `venv\CleanListen\CleanListen.exe` or `venv\CleanRead\CleanRead.exe` so Task Manager shows the app's name, not "Python" (Jason, 2026-11-03; CleanView 1.18.9's code: copies of the base pythonw.exe with the description and icon changed, only while Smart App Control is off and after a test run worked, `failed.txt` = never again; not in `Scripts`, whose onnxruntime.dll would load first). After an update it starts the launcher it just downloaded (`start_again`, env `CLEANLISTEN_UPDATE_DONE` so it doesn't check again); before 1.13.2 the old launcher opened the app itself, so the first start after 1.13.0 still said "Python" (Jason). CleanListen's "Check for updates" restarts through the launcher too. |
| `freezes.py` | Noticing a freeze or crash in both apps (CleanView 1.18.9): no answer for 20 s → what every thread was doing goes in `stopped_last_time.txt` (`cleanread_` for CleanRead), a hard crash via faulthandler (`crash_log.txt`); next start they're asked to send it in (kind "problem"). `drain()` runs each window's queue: at most 500 messages a go, only the newest progress, one bad message can't stop it (`_handle`). |
| `bookqueue.py` | The book queue (Lauren, 2026-11-04): "Your books" page state (`BookQueue`, kept in `APP_DATA/queue.json`, steps waiting → preparing → ready → save_waiting → saving → done, or failed/stopped) and the worker processes (`Workers`). "Books at once" 1–4 (default 2, or 1 on a PC with under 12 GB, `default_at_once()`; their own choice is kept); `plain_error()` turns running out of memory ("bad allocation", "[WinError 1455] The paging file is too small"…) into "set Books at once to 1, close other programs, Try again". Low memory, 1.14.5: `run()`/`popen()` wait 5/15/30 s and try again when Windows can't start ffmpeg for lack of memory (`LOW_MEMORY_ERRORS`), and `free_ai_memory()` tells Ollama to let go of the AI helper's model as soon as it's done (it otherwise holds several GB for 5 minutes); `threads_each()` shares the PC's cores between them, leaving one free for the window (16 threads: 8, 7, 5, 3 per book; 6 threads, one book: 5), and the workers run below normal priority (`_worker_flags`; their ffmpeg inherits it), so the window always comes first (1.15.1, "why is clean listen freezing": one book took all 6 cores of a 6-core, 8 GB PC at normal priority). No window code, so it's tested directly (`tests/test_queue.py`). |
| `bookrunner.py` | One book's worker process: runs `analyze()` (prepare) or `render()` (save) and sends JSON lines (`{"p","m"}`, `{"done": "ready"/"saved"}`, `{"error"}`, `{"stopped"}`) back on stdout; its stop file (`queue.stop.<run>`, written by Cancel / closing / updating) or the window going away cancels. Not stdin: on Windows a thread blocked reading a pipe stops DLLs loading (the worker froze importing numpy). Holds `jobs/<key>/queue.lock` so two runs of one book never overlap (after an update). Its stderr and faulthandler go to `jobs/<key>/worker_log.txt`. `CLEANLISTEN_ENGINE` swaps in a stand-in engine for tests. |
| `dropfiles.py` | Dropping files from File Explorer on a widget (the M4B cover box, 1.14.6): Windows' own WM_DROPFILES through ctypes (subclassing the widget's window), so nothing to install. The window procedure must not call tkinter (Tk holds its lock there): it only notes the files and an `after` loop hands them over. Tested with a real posted drop (`tests/test_dropfiles.py`). |
| `ollama_care.py` | Ollama only while CleanView, CleanListen or CleanRead are open (1.15.2; Lauren, 2026-11-05: it started with Windows and held ~4 GB once it had loaded a model). `autostart_off()` removes Ollama's Startup-folder shortcut every time the installed CleanListen or CleanRead opens (Ollama's own updates put it back). When either window closes, `stop_later()` starts a small detached helper (`stop_when_idle`): after 8 s, if no CleanView/CleanListen/CleanRead window or book worker is running (`other_apps`, a `Win32_Process` command-line query) and no model is loaded (`/api/ps`, waiting up to 7 min for one to be let go of), it stops `ollama app.exe` and `ollama.exe`. If Windows can't say, or a model stays loaded (something else using Ollama), it's left alone. The apps start Ollama themselves when needed (`cleanview_ai.start_ollama`). No numpy, so the helper starts fast. CleanView can use the same file. |
| `filters.py` | The filters both apps offer (CleanView's, for books), the ages, saved ticks (`filters.json`), the "Choose filters" window. |
| `readaloud.py` | ReadAloud's engine (§11): ebook (PDFs page by page) -> chapters -> Kokoro voice (sherpa-onnx) in worker processes -> one M4B with chapters, tags and cover. CLI: `info`, `make`, `speak` (one worker). |
| `readaloud_ai.py` | ReadAloud's reading director (§11): Claude / ChatGPT / Gemini go through the book first (what not to read, scanning fixes, who speaks, pace, pauses, pronunciations). |
| `readaloud_gpu.py`, `readaloud_gpu_req.txt`, `rv_*.flac` | ReadAloud's graphics-card readers (§11): Qwen acting, Qwen steady, Chatterbox; their one-time setup, the 18 voice clips, listening back to every line. |
| `ReadAloud.pyw` | ReadAloud's window: choose ebook, reader and voice (▶ Hear it, Set up), what to read, where to save; working page; done page. Launcher arg `aloud`. |
| `shortcuts.py` | Creates the CleanRead and ReadAloud desktop icons; points an old CleanView icon at the real CleanView. |
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
- `save_places.json` — where the chapter files and the M4B go when not the usual place
  (`chapters_dir`, `m4b_dir`, `abs`)
- `queue.json` — the "Your books" list (each book's files, filters, analyze arguments, step,
  status, results) and "Books at once"; a book that was preparing or saving when the window
  closed (or updated) goes back in line and carries on (`BookQueue.resume`; listening resumes
  per file from `transcript.json`, so the file it was on starts over)
- `settings.json` (`claude_model`, `reviewer` = claude|chatgpt), `resume.json` (reopen onto the
  same review after an update or after closing the window), `left_review.json` (a review left
  with "◀ Back to start"; the start page offers "Pick up where I left off" for 14 days)

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
   of false positives. With the final check on, **both look at the same time** (Lauren chose
   this, 2026-10-29; 1.6.7–1.9.3 skipped it): `ai_assist` works on its own copies in a thread
   (`in_background`/`wait_for`) and `_merge_ai` adds only what it alone found, unticked; the
   final check decides the rest (if the final check fails, it works as it does alone). On its
   own it skips relationships and its finds start unticked unless the word lists back them up
   (`_ai_backed`). It may only untick listed words that can be innocent (`INNOCENT_WORDS`).
6. **Learned choices** (`cleanlisten_learn.apply`): sentences the family kept/cut before, words
   muted in context, shared knowledge. A learned sentence under 5 words is never cut again just
   for being learned (`LEARNED_SHORTEST`), and one cut for a filter (`cut_for`, also in
   `shared_learned.json`) is only cut again when that filter is ticked.
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
   "◀ Back to start" leaves without saving (Jason, CleanView 1.18.1: a parent may only want to
   see what's in a book); the review is kept to pick up again.
   **The chat can learn** (Jason, CleanView 1.18.1): when told how to judge something from now on
   ("it's Aladdin, the magic is fine"), it returns `remember` (`CHAT_SCHEMA`), kept by
   `learn.add_note` in `learned.json` "notes" (this book by title, or every book; 40 at most).
   `learn.told()` puts them first in every prompt: the AI helper (`_learned_examples`), the final
   check (`examples_text`) and every chat message. The chat shows "✓ CleanListen will remember…".
   Since CleanView 1.18.2 it keeps a lesson whenever it's corrected or told why ("they're just
   sitting in bed talking"), not only for "from now on". "Back to start" also learns the ticks
   (`_learn_choices`); `learn.record` counts each choice once (`_learned_as` on the item, kept in
   analysis.json), however often she leaves and comes back. The review page shows the book's name
   on top (CleanRead too). Every yes/no box plays `chime()` first (they're silent on Windows).
9. **Render**: per file, ffmpeg `volume=0:enable='between(t,a,b)+…'` for mutes and
   `aselect='not(…)',asetpts` for cuts, from a filter file (`-/filter:a`, fallbacks
   `-filter_script:a`, inline `-filter:a`), written to `~saving~ name` then swapped in. Output in a
   `Clean` folder next to the book (multi-disc books: one `Clean` beside the disc folders, files
   prefixed with the disc name). Optional chapter split for Yoto: MP3 tracks ≤60 min on one
   continuous timeline across files, in a `Chapters` folder.
   Chapters come from the book's own chapter marks (an M4B's) when every file has them, else
   from the narrator's "Chapter One" (`find_chapters`). An M4B's clean copy gets its chapter
   marks moved with the cuts (`retag_m4b`; before 1.13.7 they stayed where they were).
   Optional **one M4B** (`m4b=True`, 2026-11-04): the owner used to make it by hand in
   AudiobookConverter from the chapter files. `make_m4b` does the same: each chapter piece to
   AAC at the book's own bitrate (48–128k, several at once), joined with `-c copy`, one chapter
   per piece with its real name, tags (title, author) and a cover: one they chose, else the
   picture inside the book, else a picture in its folder (`find_cover`: cover/folder/front
   first, then the biggest). A one-file M4B book just gets its clean copy re-tagged. ~47 s for
   6 hours of audio.
   **Where they go** (1.14.6; Lauren, 2026-11-04: "allow me to choose where to save the files"
   ... "set the folder up for audiobookshelf"): the usual places (`Clean\Chapters`, the M4B in
   `Clean`) unless they chose others on the start page (kept in `APP_DATA/save_places.json`).
   Chapter files go in `chapters_dir\<book>` (never loose: `split_tracks` clears the folder's
   old MP3s). The M4B goes in `m4b_dir`, or with `abs_layout` in
   `m4b_dir\Author\Series\Book 2 - Title\Title.m4b` (`abs_folder`): Audiobookshelf's scanner
   takes author/series/title from those folders and the number from "Book 2 - ". Series and
   number are guessed from the folders (`guess_series`: "Grace Ford Series\#2 Nearly Safe" ->
   Grace Ford, 2) and can be changed; the number is dropped from the title tag (`strip_number`).
   A one-file M4B book's re-tagged clean copy is copied there. The cover can be dropped on its box.
   **A cover from the internet** (1.14.7; Lauren: "the cover picture an option for automatic?"):
   ticked by default (`save_places.json` `cover_online`). When no cover was chosen and the book
   and its folder have none, `find_cover_online` asks Audible's catalog (square, 1215 px), then
   Apple Books, then Open Library, sending only the title and author. `same_book` is strict on
   purpose (same title without subtitle/"Unabridged", and the author's last name), because a
   wrong cover is worse than none. Apple's search returned unrelated books for "Nearly Safe".
   Results are kept (`APP_DATA/covers`, or the job folder when saving looks). The start page
   looks it up in the background and shows a small picture; saving looks it up if the start
   page hadn't. The report and the book's row say where the cover came from.

**The book queue** (1.14.0; Lauren, 2026-11-04: "queue several books, a collapsed row per
book, 3–4 at a time"). Start cleaning no longer runs the book in the window: it adds a row to
"Your books" (`show_queue`) and the start page is free for the next book. Each row: title,
filter summary, status line, progress bar, "▸ More" (files, extra checks, save folder,
Claude's note), Cancel / Remove / Try again / Move up. Up to "Books at once" run together,
each in its own worker process (`bookrunner.py`), so a crash or freeze in one book never takes
the window down (the window's own freezes are still noticed by `freezes.py`). A ready book
chimes and says "Ready to review"; Review opens the usual review page (one book at a time,
`review_job`, `review_key`). "Save clean audiobook" writes the ticks into analysis.json and
queues the save (saving goes ahead of preparing); "◀ Back to my books" keeps the review as a
ready row. The local AI helper (one Ollama model) simply makes the books' requests wait their
turn; Claude/ChatGPT final checks overlap and use the plan's limits faster (said on the page).
Closing the window asks first when books are running; workers are told to stop (5 s, then
killed with their ffmpeg/claude children) and carry on next time. `cleanlisten.write_safely`
writes transcript/analysis whole or not at all, since a worker can be stopped mid-write.

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
- **Disrespect** (Lauren, 2026-10-30; CleanView 1.18.0): a child talking back to or disobeying a
  parent, cut sentence by sentence. Word lists catch only clear lines (`DISRESPECT`: "you're
  not the boss of me", "you can't make me"; not "whatever" or "make me"); the AI helper and
  Claude catch the rest. Claude still cuts it if they learn their lesson later, and says so in
  the reason (or that they get away with it). Off by default, under Bullying.
- **Religion in parts** (Jason, 2026-10-30; 1.10.0): under "Religious content", three boxes:
  Preaching, Anger at God (both on) and Prayers & verses (the old "strict" box, off).
  `E.RELIGION_PARTS` / `religion_def(parts)` (local AI), `cc.religion_rule(filters)` (Claude),
  `filters["religion_parts"]`; analyze(`religion_parts=`), CleanRead `religion_parts(opts)`.
  Old saved settings (`religion_strict`) map onto it.
- **Reverent "Jesus"/"Christ" isn't a swear** (`reverent()`, `REVERENT_BEFORE/NEXT/IS`): "the love
  of Christ", "know Jesus", "Jesus told us", "Christ is risen", "thank You, Jesus" stay; oaths
  ("Jesus!", "Jesus, is that you?", "Oh my Jesus") are muted. CleanView has the same rule.
- **CleanView 1.18.4's word lessons** (Jason's reports): "by Allah", "God/Lord help him…",
  "sounds like bull", "PO'd" (capitals or dots only: "Po'd" is "Po would"). `E.listed_word(text,
  cats)`: Claude only mutes a missed word (or "just the word") on its own if it's on a ticked
  group's list; anything else is offered unticked. Same-sex isn't "gay" meaning cheerful;
  bullying includes a villain's mocking song and a passed-on insult; sexual references are only
  the sentences that are sexual themselves (not plain underwear talk).
- **The same filters as CleanView** (Lauren, 2026-10-30: "CleanRead needs all the same filters as
  CleanListen and CleanView"; 1.11.0): `filters.py` holds every box for both apps, grouped as in
  CleanView (Language with religion parts and your own words; Sex and nudity; Kissing and
  relationships with man & woman / same-sex kissing levels; Violence: violence, graphic, gore,
  disturbing; Other: smoking, drinking, drugs, rude gestures; Holidays; Magic). The setup page shows
  "Filtering for: Young kids / Kids / Teens / Adults" (CleanView's PRESETS; Adults = this family's
  book standard, which keeps everything new off except the splits of what was on), a one-line
  summary and "Choose filters…" (the FiltersWindow). Ticks per age and your own words are kept in
  `filters.json`, shared by both apps; the first time, Adults starts from CleanRead's old ticks.
  Engine: `E.MORE_KINDS` / `sentence_hit()` (CleanRead's word lists: SLEEPING, UNMARRIED, NUDITY,
  IMPLIED, IMMODEST, VIOLENCE, DISTURBING, SMOKING, DRINKING, DRUGS, GESTURES), `gore_level()`
  splits gory passages into graphic / gore, `kiss_hit` / `kiss_ss_hit`, `find_language(mine=)`
  (own words, cat "mine", by_you). analyze(more=, kiss_ss=, find_graphic=, mine=); old
  find_substances / find_sleeping still work. Lauren's CleanView violence calls are in the rules:
  a killing heard or described by what follows is violence; accident blood is disturbing.
  Learning is still shared across ages (CleanView learns per age). Loud music is video-only.
- **Same-sex relationships and the small AI** (Lauren, 2026-10-30: "I still want it to look for
  those in books"): both apps' AI helper looks for them, but its finds are only ticked when the
  word lists see it too (`_ai_backed` / CleanRead `rel_hit`); otherwise "AI suggests", unticked.
  It once ticked 56 ordinary man-and-woman lines of one romance (Love Songs Suck).
- **CleanRead cuts less, and you can tell Claude** (Jason, 2026-11-03): in a sentence of 14+
  words, a list hit of a `PART_KINDS` kind (drinking, smoking, violence, kissing... not jokes,
  innuendo, affairs or religion) cuts only the clauses that show it (`sentence_part`, split at
  , ; : and dashes; cut dicts get `"part": [a, b]` in the paragraph, "before"/"after" for the
  review). The review page has "Ask Claude…" (`cleanread.Chat`, through `cleanlisten_claude.run`,
  same provider as CleanListen): untick/tick, "part", "just_the_word", "add", and "remember"
  notes kept in CleanListen's learned notes (`cleanlisten_learn.add_note`), which the AI helper
  (`ai_find`, `ai_second_opinion`) and later chats follow. The working page shows the book's name.
- **CleanRead's book check** (Jason, 2026-11-03, "I can't mark anything. No where to click or
  tell Claude"): each example has a real "Not a problem" button on the left, each heading "None of
  these are a problem", the tip says where to click, and "Ask Claude…" uses `cleanread.CheckChat`
  (fine / not_fine on F-numbered findings, learned like a click, plus remembered notes, which the
  check's AI helper also follows). Places read "Chapter Two · 44% of the way through the book"
  (`Book.where`; a chapter named only "45" shows as In “45”). CleanListen's lists say "at 0:12:34".
  Any instruction naming a button must match a button that is on that page.
- **Off by default:** soft substitutes (gosh, heck…), bullying, disrespect, flirting, and the "For young
  kids" boxes (holidays, birthday candles, magic, dark magic, vampires & werewolves; CleanView
  ticks them for its kids' profiles, CleanListen has no profiles). The setup page must still
  fit: they sit in two rows under the word boxes (`KID_TOPICS` gives each box's place).
- Soft swears include "good grief", "for Pete's sake", "holy cow"/"holy moly" (Lauren: not
  fine; "holy water", "the Holy Bible" are), "gee" and "know squat" (`squat_swear`). "Thank the
  Lord" is left to the strict religion filter, like "thank God". "What the devil/dickens" are
  soft swears; "so help me God" and "holy Lord" are God's name.
- A polite "it's a pleasure" and "sex" meaning men or women ("the fair sex") don't count
  toward a sex scene (`NOT_SEX_BEFORE`; Pride and Prejudice was flagged).
- "Suck" meaning "is bad" ("life sucks", "that sucked", "sucky") is a rude word (Lauren);
  sucking something isn't ("suck it up", "the vacuum sucks up dirt"): `suck_swear`.
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

After saving a book, "Export what we refined…" (or, before saving, "Send what we refined…" on
the review page, which counts the ticks as they are now) writes
`CleanListen refined - <book> <date>.json` (every item with final decision, origin, notes,
Claude's reasons, chat, plus the PC's `learned.json`). Lauren sends these in. To use one:

1. Study it: where did she overrule the filters/Claude? (`origin == "you"`, `removed`, `note`).
   Two have been processed so far ("Bring Me Back", "If I Run"); they produced the 1.6.7/1.6.8
   rule changes in §5.
2. Merge: `python tools/merge_learned.py shared_learned.json "<file>"`, then drop bad
   "fine in this phrase" entries (`cleanlisten_learn._may_be_fine`).
3. Adjust `KIND_RULES` / `CAT_RULES` / word lists if a pattern shows up, and release.

**CleanRead refined** reports (`CleanRead refined - <book> <date>.json`, from CleanRead's "Send
what you marked…") land in the same Drive folder ("CleanListen learned", synced at
`G:\My Drive\CleanListen learned`). CleanRead's own marks stay on each PC, so clear wrong flags
from them go into `shared_learned.json` → `"cleanread_fine"` ({kind: [[item_key, text]]}), read by
`cleanread.shared_fine()`: found again they start unticked ("Kept by families before") and the AI
helper sees them as "not a problem" examples. Only teach clear mistakes she unticked (a prayer
flagged as religion, "pleasure to meet you" as a sexual reference), never her own choice to keep
something that fits its filter (preaching in a Christian novel). First batch (2026-10-30): At
Every Turn, Camp Club Girls, Love Songs Suck, The Boxcar Children (63 marks, built by hand).
Second batch (2026-11-03): Playing by Heart, Wings of a Dream, All That Glitters (147 marks;
book-check kinds like "lying" and "romance" count too). Taught: lines she or Claude unticked that
don't fit their filter ("slapped his hat on his head" as violence, "stole over me" as lying, a
man-and-woman romance as same-sex). Not taught: anything she ticked back after Claude kept it, lines
that fit (blood as gore, preaching or prayers as religion), and lines with a listed word.
Third (2026-11-04, Wings of a Dream again): 16 lines she kept this time after ticking them back
on 11-03 (the cotton gin as drinking, "eyebrows shot up" as drugs, a tortured look, "My naked arms").

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
- `test_queue.py`: the book queue's steps (add, run, ready, review, save, cancel, crash,
  resume), real worker processes with a stand-in engine (`tests/stub_engine.py`), the
  one-worker-per-book lock, and the "Your books" page driven with faked workers (opens a
  hidden Tk window).
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

## 11. ReadAloud (ebook -> audiobook)

Lauren, 2026-11-04: "there are some books I have that they didn't make audiobooks for... I don't
want stilted computer voices... but I also don't want to pay $100 per." A third window in this
install (own icon, launcher arg `aloud`, own name in Task Manager), like CleanRead.

- **Voice:** Kokoro v1.0 (82M, Apache 2.0) through sherpa-onnx's `OfflineTtsKokoroModelConfig`,
  on the CPU. Model `kokoro-multi-lang-v1_0` (334 MB, sherpa-onnx `tts-models` release) goes in
  `app\models\` on first use (`get_model`, from "▶ Hear it" or "Make audiobook"; the updater can't
  install it). `READALOUD_MODEL` points elsewhere (dev), `READALOUD_FAKE_VOICE=1` swaps in a tone
  (tests). `VOICES` is the English list worth hearing, with the model's speaker numbers (checked in
  `test_every_voice_is_in_the_model`). British voices use the gb lexicon with espeak-ng's `"en"`:
  there is no `"en-gb"` voice, and with it every British line came out silent (caught before
  release; `test_every_voice_really_speaks` runs when the model is on the PC, and `say_text`
  refuses to leave a silent gap where there were words).
- **Speed** (owner's PC, Ryzen 7 260, 16 threads): one voice with 8 threads reads ~4x real time,
  two with 4 threads each ~5.5x together, four ~5x (`workers_for_pc`: cores/5, at most 3, 4
  threads each, ~1.5 GB free memory each). A 10-hour book takes about 2 hours. Workers run at below-normal priority so the PC stays usable. The GPU
  build (`sherpa-onnx==1.13.8+cuda12.cudnn9` + 2.4 GB of NVIDIA pip packages) was tried on the RTX
  5070: ~14x real time after a 60 s first-run compile, and that build skipped words missing from
  the lexicon ("lived", "waited"). Not worth it yet.
- **Text** (`load_book`): EPUB/PDF/TXT through `cleanread.Book` (chapters from the TOC), .docx by
  its Heading styles. Cover and series (calibre:series / belongs-to-collection) from the OPF.
  `speakable()`: plain quotes, dashes as commas, "Chapter IV" -> "Chapter 4", capitals read as
  words (`KEEP_CAPS` for acronyms), no URLs or [3] footnotes. `chunks()` splits sentences (not
  after Mr. or initials) and very long ones at commas (`MAX_CHUNK`). Pauses are fixed (`GAP_*`):
  each generated piece is trimmed of its own silence first. Contents, copyright, "Also by" and
  Project Gutenberg's licence start unticked (`SKIP_TITLES`, only when short: a whole story once
  sat under "List of Illustrations"). A heading-only "Part One" joins the next chapter.
- **Job** (`APP_DATA\readaloud\<key>`, key = book + voice + speed + chapters): `job.json`,
  `chapters.json`, `cover.*`, one `chNNNN.m4a` per chapter (AAC 64k mono, written through a `~`
  temp name), a `stop` file = stop. Closing the window or "Stop for now" keeps the chapters; the
  start page offers "Carry on" (`unfinished_jobs`). `assemble()` joins them with `-c copy`,
  `write_ffmeta` chapters, `m4b_tags`, the cover as attached_pic (left off if ffmpeg refuses it),
  optional MP3 chapter files (`<book> - chapters`); then the job folder is deleted.
- **Where it goes:** next to the ebook, or a chosen folder (starts from CleanListen's
  `save_places.json` `m4b_dir`), optionally Audiobookshelf's `Author\Series\Book 2 - Title`
  (`E.abs_folder`), series and number editable.
- Checked by listening back with Parakeet: a whole chapter matched the book's words 98% (the
  rest: names, dialect, "lunch basket").
- **PDFs** (1.16.0; Lauren's Vermilion.pdf, an Internet Archive scan of a 1981 book: "it reads
  things its not supposed too, and its very stilted"): `read_pdf` reads page by page with pypdf.
  Running heads ("Phyllis A. Whitney 11", "12 Vermilion": the same letters on 6%+ of pages, fuzzy
  for scan errors) and page numbers go; lines join into paragraphs (a paragraph ends on a short
  line ending in punctuation; every printed line had been its own paragraph, read as a fragment
  with a pause: that was the stilted sound); words split at a line end are joined (`join_lines`,
  `mend_words`; the voice's lexicon, 178k words but missing many -ed/-ing forms, tells "guest-
  house" from "know- ing"); glued words are split (`unglue`: "inmy", "she'dbeen", "/ was").
  Chapters: a "Chapter 3" line, or a short page with no running head whose next page has one
  (found all 16 of Vermilion's). Before the first chapter = "Front matter", after "(continued
  from front flap)" = "Book jacket", both unticked. Title/author from the PDF's metadata
  (`_pdf_author`: "Whitney, Phyllis A., 1903-2008"). `mend_paragraphs` joins mid-sentence breaks
  in every format. No cover in the file (Vermilion's is JPEG 2000) -> `cover_online` (CleanListen's
  `find_cover_online`). The sample ("Hear it") joins sentences, so it never showed the problem.
- **Reading director** (`readaloud_ai.py`, 1.16.0; Lauren: "have claude or chat go through the book -
  remove anything that shouldn't be read, look at the context of the book and give the reading
  directions"): optional card 3, Claude / ChatGPT / Gemini through `cleanlisten_claude.run` (the
  family's own plan; `PROVIDER` set for the book only, not saved as CleanListen's choice). A cast
  pass on the opening (first person? who; characters with gender/age; names to pronounce; tone),
  then ~2500-word parts, 3 at a time, listing only paragraphs that need something: skip, fix (only
  taken when `same_words`: same words, scanning repairs only), speakers of each quoted speech,
  pace (slower 0.92 / faster 1.07) and pause (short / long / scene). Answers are cached per book +
  chapters + provider (`readaloud/direction/<key>`), so another voice or Carry on never asks again.
  `apply` writes directed items `[kind, text, {"v": voice, "s": pace, "g": pause}]`; with "Give
  the characters their own voices" quotes are split (`split_quotes`, an open quote runs to the
  paragraph end) and cast by gender within the narrator's accent; a first-person narrator's own
  speech keeps the narrator's voice. Never skips a paragraph over 150 words. Respellings only for
  words the voice doesn't know ("Sybil" -> "sib-ul" sounded worse). A report of everything left
  out / fixed / not taken goes to `APP_DATA\readaloud_reports\<title> - what was changed.txt`
  (link on the done page). Vermilion chapter 1: 41 s with Opus; a novel ~10 minutes. Kokoro can't
  act an emotion on request, so mood only sets the pace.
- **Carry on after "Stop for now"** (fixed in 1.16.0): the stop note stayed, so every worker
  stopped at once and the book was put together with chapters missing ("Impossible to open
  ch0000.m4a"). `Maker.run` clears it, and refuses to assemble with a chapter missing.
- **Four readers, chosen per book** (`readaloud_gpu.py`, 1.17.0; Lauren: "our choice of voices is
  still cheap", then after four test clips: "I do like the qwen acting better....could we have all 4
  versions? let me choose by book"). `job["reader"]`: `kokoro` (Quick, above), `acting` (Qwen3-TTS
  1.7B VoiceDesign: every line gets the voice's description + the director's acting note +
  pace words as its `instruct`), `steady` (Qwen3-TTS 1.7B Base, copies the voice clip: never
  drifts, no acting), `chatterbox` (Resemble AI, MIT: copies the clip, `feel` -> exaggeration
  0.4/0.5/0.7). All Apache/MIT. The three new ones need an NVIDIA card with 6 GB+ and driver 570+
  (`gpu_check`, CUDA 12.8 PyTorch; the RTX 5070 Laptop is Blackwell, sm_120, so cu128 or newer, and
  its driver 572.97 can't run cu130). They live in their own venv, `APP_DATA\gpu\venv`, made by
  `install()` from the "Set up" button (the base Python of CleanListen's venv; pip with
  `readaloud_gpu_req.txt`, the exact versions tested together, ~3 GB; then the reader's model from
  Hugging Face into `APP_DATA\gpu\hf`, ~4 GB each). Qwen and Chatterbox share the venv only with
  transformers 4.57.3 and numpy 1.26.4 (Chatterbox alone pulls transformers 5). Markers:
  `software.ready` (holds the req file's text, so changing it sets the software up again) and
  `<reader>.ready`.
  - Voices: 18 clips `rv_<id>.flac` (shipped, in `version.json`), designed once with VoiceDesign
    from `GPU_VOICES` descriptions (best of 3 takes by listening back); `steady`/Chatterbox copy the
    clip, `acting` gets the same description, so a voice sounds alike in all three. "Hear it" plays
    the clip (the models take ~60 s to load). Characters are cast by gender + age + accent
    (`readaloud_ai.gpu_pool`: Marilla, 9 -> Lily).
  - Reading: `Maker` runs one worker in the gpu venv (`readaloud_gpu.py speak <job> <chapters>`)
    that loads the model once and reads the chapters in turn, a few paragraphs per batch (acting 4
    lines at once: 7 at once was 0.8x real time but needed 10 GB). Speed = ffmpeg `atempo`.
    Every line is listened to with CleanListen's Parakeet and read again (3 tries, best kept) when
    `check()` finds a doubled word, a dropped word in a short line, extra words, or mostly
    different words; respelled names, spelling ("racetracks", "Lindsey") and numbers ("25") don't
    count (`_alike`; before that, good lines were read three times). Re-reads are logged in the
    job's `relisten.txt`. Careful when checking by ear with `cleanlisten.transcribe` on a whole
    file: its 30 s chunks with 2 s overlap double a word at every seam (29 s, 57 s, 85 s...), which
    first looked like the voices doubling words ("knew knew"); listen with two chunk sizes.
  - Speed on the owner's laptop, end to end (model load, listening back): acting 0.85x real time
    (4 lines at once), Chatterbox ~1x, steady ~0.45x; a 10-hour book is ~10-24 hours: "start it
    at night".
  - Names for these voices: a lowercase respelling only for names the lookup marks `tricky`
    (Tlaquepaque); "Marilla" respelled "muh-ril-uh" came out "Mafrilla", and as written it's right.
- **Director 2** (1.17.0, `DIRECTION_VERSION` "2", so 1.16 answers are asked again): every
  paragraph is listed with an acting note (`delivery`, `speech_delivery` per quote) and `feel`
  (calm / warm / strong); characters get a `manner` ("deep, steady"). Items carry `"m"` (note),
  `"x"` (feel), `"who"`; Kokoro ignores them. Names are looked up in their own pass (`names()`,
  with WebSearch for Claude; 45 for Vermilion in 57 s: Tlaquepaque, Oraibi, Coconino, "Manila" =
  Marilla): Kokoro gets the sounds in its own symbols through a per-book lexicon read before its
  own (`names-lexicon.txt`; sherpa-onnx keeps the first entry for a word, and its diphthongs are
  capitals: A I O W Y), the Qwen/Chatterbox voices get a lowercase respelling (`job["respell"]`)
  for words not in the dictionary. Pieces of a paragraph in the same voice ("I'm all right," I
  said... "I'm listening.") are read in one go, not three.
- Ideas: a queue of several books; "clean it first" straight from CleanRead's filters (for now:
  clean in CleanRead, then choose the clean copy); flash-attention on Windows for the Qwen voices
  (2x); a narrator voice designed by the director to fit the book.

## 10. Working with Lauren

She's busy, direct and not a programmer. Explain in plain words, one step at a time; say what
changed and what she needs to do ("click Check for updates"). She tests on her PC and sends
screenshots or refined exports. Don't guess about her rules — they're in §5, and when an export
shows a new pattern, say what you inferred so she can correct it.

**Sex drugs are sexual references** (1.15.1, from CleanView 1.18.15; Lauren, 2026-11-04): `sex_drug_spans` (Viagra, Cialis, Levitra, erectile dysfunction, little blue pill(s), boner/sex pill(s), aphrodisiac(s), Spanish fly; not "the blue pill" alone, which is The Matrix) adds passages to the "ref" kind in `analyze` and CleanRead's `_ref_hit`. They are not in the "sexual" word group, so they aren't muted on their own and CleanView's word check is unchanged. The AI descriptions (`AI_TYPES["ref"]`, Claude's `KIND_RULES["ref"]`) mention sex drugs and drugging someone for sex.

**Blue Ridge Sunrise** (1.15.3; Lauren, 2026-11-05: "its really bad..the flagging ... it doesn't seem to be learning, I think its getting worse" and "claude didn't change"). The report had 1,012 items, 902 of them unticked picks from the AI on this PC (677 "same-sex relationships" for ordinary lines, man-and-woman kisses as same-sex), none backed by the word lists. Fixes: (1) `_merge_ai`: with the final check, the AI on this PC's unbacked passages (`_ai_backed`) are left out where the final check read; where it couldn't (`st["claude_unchecked"]`) the AI works as alone. (2) `cleanlisten_claude.review`: a failed section is tried once more (`RETRY_WAIT`); the ones still failing are noted ("N of M sections") and kept in `claude_unchecked`; if none could be read it's a failed check. (3) `cleanlisten_learn.record` learns only real choices: something offered unticked and left alone is not "kept" (it filled the 600-sentence memory). (4) `examples()` gives the AIs her choices and the shared ones, not Claude's own past answers (Claude was learning from itself). Learning still matches whole sentences, so on a new book it shows through the examples, not as unticks. `ollama_care.CLEAN_APPS` also counts CleanView's `videoqueue.py`.

**Long review lists and PNG covers** (1.15.4, 2026-11-05). (1) "screen is messed...hasn't changed in awhile": Windows draws no window taller than 32,767 px, and the review list was one frame in the canvas, so Sweetbriar Cottage (290 passages, 38 words) went blank part way down. `_scroll_area(stacked=True)` returns `block()`, which gives the frame for the next thing: blocks of `BLOCK_ITEMS` (40) cards, words in boxes of `WORDS_PER_BOX` (50), stacked as separate canvas windows. `layout()` positions them and also runs when the view moves and every 300 ms (blocks out of view change size without an event), keeps the view inside the list, and does nothing when nothing changed. `_y_in_list` adds the block's position; `_list_height()` is the whole height. `_jump_to` aims again as cards settle. Checked in the real window with 800 passages (97,000 px) and 400 passages + 300 words. (2) Nearly Free: "[ipod] Could not find tag for codec png": an M4B (ffmpeg's ipod format) takes only JPG covers. `cover_file` now makes every cover a JPG (`_jpeg_cover`, `JPG_COVER`), the online cover goes through it, and `retag_m4b` turns a book's own PNG cover into a JPG.

**Covers at the save stage** (1.15.5, 2026-11-05). Nearly Free still failed on 1.15.4 ("codec not currently supported in container"): its file had a PNG cover plus a second picture track, and `retag_m4b` mapped every picture. Now it keeps only the audio plus one JPG cover (the one chosen, else the book's own, `_picture_to_jpeg`); `_cover_stream` also finds a picture not marked as the cover; errors show ffmpeg's first lines (`ffmpeg_says`). Lauren: "I need to be able to choose the picture if 2 accidentally got placed...I don't want to have to start over when I'm already at the save stage": `choose_cover()` (a window of thumbnails from `engine.book_pictures`: each picture in the book, saved as JPGs in the job's `pictures` folder, then the folder's pictures; Choose another; drag one in) from the review page's "M4B cover: ... Change cover..." line and from a stopped save's row ("Change cover..." next to Try again). The pick goes in the job's `cover`. Thumbnails are kept in `APP_DATA/covers/small`, never next to the picture.

**Stuck on save** (1.15.6, 2026-11-05: "cleanListen has been stuck on my computer all day"). Vermilion (one M4B, AAC mono 24 kHz) sat on "Saving..." for 10 hours: the bundled ffmpeg's AAC encoder in its default ("twoloop") mode loops forever on two seconds of that book (0:00.64), at any bitrate; decoding, MP3, stereo 44.1 kHz and `-aac_coder fast` are fine, and synthetic mono 24 kHz is fine too, so it's that audio. Every AAC encode now uses `AAC` (`-aac_coder fast`), and the save and M4B encodes run through `run_watched(cmd, out_file)`: if the output file hasn't grown for `STALL_SECONDS` (15 min), ffmpeg is stopped and the save fails with a message instead of hanging. (`readaloud.py` still encodes with the default mode.)

**CleanRead's window like the others** (1.16.1; Jason, 2026-11-06: "Clean read doesn't have anything on top that says current version like clean view", "No check for update button", "The other 2 say start cleaning"). Every page has "v1.16.1 · Check for updates" at the top right (as CleanListen); the start page has "↻ Check for updates" bottom left (as CleanView); the main button says "Start cleaning" ("Start checking" when the choice is Check the content). `check_updates` loads launcher.pyw and runs its `update()` (CleanRead updates with CleanListen), then opens CleanRead again through `launcher.pyw read` (asks first when not on the start page; not while a book is being read).

**Santa places** (1.16.1, from CleanView 1.18.20; Jason, That Thing You Do): "Santa" before a place name (`SANTA_PLACES`: Santa Anita, Monica, Barbara, Fe, Cruz...) and "Christmas Island" aren't the holiday in `TOPIC_WORDS["holiday"]` (CleanRead uses the same via `topic_hit`), and the AI descriptions say so (`AI_TYPES`, Claude's `KIND_RULES`). "Santa Claus", "Santa!", "Jiminy Christmas" still count.
