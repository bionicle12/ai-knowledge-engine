"""Tests for kb_common utility module."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import kb_common as kbc


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_basic():
    text = "---\nfoo: bar\n---\nbody\n"
    meta, body = kbc.parse_frontmatter(text)
    assert meta == {"foo": "bar"}
    assert body == "body\n"


def test_parse_frontmatter_missing():
    text = "no frontmatter here\n"
    meta, body = kbc.parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_invalid_yaml():
    text = "---\nfoo: : :\n---\nbody\n"
    meta, body = kbc.parse_frontmatter(text)
    # On invalid YAML we return empty meta and the raw text untouched
    assert meta == {}


def test_render_frontmatter_roundtrip():
    meta = {"foo": "bar", "tags": ["a", "b"]}
    body = "hello\n"
    rendered = kbc.render_frontmatter(meta, body)
    meta2, body2 = kbc.parse_frontmatter(rendered)
    assert meta2 == meta
    assert body2 == body


def test_render_frontmatter_empty_meta_returns_body():
    assert kbc.render_frontmatter({}, "body\n") == "body\n"


def test_read_write_frontmatter_file(tmp_path: Path):
    p = tmp_path / "page.md"
    meta_in = {"source": "raw/x.pdf", "tags": ["test"]}
    body_in = "# Title\n\ncontent\n"
    kbc.write_frontmatter_file(p, meta_in, body_in)
    meta_out, body_out = kbc.read_frontmatter_file(p)
    assert meta_out == meta_in
    assert body_out == body_in


# ---------------------------------------------------------------------------
# Slugify / stable filename
# ---------------------------------------------------------------------------


def test_slugify_ascii():
    assert kbc.slugify("Hello World") == "hello-world"


def test_slugify_truncation():
    s = kbc.slugify("a" * 100, max_len=10)
    assert len(s) <= 10


def test_stable_filename_with_date():
    name = kbc.stable_filename(
        original_name="My Doc.pdf",
        date=dt.date(2026, 5, 6),
    )
    assert name == "2026-05-06__my-doc.pdf"


def test_stable_filename_unknown_date():
    name = kbc.stable_filename(original_name="Notes.docx")
    assert name.startswith("unknown-date__")
    assert name.endswith(".docx")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_compute_source_hash_stable(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    h1 = kbc.compute_source_hash(f)
    h2 = kbc.compute_source_hash(f)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_compute_source_hash_changes(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"a")
    h1 = kbc.compute_source_hash(f)
    f.write_bytes(b"b")
    h2 = kbc.compute_source_hash(f)
    assert h1 != h2


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_append_log_creates_file(tmp_path: Path):
    p = kbc.append_log(
        operation="test",
        title="hello",
        details=["a", "b"],
        root=tmp_path,
    )
    assert p == tmp_path / "log.md"
    content = p.read_text(encoding="utf-8")
    assert "# Operations Log" in content
    assert "test | hello" in content
    assert "- a" in content


def test_append_log_appends(tmp_path: Path):
    kbc.append_log(operation="op1", title="first", root=tmp_path)
    kbc.append_log(operation="op2", title="second", root=tmp_path)
    content = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "op1 | first" in content
    assert "op2 | second" in content
    # Ensure header appears only once
    assert content.count("# Operations Log") == 1


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------


def test_extract_wikilinks_simple():
    text = "see [[caching]] and [[domain/database]]"
    assert kbc.extract_wikilinks(text) == ["caching", "domain/database"]


def test_extract_wikilinks_with_alias():
    text = "see [[caching|the caching page]]"
    assert kbc.extract_wikilinks(text) == ["caching"]


def test_extract_wikilinks_none():
    assert kbc.extract_wikilinks("plain text [link](url)") == []


def test_scan_knowledge_slugs(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    (knowledge / "domain").mkdir(parents=True)
    (knowledge / "principles").mkdir(parents=True)
    (knowledge / "domain" / "caching.md").write_text("x")
    (knowledge / "principles" / "quality.md").write_text("x")
    slugs = kbc.scan_knowledge_slugs(knowledge)
    assert "caching" in slugs
    assert "quality" in slugs
    assert len(slugs["caching"]) == 1


def test_scan_knowledge_slugs_duplicates(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    (knowledge / "a").mkdir(parents=True)
    (knowledge / "b").mkdir(parents=True)
    (knowledge / "a" / "shared.md").write_text("x")
    (knowledge / "b" / "shared.md").write_text("x")
    slugs = kbc.scan_knowledge_slugs(knowledge)
    assert len(slugs["shared"]) == 2


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_config_missing_file_returns_defaults(tmp_path: Path):
    cfg = kbc.load_config(tmp_path)
    assert cfg.mode == "default"
    assert cfg.primary_language == "en"


def test_load_config_parses_basic_yaml(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        """
knowledge_base:
  mode: super
language_policy:
  primary: ru
nlp:
  spacy_model: ru_core_news_md
mode_profiles:
  default:
    surprise:
      engine: python
  super:
    surprise:
      engine: ai
""".strip(),
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.mode == "super"
    assert cfg.primary_language == "ru"
    assert cfg.spacy_model == "ru_core_news_md"
    profile = cfg.profile()
    assert profile.surprise_engine == "ai"


def test_find_kb_root_walks_up(tmp_path: Path):
    root = tmp_path / "kb"
    root.mkdir()
    (root / "kb.config.yml").write_text("knowledge_base:\n  name: x\n")
    nested = root / "scripts" / "deep"
    nested.mkdir(parents=True)
    found = kbc.find_kb_root(nested)
    assert found == root


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def test_write_read_json(tmp_path: Path):
    p = tmp_path / "data.json"
    data = {"a": 1, "b": [2, 3], "ru": "тест"}
    kbc.write_json(p, data)
    assert kbc.read_json(p) == data
