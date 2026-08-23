"""Tests for kb_ingest reference pipeline."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

import kb_common as kbc
import kb_ingest


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


def test_skipped_extension(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        """
knowledge_base:
  name: test-kb
  mode: default
nlp:
  enabled: false
  skip_extensions: [".csv"]
""".strip(),
        encoding="utf-8",
    )
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "data.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    # Should remain in unsorted because it's skipped
    assert src.exists()



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
    # Members extracted (flattened) into raw/unsorted/unsorted for re-ingestion
    extracted = [p.name for p in (kb_root / "raw" / "unsorted" / "unsorted").glob("*")]
    assert any(n.endswith("a.txt") for n in extracted)
    assert any(n.endswith("b.txt") for n in extracted)
    # A listing was written to processed/markdown
    assert list((kb_root / "processed" / "markdown").glob("*.md"))


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
