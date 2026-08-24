"""Tests for source promotion and managed-link update ops (spec §5.3)."""
from __future__ import annotations

import subprocess

import pytest

from ai_skills_fixer.gitops import current_commit
from ai_skills_fixer.installer import apply_plan
from ai_skills_fixer.planner import build_plan, set_profile_state
from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.releases import create_release
from ai_skills_fixer.rollback import rollback_apply
from ai_skills_fixer.sources import add_source, promote_source, refresh_source
from ai_skills_fixer.store import init_store


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path, body="v1\n"):
    d = path / "skills" / "foo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: foo\ndescription: does foo\n---\n{body}", encoding="utf-8"
    )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)


def bump_origin(path, body="v2\n"):
    (path / "skills" / "foo" / "SKILL.md").write_text(
        f"---\nname: foo\ndescription: does foo\n---\n{body}", encoding="utf-8"
    )
    git("commit", "-aqm", "c2", cwd=path)


@pytest.fixture
def env(tmp_path):
    store = tmp_path / "store"
    init_store(store, machine="m1")
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    add_source(store, str(origin), source_id="awesome")
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    return store, origin, home


def test_promote_moves_checkout_to_candidate(env):
    store, origin, _ = env
    bump_origin(origin)
    candidate = refresh_source(store, "awesome")

    result = promote_source(store, "awesome")
    checkout = store / "sources" / "awesome"
    assert current_commit(checkout) == candidate["candidate_commit"]
    assert result["commit"] == candidate["candidate_commit"]
    assert "v2" in (checkout / "skills" / "foo" / "SKILL.md").read_text()


def test_stale_managed_link_becomes_update_op(env, directory_link):
    store, origin, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])

    src = store / "sources" / "awesome" / "skills" / "foo"
    old_commit = current_commit(store / "sources" / "awesome")
    old_release = create_release(store, "awesome", "foo", src, old_commit)
    dest = home / ".claude" / "skills" / "foo"
    directory_link(dest, old_release)

    bump_origin(origin)
    refresh_source(store, "awesome")
    promote_source(store, "awesome")

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "update"
    assert op["precondition"]["target"] == str(old_release)
    assert "v2" not in old_release.name  # old release untouched by planning


def test_cli_source_promote(env, capsys):
    from ai_skills_fixer.cli import main

    store, origin, _ = env
    bump_origin(origin)
    base = ["--store-root", str(store)]
    assert main(["source", "refresh", *base]) == 0
    capsys.readouterr()
    assert main(["source", "promote", "awesome", *base]) == 0
    out = capsys.readouterr().out
    assert "promoted" in out
    checkout = store / "sources" / "awesome"
    assert "v2" in (checkout / "skills" / "foo" / "SKILL.md").read_text()


def test_apply_update_relinks_and_rollback_restores(env, directory_link):
    store, origin, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    src = store / "sources" / "awesome" / "skills" / "foo"
    old_commit = current_commit(store / "sources" / "awesome")
    old_release = create_release(store, "awesome", "foo", src, old_commit)
    dest = home / ".claude" / "skills" / "foo"
    directory_link(dest, old_release)

    bump_origin(origin)
    refresh_source(store, "awesome")
    promote_source(store, "awesome")

    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"])

    assert dest.resolve() != dest.absolute()
    assert dest.resolve() != old_release
    assert "v2" in (dest / "SKILL.md").read_text()
    assert content_hash(dest) == content_hash(src)

    rollback_apply(store, record["apply_id"])
    assert dest.resolve() == old_release
    assert "v2" not in (dest / "SKILL.md").read_text()
