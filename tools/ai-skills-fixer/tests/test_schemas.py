"""Tests for artifact schemas and the built-in validator (spec §6.1, §6.4).

The venv has no jsonschema, so these tests exercise the built-in
structural fallback — required keys, types, enums — reading the same
schema files a full jsonschema install would use.
"""
from __future__ import annotations

import subprocess

import yaml

from ai_skills_fixer.planner import build_plan, set_profile_state
from ai_skills_fixer.sources import add_source
from ai_skills_fixer.store import init_store
from ai_skills_fixer.validation import validate


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path):
    d = path / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: foo\ndescription: does foo\n---\nbody\n", encoding="utf-8"
    )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_init_store_artifacts_validate(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    assert validate("repositories", read_yaml(store / "registry" / "repositories.yml")) == []
    assert validate("profile", read_yaml(store / "profiles" / "default.yml")) == []
    assert validate("machine", read_yaml(store / "machines" / "m1.local.yml")) == []


def test_registry_with_source_validates(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    origin = tmp_path / "origin"
    make_skill_repo(origin)
    add_source(store, str(origin), source_id="awesome")
    assert validate("repositories", read_yaml(store / "registry" / "repositories.yml")) == []


def test_plan_and_lock_proposal_validate(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    origin = tmp_path / "origin"
    make_skill_repo(origin)
    add_source(store, str(origin), source_id="awesome")
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)

    plan = build_plan(store, "m1", home=home)
    assert validate("change-plan", plan) == []
    assert validate("lock", plan["lock_proposal"]) == []


def test_inventory_payload_validates(tmp_path):
    from ai_skills_fixer.cli import build_inventory

    home = tmp_path / "home"
    d = home / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: foo\ndescription: d\n---\nb\n")

    payload = build_inventory(home, None, [])
    assert validate("inventory", payload) == []


def test_invalid_profile_is_rejected():
    errors = validate("profile", {"schema_version": 1, "skills": [{"state": "enabled"}]})
    assert errors, "missing id must be reported"
    errors = validate("profile", {"schema_version": 1, "skills": [
        {"id": "a:b", "state": "sometimes"}
    ]})
    assert any("state" in e for e in errors)


def test_unknown_schema_kind_raises():
    import pytest

    from ai_skills_fixer.validation import SchemaError
    with pytest.raises(SchemaError):
        validate("nope", {})
