"""Cross-platform tests for managed directory links."""
from __future__ import annotations

import os
import shutil

import pytest

from ai_skills_fixer.filesystem import (
    managed_link_type,
    materialize_directory,
    remove_managed_link,
    remove_tree,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_accepts_cmd_metacharacters_without_touching_target(tmp_path):
    source = tmp_path / "source & 100%"
    source.mkdir()
    (source / "proof.txt").write_text("kept\n", encoding="utf-8")
    dest = tmp_path / "linked & 100%"

    materialize_directory(source, dest, "junction")

    assert managed_link_type(dest) == "junction"
    assert (dest / "proof.txt").read_text(encoding="utf-8") == "kept\n"
    remove_managed_link(dest)
    assert not dest.exists()
    assert (source / "proof.txt").is_file()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX folder permissions; root ignores them",
)
def test_copy_of_a_read_only_release_stays_movable(tmp_path):
    """B4: releases have read-only folders; a `copy` install made from one
    must still be quarantined (moved) and rolled back (removed)."""
    release = tmp_path / "release"
    (release / "references").mkdir(parents=True)
    (release / "SKILL.md").write_text("s\n", encoding="utf-8")
    (release / "references" / "n.md").write_text("n\n", encoding="utf-8")
    for path in (release / "references" / "n.md", release / "SKILL.md",
                 release / "references", release):
        path.chmod(0o555 if path.is_dir() else 0o444)

    dest = tmp_path / "host" / "skills" / "foo"
    materialize_directory(release, dest, "copy")
    backup = tmp_path / "backups" / "foo"
    backup.parent.mkdir()
    shutil.move(str(dest), str(backup))  # quarantine
    remove_tree(backup)  # rollback of a copy install
    assert not backup.exists()

    remove_tree(release)  # read-only folders are removable on purpose
    assert not release.exists()
