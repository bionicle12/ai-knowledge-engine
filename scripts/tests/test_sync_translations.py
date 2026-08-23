"""Tests for sync_translations — frontmatter metadata bumper."""
from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# --to-source / --to-commit: which commit ends up in source_commit
# ---------------------------------------------------------------------------


def _git_repo(tmp_path: Path, monkeypatch) -> Path:
    """Tiny repo whose EN source is *not* touched by the tip commit."""
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=str(tmp_path), check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q", ".")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")

    en = tmp_path / "knowledge-base"
    en.mkdir()
    (en / "00_OVERVIEW.md").write_text("# Overview\n", encoding="utf-8")
    ru = tmp_path / "i18n" / "ru"
    ru.mkdir(parents=True)
    (ru / "PAGE.md").write_text(SAMPLE, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "sources")

    # A later commit that touches something else entirely — this is the case
    # --to-head gets wrong.
    (tmp_path / "UNRELATED.md").write_text("x\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "unrelated")

    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(st, "VERSION_FILE", tmp_path / "VERSION")
    return tmp_path


def test_to_source_stamps_the_commit_that_touched_the_en_file(
    tmp_path: Path, monkeypatch
):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    stamped = re.search(
        r"(?m)^source_commit:\s*(\S+)", page.read_text(encoding="utf-8")
    ).group(1)
    assert stamped == st.source_commit_for(
        page, page.read_text(encoding="utf-8")
    )[0]
    assert stamped != st.head_sha(), "--to-source must not stamp the tip"


def test_to_head_stamps_a_commit_that_never_touched_the_source(
    tmp_path: Path, monkeypatch
):
    """The trap --to-source exists to avoid; locked in so it stays documented."""
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-head"]) == 0

    stamped = re.search(
        r"(?m)^source_commit:\s*(\S+)", page.read_text(encoding="utf-8")
    ).group(1)
    assert stamped == st.head_sha()
    assert stamped != st.source_commit_for(
        page, page.read_text(encoding="utf-8")
    )[0]


def test_to_source_is_idempotent(tmp_path: Path, monkeypatch):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"
    args = ["--files", "i18n/ru/PAGE.md", "--to-source", "--to-date", "2026-08-23"]

    st.main(args)
    once = page.read_text(encoding="utf-8")
    st.main(args)
    assert page.read_text(encoding="utf-8") == once


def test_to_source_skips_a_file_without_translation_of(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _git_repo(tmp_path, monkeypatch)
    orphan = repo / "i18n" / "ru" / "ORPHAN.md"
    orphan.write_text(
        "---\nsource_commit: 0000000\nsource_version: 0.9.0\n"
        "translated_at: 2026-01-01\n---\n\n# x\n",
        encoding="utf-8",
    )
    before = orphan.read_text(encoding="utf-8")

    assert st.main(["--files", "i18n/ru/ORPHAN.md", "--to-source"]) == 0
    assert "no translation_of" in capsys.readouterr().out
    assert orphan.read_text(encoding="utf-8") == before


def test_to_commit_accepts_a_revision(tmp_path: Path, monkeypatch):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"
    target = st.resolve_rev("HEAD~1")

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-commit", "HEAD~1"]) == 0
    assert f"source_commit: {target}" in page.read_text(encoding="utf-8")


def test_to_commit_rejects_an_unknown_revision(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"
    before = page.read_text(encoding="utf-8")

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-commit", "nope"]) == 1
    assert "not a revision" in capsys.readouterr().err
    assert page.read_text(encoding="utf-8") == before


def test_dry_run_counts_only_the_files_it_would_change(
    tmp_path: Path, monkeypatch, capsys
):
    i18n = tmp_path / "i18n" / "ru"
    i18n.mkdir(parents=True)
    (i18n / "STALE.md").write_text(SAMPLE, encoding="utf-8")
    (i18n / "CURRENT.md").write_text(
        SAMPLE.replace("source_version: 0.9.0", "source_version: 0.12.0")
        .replace("translated_at: 2026-01-01", "translated_at: 2026-08-23"),
        encoding="utf-8",
    )
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(st, "VERSION_FILE", tmp_path / "VERSION")

    st.main(["--lang", "ru", "--to-version", "0.12.0",
             "--to-date", "2026-08-23", "--dry-run"])

    out = capsys.readouterr().out
    assert "NOOP" in out
    assert "would update 1 file(s)" in out


def test_to_source_and_to_head_are_mutually_exclusive(tmp_path: Path):
    import pytest

    with pytest.raises(SystemExit):
        st.main(["--to-source", "--to-head"])
