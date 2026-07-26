#!/usr/bin/env python3
"""Thin launcher for the authoritative AI Knowledge Engine upgrader.

This file is deployed into each knowledge base. It deliberately contains no
upgrade rules of its own: it finds the current source repository and delegates
to ``<repo>/scripts/kb_upgrade.py`` so the updater never updates from a stale
copy of itself.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


def _is_source_repo(path: Path) -> bool:
    return (
        (path / "VERSION").is_file()
        and (path / "scripts" / "kb_upgrade.py").is_file()
        and (path / "knowledge-base").is_dir()
    )


def _candidate_parents(start: Path) -> list[Path]:
    resolved = start.resolve()
    return [resolved, *resolved.parents]


def find_source_repo(
    *,
    explicit: Path | None,
    start: Path,
    script_path: Path,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the authoritative source repo from explicit/env/local hints."""
    env = environment if environment is not None else os.environ
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    configured = env.get("AI_KNOWLEDGE_ENGINE_HOME", "").strip()
    if configured:
        candidates.append(Path(configured))

    for parent in _candidate_parents(start):
        candidates.extend((parent, parent / "ai-knowledge-engine"))
    for parent in _candidate_parents(script_path.parent):
        candidates.extend((parent, parent / "ai-knowledge-engine"))

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        identity = str(resolved).casefold() if os.name == "nt" else str(resolved)
        if identity in seen:
            continue
        seen.add(identity)
        if _is_source_repo(resolved):
            return resolved
    raise FileNotFoundError(
        "AI Knowledge Engine source repository not found. Pass "
        "--repo-root PATH or set AI_KNOWLEDGE_ENGINE_HOME."
    )


def find_kb_root(start: Path) -> Path:
    for candidate in _candidate_parents(start):
        if (candidate / "kb.config.yml").is_file():
            return candidate
    raise FileNotFoundError(
        "kb.config.yml not found. Run this command from inside a deployed KB "
        "or pass --kb-root to the central updater."
    )


def build_command(
    *,
    source_repo: Path,
    kb_root: Path,
    passthrough: Sequence[str],
) -> list[str]:
    arguments = list(passthrough)
    has_target = "--kb-root" in arguments or "--all-root" in arguments
    target = [] if has_target else ["--kb-root", str(kb_root)]
    return [
        sys.executable,
        str(source_repo / "scripts" / "kb_upgrade.py"),
        *target,
        *arguments,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        add_help=False,
        description="Launch the current AI Knowledge Engine upgrader",
    )
    parser.add_argument("--repo-root", type=Path)
    known, passthrough = parser.parse_known_args(argv)
    if "-h" in passthrough or "--help" in passthrough:
        print(
            "Local KB updater\n\n"
            "  --repo-root PATH  authoritative ai-knowledge-engine checkout\n"
            "  all other options are forwarded to the central kb_upgrade.py\n"
        )
    try:
        kb_root = find_kb_root(Path.cwd())
        source_repo = find_source_repo(
            explicit=known.repo_root,
            start=kb_root,
            script_path=Path(__file__),
        )
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 3
    command = build_command(
        source_repo=source_repo,
        kb_root=kb_root,
        passthrough=passthrough,
    )
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
