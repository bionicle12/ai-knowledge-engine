"""Tests for the Phase 1 CLI: inventory command, --json, exit codes (spec §17)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ai_skills_fixer.cli import main

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
SPEC_MD = (
    Path(__file__).resolve().parents[3]
    / "docs" / "superpowers" / "specs" / "2026-08-19-ai-skills-fixer-design.md"
)


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


def test_skill_md_lists_only_commands_the_cli_has(capsys):
    """B9: the spec's `eval` command does not exist; SKILL.md must not
    present it (or any other missing command) as available."""
    text = SKILL_MD.read_text(encoding="utf-8")
    section = text.split("## Commands", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^- `([a-z]+)", section, re.M))
    assert {"inventory", "source", "reconcile", "rollback", "eval"} <= documented

    for command in sorted(documented - {"eval"}):
        with pytest.raises(SystemExit) as info:
            main([command, "--help"])
        assert info.value.code == 0, command
    with pytest.raises(SystemExit) as info:
        main(["eval", "--help"])
    assert info.value.code == 2
    capsys.readouterr()
    assert re.search(r"`eval`[^\n]*is not implemented", section)


def test_spec_marks_eval_unimplemented_and_states_the_apply_guards():
    """B9/B5/B8: the design spec listed `eval` as a core command and left out
    the release and apply guards the code enforces."""
    if not SPEC_MD.is_file():
        pytest.skip("design spec is not next to the tool (installed copy)")
    spec = " ".join(SPEC_MD.read_text(encoding="utf-8").split())
    assert "ai-skills-fixer eval <skill-id> # Phase 5 (§16, §22) — not implemented yet" in spec
    assert "`.git` folders are never copied into them" in spec
    assert "installed into host roots under a folder named `<source-id>`" in spec
    from ai_skills_fixer.sources import SOURCE_ID_RE

    assert f"matching `{SOURCE_ID_RE.pattern}`" in spec
    assert "must equal the user roots discovered at apply time" in spec
    assert "The apply record is a write-ahead journal" in spec
