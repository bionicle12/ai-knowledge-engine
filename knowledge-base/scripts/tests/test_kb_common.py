"""Tests for kb_common utility module."""
from __future__ import annotations

import ast
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import yaml

import kb_common as kbc

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(kbc.__file__).resolve().parent
TEMPLATES = REPO_ROOT / "knowledge-base" / "templates"


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


def test_invariant_ids_and_strip():
    text = (
        "outside always\n"
        "<!-- AI-KE:INVARIANT:BEGIN id=\"forbidden\" -->\n"
        "## Forbidden\nnever index raw\n"
        "<!-- AI-KE:INVARIANT:END id=\"forbidden\" -->\n"
        "<!-- AI-KE:INVARIANT:BEGIN id=\"language\" -->\n"
        "## Language\n"
        "<!-- AI-KE:INVARIANT:END id=\"language\" -->\n"
        "after must\n"
    )
    assert kbc.invariant_ids(text) == {"forbidden", "language"}
    stripped = kbc.strip_invariant_bodies(text)
    assert "never index raw" not in stripped
    assert "outside always" in stripped
    assert "after must" in stripped


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
    readme = (first / "README.md").read_text(encoding="utf-8")
    # D5: a deployed base keeps the modules under kb-docs/, not at the root.
    assert "(see `kb-docs/16_MERGE.md`)" in readme
    assert "undo journal (`kb_import.py --undo <report>`)" in readme


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


# ---------------------------------------------------------------------------
# Engine version
# ---------------------------------------------------------------------------


