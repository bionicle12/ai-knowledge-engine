"""Integration tests for shell/ wrappers: project-root resolution.

Regression test for the bug where shell/watcher.sh did `cd $(dirname $0)`
and ended up inside shell/, then failed to find scripts/kb_watch.py
which lives at <project-root>/scripts/.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SHELL_DIR = REPO_ROOT / "knowledge-base" / "shell"


def _setup_project(root: Path, *, with_scripts: bool = True) -> None:
    """Stage a deployed project layout at `root`."""
    (root / "shell").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    # Copy real shell wrappers and launchers
    for fname in ("watcher.sh", "reindex.sh", "lint.sh", "doctor.sh",
                  "export.sh", "import.sh",
                  "watcher-start.command", "reindex.command",
                  "export.command", "import.command"):
        src = SHELL_DIR / fname
        dst = root / "shell" / fname
        shutil.copy2(src, dst)
        dst.chmod(0o755)

    if with_scripts:
        # Stub scripts that just print and exit cleanly
        for name, body in [
            ("kb_watch.py", "print('watcher ok'); raise SystemExit(0)"),
            ("kb_ingest.py", "print('ingest ok'); raise SystemExit(0)"),
            ("kb_lint.py", "import sys; print('lint ok'); sys.exit(0)"),
            ("kb_doctor.py", "print('doctor ok'); raise SystemExit(0)"),
            ("kb_export.py", "print('export ok'); raise SystemExit(0)"),
            # Exit 1 = "merged, conflicts pending" — a normal outcome the
            # wrapper must pass through rather than treat as a failure.
            ("kb_import.py", "print('import ok'); raise SystemExit(1)"),
        ]:
            p = root / "scripts" / name
            p.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Wrapper scripts called from project root
# ---------------------------------------------------------------------------


def test_watcher_sh_resolves_project_root_from_shell_dir(tmp_path: Path):
    _setup_project(tmp_path)
    # Invoke watcher.sh with --status (doesn't actually start the daemon)
    result = subprocess.run(
        ["bash", "shell/watcher.sh", "--status"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Should succeed (exit 0) and not complain about missing kb_watch.py
    assert "kb_watch.py not found" not in result.stdout + result.stderr
    assert "kb_watch.py not found" not in result.stderr
    assert result.returncode == 0


def test_watcher_sh_called_from_outside_project_still_works(tmp_path: Path):
    _setup_project(tmp_path)
    # Run from /tmp, not from the project — sh script must still resolve correctly
    result = subprocess.run(
        ["bash", str(tmp_path / "shell" / "watcher.sh"), "--status"],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "kb_watch.py not found" not in result.stderr


def test_watcher_sh_reports_project_root_when_kb_watch_missing(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    result = subprocess.run(
        ["bash", "shell/watcher.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    # Error should be helpful — point at the actual searched location
    assert "kb_watch.py not found" in result.stdout
    assert str(tmp_path / "scripts") in result.stdout


def test_lint_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", "shell/lint.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "lint ok" in result.stdout


def test_doctor_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", "shell/doctor.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "doctor ok" in result.stdout


def test_export_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", "shell/export.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "export ok" in result.stdout


def test_import_sh_passes_through_conflict_exit_code(tmp_path: Path):
    """Exit 1 means "conflicts queued", not a wrapper failure."""
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", "shell/import.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "import ok" in result.stdout


def test_import_sh_reports_missing_script(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    result = subprocess.run(
        ["bash", "shell/import.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "kb_import.py not found" in result.stdout


# ---------------------------------------------------------------------------
# .command launchers (the macOS double-click case)
# ---------------------------------------------------------------------------


def test_watcher_start_command_from_shell_dir(tmp_path: Path):
    """Simulates macOS double-clicking watcher-start.command located at shell/watcher-start.command."""
    _setup_project(tmp_path)
    launcher = tmp_path / "shell" / "watcher-start.command"

    # The .command launcher uses `read -p` after errors. We pass /dev/null as
    # stdin so it won't hang. On success the watcher stub exits immediately.
    result = subprocess.run(
        ["bash", str(launcher)],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"Launcher failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "watcher ok" in result.stdout
    assert str(tmp_path) in result.stdout
    assert "kb_watch.py not found" not in result.stdout


def test_watcher_start_command_at_project_root(tmp_path: Path):
    """Launcher copied to project root (alternative deployment style)."""
    _setup_project(tmp_path)
    # Move the launcher to root
    src = tmp_path / "shell" / "watcher-start.command"
    dst = tmp_path / "watcher-start.command"
    shutil.copy2(src, dst)
    dst.chmod(0o755)

    result = subprocess.run(
        ["bash", str(dst)],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0
    assert "watcher ok" in result.stdout


def test_watcher_start_command_reports_when_no_scripts(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    launcher = tmp_path / "shell" / "watcher-start.command"
    # The launcher does `read -p "..."` on failure, so feed it /dev/null
    result = subprocess.run(
        ["bash", str(launcher)],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode != 0
    assert "Cannot find scripts/kb_watch.py" in result.stdout


def test_export_command_launcher(tmp_path: Path):
    """macOS double-click path for export."""
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", str(tmp_path / "shell" / "export.command")],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"Launcher failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "export ok" in result.stdout
    assert str(tmp_path) in result.stdout


def test_import_command_launcher_explains_pending_conflicts(tmp_path: Path):
    """Exit 1 from kb_import means conflicts are queued — say so, don't look broken."""
    _setup_project(tmp_path)
    result = subprocess.run(
        ["bash", str(tmp_path / "shell" / "import.command")],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert "import ok" in result.stdout
    assert "!merge" in result.stdout


def test_import_command_launcher_at_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    dst = tmp_path / "import.command"
    shutil.copy2(tmp_path / "shell" / "import.command", dst)
    dst.chmod(0o755)

    result = subprocess.run(
        ["bash", str(dst)],
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
    )
    assert "import ok" in result.stdout
