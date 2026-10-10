"""System-git wrapper with fixed argument lists (spec §6.4).

Clone and fetch are the tool's only network activity; everything else
reads local repository state. Errors surface as GitError with the git
stderr attached — never as raw subprocess exceptions. Caller-supplied
URLs and refs can never be parsed as git options, and credentials
embedded in a URL never reach an error message.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class GitError(Exception):
    pass


_HTTP_USERINFO_RE = re.compile(r"(?i)\b(https?://)[^/\s@]+@")


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


def redact_url(url: str) -> str:
    """Drop credentials from a clone URL before it is stored or printed.

    For http(s) the whole userinfo goes (a token is often passed as the
    user name); for other schemes only a password is removed, so
    ``ssh://git@host/...`` stays usable. scp-like ``git@host:path`` and
    local paths carry no secret and are returned unchanged.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or "@" not in parts.netloc:
        return url
    userinfo, _, hostport = parts.netloc.rpartition("@")
    if parts.scheme.lower() in ("http", "https"):
        netloc = hostport
    elif ":" in userinfo:
        netloc = f"{userinfo.split(':', 1)[0]}@{hostport}"
    else:
        return url
    return urlunsplit(parts._replace(netloc=netloc))


def _check_ref(ref: str) -> None:
    if not ref or ref.startswith("-"):
        raise GitError(f"refusing git ref {ref!r}: empty or looks like an option")


def clone(url: str, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["clone", "--quiet", "--", url, str(dest)])
    except GitError as exc:
        message = str(exc).replace(url, redact_url(url))
        raise GitError(_HTTP_USERINFO_RE.sub(r"\1", message)) from None


def fetch(repo: Path) -> None:
    _run(["-C", str(repo), "fetch", "--quiet", "origin"])


def checkout(repo: Path, ref: str) -> None:
    _check_ref(ref)
    _run(["-C", str(repo), "checkout", "--quiet", "--detach", ref])


def current_branch(repo: Path) -> str:
    """Branch name, or the commit hash when HEAD is detached."""
    name = _run(["-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if name == "HEAD":
        return rev_parse(repo, "HEAD")
    return name


def rev_parse(repo: Path, ref: str = "HEAD") -> str:
    _check_ref(ref)
    return _run(["-C", str(repo), "rev-parse", "--verify", ref]).strip()


def current_commit(repo: Path) -> str:
    return rev_parse(repo, "HEAD")


def is_dirty(repo: Path) -> bool:
    return bool(_run(["-C", str(repo), "status", "--porcelain"]).strip())
