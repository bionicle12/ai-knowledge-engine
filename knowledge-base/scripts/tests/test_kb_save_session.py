"""Tests for session-summary saving."""
from __future__ import annotations

from pathlib import Path

import yaml

import kb_save_session


def _write_config(root: Path) -> None:
    (root / "kb.config.yml").write_text(
        """
knowledge_base:
  name: test-kb
  mode: super
language_policy:
  primary: ru
privacy:
  require_redaction_for_chats: true
""".strip(),
        encoding="utf-8",
    )


def test_save_session_writes_summary_file(tmp_path: Path):
    _write_config(tmp_path)

    code = kb_save_session.main(
        [
            "--root", str(tmp_path),
            "--title", "Fix extraction issues",
            "--summary", "Reprocessed a stuck PDF asset and checked session logging.",
            "--decision", "Install missing Python packages first.",
            "--processed", "assets/documents/2026-07-01__manual.pdf",
            "--tag", "maintenance",
        ]
    )
    assert code == 0

    sessions = list((tmp_path / "interactions" / "sessions").glob("*.md"))
    assert len(sessions) == 1

    text = sessions[0].read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["title"] == "Fix extraction issues"
    assert meta["redacted"] is True
    assert meta["source"] == "manual"
    assert "## Summary" in text
    assert "## Decisions" in text
    assert "## Processed Materials" in text
