"""Integration tests for shell/ wrappers, launchers and the git hook.

Regression test for the bug where shell/watcher.sh did `cd $(dirname $0)`
and ended up inside shell/, then failed to find scripts/kb_watch.py
which lives at <project-root>/scripts/.

Wrappers source shell/_kbpy.sh (0.16.0), which prints its errors on stderr and
picks the interpreter itself; the tests pass KB_PYTHON=sys.executable.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SHELL_DIR = REPO_ROOT / "knowledge-base" / "shell"
TEMPLATES = REPO_ROOT / "knowledge-base" / "templates"


def _bash_can_see_repo() -> bool:
    """True when a usable bash is on PATH and it understands Windows paths.

    On Windows, PATH may resolve `bash` to WSL, which cannot see C:/ paths
    directly — these integration tests would fail for environment reasons.
    """
    try:
        result = subprocess.run(
            ["bash", "-c", f"test -d '{SHELL_DIR.as_posix()}'"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


needs_bash = pytest.mark.skipif(
    not _bash_can_see_repo(),
    reason="requires a bash that can access the repository path (e.g. Git Bash)",
)
needs_posix_git = pytest.mark.skipif(
    os.name == "nt" or shutil.which("git") is None or not _bash_can_see_repo(),
    reason="needs git and a POSIX bash",
)

SHELL_FILES = (
    "_kbpy.sh", "watcher.sh", "reindex.sh", "lint.sh", "doctor.sh",
    "export.sh", "import.sh", "install-hooks.sh",
    "watcher-start.command", "watcher-stop.command", "reindex.command",
    "export.command", "import.command",
)

CALLS = "hook-calls.txt"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("GIT_")]:
        env.pop(key)
    env.update(
        HOME=str(tmp_path / "home"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.com",
        KB_PYTHON=sys.executable,
    )
    env.update(extra)
    return env


def _setup_project(root: Path, *, with_scripts: bool = True) -> None:
    """Stage a deployed project layout at `root`."""
    (root / "shell" / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    # Copy real shell wrappers and launchers
    for fname in (*SHELL_FILES, "hooks/post-commit"):
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
            (
                "kb_reindex.py",
                "import os, sys\n"
                f"with open({CALLS!r}, 'a', encoding='utf-8') as fh:\n"
                "    fh.write(os.getcwd() + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
                "print('reindex ok')",
            ),
        ]:
            p = root / "scripts" / name
            p.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")


def _run(cmd: list[str], tmp_path: Path, *, cwd: Path | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd or tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
        stdin=subprocess.DEVNULL,
        env=env or _env(tmp_path),
    )


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ---------------------------------------------------------------------------
# Wrapper scripts called from project root
# ---------------------------------------------------------------------------


@needs_bash
def test_watcher_sh_resolves_project_root_from_shell_dir(tmp_path: Path):
    _setup_project(tmp_path)
    # Invoke watcher.sh with --status (doesn't actually start the daemon)
    result = _run(["bash", "shell/watcher.sh", "--status"], tmp_path)
    # Should succeed (exit 0) and not complain about missing kb_watch.py
    assert "kb_watch.py not found" not in result.stdout + result.stderr
    assert result.returncode == 0


@needs_bash
def test_watcher_sh_called_from_outside_project_still_works(tmp_path: Path):
    _setup_project(tmp_path)
    # Run from outside the project — sh script must still resolve correctly
    # (tmp_path.parent instead of /tmp: the latter is not a valid cwd on Windows)
    result = _run(["bash", str(tmp_path / "shell" / "watcher.sh"), "--status"],
                  tmp_path, cwd=tmp_path.parent)
    assert result.returncode == 0
    assert "kb_watch.py not found" not in result.stdout + result.stderr


@needs_bash
def test_watcher_sh_reports_project_root_when_kb_watch_missing(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    result = _run(["bash", "shell/watcher.sh"], tmp_path)
    assert result.returncode == 2
    # Error should be helpful — point at the actual searched location.
    # Git Bash prints POSIX-style paths on Windows, so compare a normalized tail.
    output = (result.stdout + result.stderr).replace("\\", "/")
    assert "kb_watch.py not found" in output
    assert f"{tmp_path.name}/scripts" in output


@needs_bash
def test_lint_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = _run(["bash", "shell/lint.sh"], tmp_path)
    assert result.returncode == 0
    assert "lint ok" in result.stdout


@needs_bash
def test_doctor_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = _run(["bash", "shell/doctor.sh"], tmp_path)
    assert result.returncode == 0
    assert "doctor ok" in result.stdout


@needs_bash
def test_export_sh_resolves_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    result = _run(["bash", "shell/export.sh"], tmp_path)
    assert result.returncode == 0
    assert "export ok" in result.stdout


@needs_bash
def test_import_sh_passes_through_conflict_exit_code(tmp_path: Path):
    """Exit 1 means "conflicts queued", not a wrapper failure."""
    _setup_project(tmp_path)
    result = _run(["bash", "shell/import.sh"], tmp_path)
    assert result.returncode == 1
    assert "import ok" in result.stdout


@needs_bash
def test_import_sh_reports_missing_script(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    result = _run(["bash", "shell/import.sh"], tmp_path)
    assert result.returncode == 2
    assert "kb_import.py not found" in result.stdout + result.stderr


@needs_bash
@pytest.mark.skipif(os.name == "nt", reason="fake interpreter is a POSIX script")
@pytest.mark.parametrize("wrapper", ["export.sh", "import.sh"])
def test_export_import_wrappers_take_python_from_kbpy(tmp_path: Path, wrapper: str):
    """The wrappers source shell/_kbpy.sh: $KB_PYTHON wins over PATH."""
    _setup_project(tmp_path)
    fake = _executable(tmp_path / "bin" / "fake-python", '#!/bin/sh\necho "fake python $*"\n')
    result = _run(["bash", f"shell/{wrapper}", "--flag"], tmp_path,
                  env=_env(tmp_path, KB_PYTHON=str(fake)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fake python scripts/kb_" in result.stdout
    assert result.stdout.rstrip().endswith("--flag")


@needs_bash
@pytest.mark.skipif(os.name == "nt", reason="fake venv interpreter is a POSIX script")
def test_export_sh_uses_project_venv_before_finalize(tmp_path: Path):
    """D8: during deployment the venv sits at the project root, next to setup/."""
    project = tmp_path / "project"
    base = project / "knowledge-base"
    _setup_project(base)
    (project / "setup" / "scripts").mkdir(parents=True)
    (project / "setup" / "scripts" / "kb_common.py").write_text("", encoding="utf-8")
    _executable(project / ".venv" / "bin" / "python", '#!/bin/sh\necho "project venv $1"\n')
    env = _env(tmp_path)
    env.pop("KB_PYTHON")

    result = _run(["bash", "knowledge-base/shell/export.sh"], tmp_path, cwd=project, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "project venv scripts/kb_export.py"


# ---------------------------------------------------------------------------
# .command launchers (the macOS double-click case)
# ---------------------------------------------------------------------------


@needs_bash
def test_watcher_start_command_from_shell_dir(tmp_path: Path):
    """Simulates macOS double-clicking watcher-start.command located at shell/watcher-start.command."""
    _setup_project(tmp_path)
    launcher = tmp_path / "shell" / "watcher-start.command"

    # The launcher reads stdin after errors; /dev/null keeps it from hanging.
    # On success the watcher stub exits immediately.
    result = _run(["bash", str(launcher)], tmp_path)
    assert result.returncode == 0, (
        f"Launcher failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "watcher ok" in result.stdout
    # tmp_path.name survives Git Bash's POSIX-style path rewriting on Windows
    assert tmp_path.name in result.stdout
    assert "kb_watch.py not found" not in result.stdout


@needs_bash
def test_watcher_start_command_at_project_root(tmp_path: Path):
    """Launcher copied to project root (alternative deployment style)."""
    _setup_project(tmp_path)
    # Move the launcher to root
    src = tmp_path / "shell" / "watcher-start.command"
    dst = tmp_path / "watcher-start.command"
    shutil.copy2(src, dst)
    dst.chmod(0o755)

    result = _run(["bash", str(dst)], tmp_path)
    assert result.returncode == 0
    assert "watcher ok" in result.stdout


@needs_bash
def test_watcher_start_command_reports_when_no_scripts(tmp_path: Path):
    _setup_project(tmp_path, with_scripts=False)
    launcher = tmp_path / "shell" / "watcher-start.command"
    result = _run(["bash", str(launcher)], tmp_path)
    assert result.returncode != 0
    assert "Cannot find scripts/kb_watch.py" in result.stdout


@needs_bash
def test_export_command_launcher(tmp_path: Path):
    """macOS double-click path for export."""
    _setup_project(tmp_path)
    result = _run(["bash", str(tmp_path / "shell" / "export.command")], tmp_path)
    assert result.returncode == 0, (
        f"Launcher failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "export ok" in result.stdout
    # tmp_path.name survives Git Bash's POSIX-style path rewriting on Windows
    assert tmp_path.name in result.stdout


@needs_bash
def test_export_command_reports_failure_and_keeps_exit_code(tmp_path: Path):
    _setup_project(tmp_path)
    (tmp_path / "scripts" / "kb_export.py").write_text(
        "print('export broke'); raise SystemExit(3)\n", encoding="utf-8"
    )
    result = _run(["bash", str(tmp_path / "shell" / "export.command")], tmp_path)
    assert result.returncode == 3
    assert "Export failed (exit 3)" in result.stdout
    assert "Copy the bundle" not in result.stdout


@needs_bash
def test_import_command_launcher_explains_pending_conflicts(tmp_path: Path):
    """Exit 1 from kb_import means conflicts are queued — say so, don't look broken."""
    _setup_project(tmp_path)
    result = _run(["bash", str(tmp_path / "shell" / "import.command")], tmp_path)
    assert "import ok" in result.stdout
    assert "!merge" in result.stdout
    assert result.returncode == 1


