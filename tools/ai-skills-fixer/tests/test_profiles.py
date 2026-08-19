"""Tests for profile and machine-config loading and validation (spec §7.2, §7.3)."""
from __future__ import annotations

import pytest
import yaml

from ai_skills_fixer.planner import (
    ValidationError, load_machine, load_profile, set_profile_state,
)
from ai_skills_fixer.store import init_store


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    init_store(root, machine="test-machine")
    return root


def write_profile(store, skills):
    (store / "profiles" / "default.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "skills": skills}), encoding="utf-8"
    )


def test_load_valid_profile(store):
    write_profile(store, [
        {"id": "awesome:backend-architect", "state": "enabled",
         "targets": ["claude", "codex"]},
        {"id": "awesome:blockchain-developer", "state": "excluded"},
    ])
    skills = load_profile(store)
    assert skills[0].skill_id == "awesome:backend-architect"
    assert skills[0].state == "enabled"
    assert skills[0].targets == ["claude", "codex"]
    assert skills[1].state == "excluded"
    assert skills[1].targets == []


def test_unknown_state_is_validation_error(store):
    write_profile(store, [{"id": "a:b", "state": "sometimes"}])
    with pytest.raises(ValidationError):
        load_profile(store)


def test_unknown_target_is_validation_error(store):
    write_profile(store, [{"id": "a:b", "state": "enabled", "targets": ["emacs"]}])
    with pytest.raises(ValidationError):
        load_profile(store)


def test_duplicate_profile_ids_are_validation_error(store):
    write_profile(store, [
        {"id": "a:b", "state": "enabled", "targets": ["claude"]},
        {"id": "a:b", "state": "excluded"},
    ])
    with pytest.raises(ValidationError):
        load_profile(store)


def test_load_machine_defaults(store):
    machine = load_machine(store, "test-machine")
    assert machine["machine_id"] == "test-machine"
    assert machine["agents"]["claude"]["enabled"] is True
    assert machine["profile_overrides"]["disable"] == []


def test_load_machine_missing_file_is_validation_error(store):
    with pytest.raises(ValidationError):
        load_machine(store, "other-machine")


def test_set_profile_state_appends_and_updates(store):
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    skills = load_profile(store)
    assert skills[0].skill_id == "awesome:foo"
    assert skills[0].state == "enabled"

    set_profile_state(store, "awesome:foo", "excluded")
    skills = load_profile(store)
    assert len(skills) == 1
    assert skills[0].state == "excluded"


def test_set_profile_state_rejects_bad_input(store):
    with pytest.raises(ValidationError):
        set_profile_state(store, "awesome:foo", "sometimes")
    with pytest.raises(ValidationError):
        set_profile_state(store, "awesome:foo", "enabled", targets=["emacs"])
