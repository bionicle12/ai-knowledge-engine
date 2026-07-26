"""Tests for the cross-platform reindex orchestration."""
from __future__ import annotations

from pathlib import Path

import kb_reindex


def test_reindex_refreshes_routes_between_ingest_and_lint(
    tmp_path: Path, monkeypatch
):
    calls: list[tuple[str, tuple[str, ...]]] = []

    def record(script: str, *args: str, root: Path) -> int:
        calls.append((script, args))
        return 0

    monkeypatch.setattr(kb_reindex, "_py", record)

    assert (
        kb_reindex.reindex(
            tmp_path,
            quick=True,
            do_index=False,
            do_ingest=True,
        )
        == 0
    )
    assert calls == [
        ("kb_ingest.py", ()),
        ("kb_route.py", ()),
        ("kb_lint.py", ("--quick",)),
    ]
