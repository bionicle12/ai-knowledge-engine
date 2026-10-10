"""Tests for plan application with drift protection (spec §17, §18, §19)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ai_skills_fixer import installer
from ai_skills_fixer.installer import ApplyError, DriftError, LockError, apply_plan
from ai_skills_fixer.planner import (
    ValidationError, build_plan, plan_id_for, set_profile_state,
)
from ai_skills_fixer.provenance import content_hash
from ai_skills_fixer.rollback import rollback_apply
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

    record = apply_plan(store, plan["plan_id"], home=home)

    dest = home / ".claude" / "skills" / "foo"
    assert dest.resolve() != dest.absolute()
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
    record = apply_plan(store, plan["plan_id"], home=home)

    assert dest.resolve() != dest.absolute()
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
    record = apply_plan(store, plan["plan_id"], home=home)

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
    record = apply_plan(store, plan["plan_id"], home=home)

    (op_result,) = record["operations"]
    assert op_result["status"] == "skipped-manual-review"
    assert content_hash(dest) == before


def test_apply_rejects_config_drift(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    set_profile_state(store, "awesome:bar", "enabled", targets=["claude"])

    with pytest.raises(DriftError):
        apply_plan(store, plan["plan_id"], home=home)
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
        apply_plan(store, plan["plan_id"], home=home)

    assert not (home / ".claude" / "skills" / "bar").exists(), (
        "completed install must be rolled back after partial failure"
    )


def test_concurrent_mutating_run_fails_fast(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    (store / "state" / ".lock").write_text("held\n")

    with pytest.raises(LockError):
        apply_plan(store, plan["plan_id"], home=home)


def load_record(store, apply_id):
    return json.loads(
        (store / "state" / "plans" / f"{apply_id}.json").read_text(encoding="utf-8")
    )


def only_record(store):
    (path,) = (store / "state" / "plans").glob("*.apply-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_non_drift_failure_rolls_back_and_is_recorded(env, monkeypatch):
    """B3a: a PermissionError while backing up the 2nd op used to leave the
    1st op applied with no apply record, so rollback was impossible."""
    store, home = env
    set_profile_state(store, "awesome:bar", "enabled", targets=["claude"])
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    foo = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", foo)
    original = content_hash(foo)
    plan = build_plan(store, "m1", home=home)
    assert [op["type"] for op in plan["operations"]] == ["install", "adopt"]

    def denied(src, dst):
        raise PermissionError(13, "Permission denied", src)

    monkeypatch.setattr(installer.shutil, "move", denied)
    with pytest.raises(ApplyError, match="rolled back"):
        apply_plan(store, plan["plan_id"], home=home)

    bar = home / ".claude" / "skills" / "bar"
    assert not bar.exists() and not bar.is_symlink(), "applied install rolled back"
    assert foo.is_dir() and not foo.is_symlink() and content_hash(foo) == original
    record = only_record(store)
    assert record["success"] is False and record["finished_at"]
    assert "Permission denied" in record["error"]
    assert [r["status"] for r in record["operations"]] == ["rolled-back", "failed"]


def test_failed_post_install_validation_removes_the_new_link(env, monkeypatch):
    """B3b: the link created by the failing op was left behind unrecorded."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    def invalid(dest, digest):
        raise DriftError(f"post-install validation failed at {dest}")

    monkeypatch.setattr(installer, "_validate_installed", invalid)
    with pytest.raises(DriftError, match="apply plan-"):
        apply_plan(store, plan["plan_id"], home=home)

    dest = home / ".claude" / "skills" / "foo"
    assert not dest.exists() and not dest.is_symlink()
    (op,) = only_record(store)["operations"]
    assert op["status"] == "failed"


