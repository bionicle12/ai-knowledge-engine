"""Tests for kb_ingest reference pipeline."""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import subprocess
import sys
import tarfile
import types
import zipfile
from pathlib import Path, PureWindowsPath

import pytest
import yaml

import kb_common as kbc
import kb_ingest

SCRIPTS_DIR = Path(kb_ingest.__file__).resolve().parent
BASE_CONFIG = """
knowledge_base:
  name: test-kb
  mode: default
language_policy:
  primary: en
nlp:
  enabled: false
  spacy_model: en_core_web_md
  complexity_threshold: 0.7
""".strip() + "\n"


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    # Minimal config so kb_ingest knows what to do
    (tmp_path / "kb.config.yml").write_text(
        """
knowledge_base:
  name: test-kb
  mode: default
language_policy:
  primary: en
nlp:
  enabled: false
  spacy_model: en_core_web_md
  complexity_threshold: 0.7
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def test_init_dirs(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    for sub in ("raw", "processed", "knowledge", "assets", "assets-index", "review"):
        assert (kb_root / sub).is_dir()
    # Sub-folders
    assert (kb_root / "raw" / "documents" / "unsorted").is_dir()
    assert (kb_root / "processed" / "markdown").is_dir()
    assert (kb_root / "eval" / "results").is_dir()
    assert (kb_root / "knowledge" / "domain").is_dir()
    assert (kb_root / "review" / "needs-ai-decision").is_dir()
    assert (kb_root / "review" / "needs-heal").is_dir()
    assert (kb_root / "interactions" / "sessions").is_dir()
    assert (kb_root / "interactions" / "init").is_dir()
    assert (kb_root / "interactions" / "quiz").is_dir()
    # I16: the 07_INTERACTION_LOOP.md layout, and no raw/unsorted/unsorted/
    assert (kb_root / "interactions" / "insights").is_dir()
    assert (kb_root / "interactions" / "meta-reviews").is_dir()
    assert (kb_root / "raw" / "unsorted").is_dir()
    assert not (kb_root / "raw" / "unsorted" / "unsorted").exists()


def test_ingest_simple_md(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "Hello World.md"
    src.write_text("# Hello\n\nthis is content\n", encoding="utf-8")

    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0

    # Original removed from unsorted
    assert not src.exists()
    # Asset created
    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 1
    asset = assets[0]
    assert asset.name.endswith("__hello-world.md")
    # Processed copy
    processed = list((kb_root / "processed" / "markdown").glob("*.md"))
    assert len(processed) == 1
    # Metadata
    meta_files = list((kb_root / "processed" / "extracted-metadata").glob("*.yml"))
    assert len(meta_files) == 1
    meta = yaml.safe_load(meta_files[0].read_text(encoding="utf-8"))
    assert meta["original_filename"] == "Hello World.md"
    assert meta["source_hash"].startswith("sha256:")
    assert meta["asset_path"].endswith("__hello-world.md")
    # assets-index updated
    idx = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert "hello-world" in idx
    # log.md written
    assert (kb_root / "log.md").exists()
    log_text = (kb_root / "log.md").read_text(encoding="utf-8")
    assert "ingest |" in log_text


def test_ingest_failure_keeps_original_in_unsorted(kb_root: Path, monkeypatch):
    """A crash mid-pipeline must not strand a half-ingested file."""
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "keep-me.md"
    src.write_text("# body\n", encoding="utf-8")
    cfg = kbc.load_config(kb_root)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(kb_ingest, "_upsert_assets_index", boom)
    with pytest.raises(OSError):
        kb_ingest.process_one(src, root=kb_root, cfg=cfg, nlp_enabled=False)
    # Original still in place, no orphaned asset copy left behind
    assert src.exists()
    assert list((kb_root / "assets" / "documents").glob("*")) == []

    # Once the fault is gone, the same file ingests cleanly
    monkeypatch.undo()
    result = kb_ingest.process_one(src, root=kb_root, cfg=cfg, nlp_enabled=False)
    assert result.success
    assert not src.exists()
    assert len(list((kb_root / "assets" / "documents").glob("*"))) == 1


def test_upsert_assets_index_heading_prefix_not_lost(kb_root: Path):
    """A new block whose heading is a prefix of an existing one must be appended."""
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    idx = kb_root / "assets-index" / "documents.md"
    idx.write_text(
        "# Documents\n\n## 2026-08-13__foo-bar\n\n- Type: documents\n"
        "- Original: `assets/documents/2026-08-13__foo-bar.md`\n"
        "- Converted: none yet\n- Description: existing\n",
        encoding="utf-8",
    )
    asset = kb_root / "assets" / "documents" / "2026-08-13__foo.md"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text("# t\n", encoding="utf-8")

    kb_ingest._upsert_assets_index(kb_root, "documents", asset, None)

    text = idx.read_text(encoding="utf-8")
    assert "## 2026-08-13__foo-bar" in text  # old block intact
    assert "\n## 2026-08-13__foo\n" in text  # new block appended, not dropped


def test_ingest_idempotent(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "doc.md"
    src.write_text("content\n", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    # Drop the same content again
    src2 = kb_root / "raw" / "documents" / "unsorted" / "duplicate.md"
    src2.write_text("content\n", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    # Only one asset (second was a duplicate by hash)
    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 1


def test_ingest_routes_complex_to_review(kb_root: Path):
    """A long file with markers should be routed to review."""
    # Lower the complexity threshold so this test stays robust as we tune heuristics
    (kb_root / "kb.config.yml").write_text(
        """
knowledge_base:
  name: test-kb
  mode: default
language_policy:
  primary: en
nlp:
  enabled: false
  spacy_model: en_core_web_md
  complexity_threshold: 0.5
""".strip(),
        encoding="utf-8",
    )
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "long.md"
    # Build a long, "complex" body that triggers heuristics
    body = (
        "# Very long\n\n"
        + ("word " * 6000)
        + "\n\nHowever, this is a contradiction.\n"
        + "| h1 | h2 |\n" + "|---|---|\n" + ("| a | b |\n" * 20)
        + "\n42 numbers 99 here 7\n"
    )
    src.write_text(body, encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    review = list((kb_root / "review" / "needs-ai-decision").glob("*.md"))
    assert len(review) == 1, "long+complex content should land in review"


def test_complexity_heuristic_growth():
    short = kb_ingest.estimate_complexity("hi there")
    long_with_table = kb_ingest.estimate_complexity(
        "word " * 3000 + " however | a | b |\n" * 30 + "12 34 56"
    )
    assert long_with_table > short


def test_dry_run_does_not_move(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "x.md"
    src.write_text("body\n", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp", "--dry-run"])
    assert code == 0
    assert src.exists(), "dry-run must not touch source files"
    assert not list((kb_root / "assets" / "documents").glob("*.md"))


def test_skip_extensions_only_skips_nlp(kb_root: Path, monkeypatch):
    """H2/E-H4: nlp.skip_extensions used to leave tables in unsorted/ forever."""
    (kb_root / "kb.config.yml").write_text(
        """
knowledge_base:
  name: test-kb
  mode: default
nlp:
  enabled: true
  skip_extensions: [".csv", ".xlsx"]
""".strip(),
        encoding="utf-8",
    )
    enriched: list[str] = []

    def fake_nlp(text, cfg, knowledge_dir):
        enriched.append(text)
        return {"complexity": 0.0, "ner_engine": None}

    monkeypatch.setattr(kb_ingest, "nlp_enrich", fake_nlp)
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "data.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    note = kb_root / "raw" / "documents" / "unsorted" / "note.md"
    note.write_text("# note\n", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root)])
    assert code == 0
    assert not src.exists(), "the table is ingested"
    tables = list((kb_root / "processed" / "tables").glob("*.md"))
    assert len(tables) == 1
    assert "| a | b |" in tables[0].read_text(encoding="utf-8")
    # NLP ran for the note only
    assert enriched == ["# note\n"]
    assert not list((kb_root / "processed" / "nlp-meta").glob("*data*"))



# ---------------------------------------------------------------------------
# Long-book detection (PDFs/EPUBs/DOCX with >25k words → asset-only flow)
# ---------------------------------------------------------------------------


def test_looks_like_long_book_short_text_is_false():
    assert kb_ingest._looks_like_long_book(
        ext=".pdf", processed_text="just a short note"
    ) is False


def test_looks_like_long_book_long_pdf_is_true():
    long_text = "word " * 30_000
    assert kb_ingest._looks_like_long_book(
        ext=".pdf", processed_text=long_text
    ) is True


def test_looks_like_long_book_many_pdf_pages_with_collapsed_spacing_is_true():
    collapsed_pages = "\n\n".join(
        f"## Page {i}\n\n" + ("A" * 1800) for i in range(1, 121)
    )
    assert kb_ingest._looks_like_long_book(
        ext=".pdf", processed_text=collapsed_pages
    ) is True


def test_looks_like_long_book_long_epub_is_true():
    long_text = "word " * 26_000
    assert kb_ingest._looks_like_long_book(
        ext=".epub", processed_text=long_text
    ) is True


def test_looks_like_long_book_long_docx_is_true():
    long_text = "word " * 30_000
    assert kb_ingest._looks_like_long_book(
        ext=".docx", processed_text=long_text
    ) is True


def test_looks_like_long_book_other_ext_is_false():
    long_text = "word " * 30_000
    # Plain markdown drafts are not "books"
    assert kb_ingest._looks_like_long_book(
        ext=".md", processed_text=long_text
    ) is False


def test_looks_like_long_book_no_text_is_false():
    assert kb_ingest._looks_like_long_book(
        ext=".pdf", processed_text=None
    ) is False
    assert kb_ingest._looks_like_long_book(
        ext=".pdf", processed_text=""
    ) is False


def test_review_package_includes_long_book_hint_block():
    pkg = kb_ingest._build_review_package(
        asset_path="assets/documents/x.pdf",
        processed_path="processed/markdown/x.md",
        nlp_meta={},
        reason="looks like a long-form reference book",
        long_book_hint=True,
    )
    assert "Likely long-form reference book" in pkg
    assert "Recommended flow" in pkg
    # Runtime modules live in kb-docs/ of a deployed base (D5).
    assert "kb-docs/03_PIPELINE.md" in pkg
    assert "bookshelf" in pkg.lower()
    assert "voice" in pkg.lower()


def test_review_package_no_long_book_hint_when_flag_false():
    pkg = kb_ingest._build_review_package(
        asset_path="assets/documents/x.md",
        processed_path="processed/markdown/x.md",
        nlp_meta={},
        reason="complexity 0.85 >= threshold 0.7",
        long_book_hint=False,
    )
    assert "Likely long-form reference book" not in pkg
    assert "## What to do" in pkg


# ---------------------------------------------------------------------------
# Media (STT / OCR) + archive strategies
# ---------------------------------------------------------------------------


def test_strategy_mapping_media_and_archive():
    assert kb_ingest._detect_strategy(".m4a") == "stt"
    assert kb_ingest._detect_strategy(".mov") == "stt"
    assert kb_ingest._detect_strategy(".webm") == "stt"
    assert kb_ingest._detect_strategy(".webp") == "ocr"
    assert kb_ingest._detect_strategy(".tiff") == "ocr"
    assert kb_ingest._detect_strategy(".tgz") == "archive"
    assert kb_ingest._detect_strategy(".tar.gz") == "archive"
    assert kb_ingest._detect_strategy(".gz") == "unknown"
    assert kb_ingest._file_ext(Path("bundle.tar.gz")) == ".tar.gz"
    assert kb_ingest._detect_asset_type(".flac") == "media"
    assert kb_ingest._detect_asset_type(".tiff") == "images"
    assert kb_ingest._detect_asset_type(".tgz") == "archives"
    assert kb_ingest._detect_asset_type(".tar.gz") == "archives"


def test_strategy_mapping_rtf():
    assert kb_ingest._detect_strategy(".rtf") == "rtf"


def test_convert_dispatches_rtf_converter(tmp_path: Path, monkeypatch):
    source = tmp_path / "document.rtf"
    source.write_text(r"{\rtf1 Hello}", encoding="utf-8")
    monkeypatch.setattr(
        kb_ingest,
        "_convert_rtf",
        lambda path: "# Converted RTF\n",
        raising=False,
    )

    assert kb_ingest._convert("rtf", source) == ("# Converted RTF\n", "markdown")


def test_ingest_audio_without_backend_routes_to_review(kb_root: Path, monkeypatch):
    import kb_stt

    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    audio = kb_root / "raw" / "media" / "unsorted" / "note.mp3"
    audio.write_bytes(b"ID3 fake mp3 data not decodable")

    # Force "no STT backend" regardless of what's installed on the test machine
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: [])

    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    # Original safely stored as an asset
    assert list((kb_root / "assets" / "media").glob("*.mp3"))
    # Routed to review with an actionable, OS-specific install hint
    review = list((kb_root / "review" / "needs-ai-decision").glob("*.md"))
    assert len(review) == 1
    text = review[0].read_text(encoding="utf-8")
    assert "requirements-media.txt" in text


def test_ingest_zip_archive_extracts_members(kb_root: Path):
    import zipfile

    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    archive = kb_root / "raw" / "documents" / "unsorted" / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("sub/b.txt", "world")

    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0

    # Archive original moved to assets/archives
    assert list((kb_root / "assets" / "archives").glob("*.zip"))
    # Members unpacked (flattened) into the archive's own category and
    # ingested in the same run; nothing is left in unsorted/.
    names = [p.name for p in (kb_root / "assets" / "documents").glob("*.txt")]
    assert any(n.endswith("a.txt") for n in names)
    assert any(n.endswith("sub-b.txt") for n in names)
    assert not list((kb_root / "raw" / "documents" / "unsorted").iterdir())
    assert not (kb_root / "raw" / "unsorted" / "unsorted").exists()
    # A listing was written to processed/markdown; the archive itself needs
    # no extraction (its files are ingested one by one).
    listing = list((kb_root / "processed" / "markdown").glob("*bundle.md"))
    assert listing and "sub/b.txt" in listing[0].read_text(encoding="utf-8")
    meta = yaml.safe_load(
        next((kb_root / "processed" / "extracted-metadata").glob("*bundle.yml")).read_text(
            encoding="utf-8"
        )
    )
    assert meta["extraction"] == "skipped"
    assert meta["archive_extracted_files"] == 2


def test_ingest_routes_many_page_pdf_with_collapsed_spacing_to_review(
    kb_root: Path, monkeypatch
):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "book.pdf"
    src.write_bytes(b"%PDF-1.7 fake content")

    collapsed_pages = "\n\n".join(
        f"## Page {i}\n\n" + ("A" * 1800) for i in range(1, 121)
    )
    monkeypatch.setattr(
        kb_ingest,
        "_convert",
        lambda strategy, path: (collapsed_pages, "markdown"),
    )

    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0

    review = list((kb_root / "review" / "needs-ai-decision").glob("*.md"))
    assert len(review) == 1
    text = review[0].read_text(encoding="utf-8")
    assert "Likely long-form reference book" in text


def test_reprocess_existing_asset_creates_processed_output(kb_root: Path, monkeypatch):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])

    asset = kb_root / "assets" / "documents" / "2026-07-01__manual.pdf"
    asset.write_bytes(b"%PDF-1.7 fake content")
    stem = asset.stem

    metadata_path = kb_root / "processed" / "extracted-metadata" / f"{stem}.yml"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        yaml.safe_dump(
            {
                "original_filename": "manual.pdf",
                "stable_filename": asset.name,
                "asset_path": f"assets/documents/{asset.name}",
                "processed_path": None,
                "source_hash": kbc.compute_source_hash(asset),
                "file_type": "pdf",
                "asset_type": "documents",
                "strategy": "pdf",
                "processing_date": "2026-07-01T00:00:00+00:00",
                "extracted_at": "2026-07-01",
                "valid_from": "2026-07-01",
                "lifecycle": "evolving",
                "confidence": "medium",
                "complexity": 0.0,
                "is_surprise": True,
                "surprise_engine": "python",
                "long_book_hint": False,
                "needs_ai_review": True,
                "review_reason": "conversion unavailable: pypdf not installed",
                "nlp_meta_path": None,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    review_path = kb_root / "review" / "needs-ai-decision" / f"{stem}.md"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text("# placeholder\n", encoding="utf-8")

    monkeypatch.setattr(kb_ingest, "_convert", lambda strategy, src: ("# Extracted\n", "markdown"))

    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp", str(asset)])
    assert code == 0

    processed_path = kb_root / "processed" / "markdown" / f"{stem}.md"
    assert processed_path.is_file()
    assert processed_path.read_text(encoding="utf-8") == "# Extracted\n"

    meta = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert meta["processed_path"].endswith(f"{stem}.md")
    assert meta["needs_ai_review"] is False
    assert meta["review_reason"] == ""
    assert not review_path.exists()
    log_text = (kb_root / "log.md").read_text(encoding="utf-8")
    assert "NLP meta: —" in log_text
    assert "вЂ”" not in log_text


def test_upsert_assets_index_replaces_existing_windows_path_block(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])

    asset = kb_root / "assets" / "documents" / "2026-07-01__manual.pdf"
    asset.write_bytes(b"pdf")
    first_processed = kb_root / "processed" / "markdown" / "2026-07-01__manual.md"
    first_processed.parent.mkdir(parents=True, exist_ok=True)
    first_processed.write_text("v1\n", encoding="utf-8")

    kb_ingest._upsert_assets_index(kb_root, "documents", asset, first_processed)
    kb_ingest._upsert_assets_index(kb_root, "documents", asset, None)

    text = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert text.count("## 2026-07-01__manual") == 1
    # Paths in assets-index must be POSIX (stable across Windows/Linux/macOS).
    assert "assets/documents/2026-07-01__manual.pdf" in text
    assert "assets\\documents\\" not in text


def test_ingest_rejects_path_outside_unsorted(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    outside = kb_root / "outside.md"
    outside.write_text("# secret\n", encoding="utf-8")

    code = kb_ingest.main(["--root", str(kb_root), str(outside)])
    assert code == 1
    assert outside.exists()
    assert not any((kb_root / "assets").rglob("outside.md"))


def test_ingest_accepts_path_under_unsorted(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "ok.md"
    src.write_text("# ok\n", encoding="utf-8")

    code = kb_ingest.main(["--root", str(kb_root), str(src)])
    assert code == 0
    assert not src.exists()


# ---------------------------------------------------------------------------
# Audit 2026-09 regressions
# ---------------------------------------------------------------------------


def _unsorted(root: Path, category: str = "documents") -> Path:
    path = root / "raw" / category / "unsorted"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta(root: Path, pattern: str = "*.yml") -> list[dict]:
    return [
        yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted((root / "processed" / "extracted-metadata").glob(pattern))
    ]


def _ingest(root: Path, *extra: str) -> int:
    return kb_ingest.main(["--root", str(root), "--no-nlp", *extra])


def _config(root: Path, extra: str) -> None:
    (root / "kb.config.yml").write_text(BASE_CONFIG + extra, encoding="utf-8")


@pytest.fixture(autouse=True)
def _fresh_nlp_caches():
    for cached in (kb_ingest._spacy_pipeline, kb_ingest._rake, kb_ingest._keybert_model):
        cached.cache_clear()
    kb_ingest._WARNED.clear()
    yield
    for cached in (kb_ingest._spacy_pipeline, kb_ingest._rake, kb_ingest._keybert_model):
        cached.cache_clear()


def test_same_stem_different_extension_keeps_both(kb_root: Path):
    """C2: plan.md and plan.txt of one day shared processed/, metadata and index entry."""
    intake = _unsorted(kb_root)
    (intake / "plan.md").write_text("markdown plan\n", encoding="utf-8")
    (intake / "plan.txt").write_text("text plan\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    metas = _meta(kb_root)
    assert sorted(m["original_filename"] for m in metas) == ["plan.md", "plan.txt"]
    assert len({m["processed_path"] for m in metas}) == 2
    for m in metas:
        body = (kb_root / m["processed_path"]).read_text(encoding="utf-8")
        assert body == ("markdown plan\n" if m["original_filename"] == "plan.md" else "text plan\n")
        assert kbc.compute_source_hash(kb_root / m["asset_path"]) == m["source_hash"]
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert index.count("\n## ") == 2


def test_light_file_keeps_the_review_package_of_its_namesake(kb_root: Path):
    """C2: contract.txt (→ processed/) deleted the pending package of contract.odt."""
    intake = _unsorted(kb_root)
    (intake / "contract.odt").write_bytes(b"not convertible here")
    (intake / "contract.txt").write_text("short\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    packages = list((kb_root / "review" / "needs-ai-decision").glob("*.md"))
    assert len(packages) == 1
    text = packages[0].read_text(encoding="utf-8")
    assert "contract.odt" in text
    assert "no automatic converter for .odt files" in text


def test_failure_while_logging_rolls_back_and_rerun_ingests(kb_root: Path, monkeypatch):
    """H1: a crash after the metadata write made the file 'already ingested' forever."""
    src = _unsorted(kb_root, "reference") / "note.md"
    src.write_text("# note\n", encoding="utf-8")

    def boom(**kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(kbc, "append_log", boom)
    assert _ingest(kb_root) == 1
    assert src.exists()
    for sub in ("assets/documents", "processed/markdown", "processed/extracted-metadata"):
        assert not list((kb_root / sub).iterdir()), sub
    assert not (kb_root / "assets-index" / "documents.md").exists()

    monkeypatch.undo()
    assert _ingest(kb_root) == 0
    assert not src.exists()
    assert len(_meta(kb_root)) == 1


def test_asset_left_by_a_killed_run_is_finished_not_skipped(kb_root: Path):
    """H1: an asset copy without metadata blocked the file ('asset already exists')."""
    src = _unsorted(kb_root) / "doc.md"
    src.write_text("body\n", encoding="utf-8")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    day = dt.datetime.fromtimestamp(1_700_000_000).date().isoformat()
    orphan = kb_root / "assets" / "documents" / f"{day}__doc.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(src.read_bytes())  # copied, then the process was killed
    assert _ingest(kb_root) == 0
    assert not src.exists()
    [meta] = _meta(kb_root)
    assert meta["asset_path"] == f"assets/documents/{day}__doc.md"
    assert list((kb_root / "assets" / "documents").iterdir()) == [orphan]


def test_busy_pipeline_lock_stops_a_second_ingest(kb_root: Path, monkeypatch):
    """H5: watcher, hook and a manual run used to ingest the same files at once."""
    src = _unsorted(kb_root) / "doc.md"
    src.write_text("body\n", encoding="utf-8")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import kb_common as kbc\n"
            "with kbc.kb_lock(sys.argv[2], 'pipeline'):\n"
            "    print('locked', flush=True)\n"
            "    sys.stdin.read()\n",
            str(SCRIPTS_DIR),
            str(kb_root),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        monkeypatch.setattr(kb_ingest, "LOCK_TIMEOUT", 0.3)
        assert _ingest(kb_root) == 2
        assert src.exists()
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert _ingest(kb_root) == 0
    assert not src.exists()


def test_parallel_ingests_do_not_duplicate_or_fail(kb_root: Path):
    """H5: two concurrent runs produced duplicate assets and 'hashing failed' errors."""
    intake = _unsorted(kb_root)
    for i in range(20):
        (intake / f"note-{i:02d}.md").write_text(f"note {i}\n", encoding="utf-8")
    cmd = [sys.executable, str(SCRIPTS_DIR / "kb_ingest.py"), "--root", str(kb_root), "--no-nlp"]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    runs = [
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for _ in range(2)
    ]
    outputs = [run.communicate(timeout=180) for run in runs]
    assert [run.returncode for run in runs] == [0, 0], outputs
    assert len(list((kb_root / "assets" / "documents").iterdir())) == 20
    assert len(_meta(kb_root)) == 20


def test_registry_cache_skips_unchanged_metadata(kb_root: Path, monkeypatch):
    """H6: every ingest parsed every metadata file (O(N²) on a big base)."""
    intake = _unsorted(kb_root)
    for i in range(3):
        (intake / f"n{i}.md").write_text(f"n{i}\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    assert len(kb_ingest._load_registry(kb_root).records) == 3  # picks up the new files
    assert (kb_root / ".kb-state" / "ingest-registry.json").is_file()

    parsed: list[str] = []
    real = kb_ingest._read_metadata
    monkeypatch.setattr(
        kb_ingest, "_read_metadata", lambda path: parsed.append(path.name) or real(path)
    )
    assert len(kb_ingest._load_registry(kb_root).records) == 3
    assert parsed == []
    md = sorted((kb_root / "processed" / "extracted-metadata").glob("*.yml"))[0]
    md.write_text(md.read_text(encoding="utf-8") + "importance: 7\n", encoding="utf-8")
    kb_ingest._load_registry(kb_root)
    assert parsed == [md.name]


def _fake_spacy(monkeypatch, ents: list[tuple[str, str]]) -> list[str]:
    loads: list[str] = []

    def load(name):
        loads.append(name)
        return lambda text: types.SimpleNamespace(
            ents=[types.SimpleNamespace(text=t, label_=label) for t, label in ents]
        )

    monkeypatch.setitem(sys.modules, "spacy", types.SimpleNamespace(load=load))
    return loads


def test_nlp_models_load_once_and_fuzzy_resolution_links_pages(tmp_path: Path, monkeypatch):
    """H6: spacy.load ran for every file; L8: suggested_targets was always empty."""
    loads = _fake_spacy(monkeypatch, [("Docker Swarn", "PRODUCT"), ("Nobody Knows", "PER")])
    monkeypatch.setitem(sys.modules, "keybert", None)
    monkeypatch.setitem(sys.modules, "rake_nltk", None)
    knowledge = tmp_path / "knowledge"
    (knowledge / "domain").mkdir(parents=True)
    (knowledge / "domain" / "docker-swarm.md").write_text("# Swarm\n", encoding="utf-8")
    cfg = kbc.KbConfig(raw={}, root=tmp_path)
    first = kb_ingest.nlp_enrich("text one", cfg, knowledge)
    kb_ingest.nlp_enrich("text two", cfg, knowledge)
    assert loads == [cfg.spacy_model]
    assert first["ner_engine"] == "spacy"
    assert first["entities"][0]["canonical"] == "docker-swarm"
    assert first["entities"][0]["existing_page"] == "knowledge/domain/docker-swarm.md"
    assert first["unresolved_entities"] == ["Nobody Knows"]
    assert first["suggested_targets"] == [
        {"path": "knowledge/domain/docker-swarm.md", "reason": "linked entities: Docker Swarn"}
    ]


def test_rake_without_nltk_data_warns_once(tmp_path: Path, monkeypatch, caplog):
    """RAKE silently returned no keywords when the NLTK data was missing."""

    class Rake:
        def __init__(self, language="english"):
            raise LookupError("Resource stopwords not found")

    monkeypatch.setitem(sys.modules, "rake_nltk", types.SimpleNamespace(Rake=Rake))
    monkeypatch.setitem(sys.modules, "keybert", None)
    monkeypatch.setitem(sys.modules, "spacy", None)
    cfg = kbc.KbConfig(raw={}, root=tmp_path)
    with caplog.at_level(logging.WARNING, logger="kb_ingest"):
        assert kb_ingest.nlp_enrich("alpha beta", cfg, tmp_path)["keywords"] == []
        kb_ingest.nlp_enrich("gamma delta", cfg, tmp_path)
    warnings = [r for r in caplog.records if "nltk.downloader" in r.getMessage()]
    assert len(warnings) == 1


def test_cp1251_text_is_decoded_and_its_encoding_recorded(kb_root: Path):
    """M1: cp1251 text turned into U+FFFD without a warning."""
    src = _unsorted(kb_root, "work") / "zametka.txt"
    text = "Привет, мир! Это заметка о переговорах с поставщиком чая.\n"
    src.write_bytes(text.encode("cp1251"))
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert (kb_root / meta["processed_path"]).read_text(encoding="utf-8") == text
    assert meta["source_encoding"] == "cp1251"
    assert "Encoding: cp1251 (stored as UTF-8)" in (kb_root / "log.md").read_text(encoding="utf-8")


def test_semicolon_csv_becomes_a_valid_table(kb_root: Path):
    """M1: Excel-style CSV (';', cp1251) came out as one garbled column."""
    src = _unsorted(kb_root) / "prices.csv"
    src.write_bytes("товар;цена\nчай зелёный;100\nкофе;250\n".encode("cp1251"))
    assert _ingest(kb_root) == 0
    [table] = list((kb_root / "processed" / "tables").glob("*.md"))
    assert table.read_text(encoding="utf-8") == (
        "| товар | цена |\n|---|---|\n| чай зелёный | 100 |\n| кофе | 250 |\n"
    )


def test_archive_limits_and_long_member_names(kb_root: Path):
    """M2: no unpacked-size limits; a long Cyrillic member name crashed the archive."""
    _config(kb_root, "media:\n  archives:\n    max_member_mb: 0.001\n    max_total_mb: 0.003\n")
    long_name = "очень-длинное-имя-файла-из-архива-" * 5 + ".txt"
    archive = _unsorted(kb_root) / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("big.bin", b"x" * 2000)
        zf.writestr(long_name, "long name body")
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            zf.writestr(name, name[0] * 1000)
    assert _ingest(kb_root) == 0
    [bundle] = _meta(kb_root, "*bundle.yml")
    assert bundle["archive_extracted_files"] == 4  # long name + a, b, c
    notes = " ".join(bundle["archive_notes"])
    assert "big.bin: skipped" in notes
    assert "stopped at d.txt" in notes
    originals = [m["original_filename"] for m in _meta(kb_root) if m is not bundle]
    assert any(len(n.encode("utf-8")) <= 180 and n.endswith(".txt") and "очень" in n for n in originals)
    assert not any(n.endswith("big.bin") or n.endswith("d.txt") for n in originals)


def test_reprocessing_an_archive_does_not_refill_unsorted(kb_root: Path):
    """M2: every re-process left copies of the members in unsorted/ forever."""
    archive = _unsorted(kb_root) / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("b.txt", "world")
    assert _ingest(kb_root) == 0
    asset = next((kb_root / "assets" / "archives").glob("*.zip"))
    assert _ingest(kb_root, str(asset)) == 0
    assert kb_ingest._files_in_unsorted(kb_root) == []
    listing = next((kb_root / "processed" / "markdown").glob("*bundle.md"))
    assert listing.read_text(encoding="utf-8").count("already ingested") == 2


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX symlinks")
def test_symlinked_raw_folder_is_ingested(kb_root: Path, tmp_path_factory):
    """M3: raw/ as a symlink to a synced folder was 'outside raw/**/unsorted/'."""
    synced = tmp_path_factory.mktemp("dropbox") / "raw"
    (synced / "documents" / "unsorted").mkdir(parents=True)
    (kb_root / "raw").symlink_to(synced, target_is_directory=True)
    src = synced / "documents" / "unsorted" / "doc.md"
    src.write_text("body\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    assert not src.exists()
    assert len(_meta(kb_root)) == 1


def test_reprocess_keeps_description_and_extraction_record(kb_root: Path):
    """M4: re-processing replaced the agent's Description with the placeholder."""
    (_unsorted(kb_root) / "memo.md").write_text("Q3 memo\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    page = kb_root / "knowledge" / "domain" / "memo.md"
    page.write_text("# Memo\n", encoding="utf-8")
    kb_ingest.mark_extraction(kb_root, meta["asset_path"], pages=["domain/memo.md"])
    index = kb_root / "assets-index" / "documents.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "- Description: (to be filled by AI agent during review)",
            "- Description: Q3 pricing memo by the owner\n- Note: keep me",
        ),
        encoding="utf-8",
    )
    assert _ingest(kb_root, str(kb_root / meta["asset_path"])) == 0
    after = index.read_text(encoding="utf-8")
    assert "- Description: Q3 pricing memo by the owner" in after
    assert "- Note: keep me" in after
    assert "(to be filled" not in after
    assert "- Extracted knowledge: `knowledge/domain/memo.md`" in after
    assert after.count("\n## ") == 1
    [meta] = _meta(kb_root)
    assert meta["extraction"] == "done"
    assert meta["extracted_to"] == ["knowledge/domain/memo.md"]