def _run_kb_common(*args: str, prelude: str = "") -> subprocess.CompletedProcess:
    code = (
        "import runpy, sys\n"
        f"{prelude}"
        f"sys.argv = ['kb_common.py', *{list(args)!r}]\n"
        f"runpy.run_path({str(SCRIPTS_DIR / 'kb_common.py')!r}, run_name='__main__')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_engine_version_matches_repo_version_file():
    version_file = REPO_ROOT / "VERSION"
    if not version_file.is_file():
        pytest.skip("repo VERSION file not reachable (deployed copy)")
    assert kbc.ENGINE_VERSION == version_file.read_text(encoding="utf-8").strip()


def test_cli_version_prints_engine_version():
    result = _run_kb_common("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == kbc.ENGINE_VERSION


def test_cli_version_works_before_pyyaml_is_installed():
    # 02_INIT fills {{KB_INSTRUCTIONS_VERSION}} from this; a bare python3
    # without the venv must still answer.
    result = _run_kb_common("--version", prelude="sys.modules['yaml'] = None\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == kbc.ENGINE_VERSION


# ---------------------------------------------------------------------------
# YAML loading (MV13/Q17 speed, MV19 alias bombs)
# ---------------------------------------------------------------------------

_ALIAS_BOMB = (
    'a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]\n'
    "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
    "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
    "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
    "e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
    "f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]\n"
)


def test_yaml_loader_prefers_libyaml():
    if getattr(yaml, "CSafeLoader", None) is None:
        pytest.skip("PyYAML built without libyaml")
    assert kbc.YAML_LOADER is yaml.CSafeLoader


def test_yaml_load_refuses_alias_bomb_quickly():
    # 45 aliases (under the count limit) that expand to ~600k nodes.
    started = time.monotonic()
    with pytest.raises(yaml.YAMLError, match="expand"):
        kbc.yaml_load(_ALIAS_BOMB)
    assert time.monotonic() - started < 2


def test_yaml_load_alias_count_limit():
    def doc(count: int) -> str:
        return "x: &x 1\nitems: [" + ", ".join(["*x"] * count) + "]\n"

    assert len(kbc.yaml_load(doc(kbc.MAX_YAML_ALIASES))["items"]) == kbc.MAX_YAML_ALIASES
    with pytest.raises(yaml.YAMLError, match="aliases"):
        kbc.yaml_load(doc(kbc.MAX_YAML_ALIASES + 1))


def test_yaml_load_refuses_recursive_alias():
    with pytest.raises(yaml.YAMLError, match="recursive"):
        kbc.yaml_load("a: &x [1, *x]\n")


def test_yaml_load_keeps_ordinary_anchors_and_merge_keys():
    data = kbc.yaml_load("base: &b {x: 1}\nchild: {<<: *b, y: 2}\nglob: '*.md'\n")
    assert data["child"] == {"x": 1, "y": 2}
    assert data["glob"] == "*.md"


def test_yaml_load_bad_value_is_a_yaml_error():
    # PyYAML raises a bare ValueError for impossible dates.
    with pytest.raises(yaml.YAMLError):
        kbc.yaml_load("verified: 2026-13-45\n")


def test_parse_frontmatter_alias_bomb_returns_empty():
    text = "---\n" + _ALIAS_BOMB + "---\nbody\n"
    meta, body = kbc.parse_frontmatter(text)
    assert meta == {}
    assert body == text
    assert "expand" in kbc.frontmatter_error(text)


# Built inside a child process: a regression is a SIGSEGV there, not in pytest.
_DEEP_NESTING = {
    "flow": "'x: ' + '[' * 40000 + ']' * 40000",
    "block-sequence": "'- ' * 40000 + 'x'",
    "explicit-key": "'? ' * 40000 + 'x'",
}


@pytest.mark.parametrize("kind", sorted(_DEEP_NESTING))
def test_deep_nesting_is_a_yaml_error_not_a_crash(kind):
    # Review of WP0: libyaml composes by unbounded C recursion; ~30 000 levels
    # (60 KB of frontmatter) killed kb_lint with SIGSEGV (exit 139) where the
    # old pure-Python parse reported the page as unreadable.
    code = (
        "import sys, yaml\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import kb_common as kbc\n"
        f"text = {_DEEP_NESTING[kind]}\n"
        "try:\n"
        "    kbc.yaml_load(text)\n"
        "    print('loaded')\n"
        "except yaml.YAMLError:\n"
        "    print('yaml-error')\n"
        "page = '---\\n' + text + '\\n---\\nbody\\n'\n"
        "print(kbc.parse_frontmatter(page)[0], kbc.frontmatter_error(page))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-500:])
    lines = result.stdout.splitlines()
    assert lines[0] == "yaml-error"
    assert lines[1].startswith("{} invalid YAML")


def test_yaml_load_depth_limit_boundary():
    if kbc.YAML_LOADER is yaml.SafeLoader:
        pytest.skip("PyYAML built without libyaml (pure Python stops at its recursion limit)")
    n = kbc.MAX_YAML_DEPTH
    data, depth = kbc.yaml_load("[" * n + "]" * n), 0
    while isinstance(data, list):
        data, depth = (data[0] if data else None), depth + 1
    assert depth == n
    assert isinstance(kbc.yaml_load("a: " + "[" * (n - 1) + "]" * (n - 1))["a"], list)
    with pytest.raises(yaml.YAMLError, match="deeper than"):
        kbc.yaml_load("a: " + "[" * n + "]" * n)
    with pytest.raises(yaml.YAMLError, match="deeper than"):
        kbc.yaml_load(("- " * (n + 1) + "x").encode())


def test_yaml_load_lone_surrogate_is_a_yaml_error():
    # libyaml cannot encode a lone surrogate (JSON "\udc97" in an import
    # bundle): UnicodeEncodeError escaped yaml_load and parse_frontmatter.
    with pytest.raises(yaml.YAMLError):
        kbc.yaml_load("a: \udc97\n")
    text = "---\na: \udc97\n---\nbody\n"
    assert kbc.parse_frontmatter(text) == ({}, text)
    assert kbc.frontmatter_error(text).startswith("invalid YAML")


def test_yaml_load_large_shallow_documents_still_load():
    # More nesting indicators than MAX_YAML_DEPTH, but shallow: the depth pass
    # lets it through and libyaml parses it as before.
    text = "items:\n" + "".join(f"  - {{k: [{i}, '-?:']}}\n" for i in range(3000))
    data = kbc.yaml_load(text)
    assert len(data["items"]) == 3000
    assert data["items"][-1] == {"k": [2999, "-?:"]}
    assert kbc.parse_frontmatter("---\n" + text + "---\nbody\n")[1] == "body\n"


# ---------------------------------------------------------------------------
# Frontmatter robustness (MV15, Q5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "front",
    ["- a\n- b\n", "just a string\n", "42\n", "[x, y]\n"],
)
def test_parse_frontmatter_non_mapping_returns_empty(front):
    text = f"---\n{front}---\nbody\n"
    meta, body = kbc.parse_frontmatter(text)
    assert meta == {}
    assert body == text
    assert kbc.frontmatter_error(text).startswith("frontmatter is not a mapping")


def test_parse_frontmatter_bad_value_never_raises():
    text = "---\nlast_verified: 2026-13-45\n---\nbody\n"
    assert kbc.parse_frontmatter(text) == ({}, text)
    assert kbc.frontmatter_error(text).startswith("invalid YAML")


def test_frontmatter_error_reports_the_q5_page():
    # The page `kb_lint --fix` used to corrupt: an unclosed flow list.
    text = "---\nsource: raw/a.md\ntags: [x, y\nlifecycle: permanent\n---\n# T\n"
    error = kbc.frontmatter_error(text)
    assert error is not None and error.startswith("invalid YAML:")
    assert "\n" not in error


def test_frontmatter_error_none_for_valid_or_absent():
    assert kbc.frontmatter_error("---\na: 1\n---\nbody\n") is None
    assert kbc.frontmatter_error("no frontmatter\n") is None
    assert kbc.frontmatter_error("---\n---\nbody\n") is None


def test_frontmatter_error_unclosed_block():
    assert "not closed" in kbc.frontmatter_error("---\na: 1\nbody without closing\n")


def test_parse_frontmatter_empty_block_and_closing_at_eof():
    assert kbc.parse_frontmatter("---\n---\nbody\n") == ({}, "body\n")
    assert kbc.parse_frontmatter("---\na: 1\n---") == ({"a": 1}, "")


def test_parse_frontmatter_keeps_legacy_body_offsets():
    # Blank lines right after the closing `---` are not part of the body —
    # unchanged, so content fingerprints of existing pages do not move.
    assert kbc.parse_frontmatter("---\na: 1\n---\n\n# T\n") == ({"a": 1}, "# T\n")


def test_read_frontmatter_file_decodes_legacy_code_page(tmp_path: Path):
    page = tmp_path / "page.md"
    page.write_bytes("---\ntitle: Заметка\n---\nТекст заметки\n".encode("cp1251"))
    meta, body = kbc.read_frontmatter_file(page)
    assert meta == {"title": "Заметка"}
    assert body == "Текст заметки\n"


# Review of WP0: a UTF-8 page with one stray cp1251 byte was decoded as
# latin-1, and kb_route wrote the mojibake back (plus a second frontmatter).
_MOSTLY_UTF8_PAGE = (
    "---\ntitle: Маршруты\n---\n# Таблица маршрутов\n\n- [[p]] — страница\n".encode("utf-8")
    + b"\x97 stray\n"
)


def test_mostly_utf8_page_survives_a_read_write_round_trip(tmp_path: Path):
    page = tmp_path / "routing-table.md"
    page.write_bytes(_MOSTLY_UTF8_PAGE)
    meta, body = kbc.read_frontmatter_file(page)
    assert meta == {"title": "Маршруты"}
    assert body == "# Таблица маршрутов\n\n- [[p]] — страница\n— stray\n"
    kbc.write_frontmatter_file(page, meta, body)
    written = page.read_text(encoding="utf-8")
    assert written == "---\ntitle: Маршруты\n---\n" + body
    assert "Ð" not in written


def test_write_frontmatter_file_only_if_changed(tmp_path: Path):
    page = tmp_path / "page.md"
    assert kbc.write_frontmatter_file(page, {"a": 1}, "body\n") is True
    os.utime(page, (1_000_000, 1_000_000))
    assert kbc.write_frontmatter_file(page, {"a": 1}, "body\n", only_if_changed=True) is False
    assert page.stat().st_mtime == 1_000_000
    assert kbc.write_frontmatter_file(page, {"a": 2}, "body\n", only_if_changed=True) is True
    assert kbc.read_frontmatter_file(page)[0] == {"a": 2}


# ---------------------------------------------------------------------------
# Atomic writes (L2)
# ---------------------------------------------------------------------------


def _leftover_temp_files(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def test_atomic_write_text_replaces_and_leaves_no_temp(tmp_path: Path):
    target = tmp_path / "index.md"
    target.write_text("old\n", encoding="utf-8")
    kbc.atomic_write_text(target, "new ✓\n")
    assert target.read_text(encoding="utf-8") == "new ✓\n"
    assert _leftover_temp_files(tmp_path) == []


def test_atomic_write_keeps_original_when_replace_fails(tmp_path: Path, monkeypatch):
    target = tmp_path / "assets-index.md"
    target.write_text("precious\n", encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(kbc.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        kbc.atomic_write_text(target, "half-written")
    assert target.read_text(encoding="utf-8") == "precious\n"
    assert _leftover_temp_files(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_atomic_write_handles_a_long_cyrillic_name(tmp_path: Path):
    # Review of WP0: the temp name was cut at 180 characters, not bytes, so a
    # valid 245-byte Cyrillic name overflowed NAME_MAX (ENAMETOOLONG).
    name = "ж" * 120 + ".md"  # 243 bytes: valid on ext4/APFS/NTFS
    target = tmp_path / name
    kbc.atomic_write_text(target, "x")
    assert target.read_text(encoding="utf-8") == "x"


def test_atomic_write_keeps_permissions(tmp_path: Path):
    target = tmp_path / "hook.sh"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o754)
    kbc.atomic_write_text(target, "new\n")
    assert target.stat().st_mode & 0o777 == 0o754


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_atomic_write_writes_through_symlink(tmp_path: Path):
    real = tmp_path / "real.md"
    real.write_text("old\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    kbc.atomic_write_text(link, "new\n")
    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "new\n"


def test_write_if_changed_leaves_identical_file_alone(tmp_path: Path):
    target = tmp_path / "routing-table.md"
    assert kbc.write_if_changed(target, "same\n") is True
    os.utime(target, (1_000_000, 1_000_000))
    assert kbc.write_if_changed(target, "same\n") is False
    assert target.stat().st_mtime == 1_000_000
    assert kbc.write_if_changed(target, "other\n") is True


def test_atomic_write_text_writes_newlines_verbatim_on_every_os(tmp_path: Path):
    target = tmp_path / "x.sh"
    kbc.atomic_write_text(target, "a\nb\r\n")
    assert target.read_bytes() == b"a\nb\r\n"


# ---------------------------------------------------------------------------
# State dir & locks (G:H5 foundation)
# ---------------------------------------------------------------------------


def test_state_dir_is_created_and_ignores_itself(tmp_path: Path):
    state = kbc.state_dir(tmp_path)
    assert state == tmp_path / ".kb-state"
    assert state.is_dir()
    assert (state / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"


def test_kb_lock_creates_lock_file_and_exports_claim(tmp_path: Path):
    with kbc.kb_lock(tmp_path) as path:
        assert path == tmp_path / ".kb-state" / "locks" / "pipeline.lock"
        claim = os.environ["KB_LOCK_PIPELINE"]
        pid, token, lock_path = claim.split(":", 2)
        assert pid == str(os.getpid()) and len(token) == 16
        assert lock_path == os.path.realpath(path)
        owner = path.with_name("pipeline.lock.owner")
        assert owner.read_text(encoding="utf-8") == claim
    assert "KB_LOCK_PIPELINE" not in os.environ
    assert not owner.exists()


def test_kb_lock_rejects_bad_names(tmp_path: Path):
    with pytest.raises(ValueError):
        with kbc.kb_lock(tmp_path, "../escape"):
            pass


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KB_LOCK_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


_HOLD_LOCK = (
    "import sys; sys.path.insert(0, {scripts!r})\n"
    "import kb_common as kbc\n"
    "with kbc.kb_lock({root!r}, 'pipeline', timeout=5):\n"
    "    print('locked', flush=True)\n"
    "    sys.stdin.read()\n"
)


def test_kb_lock_times_out_while_another_process_holds_it(tmp_path: Path):
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK.format(scripts=str(SCRIPTS_DIR), root=str(tmp_path))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=_child_env(),
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        started = time.monotonic()
        with pytest.raises(kbc.KbLockTimeout) as info:
            with kbc.kb_lock(tmp_path, "pipeline", timeout=0.3):
                pass
        assert time.monotonic() - started >= 0.3
        assert isinstance(info.value, TimeoutError)
        assert "busy" in str(info.value)
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    # Released when the holder exits: now it is ours immediately.
    with kbc.kb_lock(tmp_path, "pipeline", timeout=0):
        pass


def test_kb_lock_is_shared_with_child_processes(tmp_path: Path):
    # kb_reindex holds the pipeline lock and runs kb_ingest as a subprocess.
    child = (
        "import sys; sys.path.insert(0, {scripts!r})\n"
        "import kb_common as kbc\n"
        "with kbc.kb_lock({root!r}, 'pipeline', timeout=0):\n"
        "    print('child ran')\n"
    ).format(scripts=str(SCRIPTS_DIR), root=str(tmp_path))
    with kbc.kb_lock(tmp_path, "pipeline"):
        result = subprocess.run(
            [sys.executable, "-c", child],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    assert result.returncode == 0, result.stderr
    assert "child ran" in result.stdout


def test_kb_lock_nested_in_one_process_does_not_deadlock(tmp_path: Path):
    with kbc.kb_lock(tmp_path, "pipeline"):
        with kbc.kb_lock(tmp_path, "pipeline", timeout=0):
            pass
        assert "KB_LOCK_PIPELINE" in os.environ
    assert "KB_LOCK_PIPELINE" not in os.environ


def test_kb_lock_is_not_shared_between_threads(tmp_path: Path):
    """Residual security: the claim lives in process-wide os.environ, so a
    second thread took it for its own and held the lock beside the first."""
    holders: list[int] = []
    overlap: list[list[int]] = []
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            with kbc.kb_lock(tmp_path, "pipeline", timeout=5):
                holders.append(n)
                overlap.append(list(holders))
                with kbc.kb_lock(tmp_path, "pipeline", timeout=0):  # nested: same thread
                    pass
                time.sleep(0.5)
                holders.remove(n)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(2)]
    threads[0].start()
    time.sleep(0.2)
    threads[1].start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors
    assert overlap == [[0], [1]]
    assert "KB_LOCK_PIPELINE" not in os.environ


@pytest.mark.parametrize("claimant", ["dead", "alive"])
def test_kb_lock_ignores_a_claim_the_current_holder_did_not_make(
    tmp_path: Path, monkeypatch, claimant: str
):
    # Review of WP0: a child spawned under the lock outlived its parent's
    # release; once an unrelated process took the lock, the child must wait
    # too — whether or not the claiming process is still alive.
    lock = tmp_path / ".kb-state" / "locks" / "pipeline.lock"
    if claimant == "dead":
        pid = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                             capture_output=True, text=True, check=True).stdout.strip()
    else:
        pid = str(os.getpid())
    kbc.state_dir(tmp_path)
    monkeypatch.setenv("KB_LOCK_PIPELINE", f"{pid}:0123456789abcdef:{os.path.realpath(lock)}")
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK.format(scripts=str(SCRIPTS_DIR), root=str(tmp_path))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=_child_env(),
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        if os.name != "nt":
            with pytest.raises(kbc.KbLockTimeout):
                with kbc.kb_lock(tmp_path, "pipeline", timeout=0.2):
                    pass
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)


@pytest.mark.skipif(os.name == "nt", reason="fcntl locks")
def test_kb_lock_fails_fast_when_the_filesystem_cannot_lock(tmp_path: Path, monkeypatch):
    # Review of WP0: ENOLCK/EOPNOTSUPP (NFS, FUSE) counted as "busy", so
    # kb_lock waited out its 600 s timeout and every append_log stalled 30 s.
    import errno
    import fcntl

    def no_lock_support(fd, operation):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_lock_support)
    started = time.monotonic()
    with pytest.raises(OSError) as info:
        with kbc.kb_lock(tmp_path, "pipeline", timeout=600):
            pass
    assert info.value.errno == errno.ENOLCK
    kbc.append_log(operation="ingest", title="still logged", root=tmp_path)
    assert time.monotonic() - started < 5
    assert "ingest | still logged" in kbc.log_path(tmp_path).read_text(encoding="utf-8")


def test_kb_lock_different_names_are_independent(tmp_path: Path):
    with kbc.kb_lock(tmp_path, "pipeline"):
        with kbc.kb_lock(tmp_path, "log", timeout=0):
            assert os.environ["KB_LOCK_LOG"]


# ---------------------------------------------------------------------------
# kb.config.yml line editing (Q3, I7, Q16)
# ---------------------------------------------------------------------------


def _template_config() -> str:
    text = (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8")
    return re.sub(r"\{\{[A-Z_]+\}\}", "x", text)


def _comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def test_config_set_accepts_every_config_load_config_reads(tmp_path: Path):
    # Review of WP0: a tab before a trailing comment — libyaml (load_config)
    # reads it, the pure-Python composer of config_set called it invalid YAML.
    if kbc.YAML_LOADER is yaml.SafeLoader:
        pytest.skip("PyYAML built without libyaml")
    text = "a:\n  b: 1\t# c\n"
    (tmp_path / "kb.config.yml").write_text(text, encoding="utf-8")
    assert kbc.load_config(tmp_path).raw == {"a": {"b": 1}}
    assert kbc.config_set(text, "a.b", 2) == "a:\n  b: 2\t# c\n"
    assert kbc.config_set(text, "a.c", 3) == "a:\n  b: 1\t# c\n  c: 3\n"
    assert kbc.config_append_block(text, "status", "status:\n  enabled: true\n") == (
        text + "\nstatus:\n  enabled: true\n"
    )


def test_config_set_inserts_missing_key_and_keeps_every_comment():
    # Q3 reproduction 1: primary_agent uncommented, window_profile removed.
    text = _template_config().replace('  # primary_agent: "codex"', '  primary_agent: "codex"')
    text = "".join(
        line for line in text.splitlines(keepends=True) if "window_profile:" not in line
    )
    result = kbc.config_set(text, "index.window_profile", "400k")
    assert _comment_lines(result) == _comment_lines(text)
    assert kbc.yaml_load(result)["index"]["window_profile"] == "400k"
    assert '\n  window_profile: "400k"\n' in result
    assert kbc.config_set(result, "index.window_profile", "400k") == result


def test_config_set_replaces_quoted_value_in_place():
    # Q3 reproduction 2: a quoted number made heal fall back to safe_dump.
    text = _template_config().replace("agents_max_bytes: 10240", 'agents_max_bytes: "9000"')
    result = kbc.config_set(text, "instructions_lint.agents_max_bytes", 10240)
    assert _comment_lines(result) == _comment_lines(text)
    assert kbc.yaml_load(result)["instructions_lint"]["agents_max_bytes"] == 10240
    assert len(result.splitlines()) == len(text.splitlines())


def test_config_set_never_touches_commented_lines_and_converges():
    # Q3 reproduction 3: the regex used to edit `# agents_max_bytes: 9216`.
    text = _template_config().replace(
        "  agents_max_bytes: 10240", "  # agents_max_bytes: 9216\n  agents_max_bytes: 9000"
    )
    result = kbc.config_set(text, "instructions_lint.agents_max_bytes", 10240)
    assert "  # agents_max_bytes: 9216\n" in result
    assert "  agents_max_bytes: 10240\n" in result
    assert kbc.config_set(result, "instructions_lint.agents_max_bytes", 10240) == result


def test_config_set_keeps_trailing_comment():
    text = "heal:\n  stage: 1                    # 1 safe | 2 hygiene\n"
    assert kbc.config_set(text, "heal.stage", 2) == (
        "heal:\n  stage: 2                    # 1 safe | 2 hygiene\n"
    )


def test_config_set_uses_the_parents_indent():
    # Q16: a 4-space heal block became invalid YAML after last_run was added.
    text = "heal:\n    auto_apply: false\n    stage: 3\nother: 1\n"
    result = kbc.config_set(text, "heal.last_run.at", "2026-09-23")
    result = kbc.config_set(result, "heal.last_run.version", "0.16.0")
    assert result == (
        "heal:\n    auto_apply: false\n    stage: 3\n"
        '    last_run:\n        at: "2026-09-23"\n        version: "0.16.0"\n'
        "other: 1\n"
    )


def test_config_set_heal_last_run_in_template_keeps_comments():
    text = _template_config()
    result = kbc.config_set(text, "heal.last_run.at", "2026-09-23")
    data = kbc.yaml_load(result)
    assert data["heal"]["last_run"] == {"at": "2026-09-23"}
    assert data["heal"]["stage"] == 1
    assert _comment_lines(result) == _comment_lines(text)


@pytest.mark.parametrize(
    "text, key",
    [
        ("heal: {auto_apply: false, stage: 3}\n", "heal.last_run.at"),
        ("heal: {auto_apply: false, stage: 3}\n", "heal.stage"),
        ("{heal: 1}\n", "heal"),
    ],
)
def test_config_set_refuses_flow_style_parents(text, key):
    with pytest.raises(kbc.ConfigEditError, match="flow"):
        kbc.config_set(text, key, 2)


@pytest.mark.parametrize(
    "text",
    ["heal: 5\n", "heal: [1, 2]\n", "heal:\n  - 1\n"],
)
def test_config_set_refuses_non_mapping_parents(text):
    with pytest.raises(kbc.ConfigEditError, match="not a mapping"):
        kbc.config_set(text, "heal.stage", 2)


def test_config_set_refuses_multiline_values_and_mappings():
    with pytest.raises(kbc.ConfigEditError, match="several lines"):
        kbc.config_set("watch:\n  - a\n  - b\n", "watch", ["c"])
    with pytest.raises(kbc.ConfigEditError, match="leaf keys"):
        kbc.config_set("a: 1\n", "b", {"x": 1})


def test_config_set_creates_a_top_level_section_at_the_end():
    assert kbc.config_set("a: 1  # c\n", "status.enabled", True) == (
        "a: 1  # c\n\nstatus:\n  enabled: true\n"
    )
    assert kbc.config_set("", "status.file", "STATUS.md") == 'status:\n  file: "STATUS.md"\n'


def test_config_set_fills_null_and_empty_flow_parents():
    assert kbc.config_set("heal:\nnext: 1\n", "heal.stage", 2) == (
        "heal:\n  stage: 2\nnext: 1\n"
    )
    assert kbc.config_set("entities: {}   # from examples\n", "entities.x", 1) == (
        "entities:   # from examples\n  x: 1\n"
    )


def test_config_set_edits_the_effective_duplicate():
    text = "heal:\n  stage: 1\nheal:\n  stage: 3\n"
    result = kbc.config_set(text, "heal.stage", 2)
    assert result == "heal:\n  stage: 1\nheal:\n  stage: 2\n"


def test_config_set_keeps_crlf_and_bom():
    text = "﻿a: 1\r\nb:\r\n  c: 2\r\n"
    result = kbc.config_set(text, "b.d", "x")
    assert result == '﻿a: 1\r\nb:\r\n  c: 2\r\n  d: "x"\r\n'


def test_config_set_same_value_keeps_the_text():
    text = "index:\n  window_profile: '256k'   # quoted my way\n"
    assert kbc.config_set(text, "index.window_profile", "256k") == text


def test_config_set_value_rendering_round_trips():
    text = "a: 0\n"
    for value in ["0.16.0", "yes", "", "ё \"q\"", 0.7, 200, None, True, ["*.tmp", "~$*"], []]:
        result = kbc.config_set(text, "a", value)
        assert kbc.yaml_load(result)["a"] == value


def test_config_set_comment_goes_on_new_lines_only():
    result = kbc.config_set("a: 1\n", "b", 2, comment="added by heal")
    assert result == "a: 1\n\nb: 2  # added by heal\n"
    assert kbc.config_set(result, "b", 3, comment="ignored") == "a: 1\n\nb: 3  # added by heal\n"


def test_config_set_rejects_bad_input():
    with pytest.raises(kbc.ConfigEditError):
        kbc.config_set("a: [1\n", "a", 2)
    with pytest.raises(kbc.ConfigEditError):
        kbc.config_set("a: 1\n", "a..b", 2)
    with pytest.raises(kbc.ConfigEditError):
        kbc.config_set("- 1\n", "a", 2)


def test_config_append_block_adds_missing_section_verbatim():
    block = "media:\n  # comments survive\n  stt:\n    enabled: true\n"
    result = kbc.config_append_block("a: 1\n", "media", block)
    assert result == "a: 1\n\n" + block
    assert kbc.config_append_block(result, "media", block) == result


def test_config_append_block_keeps_an_existing_section():
    text = "media:\n  stt:\n    enabled: false\n"
    assert kbc.config_append_block(text, "media", "media:\n  ocr: {}\n") == text


def test_config_append_block_replaces_an_empty_section():
    text = "a: 1\nentities: {}   # from examples/<role>.yml\nb: 2\n"
    result = kbc.config_append_block(text, "entities", "entities:\n  tools:\n    - git\n")
    assert result == "a: 1\nentities:  # from examples/<role>.yml\n  tools:\n    - git\nb: 2\n"


def test_config_append_block_validates_the_block():
    with pytest.raises(kbc.ConfigEditError):
        kbc.config_append_block("a: 1\n", "media", "sync:\n  label: x\n")
    with pytest.raises(kbc.ConfigEditError):
        kbc.config_append_block("a: 1\n", "media", "media:\n  x: 1\nsync: 2\n")


def test_update_config_file_is_atomic_and_reports_changes(tmp_path: Path):
    cfg = tmp_path / "kb.config.yml"
    cfg.write_bytes(b"\xef\xbb\xbf# top\r\nheal:\r\n  stage: 1  # c\r\n")
    assert kbc.update_config_file(tmp_path, {"heal.stage": 2}) is True
    assert cfg.read_bytes() == b"\xef\xbb\xbf# top\r\nheal:\r\n  stage: 2  # c\r\n"
    os.utime(cfg, (1_000_000, 1_000_000))
    assert kbc.update_config_file(tmp_path, [("heal.stage", 2)]) is False
    assert cfg.stat().st_mtime == 1_000_000
    with pytest.raises(kbc.ConfigEditError):
        kbc.update_config_file(tmp_path, [("heal.stage", 3), ("heal.stage.x", 1)])
    assert kbc.load_config(tmp_path).raw["heal"]["stage"] == 2
    assert kbc.update_config_file(tmp_path, [("heal.last_run.at", "2026-09-23", "stamped")])
    assert b'  last_run:\r\n    at: "2026-09-23"  # stamped\r\n' in cfg.read_bytes()


def test_update_config_file_accepts_block_edits(tmp_path: Path):
    cfg = tmp_path / "kb.config.yml"
    cfg.write_bytes(b"# top\r\nentities: {}\r\n")
    block = "entities:\n  tools:\n    - git\n"
    edits = [
        lambda text: kbc.config_append_block(text, "entities", block),
        lambda text: kbc.config_append_block(text, "media", "media:\n  stt:\n    enabled: true\n"),
        ("media.stt.model", "small"),
    ]
    assert kbc.update_config_file(tmp_path, edits) is True
    assert cfg.read_bytes() == (
        b"# top\r\nentities:\r\n  tools:\r\n    - git\r\n\r\n"
        b'media:\r\n  stt:\r\n    enabled: true\r\n    model: "small"\r\n'
    )
    assert kbc.update_config_file(tmp_path, edits) is False


_CONFIG_REFERENCES = {"kb.config.yml", "DEFAULT_CONFIG_FILENAME", "kb_config_path"}


def _yaml_dump_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return (
            isinstance(func.value, ast.Name)
            and func.value.id == "yaml"
            and func.attr in {"dump", "safe_dump", "dump_all", "safe_dump_all"}
        )
    return isinstance(func, ast.Name) and func.id == "safe_dump"


def _references_config(function: ast.AST) -> bool:
    docstring = None
    body = getattr(function, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        docstring = body[0].value
    for node in ast.walk(function):
        if node is docstring:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "kb.config.yml" in node.value:
                return True
        if isinstance(node, ast.Name) and node.id in _CONFIG_REFERENCES:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _CONFIG_REFERENCES:
            return True
    return False


def _config_dumping_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_yaml_dump_call(inner) for inner in ast.walk(node))
        and _references_config(node)
    ]


def _script_files() -> list[Path]:
    return sorted(
        [*(REPO_ROOT / "knowledge-base" / "scripts").glob("*.py"),
         *(REPO_ROOT / "scripts").glob("*.py")]
    )


def test_config_dump_detector_catches_the_heal_pattern(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import yaml\n"
        "def f(root):\n"
        "    '''Never touches kb.config.yml.'''\n"
        "    data = {}\n"
        "    (root / 'kb.config.yml').write_text(yaml.safe_dump(data))\n"
        "def g(root):\n"
        "    '''Dumps a snapshot of kb.config.yml into a bundle.'''\n"
        "    return yaml.safe_dump({})\n",
        encoding="utf-8",
    )
    assert _config_dumping_functions(bad) == ["f"]


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(path, id=path.relative_to(REPO_ROOT).as_posix())
        for path in _script_files()
    ],
)
def test_no_script_rewrites_kb_config_through_a_yaml_dumper(script: Path):
    # kb.config.yml is hand-edited and commented: code edits it with
    # kbc.config_set / config_append_block / update_config_file only.
    assert _config_dumping_functions(script) == []


# ---------------------------------------------------------------------------
# Wikilinks (Q13)
# ---------------------------------------------------------------------------


def _links(text: str) -> list[tuple]:
    return [
        (l.target, l.slug, l.section, l.alias, l.is_embed, l.path_hint)
        for l in kbc.iter_wikilinks(text)
    ]


def test_iter_wikilinks_normalises_the_q13_forms():
    text = (
        "[[target#section]] [[target.md]] [[knowledge/domain/target]] "
        "![[diagram.png]] [[domain/db|the DB]] [[ ./x.MD#^block ]]"
    )
    assert _links(text) == [
        ("target", "target", "section", None, False, None),
        ("target", "target", None, None, False, None),
        ("knowledge/domain/target", "target", None, None, False, "knowledge/domain"),
        ("diagram.png", "diagram.png", None, None, True, None),
        ("domain/db", "db", None, "the DB", False, "domain"),
        ("x", "x", "^block", None, False, None),
    ]


def test_wikilink_page_id_is_relative_to_knowledge():
    ids = [link.page_id for link in kbc.iter_wikilinks("[[knowledge/domain/t]] [[domain/t]] [[t]]")]
    assert ids == ["domain/t", "domain/t", "t"]


def test_iter_wikilinks_ignores_code():
    text = (
        "real [[a]] and `[[inline]]` and ``[[double `tick`]]``\n"
        "```python\n[[fenced]]\n```\n"
        "~~~\n[[tilde]]\n~~~\n"
        "````\n```\n[[nested]]\n```\n````\n"
        "after [[b]]\n"
        "    ```not a fence``` [[c]]\n"
    )
    assert [link.slug for link in kbc.iter_wikilinks(text)] == ["a", "b", "c"]


def test_iter_wikilinks_unclosed_fence_hides_the_rest():
    assert [link.slug for link in kbc.iter_wikilinks("[[a]]\n```\n[[b]]\n")] == ["a"]


def test_iter_wikilinks_unmatched_backtick_is_literal():
    assert [link.slug for link in kbc.iter_wikilinks("a ` b [[x]]\n\nc ` [[y]]")] == ["x", "y"]


def test_inline_code_masking_is_not_quadratic():
    # Review of WP0: many unmatched backtick runs of different lengths made
    # the inline-code regex rescan the paragraph for each run (69 s here).
    text = " ".join("`" * k + "x" for k in range(1, 1500)) + " [[end]]"
    started = time.monotonic()
    assert kbc.extract_wikilinks(text) == ["end"]
    assert time.monotonic() - started < 5


def test_inline_code_spans_follow_the_regex_rule():
    # The scanner must keep the old regex's semantics exactly: a run closed by
    # the next run of the same length, never across a blank line.
    import random

    reference = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.DOTALL)
    pieces = ["`", "``", "```", "a", " ", "\n", "\n\n", " \t\n", "[[x]]"]
    rng = random.Random(13)
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 20)))
        assert kbc._inline_code_spans(text) == [m.span() for m in reference.finditer(text)], text


