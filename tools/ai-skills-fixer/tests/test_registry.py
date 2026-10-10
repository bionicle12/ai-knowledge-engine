"""Tests for the source registry and source add/refresh (spec §7.1, §7.4)."""
from __future__ import annotations

import json
import subprocess

import pytest

from ai_skills_fixer import sources
from ai_skills_fixer.sources import (
    CatalogError, _default_source_id, add_source, load_registry, refresh_source,
    source_checkout,
)
from ai_skills_fixer.store import init_store


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_skill_repo(path, skills=("foo",)):
    for skill in skills:
        d = path / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: does {skill}\n---\nbody\n",
            encoding="utf-8",
        )
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "user.email", "t@t", cwd=path)
    git("config", "user.name", "t", cwd=path)
    git("add", ".", cwd=path)
    git("commit", "-q", "-m", "c1", cwd=path)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    init_store(root, machine="test-machine")
    return root


def test_add_source_clones_and_registers(store, tmp_path):
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)

    spec = add_source(store, str(origin))
    assert spec.source_id == "origin-repo"
    assert spec.ref == "main"
    assert spec.layout == {"type": "collection", "roots": ["skills"]}
    assert (store / "sources" / "origin-repo" / "skills" / "foo" / "SKILL.md").is_file()

    registry = load_registry(store)
    assert registry["origin-repo"].url == str(origin)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("/srv/skills/origin-repo", "origin-repo"),
        (r"C:\skills\origin-repo", "origin-repo"),
        (r"C:\skills\origin-repo.git", "origin-repo"),
        ("https://example.test/team/origin-repo.git", "origin-repo"),
        ("https://example.test/team/My_Skills.git", "my_skills"),
        ("git@example.test:Team Skills.git", "team-skills"),
    ],
)
def test_default_source_id_accepts_portable_path_separators(location, expected):
    assert _default_source_id(location) == expected


