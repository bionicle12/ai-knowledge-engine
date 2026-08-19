"""Tests for plan application with drift protection (spec §17, §18, §19)."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from ai_skills_fixer.installer import DriftError, LockError, apply_plan
from ai_skills_fixer.planner import build_plan, set_profile_state
from ai_skills_fixer.provenance import content_hash
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
        (d / "references").mkdir(exist_ok=True)
        (d / "references" / "notes.md").write_text("n\n", encoding="utf-8")
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


def test_apply_install_creates_release_and_symlink(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    record = apply_plan(store, plan["plan_id"])

    dest = home / ".claude" / "skills" / "foo"
    assert dest.is_symlink()
    assert (dest / "SKILL.md").is_file()
    assert str(dest.resolve()).startswith(str(store / "releases"))
    assert record["success"] is True
    (op_result,) = [r for r in record["operations"] if r["type"] == "install"]
    assert op_result["status"] == "applied"
    saved = store / "state" / "plans" / f"{record['apply_id']}.json"
    assert saved.is_file()


def test_apply_adopt_backs_up_original_and_links(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    src = store / "sources" / "awesome" / "skills" / "foo"
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(src, dest)
    original_hash = content_hash(dest)

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])

    assert dest.is_symlink()
    assert content_hash(dest) == original_hash
    (op_result,) = record["operations"]
    backup = store / op_result["backup_path"]
    assert backup.is_dir() and not backup.is_symlink()
    assert content_hash(backup) == original_hash


def test_apply_quarantine_moves_copy_to_backup(env):
    store, home = env
    set_profile_state(store, "awesome:bar", "excluded")
    src = store / "sources" / "awesome" / "skills" / "bar"
    dest = home / ".claude" / "skills" / "bar"
    shutil.copytree(src, dest)

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])

    assert not dest.exists()
    (op_result,) = record["operations"]
    assert op_result["status"] == "applied"
    assert content_hash(store / op_result["backup_path"]) == content_hash(src)


def test_apply_skips_review_ops(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", dest)
    (dest / "SKILL.md").write_text("---\nname: foo\n---\nlocal edit\n")
    before = content_hash(dest)

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])

    (op_result,) = record["operations"]
    assert op_result["status"] == "skipped-manual-review"
    assert content_hash(dest) == before


def test_apply_rejects_config_drift(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    set_profile_state(store, "awesome:bar", "enabled", targets=["claude"])

    with pytest.raises(DriftError):
        apply_plan(store, plan["plan_id"])
    assert not (home / ".claude" / "skills" / "foo").exists()


def test_partial_failure_rolls_back_completed_ops(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    set_profile_state(store, "awesome:bar", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    # Ops apply in sorted order (bar, then foo). Sabotage the SECOND op so
    # the first one really gets applied and must then be rolled back.
    (home / ".claude" / "skills" / "foo").mkdir()

    with pytest.raises(DriftError):
        apply_plan(store, plan["plan_id"])

    assert not (home / ".claude" / "skills" / "bar").exists(), (
        "completed install must be rolled back after partial failure"
    )


def test_concurrent_mutating_run_fails_fast(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    (store / "state" / ".lock").write_text("held\n")

    with pytest.raises(LockError):
        apply_plan(store, plan["plan_id"])
