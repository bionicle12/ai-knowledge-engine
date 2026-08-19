"""End-to-end CLI tests for apply and rollback (spec §17)."""
from __future__ import annotations

import json
import shutil
import subprocess

from ai_skills_fixer.cli import main


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


def setup(tmp_path, capsys):
    store = tmp_path / "store"
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    base = ["--store-root", str(store)]
    main(["init", *base, "--machine-id", "m1"])
    main(["source", "add", str(origin), *base])
    capsys.readouterr()
    return store, origin, home, base


def test_cli_adopt_apply_and_rollback_flow(tmp_path, capsys):
    store, _, home, base = setup(tmp_path, capsys)
    dest = home / ".claude" / "skills" / "foo"
    shutil.copytree(store / "sources" / "origin-repo" / "skills" / "foo", dest)

    main(["profile", "set", "origin-repo:foo", "enabled", "--targets", "claude", *base])
    capsys.readouterr()
    main(["reconcile", *base, "--machine-id", "m1", "--home", str(home), "--json"])
    plan = json.loads(capsys.readouterr().out)

    rc = main(["reconcile", *base, "--apply", plan["plan_id"], "--json"])
    assert rc == 0
    record = json.loads(capsys.readouterr().out)
    assert record["success"] is True
    assert dest.is_symlink()

    rc = main(["rollback", record["apply_id"], *base])
    assert rc == 0
    assert not dest.is_symlink() and dest.is_dir()


def test_cli_apply_drift_returns_3(tmp_path, capsys):
    store, _, home, base = setup(tmp_path, capsys)
    main(["profile", "set", "origin-repo:foo", "enabled", "--targets", "claude", *base])
    capsys.readouterr()
    main(["reconcile", *base, "--machine-id", "m1", "--home", str(home), "--json"])
    plan = json.loads(capsys.readouterr().out)

    main(["profile", "set", "origin-repo:bar", "enabled", "--targets", "claude", *base])
    capsys.readouterr()

    rc = main(["reconcile", *base, "--apply", plan["plan_id"]])
    assert rc == 3


def test_cli_rollback_unknown_apply_id_is_safe_stop(tmp_path, capsys):
    store, _, _, base = setup(tmp_path, capsys)
    rc = main(["rollback", "plan-x.apply-20260101T000000Z", *base])
    assert rc == 2
