"""Tests for the system-git wrapper against local fixture repos (spec §6.4)."""
from __future__ import annotations

import subprocess

import pytest

from ai_skills_fixer import gitops
from ai_skills_fixer.gitops import (
    GitError, checkout, clone, current_commit, fetch, is_dirty, redact_url,
    rev_parse,
)


def git(*args, cwd):
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def make_repo(path, filename="f.txt", content="one\n"):
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    (path / filename).write_text(content)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def test_clone_local_repo(tmp_path):
    origin = tmp_path / "origin"
    sha = make_repo(origin)
    dest = tmp_path / "dest"
    clone(str(origin), dest)
    assert (dest / "f.txt").read_text() == "one\n"
    assert current_commit(dest) == sha


def test_checkout_specific_commit(tmp_path):
    origin = tmp_path / "origin"
    first = make_repo(origin)
    (origin / "f.txt").write_text("two\n")
    git("commit", "-aqm", "c2", cwd=origin)

    dest = tmp_path / "dest"
    clone(str(origin), dest)
    checkout(dest, first)
    assert (dest / "f.txt").read_text() == "one\n"
    assert current_commit(dest) == first


def test_fetch_sees_new_origin_commits_without_moving_worktree(tmp_path):
    origin = tmp_path / "origin"
    first = make_repo(origin)
    dest = tmp_path / "dest"
    clone(str(origin), dest)

    (origin / "f.txt").write_text("three\n")
    git("commit", "-aqm", "c2", cwd=origin)

    fetch(dest)
    assert current_commit(dest) == first
    assert rev_parse(dest, "origin/main") != first
    assert (dest / "f.txt").read_text() == "one\n"


def test_is_dirty(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo)
    assert is_dirty(repo) is False
    (repo / "f.txt").write_text("dirty\n")
    assert is_dirty(repo) is True


def test_git_error_is_raised_not_leaked(tmp_path):
    with pytest.raises(GitError):
        rev_parse(tmp_path, "HEAD")


def test_clone_never_parses_the_url_as_an_option(tmp_path, monkeypatch):
    """B1: `git clone -- <url>` — a source named like an option is a path.

    Without the `--`, git reads `-origin` as `-o rigin` and the clone
    fails (or, with a crafted URL, runs with attacker-chosen options).
    """
    sha = make_repo(tmp_path / "-origin")
    monkeypatch.chdir(tmp_path)
    clone("-origin", tmp_path / "dest")
    assert current_commit(tmp_path / "dest") == sha


@pytest.mark.parametrize("ref", ["--orphan=x", "-b", ""])
def test_refs_that_look_like_options_are_refused(tmp_path, ref):
    origin = tmp_path / "origin"
    make_repo(origin)
    with pytest.raises(GitError, match="refusing git ref"):
        checkout(origin, ref)
    with pytest.raises(GitError, match="refusing git ref"):
        rev_parse(origin, ref)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x-access-token:ghp_SECRET@github.com/o/r.git",
         "https://github.com/o/r.git"),
        ("https://ghp_SECRET@github.com/o/r.git", "https://github.com/o/r.git"),
        ("ssh://git:SECRET@host/o/r.git", "ssh://git@host/o/r.git"),
        ("ssh://git@host/o/r.git", "ssh://git@host/o/r.git"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("/srv/skills/repo", "/srv/skills/repo"),
    ],
)
def test_redact_url_drops_credentials_only(url, expected):
    assert redact_url(url) == expected


def test_clone_error_never_echoes_url_credentials(tmp_path, monkeypatch):
    """B9: a failing clone of a token URL must not print the token."""
    def fake_run(args, cwd=None):
        raise GitError(
            f"git {' '.join(args)} failed (rc=128): fatal: unable to access "
            f"'{args[-2]}': could not resolve host"
        )

    monkeypatch.setattr(gitops, "_run", fake_run)
    with pytest.raises(GitError) as info:
        clone("https://user:ghp_SECRET@example.invalid/o/r.git", tmp_path / "d")
    assert "SECRET" not in str(info.value)
    assert "example.invalid/o/r.git" in str(info.value)
