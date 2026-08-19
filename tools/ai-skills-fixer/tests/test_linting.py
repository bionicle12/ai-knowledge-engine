"""Tests for structural skill lint (spec §11.1, Phase 1 scope)."""
from __future__ import annotations

from ai_skills_fixer.linting import lint_skill_dir


def make_skill(root, folder="good-skill", name=None, description="Use when testing.",
               body="Short body.\n"):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    name = name if name is not None else folder
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


def checks(findings):
    return {f.check for f in findings}


def test_clean_skill_has_no_findings(tmp_path):
    d = make_skill(tmp_path)
    assert lint_skill_dir(d) == []


def test_missing_frontmatter_is_error(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "SKILL.md").write_text("just text\n", encoding="utf-8")
    findings = lint_skill_dir(d)
    assert any(f.check == "frontmatter" and f.severity == "error" for f in findings)


def test_name_folder_mismatch_is_warning(tmp_path):
    d = make_skill(tmp_path, folder="folder-name", name="different-name")
    findings = lint_skill_dir(d)
    assert any(f.check == "name-folder-mismatch" and f.severity == "warning"
               for f in findings)


def test_nonportable_name_is_warning(tmp_path):
    d = make_skill(tmp_path, folder="bad", name="Bad Name With Spaces")
    assert "portable-name" in checks(lint_skill_dir(d))


def test_missing_description_is_error(tmp_path):
    d = tmp_path / "nodesc"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: nodesc\n---\nbody\n", encoding="utf-8")
    findings = lint_skill_dir(d)
    assert any(f.check == "description-missing" and f.severity == "error"
               for f in findings)


def test_overlong_description_is_warning(tmp_path):
    d = make_skill(tmp_path, folder="longdesc", description="x" * 1100)
    assert "description-length" in checks(lint_skill_dir(d))


def test_broken_relative_link_is_error(tmp_path):
    d = make_skill(tmp_path, body="See [notes](references/missing.md).\n")
    findings = lint_skill_dir(d)
    assert any(f.check == "broken-reference" and f.severity == "error"
               for f in findings)


def test_existing_relative_link_and_http_links_are_fine(tmp_path):
    d = make_skill(
        tmp_path,
        body="See [notes](references/notes.md) and [site](https://example.com).\n",
    )
    (d / "references").mkdir()
    (d / "references" / "notes.md").write_text("n\n", encoding="utf-8")
    assert lint_skill_dir(d) == []


def test_long_body_is_warning(tmp_path):
    d = make_skill(tmp_path, folder="huge", body=("line of text\n" * 2000))
    assert "body-length" in checks(lint_skill_dir(d))
