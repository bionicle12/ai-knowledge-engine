"""Tests for the canonical skill content hash (spec §6.3)."""
from __future__ import annotations

import hashlib

from ai_skills_fixer.provenance import content_hash


def make_skill(root, files):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_identical_trees_hash_equal(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    files = {"SKILL.md": "---\nname: x\n---\nbody\n", "references/notes.md": "n\n"}
    make_skill(a, files)
    make_skill(b, files)
    assert content_hash(a) == content_hash(b)


def test_content_change_changes_hash(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_skill(a, {"SKILL.md": "one\n"})
    make_skill(b, {"SKILL.md": "two\n"})
    assert content_hash(a) != content_hash(b)


def test_git_dir_is_excluded(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_skill(a, {"SKILL.md": "same\n"})
    make_skill(b, {"SKILL.md": "same\n", ".git/HEAD": "ref: refs/heads/main\n"})
    assert content_hash(a) == content_hash(b)


def test_matches_documented_manifest_algorithm(tmp_path):
    skill = tmp_path / "skill"
    make_skill(skill, {"b.md": "bee\n", "a/deep.md": "deep\n"})

    def file_sha(text):
        return hashlib.sha256(text.encode()).hexdigest()

    manifest = (
        f"a/deep.md\n{file_sha('deep\n')}\n"
        f"b.md\n{file_sha('bee\n')}\n"
    )
    expected = hashlib.sha256(manifest.encode()).hexdigest()
    assert content_hash(skill) == expected


def test_symlink_contributes_target_string(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_skill(a, {"SKILL.md": "s\n"})
    make_skill(b, {"SKILL.md": "s\n"})
    (a / "link.md").symlink_to("SKILL.md")
    (b / "link.md").symlink_to("other-target.md")
    assert content_hash(a) != content_hash(b)
