"""Tests for deterministic routing-page generation."""
from __future__ import annotations

import datetime as dt
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
