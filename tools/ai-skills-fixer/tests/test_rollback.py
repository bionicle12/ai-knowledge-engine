"""Tests for rollback of applied plans (spec §18, Phase 3 criterion)."""
from __future__ import annotations

import json
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
    record = apply_plan(store, plan["plan_id"], home=home)
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
    record = apply_plan(store, plan["plan_id"], home=home)
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
    record = apply_plan(store, plan["plan_id"], home=home)
    assert not dest.exists()

    rollback_apply(store, record["apply_id"])
    assert dest.is_dir()
    assert content_hash(dest) == original_hash


def test_rollback_twice_is_an_error(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    record = apply_plan(store, plan["plan_id"], home=home)
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
    record = apply_plan(store, plan["plan_id"], home=home)

    (op_result,) = record["operations"]
    shutil.rmtree(store / op_result["backup_path"])

    with pytest.raises(RollbackError):
        rollback_apply(store, record["apply_id"])
    assert dest.resolve() != dest.absolute(), (
        "destination must stay untouched when backup is gone"
    )


def test_rollback_is_resumable_after_a_blocked_undo(env):
    """B7: the first run restored `foo`, stopped at the modified `bar`; the
    retry then failed forever with `backup missing for adopt of …/foo`."""
    store, home = env
    root = home / ".claude" / "skills"
    originals = {}
    for name in ("bar", "foo"):
        set_profile_state(store, f"awesome:{name}", "enabled", targets=["claude"])
        shutil.copytree(store / "sources" / "awesome" / "skills" / name, root / name)
        originals[name] = content_hash(root / name)
    record = apply_plan(store, build_plan(store, "m1", home=home)["plan_id"], home=home)
    assert [r["type"] for r in record["operations"]] == ["adopt", "adopt"]

    # The user replaces the managed `bar` link with an edited real folder.
    (root / "bar").unlink()
    (root / "bar").mkdir()
    (root / "bar" / "SKILL.md").write_text("---\nname: bar\n---\nmy edit\n")

    with pytest.raises(RollbackError, match="run rollback .* again"):
        rollback_apply(store, record["apply_id"])
    assert content_hash(root / "foo") == originals["foo"], "foo restored first"
    saved = json.loads(
        (store / "state" / "plans" / f"{record['apply_id']}.json").read_text()
    )
    statuses = {r["skill_id"]: r["status"] for r in saved["operations"]}
    assert statuses == {"awesome:bar": "needs-recovery", "awesome:foo": "rolled-back"}
    assert "rolled_back_at" not in saved

    # The user moves their edit aside; the retry finishes the job.
    (root / "bar").rename(home / "bar-mine")
    rolled = rollback_apply(store, record["apply_id"])
    assert rolled["rolled_back_at"]
    assert content_hash(root / "bar") == originals["bar"]
    assert content_hash(root / "foo") == originals["foo"]


@pytest.mark.parametrize(
    "apply_id", ["../../registry/repositories", "plan-0123456789ab.apply-x"]
)
def test_rollback_rejects_malformed_apply_ids(env, apply_id):
    store, _ = env
    with pytest.raises(RollbackError, match="unknown apply id"):
        rollback_apply(store, apply_id)


def test_rollback_never_deletes_an_unverifiable_directory(env):
    """An install record without a release hash cannot prove the folder at
    its destination is the tool's own copy."""
    from ai_skills_fixer.rollback import undo_operation

    store, home = env
    dest = home / ".claude" / "skills" / "foo"
    dest.mkdir()
    (dest / "SKILL.md").write_text("mine\n")
    with pytest.raises(RollbackError, match="refusing to delete"):
        undo_operation(store, {"type": "install", "destination": str(dest),
                               "release_hash": None})
    assert (dest / "SKILL.md").read_text() == "mine\n"
