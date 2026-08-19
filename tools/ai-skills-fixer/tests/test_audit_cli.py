"""Tests for the deterministic audit command (spec §11, §17)."""
from __future__ import annotations

import json

from ai_skills_fixer.cli import main
from ai_skills_fixer.store import init_store


def write_skill(home, name, body):
    d = home / ".claude" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n{body}",
        encoding="utf-8",
    )


BOILERPLATE = (
    "Follow the standard operating procedure documented here in enough "
    "detail that it applies to every single skill in exactly the same way."
)


def setup_home(tmp_path):
    home = tmp_path / "home"
    write_skill(
        home, "relic-skill",
        "You MUST always think step by step.\nOptimized for GPT-4.\n\n"
        f"{BOILERPLATE}\n",
    )
    write_skill(home, "clean-skill", f"Specific instructions only.\n\n{BOILERPLATE}\n")
    return home


def test_audit_json_reports_lint_and_debt_signals(tmp_path, capsys):
    home = setup_home(tmp_path)
    rc = main(["audit", "--home", str(home), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)

    relic = next(s for s in data["skills"] if s["skill"] == "relic-skill")
    kinds = {sig["signal"] for sig in relic["debt_signals"]}
    assert {"absolute-rule", "generic-prompting", "model-reference"} <= kinds

    assert data["summary"]["skills_audited"] == 2
    assert data["summary"]["signals_by_type"]["model-reference"] >= 1


def test_audit_finds_cross_skill_boilerplate(tmp_path, capsys):
    home = setup_home(tmp_path)
    main(["audit", "--home", str(home), "--json"])
    data = json.loads(capsys.readouterr().out)
    (shared,) = data["cross_skill_duplicates"]
    assert sorted(shared["skills"]) == ["clean-skill", "relic-skill"]


def test_audit_filters_by_skill_name(tmp_path, capsys):
    home = setup_home(tmp_path)
    rc = main(["audit", "clean-skill", "--home", str(home), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["skill"] for s in data["skills"]] == ["clean-skill"]


def test_audit_persists_reports_into_store(tmp_path, capsys):
    home = setup_home(tmp_path)
    store = tmp_path / "store"
    init_store(store, machine="m1")

    rc = main(["audit", "--home", str(home), "--store-root", str(store), "--json"])
    assert rc == 0
    reports = list((store / "state" / "reports").iterdir())
    suffixes = {p.suffix for p in reports}
    assert suffixes == {".json", ".md"}


def test_usage_command_reports_evidence_and_disclosure(tmp_path, capsys):
    home = setup_home(tmp_path)
    (home / ".claude" / "projects" / "p1").mkdir(parents=True)
    (home / ".claude" / "projects" / "p1" / "s.jsonl").write_text(
        '{"type":"tool_use","name":"Skill","input":{"skill":"relic-skill"}}\n',
        encoding="utf-8",
    )

    rc = main(["usage", "--home", str(home), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)

    by_skill = {e["skill"]: e for e in data["skills"]}
    assert by_skill["relic-skill"]["level"] == "explicit"
    assert by_skill["clean-skill"]["level"] == "not-observed"
    assert any("projects" in p for p in data["scanned"])
    assert "not-observed" in data["note"]


def test_audit_notes_missing_model_guidance(tmp_path, capsys):
    home = setup_home(tmp_path)
    store = tmp_path / "store"
    init_store(store, machine="m1")
    main(["audit", "--home", str(home), "--store-root", str(store), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["model_guidance"]["entries"] == []
    assert "research" in data["model_guidance"]["note"]