@needs_bash
def test_import_command_launcher_at_project_root(tmp_path: Path):
    _setup_project(tmp_path)
    dst = tmp_path / "import.command"
    shutil.copy2(tmp_path / "shell" / "import.command", dst)
    dst.chmod(0o755)

    result = _run(["bash", str(dst)], tmp_path)
    assert "import ok" in result.stdout


@needs_bash
def test_reindex_command_succeeds_without_a_terminal(tmp_path: Path):
    """No TERM and EOF on stdin (double-click edge cases) must not turn a good run into exit 1."""
    _setup_project(tmp_path)
    env = _env(tmp_path)
    env.pop("TERM", None)
    result = _run(["bash", str(tmp_path / "shell" / "reindex.command")], tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reindex ok" in result.stdout


@needs_bash
@pytest.mark.skipif(os.name == "nt", reason="fake venv interpreters are POSIX scripts")
@pytest.mark.parametrize("launcher", ["export.command", "import.command"])
def test_command_launchers_still_use_the_legacy_venv_of_older_bases(tmp_path: Path, launcher: str):
    """Review: the old launchers activated venv/ of older bases; without it they
    silently ran the system python3 (and lost NLP and other dependencies)."""
    _setup_project(tmp_path)
    _executable(tmp_path / "venv" / "bin" / "python", '#!/bin/sh\necho "legacy venv $*"\n')
    env = _env(tmp_path)
    env.pop("KB_PYTHON")
    script = f"scripts/kb_{launcher.split('.')[0]}.py"

    legacy = _run(["bash", str(tmp_path / "shell" / launcher), "--x"], tmp_path, env=env)
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert f"legacy venv {script} --x" in legacy.stdout

    # A .venv (the current layout) still comes first.
    _executable(tmp_path / ".venv" / "bin" / "python", '#!/bin/sh\necho "dot venv $*"\n')
    current = _run(["bash", str(tmp_path / "shell" / launcher)], tmp_path, env=env)
    assert f"dot venv {script}" in current.stdout
    assert "legacy venv" not in current.stdout


@pytest.mark.parametrize("launcher", sorted(n for n in SHELL_FILES if n.endswith(".command")))
def test_every_command_launcher_keeps_the_legacy_venv_fallback(launcher: str):
    text = (SHELL_DIR / launcher).read_text(encoding="utf-8")
    assert 'export KB_PYTHON="$PROJECT_ROOT/venv/bin/python"' in text
    assert "../setup/scripts/kb_common.py" in text  # same precedence as _kbpy.sh


@needs_bash
def test_watcher_stop_command_succeeds_without_a_terminal(tmp_path: Path):
    _setup_project(tmp_path)
    result = _run(["bash", str(tmp_path / "shell" / "watcher-stop.command")], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Stopping knowledge-base watcher" in result.stdout


# ---------------------------------------------------------------------------
# .bat launchers (static checks: cmd.exe is not available on CI hosts)
# ---------------------------------------------------------------------------

BAT_FILES = {
    "reindex.bat": "kb_reindex.py",
    "watcher-start.bat": "kb_watch.py",
    "export.bat": "kb_export.py",
    "import.bat": "kb_import.py",
}


def _same_block_expansions(text: str) -> list[tuple[int, str]]:
    """%VAR% expanded inside a (...) block after VAR was set (or the directory
    changed, for %CD%) earlier in that block.

    cmd.exe expands %VAR% once, when it parses the whole block, so such a
    reference sees the value from BEFORE the block ran.
    """
    bugs: list[tuple[int, str]] = []
    depth = 0
    assigned: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if re.match(r"(?i)rem\b", line) or line.startswith("::"):
            continue
        if line.startswith(")"):
            depth -= 1
        if depth > 0:
            bugs += [(lineno, n) for n in re.findall(r"%(\w+)%", line) if n.upper() in assigned]
            assigned |= {m.upper() for m in re.findall(r'(?i)\bset\s+"?(\w+)=', line)}
            if re.match(r"(?i)(pushd|popd|cd|chdir)\b", line):
                assigned.add("CD")
        if line.endswith("("):
            depth += 1
        if depth <= 0:
            depth = 0
            assigned = set()
    return bugs


def test_block_expansion_checker_catches_the_pushd_cd_bug():
    old = (
        'if exist "%SCRIPT_DIR%scripts\\x.py" (\n'
        '    set "PROJECT_ROOT=%SCRIPT_DIR%"\n'
        ') else if exist "%SCRIPT_DIR%..\\scripts\\x.py" (\n'
        '    pushd "%SCRIPT_DIR%.."\n'
        '    set "PROJECT_ROOT=%CD%\\"\n'
        "    popd\n"
        ")\n"
    )
    assert _same_block_expansions(old) == [(5, "CD")]


@pytest.mark.parametrize("name", sorted(BAT_FILES))
def test_bat_launchers_resolve_the_project_root_at_run_time(name: str):
    """Q-LOW: `%CD%` inside the if-block was expanded before `pushd` ran."""
    text = (SHELL_DIR / name).read_text(encoding="utf-8")
    assert _same_block_expansions(text) == []
    assert f"scripts\\{BAT_FILES[name]}" in text


@pytest.mark.parametrize("name", sorted(BAT_FILES))
def test_bat_launchers_pick_python_like_kbpy(name: str):
    """Same order as shell/_kbpy.sh, and the script's exit code survives `pause`."""
    text = (SHELL_DIR / name).read_text(encoding="utf-8")
    order = [
        text.index('set "PY=%KB_PYTHON%"'),
        text.index(".venv\\Scripts\\python.exe"),
        text.index("..\\setup\\scripts\\kb_common.py"),
        text.index('if exist "venv\\Scripts\\python.exe"'),  # the venv of older bases
        text.index("where py"),
        text.index('set "PY=python"'),
    ]
    assert order == sorted(order)
    assert "activate.bat" not in text
    assert f'"%PY%" %PYARGS% scripts\\{BAT_FILES[name]} %*' in text
    assert text.rstrip().endswith("endlocal & exit /b %CODE%")


# ---------------------------------------------------------------------------
# .gitattributes template
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_gitattributes_template_pins_script_line_endings(tmp_path: Path):
    repo = tmp_path / "base"
    repo.mkdir()
    env = _env(tmp_path)
    assert _run(["git", "init", "-q"], tmp_path, cwd=repo, env=env).returncode == 0
    shutil.copy(TEMPLATES / ".gitattributes.template", repo / ".gitattributes")
    paths = [
        "shell/lint.sh", "reindex.command", "shell/hooks/post-commit",
        "scripts/kb_lint.py", "reindex.bat", "shell/export.bat", "knowledge/x.md",
    ]
    result = _run(["git", "check-attr", "eol", "--", *paths], tmp_path, cwd=repo, env=env)
    eol = dict(line.split(": eol: ") for line in result.stdout.splitlines())
    assert eol == {
        "shell/lint.sh": "lf",
        "reindex.command": "lf",
        "shell/hooks/post-commit": "lf",
        "scripts/kb_lint.py": "lf",
        "reindex.bat": "crlf",
        "shell/export.bat": "crlf",
        "knowledge/x.md": "unspecified",
    }


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_engine_repo_pins_the_kit_script_line_endings(tmp_path: Path):
    """A Windows checkout of the kit keeps LF shell scripts and CRLF batch files."""
    repo = tmp_path / "engine"
    repo.mkdir()
    env = _env(tmp_path)
    assert _run(["git", "init", "-q"], tmp_path, cwd=repo, env=env).returncode == 0
    shutil.copy(REPO_ROOT / ".gitattributes", repo / ".gitattributes")
    kit = sorted(p.relative_to(REPO_ROOT).as_posix() for p in SHELL_DIR.rglob("*")
                 if p.is_file() and p.suffix in (".sh", ".command", ".bat", ""))
    assert "knowledge-base/shell/hooks/post-commit" in kit
    result = _run(["git", "check-attr", "eol", "--", *kit, "README.md"], tmp_path,
                  cwd=repo, env=env)
    eol = dict(line.split(": eol: ") for line in result.stdout.splitlines())
    for path in kit:
        assert eol[path] == ("crlf" if path.endswith(".bat") else "lf"), path
    assert eol["README.md"] == "unspecified"


# ---------------------------------------------------------------------------
# Full-mode git hook: shell/install-hooks.sh + shell/hooks/post-commit
# ---------------------------------------------------------------------------


def _git(repo: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", *args], tmp_path, cwd=repo)


def _git_base(tmp_path: Path, base: Path, *, repo: Path | None = None) -> Path:
    """A deployed base inside a git work tree (`repo`, default: the base itself)."""
    repo = repo or base
    repo.mkdir(parents=True, exist_ok=True)
    assert _git(repo, tmp_path, "init", "-q").returncode == 0
    _setup_project(base)
    (base / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    return repo


def _commit(repo: Path, tmp_path: Path, name: str = "note.md") -> None:
    (repo / name).write_text(f"{name} {time.time()}\n", encoding="utf-8")
    assert _git(repo, tmp_path, "add", name).returncode == 0
    result = _git(repo, tmp_path, "commit", "-qm", name)
    assert result.returncode == 0, result.stdout + result.stderr


def _wait_for(path: Path, text: str, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and text in (content := path.read_text(encoding="utf-8")):
            return content
        time.sleep(0.1)
    raise AssertionError(f"{path} never contained {text!r}")


def _install(base: Path, tmp_path: Path, shell: str = "bash") -> subprocess.CompletedProcess:
    return _run([shell, str(base / "shell" / "install-hooks.sh")], tmp_path, cwd=tmp_path)


@needs_posix_git
def test_install_hooks_installs_the_hook_and_commits_run_hook_mode(tmp_path: Path):
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)

    first = _install(base, tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    hook = repo / ".git" / "hooks" / "post-commit"
    assert hook.read_bytes() == (SHELL_DIR / "hooks" / "post-commit").read_bytes()
    assert os.access(hook, os.X_OK)
    again = _install(base, tmp_path)
    assert again.returncode == 0
    assert "already installed" in again.stdout

    _commit(repo, tmp_path)
    calls = _wait_for(base / CALLS, "--hook")
    assert calls.split()[:2] == [str(base.resolve()), "--hook"]
    assert "reindex ok" in _wait_for(base / ".kb-state" / "hooks.log", "reindex ok")
    assert (base / ".kb-state" / ".gitignore").read_text(encoding="utf-8") == "*\n"


@needs_posix_git
@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")
def test_install_hooks_runs_under_plain_sh(tmp_path: Path):
    """13_AUTORUN tells owners `sh shell/install-hooks.sh`; dash has no BASH_SOURCE."""
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)

    result = _install(base, tmp_path, shell="sh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".git" / "hooks" / "post-commit").is_file()


@needs_posix_git
def test_install_hooks_works_in_a_linked_worktree(tmp_path: Path):
    """A4: a hard-coded .git/hooks fails in worktrees, where .git is a file."""
    main = tmp_path / "main"
    _git_base(tmp_path, main)
    _commit(main, tmp_path, "seed.md")
    linked = tmp_path / "linked"
    assert _git(main, tmp_path, "worktree", "add", "-q", str(linked)).returncode == 0
    _setup_project(linked)
    (linked / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")

    result = _install(linked, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (main / ".git" / "hooks" / "post-commit").is_file()
    _commit(linked, tmp_path)
    _wait_for(linked / CALLS, "--hook")


@needs_posix_git
def test_install_hooks_honours_core_hooks_path_with_a_warning(tmp_path: Path):
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)
    assert _git(repo, tmp_path, "config", "core.hooksPath", ".husky").returncode == 0

    result = _install(base, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "core.hooksPath" in result.stdout
    assert (repo / ".husky" / "post-commit").is_file()
    assert not (repo / ".git" / "hooks" / "post-commit").exists()


@needs_posix_git
def test_install_hooks_backs_up_a_foreign_hook(tmp_path: Path):
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)
    foreign = _executable(repo / ".git" / "hooks" / "post-commit", "#!/bin/sh\necho mine\n")

    result = _install(base, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    backups = list(foreign.parent.glob("post-commit.backup-*"))
    assert [b.read_text(encoding="utf-8") for b in backups] == ["#!/bin/sh\necho mine\n"]
    assert "ai-knowledge-engine post-commit hook" in foreign.read_text(encoding="utf-8")
    assert "backup" in result.stdout


@needs_posix_git
def test_install_hooks_backs_up_an_edited_copy_of_its_own_hook(tmp_path: Path):
    """Review: a hook carrying our marker line was overwritten without a backup,
    silently dropping the commands the owner had added to it."""
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)
    assert _install(base, tmp_path).returncode == 0
    hook = repo / ".git" / "hooks" / "post-commit"
    edited = hook.read_text(encoding="utf-8").replace("exit 0\n", "echo owner-extra\nexit 0\n")
    hook.write_text(edited, encoding="utf-8")

    result = _install(base, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    backups = list(hook.parent.glob("post-commit.backup-*"))
    assert [b.read_text(encoding="utf-8") for b in backups] == [edited]
    assert hook.read_bytes() == (SHELL_DIR / "hooks" / "post-commit").read_bytes()
    assert "kept as" in result.stdout


@needs_posix_git
def test_hook_finds_a_base_in_a_subfolder_and_falls_back_to_the_top(tmp_path: Path):
    """Before finalize the base is <project>/knowledge-base; afterwards the project root."""
    project = tmp_path / "project"
    base = project / "knowledge-base"
    _git_base(tmp_path, base, repo=project)

    result = _install(base, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(project, tmp_path, "config", "kb.root").stdout.strip() == "knowledge-base"
    _commit(project, tmp_path)
    assert _wait_for(base / CALLS, "--hook").split()[0] == str(base.resolve())

    # finalize.sh flattened the base into the project root: kb.root is gone.
    _setup_project(project)
    (project / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    base.rename(tmp_path / "old-knowledge-base")
    _commit(project, tmp_path, "second.md")
    assert _wait_for(project / CALLS, "--hook").split()[0] == str(project.resolve())


@needs_posix_git
def test_hook_without_a_base_leaves_the_commit_alone(tmp_path: Path):
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)
    assert _install(base, tmp_path).returncode == 0
    (base / "kb.config.yml").unlink()

    _commit(repo, tmp_path)  # asserts exit 0

    time.sleep(0.5)
    assert not (base / CALLS).exists()
    assert not (base / ".kb-state").exists()


@needs_posix_git
def test_hook_log_moves_to_hooks_log_1_above_1_mb(tmp_path: Path):
    """13_AUTORUN: hooks.log keeps one previous log once it passes 1 MB."""
    base = tmp_path / "base"
    repo = _git_base(tmp_path, base)
    assert _install(base, tmp_path).returncode == 0
    log = base / ".kb-state" / "hooks.log"
    log.parent.mkdir()
    log.write_text("old\n" * 300_000, encoding="utf-8")  # 1.2 MB

    _commit(repo, tmp_path)

    assert "reindex ok" in _wait_for(log, "reindex ok")
    assert (base / ".kb-state" / "hooks.log.1").read_text(encoding="utf-8").startswith("old\n")
    assert log.stat().st_size < 1024 * 1024
    doc = (SHELL_DIR.parent / "13_AUTORUN.md").read_text(encoding="utf-8")
    for fact in ("bash shell/install-hooks.sh", "post-commit.backup-<timestamp>",
                 "git config kb.root", "hooks.log.1", "sh <base>/shell/hooks/post-commit"):
        assert fact in doc, fact
    assert "post-commit.local" not in doc


@needs_posix_git
def test_install_hooks_outside_a_git_work_tree_fails_clearly(tmp_path: Path):
    base = tmp_path / "base"
    _setup_project(base)
    result = _install(base, tmp_path)
    assert result.returncode == 1
    assert "git init" in result.stderr
