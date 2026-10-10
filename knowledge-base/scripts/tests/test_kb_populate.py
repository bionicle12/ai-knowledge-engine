"""Tests for kb_populate.py (lives in knowledge-base/scripts/)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import kb_populate as kp


# Test file is at knowledge-base/scripts/tests/test_kb_populate.py
# REPO_ROOT (source-repo root) is three levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]

REQUESTED_ROLE_TEMPLATES = {
    "psychologist-gestalt.yml": "Gestalt-oriented psychologist",
    "music-video-director.yml": "Music video writer-director",
    "battle-rap-producer.yml": "Battle rap producer & lyricist",
    "viral-short-form-veo.yml": "Viral short-form video director (TikTok / Veo3)",
    "russian-software-engineering-student.yml": "Software engineering student in Russia",
    "startup-opportunity-explorer.yml": "Startup Opportunity Explorer",
}


@pytest.fixture()
def minimal_role(tmp_path: Path) -> Path:
    p = tmp_path / "test-role.yml"
    p.write_text(
        """
role: "Test role"
description: "Just a test."
placement_examples:
  intro: "Test intro paragraph."
  by_artifact:
    - artifact: "ADR"
      destination: "raw/reference/unsorted/"
      examples:
        - "adr-001.md"
      knowledge_target: "knowledge/decisions/"
      tip: "ADRs land in decisions"
    - artifact: "Postmortems"
      destination: "raw/work/unsorted/"
      examples:
        - "postmortem-2026-05-15.md"
      knowledge_target: "knowledge/playbooks/debugging.md"
  quickstart:
    - "Drop README → raw/reference/unsorted/"
    - "Run reindex"
  do_not_drop:
    - "API keys"
""".strip(),
        encoding="utf-8",
    )
    return p


def test_resolve_role_path_finds_built_in(monkeypatch, tmp_path: Path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "demo.yml").write_text("role: demo", encoding="utf-8")
    monkeypatch.setattr(kp, "EXAMPLES_DIR", examples)
    p = kp.resolve_role_path("demo", None)
    assert p.is_file()
    assert p.name == "demo.yml"


def test_resolve_role_path_via_from(tmp_path: Path):
    p = tmp_path / "custom.yml"
    p.write_text("role: custom", encoding="utf-8")
    out = kp.resolve_role_path(None, p)
    assert out.resolve() == p.resolve()


def test_resolve_role_path_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(kp, "EXAMPLES_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        kp.resolve_role_path("nonexistent", None)


def test_load_role_yaml_basic(minimal_role: Path):
    data = kp.load_role_yaml(minimal_role)
    assert data["role"] == "Test role"
    assert "placement_examples" in data


def test_load_role_yaml_invalid(tmp_path: Path):
    p = tmp_path / "bad.yml"
    p.write_text("- list at top level\n", encoding="utf-8")
    with pytest.raises(ValueError):
        kp.load_role_yaml(p)


def test_easter_egg_role_never_deploys(tmp_path: Path, capsys):
    """The balabanov-director role must joke and exit without writing anything."""
    egg = REPO_ROOT / "knowledge-base" / "examples" / "balabanov-director.yml"
    assert egg.is_file()

    rc = kp.main(["--from", str(egg), "--kb-root", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "шутник" in out
    assert "comedian" in out
    # Nothing deployed: no DATA_PLACEMENT_EXAMPLES.md, no samples, no folders.
    assert list(tmp_path.iterdir()) == []


def test_render_markdown_includes_role_title(minimal_role: Path):
    data = kp.load_role_yaml(minimal_role)
    md = kp.render_markdown(data, source_path=minimal_role)
    assert md.startswith("# Data Placement Examples — Test role")


def test_render_markdown_has_all_sections(minimal_role: Path):
    data = kp.load_role_yaml(minimal_role)
    md = kp.render_markdown(data, source_path=minimal_role)
    assert "Why this file" in md
    assert "You have → put it in (generic)" in md
    assert "Adding files through chat" in md
    assert "Role-specific quick map" in md
    assert "Role-specific examples" in md
    assert "5-minute quickstart" in md
    assert "Do NOT drop" in md
    assert "Next steps" in md


def test_render_markdown_lists_artifacts(minimal_role: Path):
    data = kp.load_role_yaml(minimal_role)
    md = kp.render_markdown(data, source_path=minimal_role)
    assert "### ADR" in md
    assert "### Postmortems" in md
    assert "adr-001.md" in md
    assert "postmortem-2026-05-15.md" in md
    # Tips and knowledge targets show up
    assert "ADRs land in decisions" in md
    assert "knowledge/decisions/" in md


def test_render_markdown_handles_missing_optional_fields(tmp_path: Path):
    p = tmp_path / "minimal.yml"
    p.write_text(
        """
