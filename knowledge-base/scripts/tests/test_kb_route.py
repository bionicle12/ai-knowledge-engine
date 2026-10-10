"""Tests for deterministic routing-page generation."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import kb_common as kbc
import kb_route


def _make_page(knowledge: Path, relpath: str, *, title: str) -> Path:
    page = knowledge / relpath
    page.parent.mkdir(parents=True, exist_ok=True)
    kbc.write_frontmatter_file(
        page,
        {
            "source": "raw/example.md",
            "extracted_at": dt.date.today().isoformat(),
            "tags": ["test"],
            "lifecycle": "evolving",
        },
        f"# {title}\n\ncontent\n",
    )
    return page


def test_generate_routes_creates_section_pages_and_root_block(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    _make_page(knowledge, "domain/brand.md", title="Brand")
    _make_page(
        knowledge,
        "projects/roadmap/near-term.md",
        title="Near Term Roadmap",
    )

    result = kb_route.generate_routes(tmp_path)

    domain_page = knowledge / "routing" / "domain.md"
    projects_page = knowledge / "routing" / "projects.md"
    root_table = knowledge / "routing-table.md"
    assert result["root_table"] == "knowledge/routing-table.md"
    assert "[[domain/brand]] - Brand" in domain_page.read_text(encoding="utf-8")
    projects_text = projects_page.read_text(encoding="utf-8")
    assert "## Roadmap" in projects_text
    assert "[[projects/roadmap/near-term]] - Near Term Roadmap" in projects_text
    root_text = root_table.read_text(encoding="utf-8")
    assert "<!-- AUTO-ROUTING:BEGIN -->" in root_text
    assert "[[routing/domain]] - market, product, and strategic knowledge." in root_text


def test_generate_routes_preserves_manual_root_content(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    _make_page(knowledge, "voice/product-messaging.md", title="Product Messaging")
    kbc.write_frontmatter_file(
        knowledge / "routing-table.md",
        {
            "source": "manual",
            "extracted_at": dt.date.today().isoformat(),
            "tags": ["routing"],
            "lifecycle": "evolving",
        },
        "# Routing Table\n\nManual intro.\n",
    )

    kb_route.generate_routes(tmp_path)

    text = (knowledge / "routing-table.md").read_text(encoding="utf-8")
    assert text.count("Manual intro.") == 1
    assert "[[routing/voice]] - messaging and tone rules." in text


def _age(path: Path, seconds: float = 3600) -> float:
    """Push a file's mtime into the past; return the new mtime."""
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))
    return stamp


def _set_meta(page: Path, **values) -> None:
    meta, body = kbc.read_frontmatter_file(page)
    meta.update(values)
    kbc.write_frontmatter_file(page, meta, body)


def test_second_run_writes_nothing(tmp_path: Path):
    """kb_route rewrote every routing page on every run (new mtime, dates =
    today, access_count = 0): the watcher saw its own writes as edits and
    looped reindex → route → reindex (C1, M10, I17)."""
    knowledge = tmp_path / "knowledge"
    _make_page(knowledge, "domain/brand.md", title="Brand")
    kb_route.generate_routes(tmp_path)
    domain_page = knowledge / "routing" / "domain.md"
    root_table = knowledge / "routing-table.md"
    _set_meta(domain_page, extracted_at="2026-01-01", last_verified="2026-01-02",
              valid_from="2026-01-01", last_accessed="2026-01-03", access_count=7)
    before = {p: (_age(p), p.read_bytes()) for p in (domain_page, root_table)}

    result = kb_route.generate_routes(tmp_path)

    assert result["written"] == []
    assert result["unchanged"] == ["knowledge/routing/domain.md"]
    assert result["root_table_written"] is False
    for page, (mtime, data) in before.items():
        assert page.stat().st_mtime == mtime
        assert page.read_bytes() == data


def test_changed_section_keeps_dates_and_counters(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    _make_page(knowledge, "domain/brand.md", title="Brand")
    kb_route.generate_routes(tmp_path)
    domain_page = knowledge / "routing" / "domain.md"
    _set_meta(domain_page, extracted_at="2026-01-01", last_verified="2026-01-02",
              last_accessed="2026-01-03", access_count=7, note="kept")
    _make_page(knowledge, "domain/pricing.md", title="Pricing")

    result = kb_route.generate_routes(tmp_path)

    assert result["written"] == ["knowledge/routing/domain.md"]
    meta, body = kbc.read_frontmatter_file(domain_page)
    assert "[[domain/pricing]] - Pricing" in body
    assert meta["last_verified"] == dt.date.today().isoformat()
    assert meta["extracted_at"] == "2026-01-01"
    assert meta["last_accessed"] == "2026-01-03"
    assert meta["access_count"] == 7
    assert meta["note"] == "kept"
    assert meta["generated_by"] == "kb_route.py"


def test_non_utf8_page_is_routed_with_its_title(tmp_path: Path):
    """One cp1251 page used to abort the whole run (UnicodeDecodeError)."""
    page = tmp_path / "knowledge" / "domain" / "legacy.md"
    page.parent.mkdir(parents=True)
    page.write_bytes("---\nsource: manual\n---\n# Переписка с клиентом\n".encode("cp1251"))

    kb_route.generate_routes(tmp_path)

    text = (tmp_path / "knowledge" / "routing" / "domain.md").read_text(encoding="utf-8")
    assert "[[domain/legacy]] - Переписка с клиентом" in text


def test_routing_table_with_broken_frontmatter_is_left_alone(tmp_path: Path):
    """Invalid YAML parsed as 'no frontmatter' and got a second one prepended."""
    knowledge = tmp_path / "knowledge"
    _make_page(knowledge, "domain/brand.md", title="Brand")
    table = knowledge / "routing-table.md"
    original = "---\ntitle: [unclosed\n---\n# Routing Table\n\nManual notes.\n"
    table.write_text(original, encoding="utf-8")

    result = kb_route.generate_routes(tmp_path)

    assert table.read_text(encoding="utf-8") == original
    assert result["root_table_written"] is False
    assert "left unchanged" in result["warnings"][0]
    assert (knowledge / "routing" / "domain.md").is_file()


def test_archived_pages_are_not_routed(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    _make_page(knowledge, "domain/live.md", title="Live")
    _make_page(knowledge, "domain/_archive/old.md", title="Old")

    kb_route.generate_routes(tmp_path)

    text = (knowledge / "routing" / "domain.md").read_text(encoding="utf-8")
    assert "[[domain/live]]" in text
    assert "_archive" not in text


def test_main_refuses_a_folder_without_kb_config(tmp_path: Path, capsys):
    """A wrong --root used to grow a phantom knowledge/routing/ tree (M11)."""
    assert kb_route.main(["--root", str(tmp_path)]) == 2
    assert not (tmp_path / "knowledge").exists()
    assert "no kb.config.yml" in capsys.readouterr().err


def test_main_resolves_a_relative_root(tmp_path: Path, monkeypatch, capsys):
    base = tmp_path / "kb"
    (base / "knowledge").mkdir(parents=True)
    (base / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    _make_page(base / "knowledge", "domain/brand.md", title="Brand")
    monkeypatch.chdir(tmp_path)

    assert kb_route.main(["--root", "kb"]) == 0
    assert (base / "knowledge" / "routing" / "domain.md").is_file()
    assert "knowledge/routing-table.md: updated" in capsys.readouterr().out
    assert kb_route.main(["--root", "kb"]) == 0
    assert "knowledge/routing-table.md: unchanged" in capsys.readouterr().out