def test_iter_wikilinks_escaped_pipe_in_tables_and_self_links():
    text = "| [[page\\|Alias]] | [[#heading]] | [[ ]] |"
    assert _links(text) == [("page", "page", None, "Alias", False, None)]


def test_extract_wikilinks_q13_false_positives_are_gone():
    text = (
        "[[target#section]] [[target.md]] [[knowledge/domain/target]] "
        "![[diagram.png]] `[[inline]]`\n```\n[[fenced]]\n```\n"
    )
    assert kbc.extract_wikilinks(text) == ["target", "target", "domain/target"]


def test_extract_wikilinks_with_context_skips_code_and_embeds():
    text = "see [[a#x]] here\n```\n[[b]]\n```\n![[img.png]] and [[c]]\n"
    assert kbc.extract_wikilinks_with_context(text) == [
        ("a", "see [[a#x]] here"),
        ("c", "![[img.png]] and [[c]]"),
    ]


# ---------------------------------------------------------------------------
# Path helpers: resolve_under, is_archived, is_generated
# ---------------------------------------------------------------------------


def test_resolve_under_accepts_inside_and_rejects_escapes(tmp_path: Path):
    base = tmp_path / "knowledge"
    (base / "domain").mkdir(parents=True)
    page = base / "domain" / "x.md"
    page.write_text("x", encoding="utf-8")
    assert kbc.resolve_under(base, "domain/x.md") == page.resolve()
    assert kbc.resolve_under(base, page) == page.resolve()
    assert kbc.resolve_under(base, base) == base.resolve()
    assert kbc.resolve_under(base, "../kb.config.yml") is None
    assert kbc.resolve_under(base, tmp_path / "other.md") is None
    assert kbc.resolve_under(base, "bad\0name") is None


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_resolve_under_follows_symlinks(tmp_path: Path):
    base = tmp_path / "knowledge"
    base.mkdir()
    secret = tmp_path / ".env"
    secret.write_text("SECRET_TOKEN=x", encoding="utf-8")
    (base / "leak.md").symlink_to(secret)
    (base / "inside.md").write_text("x", encoding="utf-8")
    (base / "alias.md").symlink_to(base / "inside.md")
    assert kbc.resolve_under(base, "leak.md") is None
    assert kbc.resolve_under(base, "alias.md") == (base / "inside.md").resolve()


