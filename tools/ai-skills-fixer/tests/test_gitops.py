"""Tests for the system-git wrapper against local fixture repos (spec §6.4)."""
from __future__ import annotations

import subprocess

import pytest

from ai_skills_fixer.gitops import (
    GitError, checkout, clone, current_commit, fetch, is_dirty, rev_parse,
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
