"""System-git wrapper with fixed argument lists (spec §6.4).

Clone and fetch are the tool's only network activity; everything else
reads local repository state. Errors surface as GitError with the git
stderr attached — never as raw subprocess exceptions.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(args: list[str], cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GitError(f"cannot execute git: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def clone(url: str, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["clone", "--quiet", url, str(dest)])


def fetch(repo: Path) -> None:
    _run(["-C", str(repo), "fetch", "--quiet", "origin"])


def checkout(repo: Path, ref: str) -> None:
    _run(["-C", str(repo), "checkout", "--quiet", "--detach", ref])


def current_branch(repo: Path) -> str:
    """Branch name, or the commit hash when HEAD is detached."""
    name = _run(["-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if name == "HEAD":
        return rev_parse(repo, "HEAD")
    return name


def rev_parse(repo: Path, ref: str = "HEAD") -> str:
    return _run(["-C", str(repo), "rev-parse", "--verify", ref]).strip()


def current_commit(repo: Path) -> str:
    return rev_parse(repo, "HEAD")


def is_dirty(repo: Path) -> bool:
    return bool(_run(["-C", str(repo), "status", "--porcelain"]).strip())
