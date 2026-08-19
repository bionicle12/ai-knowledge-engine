"""Tests for store bootstrap: root resolution, machine id, init (spec §5.1, §6.2)."""
from __future__ import annotations

import yaml

from ai_skills_fixer.store import init_store, machine_id, resolve_store_root


def test_cli_flag_wins_over_env_and_default(tmp_path):
    repo = tmp_path / "repos" / "ai-knowledge-engine"
    repo.mkdir(parents=True)
    flag = tmp_path / "flagged-store"
    resolved = resolve_store_root(
        cli_value=flag,
        env={"AI_SKILLS_FIXER_STORE_ROOT": str(tmp_path / "env-store")},
        repo_root=repo,
    )
    assert resolved == flag.resolve()


def test_env_wins_over_default(tmp_path):
    repo = tmp_path / "repos" / "ai-knowledge-engine"
    repo.mkdir(parents=True)
    env_store = tmp_path / "env-store"
    resolved = resolve_store_root(
        cli_value=None,
        env={"AI_SKILLS_FIXER_STORE_ROOT": str(env_store)},
        repo_root=repo,
    )
    assert resolved == env_store.resolve()


def test_default_is_repo_sibling(tmp_path):
    repo = tmp_path / "repos" / "ai-knowledge-engine"
    repo.mkdir(parents=True)
    resolved = resolve_store_root(cli_value=None, env={}, repo_root=repo)
    assert resolved == (tmp_path / "repos" / "skill-repositories").resolve()


def test_machine_id_is_sanitized_lowercase_hostname():
    assert machine_id(hostname="My.Laptop_01") == "my-laptop-01"
    assert machine_id(hostname="linux-desktop") == "linux-desktop"


def test_machine_id_env_override():
    assert machine_id(hostname="host", env={"AI_SKILLS_FIXER_MACHINE_ID": "custom"}) == "custom"


def test_init_store_creates_skeleton_and_templates(tmp_path):
    store = tmp_path / "store"
    created = init_store(store, machine="linux-desktop")
    assert created is True

    for rel in [
        "registry", "profiles", "machines", "sources", "releases", "local",
        "state/inventories", "state/candidates", "state/model-guidance",
        "state/plans", "state/reports", "state/backups", "state/evaluations",
    ]:
        assert (store / rel).is_dir(), rel

    registry = yaml.safe_load((store / "registry" / "repositories.yml").read_text())
    assert registry == {"schema_version": 1, "repositories": {}}

    profile = yaml.safe_load((store / "profiles" / "default.yml").read_text())
    assert profile["schema_version"] == 1
    assert profile["skills"] == []

    machine = yaml.safe_load(
        (store / "machines" / "linux-desktop.local.yml").read_text()
    )
    assert machine["machine_id"] == "linux-desktop"
    assert "store_root" not in machine


def test_init_store_is_idempotent_and_preserves_files(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    profile_path = store / "profiles" / "default.yml"
    profile_path.write_text("schema_version: 1\nskills:\n- id: x\n  state: enabled\n")

    created = init_store(store, machine="m1")
    assert created is False
    assert "id: x" in profile_path.read_text()
