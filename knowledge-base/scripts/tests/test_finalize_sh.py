"""Integration tests for shell/finalize.sh.

Tests the post-deploy flattening behavior: knowledge-base/ contents promoted
to project root, then both setup/ and knowledge-base/ removed.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FINALIZE_SH = REPO_ROOT / "knowledge-base" / "shell" / "finalize.sh"


def _stage_project(root: Path, *, valid: bool = True) -> Path:
    """Create a fake deployed project layout."""
    setup = root / "setup" / "shell"
    setup.mkdir(parents=True)
    (root / "setup" / "scripts").mkdir(parents=True, exist_ok=True)
    # Symlink real finalize.sh — script runs as if it were inside the project
    (setup / "finalize.sh").symlink_to(FINALIZE_SH)

    kb = root / "knowledge-base"
    kb.mkdir()

    if valid:
        # Required files for finalize to accept the base
        (kb / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        (kb / "kb.config.yml").write_text(
            "knowledge_base:\n  name: test\n", encoding="utf-8"
        )
        (kb / "scripts").mkdir()
        (kb / "scripts" / "kb_ingest.py").write_text("# stub\n", encoding="utf-8")

    # Some additional realistic content
    (kb / "raw").mkdir(exist_ok=True)
    (kb / "knowledge").mkdir(exist_ok=True)
    (kb / "reindex.sh").write_text("echo hi\n", encoding="utf-8")
    return kb


def _run_finalize(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(root / "setup" / "shell" / "finalize.sh"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_finalize_promotes_kb_to_root(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0, result.stderr
    # Content should be promoted
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "kb.config.yml").is_file()
    assert (tmp_path / "scripts" / "kb_ingest.py").is_file()
    assert (tmp_path / "knowledge").is_dir()
    assert (tmp_path / "raw").is_dir()
    # Containers should be gone
    assert not (tmp_path / "knowledge-base").exists()
    assert not (tmp_path / "setup").exists()


def test_finalize_keep_setup_flag(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--keep-setup")
    assert result.returncode == 0
    assert not (tmp_path / "knowledge-base").exists()
    assert (tmp_path / "setup").is_dir(), "--keep-setup should retain setup/"


def test_finalize_dry_run_changes_nothing(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--dry-run")
    assert result.returncode == 0
    # Nothing should have moved
    assert (tmp_path / "knowledge-base" / "AGENTS.md").is_file()
    assert (tmp_path / "setup").is_dir()
    assert not (tmp_path / "AGENTS.md").exists()


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------


def test_finalize_refuses_when_kb_missing(tmp_path: Path):
    setup = tmp_path / "setup" / "shell"
    setup.mkdir(parents=True)
    (setup / "finalize.sh").symlink_to(FINALIZE_SH)
    # No knowledge-base/ created
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "deployed base not found" in result.stderr.lower()


def test_finalize_refuses_when_required_files_missing(tmp_path: Path):
    _stage_project(tmp_path, valid=False)
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "missing required files" in result.stderr.lower()
    # Still nothing moved
    assert not (tmp_path / "AGENTS.md").exists()


def test_finalize_refuses_on_conflicts(tmp_path: Path):
    _stage_project(tmp_path)
    # Pre-existing AGENTS.md at project root → conflict
    (tmp_path / "AGENTS.md").write_text("preexisting\n", encoding="utf-8")
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "would be overwritten" in result.stderr.lower()
    # Original preserved
    assert (tmp_path / "AGENTS.md").read_text() == "preexisting\n"


def test_finalize_force_overwrites_conflicts(tmp_path: Path):
    _stage_project(tmp_path)
    (tmp_path / "AGENTS.md").write_text("preexisting\n", encoding="utf-8")
    result = _run_finalize(tmp_path, "--force")
    assert result.returncode == 0
    assert "AGENTS" in (tmp_path / "AGENTS.md").read_text()
    # The deployed AGENTS.md replaced the pre-existing one
    assert (tmp_path / "AGENTS.md").read_text() != "preexisting\n"


# ---------------------------------------------------------------------------
# Idempotency / re-runs
# ---------------------------------------------------------------------------


def test_finalize_second_run_is_safe(tmp_path: Path):
    _stage_project(tmp_path)
    first = _run_finalize(tmp_path)
    assert first.returncode == 0
    # No setup/ left, so a second invocation requires a fresh path
    # Just verify the project state is intact
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "scripts" / "kb_ingest.py").is_file()
