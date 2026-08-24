"""Tests for the dry-run reconciliation planner (spec §5.4, §17, §18)."""
from __future__ import annotations

import shutil
import subprocess
import os
from pathlib import Path

import pytest

from ai_skills_fixer.planner import ValidationError, build_plan, set_profile_state
from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.releases import create_release
from ai_skills_fixer.sources import CatalogError, add_source
from ai_skills_fixer.store import init_store
from ai_skills_fixer.gitops import current_commit


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
    return store, home, tmp_path


def ops_by_key(plan):
    return {(op["skill_id"], op["host"], op["type"]): op for op in plan["operations"]}


def test_install_op_for_missing_skill(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    ops = plan["operations"]
    assert len(ops) == 1
    op = ops[0]
    assert op["type"] == "install"
    assert op["skill_id"] == "awesome:foo"
    assert op["host"] == "claude"
    assert op["strategy"] == ("junction" if os.name == "nt" else "symlink")
    assert Path(op["destination"]).parts[-3:] == (".claude", "skills", "foo")
    assert Path(op["source"]).parts[-4:-1] == ("releases", "awesome", "foo")
    assert op["precondition"] == {"destination": "absent"}


def test_adopt_op_for_exact_unmanaged_copy(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    src = store / "sources" / "awesome" / "skills" / "foo"
    shutil.copytree(src, home / ".claude" / "skills" / "foo")

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "adopt"
    assert op["precondition"]["content_hash"] == content_hash(src)
    assert op["backup"] is not None


def test_review_op_for_modified_copy(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", dest)
    (dest / "SKILL.md").write_text("---\nname: foo\n---\nlocal edits\n")

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "review"
    assert op["risk"] == "high"


def test_quarantine_op_for_excluded_installed(env):
    store, home, _ = env
    set_profile_state(store, "awesome:bar", "excluded")
    shutil.copytree(
        store / "sources" / "awesome" / "skills" / "bar",
        home / ".claude" / "skills" / "bar",
    )

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "quarantine"
    assert op["backup"] is not None


def test_noop_for_managed_link_on_current_release(env, directory_link):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    src = store / "sources" / "awesome" / "skills" / "foo"
    commit = current_commit(store / "sources" / "awesome")
    release = create_release(store, "awesome", "foo", src, commit)
    directory_link(home / ".claude" / "skills" / "foo", release)

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "noop"


def test_occasional_fallback_is_recorded_not_installed(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "occasional", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    assert plan["operations"] == []
    assert plan["notes"]["occasional_fallbacks"] == {
        "awesome:foo": "catalog-only (no low-noise exposure on claude)"
    }


def test_plan_id_is_deterministic_and_input_sensitive(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan_a = build_plan(store, "m1", home=home)
    plan_b = build_plan(store, "m1", home=home)
    assert plan_a["plan_id"] == plan_b["plan_id"]

    set_profile_state(store, "awesome:bar", "enabled", targets=["claude"])
    plan_c = build_plan(store, "m1", home=home)
    assert plan_c["plan_id"] != plan_a["plan_id"]


def test_plan_is_saved_with_config_hashes_and_lock_proposal(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    saved = store / "state" / "plans" / f"{plan['plan_id']}.json"
    assert saved.is_file()
    assert set(plan["config_hashes"]) == {"registry", "profile", "machine"}

    (lock_entry,) = plan["lock_proposal"]["skills"]
    assert lock_entry["skill_id"] == "awesome:foo"
    assert lock_entry["resolved_commit"] == current_commit(
        store / "sources" / "awesome"
    )
    assert lock_entry["content_hash"]
    assert lock_entry["release"]


def test_unknown_profile_skill_is_validation_error(env):
    store, home, _ = env
    set_profile_state(store, "awesome:ghost", "enabled", targets=["claude"])
    with pytest.raises(ValidationError):
        build_plan(store, "m1", home=home)


def test_dirty_source_checkout_is_safe_stop(env):
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    (store / "sources" / "awesome" / "skills" / "foo" / "SKILL.md").write_text(
        "dirty\n"
    )
    with pytest.raises(CatalogError):
        build_plan(store, "m1", home=home)
