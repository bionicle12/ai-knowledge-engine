"""Tests for batch NLP refresh across all processed text outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import kb_ingest
import kb_nlp_batch


@pytest.fixture
def base(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        kb_ingest,
        "nlp_enrich",
        lambda text, cfg, knowledge_dir: {"source_text": text.strip()},
    )
    return tmp_path


def _processed(root: Path, rel: str, text: str, **metadata) -> Path:
    path = root / "processed" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if metadata:
        meta_path = root / "processed" / "extracted-metadata" / f"{path.stem}.yml"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"processed_path": f"processed/{rel}", "nlp_meta_path": None, **metadata}
        meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return path


def _nlp_meta(root: Path, stem: str) -> dict:
    return yaml.safe_load((root / "processed" / "nlp-meta" / f"{stem}.yml").read_text(encoding="utf-8"))


def test_batch_processes_markdown_and_transcripts(base: Path):
    _processed(base, "markdown/article.md", "Article body\n")
    _processed(base, "transcripts/interview.md", "Interview body\n")

    assert kb_nlp_batch.main(["--root", str(base)]) == 0
    article = _nlp_meta(base, "article")
    assert article["source_text"] == "Article body"
    assert article["source"] == "processed/markdown/article.md"  # same shape as ingest's nlp-meta
    assert article["processed_at"]
    assert _nlp_meta(base, "interview")["source_text"] == "Interview body"


def test_nlp_disabled_in_config_writes_nothing(base: Path, capsys):
    """L5: the batch used to ignore `nlp.enabled: false`."""
    (base / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\nnlp:\n  enabled: false\n", encoding="utf-8"
    )
    _processed(base, "markdown/article.md", "Article body\n")
    assert kb_nlp_batch.main(["--root", str(base)]) == 0
    assert "nlp.enabled is false" in capsys.readouterr().out
    assert not (base / "processed" / "nlp-meta").exists()
    assert not (base / "log.md").exists()


def test_refresh_records_nlp_meta_path_in_ingest_metadata(base: Path):
    """L5: a new nlp-meta file is linked from the file's extracted-metadata entry."""
    _processed(base, "markdown/article.md", "Article body\n", file_type="docx", strategy="docx")
    assert kb_nlp_batch.main(["--root", str(base), "--incremental"]) == 0
    metadata = yaml.safe_load(
        (base / "processed" / "extracted-metadata" / "article.yml").read_text(encoding="utf-8")
    )
    assert metadata["nlp_meta_path"] == "processed/nlp-meta/article.yml"
    assert metadata["file_type"] == "docx"  # the rest of the entry is kept


