"""L1 mutation testing — seven known defects must wake lint."""
from __future__ import annotations

from pathlib import Path

import kb_mutate


def test_seven_l1_mutations_are_killed(tmp_path: Path):
    root = tmp_path / "kb"
    root.mkdir()
    work = tmp_path / "work"
    report = kb_mutate.run_mutations(root, work=work, keep=True)
    assert report.total == 7
    assert report.survivors == [], report.line
    assert set(report.killed) == {m.id for m in kb_mutate.MUTATIONS}


def test_mutate_cli_exit_zero_when_all_killed(tmp_path: Path):
    root = tmp_path / "kb"
    root.mkdir()
    code = kb_mutate.main(["--root", str(root), "--work", str(tmp_path / "w")])
    assert code == 0