role: "Bare role"
placement_examples:
  by_artifact:
    - artifact: "Only this"
      destination: "raw/unsorted/"
""".strip(),
        encoding="utf-8",
    )
    data = kp.load_role_yaml(p)
    md = kp.render_markdown(data, source_path=p)
    # No intro, no quickstart, no don't-drop — must not crash
    assert "Only this" in md
    assert "raw/unsorted/" in md


def test_render_markdown_invalid_placement_examples_type(tmp_path: Path):
    p = tmp_path / "bad.yml"
    p.write_text("role: x\nplacement_examples: 'wrong type'\n", encoding="utf-8")
    data = kp.load_role_yaml(p)
    with pytest.raises(ValueError):
        kp.render_markdown(data, source_path=p)


def test_main_dry_run_prints_to_stdout(minimal_role: Path, capsys, tmp_path: Path):
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(tmp_path),
        "--dry-run",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Test role" in out
    # Output file should not exist
    assert not (tmp_path / "DATA_PLACEMENT_EXAMPLES.md").exists()


def test_main_writes_file(minimal_role: Path, tmp_path: Path):
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(tmp_path),
    ])
    assert code == 0
    output = tmp_path / "DATA_PLACEMENT_EXAMPLES.md"
    assert output.is_file()
    content = output.read_text(encoding="utf-8")
    assert "Test role" in content
    assert "adr-001.md" in content


def test_main_custom_output_name(minimal_role: Path, tmp_path: Path):
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(tmp_path),
        "--output", "PLACEMENT.md",
    ])
    assert code == 0
    assert (tmp_path / "PLACEMENT.md").is_file()
    assert not (tmp_path / "DATA_PLACEMENT_EXAMPLES.md").exists()


def test_main_create_samples(minimal_role: Path, tmp_path: Path):
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(tmp_path),
        "--create-samples",
    ])
    assert code == 0
    samples_dir = tmp_path / "raw" / "_samples"
    assert samples_dir.is_dir()
    sample_files = list(samples_dir.glob("*.example.md"))
    # Two artifacts → two samples
    assert len(sample_files) == 2
    # README in samples folder
    assert (samples_dir / "README.md").is_file()
    # Sample content references the artifact
    adr_sample = next(p for p in sample_files if "adr" in p.name.lower())
    assert "ADR" in adr_sample.read_text(encoding="utf-8")


def test_main_missing_placement_examples(tmp_path: Path):
    p = tmp_path / "no-pe.yml"
    p.write_text("role: noop\n", encoding="utf-8")
    code = kp.main(["--from", str(p), "--kb-root", str(tmp_path)])
    assert code == 1


def test_main_role_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(kp, "EXAMPLES_DIR", tmp_path)
    code = kp.main(["--role", "ghost", "--kb-root", str(tmp_path)])
    assert code == 1


def test_main_kb_root_must_exist(minimal_role: Path, tmp_path: Path):
    fake = tmp_path / "ghost"
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(fake),
    ])
    assert code == 2


def test_main_json_output(minimal_role: Path, tmp_path: Path, capsys):
    code = kp.main([
        "--from", str(minimal_role),
        "--kb-root", str(tmp_path),
        "--json",
    ])
    assert code == 0
    out = capsys.readouterr().out
    import json
    data = json.loads(out)
    assert "written" in data
    assert "markdown_length" in data
    assert data["markdown_length"] > 100


# Integration: every real role template should populate without errors

def test_requested_role_templates_ship_with_population_data():
    """Requested built-in roles should be complete role YAMLs, not stubs."""
    examples_dir = REPO_ROOT / "knowledge-base" / "examples"
    for filename, role_title in REQUESTED_ROLE_TEMPLATES.items():
        role_path = examples_dir / filename
        assert role_path.is_file()

        data = kp.load_role_yaml(role_path)
        assert data["role"] == role_title
        assert len(data.get("entities") or {}) >= 5
        assert len(data.get("raw_data_examples") or []) >= 5
        assert len(data.get("ai_assistant_tasks") or []) >= 5

        placement = data.get("placement_examples") or {}
        assert len(placement.get("by_artifact") or []) >= 5
        assert len(placement.get("quickstart") or []) >= 4
        assert len(placement.get("do_not_drop") or []) >= 4

        md = kp.render_markdown(data, source_path=role_path)
        assert role_title in md
        assert "Role-specific examples" in md
        assert "Run ./shell/reindex.sh" in md

def _real_role_files() -> list[Path]:
    return sorted((REPO_ROOT / "knowledge-base" / "examples").glob("*.yml"))


@pytest.mark.parametrize("role_path", _real_role_files(), ids=lambda p: p.stem)
def test_real_role_templates_render(role_path: Path):
    """Every shipped role template must produce valid markdown."""
    data = kp.load_role_yaml(role_path)
    if not data.get("placement_examples"):
        pytest.skip(f"{role_path.name} has no placement_examples")
    md = kp.render_markdown(data, source_path=role_path)
    assert "# Data Placement Examples" in md
    assert "## You have → put it in" in md


# ---------------------------------------------------------------------------
# Re-runs keep the agent's notes (G:M9 / E-H5)
# ---------------------------------------------------------------------------

LEGACY_FILE = """\
# Data Placement Examples — Test role