def test_is_archived_and_is_generated():
    assert kbc.is_archived("knowledge/_archive/old.md")
    assert kbc.is_archived("_archive\\sub\\old.md")
    assert not kbc.is_archived("knowledge/domain/_archive-notes.md")
    assert kbc.is_generated({"generated_by": "kb_route"})
    assert not kbc.is_generated({"generated_by": ""})
    assert not kbc.is_generated(["generated_by"])


# ---------------------------------------------------------------------------
# Lifecycle & the single stale rule (MV14, I6, I11)
# ---------------------------------------------------------------------------

TODAY = dt.date(2026, 9, 23)
OLD = "2026-01-01"
BY_FOLDER = {"decisions": "permanent", "profile": "permanent", "principles": "permanent"}


@pytest.mark.parametrize(
    "meta, rel, expected, reason",
    [
        ({"last_verified": OLD}, "knowledge/domain/a.md", True, "last_verified"),
        ({"extracted_at": OLD}, "domain/a.md", True, "extracted_at"),
        # Viewer used to flag "Fresh — never verified" (extracted 3 days ago).
        ({"extracted_at": "2026-09-20"}, "knowledge/domain/a.md", False, "3 days"),
        ({"last_verified": OLD, "extracted_at": "2026-09-01"}, "domain/a.md", False, "extracted_at"),
        ({"last_verified": OLD, "lifecycle": "permanent"}, "domain/a.md", False, "permanent"),
        ({"last_verified": OLD}, "knowledge/_archive/a.md", False, "archived"),
        ({"last_verified": OLD, "generated_by": "kb_route"}, "routing/a.md", False, "generated"),
        ({"last_verified": OLD, "valid_until": "2026-12-31"}, "domain/a.md", False, "valid until"),
        ({"last_verified": OLD, "valid_until": TODAY}, "domain/a.md", False, "valid until"),
        ({"last_verified": OLD, "valid_until": "2026-02-01"}, "domain/a.md", True, "days old"),
        ({}, "domain/a.md", False, "no date"),
        ({"last_verified": "not a date"}, "domain/a.md", False, "no date"),
        # lifecycle.by_folder: decisions/ are permanent unless the page opts out.
        ({"last_verified": OLD, "lifecycle": "evolving"}, "knowledge/decisions/a.md", False, "permanent"),
        ({"last_verified": OLD}, "decisions/2026/a.md", False, "permanent"),
        ({"last_verified": OLD, "lifecycle": "temporal"}, "decisions/a.md", True, "days old"),
        ({"last_verified": dt.datetime(2026, 1, 1, 12, 0)}, "domain/a.md", True, "days old"),
    ],
)
def test_stale_status_rule(meta, rel, expected, reason):
    stale, why = kbc.stale_status(meta, rel, today=TODAY, stale_days=30, by_folder=BY_FOLDER)
    assert stale is expected
    assert reason in why


