"""Cross-platform tests for managed directory links."""
from __future__ import annotations

import os

import pytest

from ai_skills_fixer.filesystem import (
    managed_link_type,
    materialize_directory,
    remove_managed_link,
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
