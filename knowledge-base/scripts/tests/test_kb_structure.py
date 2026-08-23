"""Tests for kb_structure — four init sketches + blind-spot order."""
from __future__ import annotations

from pathlib import Path

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
