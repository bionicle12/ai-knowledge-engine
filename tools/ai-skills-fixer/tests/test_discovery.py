"""Tests for cross-platform host root discovery (spec §8)."""
from __future__ import annotations

from ai_skills_fixer.discovery import discover_roots


def make_dirs(home, rels):
    for rel in rels:
        (home / rel).mkdir(parents=True, exist_ok=True)


def by_host_kind(roots):
    return {(r.host, r.kind): r for r in roots}


def test_discovers_default_user_roots(tmp_path):
    make_dirs(
        tmp_path,
        [".claude/skills", ".codex/skills", ".cursor/skills", ".antigravity/skills"],
    )
    roots = [r for r in discover_roots(home=tmp_path, env={}) if r.exists]
    found = by_host_kind(roots)
    assert found[("claude", "user")].path == tmp_path / ".claude/skills"
    assert found[("codex", "user")].path == tmp_path / ".codex/skills"
    assert found[("cursor", "user")].path == tmp_path / ".cursor/skills"
    assert found[("antigravity", "user")].path == tmp_path / ".antigravity/skills"
    assert found[("claude", "user")].evidence == "default-location-exists"
    assert found[("claude", "user")].confidence == "high"


def test_missing_roots_reported_absent_not_invented(tmp_path):
    roots = discover_roots(home=tmp_path, env={})
    assert roots, "candidates must still be listed"
    assert all(not r.exists for r in roots)


def test_codex_home_env_override(tmp_path):
    alt = tmp_path / "custom-codex"
    (alt / "skills").mkdir(parents=True)
    roots = discover_roots(home=tmp_path, env={"CODEX_HOME": str(alt)})
    codex = [r for r in roots if r.host == "codex" and r.exists]
    assert codex and codex[0].path == alt / "skills"
    assert codex[0].evidence == "env-override"


def test_claude_config_dir_env_override(tmp_path):
    alt = tmp_path / "claude-alt"
    (alt / "skills").mkdir(parents=True)
    roots = discover_roots(home=tmp_path, env={"CLAUDE_CONFIG_DIR": str(alt)})
    claude = [r for r in roots if r.host == "claude" and r.kind == "user" and r.exists]
    assert claude and claude[0].path == alt / "skills"
    assert claude[0].evidence == "env-override"


def test_project_local_claude_root(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".claude" / "skills").mkdir(parents=True)
    roots = discover_roots(home=home, project_dir=project, env={})
    proj = [r for r in roots if r.host == "claude" and r.kind == "project"]
    assert proj and proj[0].exists
    assert proj[0].path == project / ".claude" / "skills"


def test_cursor_system_root_is_separate_kind(tmp_path):
    make_dirs(tmp_path, [".cursor/skills-cursor"])
    roots = discover_roots(home=tmp_path, env={})
    system = [r for r in roots if r.host == "cursor" and r.kind == "system"]
    assert system and system[0].exists


def test_claude_plugin_cache_root(tmp_path):
    make_dirs(tmp_path, [".claude/plugins/cache"])
    roots = discover_roots(home=tmp_path, env={})
    plugin = [r for r in roots if r.host == "claude" and r.kind == "plugin"]
    assert plugin and plugin[0].exists