def test_stale_status_threshold_is_exclusive():
    meta = {"last_verified": "2026-08-24"}  # 30 days before TODAY
    assert kbc.stale_status(meta, "a.md", today=TODAY, stale_days=30)[0] is False
    assert kbc.stale_status(meta, "a.md", today=TODAY, stale_days=29)[0] is True


def test_stale_status_tolerates_garbage_meta():
    assert kbc.stale_status(["x"], "a.md", today=TODAY) == (False, "no date")


def test_effective_lifecycle_rules():
    by_folder = {"decisions": "permanent", "projects/legacy": "temporal", "bad": "forever"}
    assert kbc.effective_lifecycle({}, "knowledge/decisions/x.md", by_folder) == "permanent"
    assert kbc.effective_lifecycle({"lifecycle": "evolving"}, "decisions/x.md", by_folder) == "permanent"
    assert kbc.effective_lifecycle({"lifecycle": "temporal"}, "decisions/x.md", by_folder) == "temporal"
    assert kbc.effective_lifecycle({}, "projects/legacy/x.md", by_folder) == "temporal"
    assert kbc.effective_lifecycle({}, "projects/x.md", by_folder) == "evolving"
    assert kbc.effective_lifecycle({}, "bad/x.md", by_folder) == "evolving"
    assert kbc.effective_lifecycle({"lifecycle": "PERMANENT"}, "x.md", None) == "permanent"
    assert kbc.effective_lifecycle({"lifecycle": "weird"}, "x.md", None) == "evolving"
    assert kbc.effective_lifecycle({}, "x.md", by_folder, default="permanent") == "permanent"


