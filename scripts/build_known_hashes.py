#!/usr/bin/env python3
"""Rebuild scripts/known_hashes.json from this repository's git history.

The registry lists every upstream version of the files and AGENTS.md managed
blocks that `kb_upgrade.py` delivers into deployed bases:

    {"files":  {"knowledge-base/scripts/kb_lint.py": {"<sha256>": ["0.15.0"], …}},
     "blocks": {"INDEX": {"<sha256>": ["0.13.0", "0.15.0", …]}, …}}

Keys are SHA-256 digests of the content with CRLF read as LF. Every committed
version is listed (so the upgrader recognises an unmodified copy and replaces
it instead of writing a `.new` sidecar — without git tags or a full clone,
e.g. when the engine came as a ZIP download); the list names the releases that
shipped exactly this content: the first commit of each `VERSION` value.

Walks every commit reachable from HEAD (use a full clone, not a shallow one)
plus the working tree. The working tree counts as the release of its
`VERSION` when no commit carries that value yet — so run this after bumping
`VERSION` and before the release commit (docs/MAINTENANCE.md).

Usage:
    python3 scripts/build_known_hashes.py
    python3 scripts/build_known_hashes.py --repo /path/to/checkout --output /tmp/known.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import kb_upgrade  # noqa: E402

TEMPLATE_PATH = "knowledge-base/templates/AGENTS.md.template"
# Before 0.16.0 the VIEW / INDEX reference blocks were constants in here.
LEGACY_UPGRADER_PATH = "scripts/kb_upgrade.py"
_LEGACY_MARKER_RE = re.compile(r'^([A-Z]+_BLOCK_(?:BEGIN|END)) = "([^"\n]*)"', re.M)
_LEGACY_BLOCK_RE = re.compile(r'^([A-Z]+)_BLOCK = f?"""\\\n(.*?)"""', re.M | re.S)


def _git(repo: Path, *args: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, check=False
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def legacy_blocks(source: str) -> dict[str, str]:
    """Managed blocks hard-coded in a pre-0.16 `scripts/kb_upgrade.py`."""
    markers = dict(_LEGACY_MARKER_RE.findall(source))
    blocks: dict[str, str] = {}
    for label, body in _LEGACY_BLOCK_RE.findall(source):
        if label not in kb_upgrade.MANAGED_BLOCK_LABELS:
            continue
        for name, value in markers.items():
            body = body.replace("{" + name + "}", value)
        blocks[label] = body
    return blocks


class Registry:
    def __init__(self) -> None:
        self.files: dict[str, dict[str, set[str]]] = {}
        self.blocks: dict[str, dict[str, set[str]]] = {}

    def add(self, rel: str, data: bytes, release: str | None) -> None:
        if kb_upgrade.is_managed_source(rel):
            versions = self.files.setdefault(rel, {}).setdefault(
                kb_upgrade.content_digest(data), set()
            )
            if release:
                versions.add(release)
        text = data.decode("utf-8", errors="replace")
        if rel == TEMPLATE_PATH:
            self._add_blocks(kb_upgrade.extract_managed_blocks(text), release)
        elif rel == LEGACY_UPGRADER_PATH:
            self._add_blocks(legacy_blocks(text), release)

    def _add_blocks(self, blocks: dict[str, str], release: str | None) -> None:
        for label, block in blocks.items():
            versions = self.blocks.setdefault(label, {}).setdefault(
                kb_upgrade.block_digest(block), set()
            )
            if release:
                versions.add(release)

    def as_json(self) -> dict:
        def order(version: str) -> tuple:
            return (kb_upgrade.version_key(version) or (), version)

        def dump(table: dict[str, dict[str, set[str]]]) -> dict:
            return {
                key: {
                    digest: sorted(versions, key=order)
                    for digest, versions in sorted(entries.items())
                }
                for key, entries in sorted(table.items())
            }

        return {
            "format": 1,
            "generated_by": "scripts/build_known_hashes.py",
            "files": dump(self.files),
            "blocks": dump(self.blocks),
        }


def _wanted(rel: str) -> bool:
    return rel in (TEMPLATE_PATH, LEGACY_UPGRADER_PATH) or kb_upgrade.is_managed_source(rel)


def build_registry(repo: Path) -> dict:
    """Registry of `repo` (a git checkout): its history plus the working tree."""
    registry = Registry()
    blobs: dict[str, bytes] = {}
    released: set[str] = set()
    commits = (_git(repo, "rev-list", "--reverse", "--topo-order", "HEAD") or b"").split()
    for commit in (c.decode() for c in commits):
        version = (_git(repo, "show", f"{commit}:VERSION") or b"").decode(
            "utf-8", errors="replace"
        ).strip()
        release = version if version and version not in released else None
        if release:
            released.add(release)
        listing = _git(
            repo, "ls-tree", "-r", "-z", commit, "knowledge-base", LEGACY_UPGRADER_PATH
        ) or b""
        for entry in listing.split(b"\0"):
            meta, _, path = entry.partition(b"\t")
            fields = meta.split()
            rel = path.decode("utf-8", errors="replace")
            if len(fields) != 3 or fields[1] != b"blob" or not _wanted(rel):
                continue
            oid = fields[2].decode()
            if oid not in blobs:
                blobs[oid] = _git(repo, "cat-file", "blob", oid) or b""
            registry.add(rel, blobs[oid], release)

    version_file = repo / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
    release = version if version and version not in released else None
    for path in sorted((repo / "knowledge-base").rglob("*")):
        rel = path.relative_to(repo).as_posix()
        if path.is_file() and _wanted(rel):
            registry.add(rel, path.read_bytes(), release)
    upgrader = repo / LEGACY_UPGRADER_PATH
    if upgrader.is_file():
        registry.add(LEGACY_UPGRADER_PATH, upgrader.read_bytes(), release)
    return registry.as_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild scripts/known_hashes.json from git history"
    )
    parser.add_argument(
        "--repo", type=Path, default=kb_upgrade.REPO_ROOT, help="engine checkout (default: this one)"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="default: <repo>/scripts/known_hashes.json"
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if _git(repo, "rev-parse", "HEAD") is None:
        print(f"[ERROR] {repo} is not a git checkout with commits", file=sys.stderr)
        return 2
    if (_git(repo, "rev-parse", "--is-shallow-repository") or b"").strip() == b"true":
        print(
            "[WARN] shallow clone: versions older than its history are missing — "
            "run `git fetch --unshallow` first",
            file=sys.stderr,
        )
    data = build_registry(repo)
    output = args.output or repo / "scripts" / "known_hashes.json"
    kb_upgrade.kbc.atomic_write_text(output, json.dumps(data, indent=1) + "\n")
    digests = sum(len(entries) for entries in data["files"].values())
    print(
        f"Wrote {output}: {len(data['files'])} files ({digests} versions), "
        f"{len(data['blocks'])} managed blocks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