def test_skip_extensions_and_archive_listings_get_no_nlp(base: Path, capsys):
    """Same rule as ingest: `nlp.skip_extensions` and archive listings skip NLP."""
    _processed(base, "tables/sheet.md", "| a |\n", file_type="csv", strategy="csv")
    _processed(base, "markdown/bundle.md", "# Archive\n", file_type="zip", strategy="archive")
    _processed(base, "markdown/note.md", "Note\n", file_type="txt", strategy="passthrough")
    (base / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\nnlp:\n  skip_extensions: ['.CSV', xlsx]\n",
        encoding="utf-8",
    )
    assert kb_nlp_batch.main(["--root", str(base), "--json"]) == 0
    rows = {row["processed_path"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["processed/tables/sheet.md"]["reason"] == "nlp.skip_extensions (.csv)"
    assert rows["processed/markdown/bundle.md"]["reason"] == "archive listing"
    assert rows["processed/markdown/note.md"]["nlp_meta_path"] == "processed/nlp-meta/note.yml"
    assert sorted(p.name for p in (base / "processed" / "nlp-meta").iterdir()) == ["note.yml"]


def test_not_a_knowledge_base_is_refused(tmp_path: Path, capsys):
    """M11: a wrong --root used to grow processed/nlp-meta/ (and log.md) anywhere."""
    stray = tmp_path / "not-a-base"
    (stray / "processed" / "markdown").mkdir(parents=True)
    (stray / "processed" / "markdown" / "x.md").write_text("x\n", encoding="utf-8")
    assert kb_nlp_batch.main(["--root", str(stray)]) == 2
    assert "not a knowledge base" in capsys.readouterr().err
    assert not (stray / "processed" / "nlp-meta").exists()
    assert not (stray / "log.md").exists()


def test_relative_root_from_inside_the_base_makes_no_phantom_base(base: Path, monkeypatch):
    """M11: cwd=<base> plus --root <base name> used to create <base>/<base>/processed/."""
    _processed(base, "markdown/article.md", "Article body\n")
    monkeypatch.chdir(base)
    assert kb_nlp_batch.main(["--root", base.name]) == 2
    assert not (base / base.name).exists()
    monkeypatch.chdir(base.parent)
    assert kb_nlp_batch.main(["--root", base.name]) == 0
    assert _nlp_meta(base, "article")["source_text"] == "Article body"


def test_incremental_run_with_nothing_new_does_not_log(base: Path):
    _processed(base, "markdown/article.md", "Article body\n")
    assert kb_nlp_batch.main(["--root", str(base), "--incremental"]) == 0
    log = (base / "log.md").read_text(encoding="utf-8")
    assert "nlp-batch" in log
    assert kb_nlp_batch.main(["--root", str(base), "--incremental"]) == 0
    assert (base / "log.md").read_text(encoding="utf-8") == log


def test_stale_nlp_meta_of_skipped_files_is_removed(base: Path, capsys):
    """Older batches wrote nlp-meta (without `source`) for skip_extensions files
    and archive listings; --incremental used to keep it as 'already exists'."""
    (base / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\nnlp:\n  skip_extensions: [csv]\n", encoding="utf-8"
    )
    _processed(base, "tables/sheet.md", "| a |\n", file_type="csv", strategy="csv",
               nlp_meta_path="processed/nlp-meta/sheet.yml")
    _processed(base, "markdown/bundle.md", "# Archive\n", file_type="zip", strategy="archive")
    nlp_dir = base / "processed" / "nlp-meta"
    nlp_dir.mkdir(parents=True)
    (nlp_dir / "sheet.yml").write_text("keywords: [a]\n", encoding="utf-8")
    (nlp_dir / "bundle.yml").write_text("keywords: [zip]\n", encoding="utf-8")

    assert kb_nlp_batch.main(["--root", str(base), "--incremental", "--json"]) == 0
    rows = {row["processed_path"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["processed/tables/sheet.md"]["reason"] == "nlp.skip_extensions (.csv); stale nlp-meta removed"
    assert rows["processed/markdown/bundle.md"]["reason"] == "archive listing; stale nlp-meta removed"
    assert list(nlp_dir.iterdir()) == []
    metadata = yaml.safe_load(
        (base / "processed" / "extracted-metadata" / "sheet.yml").read_text(encoding="utf-8")
    )
    assert metadata["nlp_meta_path"] is None


def test_nlp_meta_of_another_source_is_not_removed(base: Path):
    (base / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test-kb\nnlp:\n  skip_extensions: [csv]\n", encoding="utf-8"
    )
    _processed(base, "tables/sheet.md", "| a |\n", file_type="csv", strategy="csv")
    other = base / "processed" / "nlp-meta" / "sheet.yml"
    other.parent.mkdir(parents=True)
    other.write_text("source: processed/markdown/sheet.md\nkeywords: [a]\n", encoding="utf-8")
    assert kb_nlp_batch.main(["--root", str(base)]) == 0
    assert other.is_file()


def test_mark_extracted_during_nlp_is_not_undone(base: Path, monkeypatch):
    """Residual H5: the batch read the metadata before the slow NLP call and
    wrote that old copy back, undoing a concurrent --mark-extracted."""
    import contextlib

    import kb_common as kbc

    (base / "knowledge" / "domain").mkdir(parents=True)
    (base / "knowledge" / "domain" / "r.md").write_text("# R\n", encoding="utf-8")
    (base / "assets" / "documents").mkdir(parents=True)
    (base / "assets" / "documents" / "r.txt").write_text("r\n", encoding="utf-8")
    _processed(
        base, "markdown/r.md", "R body\n",
        asset_path="assets/documents/r.txt", strategy="passthrough", file_type="txt",
        extraction="pending", extracted_to=[],
    )
    locked: list[str] = []
    real_lock = kbc.kb_lock

    @contextlib.contextmanager
    def recording_lock(root, name="pipeline", timeout=600.0):
        with real_lock(root, name, timeout=timeout) as path:
            locked.append(name)
            yield path

    def slow_nlp(text, cfg, knowledge_dir):
        # What another process does while NLP is busy.
        kb_ingest.mark_extraction(base, "assets/documents/r.txt", pages=["domain/r.md"])
        return {"source_text": text.strip()}

    monkeypatch.setattr(kbc, "kb_lock", recording_lock)
    monkeypatch.setattr(kb_ingest, "nlp_enrich", slow_nlp)
    assert kb_nlp_batch.main(["--root", str(base)]) == 0
    meta = yaml.safe_load(
        (base / "processed" / "extracted-metadata" / "r.yml").read_text(encoding="utf-8")
    )
    assert meta["extraction"] == "done"
    assert meta["extracted_to"] == ["knowledge/domain/r.md"]
    assert meta["nlp_meta_path"] == "processed/nlp-meta/r.yml"
    assert locked.count("pipeline") == 1  # the metadata write is locked