# ---------------------------------------------------------------------------
# Text decoding (G:M1)
# ---------------------------------------------------------------------------

RUSSIAN = "Переписка с Иваном о долгах.\nСумма долга — 100 руб., «срочно».\n"


def test_read_text_auto_utf8_variants(tmp_path: Path):
    plain = tmp_path / "a.txt"
    plain.write_bytes(RUSSIAN.encode("utf-8"))
    assert kbc.read_text_auto(plain) == (RUSSIAN, "utf-8")
    bom = tmp_path / "b.txt"
    bom.write_bytes(b"\xef\xbb\xbf" + RUSSIAN.encode("utf-8"))
    assert kbc.read_text_auto(bom) == (RUSSIAN, "utf-8-sig")
    wide = tmp_path / "c.txt"
    wide.write_bytes(RUSSIAN.encode("utf-16"))
    assert kbc.read_text_auto(wide) == (RUSSIAN, "utf-16")


def test_read_text_auto_normalises_newlines(tmp_path: Path):
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"a\r\nb\rc\n")
    assert kbc.read_text_auto(path)[0] == "a\nb\nc\n"


@pytest.fixture
def no_charset_normalizer(monkeypatch):
    monkeypatch.setitem(sys.modules, "charset_normalizer", None)


def test_read_text_auto_cp1251_without_detector(tmp_path: Path, no_charset_normalizer):
    path = tmp_path / "заметка.txt"
    path.write_bytes(RUSSIAN.encode("cp1251"))
    text, encoding = kbc.read_text_auto(path)
    assert (text, encoding) == (RUSSIAN, "cp1251")
    short = tmp_path / "short.txt"
    short.write_bytes("заметка".encode("cp1251"))
    assert kbc.read_text_auto(short) == ("заметка", "cp1251")


def test_read_text_auto_western_text_is_not_cyrillic(tmp_path: Path, no_charset_normalizer):
    for sample in ("Café crème, für Müller — “quoted”", "Informação sobre a situação"):
        path = tmp_path / "w.txt"
        path.write_bytes(sample.encode("cp1252"))
        assert kbc.read_text_auto(path) == (sample, "cp1252")


def test_read_text_auto_uses_charset_normalizer_when_present(tmp_path: Path, monkeypatch):
    class Guess:
        encoding = "koi8_r"

    fake = types.ModuleType("charset_normalizer")
    fake.from_bytes = lambda data: types.SimpleNamespace(best=lambda: Guess())
    monkeypatch.setitem(sys.modules, "charset_normalizer", fake)
    path = tmp_path / "k.txt"
    path.write_bytes("Café".encode("cp1252"))
    assert kbc.read_text_auto(path) == ("Café".encode("cp1252").decode("koi8_r"), "koi8_r")


def test_read_text_auto_short_cp1251_beats_a_wrong_detector_guess(tmp_path: Path, monkeypatch):
    # charset_normalizer 3.x reads the cp1251 bytes of "Встреча" as shift_jis.
    class Guess:
        encoding = "shift_jis_2004"

    fake = types.ModuleType("charset_normalizer")
    fake.from_bytes = lambda data: types.SimpleNamespace(best=lambda: Guess())
    monkeypatch.setitem(sys.modules, "charset_normalizer", fake)
    path = tmp_path / "note.txt"
    path.write_bytes("Встреча".encode("cp1251"))
    assert kbc.read_text_auto(path) == ("Встреча", "cp1251")


def test_read_text_auto_never_returns_replacement_chars(tmp_path: Path, no_charset_normalizer):
    path = tmp_path / "bin.dat"
    path.write_bytes(bytes(range(256)) * 4)
    text, _encoding = kbc.read_text_auto(path)
    assert "�" not in text


def test_read_text_auto_mostly_utf8_keeps_the_valid_text(tmp_path: Path):
    # Review of WP0: one stray byte sent a UTF-8 page to latin-1 (mojibake).
    path = tmp_path / "page.md"
    path.write_bytes(_MOSTLY_UTF8_PAGE)
    assert kbc.read_text_auto(path) == (
        "---\ntitle: Маршруты\n---\n# Таблица маршрутов\n\n- [[p]] — страница\n— stray\n",
        "utf-8+cp1251",
    )
    path.write_bytes("Ссылка на страницу".encode("utf-8") + b"\xff")
    assert kbc.read_text_auto(path) == ("Ссылка на страницуя", "utf-8+cp1251")
    path.write_bytes("Café crème — naïve résumé ".encode("utf-8") + b"\x93quoted\x94")
    assert kbc.read_text_auto(path) == ("Café crème — naïve résumé “quoted”", "utf-8+cp1252")


def test_read_text_auto_legacy_text_is_not_taken_for_damaged_utf8(tmp_path: Path, no_charset_normalizer):
    # cp1251 bytes form a valid UTF-8 pair now and then ("Вё" = C2 B8).
    sample = "Вёл он долгий разговор о погоде, планах и ёмкости склада. " * 3
    path = tmp_path / "note.txt"
    path.write_bytes(sample.encode("cp1251"))
    assert kbc.read_text_auto(path) == (sample, "cp1251")


@pytest.mark.parametrize(
    ("utf8_part", "stray", "expected"),
    [
        # Review of WP0 round 2: a mostly-ASCII Western page with one or two
        # pasted cp1252 bytes was decoded whole as cp1252 (mojibake).
        ("It’s fine", b" \x96 pasted", "It’s fine – pasted"),
        ("A — B — C — D", b" \x97 E \x97 F", "A — B — C — D — E — F"),
    ],
)
def test_read_text_auto_western_page_with_stray_bytes(
    tmp_path: Path, no_charset_normalizer, utf8_part: str, stray: bytes, expected: str
):
    path = tmp_path / "page.md"
    path.write_bytes(utf8_part.encode("utf-8") + stray)
    assert kbc.read_text_auto(path) == (expected, "utf-8+cp1252")


