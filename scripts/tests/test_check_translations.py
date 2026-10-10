"""Tests for scripts/check_translations.py."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import check_translations as ct

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


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


def test_parse_frontmatter_strips_trailing_comment_and_stays_in_block():
    text = (
        "---\n"
        "source_commit: abc1234  # verified by hand\n"
        "translated_at:\n"
        "---\n"
        "source_version: 9.9.9\n"
    )
    fm = ct.parse_frontmatter(text)
    assert fm == {"source_commit": "abc1234", "translated_at": ""}


def test_parse_frontmatter_accepts_crlf_and_empty_block():
    assert ct.parse_frontmatter("---\r\nkey: v\r\n---\r\nbody\r\n") == {"key": "v"}
    assert ct.parse_frontmatter("---\n---\nbody\n") == {}


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


def test_render_report_marks_unknown():
    statuses = [
        ct.TranslationStatus(
            lang="ru", translation_path="i18n/ru/x.md", source_path="x.md",
            source_commit="abc1234", state="unknown", note="no git history",
        ),
    ]
    out = ct.render_report(statuses)
    assert "❔ unknown" in out
    assert "no git history" in out


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


# ---------------------------------------------------------------------------
# Drift against real git history (C1, C4, C5)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _translation(repo: Path, source_rel: str, source_commit: str) -> Path:
    return _write(
        repo / "i18n" / "ru" / source_rel,
        f"---\ntranslation_of: {source_rel}\nsource_commit: {source_commit}\n"
        "source_version: 0.15.0\ntranslated_at: 2026-08-23\n"
        "translator: human\n---\n\n# Перевод\n",
    )


@pytest.fixture
def base(tmp_path: Path, monkeypatch) -> Path:
    """A repo root outside any git checkout; ct points at it."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(ct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ct, "I18N_DIR", tmp_path / "i18n")
    monkeypatch.setattr(ct, "STATUS_FILE", tmp_path / "i18n" / "TRANSLATION_STATUS.md")
    return tmp_path


