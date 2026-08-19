"""Tests for advisory usage-telemetry scanning (spec §14).

Aggregate counts and evidence levels only — never prompt content.
"""
from __future__ import annotations

from ai_skills_fixer.usage import merge_evidence, scan_claude_usage, scan_codex_usage


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


INSTALLED = {"clean-code", "bash-pro", "fastapi-pro", "unused-skill"}


def test_claude_skill_invocation_is_explicit(tmp_path):
    write(
        tmp_path / "projects" / "p1" / "s1.jsonl",
        '{"type":"tool_use","name":"Skill","input":{"skill":"clean-code"}}\n'
        '{"type":"tool_use","name":"Skill","input":{"skill":"clean-code"}}\n'
        '{"type":"tool_use","name":"Skill","input":{"skill":"not-installed"}}\n',
    )
    evidence = scan_claude_usage(tmp_path / "projects", INSTALLED)
    (e,) = [x for x in evidence if x.skill == "clean-code"]
    assert e.level == "explicit"
    assert e.count == 2
    assert e.last_seen is not None
    assert not any(x.skill == "not-installed" for x in evidence)


def test_claude_path_read_is_strong(tmp_path):
    write(
        tmp_path / "projects" / "p1" / "s1.jsonl",
        '{"text":"read /home/u/.claude/skills/bash-pro/SKILL.md ok"}\n',
    )
    evidence = scan_claude_usage(tmp_path / "projects", INSTALLED)
    (e,) = [x for x in evidence if x.skill == "bash-pro"]
    assert e.level == "strong"
    assert e.count == 1


def test_codex_path_mention_is_strong(tmp_path):
    write(
        tmp_path / "sessions" / "2026" / "log.jsonl",
        'loaded /home/u/.codex/skills/fastapi-pro/SKILL.md\n',
    )
    evidence = scan_codex_usage([tmp_path / "sessions"], INSTALLED)
    (e,) = [x for x in evidence if x.skill == "fastapi-pro"]
    assert e.level == "strong"


def test_missing_log_dirs_produce_no_evidence(tmp_path):
    assert scan_claude_usage(tmp_path / "nope", INSTALLED) == []
    assert scan_codex_usage([tmp_path / "nope"], INSTALLED) == []


def test_merge_explicit_beats_strong_and_fills_not_observed(tmp_path):
    write(
        tmp_path / "projects" / "p1" / "s1.jsonl",
        '{"type":"tool_use","name":"Skill","input":{"skill":"clean-code"}}\n'
        '{"text":"/home/u/.claude/skills/clean-code/SKILL.md"}\n'
        '{"text":"/home/u/.claude/skills/bash-pro/SKILL.md"}\n',
    )
    evidence = scan_claude_usage(tmp_path / "projects", INSTALLED)
    merged = merge_evidence(INSTALLED, evidence)
    by_skill = {e.skill: e for e in merged}

    assert by_skill["clean-code"].level == "explicit"
    assert by_skill["bash-pro"].level == "strong"
    assert by_skill["unused-skill"].level == "not-observed"
    assert by_skill["unused-skill"].count == 0
    assert len(merged) == len(INSTALLED)
