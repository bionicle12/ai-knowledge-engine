"""L1 mutation testing — seven known defects must wake lint."""
from __future__ import annotations

from pathlib import Path

import kb_lint
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


def test_mutation_is_killed_only_on_its_own_page(tmp_path: Path, monkeypatch):
    """Q19: a broken orphan check that still reports an unrelated orphan
    elsewhere in the base must not count the orphan mutation as killed."""
    root = tmp_path / "kb"
    stray = root / "knowledge" / "domain" / "stray.md"
    stray.parent.mkdir(parents=True)
    stray.write_text(
        "---\nsource: raw/x.md\nextracted_at: 2026-01-01\ntags: []\n"
        "lifecycle: evolving\n---\nnobody links here\n",
        encoding="utf-8",
    )
    real = kb_lint._orphan_paths

    def broken(*args):
        return {p for p in real(*args) if p.name != "mutate-gamma.md"}

    monkeypatch.setattr(kb_lint, "_orphan_paths", broken)
    report = kb_mutate.run_mutations(root, work=tmp_path / "work", keep=True)
    assert report.survivors == ["orphan"], report.line