@pytest.fixture
def repo(base: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    _git(base, "init", "-q", ".")
    return base


def test_c1_copy_without_git_is_unknown_and_fails_strict(base: Path, capsys):
    # The audit repro: a copy without .git whose README was edited used to
    # report every translation "in sync" because git gave an empty sha.
    _write(base / "README.md", "# Readme, edited in the copy\n")
    page = _translation(base, "README.md", "abc1234")

    status = ct.evaluate(page)

    assert status.state == "unknown"
    assert "no git history" in status.note
    assert ct.main(["--strict"]) == 1
    assert "❔ unknown" in capsys.readouterr().out


@needs_git
def test_c1_uncommitted_new_source_is_unknown(repo: Path):
    # 17_REFACTOR / 18_HEAL showed "pending ✅ in sync" while their EN
    # sources were not committed yet.
    _write(repo / "README.md", "# Readme\n")
    _commit(repo, "readme")
    _write(repo / "knowledge-base" / "17_REFACTOR.md", "# Refactor\n")
    page = _translation(repo, "knowledge-base/17_REFACTOR.md", "pending")

    status = ct.evaluate(page)

    assert status.state == "unknown"
    assert "not committed" in status.note


@needs_git
def test_placeholder_source_commit_is_stale(repo: Path):
    _write(repo / "knowledge-base" / "18_HEAL.md", "# Heal\n")
    _commit(repo, "heal")
    page = _translation(repo, "knowledge-base/18_HEAL.md", "pending")

    status = ct.evaluate(page)

    assert status.state == "stale"
    assert "'pending' is not a commit" in status.note


@needs_git
@pytest.mark.parametrize("ref", ["HEAD", "main"])
def test_symbolic_source_commit_is_stale_not_in_sync(repo: Path, ref: str):
    """A hand-written `HEAD` or branch name resolves to the source's own tip,
    so the check compared the file with itself and always said in sync."""
    _write(repo / "README.md", "# Readme\n")
    _commit(repo, "readme")
    _git(repo, "branch", "-M", "main")
    _write(repo / "README.md", "# Readme, changed\n")
    _commit(repo, "change")
    page = _translation(repo, "README.md", ref)

    status = ct.evaluate(page)

    assert status.state == "stale"
    assert f"{ref!r} is not a commit sha" in status.note


@needs_git
def test_sha_missing_from_the_clone_is_unknown(repo: Path):
    _write(repo / "README.md", "# Readme\n")
    _commit(repo, "readme")
    page = _translation(repo, "README.md", "0123456789abcdef0123456789abcdef01234567")

    status = ct.evaluate(page)

    assert status.state == "unknown"
    assert "not in this clone" in status.note


@needs_git
def test_c5_uncommitted_source_edit_is_stale(repo: Path):
    source = _write(repo / "knowledge-base" / "03_PIPELINE.md", "# Pipeline\n")
    sha = _commit(repo, "pipeline")
    page = _translation(repo, "knowledge-base/03_PIPELINE.md", sha)
    assert ct.evaluate(page).state == "in_sync"

    source.write_text("# Pipeline\n\nNew rule.\n", encoding="utf-8")
    status = ct.evaluate(page)

    assert status.state == "stale"
    assert "uncommitted edits" in status.note


@needs_git
def test_c5_version_badge_alone_is_not_drift(repo: Path):
    badge = (
        '<a href="VERSION"><img src="https://img.shields.io/badge/version-{v}'
        '-62D8FF?style=flat-square" alt="Version {v}"></a>\n'
    )
    readme = _write(repo / "README.md", "# Engine\n" + badge.format(v="0.15.0"))
    sha = _commit(repo, "0.15.0")
    page = _translation(repo, "README.md", sha)

    readme.write_text("# Engine\n" + badge.format(v="0.15.1"), encoding="utf-8")
    _commit(repo, "bump badge")

    assert ct.evaluate(page).state == "in_sync"

    readme.write_text("# Engine 2\n" + badge.format(v="0.15.1"), encoding="utf-8")
    _commit(repo, "real change")
    status = ct.evaluate(page)
    assert status.state == "stale"
    assert status.drift_commits == 2
    assert "2 commits" in status.note


@needs_git
def test_commit_that_did_not_touch_the_source_counts_as_in_sync(repo: Path):
    # The --to-head trap: the stamped commit is a later one that never
    # touched the source. The text is identical, so this is not drift.
    _write(repo / "knowledge-base" / "00_OVERVIEW.md", "# Overview\n")
    _commit(repo, "sources")
    _write(repo / "UNRELATED.md", "x\n")
    tip = _commit(repo, "unrelated")
    page = _translation(repo, "knowledge-base/00_OVERVIEW.md", tip)

    assert ct.evaluate(page).state == "in_sync"


@needs_git
def test_source_added_after_source_commit_is_stale(repo: Path):
    _write(repo / "README.md", "# Readme\n")
    first = _commit(repo, "readme")
    _write(repo / "knowledge-base" / "19_NEW.md", "# New\n")
    _commit(repo, "new module")
    page = _translation(repo, "knowledge-base/19_NEW.md", first)

    status = ct.evaluate(page)

    assert status.state == "stale"
    assert "did not exist" in status.note


def test_c5_find_missing_covers_readme_and_nested_docs(base: Path):
    for rel in (
        "README.md",
        "knowledge-base/00_OVERVIEW.md",
        "knowledge-base/guides/deep.md",
        "knowledge-base/scripts/tests/fixtures/empty.md",
        "knowledge-base/scripts/kb_viewer/vendor/NOTICE.md",
        "quick-start/INIT_GUIDE.md",
        "quick-start/templates/AGENTS_SECTION.md",
        "quick-start/.cache/x.md",
    ):
        _write(base / rel, "# x\n")
    (base / "i18n" / "ru").mkdir(parents=True)

    missing = {s.source_path for s in ct.find_missing(base / "i18n", [])}

    assert missing == {
        "README.md",
        "knowledge-base/00_OVERVIEW.md",
        "knowledge-base/guides/deep.md",
        "quick-start/INIT_GUIDE.md",
    }


def test_c4_report_does_not_embed_head():
    statuses = [
        ct.TranslationStatus(
            lang="ru", translation_path="i18n/ru/x.md", source_path="x.md",
            source_commit="abc1234", state="in_sync",
        ),
    ]
    out = ct.render_report(statuses)
    assert "HEAD" not in out


@needs_git
def test_c4_update_status_is_stable_across_unrelated_commits(repo: Path, capsys):
    _write(repo / "README.md", "# Readme\n")
    sha = _commit(repo, "readme")
    _translation(repo, "README.md", sha)

    assert ct.main(["--update-status"]) == 0
    first = ct.STATUS_FILE.read_text(encoding="utf-8")
    _write(repo / "UNRELATED.md", "x\n")
    _commit(repo, "unrelated")
    capsys.readouterr()

    assert ct.main(["--update-status"]) == 0
    assert "Up to date" in capsys.readouterr().out
    assert ct.STATUS_FILE.read_text(encoding="utf-8") == first
    assert "✅ in sync" in first


def test_contributing_names_every_tree_the_checker_watches():
    """CONTRIBUTING said "any `knowledge-base/*.md`"; the checker also covers
    README.md and quick-start/ (CANONICAL_GLOBS)."""
    repo = Path(ct.__file__).resolve().parents[1]
    step = next(
        line for line in (repo / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8").splitlines()
        if "check_translations.py" in line
    )
    for glob in ct.CANONICAL_GLOBS:
        top = glob.split("/", 1)[0]
        assert f"`{top}/`" in step or f"`{top}`" in step, glob


@needs_git
def test_one_drift_commit_is_singular(repo: Path):
    """The note printed '1 commits'."""
    source = _write(repo / "README.md", "# Readme\n")
    sha = _commit(repo, "readme")
    page = _translation(repo, "README.md", sha)
    source.write_text("# Readme, changed\n", encoding="utf-8")
    _commit(repo, "change")

    status = ct.evaluate(page)

    assert status.state == "stale"
    assert "(1 commit)" in status.note
