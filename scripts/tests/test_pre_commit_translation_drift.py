"""Tests for scripts/hooks/pre-commit-translation-drift.sh."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pre-commit-translation-drift.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("sh") is None,
    reason="needs git and a POSIX sh",
)

# EN source → does a translation exist for it
FILES = {
    "README.md": True,
    "knowledge-base/My Module.md": True,
    "knowledge-base/50%s done.md": True,
    "knowledge-base/03_PIPELINE.md": True,
    "knowledge-base/scripts/tests/fixtures/empty.md": True,
    "quick-start/templates/AGENTS_SECTION.md": True,
    "quick-start/INIT_GUIDE.md": False,
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    _git(tmp_path, "init", "-q", ".")
    for rel, translated in FILES.items():
        src = tmp_path / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("# EN\n", encoding="utf-8")
        if translated:
            tr = tmp_path / "i18n" / "ru" / rel
            tr.parent.mkdir(parents=True, exist_ok=True)
            tr.write_text("# RU\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def _stage(repo: Path, *rels: str) -> None:
    for rel in rels:
        (repo / rel).write_text("# changed\n", encoding="utf-8")
    _git(repo, "add", "--", *rels)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(HOOK)], cwd=str(repo), capture_output=True, text=True
    )


def test_readme_and_odd_file_names_are_reported_verbatim(repo: Path):
    _stage(repo, "README.md", "knowledge-base/My Module.md", "knowledge-base/50%s done.md")

    result = _run_hook(repo)

    assert result.returncode == 0
    out = result.stdout
    assert "i18n/ru/README.md (will be stale relative to README.md)" in out
    assert "i18n/ru/knowledge-base/My Module.md (will be stale" in out
    # the path is data, never a printf format
    assert "i18n/ru/knowledge-base/50%s done.md (will be stale" in out


def test_staged_translation_and_non_doc_folders_are_not_reported(repo: Path):
    _stage(
        repo,
        "knowledge-base/03_PIPELINE.md",
        "i18n/ru/knowledge-base/03_PIPELINE.md",
        "knowledge-base/scripts/tests/fixtures/empty.md",
        "quick-start/templates/AGENTS_SECTION.md",
        "quick-start/INIT_GUIDE.md",
    )

    result = _run_hook(repo)

    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_is_silent_without_canonical_changes(repo: Path):
    (repo / "notes.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")

    result = _run_hook(repo)

    assert result.returncode == 0
    assert result.stdout == ""


def test_advice_stamps_only_the_updated_translations(repo: Path):
    """A bare `sync_translations.py --to-source` re-stamps every translation
    whose source moved, the stale ones nobody updated included."""
    _stage(repo, "README.md")

    out = _run_hook(repo).stdout

    assert "sync_translations.py --to-source --files <the translations you updated>" in out
    assert "sync_translations.py --to-source\n" not in out


@pytest.mark.parametrize("how", ["rm", "mv"])
def test_deleted_or_renamed_source_with_a_translation_is_reported(repo: Path, how: str):
    """--diff-filter=ACMR hid a deleted (or renamed) source whose translation
    stays behind as an orphan."""
    if how == "rm":
        _git(repo, "rm", "-q", "knowledge-base/03_PIPELINE.md")
    else:
        _git(repo, "mv", "knowledge-base/03_PIPELINE.md", "knowledge-base/03_INGEST.md")

    result = _run_hook(repo)

    assert result.returncode == 0
    assert ("i18n/ru/knowledge-base/03_PIPELINE.md (its source "
            "knowledge-base/03_PIPELINE.md is deleted or renamed)") in result.stdout
    assert "will be stale" not in result.stdout


def test_deleting_the_translation_with_its_source_is_silent(repo: Path):
    _git(repo, "rm", "-q", "knowledge-base/03_PIPELINE.md", "i18n/ru/knowledge-base/03_PIPELINE.md")

    result = _run_hook(repo)

    assert result.returncode == 0
    assert result.stdout == ""
