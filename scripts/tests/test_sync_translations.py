"""Tests for sync_translations — frontmatter metadata bumper."""
from __future__ import annotations

from pathlib import Path

import sync_translations as st


SAMPLE = """---
translation_of: knowledge-base/00_OVERVIEW.md
source_commit: 0000000000000000000000000000000000000000
source_version: 0.9.0
translated_at: 2026-01-01
translator: human
---

# Заголовок

Текст перевода.
"""


def test_patch_field_replaces_value():
    text, ok = st.patch_field(SAMPLE, "source_version", "0.12.0")
    assert ok
    assert "source_version: 0.12.0" in text
    assert "source_version: 0.9.0" not in text
    # body untouched
    assert "Текст перевода." in text


def test_patch_field_missing_key_is_noop():
    text, ok = st.patch_field(SAMPLE, "nonexistent_key", "x")
    assert not ok
    assert text == SAMPLE


def test_patch_field_only_touches_first_occurrence():
    doubled = SAMPLE + "\nsource_version: 0.9.0\n"
    text, ok = st.patch_field(doubled, "source_version", "0.12.0")
    assert ok
    assert text.count("source_version: 0.12.0") == 1
    assert text.count("source_version: 0.9.0") == 1


def test_main_updates_specific_files(tmp_path: Path, monkeypatch, capsys):
    i18n = tmp_path / "i18n" / "ru"
    i18n.mkdir(parents=True)
    f = i18n / "PAGE.md"
    f.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(st, "VERSION_FILE", tmp_path / "VERSION")
    (tmp_path / "VERSION").write_text("0.12.0\n", encoding="utf-8")

    code = st.main(["--files", "i18n/ru/PAGE.md", "--to-date", "2026-08-13"])

    assert code == 0
    updated = f.read_text(encoding="utf-8")
    assert "source_version: 0.12.0" in updated
    assert "translated_at: 2026-08-13" in updated
    # source_commit untouched without --to-head
    assert "source_commit: 0000000000000000000000000000000000000000" in updated


def test_main_dry_run_changes_nothing(tmp_path: Path, monkeypatch):
    i18n = tmp_path / "i18n" / "ru"
    i18n.mkdir(parents=True)
    f = i18n / "PAGE.md"
    f.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(st, "VERSION_FILE", tmp_path / "VERSION")

    code = st.main(["--lang", "ru", "--to-version", "9.9.9", "--dry-run"])

    assert code == 0
    assert f.read_text(encoding="utf-8") == SAMPLE


def test_collect_files_skips_status_file(tmp_path: Path, monkeypatch):
    i18n = tmp_path / "i18n"
    (i18n / "ru").mkdir(parents=True)
    (i18n / "ru" / "PAGE.md").write_text(SAMPLE, encoding="utf-8")
    (i18n / "ru" / "TRANSLATION_STATUS.md").write_text("# x\n", encoding="utf-8")
    monkeypatch.setattr(st, "I18N_DIR", i18n)

    class _Args:
        files = None
        lang = None

    files = st.collect_files(_Args())
    assert [p.name for p in files] == ["PAGE.md"]
