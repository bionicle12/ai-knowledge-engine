"""Tests for immutable release snapshots (spec §6.3)."""
from __future__ import annotations

import os
import stat

import pytest

from ai_skills_fixer.filesystem import remove_tree
from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.releases import ReleaseError, create_release, release_dir
from ai_skills_fixer.store import init_store

WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


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


def test_create_release_files_are_read_only(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")

    dest = create_release(store, "awesome", "foo", skill, "c" * 40)
    for path in (dest / "SKILL.md", dest / "references" / "notes.md"):
        assert not path.stat().st_mode & WRITE_BITS, f"{path} must be read-only"


def test_existing_release_is_reused_only_while_its_hash_matches(tmp_path):
    """B4: a release edited in place (e.g. through a host skill link) is
    never trusted as-is and never rewritten silently."""
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")
    commit = "c" * 40

    first = create_release(store, "awesome", "foo", skill, commit)
    assert create_release(store, "awesome", "foo", skill, commit) == first

    marker = first / "SKILL.md"
    marker.chmod(0o644)
    marker.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ReleaseError, match="modified after it was created"):
        create_release(store, "awesome", "foo", skill, commit)
    assert marker.read_text() == "tampered\n", "existing release must not be rewritten"


def test_release_refuses_symlinks_leaving_the_skill(tmp_path):
    """B8: a link such as reference.md -> ~/.ssh/key never becomes a release."""
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")
    secret = tmp_path / "id_test"
    secret.write_text("PRIVATE KEY\n", encoding="utf-8")
    (skill / "reference.md").symlink_to(secret)

    with pytest.raises(ReleaseError, match="reference.md ->"):
        create_release(store, "awesome", "foo", skill, "c" * 40)
    assert not (store / "releases" / "awesome").exists()


def test_release_keeps_symlinks_inside_the_skill(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")
    (skill / "notes-link.md").symlink_to("references/notes.md")

    dest = create_release(store, "awesome", "foo", skill, "c" * 40)
    assert (dest / "notes-link.md").is_symlink()
    assert (dest / "notes-link.md").read_text() == "n\n"


def test_release_refuses_a_symlink_chain_escaping_the_skill(tmp_path):
    """B8 bypass: `x -> .`, `up -> x/..` each look safe lexically."""
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "skills" / "foo")
    (tmp_path / "src" / "secret.txt").write_text("SECRET\n", encoding="utf-8")
    (skill / "x").symlink_to(".")
    (skill / "up").symlink_to("x/..")
    (skill / "ref.md").symlink_to("up/../secret.txt")
    assert (skill / "ref.md").read_text() == "SECRET\n"

    with pytest.raises(ReleaseError, match="ref.md -> up/../secret.txt"):
        create_release(store, "awesome", "foo", skill, "c" * 40)
    assert not (store / "releases" / "awesome").exists()


def test_release_never_copies_git_metadata(tmp_path):
    """B6/B9: a single-skill source's path is the checkout root; its .git
    (with the clone URL, possibly a token) must not reach the release."""
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "solo")
    (skill / ".git").mkdir()
    (skill / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://ghp_SECRET@example.com/o/solo.git\n',
        encoding="utf-8",
    )

    dest = create_release(store, "solo", "skill", skill, "c" * 40)
    assert not (dest / ".git").exists()
    assert (dest / "SKILL.md").is_file()
    assert content_hash(dest) == content_hash(skill)


def test_existing_release_holding_git_metadata_is_not_reused(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "solo")
    dest = release_dir(store, "solo", "skill", "c" * 40, content_hash(skill))
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text((skill / "SKILL.md").read_text(), encoding="utf-8")
    (dest / "references").mkdir()
    (dest / "references" / "notes.md").write_text("n\n", encoding="utf-8")
    (dest / ".git").mkdir()
    assert content_hash(dest) == content_hash(skill)  # .git is outside the hash

    with pytest.raises(ReleaseError, match="modified after it was created"):
        create_release(store, "solo", "skill", skill, "c" * 40)


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX folder permissions; root ignores them",
)
def test_release_folders_are_read_only(tmp_path):
    """B4: files could not be edited, but new ones could be added or
    deleted through the host link."""
    store = tmp_path / "store"
    init_store(store, machine="m")
    skill = make_skill(tmp_path / "src" / "foo")

    dest = create_release(store, "awesome", "foo", skill, "c" * 40)
    for folder in (dest, dest / "references"):
        assert not folder.stat().st_mode & WRITE_BITS, f"{folder} must be read-only"
    with pytest.raises(PermissionError):
        (dest / "extra.md").write_text("added\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        (dest / "references" / "notes.md").unlink()

    remove_tree(dest)  # the tool can still remove it on purpose
    assert not dest.exists()