def test_failed_adopt_restores_the_original_copy(env, monkeypatch):
    """B3c: adopt failing after the backup left the copy only in backups."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "awesome" / "skills" / "foo", dest)
    original = content_hash(dest)
    plan = build_plan(store, "m1", home=home)

    def broken(release, target, strategy):
        raise OSError("disk full")

    monkeypatch.setattr(installer, "materialize_directory", broken)
    with pytest.raises(DriftError):
        apply_plan(store, plan["plan_id"], home=home)

    assert dest.is_dir() and not dest.is_symlink()
    assert content_hash(dest) == original
    (op,) = only_record(store)["operations"]
    assert op["status"] == "failed"
    assert not (store / op["backup_path"]).exists()


def test_interrupted_apply_leaves_a_journal_rollback_can_replay(env, monkeypatch):
    """B3: intent is journaled before each effect, so even a run killed
    mid-operation (not caught as Exception) can be rolled back."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)

    def killed(dest, digest):
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "_validate_installed", killed)
    with pytest.raises(KeyboardInterrupt):
        apply_plan(store, plan["plan_id"], home=home)

    dest = home / ".claude" / "skills" / "foo"
    assert dest.is_symlink(), "the interrupted op really left its link"
    record = only_record(store)
    (op,) = record["operations"]
    assert op["status"] == "in-progress" and op["release_hash"]

    rolled = rollback_apply(store, record["apply_id"])
    assert not dest.exists() and not dest.is_symlink()
    assert rolled["operations"][0]["status"] == "rolled-back"


def test_edited_plan_is_refused(env, tmp_path):
    """B5: an approved plan with an appended quarantine of an arbitrary
    directory used to apply with rc=0."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    important = tmp_path / "Documents" / "important"
    important.mkdir(parents=True)
    (important / "notes.txt").write_text("keep me\n")

    path = store / "state" / "plans" / f"{plan['plan_id']}.json"
    data = json.loads(path.read_text())
    data["operations"].append({
        "skill_id": "awesome:foo", "host": "claude", "type": "quarantine",
        "destination": str(important), "strategy": None, "source": None,
        "precondition": {"destination": "exists",
                         "content_hash": content_hash(important)},
        "risk": "medium", "approval_required": True,
    })
    path.write_text(json.dumps(data))

    with pytest.raises(ValidationError, match="edited after reconcile"):
        apply_plan(store, plan["plan_id"], home=home)
    assert (important / "notes.txt").read_text() == "keep me\n"
    assert not (home / ".claude" / "skills" / "foo").exists()


def test_destination_outside_the_user_root_is_refused(env, tmp_path):
    """B5: even a plan that hashes correctly may only touch direct children
    of the recorded user skill root."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    important = tmp_path / "Documents" / "important"
    important.mkdir(parents=True)

    forged = {k: v for k, v in plan.items() if k not in ("plan_id", "created_at")}
    forged["operations"] = [dict(plan["operations"][0], type="quarantine",
                                 destination=str(important))]
    forged["plan_id"] = plan_id_for(forged)
    (store / "state" / "plans" / f"{forged['plan_id']}.json").write_text(
        json.dumps(forged)
    )

    with pytest.raises(ValidationError, match="not a direct child"):
        apply_plan(store, forged["plan_id"], home=home)
    assert important.is_dir()


