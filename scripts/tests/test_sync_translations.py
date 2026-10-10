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
    assert "translated_at: 2026-08-13" in updated
    # C3: only what was asked for; VERSION is not stamped without a re-sync
    assert "source_version: 0.9.0" in updated
    # source_commit untouched without --to-source/--to-commit/--to-head
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


# ---------------------------------------------------------------------------
# C2: patch_field edits one frontmatter line, never the next line or the body
# ---------------------------------------------------------------------------


def test_c2_empty_value_does_not_swallow_the_next_line():
    text = (
        "---\n"
        "translation_of: knowledge-base/00_OVERVIEW.md\n"
        "source_commit:\n"
        "translated_at: 2026-01-01\n"
        "---\n"
        "body\n"
    )
    new, ok = st.patch_field(text, "source_commit", "abc123")
    assert ok
    assert new == text.replace("source_commit:\n", "source_commit: abc123\n")
    assert "translated_at: 2026-01-01" in new


def test_c2_key_missing_from_frontmatter_leaves_the_body_alone():
    text = (
        "---\n"
        "translation_of: knowledge-base/00_OVERVIEW.md\n"
        "---\n"
        "\n"
        "```yaml\n"
        "source_version: 0.3.0\n"
        "```\n"
    )
    new, ok = st.patch_field(text, "source_version", "0.16.0")
    assert not ok
    assert new == text


def test_patch_field_without_frontmatter_is_noop():
    text = "# No frontmatter\nsource_commit: abc\n"
    assert st.patch_field(text, "source_commit", "def") == (text, False)


def test_patch_field_keeps_trailing_comment_and_crlf():
    text = "---\r\nsource_version: 0.9.0  # checked\r\ntranslator: human\r\n---\r\nbody\r\n"
    new, ok = st.patch_field(text, "source_version", "0.16.0")
    assert ok
    assert new == text.replace("0.9.0", "0.16.0")


def test_main_keeps_crlf_line_endings(tmp_path: Path, monkeypatch):
    page = tmp_path / "i18n" / "ru" / "PAGE.md"
    page.parent.mkdir(parents=True)
    page.write_bytes(SAMPLE.replace("\n", "\r\n").encode("utf-8"))
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")

    assert st.main(["--lang", "ru", "--to-date", "2026-09-24"]) == 0

    data = page.read_bytes()
    assert b"translated_at: 2026-09-24\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")


# ---------------------------------------------------------------------------
# C3: nothing is stamped that was not asked for or re-synced
# ---------------------------------------------------------------------------


def test_c3_bare_run_stamps_nothing_and_fails(tmp_path: Path, monkeypatch, capsys):
    page = tmp_path / "i18n" / "ru" / "PAGE.md"
    page.parent.mkdir(parents=True)
    page.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(st, "VERSION_FILE", tmp_path / "VERSION")
    (tmp_path / "VERSION").write_text("0.16.0\n", encoding="utf-8")

    assert st.main([]) == 1
    assert "nothing to stamp" in capsys.readouterr().err
    assert page.read_text(encoding="utf-8") == SAMPLE


def test_c3_to_source_dates_only_the_files_it_resyncs(tmp_path: Path, monkeypatch):
    repo = _git_repo(tmp_path, monkeypatch)
    (repo / "VERSION").write_text("0.16.0\n", encoding="utf-8")
    moved = repo / "i18n" / "ru" / "PAGE.md"
    current = repo / "i18n" / "ru" / "CURRENT.md"
    sha = st.source_commit_for(moved, SAMPLE)[0]
    current.write_text(
        SAMPLE.replace("0" * 40, sha), encoding="utf-8"
    )
    before = current.read_text(encoding="utf-8")

    assert st.main(["--lang", "ru", "--to-source"]) == 0

    # Already stamped with the right commit: its date and version stay.
    assert current.read_text(encoding="utf-8") == before
    text = moved.read_text(encoding="utf-8")
    assert f"source_commit: {sha}" in text
    assert "source_version: 0.16.0" in text
    assert f"translated_at: {st._dt.date.today().isoformat()}" in text