def test_read_text_auto_utf8_page_with_a_pasted_cp1251_paragraph(tmp_path: Path, no_charset_normalizer):
    pasted = "Этот абзац вставлен из старого документа в кодировке Windows-1251. " * 4
    path = tmp_path / "page.md"
    head = "Короткая заметка на русском — с «кавычками».\n"
    path.write_bytes(head.encode("utf-8") + pasted.encode("cp1251"))
    assert kbc.read_text_auto(path) == (head + pasted, "utf-8+cp1251")
    # An ASCII head carries no UTF-8 evidence: the file is plain cp1251.
    path.write_bytes(b"Short English note.\n" + pasted.encode("cp1251"))
    assert kbc.read_text_auto(path) == ("Short English note.\n" + pasted, "cp1251")


def test_read_text_auto_short_cp1251_with_punctuation(tmp_path: Path, no_charset_normalizer):
    # Review of WP0: №, «», — are shared punctuation, not evidence for cp1252.
    path = tmp_path / "note.txt"
    path.write_bytes("№5 — «Да»".encode("cp1251"))
    assert kbc.read_text_auto(path) == ("№5 — «Да»", "cp1251")
    path.write_bytes("He said “hi” — ok…".encode("cp1252"))
    assert kbc.read_text_auto(path) == ("He said “hi” — ok…", "cp1252")


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_read_text_auto_utf16_without_bom(tmp_path: Path, encoding: str):
    # Review of WP0: BOM-less UTF-16 ASCII decoded as UTF-8 with NULs.
    path = tmp_path / "export.txt"
    for sample in ("hello world\n", "Привет, мир\n", RUSSIAN):
        path.write_bytes(sample.encode(encoding))
        assert kbc.read_text_auto(path) == (sample, encoding)


# ---------------------------------------------------------------------------
# log.md rotation (logging.rotation_threshold)
# ---------------------------------------------------------------------------


def _entries(text: str) -> list[str]:
    return re.findall(r"^## \[[^\]]+\] (\S+) \|", text, flags=re.MULTILINE)


def test_append_log_rotates_old_entries_into_monthly_archives(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "logging:\n  rotation_threshold: 4\n  archive_dir: old-logs\n", encoding="utf-8"
    )
    (tmp_path / "log.md").write_text(
        "# Operations Log\n\n"
        "## [2026-07-30T10:00:00+03:00] op1 | a\n- d\n\n"
        "## [2026-08-01T10:00:00+03:00] op2 | b\n\n"
        "## [2026-08-02T10:00:00] op3 | naive time\n\n"
        "## [not a date] op4 | c\n\n",
        encoding="utf-8",
    )
    kbc.append_log(operation="op5", title="new", root=tmp_path)
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert log.startswith("# Operations Log\n\n## [")
    assert _entries(log) == ["op4", "op5"]
    july = (tmp_path / "old-logs" / "log-2026-07.md").read_text(encoding="utf-8")
    august = (tmp_path / "old-logs" / "log-2026-08.md").read_text(encoding="utf-8")
    assert july.startswith("# Operations Log — archive 2026-07\n\n")
    assert _entries(july) == ["op1"] and "- d\n" in july
    assert _entries(august) == ["op2", "op3"]
    # Next rotation appends to the same monthly archive, oldest first.
    for n in range(6, 9):
        kbc.append_log(operation=f"op{n}", title="x", root=tmp_path)
    kept = _entries((tmp_path / "log.md").read_text(encoding="utf-8"))
    archived = [
        name
        for path in sorted((tmp_path / "old-logs").glob("log-*.md"))
        for name in _entries(path.read_text(encoding="utf-8"))
    ]
    assert sorted(archived + kept) == sorted(f"op{n}" for n in range(1, 9))
    assert len(kept) <= 4


def test_append_log_without_config_uses_default_threshold(tmp_path: Path):
    for n in range(5):
        kbc.append_log(operation=f"op{n}", title="x", root=tmp_path)
    assert len(_entries((tmp_path / "log.md").read_text(encoding="utf-8"))) == 5
    assert not (tmp_path / "log-archive").exists()


