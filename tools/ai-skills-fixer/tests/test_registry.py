"""Tests for the source registry and source add/refresh (spec §7.1, §7.4)."""
from __future__ import annotations

import json
import subprocess

import pytest

from ai_skills_fixer.sources import (
    CatalogError, add_source, load_registry, refresh_source,
)
from ai_skills_fixer.store import init_store


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path, skills=("foo",)):
    for skill in skills:
        d = path / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: does {skill}\n---\nbody\n",
            encoding="utf-8",
        )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    init_store(root, machine="test-machine")
    return root


def test_add_source_clones_and_registers(store, tmp_path):
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)

    spec = add_source(store, str(origin))
    assert spec.source_id == "origin-repo"
    assert spec.ref == "main"
    assert spec.layout == {"type": "collection", "roots": ["skills"]}
    assert (store / "sources" / "origin-repo" / "skills" / "foo" / "SKILL.md").is_file()

    registry = load_registry(store)
    assert registry["origin-repo"].url == str(origin)


def test_add_source_with_explicit_id_and_ref(store, tmp_path):
    origin = tmp_path / "origin"
    first = make_skill_repo(origin)
    (origin / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nv2\n")
    git("commit", "-aqm", "c2", cwd=origin)

    spec = add_source(store, str(origin), source_id="pinned", ref=first)
    assert spec.source_id == "pinned"
    assert spec.ref == first
    assert "v2" not in (
        store / "sources" / "pinned" / "skills" / "foo" / "SKILL.md"
    ).read_text()


def test_add_source_rejects_non_skill_repo(store, tmp_path):
    origin = tmp_path / "plain"
    origin.mkdir()
    (origin / "readme.md").write_text("hi\n")
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.email", "t@t", cwd=origin)
    git("config", "user.name", "t", cwd=origin)
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "c1", cwd=origin)

    with pytest.raises(CatalogError):
        add_source(store, str(origin))
    assert not (store / "sources" / "plain").exists()
    assert load_registry(store) == {}


def test_add_duplicate_source_id_raises(store, tmp_path):
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    add_source(store, str(origin))
    with pytest.raises(CatalogError):
        add_source(store, str(origin))


def test_refresh_records_candidate_without_moving_worktree(store, tmp_path):
    origin = tmp_path / "origin-repo"
    first = make_skill_repo(origin)
    add_source(store, str(origin))

    (origin / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nv2\n")
    git("commit", "-aqm", "c2", cwd=origin)

    candidate = refresh_source(store, "origin-repo")
    assert candidate["current_commit"] == first
    assert candidate["candidate_commit"] != first
    assert candidate["changed"] is True

    saved = json.loads(
        (store / "state" / "candidates" / "origin-repo.json").read_text()
    )
    assert saved["candidate_commit"] == candidate["candidate_commit"]
    assert "v2" not in (
        store / "sources" / "origin-repo" / "skills" / "foo" / "SKILL.md"
    ).read_text()


def test_load_registry_rejects_bad_schema(store):
    (store / "registry" / "repositories.yml").write_text("schema_version: 99\n")
    with pytest.raises(CatalogError):
        load_registry(store)
