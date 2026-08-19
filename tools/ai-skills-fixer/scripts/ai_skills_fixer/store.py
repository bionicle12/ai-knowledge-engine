"""Store bootstrap: root resolution, machine identity, initialization.

Resolution order for the store root (spec §5.1): CLI option, then the
``AI_SKILLS_FIXER_STORE_ROOT`` environment variable, then the sibling of
the repository root. Machine-local configuration lives inside the store
and can never override the store location.
"""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from typing import Mapping

import yaml

STORE_ROOT_ENV = "AI_SKILLS_FIXER_STORE_ROOT"
MACHINE_ID_ENV = "AI_SKILLS_FIXER_MACHINE_ID"
DEFAULT_STORE_NAME = "skill-repositories"

STORE_DIRS = [
    "registry",
    "profiles",
    "machines",
    "sources",
    "releases",
    "local",
    "state/inventories",
    "state/candidates",
    "state/model-guidance",
    "state/plans",
    "state/reports",
    "state/backups",
    "state/evaluations",
]


def repo_root_from_here() -> Path:
    # tools/ai-skills-fixer/scripts/ai_skills_fixer/store.py -> repo root
    return Path(__file__).resolve().parents[4]


def resolve_store_root(
    cli_value: Path | None,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    env = os.environ if env is None else env
    if cli_value is not None:
        return Path(cli_value).resolve()
    if env.get(STORE_ROOT_ENV):
        return Path(env[STORE_ROOT_ENV]).resolve()
    repo_root = repo_root_from_here() if repo_root is None else Path(repo_root)
    return (repo_root.resolve().parent / DEFAULT_STORE_NAME).resolve()


def machine_id(
    hostname: str | None = None, env: Mapping[str, str] | None = None
) -> str:
    env = os.environ if env is None else env
    if env.get(MACHINE_ID_ENV):
        return env[MACHINE_ID_ENV]
    hostname = hostname if hostname is not None else socket.gethostname()
    sanitized = re.sub(r"[^a-z0-9-]+", "-", hostname.lower()).strip("-")
    return sanitized or "machine"


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def init_store(store_root: Path, machine: str) -> bool:
    """Create the store skeleton. Returns True if anything was created.

    Existing files are never overwritten.
    """
    store_root = Path(store_root)
    created = not store_root.is_dir()

    for rel in STORE_DIRS:
        target = store_root / rel
        if not target.is_dir():
            target.mkdir(parents=True)
            created = True

    registry = store_root / "registry" / "repositories.yml"
    if not registry.exists():
        _write_yaml(registry, {"schema_version": 1, "repositories": {}})
        created = True

    profile = store_root / "profiles" / "default.yml"
    if not profile.exists():
        _write_yaml(profile, {"schema_version": 1, "skills": []})
        created = True

    machine_file = store_root / "machines" / f"{machine}.local.yml"
    if not machine_file.exists():
        _write_yaml(
            machine_file,
            {
                "schema_version": 1,
                "machine_id": machine,
                "agents": {
                    host: {"enabled": True, "install_path": "auto", "strategy": "auto"}
                    for host in ("claude", "codex", "cursor", "antigravity")
                },
                "profile_overrides": {"disable": [], "additional_targets": {}},
            },
        )
        created = True

    return created
