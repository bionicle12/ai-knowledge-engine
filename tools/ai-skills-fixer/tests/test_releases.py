"""Tests for immutable release snapshots (spec §6.3)."""
from __future__ import annotations

from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.releases import create_release, release_dir
from ai_skills_fixer.store import init_store


def make_skill(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\nname: foo\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    (root / "references").mkdir()
    (root / "references" / "notes.md").write_text("n\n", encoding="utf-8")
    return root


def test_release_path_formula(tmp_path):
    store = tmp_path / "store"
    commit = "a" * 40
    digest = "b" * 64
    path = release_dir(store, "awesome", "backend-architect", commit, digest)
    assert path == store / "releases" / "awesome" / "backend-architect" / (
        "a" * 12 + "-" + "b" * 12
    )


def test_create_release_materializes_full_copy(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")
    commit = "c" * 40

    dest = create_release(store, "awesome", "foo", skill, commit)
    assert (dest / "SKILL.md").is_file()
    assert (dest / "references" / "notes.md").is_file()
    assert content_hash(dest) == content_hash(skill)
    assert dest.name == "c" * 12 + "-" + content_hash(skill)[:12]


def test_create_release_is_immutable_once_created(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")
    commit = "c" * 40

    first = create_release(store, "awesome", "foo", skill, commit)
    marker = first / "SKILL.md"
    marker.write_text("tampered\n", encoding="utf-8")

    second = create_release(store, "awesome", "foo", skill, commit)
    assert second == first
    assert marker.read_text() == "tampered\n", "existing release must not be rewritten"
