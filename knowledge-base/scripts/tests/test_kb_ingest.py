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
    assert (kb_root / "knowledge" / "domain").is_dir()
    assert (kb_root / "review" / "needs-ai-decision").is_dir()


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
