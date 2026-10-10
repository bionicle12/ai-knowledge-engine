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


def make_single_repo(path, name="solo"):
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: does {name}\n---\nbody\n",
        encoding="utf-8",
    )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)


def test_excluded_never_quarantines_the_users_own_same_named_skill(env):
    """B2: the user's own `brainstorming` (unknown provenance) must not be
    moved to backups just because `coll:brainstorming` is excluded."""
    store, home, _ = env
    set_profile_state(store, "awesome:bar", "excluded")
    mine = home / ".claude" / "skills" / "bar"
    mine.mkdir()
    (mine / "SKILL.md").write_text("---\nname: bar\ndescription: mine\n---\nmine\n")

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "review"
    assert op["destination"] == str(mine)
    assert "not provably" in plan["notes"]["review_reasons"]["awesome:bar -> claude"]


def test_excluded_skill_without_catalog_entry_is_only_reviewed(env):
    store, home, _ = env
    set_profile_state(store, "gone:bar", "excluded")
    shutil.copytree(
        store / "sources" / "awesome" / "skills" / "bar",
        home / ".claude" / "skills" / "bar",
    )
    plan = build_plan(store, "m1", home=home)
    assert [op["type"] for op in plan["operations"]] == ["review"]


def test_excluded_managed_link_is_quarantined(env, directory_link):
    store, home, _ = env
    set_profile_state(store, "awesome:bar", "excluded")
    src = store / "sources" / "awesome" / "skills" / "bar"
    release = create_release(
        store, "awesome", "bar", src, current_commit(store / "sources" / "awesome")
    )
    directory_link(home / ".claude" / "skills" / "bar", release)

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "quarantine"


def test_release_edited_through_the_host_link_is_review_not_noop(env, directory_link):
    """B4: an edit via ~/.claude/skills/foo/SKILL.md changes the release;
    reconcile must not call that `noop … risk none`."""
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    src = store / "sources" / "awesome" / "skills" / "foo"
    release = create_release(
        store, "awesome", "foo", src, current_commit(store / "sources" / "awesome")
    )
    link = home / ".claude" / "skills" / "foo"
    directory_link(link, release)
    (release / "SKILL.md").chmod(0o644)
    (link / "SKILL.md").write_text("---\nname: foo\n---\nedited via link\n")

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "review" and op["risk"] == "high"
    assert "modified in place" in plan["notes"]["review_reasons"]["awesome:foo -> claude"]


def test_single_layout_source_installs_under_its_source_id(env):
    """B6: `rel_path` is `.` for a single-skill source; the destination used
    to be the skill root itself."""
    store, home, tmp_path = env
    make_single_repo(tmp_path / "solo-origin")
    add_source(store, str(tmp_path / "solo-origin"), source_id="solo")
    set_profile_state(store, "solo", "enabled", targets=["claude"])

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "install"
    assert op["destination"] == str(home / ".claude" / "skills" / "solo")


def test_source_skill_with_escaping_symlink_is_blocked(env):
    """B8: a third-party `reference.md -> ~/.ssh/id_test` is never planned
    for installation."""
    store, home, tmp_path = env
    origin = tmp_path / "evil-origin"
    make_skill_repo(origin, skills=("sneaky",))
    (origin / "skills" / "sneaky" / "reference.md").symlink_to(tmp_path / "id_test")
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "link", cwd=origin)
    add_source(store, str(origin), source_id="evil")
    set_profile_state(store, "evil:sneaky", "enabled", targets=["claude"])

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "review"
    reason = plan["notes"]["review_reasons"]["evil:sneaky -> claude"]
    assert "reference.md ->" in reason


def test_nested_same_named_skill_is_reviewed_not_adopted(env):
    """Mutating ops only target direct children of the user root: a copy
    nested in a user folder must not yield an adopt at a wrong path."""
    store, home, _ = env
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])
    set_profile_state(store, "awesome:bar", "excluded")
    pack = home / ".claude" / "skills" / "my-pack"
    for name in ("foo", "bar"):
        shutil.copytree(store / "sources" / "awesome" / "skills" / name, pack / name)

    plan = build_plan(store, "m1", home=home)
    assert sorted(op["type"] for op in plan["operations"]) == ["review", "review"]
    assert all(op["type"] != "quarantine" for op in plan["operations"])
    assert plan["user_roots"]["claude"] == str(home / ".claude" / "skills")


def test_lock_proposal_never_carries_url_credentials(env):
    """B9: a legacy registry URL with a token is redacted in the plan."""
    store, home, _ = env
    registry = store / "registry" / "repositories.yml"
    text = registry.read_text()
    url = next(line.split("url: ", 1)[1] for line in text.splitlines() if "url: " in line)
    registry.write_text(
        text.replace(url, "https://x-access-token:ghp_SECRET@example.test/o/r.git")
    )
    set_profile_state(store, "awesome:foo", "enabled", targets=["claude"])

    plan = build_plan(store, "m1", home=home)
    (entry,) = plan["lock_proposal"]["skills"]
    assert entry["url"] == "https://example.test/o/r.git"
    saved = store / "state" / "plans" / f"{plan['plan_id']}.json"
    assert "SECRET" not in saved.read_text()


def test_source_skill_with_escaping_symlink_chain_is_blocked(env):
    """B8 bypass: links that each look safe (`x -> .`, `u1 -> x/..`) but
    chain outside the skill used to give a plain `install`."""
    store, home, tmp_path = env
    origin = tmp_path / "chain-origin"
    make_skill_repo(origin, skills=("evil",))
    d = origin / "skills" / "evil"
    (d / "x").symlink_to(".")
    (d / "u1").symlink_to("x/..")
    (d / "u2").symlink_to("u1/..")
    (d / "ref.md").symlink_to("u2/.ssh/id_test")
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "chain", cwd=origin)
    add_source(store, str(origin), source_id="chain")
    set_profile_state(store, "chain:evil", "enabled", targets=["claude"])

    plan = build_plan(store, "m1", home=home)
    (op,) = plan["operations"]
    assert op["type"] == "review"
    reason = plan["notes"]["review_reasons"]["chain:evil -> claude"]
    assert "ref.md -> u2/.ssh/id_test" in reason


def test_source_linking_to_the_users_own_skill_never_quarantines_it(env):
    """B2 via B8: `coll/skills/bar -> ~/.claude/skills/bar` made the source
    skill an exact copy of the user's own skill, so `excluded` moved it."""
    store, home, _ = env
    mine = home / ".claude" / "skills" / "bar"
    mine.mkdir()
    (mine / "SKILL.md").write_text("---\nname: bar\ndescription: mine\n---\nmine\n")
    checkout = store / "sources" / "awesome"
    shutil.rmtree(checkout / "skills" / "bar")
    (checkout / "skills" / "bar").symlink_to(mine, target_is_directory=True)
    git("add", "-A", cwd=checkout)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "link",
        cwd=checkout)  # a clean checkout at a new commit, as after promote
    set_profile_state(store, "awesome:bar", "excluded")

    with pytest.raises(CatalogError, match="'skills/bar' resolves outside"):
        build_plan(store, "m1", home=home)
    assert (mine / "SKILL.md").read_text() == "---\nname: bar\ndescription: mine\n---\nmine\n"