> Generated by `kb_populate.py` on 2026-01-01 from `test-role.yml`.

## Next steps

4. Open `.repomix/output.xml` once the AI has indexed your knowledge

If something feels off, edit the source YAML and re-run `python3 scripts/kb_populate.py --role <role>`.

## Project notes

- Drop the highway-clicker README first
"""


def test_rerun_keeps_legacy_project_notes(minimal_role: Path, tmp_path: Path):
    out = tmp_path / "DATA_PLACEMENT_EXAMPLES.md"
    out.write_text(LEGACY_FILE, encoding="utf-8")

    assert kp.main(["--from", str(minimal_role), "--kb-root", str(tmp_path)]) == 0

    text = out.read_text(encoding="utf-8")
    assert text.count("## Project notes") == 1
    assert "- Drop the highway-clicker README first" in text
    assert "adr-001.md" in text  # generated part refreshed
    assert text.index(kp.END_MARKER) < text.index("## Project notes")
    assert "2026-01-01" not in text


def test_notes_below_the_marker_survive_reruns(minimal_role: Path, tmp_path: Path):
    args = ["--from", str(minimal_role), "--kb-root", str(tmp_path)]
    out = tmp_path / "DATA_PLACEMENT_EXAMPLES.md"
    assert kp.main(args) == 0
    assert out.read_text(encoding="utf-8").rstrip().endswith(kp.END_MARKER)
    with out.open("a", encoding="utf-8") as fh:
        fh.write("\n## Project notes\n\n- Stack is Rust + React\n")

    assert kp.main(args) == 0
    once = out.read_text(encoding="utf-8")
    assert kp.main(args) == 0
    assert out.read_text(encoding="utf-8") == once
    assert once.count("- Stack is Rust + React") == 1


def test_template_skeleton_is_replaced_entirely(minimal_role: Path, tmp_path: Path):
    skeleton = REPO_ROOT / "knowledge-base" / "templates" / "DATA_PLACEMENT_EXAMPLES.md.template"
    out = tmp_path / "DATA_PLACEMENT_EXAMPLES.md"
    out.write_text(skeleton.read_text(encoding="utf-8"), encoding="utf-8")
    assert kp.main(["--from", str(minimal_role), "--kb-root", str(tmp_path)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "{{" not in text
    assert text.rstrip().endswith(kp.END_MARKER)


def test_populate_is_logged_in_a_real_base(minimal_role: Path, tmp_path: Path):
    # 14_INITIAL_POPULATION.md promises `populate | DATA_PLACEMENT_EXAMPLES generated`.
    (tmp_path / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    assert kp.main(["--from", str(minimal_role), "--kb-root", str(tmp_path)]) == 0
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "] populate | DATA_PLACEMENT_EXAMPLES generated" in log
    assert "- Role: Test role" in log


def test_populate_does_not_log_outside_a_base(minimal_role: Path, tmp_path: Path):
    assert kp.main(["--from", str(minimal_role), "--kb-root", str(tmp_path)]) == 0
    assert not (tmp_path / "log.md").exists()


def test_footer_does_not_point_at_a_single_index_dump(minimal_role: Path):
    # Pack mode has no `.repomix/output.xml`.
    md = kp.render_markdown(kp.load_role_yaml(minimal_role), source_path=minimal_role)
    assert "output.xml" not in md
    assert "!review" in md


def test_skeleton_template_points_at_runtime_docs():
    # D5: a deployed base keeps the modules in kb-docs/.
    import re

    text = (REPO_ROOT / "knowledge-base" / "templates"
            / "DATA_PLACEMENT_EXAMPLES.md.template").read_text(encoding="utf-8")
    refs = re.findall(r"(\S*?)(\d\d_[A-Z_]+\.md)", text)
    assert refs
    assert all(prefix.endswith("kb-docs/") for prefix, _name in refs), refs
    assert "output.xml" not in text


# ---------------------------------------------------------------------------
# Role by title or slug (I13)
# ---------------------------------------------------------------------------


@pytest.fixture()
def examples(monkeypatch, tmp_path: Path, minimal_role: Path) -> Path:
    folder = tmp_path / "engine-examples"
    folder.mkdir()
    (folder / "test-role.yml").write_text(minimal_role.read_text(encoding="utf-8"),
                                          encoding="utf-8")
    monkeypatch.setattr(kp, "EXAMPLES_DIR", folder)
    return folder


@pytest.mark.parametrize(
    "given", ["test-role", "Test role", "  TEST ROLE ", "test-role.yml", "test-role.YAML"]
)
def test_role_resolves_by_slug_or_title(examples: Path, given: str):
    assert kp.resolve_role_path(given, None) == examples / "test-role.yml"


def test_unknown_role_lists_known_roles(examples: Path):
    with pytest.raises(FileNotFoundError, match="test-role"):
        kp.resolve_role_path("Astronaut", None)


def test_role_defaults_to_roles_primary_from_config(examples: Path, tmp_path: Path):
    # `!populate` works from the title stored in knowledge_base.roles.primary.
    base = tmp_path / "base"
    base.mkdir()
    (base / "kb.config.yml").write_text(
        'knowledge_base:\n  name: t\n  roles:\n    primary: "Test role"\n',
        encoding="utf-8",
    )
    assert kp.main(["--kb-root", str(base)]) == 0
    assert "adr-001.md" in (base / "DATA_PLACEMENT_EXAMPLES.md").read_text(encoding="utf-8")


def test_unmatched_roles_primary_says_where_the_role_came_from(
    examples: Path, tmp_path: Path, capsys
):
    # I13: a custom title in roles.primary with no YAML behind it.
    (tmp_path / "kb.config.yml").write_text(
        'knowledge_base:\n  roles:\n    primary: "Staff Engineer"\n', encoding="utf-8"
    )
    assert kp.main(["--kb-root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "Known roles: test-role" in err
    assert "knowledge_base.roles.primary ('Staff Engineer')" in err
    assert not (tmp_path / "DATA_PLACEMENT_EXAMPLES.md").exists()


def test_missing_role_and_unset_primary_is_a_usage_error(examples: Path, tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        'knowledge_base:\n  roles:\n    primary: "{{PRIMARY_ROLE}}"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit) as exc:
        kp.main(["--kb-root", str(tmp_path)])
    assert exc.value.code == 2


def test_custom_role_in_the_base_examples_is_found(examples: Path, tmp_path: Path):
    # 14 Path B stores the custom YAML in the base's examples/, while the
    # script may run from setup/ (another examples/ folder).
    base = tmp_path / "base"
    (base / "examples").mkdir(parents=True)
    custom = base / "examples" / "night-baker.yml"
    custom.write_text(
        'role: "Night baker"\nplacement_examples:\n  by_artifact:\n'
        '    - artifact: "Recipe card"\n      destination: "raw/documents/unsorted/"\n',
        encoding="utf-8",
    )
    assert kp.resolve_role_path("night-baker", None, kb_root=base) == custom
    assert kp.main(["--role", "Night baker", "--kb-root", str(base)]) == 0
    assert "Recipe card" in (base / "DATA_PLACEMENT_EXAMPLES.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# --entities-from (E friction: "copy entities from examples" had no helper)
# ---------------------------------------------------------------------------

CONFIG_WITH_COMMENTS = """\
# My base — hand-edited
knowledge_base:
  name: "my-kb"          # keep this comment
  roles:
    primary: "Senior Software Engineer"

