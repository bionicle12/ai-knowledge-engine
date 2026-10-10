"""Tests for kb_structure — four init sketches + blind-spot order."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import kb_populate
import kb_structure


REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "knowledge-base" / "examples"


def test_fiction_writer_has_exactly_four_axes():
    path = EXAMPLES / "fiction-writer.yml"
    data = __import__("kb_populate").load_role_yaml(path)
    sketches = kb_structure.variants(data)
    assert [s["id"] for s in sketches] == list(kb_structure.AXES)
    trees = [s["tree"] for s in sketches]
    assert len(set(trees)) == 4
    assert "projects/" in sketches[0]["tree"]
    assert "timelines/" in sketches[2]["tree"]
    assert "decisions/" in sketches[3]["tree"]


def test_yaml_blind_spots_win_over_defaults(tmp_path: Path):
    role = {
        "role": "X",
        "blind_spots": [
            "Where do dead drafts go? (changes knowledge/ layout)",
            "What must never be invented?",
        ],
        "entities": {"voice": {"enabled": True, "knowledge_paths": ["knowledge/voice/a.md"]}},
    }
    spots = kb_structure.blind_spots(role)
    assert spots[0].startswith("Where do dead drafts")
    assert len(spots) == 2
    defaults = kb_structure.default_blind_spots({"role": "X"})
    assert defaults[0].startswith("Where do paused")


def test_write_variants_lands_in_interactions_init(tmp_path: Path):
    path = EXAMPLES / "fiction-writer.yml"
    data = __import__("kb_populate").load_role_yaml(path)
    dest = kb_structure.write_variants(tmp_path, data, source_path=path)
    assert dest == tmp_path / "interactions" / "init" / "STRUCTURE_VARIANTS.md"
    text = dest.read_text(encoding="utf-8")
    assert "## Blind spots" in text
    assert "By project" in text
    assert "By artefact type" in text
    assert "By time" in text
    assert "By decision" in text
    assert "reacts" in text


def test_cli_blind_spots(tmp_path: Path, capsys):
    rc = kb_structure.main(["--role", "fiction-writer", "--blind-spots"])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) >= 3


def _sketch(data: dict, axis: str, **kwargs) -> str:
    return next(s["tree"] for s in kb_structure.variants(data, **kwargs) if s["id"] == axis)


def test_dated_sketches_follow_the_current_date():
    # G:L8: the sketches had "2026/", "2025/" and "2026-08__example.md" baked in.
    data = kb_populate.load_role_yaml(EXAMPLES / "fiction-writer.yml")
    later = dt.date(2031, 3, 1)
    time_tree = _sketch(data, "time", today=later)
    decisions_tree = _sketch(data, "decisions", today=later)
    assert "    2031/" in time_tree and "    2030/" in time_tree
    assert "2031-03__example.md" in decisions_tree
    assert "2026" not in time_tree + decisions_tree
    assert f"    {dt.date.today().year}/" in _sketch(data, "time")


def test_project_sketch_does_not_turn_entities_into_projects():
    # E: "by project" put every entity under projects/, e.g. projects/projects/.
    data = kb_populate.load_role_yaml(EXAMPLES / "programmer-senior.yml")
    assert {"projects", "tech_stack"} <= set(data["entities"])
    tree = _sketch(data, "projects")
    assert "    projects/" not in tree
    assert "tech-stack" not in tree
    assert "<project-a>/" in tree


def test_cli_finds_a_custom_role_by_title_in_the_base(tmp_path: Path, capsys):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "night-baker.yml").write_text(
        'role: "Night baker"\nblind_spots: ["Where do failed batches go?"]\n',
        encoding="utf-8",
    )
    rc = kb_structure.main(["--role", "Night baker", "--blind-spots", "--kb-root", str(tmp_path)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "Where do failed batches go?"


def test_cli_defaults_the_kb_root_to_the_cwd(tmp_path: Path, capsys, monkeypatch):
    # Review: kb_populate found ./examples/<custom>.yml without --kb-root,
    # kb_structure did not.
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "my-custom.yml").write_text(
        'role: "My Custom Role"\nblind_spots: ["What gets thrown away?"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert kb_structure.main(["--role", "My Custom Role", "--blind-spots"]) == 0
    assert capsys.readouterr().out.strip() == "What gets thrown away?"
