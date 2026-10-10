"""Tests for shell/_kbpy.sh — interpreter and base-root resolution for wrappers.

D8: the venv lives at the project root. Before finalize.sh the base sits in
<project>/knowledge-base/ and wrappers must use <project>/.venv; after it the
base is the project root. Resolution must not depend on $0 being absolute.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
KBPY = REPO_ROOT / "knowledge-base" / "shell" / "_kbpy.sh"

WRAPPER = """#!/usr/bin/env bash
set -eu
KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2
case "${1:-}" in
  root) kb_root ;;
  python) kb_python ;;
  require) kb_require "$2" ;;
  run) shift; kb_run "$@" ;;
esac
"""

FAKE_PYTHON = """#!/bin/sh
echo "fake:$(pwd -P):$*"
exit 3
"""


def _bash_works() -> bool:
    try:
        return subprocess.run(
            ["bash", "-c", f"test -f '{KBPY.as_posix()}'"], capture_output=True, timeout=15
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    os.name == "nt" or not _bash_works(),
    reason="needs a POSIX bash that can see the repository",
)


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _base(root: Path) -> Path:
    """A base at `root`: shell/ with the helper + test wrapper, scripts/."""
    shutil.copy(KBPY, _executable(root / "shell" / "w.sh", WRAPPER).parent / "_kbpy.sh")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "kb_x.py").write_text("print('x')\n", encoding="utf-8")
    return root


def _run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if k not in ("KB_PYTHON", "CDPATH")}
    full_env.update(env or {})
    return subprocess.run(
        ["bash", *args], cwd=cwd, capture_output=True, text=True, timeout=30, env=full_env
    )


def test_kb_root_is_absolute_with_a_relative_script_path_and_cdpath(tmp_path: Path):
    base = _base(tmp_path / "proj")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "shell").mkdir()  # a decoy CDPATH could jump to
    result = _run(tmp_path, "proj/shell/w.sh", "root", env={"CDPATH": str(elsewhere)})
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{base.resolve()}\n"


def test_finalized_base_uses_its_own_venv(tmp_path: Path):
    base = _base(tmp_path / "proj")
    python = _executable(base / ".venv" / "bin" / "python", FAKE_PYTHON)
    result = _run(tmp_path, "proj/shell/w.sh", "python")
    assert result.stdout.strip() == str(python.resolve())


def _setup(project: Path) -> None:
    """The engine copy next to the base before finalize.sh (02_INIT)."""
    (project / "setup" / "scripts").mkdir(parents=True)
    (project / "setup" / "scripts" / "kb_common.py").write_text("", encoding="utf-8")


def test_deploy_layout_uses_the_project_root_venv(tmp_path: Path):
    project = tmp_path / "my project"
    _base(project / "knowledge-base")
    _setup(project)
    python = _executable(project / ".venv" / "bin" / "python", FAKE_PYTHON)
    result = _run(project, "knowledge-base/shell/w.sh", "python")
    assert result.stdout.strip() == str(python.resolve())


def test_deploy_layout_with_custom_folder_next_to_setup(tmp_path: Path):
    project = tmp_path / "proj"
    _base(project / "kb")
    _setup(project)
    python = _executable(project / ".venv" / "bin" / "python", FAKE_PYTHON)
    assert _run(project, "kb/shell/w.sh", "python").stdout.strip() == str(python.resolve())


def test_finalized_base_named_knowledge_base_ignores_the_venv_above_it(tmp_path: Path):
    # Review repro: ~/knowledge-base (finalized, no .venv of its own) must not
    # run with an unrelated ~/.venv just because of its folder name.
    _base(tmp_path / "knowledge-base")
    foreign = _executable(tmp_path / ".venv" / "bin" / "python", FAKE_PYTHON)
    (tmp_path / "setup").mkdir()  # an unrelated folder called setup/ proves nothing either
    result = _run(tmp_path, "knowledge-base/shell/w.sh", "python")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != str(foreign.resolve())
    assert result.stdout.strip() == shutil.which("python3")


def test_finalized_base_never_uses_a_venv_above_it(tmp_path: Path):
    _base(tmp_path / "proj")
    foreign = _executable(tmp_path / ".venv" / "bin" / "python", FAKE_PYTHON)
    result = _run(tmp_path, "proj/shell/w.sh", "python")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != str(foreign.resolve())
    assert result.stdout.strip() == shutil.which("python3")


def test_kb_python_env_override_wins(tmp_path: Path):
    base = _base(tmp_path / "proj")
    _executable(base / ".venv" / "bin" / "python", FAKE_PYTHON)
    custom = _executable(tmp_path / "custom" / "py", FAKE_PYTHON)
    assert _run(tmp_path, "proj/shell/w.sh", "python", env={"KB_PYTHON": str(custom)}).stdout.strip() == str(custom)
    relative = _run(tmp_path, "proj/shell/w.sh", "python", env={"KB_PYTHON": "custom/py"})
    assert relative.stdout.strip() == f"{tmp_path.resolve()}/custom/py"
    missing = _run(tmp_path, "proj/shell/w.sh", "python", env={"KB_PYTHON": str(tmp_path / "nope")})
    assert missing.returncode == 2
    assert "KB_PYTHON" in missing.stderr


def test_kb_require_reports_missing_scripts(tmp_path: Path):
    _base(tmp_path / "proj")
    assert _run(tmp_path, "proj/shell/w.sh", "require", "scripts/kb_x.py").returncode == 0
    result = _run(tmp_path, "proj/shell/w.sh", "require", "scripts/kb_missing.py")
    assert result.returncode == 2
    assert "scripts/kb_missing.py not found" in result.stderr
    assert f"{(tmp_path / 'proj').resolve()}/scripts/" in result.stderr


def test_kb_run_runs_from_the_base_root_and_passes_the_exit_code(tmp_path: Path):
    base = _base(tmp_path / "proj")
    _executable(base / ".venv" / "bin" / "python", FAKE_PYTHON)
    result = _run(tmp_path, "proj/shell/w.sh", "run", "scripts/kb_x.py", "--flag", "two words")
    assert result.returncode == 3
    assert result.stdout.strip() == f"fake:{base.resolve()}:scripts/kb_x.py --flag two words"
    assert _run(tmp_path, "proj/shell/w.sh", "run", "scripts/kb_gone.py").returncode == 2


def test_helper_derives_its_folder_from_bash_source(tmp_path: Path):
    base = _base(tmp_path / "proj")
    result = subprocess.run(
        ["bash", "-c", '. proj/shell/_kbpy.sh && printf "%s|%s" "$KB_SHELL_DIR" "$(kb_root)"'],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.stdout == f"{(base / 'shell').resolve()}|{base.resolve()}"


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")
def test_helper_is_posix_sh(tmp_path: Path):
    base = _base(tmp_path / "proj")
    python = _executable(base / ".venv" / "bin" / "python", FAKE_PYTHON)
    ok = subprocess.run(
        ["sh", "-c", 'KB_SHELL_DIR="$PWD/proj/shell"; . "$KB_SHELL_DIR/_kbpy.sh" && kb_root && kb_python'],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert ok.stdout.splitlines() == [str(base.resolve()), str(python.resolve())], ok.stderr
    bare = subprocess.run(
        ["sh", "-c", '. "$PWD/proj/shell/_kbpy.sh"; echo "status=$?"'],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    if os.path.basename(os.path.realpath(shutil.which("sh"))) == "dash":
        # No BASH_SOURCE in dash: the helper refuses with a clear message.
        assert "status=2" in bare.stdout
        assert "KB_SHELL_DIR" in bare.stderr