# Entities to track
entities: {}   # filled at deployment

ingest:
  max_file_mb: 50
"""


def test_entities_from_copies_role_entities_into_config(tmp_path: Path, capsys):
    config = tmp_path / "kb.config.yml"
    config.write_text(CONFIG_WITH_COMMENTS, encoding="utf-8")

    assert kp.main(["--entities-from", "programmer-senior", "--kb-root", str(tmp_path)]) == 0

    text = config.read_text(encoding="utf-8")
    assert '  name: "my-kb"          # keep this comment' in text
    assert "# My base — hand-edited" in text
    data = yaml.safe_load(text)
    role = kp.load_role_yaml(REPO_ROOT / "knowledge-base" / "examples" / "programmer-senior.yml")
    assert data["entities"] == role["entities"]
    assert data["ingest"] == {"max_file_mb": 50}
    assert "Copied 7 entities" in capsys.readouterr().out


def test_entities_from_accepts_a_title_and_keeps_existing_entities(tmp_path: Path, capsys):
    config = tmp_path / "kb.config.yml"
    config.write_text(CONFIG_WITH_COMMENTS, encoding="utf-8")
    args = ["--entities-from", "Senior Software Engineer", "--kb-root", str(tmp_path)]
    assert kp.main(args) == 0
    first = config.read_text(encoding="utf-8")
    capsys.readouterr()

    assert kp.main(args) == 0
    assert config.read_text(encoding="utf-8") == first
    assert "already has entities" in capsys.readouterr().out


def test_entities_from_works_on_the_shipped_config_template(tmp_path: Path):
    template = REPO_ROOT / "knowledge-base" / "templates" / "kb.config.yml.template"
    (tmp_path / "kb.config.yml").write_text(template.read_text(encoding="utf-8"),
                                            encoding="utf-8")
    assert kp.main(["--entities-from", "fiction-writer", "--kb-root", str(tmp_path)]) == 0
    data = yaml.safe_load((tmp_path / "kb.config.yml").read_text(encoding="utf-8"))
    assert "voice" in data["entities"]


def test_entities_from_needs_a_config(tmp_path: Path):
    assert kp.main(["--entities-from", "programmer-senior", "--kb-root", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_entities_from_role_without_entities_fails(tmp_path: Path, minimal_role: Path,
                                                   monkeypatch):
    monkeypatch.setattr(kp, "EXAMPLES_DIR", minimal_role.parent)
    (tmp_path / "kb.config.yml").write_text(CONFIG_WITH_COMMENTS, encoding="utf-8")
    assert kp.main(["--entities-from", "test-role", "--kb-root", str(tmp_path)]) == 1
    assert (tmp_path / "kb.config.yml").read_text(encoding="utf-8") == CONFIG_WITH_COMMENTS


def test_entities_from_dry_run_leaves_the_config_untouched(tmp_path: Path, capsys):
    # Review: --dry-run was ignored and kb.config.yml was rewritten.
    config = tmp_path / "kb.config.yml"
    config.write_text(CONFIG_WITH_COMMENTS, encoding="utf-8")
    args = ["--entities-from", "Senior Software Engineer", "--kb-root", str(tmp_path), "--dry-run"]

    assert kp.main(args) == 0
    assert config.read_text(encoding="utf-8") == CONFIG_WITH_COMMENTS
    out = capsys.readouterr().out
    assert "would copy 7 entities" in out and "nothing written" in out
    assert "entities:\n  tech_stack:" in out

    assert kp.main([*args, "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["would_copy"] is True
    assert summary["copied"] is False
    assert config.read_text(encoding="utf-8") == CONFIG_WITH_COMMENTS
    assert not (tmp_path / "log.md").exists()


def test_entities_from_dry_run_reports_existing_entities(tmp_path: Path, capsys):
    config = tmp_path / "kb.config.yml"
    config.write_text(CONFIG_WITH_COMMENTS, encoding="utf-8")
    assert kp.main(["--entities-from", "programmer-senior", "--kb-root", str(tmp_path)]) == 0
    filled = config.read_text(encoding="utf-8")
    capsys.readouterr()

    args = ["--entities-from", "fiction-writer", "--kb-root", str(tmp_path), "--dry-run"]
    assert kp.main([*args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["would_copy"] is False
    assert kp.main(args) == 0
    assert "nothing would change" in capsys.readouterr().out
    assert config.read_text(encoding="utf-8") == filled


@pytest.mark.parametrize(
    "role_path", [pytest.param(path, id=path.stem) for path in _real_role_files()]
)
def test_real_roles_do_not_point_at_a_single_index_dump(role_path: Path):
    # Pack mode writes .repomix/packs/, never .repomix/output.xml.
    data = kp.load_role_yaml(role_path)
    if data.get("easter_egg"):
        pytest.skip("easter egg")
    assert "output.xml" not in kp.render_markdown(data, source_path=role_path)