def test_plan_bringing_its_own_user_roots_is_refused(env, tmp_path):
    """B5: a self-consistent plan (ID recomputed) that also rewrites
    `user_roots` used to quarantine any folder it named."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    documents = home / "Documents"
    important = documents / "important"
    important.mkdir(parents=True)
    (important / "data.txt").write_text("precious\n", encoding="utf-8")

    forged = {k: v for k, v in plan.items() if k not in ("plan_id", "created_at")}
    forged["user_roots"] = dict(plan["user_roots"], claude=str(documents))
    forged["operations"] = [dict(
        plan["operations"][0], type="quarantine", destination=str(important),
        precondition={"destination": "exists",
                      "content_hash": content_hash(important)},
    )]
    forged["plan_id"] = plan_id_for(forged)
    (store / "state" / "plans" / f"{forged['plan_id']}.json").write_text(
        json.dumps(forged)
    )

    with pytest.raises(ValidationError, match="discovery finds"):
        apply_plan(store, forged["plan_id"], home=home)
    assert (important / "data.txt").read_text() == "precious\n"


def test_apply_needs_the_home_reconcile_used(env, tmp_path):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    other = tmp_path / "other-home"
    (other / ".claude" / "skills").mkdir(parents=True)

    with pytest.raises(ValidationError, match="same --home"):
        apply_plan(store, plan["plan_id"], home=other)
    assert not (other / ".claude" / "skills" / "foo").exists()
    assert not (home / ".claude" / "skills" / "foo").exists()


def test_plan_without_recorded_user_roots_must_be_recreated(env):
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    plan = build_plan(store, "m1", home=home)
    legacy = {k: v for k, v in plan.items() if k not in ("plan_id", "user_roots")}
    legacy["plan_id"] = plan_id_for(legacy)
    (store / "state" / "plans" / f"{legacy['plan_id']}.json").write_text(
        json.dumps(legacy)
    )
    with pytest.raises(ValidationError, match="run reconcile again"):
        apply_plan(store, legacy["plan_id"], home=home)


@pytest.mark.parametrize("plan_id", ["../../registry/repositories", "plan-x", ""])
def test_plan_id_must_be_a_plan_id(env, plan_id):
    store, _ = env
    with pytest.raises(ValidationError, match="invalid plan id"):
        apply_plan(store, plan_id)


def test_single_layout_source_applies(env, tmp_path):
    """B6: apply used to stop with `drift: …/.claude/skills exists`."""
    store, home = env
    solo = tmp_path / "solo-origin"
    solo.mkdir()
    (solo / "SKILL.md").write_text("---\nname: solo\ndescription: d\n---\nb\n")
    git("init", "-q", "-b", "main", cwd=solo)
    git("config", "user.email", "t@t", cwd=solo)
    git("config", "user.name", "t", cwd=solo)
    git("add", ".", cwd=solo)
    git("commit", "-q", "-m", "c1", cwd=solo)
    add_source(store, str(solo), source_id="solo")
    set_profile_state(store, "solo", "enabled", targets=["claude"])

    record = apply_plan(store, build_plan(store, "m1", home=home)["plan_id"], home=home)
    assert record["success"] is True
    assert (home / ".claude" / "skills" / "solo" / "SKILL.md").is_file()


def test_single_layout_install_never_exposes_the_checkout_git(env, tmp_path):
    """B6/B9: the release of a single-skill source (path `.`) used to copy
    the checkout's .git, clone URL token included, into the host skill."""
    store, home = env
    solo = tmp_path / "solo-origin"
    solo.mkdir()
    (solo / "SKILL.md").write_text("---\nname: solo\ndescription: d\n---\nb\n")
    git("init", "-q", "-b", "main", cwd=solo)
    git("config", "user.email", "t@t", cwd=solo)
    git("config", "user.name", "t", cwd=solo)
    git("add", ".", cwd=solo)
    git("commit", "-q", "-m", "c1", cwd=solo)
    add_source(store, str(solo), source_id="solo")
    token_url = "https://ghp_SECRETTOKEN@github.com/o/solo.git"
    git("remote", "set-url", "origin", token_url, cwd=store / "sources" / "solo")
    set_profile_state(store, "solo", "enabled", targets=["claude"])

    record = apply_plan(store, build_plan(store, "m1", home=home)["plan_id"], home=home)
    assert record["success"] is True
    installed = home / ".claude" / "skills" / "solo"
    assert sorted(p.name for p in installed.iterdir()) == ["SKILL.md"]
    assert not any(
        "SECRETTOKEN" in p.read_text(errors="replace")
        for p in installed.rglob("*") if p.is_file()
    )


def test_tampered_release_is_never_linked_to_another_host(env, directory_link):
    """B4: an existing release whose content drifted is not trusted as-is."""
    store, home = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    record = apply_plan(store, build_plan(store, "m1", home=home)["plan_id"], home=home)
    assert record["success"] is True
    release = (home / ".claude" / "skills" / "foo").resolve()
    (release / "SKILL.md").chmod(0o644)
    (release / "SKILL.md").write_text("---\nname: foo\n---\ntampered\n")

    (home / ".codex" / "skills").mkdir(parents=True)
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude", "codex"])
    plan = build_plan(store, "m1", home=home)
    assert sorted(op["type"] for op in plan["operations"]) == ["install", "review"]

    with pytest.raises(DriftError, match="modified after it was created"):
        apply_plan(store, plan["plan_id"], home=home)
    assert not (home / ".codex" / "skills" / "foo").exists()
