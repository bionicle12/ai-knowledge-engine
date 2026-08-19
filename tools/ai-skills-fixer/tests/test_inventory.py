"""Tests for installed-skill inventory, duplicates, and provenance (spec §9)."""
from __future__ import annotations

from ai_skills_fixer.discovery import SkillRoot
from ai_skills_fixer.inventory import find_duplicates, match_provenance, scan_installed_root
from ai_skills_fixer.sources import scan_source


def write_skill(root, rel, name=None, description="does things", body="body\n"):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    name = name if name is not None else d.name
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


def make_root(path, host="claude", kind="user"):
    path.mkdir(parents=True, exist_ok=True)
    return SkillRoot(
        host=host, path=path, kind=kind, exists=True,
        evidence="default-location-exists", confidence="high",
    )


def test_scan_finds_flat_skills_and_unknown_artifacts(tmp_path):
    root = make_root(tmp_path / "skills")
    write_skill(root.path, "alpha")
    write_skill(root.path, "beta")
    (root.path / "junk-dir").mkdir()

    found = scan_installed_root(root)
    skills = {s.directory: s for s in found}
    assert skills["alpha"].has_skill_md
    assert skills["beta"].has_skill_md
    assert not skills["junk-dir"].has_skill_md
    assert skills["alpha"].name == "alpha"
    assert skills["alpha"].host == "claude"


def test_scan_records_symlink_entry_type(tmp_path):
    target = write_skill(tmp_path / "elsewhere", "linked-skill")
    root = make_root(tmp_path / "skills")
    (root.path / "linked-skill").symlink_to(target)

    (found,) = scan_installed_root(root)
    assert found.entry_type == "symlink"
    assert found.real_path == target.resolve()
    assert found.has_skill_md


def test_scan_descends_into_nested_plugin_layout(tmp_path):
    root = make_root(tmp_path / "cache", kind="plugin")
    write_skill(root.path, "marketplace/plugin/1.0/skills/deep-skill")

    found = scan_installed_root(root)
    deep = [s for s in found if s.has_skill_md]
    assert len(deep) == 1
    assert deep[0].directory == "marketplace/plugin/1.0/skills/deep-skill"


def test_scan_computes_sizes_and_token_estimate(tmp_path):
    root = make_root(tmp_path / "skills")
    write_skill(root.path, "sized", body="word " * 100 + "\n")

    (found,) = scan_installed_root(root)
    assert found.size_bytes > 0
    assert found.file_count == 1
    assert found.skill_md_chars > 500
    assert found.token_estimate > 0


def test_find_duplicates_across_hosts(tmp_path):
    root_a = make_root(tmp_path / "a", host="claude")
    root_b = make_root(tmp_path / "b", host="codex")
    write_skill(root_a.path, "same-skill")
    write_skill(root_b.path, "same-skill")
    write_skill(root_b.path, "unique-skill")

    skills = scan_installed_root(root_a) + scan_installed_root(root_b)
    dupes = find_duplicates(skills)
    assert set(dupes) == {"same-skill"}
    assert {s.host for s in dupes["same-skill"]} == {"claude", "codex"}


def test_provenance_exact_probable_modified_unknown(tmp_path):
    repo = tmp_path / "repo"
    write_skill(repo, "skills/exact-copy")
    write_skill(repo, "skills/renamed-content")
    write_skill(repo, "skills/edited-copy")
    catalog = scan_source("awesome", repo, {"type": "collection", "roots": ["skills"]})

    root = make_root(tmp_path / "installed")
    write_skill(root.path, "exact-copy")
    write_skill(root.path, "other-name", name="renamed-content")
    import shutil
    shutil.copytree(repo / "skills/renamed-content", root.path / "other-name", dirs_exist_ok=True)
    write_skill(root.path, "edited-copy", description="locally changed text")
    write_skill(root.path, "nowhere-else")

    skills = scan_installed_root(root)
    match_provenance(skills, catalog)
    by_dir = {s.directory: s for s in skills}

    assert by_dir["exact-copy"].provenance["level"] == "exact"
    assert by_dir["exact-copy"].provenance["skill_id"] == "awesome:exact-copy"
    assert by_dir["other-name"].provenance["level"] == "probable"
    assert by_dir["edited-copy"].provenance["level"] == "modified-copy"
    assert by_dir["nowhere-else"].provenance["level"] == "unknown"


def test_plugin_and_system_roots_are_not_name_matched(tmp_path):
    repo = tmp_path / "repo"
    write_skill(repo, "skills/shared-name")
    catalog = scan_source("awesome", repo, {"type": "collection", "roots": ["skills"]})

    plugin_root = make_root(tmp_path / "plugins", host="claude", kind="plugin")
    write_skill(
        plugin_root.path,
        "market/plug/1.0/skills/shared-name",
        description="totally different plugin skill",
    )
    system_root = make_root(tmp_path / "system", host="cursor", kind="system")
    write_skill(system_root.path, "shared-name", description="cursor system skill")

    skills = scan_installed_root(plugin_root) + scan_installed_root(system_root)
    match_provenance(skills, catalog)
    assert all((s.provenance or {}).get("level") == "unknown" for s in skills), (
        "plugin/system-managed skills must not become modified-copy by name collision"
    )


def test_codex_dot_system_subtree_is_system_kind(tmp_path):
    root = make_root(tmp_path / "codex-skills", host="codex")
    write_skill(root.path, ".system/skill-creator")
    write_skill(root.path, "normal-skill")
    found = {s.directory: s for s in scan_installed_root(root)}
    assert found[".system/skill-creator"].root_kind == "system"
    assert found["normal-skill"].root_kind == "user"


def test_offline_git_facts_are_recorded(tmp_path):
    root = make_root(tmp_path / "clone" / "skills")
    write_skill(root.path, "in-repo")
    git_dir = tmp_path / "clone" / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:example/clone.git\n'
    )

    (found,) = scan_installed_root(root)
    assert found.git is not None
    assert found.git["commit"] == "a" * 40
    assert found.git["remote"] == "git@github.com:example/clone.git"
