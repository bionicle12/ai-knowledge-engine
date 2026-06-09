"""Tests for kb_populate.py (lives in knowledge-base/scripts/)."""
from __future__ import annotations

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
        assert "Run ./reindex.sh" in md

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