def test_add_source_with_explicit_id_and_ref(store, tmp_path):
    origin = tmp_path / "origin"
    first = make_skill_repo(origin)
    (origin / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nv2\n")
    git("commit", "-aqm", "c2", cwd=origin)

    spec = add_source(store, str(origin), source_id="pinned", ref=first)
    assert spec.source_id == "pinned"
    assert spec.ref == first
    assert "v2" not in (
        store / "sources" / "pinned" / "skills" / "foo" / "SKILL.md"
    ).read_text()


def test_add_source_rejects_non_skill_repo(store, tmp_path):
    origin = tmp_path / "plain"
    origin.mkdir()
    (origin / "readme.md").write_text("hi\n")
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.email", "t@t", cwd=origin)
    git("config", "user.name", "t", cwd=origin)
    git("add", ".", cwd=origin)
    git("commit", "-q", "-m", "c1", cwd=origin)

    with pytest.raises(CatalogError):
        add_source(store, str(origin))
    assert not (store / "sources" / "plain").exists()
    assert load_registry(store) == {}


def test_add_duplicate_source_id_raises(store, tmp_path):
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    add_source(store, str(origin))
    with pytest.raises(CatalogError):
        add_source(store, str(origin))


def test_refresh_records_candidate_without_moving_worktree(store, tmp_path):
    origin = tmp_path / "origin-repo"
    first = make_skill_repo(origin)
    add_source(store, str(origin))

    (origin / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nv2\n")
    git("commit", "-aqm", "c2", cwd=origin)

    candidate = refresh_source(store, "origin-repo")
    assert candidate["current_commit"] == first
    assert candidate["candidate_commit"] != first
    assert candidate["changed"] is True

    saved = json.loads(
        (store / "state" / "candidates" / "origin-repo.json").read_text()
    )
    assert saved["candidate_commit"] == candidate["candidate_commit"]
    assert "v2" not in (
        store / "sources" / "origin-repo" / "skills" / "foo" / "SKILL.md"
    ).read_text()


def test_load_registry_rejects_bad_schema(store):
    (store / "registry" / "repositories.yml").write_text("schema_version: 99\n")
    with pytest.raises(CatalogError):
        load_registry(store)


@pytest.mark.parametrize(
    "bad_id",
    ["../../escaped", "x:y", ".hidden", "-opt", "a/b", "UPPER"],
)
def test_add_source_rejects_unsafe_ids_before_cloning(store, tmp_path, bad_id):
    """B1: `--id` is validated before anything touches the filesystem."""
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    with pytest.raises(CatalogError, match="invalid source id"):
        add_source(store, str(origin), source_id=bad_id)
    assert list((store / "sources").iterdir()) == []
    assert not (tmp_path / "escaped").exists()
    assert load_registry(store) == {}


def test_absolute_id_cannot_clone_into_a_host_skill_root(store, tmp_path):
    """B1: `--id "$HOME/.claude/skills/evilskill"` bypassed plan/approval by
    cloning straight into the host skill root."""
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    target = tmp_path / "home" / ".claude" / "skills" / "evilskill"
    with pytest.raises(CatalogError):
        add_source(store, str(origin), source_id=str(target))
    assert not target.exists()


def test_registry_with_escaping_id_is_refused(store):
    (store / "registry" / "repositories.yml").write_text(
        "schema_version: 1\nrepositories:\n  ../../escaped:\n"
        "    url: /x\n    ref: main\n    layout: {type: single}\n"
    )
    with pytest.raises(CatalogError, match="invalid source id"):
        load_registry(store)
    with pytest.raises(CatalogError):
        refresh_source(store, "../../escaped")
    assert not (store.parent / "escaped.json").exists()


def test_registry_keeps_loading_legacy_capitalized_ids(store):
    """Before 0.16.0 the default ID was the raw URL tail; keep such stores working."""
    (store / "registry" / "repositories.yml").write_text(
        "schema_version: 1\nrepositories:\n  My.Skills:\n"
        "    url: /x\n    ref: main\n    layout: {type: single}\n"
    )
    assert list(load_registry(store)) == ["My.Skills"]
    assert source_checkout(store, "My.Skills") == store / "sources" / "My.Skills"


def test_source_checkout_refuses_a_link_leaving_the_store(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (store / "sources" / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CatalogError, match="outside"):
        source_checkout(store, "linked")


def test_declared_skill_path_must_stay_in_the_checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / "skills").mkdir(parents=True)
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n")
    with pytest.raises(CatalogError, match="leaves the checkout"):
        sources.scan_source("s", repo, {"type": "single", "skill_path": ".."})
    with pytest.raises(CatalogError, match="leaves the checkout"):
        sources.scan_source("s", repo, {"type": "collection", "roots": [".."]})


def test_registry_and_output_never_store_url_credentials(store, tmp_path, monkeypatch):
    """B9: a token in the clone URL stays out of repositories.yml."""
    origin = tmp_path / "origin-repo"
    make_skill_repo(origin)
    real_clone = sources.gitops.clone
    monkeypatch.setattr(
        sources.gitops, "clone", lambda url, dest: real_clone(str(origin), dest)
    )

    spec = add_source(
        store, "https://x-access-token:ghp_SECRET@example.test/o/origin-repo.git"
    )
    assert spec.source_id == "origin-repo"
    assert spec.url == "https://example.test/o/origin-repo.git"
    assert "SECRET" not in (store / "registry" / "repositories.yml").read_text()


def test_add_source_refuses_a_skill_folder_linked_outside_the_checkout(store, tmp_path):
    """B1/B2/B8: the source would otherwise snapshot local private files
    and, as an exact copy, get the user's own skill quarantined."""
    private = tmp_path / "private-notes"
    private.mkdir()
    (private / "SKILL.md").write_text("---\nname: notes\n---\nx\n", encoding="utf-8")
    origin = tmp_path / "origin-repo"
    (origin / "skills").mkdir(parents=True)
    (origin / "skills" / "notes").symlink_to(private, target_is_directory=True)
    make_skill_repo(origin)

    with pytest.raises(CatalogError, match="resolves outside the checkout"):
        add_source(store, str(origin))
    assert not (store / "sources" / "origin-repo").exists()
    assert load_registry(store) == {}
