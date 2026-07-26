"""Tests for batch NLP refresh across all processed text outputs."""
from __future__ import annotations

from pathlib import Path

import yaml

import kb_ingest
import kb_nlp_batch


def test_batch_processes_markdown_and_transcripts(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\n",
        encoding="utf-8",
    )
    markdown = tmp_path / "processed" / "markdown" / "article.md"
    transcript = tmp_path / "processed" / "transcripts" / "interview.md"
    markdown.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    markdown.write_text("Article body\n", encoding="utf-8")
    transcript.write_text("Interview body\n", encoding="utf-8")

    monkeypatch.setattr(
        kb_ingest,
        "nlp_enrich",
        lambda text, cfg, knowledge_dir: {"source_text": text.strip()},
    )

    assert kb_nlp_batch.main(["--root", str(tmp_path)]) == 0
    nlp_dir = tmp_path / "processed" / "nlp-meta"
    assert yaml.safe_load((nlp_dir / "article.yml").read_text(encoding="utf-8")) == {
        "source_text": "Article body"
    }
    assert yaml.safe_load(
        (nlp_dir / "interview.yml").read_text(encoding="utf-8")
    ) == {"source_text": "Interview body"}
