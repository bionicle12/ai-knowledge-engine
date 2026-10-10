"""Tests for source repository scanning and path-based skill IDs (spec §7.1)."""
from __future__ import annotations

import pytest

from ai_skills_fixer.sources import CatalogError, scan_source


def write_skill(root, rel, name="x", description="does x"):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )


def test_scan_collection_finds_skills_with_skill_md(tmp_path):
    write_skill(tmp_path, "skills/backend-architect", name="backend-architect")
    write_skill(tmp_path, "skills/clean-code", name="clean-code")
    (tmp_path / "skills" / "not-a-skill").mkdir()

    found = scan_source(
        "awesome", tmp_path, {"type": "collection", "roots": ["skills"]}
    )
    ids = sorted(s.skill_id for s in found)
    assert ids == ["awesome:backend-architect", "awesome:clean-code"]


def test_scan_collection_reads_frontmatter_metadata(tmp_path):
    write_skill(tmp_path, "skills/foo", name="foo", description="foo helper")
    (found,) = scan_source(
        "awesome", tmp_path, {"type": "collection", "roots": ["skills"]}
    )
    assert found.name == "foo"
    assert found.description == "foo helper"
    assert found.rel_path == "skills/foo"


def test_nested_skill_dirs_get_path_ids(tmp_path):
    write_skill(tmp_path, "skills/group/deep-skill")
    (found,) = scan_source(
        "awesome", tmp_path, {"type": "collection", "roots": ["skills"]}
    )
    assert found.skill_id == "awesome:group/deep-skill"


def test_skill_dirs_are_not_scanned_inside(tmp_path):
    write_skill(tmp_path, "skills/outer")
    write_skill(tmp_path, "skills/outer/references/inner")
    found = scan_source(
        "awesome", tmp_path, {"type": "collection", "roots": ["skills"]}
    )
    assert [s.skill_id for s in found] == ["awesome:outer"]


def test_duplicate_relative_paths_across_roots_raise(tmp_path):
    write_skill(tmp_path, "root-a/foo")
    write_skill(tmp_path, "root-b/foo")
    with pytest.raises(CatalogError):
        scan_source(
            "awesome", tmp_path, {"type": "collection", "roots": ["root-a", "root-b"]}
        )


def test_broken_frontmatter_is_recorded_not_fatal(tmp_path):
    d = tmp_path / "skills" / "broken"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
    (found,) = scan_source(
        "awesome", tmp_path, {"type": "collection", "roots": ["skills"]}
    )
    assert found.skill_id == "awesome:broken"
    assert found.error == "missing-frontmatter"


def test_scan_single_uses_bare_source_id(tmp_path):
    write_skill(tmp_path, ".", name="solo")
    (found,) = scan_source("solo-src", tmp_path, {"type": "single", "skill_path": "."})
    assert found.skill_id == "solo-src"
    assert found.name == "solo"


def test_linked_skill_folder_leaving_the_checkout_stops_the_catalog(tmp_path):
    """B1/B8: `skills/notes -> /abs/private-notes` used to be scanned,
    snapshotted and installed as if the source provided it."""
    repo = tmp_path / "repo"
    write_skill(repo, "skills/foo", name="foo")
    private = tmp_path / "private-notes"
    write_skill(tmp_path, "private-notes", name="notes")
    (private / "credentials.txt").write_text("TOPSECRET\n", encoding="utf-8")
    (repo / "skills" / "notes").symlink_to(private, target_is_directory=True)

    with pytest.raises(CatalogError, match="'skills/notes' resolves outside"):
        scan_source("s", repo, {"type": "collection", "roots": ["skills"]})


def test_linked_skill_folder_into_git_metadata_stops_the_catalog(tmp_path):
    repo = tmp_path / "repo"
    write_skill(repo, "skills/foo", name="foo")
    write_skill(repo, ".git/stash", name="stash")
    (repo / "skills" / "stash").symlink_to(repo / ".git" / "stash")

    with pytest.raises(CatalogError, match="resolves outside"):
        scan_source("s", repo, {"type": "collection", "roots": ["skills"]})
    with pytest.raises(CatalogError, match="leaves the checkout"):
        scan_source("s", repo, {"type": "single", "skill_path": ".git/stash"})


def test_linked_folders_inside_the_checkout(tmp_path):
    """A linked skill folder inside the checkout is fine; linked non-skill
    folders are never searched (no loops, no walks elsewhere)."""
    repo = tmp_path / "repo"
    write_skill(repo, "lib/real", name="real")
    write_skill(repo, "skills/foo", name="foo")
    (repo / "skills" / "alias").symlink_to("../lib/real")
    (repo / "skills" / "loop").symlink_to(".")
    (repo / "skills" / "group").symlink_to("../lib")

    found = scan_source("s", repo, {"type": "collection", "roots": ["skills"]})
    assert sorted(s.skill_id for s in found) == ["s:alias", "s:foo"]
