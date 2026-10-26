# Development helpers (not shipped to users)

Used while building CleanListen on Linux; see CLAUDE.md section 8.

- `fakeclaude/claude`, `fakeclaude/codex`: stand-ins for Claude Code and Codex. Put the folder
  first on PATH; they return schema-shaped answers (a trim for long passages, "just the word"
  for "loser", a chat reply that trims the highlighted sentence, ...) and log calls to
  `$FAKE_CLAUDE_LOG`.
- `fakeai/cleanview_ai.py`: stand-in for the Ollama helper; put `dev/fakeai` first on sys.path.
- `make_test_audio.py [piper_voice_dir]`: makes `test/Bully Folder/Chapter Nine.mp3` (bullying,
  flirting, "screw you", innocent "screw"/"idiot" lines) with sherpa-onnx TTS.
- `gui_test_learning.py`, `gui_test_ask_and_export.py`: scripted GUI runs, e.g.
  `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 144" python3 dev/gui_test_learning.py`.
  They expect `test/appdataNN/` (a LOCALAPPDATA copy with the chapter already transcribed) and
  were written against the development folder layout, so adjust paths before running.
