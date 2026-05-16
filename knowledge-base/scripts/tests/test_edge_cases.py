"""Edge case tests for kb_ingest and kb_lint."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import kb_common as kbc
import kb_ingest
import kb_lint


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "kb.config.yml").write_text(
        """
knowledge_base:
  name: edge-test
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


# ---------------------------------------------------------------------------
# Empty / minimal inputs
# ---------------------------------------------------------------------------


def test_ingest_empty_file(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "empty.md"
    src.write_text("", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    # Empty file should be processed without crash
    assert code == 0
    # Should appear in assets/
    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 1


def test_ingest_handles_unicode_filename(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "Привет мир.md"
    src.write_text("# UTF-8 content\n", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 1
    # Filename should be slugified (Cyrillic → transliterated or stripped)
    assert assets[0].name != "Привет мир.md"


def test_ingest_processes_txt_via_passthrough(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "plain.txt"
    src.write_text("plain text content", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    processed = list((kb_root / "processed" / "markdown").glob("*.md"))
    assert len(processed) == 1


def test_ingest_unknown_extension_routes_to_review(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "documents" / "unsorted" / "weird.xyz"
    src.write_text("binary-ish stuff", encoding="utf-8")
    code = kb_ingest.main(["--root", str(kb_root), "--no-nlp"])
    assert code == 0
    # Unknown extensions should be routed somewhere safe
    review = list((kb_root / "review" / "needs-ai-decision").glob("*.md"))
    assert len(review) == 1


# ---------------------------------------------------------------------------
# Idempotency under churn
# ---------------------------------------------------------------------------


def test_ingest_repeated_runs_no_duplicates(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "doc.md"
    src.write_text("body\n", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])

    src2 = kb_root / "raw" / "reference" / "unsorted" / "doc-copy.md"
    src2.write_text("body\n", encoding="utf-8")  # same content
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])

    src3 = kb_root / "raw" / "reference" / "unsorted" / "doc-copy-2.md"
    src3.write_text("body\n", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])

    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 1, "same content should produce only one asset"


def test_ingest_different_content_same_name(kb_root: Path):
    kb_ingest.main(["--root", str(kb_root), "--init-dirs"])
    src = kb_root / "raw" / "reference" / "unsorted" / "doc.md"
    src.write_text("version one", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])

    src.write_text("version two", encoding="utf-8")
    kb_ingest.main(["--root", str(kb_root), "--no-nlp"])

    assets = list((kb_root / "assets" / "documents").glob("*.md"))
    assert len(assets) == 2, "different content under same name should keep both"


# ---------------------------------------------------------------------------
# Frontmatter edge cases
# ---------------------------------------------------------------------------


def test_lint_handles_broken_frontmatter(kb_root: Path):
    knowledge = kb_root / "knowledge"
    knowledge.mkdir()
    p = knowledge / "broken.md"
    p.write_text("---\nfoo: : :\n---\nbody\n", encoding="utf-8")
    # Lint must not crash
    report = kb_lint.run_lint(kb_root)
    assert report.pages_scanned == 1
    # Broken frontmatter → empty meta → reports missing required fields
    assert any(i.check == "frontmatter" for i in report.issues)


def test_lint_handles_unicode_in_frontmatter(kb_root: Path):
    knowledge = kb_root / "knowledge"
    knowledge.mkdir()
    p = knowledge / "uni.md"
    p.write_text(
        "---\n"
        "source: raw/x.md\n"
        "extracted_at: 2026-05-16\n"
        "tags: [программирование, музыка]\n"
        "lifecycle: evolving\n"
        "---\n"
        "Привет мир\n",
        encoding="utf-8",
    )
    report = kb_lint.run_lint(kb_root)
    # No frontmatter errors
    assert not [i for i in report.issues if i.check == "frontmatter"]


def test_lint_zero_pages_no_crash(kb_root: Path):
    (kb_root / "knowledge").mkdir()
    report = kb_lint.run_lint(kb_root)
    assert report.pages_scanned == 0
    assert kb_lint.exit_code(report) >= 0  # warnings about empty categories


# ---------------------------------------------------------------------------
# Large structural cases
# ---------------------------------------------------------------------------


def test_lint_with_50_pages_scales(kb_root: Path):
    knowledge = kb_root / "knowledge"
    knowledge.mkdir()
    today = dt.date.today().isoformat()
    for i in range(50):
        p = knowledge / "domain" / f"page-{i:03d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        kbc.write_frontmatter_file(
            p,
            {
                "source": f"raw/x{i}.md",
                "extracted_at": today,
                "tags": ["scale"],
                "lifecycle": "evolving",
                "importance": (i % 10) + 1,
            },
            "body\n",
        )
    report = kb_lint.run_lint(kb_root, metrics=True)
    assert report.pages_scanned == 50
    assert report.metrics["total_pages"] == 50
    # 50 pages in domain → over threshold (15) → domain-overflow warning
    assert any(i.check == "domain-overflow" for i in report.issues)


# ---------------------------------------------------------------------------
# kb_common edge cases
# ---------------------------------------------------------------------------


def test_compute_source_hash_empty_file(tmp_path: Path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    h = kbc.compute_source_hash(p)
    assert h.startswith("sha256:")
    # Empty file hash is well-known
    assert h == "sha256:e3b0c44298fc1c14"


def test_extract_wikilinks_nested_brackets():
    # [[a]] inside text alongside escape-like characters should still parse
    text = "see [[a]] and [code with [[b]] in it]"
    links = kbc.extract_wikilinks(text)
    assert "a" in links
    assert "b" in links


def test_slugify_non_ascii():
    s = kbc.slugify("Привет мир Hello")
    assert s
    assert s != "Привет мир Hello"
    assert " " not in s


# ---------------------------------------------------------------------------
# Fixture file roundtrip
# ---------------------------------------------------------------------------


def test_fixture_with_frontmatter_loads(kb_root: Path):
    src = FIXTURES / "with-frontmatter.md"
    meta, body = kbc.read_frontmatter_file(src)
    assert meta["source"] == "raw/reference/unsorted/example.md"
    assert meta["lifecycle"] == "evolving"
    assert "Fixture" in body


def test_fixture_no_frontmatter_returns_empty_meta(kb_root: Path):
    src = FIXTURES / "no-frontmatter.md"
    meta, body = kbc.read_frontmatter_file(src)
    assert meta == {}
    assert body.startswith("# No frontmatter")


def test_fixture_empty_file_no_crash(kb_root: Path):
    src = FIXTURES / "empty.md"
    meta, body = kbc.read_frontmatter_file(src)
    assert meta == {}
    assert body == ""


def test_fixture_broken_frontmatter_gracefully(kb_root: Path):
    src = FIXTURES / "broken-frontmatter.md"
    meta, body = kbc.read_frontmatter_file(src)
    # Broken YAML → empty meta, full body preserved
    assert meta == {}
    assert "Body still readable" in body
