"""Tests for the Phase 1 CLI: inventory command, --json, exit codes (spec §17)."""
from __future__ import annotations

import json

from ai_skills_fixer.cli import main


def write_skill(root, rel, name=None, description="Use when testing."):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    name = name if name is not None else d.name
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )
    return d


def setup_machine(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    write_skill(repo, "skills/copied-skill")
    write_skill(home, ".claude/skills/copied-skill")
    write_skill(home, ".claude/skills/local-only")
    write_skill(home, ".codex/skills/copied-skill")
    return home, repo


def test_inventory_json_reports_provenance_and_duplicates(tmp_path, capsys):
    home, repo = setup_machine(tmp_path)
    rc = main(
        ["inventory", "--home", str(home), "--source-repo", str(repo), "--json"]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)

    skills = {(s["host"], s["directory"]): s for s in data["skills"]}
    assert skills[("claude", "copied-skill")]["provenance"]["level"] == "exact"
    assert skills[("claude", "local-only")]["provenance"]["level"] == "unknown"
    assert "copied-skill" in data["duplicates"]
    assert data["summary"]["skills_total"] == 3
    assert data["token_note"].lower().startswith("token")


def test_inventory_human_output_summarizes(tmp_path, capsys):
    home, repo = setup_machine(tmp_path)
    rc = main(["inventory", "--home", str(home), "--source-repo", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "copied-skill" in out
    assert "exact" in out
    assert "duplicate" in out.lower()


def test_missing_source_repo_is_safe_stop(tmp_path, capsys):
    home, _ = setup_machine(tmp_path)
    rc = main(
        ["inventory", "--home", str(home), "--source-repo", str(tmp_path / "nope")]
    )
    assert rc == 2


def test_inventory_without_sources_still_works(tmp_path, capsys):
    home, _ = setup_machine(tmp_path)
    rc = main(["inventory", "--home", str(home), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["skills_total"] == 3
    levels = {s["provenance"]["level"] for s in data["skills"] if s["provenance"]}
    assert levels == {"unknown"}
