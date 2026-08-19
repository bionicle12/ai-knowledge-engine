"""Tests for tolerant SKILL.md frontmatter parsing (spec §6.4)."""
from __future__ import annotations

from ai_skills_fixer.frontmatter import parse_skill_text, read_skill_file


def test_parses_name_and_description():
    text = "---\nname: my-skill\ndescription: Does a thing.\n---\n\n# Body\n"
    doc = parse_skill_text(text)
    assert doc.error is None
    assert doc.frontmatter["name"] == "my-skill"
    assert doc.frontmatter["description"] == "Does a thing."
    assert doc.body.strip() == "# Body"


def test_tolerates_bom_and_crlf():
    text = "﻿---\r\nname: bom-skill\r\n---\r\nbody line\r\n"
    doc = parse_skill_text(text)
    assert doc.error is None
    assert doc.frontmatter["name"] == "bom-skill"
    assert "body line" in doc.body


def test_missing_frontmatter_reports_error_and_keeps_body():
    text = "# Just a heading\n"
    doc = parse_skill_text(text)
    assert doc.error == "missing-frontmatter"
    assert doc.frontmatter == {}
    assert doc.body == text


def test_unterminated_frontmatter_is_an_error():
    text = "---\nname: broken\n"
    doc = parse_skill_text(text)
    assert doc.error == "unterminated-frontmatter"


def test_invalid_yaml_is_an_error_not_an_exception():
    text = "---\nname: [unclosed\n---\nbody\n"
    doc = parse_skill_text(text)
    assert doc.error == "invalid-yaml"
    assert doc.frontmatter == {}


def test_non_mapping_frontmatter_is_an_error():
    text = "---\n- just\n- a list\n---\nbody\n"
    doc = parse_skill_text(text)
    assert doc.error == "not-a-mapping"


def test_read_skill_file_handles_missing_file(tmp_path):
    doc = read_skill_file(tmp_path / "SKILL.md")
    assert doc.error == "unreadable"


def test_read_skill_file_reads_utf8(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: файл\n---\nтело\n", encoding="utf-8")
    doc = read_skill_file(p)
    assert doc.error is None
    assert doc.frontmatter["name"] == "файл"