def test_to_source_without_version_file_leaves_source_version(
    tmp_path: Path, monkeypatch
):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    text = page.read_text(encoding="utf-8")
    assert "source_version: 0.9.0" in text
    assert "unknown" not in text


def test_to_source_skips_a_source_with_uncommitted_edits(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"
    (repo / "knowledge-base" / "00_OVERVIEW.md").write_text(
        "# Overview, edited\n", encoding="utf-8"
    )

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    assert "uncommitted edits" in capsys.readouterr().out
    assert page.read_text(encoding="utf-8") == SAMPLE


def test_files_outside_i18n_are_skipped(tmp_path: Path, monkeypatch, capsys):
    en = tmp_path / "knowledge-base" / "00_OVERVIEW.md"
    en.parent.mkdir(parents=True)
    en.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")

    assert st.main(["--files", "knowledge-base/00_OVERVIEW.md",
                    "--to-date", "2026-09-24"]) == 0

    assert "not under i18n/" in capsys.readouterr().out
    assert en.read_text(encoding="utf-8") == SAMPLE


def test_bad_to_date_is_rejected(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(st, "I18N_DIR", tmp_path / "i18n")

    assert st.main(["--to-date", "24.09.2026"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_to_source_then_check_reports_in_sync(tmp_path: Path, monkeypatch):
    import check_translations as ct

    repo = _git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(ct, "REPO_ROOT", repo)
    page = repo / "i18n" / "ru" / "PAGE.md"
    assert ct.evaluate(page).state != "in_sync"

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    assert ct.evaluate(page).state == "in_sync"


def test_to_source_keeps_a_sha_when_the_source_changed_only_its_badge(
    tmp_path: Path, monkeypatch, capsys
):
    """C3: a badge-only release bump is no drift for the checker, but
    --to-source moved source_commit to it and re-dated the translation."""
    import subprocess

    repo = _git_repo(tmp_path, monkeypatch)
    (repo / "VERSION").write_text("0.16.0\n", encoding="utf-8")
    source = repo / "knowledge-base" / "00_OVERVIEW.md"
    badge = "![v](https://img.shields.io/badge/version-{}-blue)\n"
    source.write_text("# Overview\n" + badge.format("0.15.0"), encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "text"], cwd=repo, check=True)
    page = repo / "i18n" / "ru" / "PAGE.md"
    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source", "--to-date", "2026-08-23"]) == 0
    stamped = page.read_text(encoding="utf-8")

    source.write_text("# Overview\n" + badge.format("0.16.0"), encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "release"], cwd=repo, check=True)
    capsys.readouterr()
    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    assert page.read_text(encoding="utf-8") == stamped
    assert "NOOP i18n/ru/PAGE.md (no drift since source_commit)" in capsys.readouterr().out

    # A real text change still moves it.
    source.write_text("# Overview, changed\n" + badge.format("0.16.0"), encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "change"], cwd=repo, check=True)
    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0
    assert page.read_text(encoding="utf-8") != stamped


def test_missing_frontmatter_key_is_named_not_a_silent_noop(
    tmp_path: Path, monkeypatch, capsys
):
    """C2: without `source_commit:` the file printed a bare NOOP while the
    checker kept reporting 'no source_commit recorded'."""
    repo = _git_repo(tmp_path, monkeypatch)
    page = repo / "i18n" / "ru" / "PAGE.md"
    page.write_text(re.sub(r"(?m)^source_commit:.*\n", "", SAMPLE), encoding="utf-8")
    before = page.read_text(encoding="utf-8")

    assert st.main(["--files", "i18n/ru/PAGE.md", "--to-source"]) == 0

    assert page.read_text(encoding="utf-8") == before
    assert ("NOOP i18n/ru/PAGE.md (no source_commit in the frontmatter; add by hand)"
            in capsys.readouterr().out)
