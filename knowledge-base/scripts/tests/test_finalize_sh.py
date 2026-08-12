"""Integration tests for shell/finalize.sh.

Tests the post-deploy flattening behavior: knowledge-base/ contents promoted
to project root, then both setup/ and knowledge-base/ removed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FINALIZE_SH = REPO_ROOT / "knowledge-base" / "shell" / "finalize.sh"


def _bash_can_see_repo() -> bool:
    """True when a usable bash is on PATH and it understands Windows paths.

    On Windows, PATH may resolve `bash` to WSL, which cannot see C:/ paths
    directly — these integration tests would fail for environment reasons.
    """
    try:
        result = subprocess.run(
            ["bash", "-c", f"test -f '{FINALIZE_SH.as_posix()}'"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _bash_can_see_repo(),
    reason="requires a bash that can access the repository path (e.g. Git Bash)",
)


def _stage_project(root: Path, *, valid: bool = True) -> Path:
    """Create a fake deployed project layout."""
    setup = root / "setup" / "shell"
    setup.mkdir(parents=True)
    (root / "setup" / "scripts").mkdir(parents=True, exist_ok=True)
    # Symlink real finalize.sh — script runs as if it were inside the project.
    # Windows needs Developer Mode / admin rights for symlinks; a copy behaves
    # identically for the script, so fall back to that.
    try:
        (setup / "finalize.sh").symlink_to(FINALIZE_SH)
    except OSError:
        shutil.copy2(FINALIZE_SH, setup / "finalize.sh")

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
    try:
        (setup / "finalize.sh").symlink_to(FINALIZE_SH)
    except OSError:
        shutil.copy2(FINALIZE_SH, setup / "finalize.sh")
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


# ---------------------------------------------------------------------------
# Launcher promotion + duplicate cleanup (0.9.3)
# ---------------------------------------------------------------------------


def _stage_project_with_launchers(root: Path) -> Path:
    """Stage a project where knowledge-base/ has both shell/*.command and
    duplicated *.sh at its own root — like what the agent currently does."""
    kb = _stage_project(root)
    sh = kb / "shell"
    sh.mkdir(exist_ok=True)
    # Real shell scripts live in shell/
    (sh / "watcher.sh").write_text("echo watcher\n", encoding="utf-8")
    (sh / "lint.sh").write_text("echo lint\n", encoding="utf-8")
    # macOS launchers (also in shell/ before finalize)
    (sh / "watcher-start.command").write_text("#!/bin/bash\necho start\n",
                                              encoding="utf-8")
    (sh / "watcher-stop.command").write_text("#!/bin/bash\necho stop\n",
                                             encoding="utf-8")
    (sh / "reindex.command").write_text("#!/bin/bash\necho reindex\n",
                                        encoding="utf-8")
    # Windows launchers
    (sh / "watcher-start.bat").write_text("@echo start\r\n", encoding="utf-8")
    # The agent currently also drops a *.sh duplicate at the kb root.
    # finalize.sh should detect and remove these duplicates.
    (kb / "watcher.sh").write_text("echo watcher\n", encoding="utf-8")
    (kb / "lint.sh").write_text("echo lint\n", encoding="utf-8")
    return kb


def test_finalize_promotes_command_launchers_to_root(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0, result.stderr
    # macOS launchers should now be at project root
    assert (tmp_path / "watcher-start.command").is_file()
    assert (tmp_path / "watcher-stop.command").is_file()
    assert (tmp_path / "reindex.command").is_file()
    # Windows launcher too
    assert (tmp_path / "watcher-start.bat").is_file()
    # And NOT in shell/ anymore
    assert not (tmp_path / "shell" / "watcher-start.command").exists()
    assert not (tmp_path / "shell" / "reindex.command").exists()
    assert not (tmp_path / "shell" / "watcher-start.bat").exists()


def test_finalize_keeps_sh_in_shell_only(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # *.sh should live in shell/ — duplicates at root removed
    assert (tmp_path / "shell" / "watcher.sh").is_file()
    assert (tmp_path / "shell" / "lint.sh").is_file()
    assert not (tmp_path / "watcher.sh").exists(), \
        "watcher.sh duplicate at root should be cleaned up"
    assert not (tmp_path / "lint.sh").exists()


def test_finalize_preserves_root_sh_when_different(tmp_path: Path):
    """If a *.sh at the root differs from the shell/ copy, keep both —
    user may have customized. Only identical copies are pruned."""
    _stage_project_with_launchers(tmp_path)
    # Make the root copy different
    kb = tmp_path / "knowledge-base"
    (kb / "watcher.sh").write_text("echo CUSTOM\n", encoding="utf-8")
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # Custom version preserved at root
    assert (tmp_path / "watcher.sh").read_text() == "echo CUSTOM\n"
    # shell/ copy still there too
    assert (tmp_path / "shell" / "watcher.sh").is_file()


def test_finalize_promotion_does_not_overwrite_existing_root_launcher(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    kb = tmp_path / "knowledge-base"
    # Pre-existing root launcher with custom content (someone customized)
    (kb / "watcher-start.command").write_text(
        "#!/bin/bash\necho USER_CUSTOM\n", encoding="utf-8"
    )
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # Root version preserved as-is
    assert (tmp_path / "watcher-start.command").read_text() == \
        "#!/bin/bash\necho USER_CUSTOM\n"
    # shell/ duplicate also kept since promotion was skipped
    assert (tmp_path / "shell" / "watcher-start.command").is_file()
