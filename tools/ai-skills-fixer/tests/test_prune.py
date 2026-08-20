"""Tests for prune mode: quarantine what the profile does not keep (spec §18)."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from ai_skills_fixer.planner import build_plan, set_profile_state
from ai_skills_fixer.sources import add_source
from ai_skills_fixer.store import init_store


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path, skills=("keep-me", "prune-me", "occasional-one")):
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
    root = home / ".claude" / "skills"
    root.mkdir(parents=True)
    src = store / "sources" / "awesome" / "skills"
    shutil.copytree(src / "keep-me", root / "keep-me")
    shutil.copytree(src / "prune-me", root / "prune-me")
    shutil.copytree(src / "occasional-one", root / "occasional-one")
    (root / "unknown-orig").mkdir()
    (root / "unknown-orig" / "SKILL.md").write_text(
        "---\nname: unknown-orig\ndescription: mine\n---\nlocal\n"
    )
    return store, home


def ops_of(plan, op_type):
    return [op for op in plan["operations"] if op["type"] == op_type]


def test_prune_quarantines_unprofiled_exact_copies_only(env):
    store, home = env
    set_profile_state(store, "awesome:keep-me", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home, prune=True)

    quarantined = {op["destination"].split("/")[-1] for op in ops_of(plan, "quarantine")}
    assert quarantined == {"prune-me", "occasional-one"}
    assert [op["destination"].split("/")[-1] for op in ops_of(plan, "adopt")] == ["keep-me"]
    assert "unknown-orig" in plan["notes"]["prune_skipped"]["claude"]


def test_prune_keeps_occasional_out_of_hosts_but_quarantines_installed_copy(env):
    store, home = env
    set_profile_state(store, "awesome:keep-me", "enabled", targets=["claude"])
    set_profile_state(store, "awesome:occasional-one", "occasional", targets=["claude"])
    plan = build_plan(store, "m1", home=home, prune=True)

    quarantined = {op["destination"].split("/")[-1] for op in ops_of(plan, "quarantine")}
    assert "occasional-one" in quarantined, (
        "occasional means catalog-only exposure; the installed copy goes away"
    )


def test_without_prune_unprofiled_skills_are_untouched(env):
    store, home = env
    set_profile_state(store, "awesome:keep-me", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    quarantined = {op["destination"].split("/")[-1] for op in ops_of(plan, "quarantine")}
    assert quarantined == set()