def test_new_version_of_a_file_links_the_previous_one(kb_root: Path):
    """M5: three versions of pricing.md were three unrelated assets."""
    intake = _unsorted(kb_root, "work")
    (intake / "pricing.md").write_text("price v1: 10\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [v1] = _meta(kb_root)
    kbc.write_frontmatter_file(
        kb_root / "knowledge" / "domain" / "pricing.md",
        {"source": v1["asset_path"], "extracted_at": "2026-01-01", "lifecycle": "evolving"},
        "Price is 10.\n",
    )
    (intake / "pricing.md").write_text("price v2: 12\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    v2 = next(m for m in _meta(kb_root) if m["source_hash"] != v1["source_hash"])
    assert v2["previous_version"] == v1["asset_path"]
    assert v2["review_queue"] == "review/needs-ai-decision/"
    assert f"new version of {v1['asset_path']}" in v2["review_reason"]
    pkg = kb_root / "review" / "needs-ai-decision" / f"{Path(v2['asset_path']).stem}.md"
    assert "`knowledge/domain/pricing.md`" in pkg.read_text(encoding="utf-8")


def test_junk_nested_folders_and_duplicates(kb_root: Path):
    """M6: OS junk was ingested, subfolders were skipped, duplicates stayed forever."""
    intake = _unsorted(kb_root, "work")
    (intake / ".DS_Store").write_bytes(b"\x00junk")
    (intake / "~$report.docx").write_bytes(b"office lock")
    (intake / "report.md").write_text("adr queue\n", encoding="utf-8")
    (intake / "report-copy.md").write_text("adr queue\n", encoding="utf-8")
    nested = intake / "Project X"
    nested.mkdir()
    (nested / "nested.md").write_text("nested note\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    assert (intake / ".DS_Store").exists() and (intake / "~$report.docx").exists()
    assert sorted(m["original_filename"] for m in _meta(kb_root)) == ["nested.md", "report.md"]
    assert not nested.exists(), "the emptied subfolder is pruned"
    duplicate = kb_root / "raw" / "_duplicates" / "work" / "report-copy.md"
    assert duplicate.read_text(encoding="utf-8") == "adr queue\n"
    assert not (intake / "report-copy.md").exists()
    assert "ingest-duplicate | report-copy.md" in (kb_root / "log.md").read_text(encoding="utf-8")
    assert kb_ingest.collect_status(kb_root)["unsorted"]["total"] == 0


def test_complexity_without_ner_is_flagged(kb_root: Path):
    """M7: without NER the score can never reach 0.7 — now said in metadata and log."""
    (_unsorted(kb_root) / "n.md").write_text("plain words\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert "without NER" in meta["complexity_basis"]
    assert "Complexity: 0.00 (no NER)" in (kb_root / "log.md").read_text(encoding="utf-8")
    # I5: the surprise filter is not implemented, so no hardcoded is_surprise: true
    assert "is_surprise" not in meta and "surprise_engine" not in meta


def test_paths_are_posix_on_windows_too():
    """L1: metadata and JSON carried assets\\documents\\… on Windows."""
    assert kb_ingest._rel(
        PureWindowsPath(r"C:\kb\assets\documents\x.md"), PureWindowsPath(r"C:\kb")
    ) == "assets/documents/x.md"


def test_tar_gz_keeps_its_extension_and_reprocesses_as_archive(kb_root: Path):
    """L3: backup.tar.gz became …__backup-tar.gz and re-processed as 'gz, unknown'."""
    src = _unsorted(kb_root) / "backup.tar.gz"
    with tarfile.open(src, "w:gz") as tf:
        data = b"inside"
        info = tarfile.TarInfo("inside.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    payload = src.read_bytes()
    assert _ingest(kb_root) == 0
    [asset] = list((kb_root / "assets" / "archives").iterdir())
    assert asset.name.endswith("__backup.tar.gz")
    assert _ingest(kb_root, str(asset)) == 0
    [meta] = _meta(kb_root, "*backup.yml")
    assert (meta["file_type"], meta["strategy"]) == ("tar.gz", "archive")
    # An asset named by an older version is recognised by its magic bytes.
    legacy = kb_root / "assets" / "archives" / "2026-01-01__old-tar.gz"
    legacy.write_bytes(payload)
    assert _ingest(kb_root, str(legacy)) == 0
    [old] = _meta(kb_root, "2026-01-01__old-tar.yml")
    assert old["strategy"] == "archive"
    assert old["review_reason"] == ""


def test_date_in_the_file_name_wins_over_mtime(kb_root: Path):
    """L8 / E-Low: the stable name carried the ingest date, not the one in the name."""
    (_unsorted(kb_root) / "2026-09-15 meeting notes.md").write_text("notes\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["stable_filename"] == "2026-09-15__meeting-notes.md"


def test_extensionless_pdf_is_detected_by_magic_bytes(kb_root: Path, monkeypatch):
    """L8: 03 promised magic-byte detection; a file without extension went to review."""
    (_unsorted(kb_root) / "scan").write_bytes(b"%PDF-1.7 fake")
    monkeypatch.setattr(kb_ingest, "_convert_pdf", lambda path: "## Page 1\n\ntext\n")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["stable_filename"].endswith("__scan.pdf")
    assert meta["strategy"] == "pdf"
    assert (kb_root / meta["processed_path"]).read_text(encoding="utf-8") == "## Page 1\n\ntext\n"


def test_zip_based_documents_are_not_unpacked(kb_root: Path):
    """Magic-byte detection must not turn .epub/.pages (zip containers) into archives."""
    intake = _unsorted(kb_root)
    for name in ("book.epub", "slides.pages"):
        with zipfile.ZipFile(intake / name, "w") as zf:
            zf.writestr("content.xml", f"<{name}/>")
    assert _ingest(kb_root) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    assert set(metas) == {"book.epub", "slides.pages"}
    assert metas["book.epub"]["review_queue"] == "review/needs-ai-decision/"
    assert metas["slides.pages"]["review_queue"] == "review/needs-classification/"
    assert not any("archive" in m["strategy"] for m in metas.values())


def test_nlp_meta_records_its_source_and_time(kb_root: Path, monkeypatch):
    """L8: nlp-meta lacked the `source` and `processed_at` fields 12 documents."""
    _config(kb_root, "")
    (kb_root / "kb.config.yml").write_text(
        BASE_CONFIG.replace("enabled: false", "enabled: true"), encoding="utf-8"
    )
    monkeypatch.setattr(
        kb_ingest,
        "nlp_enrich",
        lambda text, cfg, knowledge_dir: {"language": "en", "ner_engine": None, "complexity": 0.1},
    )
    (_unsorted(kb_root) / "n.md").write_text("words\n", encoding="utf-8")
    assert kb_ingest.main(["--root", str(kb_root)]) == 0
    [meta] = _meta(kb_root)
    data = yaml.safe_load((kb_root / meta["nlp_meta_path"]).read_text(encoding="utf-8"))
    assert data["source"] == meta["processed_path"]
    assert data["processed_at"]


def test_private_chat_goes_to_redaction_without_leaking_its_name(kb_root: Path):
    """H3/D10/I15: chats went to processed/ and their transliterated names into
    the indexed assets-index/."""
    src = _unsorted(kb_root, "chats") / "Переписка с Иваном о долгах.txt"
    src.write_text("Иван: верни долг до пятницы\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["raw_category"] == "chats"
    assert meta["redaction"] == "pending"
    assert meta["review_queue"] == "review/needs-redaction/"
    assert meta["extraction"] == "pending"
    assert len(list((kb_root / "review" / "needs-redaction").glob("*.md"))) == 1
    neutral = "chats item " + meta["source_hash"].split(":")[1][:8]
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert f"## {neutral}" in index
    for leak in ("perepiska", "Переписка", meta["asset_path"]):
        assert leak not in index
    log = (kb_root / "log.md").read_text(encoding="utf-8")
    assert "perepiska" not in log and neutral in log
    # Resolving the review keeps the name out of the index.
    (kb_root / "knowledge" / "domain" / "debts.md").write_text("# Debts\n", encoding="utf-8")
    kb_ingest.mark_extraction(kb_root, meta["asset_path"], pages=["domain/debts.md"])
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert "privacy review done" in index and "perepiska" not in index
    assert "perepiska" not in (kb_root / "log.md").read_text(encoding="utf-8")
    assert _meta(kb_root)[0]["redaction"] == "resolved"


def test_secret_in_a_work_file_goes_to_redaction(kb_root: Path):
    """E-H3/D10: a GitHub token and a password went straight to processed/."""
    token = "ghp_" + "A1b2C3d4" * 5
    src = _unsorted(kb_root, "work") / "deploy-notes.md"
    src.write_text(f"# Deploy\nuse {token}\npassword=hunter22\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["review_queue"] == "review/needs-redaction/"
    reasons = " ".join(meta["redaction_reasons"])
    assert "GitHub token (line 2)" in reasons
    assert "password/secret assignment (line 3)" in reasons
    package = next((kb_root / "review" / "needs-redaction").glob("*.md")).read_text(encoding="utf-8")
    for value in (token, "hunter22"):
        assert value not in reasons and value not in package


def test_secret_scan_ignores_look_alikes():
    assert kb_ingest.find_secrets(
        "secret_scan: true\npassword: none\nsk-learn-compatible-wrapper\nSecretary: Anna Petrova\n"
    ) == []
    assert kb_ingest.find_secrets("client_secret = s3cr3t-value\n") == [
        "password/secret assignment (line 1)"
    ]
    assert kb_ingest.find_secrets("AWS AKIAABCDEFGHIJKLMNOP\n") == ["AWS access key (line 1)"]


def test_unknown_type_files_are_scanned_for_secrets(kb_root: Path):
    """D10/E-H3 re-review: keys, .env and JSON configs (no converter) skipped
    the secret scan and went to needs-classification under their real names."""
    intake = _unsorted(kb_root, "work")
    (intake / "id_rsa").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (intake / "deploy.pem").write_text("-----BEGIN PRIVATE KEY-----\nMIIE\n", encoding="utf-8")
    (intake / ".env").write_text("API_KEY=abc123def456\n", encoding="utf-8")  # no pattern: by name
    (intake / "config.json").write_text(
        '{"token": "ghp_' + "Z9y8X7w6" * 5 + '", "db": {"password": "s3cr3t!!"}}\n', encoding="utf-8"
    )
    (intake / "store.p12").write_bytes(b"\x30\x82\x0a\x00binary key store")
    (intake / "settings.yaml").write_text("theme: dark\npassword: ${DB_PASSWORD}\n", encoding="utf-8")
    (intake / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    secret = {"id_rsa", "deploy.pem", ".env", "config.json", "store.p12"}
    for name in secret:
        assert metas[name]["review_queue"] == "review/needs-redaction/", name
        assert metas[name]["redaction"] == "pending"
    assert "private key (line 1)" in " ".join(metas["id_rsa"]["redaction_reasons"])
    reasons = " ".join(metas["config.json"]["redaction_reasons"])
    assert "GitHub token" in reasons and "password/secret assignment" in reasons
    assert "credential file name" in " ".join(metas[".env"]["redaction_reasons"])
    for name in ("settings.yaml", ".env.example"):
        assert metas[name]["review_queue"] == "review/needs-classification/", name
    package = next((kb_root / "review" / "needs-classification").glob("*settings.md"))
    assert "hold credentials" in package.read_text(encoding="utf-8")
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    log = (kb_root / "log.md").read_text(encoding="utf-8")
    for name in secret:
        asset = metas[name]["asset_path"]
        assert f"## {kb_ingest._asset_key(asset)}\n" not in index, name
        assert f"`{asset}`" not in index and f"| {Path(asset).name}\n" not in log, name
        neutral = "work item " + metas[name]["source_hash"].split(":")[1][:8]
        assert f"## {neutral}" in index
    assert "s3cr3t" not in reasons and "abc123" not in log


def test_secret_scan_runs_in_linear_time():
    """D10 re-review: the password pattern backtracked catastrophically (a
    15 KB `a1-a1-…` file took 20 s under the pipeline lock), and every match
    recounted the lines from the start of the text."""
    import time

    # Sized so that the old code needs ~5-13 s for each (not hours).
    adversarial = [
        "a." * 6_000,
        "build ids: " + "a1-" * 5_000,
        "AKIAABCDEFGHIJKLMNOP " * 50_000,  # 1 MB, one line, 50k matches
        "password " * 10_000,
        "a_password" + " " * 50_000 + "x",
        "-----BEGIN " + "A " * 100_000,
        ("x" * 60 + "secret" + "y" * 60 + " ") * 1_600,
    ]
    start = time.perf_counter()
    for text in adversarial:
        kb_ingest.find_secrets(text)
    assert time.perf_counter() - start < 1.5
    assert kb_ingest.find_secrets("x\n" * 3 + "AKIAABCDEFGHIJKLMNOP\n" * 7) == [
        "AWS access key (lines 4, 5, 6, 7, 8, …)"
    ]


def test_secret_scan_patterns():
    hits = kb_ingest.find_secrets
    assert hits('{"password": "s3cr3t!!"}\n') == ["password/secret assignment (line 1)"]
    assert hits("-----BEGIN PGP PRIVATE KEY BLOCK-----\n") == ["private key (line 1)"]
    assert hits("DB_PASSWORD=supersecret123\n") == ["password/secret assignment (line 1)"]
    for benign in (
        'password: "{{ vault_db_password }}"',
        "password=$DB_PASSWORD",
        '"password": true',
        "passwordless: enabled",
        "-----BEGIN PUBLIC KEY-----",
    ):
        assert hits(benign + "\n") == [], benign


def test_duplicate_of_a_private_file_names_the_original_block(kb_root: Path):
    """D10 re-review: the ingest-duplicate entry pointed at `work item …`
    while the original's block is `chats item …`."""
    (_unsorted(kb_root, "chats") / "chat.txt").write_text("Ivan: pay me back\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    (_unsorted(kb_root, "work") / "copy.txt").write_text("Ivan: pay me back\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    digest = meta["source_hash"].split(":")[1][:8]
    assert f"## chats item {digest}" in (kb_root / "assets-index" / "documents.md").read_text(
        encoding="utf-8"
    )
    log = (kb_root / "log.md").read_text(encoding="utf-8")
    assert f"ingest-duplicate | work item {digest}" in log
    assert f"Same content as: chats item {digest}" in log
    assert "copy.txt" not in log


def test_archive_from_a_private_folder_is_listed_and_its_members_reviewed(kb_root: Path):
    """03 routing: the archive row comes first — the archive goes to processed/
    (extraction: skipped) and each member is checked, privacy included."""
    with zipfile.ZipFile(_unsorted(kb_root, "chats") / "export.zip", "w") as zf:
        zf.writestr("Chat with Ivan.txt", "Ivan: hi\n")
    assert _ingest(kb_root) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    archive = metas["export.zip"]
    assert (archive["review_queue"], archive["extraction"]) == (None, "skipped")
    [member] = [m for name, m in metas.items() if name != "export.zip"]
    assert member["raw_category"] == "chats"
    assert member["review_queue"] == "review/needs-redaction/"
    for index in (kb_root / "assets-index").glob("*.md"):
        text = index.read_text(encoding="utf-8")
        assert "ivan" not in text.lower() and "export" not in text


def test_set_category_neutralises_a_legacy_private_entry(kb_root: Path, capsys):
    """D10 re-review: bases ingested before 0.16 keep named blocks for their
    chats (no raw_category in the metadata, so nothing could neutralise them)."""
    (_unsorted(kb_root, "work") / "Переписка с Иваном о долгах.txt").write_text(
        "Иван: верни долг\n", encoding="utf-8"
    )
    assert _ingest(kb_root) == 0
    md_path = next((kb_root / "processed" / "extracted-metadata").glob("*.yml"))
    legacy = yaml.safe_load(md_path.read_text(encoding="utf-8"))
    del legacy["raw_category"]  # what a pre-0.16 ingest wrote
    md_path.write_text(yaml.safe_dump(legacy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    index_file = kb_root / "assets-index" / "documents.md"
    assert "perepiska" in index_file.read_text(encoding="utf-8")
    asset = str(kb_root / legacy["asset_path"])

    assert _ingest(kb_root, "--set-category", "chats", asset) == 0
    [meta] = _meta(kb_root)
    assert (meta["raw_category"], meta["redaction"]) == ("chats", "pending")
    assert meta["review_queue"] == "review/needs-redaction/"
    assert len(list((kb_root / "review" / "needs-redaction").glob("*.md"))) == 1
    index = index_file.read_text(encoding="utf-8")
    neutral = "chats item " + meta["source_hash"].split(":")[1][:8]
    assert f"## {neutral}" in index and "perepiska" not in index
    last_entry = (kb_root / "log.md").read_text(encoding="utf-8").split("\n## ")[-1]
    assert last_entry.startswith("[") and f"reprocess | {neutral}" in last_entry
    assert "perepiska" not in last_entry

    capsys.readouterr()
    outside = _unsorted(kb_root, "work") / "x.txt"
    outside.write_text("x\n", encoding="utf-8")
    assert _ingest(kb_root, "--set-category", "chats", str(outside)) == 2
    assert "works on files under assets/" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        _ingest(kb_root, "--set-category", "../chats", asset)
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        _ingest(kb_root, "--set-category", "chats")


def test_redaction_off_routes_chats_normally(kb_root: Path):
    _config(kb_root, "privacy:\n  require_redaction_for_chats: false\n")
    (_unsorted(kb_root, "chats") / "chat.txt").write_text("hi there\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["review_queue"] is None
    assert "redaction" not in meta
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert f"## {Path(meta['asset_path']).stem}" in index


def test_decision_text_gets_a_review_package(kb_root: Path):
    """I1: 'We decided to use PostgreSQL 16…' went to processed/ and was never extracted."""
    (_unsorted(kb_root, "work") / "db.md").write_text(
        "We decided to use PostgreSQL 16 for the ledger.\n", encoding="utf-8"
    )
    assert _ingest(kb_root) == 0
    [meta] = _meta(kb_root)
    assert meta["review_queue"] == "review/needs-ai-decision/"
    assert "decisions" in meta["review_reason"]
    assert meta["extraction"] == "pending"


def test_transcripts_and_long_chats_get_review_packages(kb_root: Path, monkeypatch):
    """I1/L8: the review triggers of 03 (transcripts, chats > 500 lines) were not implemented."""
    _config(kb_root, "privacy:\n  require_redaction_for_chats: false\n")
    monkeypatch.setattr(
        kb_ingest,
        "_run_stt",
        lambda src, cfg: ("# Transcript\n\nhello\n", "transcripts", {"stt_backend": "fake"}),
    )
    (_unsorted(kb_root, "media") / "call.mp3").write_bytes(b"ID3 fake")
    (_unsorted(kb_root, "chats") / "chat.txt").write_text(
        "\n".join(f"line {i}" for i in range(600)), encoding="utf-8"
    )
    assert _ingest(kb_root) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    assert "meeting/call transcript" in metas["call.mp3"]["review_reason"]
    assert "long chat export (600 lines)" in metas["chat.txt"]["review_reason"]


def test_mark_extracted_and_skipped_update_registry_index_and_log(kb_root: Path, capsys):
    """D3/I1/E-H2: processed/ items had no extraction record, so nothing picked them up."""
    intake = _unsorted(kb_root, "reference")
    (intake / "a.md").write_text("alpha\n", encoding="utf-8")
    (intake / "b.md").write_text("beta\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    assert all(m["extraction"] == "pending" and m["extracted_to"] == [] for m in metas.values())
    assert kb_ingest.collect_status(kb_root)["extraction_pending"] == 2

    (kb_root / "knowledge" / "domain" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    root = str(kb_root)
    assert kb_ingest.main(
        ["--root", root, "--mark-extracted", metas["a.md"]["asset_path"], "--to", "domain/alpha.md"]
    ) == 0
    assert kb_ingest.main(
        ["--root", root, "--mark-skipped", metas["b.md"]["processed_path"],
         "--reason", "says nothing new"]
    ) == 0
    metas = {m["original_filename"]: m for m in _meta(kb_root)}
    assert metas["a.md"]["extraction"] == "done"
    assert metas["a.md"]["extracted_to"] == ["knowledge/domain/alpha.md"]
    assert metas["b.md"]["extraction"] == "skipped"
    assert metas["b.md"]["extraction_note"] == "says nothing new"
    index = (kb_root / "assets-index" / "documents.md").read_text(encoding="utf-8")
    assert "- Extracted knowledge: `knowledge/domain/alpha.md`" in index
    log = (kb_root / "log.md").read_text(encoding="utf-8")
    assert "review | extracted: " in log and "review | skipped: " in log
    status = kb_ingest.collect_status(kb_root)
    assert status["extraction_pending"] == 0
    assert status["extraction_pending_oldest_days"] is None
    # Unknown file / missing page → usage error, nothing changed
    assert kb_ingest.main(
        ["--root", root, "--mark-extracted", "assets/documents/nope.md", "--to", "domain/alpha.md"]
    ) == 2
    assert kb_ingest.main(
        ["--root", root, "--mark-extracted", metas["a.md"]["asset_path"], "--to", "domain/missing.md"]
    ) == 2
    with pytest.raises(SystemExit):
        kb_ingest.main(["--root", root, "--mark-skipped", metas["a.md"]["asset_path"]])


def _legacy_metadata(root: Path, name: str) -> Path:
    path = root / "processed" / "extracted-metadata" / f"2025-01-01__{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "original_filename": f"{name}.md",
                "asset_path": f"assets/documents/2025-01-01__{name}.md",
                "source_hash": f"sha256:{name}",
                "processing_date": "2025-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_status_json_counts_unsorted_extraction_and_review(kb_root: Path, capsys):
    """D3: `--status --json` / collect_status report what waits and where."""
    intake = _unsorted(kb_root)
    (intake / "done.md").write_text("x\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    (intake / "new.md").write_text("fresh\n", encoding="utf-8")
    (intake / "empty.md").write_text("", encoding="utf-8")
    _legacy_metadata(kb_root, "old-cited")
    _legacy_metadata(kb_root, "old-lonely")
    kbc.write_frontmatter_file(
        kb_root / "knowledge" / "domain" / "cited.md",
        {"source": "assets/documents/2025-01-01__old-cited.md#p2"},
        "x\n",
    )
    (kb_root / "review" / "needs-ai-decision" / "pkg.md").write_text("# pkg\n", encoding="utf-8")
    log_before = (kb_root / "log.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert kb_ingest.main(["--root", str(kb_root), "--status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status == kb_ingest.collect_status(kb_root)
    assert status["unsorted"] == {"total": 2, "by_reason": {"empty": 1, "new": 1}}
    assert status["extraction_pending"] == 2  # done.md (pending) + old-lonely (not cited)
    assert status["extraction_pending_oldest_days"] > 365
    assert status["review"]["needs-ai-decision"] == {"count": 1, "oldest_days": 0}
    assert status["review"]["needs-redaction"] == {"count": 0, "oldest_days": None}
    # Read-only
    assert (intake / "new.md").exists()
    assert (kb_root / "log.md").read_text(encoding="utf-8") == log_before
    assert kb_ingest.main(["--root", str(kb_root), "--status"]) == 0
    assert "empty" in capsys.readouterr().out


def test_status_reports_files_the_last_run_failed_on(kb_root: Path, monkeypatch):
    src = _unsorted(kb_root) / "bad.md"
    src.write_text("x\n", encoding="utf-8")

    def boom(strategy, path):
        raise OSError("device error")

    monkeypatch.setattr(kb_ingest, "_convert", boom)
    assert _ingest(kb_root) == 1
    assert kb_ingest.collect_status(kb_root)["unsorted"]["by_reason"] == {"error": 1}
    src.write_text("changed content\n", encoding="utf-8")
    assert kb_ingest.collect_status(kb_root)["unsorted"]["by_reason"] == {"new": 1}


def test_backfill_extraction_marks_cited_legacy_metadata_done(kb_root: Path):
    """Heal migration extraction-registry: metadata from before 0.16."""
    cited = _legacy_metadata(kb_root, "old-cited")
    lonely = _legacy_metadata(kb_root, "old-lonely")
    (kb_root / "knowledge" / "domain").mkdir(parents=True)
    kbc.write_frontmatter_file(
        kb_root / "knowledge" / "domain" / "cited.md",
        {"source": ["assets/documents/2025-01-01__old-cited.md"]},
        "x\n",
    )
    assert kb_ingest.backfill_extraction(kb_root) == {"done": 1, "pending": 1}
    cited_meta = yaml.safe_load(cited.read_text(encoding="utf-8"))
    assert cited_meta["extraction"] == "done"
    assert cited_meta["extracted_to"] == ["knowledge/domain/cited.md"]
    assert yaml.safe_load(lonely.read_text(encoding="utf-8"))["extraction"] == "pending"
    assert kb_ingest.backfill_extraction(kb_root) == {"done": 0, "pending": 0}


def test_docx_and_xlsx_tables_become_valid_markdown(tmp_path: Path, monkeypatch):
    """E-Low: DOCX tables had no header separator and blank lines between rows."""
    cell = lambda text: types.SimpleNamespace(text=text)  # noqa: E731
    row = lambda *texts: types.SimpleNamespace(cells=[cell(t) for t in texts])  # noqa: E731
    document = types.SimpleNamespace(
        paragraphs=[types.SimpleNamespace(text="Team", style=types.SimpleNamespace(name="Heading 1"))],
        tables=[types.SimpleNamespace(rows=[row("Name", "Role"), row("Ann", "Dev | Ops"), row("", "")])],
    )
    monkeypatch.setitem(sys.modules, "docx", types.SimpleNamespace(Document=lambda path: document))
    assert kb_ingest._convert_docx(tmp_path / "x.docx") == (
        "# Team\n\n| Name | Role |\n|---|---|\n| Ann | Dev \\| Ops |\n"
    )
    sheet = types.SimpleNamespace(
        title="S1", iter_rows=lambda values_only: iter([("a", "b"), (None, None), (1, 2.5)])
    )
    monkeypatch.setitem(
        sys.modules,
        "openpyxl",
        types.SimpleNamespace(load_workbook=lambda **kw: types.SimpleNamespace(worksheets=[sheet])),
    )
    assert kb_ingest._convert_xlsx(tmp_path / "x.xlsx") == (
        "## Sheet: S1\n\n| a | b |\n|---|---|\n| 1 | 2.5 |\n"
    )


def test_max_file_mb_leaves_large_files_in_unsorted_and_0_means_no_limit(kb_root: Path):
    """What the kb.config.yml.template comment on ingest.max_file_mb promises."""
    config = kb_root / "kb.config.yml"
    base_config = config.read_text(encoding="utf-8")
    config.write_text(base_config + "\ningest:\n  max_file_mb: 0.00001\n", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "big.md"
    src.write_text("# Big\n\n" + "x" * 200 + "\n", encoding="utf-8")

    assert kb_ingest.main(["--root", str(kb_root), "--no-nlp"]) == 0
    assert src.exists()
    assert not list((kb_root / "assets").rglob("*.md"))
    assert kb_ingest.collect_status(kb_root)["unsorted"]["by_reason"] == {"too-large": 1}

    config.write_text(base_config + "\ningest:\n  max_file_mb: 0\n", encoding="utf-8")
    assert kb_ingest.main(["--root", str(kb_root), "--no-nlp"]) == 0
    assert not src.exists()
    assert len(list((kb_root / "assets" / "documents").glob("*.md"))) == 1


def _zip_bytes(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_nested_archives_are_not_unpacked_past_the_limits(kb_root: Path):
    """Residual M2: an archive inside an archive was unpacked again with a fresh
    media.archives budget, so nesting multiplied every cap (8 KB → 9.6 MB)."""
    _config(
        kb_root,
        "media:\n  archives:\n    max_files: 4\n    max_total_mb: 0.2\n    max_member_mb: 0.2\n",
    )
    inner = {tag: _zip_bytes({f"{tag}.txt": tag * 150_000}) for tag in ("a", "b", "c")}
    archive = _unsorted(kb_root) / "outer.zip"
    archive.write_bytes(_zip_bytes({
        "a.zip": inner["a"],
        "deep/b.tar.gz": inner["b"],  # judged by its name, like ingest would
        "c": inner["c"],  # no extension: judged by its magic bytes
        "note.txt": "plain member\n",
    }))
    assert _ingest(kb_root) == 0

    assert len(list((kb_root / "assets" / "archives").iterdir())) == 1  # the outer one
    documents = list((kb_root / "assets" / "documents").iterdir())
    assert [p.name.endswith("note.txt") for p in documents] == [True]
    assert sum(p.stat().st_size for p in documents) <= 0.2 * kb_ingest.MB
    assert kb_ingest._files_in_unsorted(kb_root) == []
    [outer] = _meta(kb_root, "*outer.yml")
    assert outer["archive_extracted_files"] == 1
    notes = outer["archive_notes"]
    for name in ("a.zip", "deep/b.tar.gz", "c"):
        assert f"{name}: nested archive, not unpacked (unpack it manually)" in notes
    assert outer["review_queue"] == "review/needs-ai-decision/"
    assert outer["review_reason"] == "3 nested archive(s) not unpacked — unpack manually"
    assert outer["extraction"] == "skipped"
    pkg = (kb_root / "review" / "needs-ai-decision" / f"{Path(outer['asset_path']).stem}.md")
    text = pkg.read_text(encoding="utf-8")
    assert "extract it from the asset into `raw/documents/unsorted/`" in text
    listing = (kb_root / outer["processed_path"]).read_text(encoding="utf-8")
    assert "a.zip: nested archive" in listing


def test_same_name_in_other_subfolders_is_not_a_new_version(kb_root: Path):
    """Residual M5 x M6: Project X/README.md and Project Y/README.md were
    declared versions of each other, and the package asked to move citations."""
    intake = _unsorted(kb_root, "work")
    for project in ("Project X", "Project Y"):
        (intake / project).mkdir()
        (intake / project / "README.md").write_text(f"{project} notes\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    first = _meta(kb_root)
    assert sorted(m["raw_path"] for m in first) == [
        "raw/work/unsorted/Project X/README.md",
        "raw/work/unsorted/Project Y/README.md",
    ]
    assert not any("previous_version" in m for m in first)
    assert all(m["review_queue"] is None for m in first)
    assert not list((kb_root / "review").rglob("*.md"))

    # A new version dropped in the same subfolder still links the old one.
    y1 = next(m for m in first if "Project Y" in m["raw_path"])
    (intake / "Project Y").mkdir(parents=True, exist_ok=True)
    (intake / "Project Y" / "README.md").write_text("Project Y notes v2\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [y2] = [m for m in _meta(kb_root) if "previous_version" in m]
    assert y2["previous_version"] == y1["asset_path"]

    # Metadata from before 0.16 has no raw_path and matches by name alone.
    x1 = next(m for m in first if "Project X" in m["raw_path"])
    x1_path = kb_root / "processed" / "extracted-metadata" / f"{Path(x1['asset_path']).stem}.yml"
    x1.pop("raw_path")
    x1_path.write_text(yaml.safe_dump(x1, sort_keys=False), encoding="utf-8")
    (intake / "README.md").write_text("top-level readme\n", encoding="utf-8")
    assert _ingest(kb_root) == 0
    [top] = [m for m in _meta(kb_root) if m.get("raw_path") == "raw/work/unsorted/README.md"]
    assert top["previous_version"] == x1["asset_path"]


def test_version_chain_survives_reprocessing_an_old_version(kb_root: Path):
    """Residual M5: re-processing v1 rewrote its processing_date, so v4 was
    linked to v1 instead of v3 (same-second ingests tied the same way)."""
    intake = _unsorted(kb_root, "work")
    versions: list[str] = []
    for n in (1, 2, 3, 4):
        if n == 4:  # e.g. the --set-category privacy migration, or a manual re-process
            assert _ingest(kb_root, str(kb_root / versions[0])) == 0
        (intake / "pricing.md").write_text(f"price v{n}: {n}0\n", encoding="utf-8")
        assert _ingest(kb_root) == 0
        [new] = [m for m in _meta(kb_root) if m["asset_path"] not in versions]
        if versions:
            assert new["previous_version"] == versions[-1], n
        versions.append(new["asset_path"])


def test_dry_run_lists_targets_and_duplicates_of_the_batch(kb_root: Path, capsys):
    """Residual: --dry-run printed 'dry-run (complexity 0.00)' for every file,
    same-batch duplicates included."""
    intake = _unsorted(kb_root, "work")
    (intake / "arch-notes.md").write_text("notes\n", encoding="utf-8")
    (intake / "arch-notes (1).md").write_text("notes\n", encoding="utf-8")
    assert _ingest(kb_root, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "complexity" not in out
    assert "raw/work/unsorted/arch-notes.md → assets/documents/" in out
    assert (
        "raw/work/unsorted/arch-notes (1).md (duplicate of raw/work/unsorted/arch-notes.md "
        "(would move to raw/_duplicates/))" in out
    )
    assert "Dry run: nothing changed" in out
    assert (intake / "arch-notes (1).md").exists()


def test_mark_unknown_path_names_the_review_package(kb_root: Path):
    """Residual: the error listed every accepted path kind but the review package."""
    with pytest.raises(LookupError, match=r"or its review/needs-\*/ package"):
        kb_ingest.mark_extraction(kb_root, "processed/markdown/nope.md", reason="x")


def test_review_package_has_no_empty_nlp_section():
    """Residual: NLP that found nothing left an empty '## NLP enrichment' heading."""
    kwargs = dict(asset_path="assets/documents/x.md", processed_path=None, reason="r")
    empty = kb_ingest._build_review_package(
        nlp_meta={"entities": [], "keywords": [], "complexity": 0.1}, **kwargs
    )
    assert "## NLP enrichment" not in empty
    found = kb_ingest._build_review_package(
        nlp_meta={"entities": [], "keywords": [{"phrase": "pricing"}]}, **kwargs
    )
    assert "## NLP enrichment\n- Keywords (top): pricing" in found