def test_append_log_rotation_disabled_with_zero(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text("logging:\n  rotation_threshold: 0\n", encoding="utf-8")
    for n in range(5):
        kbc.append_log(operation=f"op{n}", title="x", root=tmp_path)
    assert len(_entries((tmp_path / "log.md").read_text(encoding="utf-8"))) == 5


def test_append_log_leaves_import_archives_alone(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text("logging:\n  rotation_threshold: 2\n", encoding="utf-8")
    imported = tmp_path / "log-archive" / "imported__laptop__2026-09-01.md"
    imported.parent.mkdir()
    imported.write_text("foreign log\n", encoding="utf-8")
    for n in range(4):
        kbc.append_log(operation=f"op{n}", title="x", root=tmp_path)
    assert imported.read_text(encoding="utf-8") == "foreign log\n"
    assert any(p.name.startswith("log-20") for p in imported.parent.iterdir())


def test_append_log_survives_a_broken_config(tmp_path: Path, capsys):
    (tmp_path / "kb.config.yml").write_text("logging: [\n", encoding="utf-8")
    kbc.append_log(operation="op", title="x", root=tmp_path)
    assert "op | x" in (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "rotation skipped" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Config: new keys, defaults, backward compatibility (D2)
# ---------------------------------------------------------------------------

IGNORE_GLOBS = (
    ".DS_Store", "Thumbs.db", "desktop.ini", "~$*", "._*",
    "*.part", "*.crdownload", "*.tmp", "*.swp",
)
D2_ATTRIBUTES = {
    "ingest_ignore_globs": IGNORE_GLOBS,
    "ingest_max_file_mb": 200.0,
    "ingest_duplicates_dir": "raw/_duplicates",
    "archives_max_total_mb": 500.0,
    "archives_max_member_mb": 200.0,
    "privacy_require_redaction_for_chats": True,
    "privacy_redact_categories": ("chats", "personal-context"),
    "privacy_secret_scan": True,
    "lifecycle_default": "evolving",
    "lifecycle_stale_warning_days": 30,
    "lifecycle_by_folder": {"decisions": "permanent", "profile": "permanent", "principles": "permanent"},
    "log_rotation_threshold": 1000,
    "log_archive_dir": "log-archive",
    "index_repomix_version": "1.14.0",
    "index_npx_fallback": True,
    "status_enabled": True,
    "status_file": "STATUS.md",
    "autorun_watch_enabled": True,
    "autorun_watch_dirs": ("raw/*/unsorted/", "knowledge/"),
    "autorun_auto_nlp": True,
    "autorun_auto_lint_on_change": True,
    "autorun_auto_reindex_on_change": True,
    "autorun_consolidation_on_reindex": True,
}


def test_new_config_keys_have_code_defaults(tmp_path: Path):
    for cfg in (kbc.KbConfig(raw={}, root=tmp_path), kbc.load_config(tmp_path)):
        for name, value in D2_ATTRIBUTES.items():
            assert getattr(cfg, name) == value, name


def test_old_config_without_new_keys_keeps_working(tmp_path: Path):
    # A 0.15.x-era config: none of the 0.16 keys, null sections, old autorun.
    (tmp_path / "kb.config.yml").write_text(
        'instructions_version: "0.15.1"\n'
        "knowledge_base:\n  name: old\n  mode: super\n"
        "privacy:\n  require_redaction_for_chats: false\n"
        "nlp:\nlifecycle:\n  stale_warning_days: 45\n"
        "autorun:\n  complexity_auto_threshold: 0.5\n  watch_enabled: false\n"
        "mode_profiles: ~\n",
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.mode == "super"
    assert cfg.instructions_version == "0.15.1"
    assert cfg.privacy_require_redaction_for_chats is False
    assert cfg.lifecycle_stale_warning_days == 45
    assert cfg.autorun_watch_enabled is False
    assert cfg.lifecycle_by_folder == D2_ATTRIBUTES["lifecycle_by_folder"]
    assert cfg.ingest_ignore_globs == IGNORE_GLOBS
    assert cfg.profile().reflection_importance_threshold == 25


def test_load_config_bad_values_fall_back_to_defaults(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        "ingest:\n  max_file_mb: lots\n  ignore_globs: 7\n"
        "lifecycle:\n  stale_warning_days: soon\n  by_folder: {decisions: forever, inbox: temporal}\n"
        "logging:\n  rotation_threshold: '500'\n"
        "index:\n  npx_fallback: 'no'\n"
        "nlp:\n  complexity_threshold: high\n",
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.ingest_max_file_mb == 200.0
    assert cfg.ingest_ignore_globs == IGNORE_GLOBS
    assert cfg.lifecycle_stale_warning_days == 30
    assert cfg.lifecycle_by_folder == {"decisions": "forever", "inbox": "temporal"}
    assert cfg.log_rotation_threshold == 500
    assert cfg.index_npx_fallback is True  # a quoted 'no' is not a boolean
    assert cfg.complexity_threshold == 0.7


def test_load_config_non_finite_numbers_fall_back_to_defaults(tmp_path: Path):
    # Review of WP0: `.inf` on an int key crashed load_config (OverflowError)
    # and `.nan` on a float key silently disabled the size limit.
    (tmp_path / "kb.config.yml").write_text(
        "ingest:\n  max_file_mb: .nan\n"
        "lifecycle:\n  stale_warning_days: .inf\n"
        "logging:\n  rotation_threshold: -.inf\n",
        encoding="utf-8",
    )
    cfg = kbc.load_config(tmp_path)
    assert cfg.ingest_max_file_mb == 200.0
    assert cfg.lifecycle_stale_warning_days == 30
    assert cfg.log_rotation_threshold == 1000
    kbc.append_log(root=tmp_path, operation="test", title="still logs")


def test_load_config_rejects_a_non_mapping_document(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="not a mapping"):
        kbc.load_config(tmp_path)


def test_load_config_accepts_a_bom(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_bytes(b"\xef\xbb\xbfknowledge_base:\n  mode: super\n")
    assert kbc.load_config(tmp_path).mode == "super"


# ---------------------------------------------------------------------------
# Templates: kb.config.yml honesty (I5, I11, I14, G:H2) and .gitignore (D2)
# ---------------------------------------------------------------------------

_HONESTY_MARKERS = ("read by the AI agent", "not implemented yet", "deprecated", "not read by scripts")
_KEY_LINE_RE = re.compile(r"^(\s*)([A-Za-z_][\w-]*):(.*)$")


def _template_keys() -> dict[str, bool]:
    """Leaf key path → whether it (or an ancestor) carries an honesty marker.

    A key's own trailing comment and the comment block right above it count.
    """
    lines = (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8").splitlines()
    stack: list[tuple[int, str, bool]] = []
    leaves: dict[str, bool] = {}
    pending_comments: list[str] = []
    entries = []
    for line in lines:
        if line.lstrip().startswith("#"):
            pending_comments.append(line)
            continue
        if not line.strip():
            pending_comments = []
            continue
        match = _KEY_LINE_RE.match(line)
        if not match:
            pending_comments = []
            continue
        entries.append((len(match.group(1)), match.group(2), match.group(3), "\n".join(pending_comments)))
        pending_comments = []
    for index, (indent, key, rest, above) in enumerate(entries):
        while stack and stack[-1][0] >= indent:
            stack.pop()
        marked = any(m in rest or m in above for m in _HONESTY_MARKERS)
        inherited = any(item[2] for item in stack)
        path = ".".join([item[1] for item in stack] + [key])
        value = rest.split("#", 1)[0].strip()
        next_indent = entries[index + 1][0] if index + 1 < len(entries) else -1
        if value or next_indent <= indent:
            leaves[path] = marked or inherited
        stack.append((indent, key, marked or inherited))
    return leaves


def _script_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _script_files())


def test_template_parses_and_matches_the_code_defaults(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(_template_config(), encoding="utf-8")
    cfg = kbc.load_config(tmp_path)
    for name, value in D2_ATTRIBUTES.items():
        assert getattr(cfg, name) == value, name
    assert cfg.skip_extensions == (".csv", ".xlsx")


def test_template_mode_lives_only_in_knowledge_base():
    data = kbc.yaml_load(_template_config())
    assert "mode" not in data
    assert data["knowledge_base"]["mode"] == "default"
    text = (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8")
    assert "The ONE place the mode lives" in text


def test_template_skip_extensions_is_nlp_only():
    line = next(
        line for line in (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("skip_extensions:")
    )
    assert "skip NLP enrichment only — files are still ingested" in line


def test_template_ingest_comments_promise_what_kb_ingest_does():
    # kb_ingest leaves a too-large file in unsorted/ (reported by --status)
    # and reads max_file_mb <= 0 as no limit
    # (test_kb_ingest::test_max_file_mb_leaves_large_files_in_unsorted_and_0_means_no_limit).
    text = (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8")
    block = text[text.index("\ningest:\n"):text.index("\nnlp:\n")]
    line = next(line for line in block.splitlines() if line.strip().startswith("max_file_mb:"))
    assert "larger files stay in unsorted/ (kb_ingest.py --status); 0 = no limit" in line
    for promise in ("not ingested", "moved"):
        assert promise not in line


def test_template_marks_every_key_no_script_reads():
    keys = _template_keys()
    for dead in (
        "knowledge_base.index_policy",
        "privacy.external_ai_allowed",
        "media.stt.allow_cloud",
        "mode_profiles.default.surprise.engine",
        "mode_profiles.super.surprise.ai_max_per_day",
        "mode_profiles.default.lint.level2_weekly_day",
        "mode_profiles.default.annotations.engine",
        "lifecycle.confidence_decay_days",
        "indexer.output_path",
    ):
        assert keys[dead], f"{dead} needs an honesty marker"
    assert "autorun.complexity_auto_threshold" not in keys
    sources = _script_sources()
    unmarked_unread = [
        path
        for path, marked in keys.items()
        if not marked and not re.search(rf"[\"']{re.escape(path.rsplit('.', 1)[-1])}[\"']", sources)
    ]
    assert unmarked_unread == []


def test_template_new_keys_are_read_by_kb_common():
    keys = _template_keys()
    for path in (
        "ingest.ignore_globs", "ingest.max_file_mb", "ingest.duplicates_dir",
        "media.archives.max_total_mb", "media.archives.max_member_mb",
        "privacy.redact_categories", "privacy.secret_scan",
        "lifecycle.stale_warning_days", "logging.rotation_threshold",
        "index.repomix_version", "index.npx_fallback", "status.enabled", "status.file",
    ):
        assert path in keys and not keys[path], path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(repo.parent),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)


def _ignored(repo: Path, rel: str) -> bool:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return _git(repo, "check-ignore", "-q", rel).returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_gitignore_template_keeps_private_material_out_of_git(tmp_path: Path):
    repo = tmp_path / "base"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    shutil.copy(TEMPLATES / ".gitignore.template", repo / ".gitignore")
    for rel in (
        "raw/chats/unsorted/secrets-leak.txt",
        "assets/documents/2026-09-23__x.pdf",
        "processed/markdown/2026-09-23__x.md",
        "review/needs-redaction/x.md",
        "interactions/sessions/2026-09-23/x.md",
        ".kb-state/locks/pipeline.lock",
        "STATUS.md",
        ".kb-backups/heal-1/kb.config.yml",
        ".kb-finalize-backup/2026-09-23T10-00-00/README.md",
        ".kb-finalize.journal",
        "sync/inbox/b.zip",
        ".repomix/core.xml",
    ):
        assert _ignored(repo, rel), rel
    for rel in (
        "knowledge/domain/x.md",
        # Review of WP0: unanchored patterns hid knowledge sub-folders too.
        "knowledge/domain/assets/diagram.png",
        "knowledge/playbooks/review/code-review.md",
        "knowledge/domain/processed/x.md",
        "knowledge/projects/alpha/STATUS.md",
        "knowledge/people/raw/notes.md",
        "kb-docs/04_REVIEW.md",
        "kb.config.yml",
        "AGENTS.md",
        "log.md",
        "eval/results/2026-09-23__after.md",
        "sync/README.md",
        "scripts/kb_common.py",
    ):
        assert not _ignored(repo, rel), rel


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_state_dir_stays_out_of_git_without_a_gitignore_entry(tmp_path: Path):
    repo = tmp_path / "old-base"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    kbc.state_dir(repo)
    assert _ignored(repo, ".kb-state/locks/pipeline.lock")
