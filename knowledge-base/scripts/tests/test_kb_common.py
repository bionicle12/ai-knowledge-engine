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


def test_parse_frontmatter_strips_bom():
    text = "﻿---\nfoo: bar\n---\nbody\n"
    meta, body = kbc.parse_frontmatter(text)
    assert meta == {"foo": "bar"}
    assert body == "body\n"


def test_read_frontmatter_file_with_bom(tmp_path: Path):
    p = tmp_path / "page.md"
    p.write_bytes(b"\xef\xbb\xbf---\nfoo: bar\n---\nbody\n")
    meta, body = kbc.read_frontmatter_file(p)
    assert meta == {"foo": "bar"}
    assert body == "body\n"


def test_fingerprint_ignores_bom(tmp_path: Path):
    plain = tmp_path / "plain.md"
    bom = tmp_path / "bom.md"
    content = "---\nfoo: bar\n---\n# Title\n\nsame body\n"
    plain.write_text(content, encoding="utf-8")
    bom.write_text(content, encoding="utf-8-sig")
    assert kbc.fingerprint_file(plain) == kbc.fingerprint_file(bom)


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


def test_extract_wikilinks_with_context_returns_source_lines():
    text = "intro\nsee [[caching]] for speed\n\n- both [[a]] and [[b|B]] here\n"
    assert kbc.extract_wikilinks_with_context(text) == [
        ("caching", "see [[caching]] for speed"),
        ("a", "- both [[a]] and [[b|B]] here"),
        ("b", "- both [[a]] and [[b|B]] here"),
    ]


def test_extract_wikilinks_with_context_matches_extract_wikilinks_order():
    text = "x [[one]]\ny [[two|alias]] z [[three]]"
    pairs = kbc.extract_wikilinks_with_context(text)
    assert [target for target, _line in pairs] == kbc.extract_wikilinks(text)


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


def test_posix_relpath_returns_portable_wikilink_target(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    page = knowledge / "projects" / "roadmap" / "near-term.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Near term\n", encoding="utf-8")

    assert (
        kbc.posix_relpath(page, knowledge, without_suffix=True)
        == "projects/roadmap/near-term"
    )


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


# ---------------------------------------------------------------------------
# Cross-platform tool discovery & config media accessors
# ---------------------------------------------------------------------------


def test_find_ffmpeg_returns_path_or_none():
    result = kbc.find_ffmpeg()
    assert result is None or isinstance(result, str)


def test_os_install_hint_nonempty():
    assert kbc.os_install_hint("ffmpeg")
    assert kbc.os_install_hint("tesseract")
    # unknown tool still returns something usable
    assert "frobnicate" in kbc.os_install_hint("frobnicate")


def test_media_accessors_default_empty(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n", encoding="utf-8"
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.stt == {}
    assert cfg.ocr == {}
    assert cfg.archives == {}


def test_media_accessors_parse(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n"
        "media:\n"
        "  stt:\n    enabled: true\n    model: small\n"
        "  ocr:\n    enabled: false\n"
        "  archives:\n    max_files: 50\n",
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.stt["model"] == "small"
    assert cfg.ocr["enabled"] is False
    assert cfg.archives["max_files"] == 50


# ---------------------------------------------------------------------------
# Cross-base sync primitives (see 16_MERGE.md)
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_frontmatter_drift():
    a = "---\ntags: [x]\naccess_count: 0\n---\n\n# T\n\nBody.\n"
    b = "---\ntags: [x, y]\naccess_count: 12\nimportance: 8\n---\n\n# T\n\nBody.\n"
    assert kbc.content_fingerprint(a) == kbc.content_fingerprint(b)


def test_fingerprint_ignores_trailing_whitespace_and_line_endings():
    a = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
    b = "---\ntitle: T\n---\r\n\r\n# T   \r\n\r\nBody.   \r\n\r\n\r\n"
    assert kbc.content_fingerprint(a) == kbc.content_fingerprint(b)


def test_fingerprint_detects_body_change():
    a = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
    b = "---\ntitle: T\n---\n\n# T\n\nBody, extended.\n"
    assert kbc.content_fingerprint(a) != kbc.content_fingerprint(b)


def test_fingerprint_file_matches_content_fingerprint(tmp_path: Path):
    page = tmp_path / "p.md"
    text = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
    page.write_text(text, encoding="utf-8")
    assert kbc.fingerprint_file(page) == kbc.content_fingerprint(text)


def test_stable_metadata_drops_volatile_keys():
    meta = {"title": "T", "access_count": 5, "merged_from": "other", "tags": ["a"]}
    assert kbc.stable_metadata(meta) == {"title": "T", "tags": ["a"]}


def test_ensure_sync_dirs_is_idempotent(tmp_path: Path):
    first = kbc.ensure_sync_dirs(tmp_path)
    kbc.ensure_sync_dirs(tmp_path)
    assert first == tmp_path / "sync"
    for sub in kbc.SYNC_DIRS:
        assert (first / sub).is_dir()
    assert (first / "README.md").is_file()


def test_sync_dir_paths(tmp_path: Path):
    assert kbc.sync_dir(tmp_path) == tmp_path / "sync"
    assert kbc.sync_dir(tmp_path, "inbox") == tmp_path / "sync" / "inbox"


def test_sync_label_falls_back_to_kb_name(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: my-kb\n", encoding="utf-8"
    )
    assert kbc.load_config(tmp_path).sync_label == "my-kb"


def test_sync_label_ignores_unparameterized_placeholder(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        'knowledge_base:\n  name: my-kb\nsync:\n  label: "{{KB_LABEL}}"\n',
        encoding="utf-8",
    )
    assert kbc.load_config(tmp_path).sync_label == "my-kb"


def test_sync_sections_parse(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n"
        "sync:\n"
        "  label: laptop-a\n"
        "  export:\n    with_assets: true\n"
        "  import:\n    strategy: prefer-local\n",
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.sync_label == "laptop-a"
    assert cfg.sync_export["with_assets"] is True
    assert cfg.sync_import["strategy"] == "prefer-local"


def test_timestamp_slug_is_filesystem_safe():
    slug = kbc.timestamp_slug()
    assert ":" not in slug
    assert len(slug) == len("2026-07-31T10-14-36")
