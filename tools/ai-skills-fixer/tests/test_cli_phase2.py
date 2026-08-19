"""End-to-end CLI tests for Phase 2 commands (spec §17)."""
from __future__ import annotations

import json
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


def test_full_phase2_flow(tmp_path, capsys):
    store = tmp_path / "store"
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    base = ["--store-root", str(store)]

    assert main(["init", *base, "--machine-id", "m1"]) == 0
    capsys.readouterr()

    assert main(["source", "add", str(origin), *base]) == 0
    capsys.readouterr()

    assert main(["catalog", *base, "--json"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    ids = [s["skill_id"] for s in catalog["skills"]]
    assert "origin-repo:foo" in ids and "origin-repo:bar" in ids

    assert main(
        ["profile", "set", "origin-repo:foo", "enabled", "--targets", "claude", *base]
    ) == 0
    capsys.readouterr()

    assert main(["profile", "show", *base, "--json"]) == 0
    profile = json.loads(capsys.readouterr().out)
    assert profile["skills"][0]["id"] == "origin-repo:foo"

    assert main(
        ["reconcile", *base, "--machine-id", "m1", "--home", str(home), "--json"]
    ) == 0
    plan = json.loads(capsys.readouterr().out)
    (op,) = plan["operations"]
    assert op["type"] == "install"
    assert plan["plan_id"].startswith("plan-")


def test_reconcile_unknown_skill_is_safe_stop(tmp_path, capsys):
    store = tmp_path / "store"
    home = tmp_path / "home"
    home.mkdir()
    base = ["--store-root", str(store)]
    main(["init", *base, "--machine-id", "m1"])
    main(["profile", "set", "ghost:skill", "enabled", "--targets", "claude", *base])
    capsys.readouterr()

    rc = main(["reconcile", *base, "--machine-id", "m1", "--home", str(home)])
    assert rc == 2


def test_source_refresh_reports_candidate(tmp_path, capsys):
    store = tmp_path / "store"
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    base = ["--store-root", str(store)]
    main(["init", *base, "--machine-id", "m1"])
    main(["source", "add", str(origin), *base])
    capsys.readouterr()

    (origin / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nv2\n")
    git("commit", "-aqm", "c2", cwd=origin)

    assert main(["source", "refresh", *base, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["candidates"][0]["changed"] is True


def test_doctor_reports_environment(tmp_path, capsys):
    store = tmp_path / "store"
    base = ["--store-root", str(store)]
    main(["init", *base, "--machine-id", "m1"])
    capsys.readouterr()

    assert main(["doctor", *base, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["store"]["initialized"] is True
    assert out["git"]["available"] is True
