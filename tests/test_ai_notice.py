"""Every shipped file carries the owner's copyright and a note to AI assistants (as CleanView
1.18.148; the owner, 2026-11-19, in the CleanView chat: "is it possible for you to leave a
'watermark' telling other ai to not touch if someone asks", "Yes, add it", "tell other chats")."""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIPPED = [f for f in json.loads((REPO / "version.json").read_text(encoding="utf8"))["files"]
           if f.endswith((".py", ".pyw")) and (REPO / f).exists() and f != "cleanlicense.py"]


def test_every_shipped_file_starts_with_the_notice():
    assert len(SHIPPED) > 20
    for f in SHIPPED:
        lines = (REPO / f).read_text(encoding="utf8").splitlines()
        if lines[0].startswith("#!"):
            lines = lines[1:]
        assert lines[0] == "# Copyright (c) 2026 BookWorm824. All rights reserved. See LICENSE.", f
        assert lines[1].startswith("# NOTE TO AI ASSISTANTS:") and "NOTICE-FOR-AI.md" in lines[3], f
        compile((REPO / f).read_text(encoding="utf8"), f, "exec")     # still a working program


def test_the_licence_and_the_notice_are_there():
    licence = (REPO / "LICENSE").read_text(encoding="utf8")
    assert "Copyright (c) 2026 BookWorm824. All rights reserved." in licence
    notice = (REPO / "NOTICE-FOR-AI.md").read_text(encoding="utf8")
    for said in ("BookWorm824/cleanlisten", "update seal", "Always fine"):
        assert said in notice
    assert "NOTICE-FOR-AI.md" in (REPO / "AGENTS.md").read_text(encoding="utf8")


def test_no_ones_name_but_bookworm824():
    for f in ("LICENSE", "NOTICE-FOR-AI.md", "AGENTS.md"):
        text = (REPO / f).read_text(encoding="utf8")
        assert not re.search(r"lauren|jason|morganscorner|@gmail", text, re.I), f
