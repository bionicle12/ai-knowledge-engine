"""Tests for scripts/check_translations.py."""
from __future__ import annotations

from pathlib import Path

import check_translations as ct


def test_parse_frontmatter_basic():
    text = (
        "---\n"
        "translation_of: knowledge-base/03_PIPELINE.md\n"
        "source_commit: abc1234\n"
        "translator: human\n"
        "---\n"
        "body\n"
    )
    fm = ct.parse_frontmatter(text)
    assert fm["translation_of"] == "knowledge-base/03_PIPELINE.md"
    assert fm["source_commit"] == "abc1234"
    assert fm["translator"] == "human"


def test_parse_frontmatter_handles_missing_block():
    fm = ct.parse_frontmatter("# Just a heading\nno frontmatter\n")
    assert fm == {}


def test_parse_frontmatter_strips_quotes():
    text = '---\nname: "quoted value"\n---\nbody\n'
    fm = ct.parse_frontmatter(text)
    assert fm["name"] == "quoted value"


def test_parse_frontmatter_ignores_blank_and_invalid_lines():
    text = (
        "---\n"
        "good: value\n"
        "\n"
        "no-colon-line\n"
        "---\n"
        "body\n"
    )
    fm = ct.parse_frontmatter(text)
    assert fm == {"good": "value"}


def test_render_report_no_translations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ct, "I18N_DIR", tmp_path / "i18n")
    out = ct.render_report([])
    assert "Translation Status" in out


def test_render_report_with_in_sync_entry():
    statuses = [
        ct.TranslationStatus(
            lang="ru",
            translation_path="i18n/ru/x.md",
            source_path="x.md",
            source_commit="abc1234",
            actual_source_commit="abc1234",
            state="in_sync",
        ),
    ]
    out = ct.render_report(statuses)
    assert "ru" in out
    assert "in sync" in out
    assert "abc1234" in out


def test_render_report_marks_stale():
    statuses = [
        ct.TranslationStatus(
            lang="ru",
            translation_path="i18n/ru/x.md",
            source_path="x.md",
            source_commit="aaa1111",
            actual_source_commit="bbb2222",
            drift_commits=3,
            state="stale",
            note="3 commits behind",
        ),
    ]
    out = ct.render_report(statuses)
    assert "stale" in out
    assert "3 commits" in out


def test_collect_translations_finds_md_only(tmp_path: Path):
    i18n = tmp_path / "i18n"
    (i18n / "ru" / "knowledge-base").mkdir(parents=True)
    (i18n / "ru" / "knowledge-base" / "01.md").write_text("hello", encoding="utf-8")
    (i18n / "ru" / "knowledge-base" / "skip.txt").write_text("skip", encoding="utf-8")
    (i18n / "TRANSLATION_STATUS.md").write_text("# status", encoding="utf-8")
    found = ct.collect_translations(i18n)
    assert len(found) == 1
    assert found[0].name == "01.md"


def test_evaluate_orphan_when_translation_of_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ct, "REPO_ROOT", tmp_path)
    p = tmp_path / "i18n" / "ru" / "x.md"
    p.parent.mkdir(parents=True)
    p.write_text("# no frontmatter\n", encoding="utf-8")
    status = ct.evaluate(p)
    assert status.state == "orphan"
    assert "translation_of" in status.note


def test_evaluate_orphan_when_source_path_does_not_exist(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ct, "REPO_ROOT", tmp_path)
    p = tmp_path / "i18n" / "ru" / "ghost.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "translation_of: knowledge-base/ghost.md\n"
        "source_commit: abc1234\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    status = ct.evaluate(p)
    assert status.state == "orphan"
    assert "source file not found" in status.note
