"""Tests for rollback of applied plans (spec §18, Phase 3 criterion)."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from ai_skills_fixer.installer import apply_plan
from ai_skills_fixer.planner import build_plan, set_profile_state
from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.rollback import RollbackError, rollback_apply
from ai_skills_fixer.sources import add_source
from ai_skills_fixer.store import init_store


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path, skills=("foo", "bar")):
    for skill in skills:
        d = path / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: does {skill}\n---\nbody\n",
            encoding="utf-8",
        )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)


@pytest.fixture
def env(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    add_source(store, str(origin), source_id="awesome")
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    return store, home


def test_rollback_restores_adopted_copy_byte_identical(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", dest)
    original_hash = content_hash(dest)

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])
    assert dest.resolve() != dest.absolute()

    rolled = rollback_apply(store, record["apply_id"])
    assert dest.resolve() == dest.absolute() and dest.is_dir()
    assert content_hash(dest) == original_hash
    assert rolled["rolled_back_at"]
    assert all(r["status"] in ("rolled-back", "noop", "skipped-manual-review")
               for r in rolled["operations"])


def test_rollback_removes_installed_link(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])
    dest = home / ".claude" / "skills" / "foo"
    assert dest.resolve() != dest.absolute()

    rollback_apply(store, record["apply_id"])
    assert not dest.exists() and not dest.is_symlink()


def test_rollback_restores_quarantined_copy(env):
    store, home = env
    set_profile_state(store, "awesome:bar", "excluded")
    dest = home / ".claude" / "skills" / "bar"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "bar", dest)
    original_hash = content_hash(dest)

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])
    assert not dest.exists()

    rollback_apply(store, record["apply_id"])
    assert dest.is_dir()
    assert content_hash(dest) == original_hash


def test_rollback_twice_is_an_error(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])
    rollback_apply(store, record["apply_id"])
    with pytest.raises(RollbackError):
        rollback_apply(store, record["apply_id"])


def test_rollback_unknown_apply_id_is_an_error(env):
    store, _ = env
    with pytest.raises(RollbackError):
        rollback_apply(store, "plan-nope.apply-20260101T000000Z")


def test_rollback_refuses_when_backup_is_missing(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", dest)
    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])

    (op_result,) = record["operations"]
    shutil.rmtree(store / op_result["backup_path"])

    with pytest.raises(RollbackError):
        rollback_apply(store, record["apply_id"])
    assert dest.resolve() != dest.absolute(), (
        "destination must stay untouched when backup is gone"
    )
