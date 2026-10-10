"""Tests for structural skill lint (spec §11.1, Phase 1 scope)."""
from __future__ import annotations

from ai_skills_fixer.filesystem import unsafe_symlinks
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


def test_symlink_leaving_the_skill_is_error(tmp_path):
    """B8: `reference.md -> ~/.ssh/id_test` must not audit as clean."""
    d = make_skill(tmp_path)
    secret = tmp_path / "id_test"
    secret.write_text("PRIVATE KEY\n", encoding="utf-8")
    (d / "reference.md").symlink_to(secret)
    (d / "up.md").symlink_to("../id_test")
    (d / "inside.md").symlink_to("SKILL.md")

    findings = [f for f in lint_skill_dir(d) if f.check == "unsafe-symlink"]
    assert {f.severity for f in findings} == {"error"}
    messages = " ".join(f.message for f in findings)
    assert "reference.md ->" in messages and "up.md -> ../id_test" in messages
    assert "inside.md" not in messages


def test_unsafe_symlink_is_reported_even_with_broken_frontmatter(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "SKILL.md").write_text("just text\n", encoding="utf-8")
    (d / "key").symlink_to("/etc/hostname")
    assert "unsafe-symlink" in checks(lint_skill_dir(d))


def test_symlink_chain_escaping_only_after_a_link_is_error(tmp_path):
    """B8 bypass: each link looks safe on its own (`x -> .`, `up1 -> x/..`),
    but the OS resolves `reference.md` outside the skill."""
    outside = tmp_path / "outside" / ".ssh"
    outside.mkdir(parents=True)
    (outside / "id_test").write_text("SECRETKEY\n", encoding="utf-8")
    d = make_skill(tmp_path / "skills", folder="evil")
    (d / "x").symlink_to(".")
    (d / "up1").symlink_to("x/..")
    (d / "up2").symlink_to("up1/..")
    (d / "reference.md").symlink_to("up2/outside/.ssh/id_test")
    assert (d / "reference.md").read_text() == "SECRETKEY\n"  # the OS agrees

    unsafe = unsafe_symlinks(d)
    assert "reference.md -> up2/outside/.ssh/id_test" in unsafe
    assert "up1 -> x/.." in unsafe and "up2 -> up1/.." in unsafe
    assert "x -> ." not in unsafe  # a link to the skill itself stays inside
    assert "unsafe-symlink" in checks(lint_skill_dir(d))


def test_links_resolving_inside_the_skill_stay_clean(tmp_path):
    d = make_skill(tmp_path)
    (d / "sub").mkdir()
    (d / "sub" / "b.md").write_text("b\n", encoding="utf-8")
    (d / "x").symlink_to(".")
    (d / "via-self.md").symlink_to("x/sub/b.md")
    (d / "sub" / "up.md").symlink_to("../SKILL.md")
    (d / "dirlink").symlink_to("sub")
    (d / "back.md").symlink_to("dirlink/../SKILL.md")
    assert unsafe_symlinks(d) == []


def test_symlink_loop_is_error(tmp_path):
    d = make_skill(tmp_path)
    (d / "a").symlink_to("b")
    (d / "b").symlink_to("a")
    assert unsafe_symlinks(d) == ["a -> b", "b -> a"]
