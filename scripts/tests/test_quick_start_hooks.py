"""Lite mode: quick-start hook templates and scripts/install-git-hooks.sh.

The update script is replaced by a stub that records how it was called, so
these tests exercise only the hooks and the installer (real git, real sh).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "quick-start" / "templates"
HOOK_NAMES = ("post-commit", "post-merge", "post-rewrite", "post-checkout", "pre-push")

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="POSIX shell scripts"),
    pytest.mark.skipif(not shutil.which("git") or not Path("/bin/sh").exists(), reason="needs git and /bin/sh"),
]

STUB = """#!/bin/sh
# records its arguments and whether stdin had data
printf '%s|%s\\n' "$*" "$(cat | tr -d '\\n')" >>"{calls}"
"""


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C.UTF-8",
    }


def _git(root: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout


def _project(tmp_path: Path, name: str = "proj") -> tuple[Path, dict[str, str], Path]:
    env = _env(tmp_path)
    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    shutil.copytree(TEMPLATES / "githooks", root / ".githooks")
    shutil.copy(TEMPLATES / "scripts" / "install-git-hooks.sh", root / "scripts")
    calls = tmp_path / "calls.txt"
    stub = root / "scripts" / "update-repomix-index.sh"
    stub.write_text(STUB.format(calls=calls), encoding="utf-8")
    stub.chmod(0o755)
    _git(root, env, "init", "-q")
    _git(root, env, "add", "-A")
    _git(root, env, "commit", "-q", "-m", "init")
    return root, env, calls


def _install(root: Path, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(root / "scripts" / "install-git-hooks.sh")], cwd=cwd or root,
                          env=env, capture_output=True, text=True, timeout=30)


def _hook(root: Path, env: dict[str, str], name: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(root / ".githooks" / name), *args], cwd=root, env=env,
                          input=stdin, capture_output=True, text=True, timeout=30)


def _calls(calls: Path) -> list[str]:
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


# ---------------------------------------------------------------------------
# A4: the installer targets the hooks folder git really uses
# ---------------------------------------------------------------------------
def test_installer_works_from_a_linked_worktree(tmp_path: Path) -> None:
    root, env, _ = _project(tmp_path)
    worktree = tmp_path / "wt"
    _git(root, env, "worktree", "add", "-q", str(worktree))

    result = _install(worktree, env)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in HOOK_NAMES:
        assert os.access(root / ".git" / "hooks" / name, os.X_OK), name


def test_installer_refuses_a_foreign_core_hookspath(tmp_path: Path) -> None:
    root, env, _ = _project(tmp_path)
    (root / ".husky").mkdir()
    (root / ".husky" / "pre-push").write_text("#!/bin/sh\nnpm test\n")
    _git(root, env, "config", "core.hooksPath", ".husky")

    result = _install(root, env)
    assert result.returncode == 1
    assert "core.hooksPath is set to '.husky'" in result.stdout
    assert "sh scripts/update-repomix-index.sh --no-wait </dev/null" in result.stdout
    assert (root / ".husky" / "pre-push").read_text() == "#!/bin/sh\nnpm test\n"
    assert not (root / ".git" / "hooks" / "post-commit").exists()


def test_installer_accepts_hookspath_pointing_at_githooks(tmp_path: Path) -> None:
    root, env, _ = _project(tmp_path)
    _git(root, env, "config", "core.hooksPath", ".githooks")
    result = _install(root, env)
    assert result.returncode == 0
    assert "git runs these hooks directly" in result.stdout


def test_installer_outside_git_fails_clearly(tmp_path: Path) -> None:
    root = tmp_path / "nogit"
    (root / "scripts").mkdir(parents=True)
    shutil.copytree(TEMPLATES / "githooks", root / ".githooks")
    shutil.copy(TEMPLATES / "scripts" / "install-git-hooks.sh", root / "scripts")
    env = {**_env(tmp_path), "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    result = _install(root, env)
    assert result.returncode == 1
    assert "Not a git repository" in result.stdout


# ---------------------------------------------------------------------------
# A9: a customised hook is backed up and diffed, local logic has a home
# ---------------------------------------------------------------------------
def test_installer_backs_up_and_diffs_a_changed_hook(tmp_path: Path) -> None:
    root, env, _ = _project(tmp_path)
    hooks = root / ".git" / "hooks"
    custom = "#!/bin/sh\n./scripts/run-ci-gate.sh || exit 1\nscripts/update-repomix-index.sh </dev/null\n"
    (hooks / "pre-push").write_text(custom)

    result = _install(root, env)
    assert result.returncode == 0
    backups = list(hooks.glob("pre-push.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == custom
    assert "-./scripts/run-ci-gate.sh || exit 1" in result.stdout
    assert ".githooks/pre-push.local" in result.stdout
    assert (hooks / "pre-push").read_text() == (TEMPLATES / "githooks" / "pre-push").read_text()

    again = _install(root, env)
    assert "Already up to date: post-commit pre-push post-merge post-rewrite post-checkout" in again.stdout
    assert len(list(hooks.glob("pre-push.bak-*"))) == 1


def test_pre_push_local_gate_runs_first_and_can_block(tmp_path: Path) -> None:
    root, env, calls = _project(tmp_path)
    gate = root / ".githooks" / "pre-push.local"
    gate.write_text(f'#!/bin/sh\nprintf "gate:%s|%s\\n" "$*" "$(cat)" >>"{calls}"\nexit 1\n')
    gate.chmod(0o755)

    blocked = _hook(root, env, "pre-push", "origin", "url", stdin="refs/heads/main abc")
    assert blocked.returncode == 1
    assert _calls(calls) == ["gate:origin url|refs/heads/main abc"]  # index update skipped

    gate.write_text(f'#!/bin/sh\ncat >/dev/null\necho gate-ok >>"{calls}"\n')
    passed = _hook(root, env, "pre-push", "origin", "url", stdin="refs/heads/main abc")
    assert passed.returncode == 0
    assert _calls(calls)[-2:] == ["gate-ok", "--no-wait|"]  # no refs leak into the script


@pytest.mark.parametrize("name", ["post-commit", "post-merge", "post-rewrite"])
def test_post_hooks_run_local_then_background_update(tmp_path: Path, name: str) -> None:
    root, env, calls = _project(tmp_path)
    local = root / ".githooks" / f"{name}.local"
    local.write_text(f'#!/bin/sh\necho local-{name} >>"{calls}"\n')
    local.chmod(0o755)
    result = _hook(root, env, name)
    assert result.returncode == 0
    assert _calls(calls) == [f"local-{name}", "--background|"]


# ---------------------------------------------------------------------------
# A12: branch switches refresh the index
# ---------------------------------------------------------------------------
def test_post_checkout_fires_on_branch_checkout_only(tmp_path: Path) -> None:
    root, env, calls = _project(tmp_path)
    assert _hook(root, env, "post-checkout", "a" * 40, "b" * 40, "0").returncode == 0
    assert _calls(calls) == []
    assert _hook(root, env, "post-checkout", "a" * 40, "b" * 40, "1").returncode == 0
    assert _calls(calls) == ["--background|"]


def test_installed_post_checkout_runs_on_git_switch(tmp_path: Path) -> None:
    root, env, calls = _project(tmp_path)
    assert _install(root, env).returncode == 0
    _git(root, env, "switch", "-q", "-c", "feature")
    assert "--background|" in _calls(calls)


def test_hooks_are_quiet_when_the_update_script_is_absent(tmp_path: Path) -> None:
    root, env, _ = _project(tmp_path)
    (root / "scripts" / "update-repomix-index.sh").unlink()
    for name in HOOK_NAMES:
        result = _hook(root, env, name, "x", "y", "1")
        assert (result.returncode, result.stderr) == (0, ""), name
