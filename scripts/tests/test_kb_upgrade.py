"""Tests for scripts/kb_upgrade.py."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import kb_upgrade as up

ENGINE_ROOT = Path(up.__file__).resolve().parent.parent
ENGINE_SCRIPTS = ENGINE_ROOT / "knowledge-base" / "scripts"
RELEASE_0_13 = "093d47fc1366085f87cd895756e9db194409202e"   # the commit that set VERSION 0.13.0


def _block(label: str, body: str) -> str:
    begin, end = up.block_markers(label)
    return f"{begin}\n{body}\n{end}"


VIEW = _block("VIEW", "## Local knowledge graph viewer\n\n- `!view` → python3 scripts/kb_view.py --background")
INDEX = _block("INDEX", "### Index loading rules\n\n- Route first: `knowledge/routing-table.md`.")
STATUS = _block("STATUS", "- Read `STATUS.md` at session start.")
TEMPLATE = f"# AGENTS.md — {{{{KB_NAME}}}}\n\n## How to use\n\n{INDEX}\n\n{STATUS}\n\n## Commands\n\n{VIEW}\n"


def _setup_fake_repo(tmp_path: Path, monkeypatch, *, version: str = "0.7.0") -> Path:
    """Create a fake source repo layout so kb_upgrade can resolve paths."""
    kb = tmp_path / "knowledge-base"
    for sub in ("scripts", "shell", "templates"):
        (kb / sub).mkdir(parents=True)
    (kb / "templates" / "AGENTS.md.template").write_text(TEMPLATE, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    monkeypatch.setattr(up, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(up, "SRC_KB_DIR", kb)
    monkeypatch.setattr(up, "SRC_SCRIPTS_DIR", kb / "scripts")
    monkeypatch.setattr(up, "SRC_TEMPLATES_DIR", kb / "templates")
    monkeypatch.setattr(up, "VERSION_FILE", tmp_path / "VERSION")
    monkeypatch.setattr(up, "KNOWN_HASHES_FILE", tmp_path / "scripts" / "known_hashes.json")
    return tmp_path


def _write_known(repo: Path, files: dict | None = None, blocks: dict | None = None) -> None:
    """files: {repo path: {content: [versions]}}; blocks: {label: {block: [versions]}}."""
    data = {
        "files": {
            path: {up.content_digest(content.encode()): versions for content, versions in entries.items()}
            for path, entries in (files or {}).items()
        },
        "blocks": {
            label: {up.block_digest(block): versions for block, versions in entries.items()}
            for label, entries in (blocks or {}).items()
        },
    }
    (repo / "scripts" / "known_hashes.json").write_text(json.dumps(data), encoding="utf-8")


def _base(root: Path, *, version: str = "0.0.0", agents: str | None = "# Local\n", extra: str = "") -> Path:
    base = root / "deployed"
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    (base / "kb.config.yml").write_text(
        f'instructions_version: "{version}"\nknowledge_base:\n  mode: default\n{extra}',
        encoding="utf-8",
    )
    if agents is not None:
        (base / "AGENTS.md").write_text(agents, encoding="utf-8")
    return base


def _with_engine_scripts(base: Path) -> None:
    """Give a test base the real engine scripts, so heal runs from the base."""
    for src in ENGINE_SCRIPTS.glob("kb_*.py"):
        shutil.copy2(src, base / "scripts" / src.name)


def _config(base: Path) -> dict:
    return yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# What gets delivered
# ---------------------------------------------------------------------------


def test_plans_cover_every_shipped_script_module_wrapper_launcher_and_requirements(tmp_path: Path):
    """D5 + launchers/requirements: one upgrader delivers the whole engine layer."""
    plans = {plan.name: plan for plan in up.collect_plans(tmp_path, "0.0.0", False)}
    kb = ENGINE_ROOT / "knowledge-base"

    for script in kb.joinpath("scripts").glob("kb_*.py"):
        assert plans[script.name].dst == tmp_path / "scripts" / script.name
    modules = [p.name for p in kb.glob("[0-9][0-9]_*.md")] + ["README.md"]
    assert len(modules) >= 20
    for module in modules:
        assert plans[f"kb-docs/{module}"].dst == tmp_path / "kb-docs" / module
    assert plans["shell/_kbpy.sh"].dst == tmp_path / "shell" / "_kbpy.sh"
    assert plans["shell/lint.sh"].dst == tmp_path / "shell" / "lint.sh"
    assert plans["reindex.bat"].dst == tmp_path / "reindex.bat"
    assert plans["watcher-start.command"].dst == tmp_path / "watcher-start.command"
    assert plans["requirements.txt"].dst == tmp_path / "requirements.txt"
    assert plans["requirements-media.txt"].dst == tmp_path / "requirements-media.txt"
    assert plans["requirements-nlp.txt"].dst == tmp_path / "requirements-nlp.txt"
    assert "shell/finalize.sh" not in plans and "finalize.sh" not in plans
    assert "requirements-dev.txt" not in plans
    assert not any(name.startswith(("tests/", "17_", "18_")) for name in plans)


def test_collect_plans_recursively_includes_viewer_bundle(tmp_path: Path, monkeypatch):
    """Dropping a nested viewer asset must add it to deployed upgrade plans."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    viewer = repo / "knowledge-base" / "scripts" / "kb_viewer"
    (viewer / "vendor").mkdir(parents=True)
    (viewer / "index.html").write_text("<main></main>", encoding="utf-8")
    (viewer / "vendor" / "graph.js").write_text("graph();", encoding="utf-8")
    deployed = tmp_path / "deployed"

    plans = up.collect_plans(deployed, prev_version="0.7.0", force=False)

    viewer_plans = {
        plan.name: plan.dst.relative_to(deployed).as_posix()
        for plan in plans
        if plan.name.startswith("kb_viewer/")
    }
    assert viewer_plans == {
        "kb_viewer/index.html": "scripts/kb_viewer/index.html",
        "kb_viewer/vendor/graph.js": "scripts/kb_viewer/vendor/graph.js",
    }


def test_collect_plans_keeps_posix_wrappers_in_shell_directory(tmp_path: Path, monkeypatch):
    """Finalized KBs keep *.sh wrappers in shell/, never at project root."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    source = repo / "knowledge-base" / "shell" / "reindex.sh"
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    target = deployed / "shell" / "reindex.sh"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)

    plans = up.collect_plans(deployed, prev_version="0.7.0", force=False)
    reindex = next(plan for plan in plans if plan.name == "shell/reindex.sh")

    assert reindex.dst == target
    assert reindex.state == "up_to_date"


def test_launchers_are_refreshed_where_the_base_keeps_them(tmp_path: Path, monkeypatch):
    """finalize.sh promotes launchers to the root; an unfinalized base keeps them in shell/."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    shell = repo / "knowledge-base" / "shell"
    (shell / "reindex.bat").write_text("new bat\n", encoding="utf-8")
    (shell / "export.command").write_text("new command\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    (deployed / "shell").mkdir(parents=True)
    (deployed / "shell" / "export.command").write_text("old\n", encoding="utf-8")

    plans = {plan.name: plan for plan in up.collect_plans(deployed, "0.7.0", False)}

    # Missing here, but this base keeps its launchers in shell/.
    assert plans["reindex.bat"].dst == deployed / "shell" / "reindex.bat"
    assert plans["export.command"].dst == deployed / "shell" / "export.command"


def test_new_launchers_join_the_others_in_shell(tmp_path: Path, monkeypatch):
    """A base that keeps every launcher in shell/ (never finalized) gets new
    ones there too — not a layout split between shell/ and the root."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    shell = repo / "knowledge-base" / "shell"
    for name in ("reindex.bat", "reindex.command", "export.bat", "export.command"):
        (shell / name).write_text(f"new {name}\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    (deployed / "shell").mkdir(parents=True)
    for name in ("reindex.bat", "reindex.command"):
        (deployed / "shell" / name).write_text("old\n", encoding="utf-8")

    plans = {plan.name: plan for plan in up.collect_plans(deployed, "0.7.0", False)}
    assert plans["export.bat"].dst == deployed / "shell" / "export.bat"
    assert plans["export.command"].dst == deployed / "shell" / "export.command"

    # A finalized base (launchers at the root) gets new ones at the root.
    (deployed / "reindex.bat").write_text("old\n", encoding="utf-8")
    plans = {plan.name: plan for plan in up.collect_plans(deployed, "0.7.0", False)}
    assert plans["export.bat"].dst == deployed / "export.bat"


def test_local_debris_in_the_checkout_is_never_shipped(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "shell" / ".DS_Store").write_bytes(b"\0finder")
    (repo / "knowledge-base" / "scripts" / "__pycache__").mkdir()
    (repo / "knowledge-base" / "scripts" / "__pycache__" / "kb_x.cpython-312.pyc").write_bytes(b"\0")

    assert up.collect_plans(tmp_path / "deployed", "0.7.0", False) == []


def test_collect_plans_can_accept_one_customized_file_only(tmp_path: Path, monkeypatch):
    """Selective acceptance must not have the destructive scope of --force."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    (scripts / "kb_lint.py").write_text("new lint\n", encoding="utf-8")
    (scripts / "kb_stt.py").write_text("new stt\n", encoding="utf-8")
    deployed = tmp_path / "deployed" / "scripts"
    deployed.mkdir(parents=True)
    (deployed / "kb_lint.py").write_text("old lint\n", encoding="utf-8")
    (deployed / "kb_stt.py").write_text("old stt\n", encoding="utf-8")

    plans = up.collect_plans(
        tmp_path / "deployed", prev_version="0.0.0", force=False, accepted={"kb_stt.py"}
    )
    states = {plan.name: plan.state for plan in plans}

    assert states["kb_stt.py"] == "accepted"
    assert states["kb_lint.py"] == "customized"


# ---------------------------------------------------------------------------
# Recognising pristine copies (Q20)
# ---------------------------------------------------------------------------


def test_known_hashes_recognise_an_old_pristine_copy_without_git(tmp_path: Path, monkeypatch):
    """Q20: a ZIP download (no .git, no tags) must still see an old clean copy as clean."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("lint v2\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "scripts" / "kb_lint.py"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"lint v1\r\n")  # CRLF checkout of the old release

    assert up.compute_plan(src, dst, "0.1.0", False).state == "customized"
    _write_known(repo, files={"knowledge-base/scripts/kb_lint.py": {"lint v1\n": ["0.1.0"]}})
    assert up.compute_plan(src, dst, "0.1.0", False).state == "clean_overwrite"


def test_shipped_registry_knows_released_engine_files():
    known = up.load_known_hashes(ENGINE_ROOT / "scripts" / "known_hashes.json")
    releases = {
        version
        for versions in known.files["knowledge-base/scripts/kb_common.py"].values()
        for version in versions
    }
    assert {"0.13.0", "0.15.0", "0.15.1"} <= releases
    assert known.blocks["INDEX"] and known.blocks["VIEW"]


def _git_blob(spec: str) -> bytes | None:
    result = subprocess.run(["git", "show", spec], cwd=ENGINE_ROOT, capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else None


def test_pristine_0_13_base_from_a_zip_is_not_reported_as_customized(tmp_path: Path, monkeypatch):
    """Q20: `git archive` engine (no history, no tags) + clean 0.13.0 base → 10 items for review."""
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", f"{RELEASE_0_13}", "knowledge-base"],
        cwd=ENGINE_ROOT, capture_output=True, text=True, check=False,
    )
    if listing.returncode != 0:
        pytest.skip("engine checkout without git history")
    base = _base(tmp_path, version="0.13.0")
    for rel in listing.stdout.splitlines():
        group = up._classify(rel)
        data = _git_blob(f"{RELEASE_0_13}:{rel}") if group else None
        if data is not None:
            dst = up._target(base, rel, group)[1]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
    template = _git_blob(f"{RELEASE_0_13}:knowledge-base/templates/AGENTS.md.template")
    (base / "AGENTS.md").write_bytes(template)
    monkeypatch.setattr(up, "file_matches_repo_history", lambda *args: False)  # a ZIP has no .git
    known = up.load_known_hashes()

    plans = up.collect_plans(base, "0.13.0", False, known=known)

    assert not [plan.name for plan in plans if plan.state not in ("up_to_date", "clean_overwrite", "missing")]
    assert sum(plan.state == "clean_overwrite" for plan in plans) >= 10
    index = up.reference_blocks()["INDEX"]
    result = _update(base / "AGENTS.md", "INDEX", index, base="0.13.0", repo=up.get_repo_version(), known=known)
    assert result.state in ("up_to_date", "outdated") and not result.sidecar


def test_load_known_hashes_tolerates_a_missing_or_broken_file(tmp_path: Path):
    assert up.load_known_hashes(tmp_path / "absent.json").files == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert up.load_known_hashes(broken).file_versions("x", "y") is None
    odd = tmp_path / "odd.json"
    odd.write_text('{"files": {"x": ["not", "a", "map"]}}', encoding="utf-8")
    assert up.load_known_hashes(odd).file_versions("x", "y") is None


# ---------------------------------------------------------------------------
# Customizations: kept, merged, accepted (Q4 / E-H7 / Q14)
# ---------------------------------------------------------------------------


def test_customization_on_an_unchanged_reference_is_kept_silently(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_structure.py"
    src.write_text("structure\n", encoding="utf-8")
    _write_known(repo, files={"knowledge-base/scripts/kb_structure.py": {"structure\n": ["0.5.0", "0.7.0"]}})
    dst = tmp_path / "deployed" / "scripts" / "kb_structure.py"
    dst.parent.mkdir(parents=True)
    dst.write_text("structure\n# my tweak\n", encoding="utf-8")

    plan = up.compute_plan(src, dst, "0.5.0", False)

    assert plan.state == "kept"
    assert "kept" in up.apply_plan(plan, dry_run=False)
    assert not dst.with_name("kb_structure.py.new").exists()


def test_accept_local_resolves_a_merge_and_the_version_moves_on(tmp_path: Path, monkeypatch, capsys):
    """E-H7: after merging the sidecar the upgrade must converge, not loop on exit 2."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    target = base / "scripts" / "kb_lint.py"
    target.write_text("old\n# MY PATCH\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    sidecar = base / "scripts" / "kb_lint.py.new"
    assert sidecar.read_text(encoding="utf-8") == "new\n"
    assert _config(base)["instructions_version"] == "0.5.0"

    target.write_text("new\n# MY PATCH\n", encoding="utf-8")  # the merge
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2  # still waits
    assert up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_lint.py"]) == 0
    assert target.read_text(encoding="utf-8") == "new\n# MY PATCH\n"
    assert not sidecar.exists()
    assert _config(base)["instructions_version"] == "0.7.0"

    capsys.readouterr()
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    assert not sidecar.exists()
    output = capsys.readouterr().out
    assert "customized" not in output
    assert "Already up to date." in output


def test_accept_local_is_remembered_while_another_file_waits(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    for name in ("kb_lint.py", "kb_route.py"):
        (repo / "knowledge-base" / "scripts" / name).write_text(f"new {name}\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    for name in ("kb_lint.py", "kb_route.py"):
        (base / "scripts" / name).write_text(f"merged {name}\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_lint.py"]) == 2
    assert _config(base)["instructions_version"] == "0.5.0"
    assert not (base / "scripts" / "kb_lint.py.new").exists()
    assert up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_route.py"]) == 0
    assert _config(base)["instructions_version"] == "0.7.0"
    assert not (base / "scripts" / "kb_lint.py.new").exists()


def test_accept_backs_up_the_local_copy_and_drops_the_sidecar(tmp_path: Path, monkeypatch):
    """Q14: --accept / --force never lose a customization; no forgotten sidecar."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    target = base / "scripts" / "kb_lint.py"
    target.write_text("custom\n", encoding="utf-8")
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    assert (base / "scripts" / "kb_lint.py.new").is_file()

    assert up.main(["--kb-root", str(base), "--no-heal", "--accept", "scripts/kb_lint.py"]) == 0

    assert target.read_text(encoding="utf-8") == "new\n"
    assert not (base / "scripts" / "kb_lint.py.new").exists()
    backups = list((base / ".kb-state" / "upgrade-backups").glob("*/scripts/kb_lint.py"))
    assert [b.read_text(encoding="utf-8") for b in backups] == ["custom\n"]
    assert (base / ".kb-state" / ".gitignore").is_file()


def test_force_backs_up_every_customized_file(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    (base / "scripts" / "kb_lint.py").write_text("custom\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal", "--force"]) == 0

    backups = list((base / ".kb-state" / "upgrade-backups").rglob("kb_lint.py"))
    assert [b.read_text(encoding="utf-8") for b in backups] == ["custom\n"]


def test_an_identical_forgotten_sidecar_is_removed(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "scripts" / "kb_lint.py"
    dst.parent.mkdir(parents=True)
    dst.write_text("new\n", encoding="utf-8")
    sidecar = dst.with_name("kb_lint.py.new")
    sidecar.write_text("new\n", encoding="utf-8")

    plan = up.compute_plan(src, dst, "0.7.0", False)
    assert "would remove" in up.apply_plan(plan, dry_run=True)
    assert sidecar.exists()
    assert "removed kb_lint.py.new" in up.apply_plan(plan, dry_run=False)
    assert not sidecar.exists()


def test_force_replaces_only_files_that_would_get_a_sidecar(tmp_path: Path, monkeypatch, capsys):
    """Q14: --force = --accept for every customized file; kept and
    --accept-local files are left alone unless named with --accept."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    for name in ("kb_lint.py", "kb_route.py", "kb_stt.py"):
        (scripts / name).write_text(f"new {name}\n", encoding="utf-8")
    # kb_lint.py: upstream unchanged since the base's version → `kept`.
    _write_known(repo, files={"knowledge-base/scripts/kb_lint.py": {"new kb_lint.py\n": ["0.5.0", "0.7.0"]}})
    base = _base(tmp_path, version="0.5.0")
    lint, route, stt = (base / "scripts" / n for n in ("kb_lint.py", "kb_route.py", "kb_stt.py"))
    lint.write_text("new kb_lint.py\n# LOCAL LINT RULE\n", encoding="utf-8")
    route.write_text("custom route\n", encoding="utf-8")
    stt.write_text("new kb_stt.py\n# merged by hand\n", encoding="utf-8")
    assert up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_stt.py"]) == 2
    capsys.readouterr()

    assert up.main(["--kb-root", str(base), "--no-heal", "--force"]) == 0
    output = capsys.readouterr().out

    assert route.read_text(encoding="utf-8") == "new kb_route.py\n"
    assert lint.read_text(encoding="utf-8") == "new kb_lint.py\n# LOCAL LINT RULE\n"
    assert stt.read_text(encoding="utf-8") == "new kb_stt.py\n# merged by hand\n"
    assert "kb_lint.py" in output and "kept (local edits" in output
    backups = [p.name for p in (base / ".kb-state" / "upgrade-backups").rglob("*.py")]
    assert backups == ["kb_route.py"]

    # Naming a file takes upstream for it even when it is kept.
    assert up.main(["--kb-root", str(base), "--no-heal", "--accept", "kb_lint.py"]) == 0
    assert lint.read_text(encoding="utf-8") == "new kb_lint.py\n"
    assert stt.read_text(encoding="utf-8") == "new kb_stt.py\n# merged by hand\n"


def test_sidecars_written_by_an_older_upgrader_are_removed(tmp_path: Path, monkeypatch, capsys):
    """Q14/Q20/E-H7: a pre-0.16 upgrader wrote `.new` copies of older engine
    versions (also for pristine files); once the live file is current they are
    obsolete and must not end up in HEAL_PLAN as merges."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    for name in ("kb_heal.py", "kb_lint.py", "kb_route.py"):
        (scripts / name).write_text(f"{name} v3\n", encoding="utf-8")
    _write_known(repo, files={
        f"knowledge-base/scripts/{name}": {f"{name} v1\n": ["0.5.0"], f"{name} v2\n": ["0.6.0"], f"{name} v3\n": ["0.7.0"]}
        for name in ("kb_heal.py", "kb_lint.py", "kb_route.py")
    })
    base = _base(tmp_path, version="0.5.0")
    live = base / "scripts"
    (live / "kb_heal.py").write_text("kb_heal.py v1\n", encoding="utf-8")        # pristine
    (live / "kb_heal.py.new").write_text("kb_heal.py v2\n", encoding="utf-8")    # old sidecar
    (live / "kb_lint.py").write_text("kb_lint.py v3\n", encoding="utf-8")        # already current
    (live / "kb_lint.py.new").write_text("kb_lint.py v1\n", encoding="utf-8")
    (live / "kb_route.py").write_text("kb_route.py v1\n", encoding="utf-8")
    (live / "kb_route.py.new").write_text("my own notes\n", encoding="utf-8")    # not an engine copy

    assert up.main(["--kb-root", str(base), "--no-heal", "--dry-run"]) == 0
    assert (live / "kb_heal.py.new").exists() and "would remove kb_heal.py.new" in capsys.readouterr().out

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    output = capsys.readouterr().out

    assert (live / "kb_heal.py").read_text(encoding="utf-8") == "kb_heal.py v3\n"
    assert not (live / "kb_heal.py.new").exists()
    assert not (live / "kb_lint.py.new").exists()
    assert "removed kb_heal.py.new (an older engine version)" in output
    assert (live / "kb_route.py.new").read_text(encoding="utf-8") == "my own notes\n"
    assert "left kb_route.py.new (not an engine version" in output


def test_a_kept_file_drops_a_forgotten_sidecar(tmp_path: Path, monkeypatch):
    """Q14 (kept): the local file already builds on the reference in the sidecar."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("lint\n", encoding="utf-8")
    _write_known(repo, files={"knowledge-base/scripts/kb_lint.py": {"lint\n": ["0.5.0", "0.7.0"]}})
    dst = tmp_path / "deployed" / "scripts" / "kb_lint.py"
    dst.parent.mkdir(parents=True)
    dst.write_text("lint\n# LOCAL LINT RULE\n", encoding="utf-8")
    sidecar = dst.with_name("kb_lint.py.new")
    sidecar.write_text("lint\n", encoding="utf-8")

    plan = up.compute_plan(src, dst, "0.5.0", False)

    assert plan.state == "kept"
    assert "removed kb_lint.py.new" in up.apply_plan(plan, dry_run=False)
    assert not sidecar.exists()
    assert dst.read_text(encoding="utf-8") == "lint\n# LOCAL LINT RULE\n"


def test_accept_and_accept_local_for_the_same_file_is_an_error(tmp_path: Path, monkeypatch):
    _setup_fake_repo(tmp_path, monkeypatch)
    base = _base(tmp_path)
    assert up.main(["--kb-root", str(base), "--accept", "kb_lint.py", "--accept-local", "kb_lint.py"]) == 3


# ---------------------------------------------------------------------------
# Dependencies (Q6)
# ---------------------------------------------------------------------------


def test_customized_shared_module_holds_back_its_dependents(tmp_path: Path, monkeypatch, capsys):
    """Q6: new kb_lint.py must not land next to an unmerged old kb_common.py."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    (scripts / "kb_common.py").write_text("def invariant_problems(t):\n    return []\n", encoding="utf-8")
    (scripts / "kb_lint.py").write_text("import kb_common as kbc\nkbc.invariant_problems('')\n", encoding="utf-8")
    (scripts / "kb_mutate.py").write_text("import kb_lint\n", encoding="utf-8")
    (scripts / "kb_update.py").write_text("import subprocess\n", encoding="utf-8")
    (repo / "knowledge-base" / "shell" / "lint.sh").write_text(
        '#!/bin/sh\n. "$KB_SHELL_DIR/_kbpy.sh"\nkb_run scripts/kb_lint.py "$@"\n', encoding="utf-8"
    )
    _write_known(repo, files={
        "knowledge-base/scripts/kb_lint.py": {"old lint\n": ["0.5.0"]},
        "knowledge-base/scripts/kb_update.py": {"old update\n": ["0.5.0"]},
    })
    base = _base(tmp_path, version="0.5.0")
    (base / "scripts" / "kb_common.py").write_text("OLD = 1  # MY PATCH\n", encoding="utf-8")
    (base / "scripts" / "kb_lint.py").write_text("old lint\n", encoding="utf-8")
    (base / "scripts" / "kb_update.py").write_text("old update\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    output = capsys.readouterr().out

    assert (base / "scripts" / "kb_common.py.new").is_file()
    assert (base / "scripts" / "kb_lint.py").read_text(encoding="utf-8") == "old lint\n"
    assert not (base / "scripts" / "kb_lint.py.new").exists()
    assert not (base / "scripts" / "kb_mutate.py").exists()   # held, not half-installed
    assert not (base / "shell" / "lint.sh").exists()
    assert (base / "scripts" / "kb_update.py").read_text(encoding="utf-8") == "import subprocess\n"
    assert "held until kb_common.py is resolved" in output
    assert _config(base)["instructions_version"] == "0.5.0"

    (base / "scripts" / "kb_common.py").write_text(  # the merge
        "OLD = 1  # MY PATCH\ndef invariant_problems(t):\n    return []\n", encoding="utf-8"
    )
    assert up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_common.py"]) == 0
    assert (base / "scripts" / "kb_lint.py").read_text(encoding="utf-8").startswith("import kb_common")
    assert (base / "scripts" / "kb_mutate.py").is_file()


def test_accept_local_of_an_unmerged_shared_module_is_refused(tmp_path: Path, monkeypatch, capsys):
    """Q6 (adversarial): --accept-local kb_common.py without the merge must not
    drop the .new and release scripts that use names the local copy lacks."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    (scripts / "kb_common.py").write_text("def stale_status(*a):\n    return None\n", encoding="utf-8")
    (scripts / "kb_lint.py").write_text("import kb_common as kbc\nkbc.stale_status()\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    local = "OLD = 1  # LOCAL TWEAK\n"
    (base / "scripts" / "kb_common.py").write_text(local, encoding="utf-8")
    (base / "scripts" / "kb_lint.py").write_text("old lint\n", encoding="utf-8")
    _write_known(repo, files={"knowledge-base/scripts/kb_lint.py": {"old lint\n": ["0.5.0"]}})

    for _ in range(2):  # the refusal is not remembered as an accepted local copy
        assert up.main(
            ["--kb-root", str(base), "--no-heal", "--accept-local", "kb_common.py"]
        ) == 2
        output = capsys.readouterr().out
        assert "--accept-local refused: the local kb_common.py lacks stale_status" in output
        assert "--accept kb_common.py" in output
        assert (base / "scripts" / "kb_common.py.new").is_file()
        assert (base / "scripts" / "kb_lint.py").read_text(encoding="utf-8") == "old lint\n"
        assert "held until kb_common.py is resolved" in output
    assert _config(base)["instructions_version"] == "0.5.0"

    assert up.main(["--kb-root", str(base), "--no-heal", "--accept", "kb_common.py"]) == 0
    assert "stale_status" in (base / "scripts" / "kb_common.py").read_text(encoding="utf-8")
    assert (base / "scripts" / "kb_lint.py").read_text(encoding="utf-8").startswith("import kb_common")


def test_viewer_assets_and_kb_view_move_together(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    (scripts / "kb_view.py").write_text("view v2\n", encoding="utf-8")
    (scripts / "kb_viewer").mkdir()
    (scripts / "kb_viewer" / "app.js").write_text("app v2\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    (deployed / "scripts" / "kb_viewer").mkdir(parents=True)
    (deployed / "scripts" / "kb_view.py").write_text("view v1\n", encoding="utf-8")
    (deployed / "scripts" / "kb_viewer" / "app.js").write_text("app v1 + mine\n", encoding="utf-8")
    _write_known(repo, files={"knowledge-base/scripts/kb_view.py": {"view v1\n": ["0.5.0"]}})

    plans = {plan.name: plan for plan in up.collect_plans(deployed, "0.5.0", False)}

    assert plans["kb_viewer/app.js"].state == "customized"
    assert plans["kb_view.py"].state == "held"


def test_shell_comments_and_the_deploy_layout_probe_are_not_dependencies():
    """Q6: a usage comment in _kbpy.sh must not tie the whole shell layer to kb_lint.py."""
    sh = (
        "#!/bin/sh\n"
        "#   kb_run scripts/kb_lint.py \"$@\"\n"
        '  [ -f "$(dirname -- "$KB_ROOT")/setup/scripts/kb_common.py" ]\n'
        '. "$KB_SHELL_DIR/_kbpy.sh" || exit 2\n'
        'kb_run scripts/kb_reindex.py "$@"  # trailing comment\n'
        "bash shell/watcher.sh stop\n"
    )
    assert up._shell_dependencies(sh, batch=False) == {
        "kb_reindex.py", "shell/_kbpy.sh", "shell/watcher.sh",
    }
    bat = (
        "@echo off\n"
        "REM Python, same order as shell/_kbpy.sh: %KB_PYTHON%\n"
        ":: scripts\\kb_lint.py\n"
        'if exist "..\\setup\\scripts\\kb_common.py" set "PY=x"\n'
        '"%PY%" scripts\\kb_reindex.py %*\n'
    )
    assert up._shell_dependencies(bat, batch=True) == {"kb_reindex.py"}

    plans = up.collect_plans(Path("/nonexistent-base"), "0.0.0", False)
    names = {plan.name for plan in plans}
    helper = next(plan for plan in plans if plan.name == "shell/_kbpy.sh")
    assert up._dependencies(helper, names) == set()


def test_scripts_run_as_subprocesses_are_dependencies(tmp_path: Path, monkeypatch):
    """Q6: kb_reindex runs kb_lint; a new kb_reindex must not call an old, customized one."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    scripts = repo / "knowledge-base" / "scripts"
    (scripts / "kb_lint.py").write_text("new lint\n", encoding="utf-8")
    (scripts / "kb_route.py").write_text("new route\n", encoding="utf-8")
    (scripts / "kb_reindex.py").write_text(
        'def _py(name, *args):\n    pass\n\n_py("kb_lint.py", "--quick")\n'
        'print("then run: python3 scripts/kb_route.py --check")\n',
        encoding="utf-8",
    )
    deployed = tmp_path / "deployed"
    (deployed / "scripts").mkdir(parents=True)
    (deployed / "scripts" / "kb_lint.py").write_text("old lint + MINE\n", encoding="utf-8")
    (deployed / "scripts" / "kb_route.py").write_text("old route + MINE\n", encoding="utf-8")

    plans = {plan.name: plan for plan in up.collect_plans(deployed, "0.5.0", False)}

    assert plans["kb_reindex.py"].state == "held"
    assert plans["kb_reindex.py"].held_by == "kb_lint.py"
    assert up._python_dependencies((scripts / "kb_reindex.py").read_bytes()) == {"kb_lint.py"}


def test_docs_and_blocks_wait_for_the_scripts_they_describe(tmp_path: Path, monkeypatch, capsys):
    """D5/D12 vs Q6: new kb-docs/ and the STATUS block must not describe
    commands the base's held-back scripts do not have yet."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    kb = repo / "knowledge-base"
    (kb / "scripts" / "kb_common.py").write_text("NEW = 1\n", encoding="utf-8")
    (kb / "scripts" / "kb_status.py").write_text("import kb_common\n", encoding="utf-8")
    (kb / "03_PIPELINE.md").write_text("Run `python3 scripts/kb_status.py --print`.\n", encoding="utf-8")
    (kb / "08_PORTABLE.md").write_text("Copy the folder.\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0", agents=f"# Local\n\n{INDEX}\n")
    (base / "scripts" / "kb_common.py").write_text("OLD = 1  # MY PATCH\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    output = capsys.readouterr().out

    assert not (base / "kb-docs" / "03_PIPELINE.md").exists()
    assert (base / "kb-docs" / "08_PORTABLE.md").is_file()
    assert "AI-KE:STATUS" not in (base / "AGENTS.md").read_text(encoding="utf-8")
    assert "held until kb_common.py is resolved" in output.split("AGENTS.md (status block)")[1].splitlines()[0]

    assert up.main(["--kb-root", str(base), "--no-heal", "--accept", "kb_common.py"]) == 0
    assert (base / "kb-docs" / "03_PIPELINE.md").is_file()
    assert f"{INDEX}\n\n{STATUS}" in (base / "AGENTS.md").read_text(encoding="utf-8")


def test_a_new_module_waits_only_for_scripts_the_base_lacks(tmp_path: Path, monkeypatch):
    """A pre-0.16 base has no kb-docs/: one customized script must not hold
    every module that mentions it — there is no older text to protect, and
    scripts installed in the same run cite those modules."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    kb = repo / "knowledge-base"
    (kb / "scripts" / "kb_common.py").write_text("NEW = 1\n", encoding="utf-8")
    (kb / "scripts" / "kb_route.py").write_text("import kb_common\n", encoding="utf-8")
    (kb / "scripts" / "kb_brandnew.py").write_text("import kb_route\n", encoding="utf-8")
    (kb / "04_REVIEW.md").write_text("`kb_route.py` writes routing pages.\n", encoding="utf-8")
    (kb / "13_AUTORUN.md").write_text("Run `kb_brandnew.py`.\n", encoding="utf-8")
    base = _base(tmp_path, version="0.5.0")
    (base / "scripts" / "kb_common.py").write_text("NEW = 1\n", encoding="utf-8")
    (base / "scripts" / "kb_route.py").write_text("LOCAL ROUTE\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2

    assert (base / "kb-docs" / "04_REVIEW.md").is_file()      # kb_route.py is there (old)
    assert not (base / "kb-docs" / "13_AUTORUN.md").exists()  # kb_brandnew.py is held
    assert not (base / "scripts" / "kb_brandnew.py").exists()


# ---------------------------------------------------------------------------
# Heal from the base's own scripts (Q6, Q17)
# ---------------------------------------------------------------------------

FAKE_HEAL = '''\
from pathlib import Path
from types import SimpleNamespace

COUNT = Path(__file__).with_name("collect-count")
APPLY = Path(__file__).with_name("apply-something")


def collect_findings(root, **kwargs):
    runs = int(COUNT.read_text()) if COUNT.exists() else 0
    COUNT.write_text(str(runs + 1))
    if APPLY.exists() and Path(root, "stamped-version").exists():
        return []   # the applied auto fix closed the finding
    return [SimpleNamespace(id="x", bucket="auto", locked=False)]


def apply_auto(root, *, version=None, **kwargs):
    findings = collect_findings(root)
    Path(root, "stamped-version").write_text(str(version))
    return findings if APPLY.exists() else []


def write_plan(root, **kwargs):
    ids = [item.id for item in collect_findings(root)]
    Path(root, "plan-written").write_text(",".join(ids) or "no findings")


def summarize(findings, applied, stage):
    return f"BASE HEAL applied={len(applied)} stage={stage}"
'''


def _fake_heal_base(tmp_path: Path, monkeypatch, *, heal_source: str = FAKE_HEAL) -> Path:
    _setup_fake_repo(tmp_path, monkeypatch)
    base = _base(tmp_path, version="0.5.0", extra="heal:\n  auto_apply: true\n  stage: 2\n")
    (base / "scripts" / "kb_heal.py").write_text(heal_source, encoding="utf-8")
    return base


def test_heal_runs_the_base_scripts_and_lint_doctor_once(tmp_path: Path, monkeypatch, capsys):
    """Q6 + Q17: heal comes from the base (not the engine) and collects once."""
    base = _fake_heal_base(tmp_path, monkeypatch)

    assert up.main(["--kb-root", str(base)]) == 0
    output = capsys.readouterr().out

    assert "BASE HEAL applied=0 stage=2" in output
    assert (base / "scripts" / "collect-count").read_text() == "1"
    assert (base / "plan-written").read_text() == "x"
    assert (base / "stamped-version").read_text() == "0.7.0"


def test_heal_collects_again_only_after_an_applied_auto_fix(tmp_path: Path, monkeypatch):
    """HEAL_PLAN lists the work left after the auto bucket, not the applied fixes."""
    base = _fake_heal_base(tmp_path, monkeypatch)
    (base / "scripts" / "apply-something").write_text("1")

    assert up.main(["--kb-root", str(base)]) == 0
    assert (base / "scripts" / "collect-count").read_text() == "2"
    assert (base / "plan-written").read_text() == "no findings"


def test_a_crashing_base_heal_is_reported_and_blocks_the_bump(tmp_path: Path, monkeypatch, capsys):
    """Q6: an inconsistent base must not be reported as healed."""
    base = _fake_heal_base(
        tmp_path, monkeypatch,
        heal_source="import kb_common\nkb_common.invariant_problems\n",
    )
    (base / "scripts" / "kb_common.py").write_text("OLD = 1\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base)]) == 2
    output = capsys.readouterr().out
    assert "heal failed" in output
    assert "invariant_problems" in output
    assert _config(base)["instructions_version"] == "0.5.0"


def test_dry_run_heal_detects_with_engine_scripts_and_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    base = _fake_heal_base(tmp_path, monkeypatch)
    (up.SRC_SCRIPTS_DIR / "kb_heal.py").write_text(
        FAKE_HEAL.replace("BASE HEAL", "ENGINE HEAL"), encoding="utf-8"
    )

    up.main(["--kb-root", str(base), "--dry-run"])
    output = capsys.readouterr().out

    assert "Heal detect (dry-run, engine scripts, not written): auto=1 assisted=0 human=0" in output
    assert not (base / "plan-written").exists()
    assert not (base / "scripts" / "collect-count").exists()


def test_upgrade_writes_heal_plan_with_the_base_heal_when_customized(tmp_path: Path, monkeypatch, capsys):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path)
    _with_engine_scripts(base)
    (base / "scripts" / "kb_lint.py").write_text(
        (ENGINE_SCRIPTS / "kb_lint.py").read_text(encoding="utf-8") + "# custom\n", encoding="utf-8"
    )

    result = up.main(["--kb-root", str(base)])
    output = capsys.readouterr().out
    assert result == 2
    assert (base / "review" / "needs-heal" / "HEAL_PLAN.md").is_file()
    assert "!heal" in output


def test_upgrade_stamps_heal_last_run_with_the_new_version(tmp_path: Path, monkeypatch):
    """Otherwise doctor warns 'version moved without heal' on a clean upgrade."""
    _setup_fake_repo(tmp_path, monkeypatch)
    base = _base(tmp_path)
    _with_engine_scripts(base)

    assert up.main(["--kb-root", str(base)]) == 0
    cfg = _config(base)
    assert cfg["instructions_version"] == "0.7.0"
    assert cfg["heal"]["last_run"]["version"] == "0.7.0"


def test_heal_stamp_never_moves_backwards_when_the_bump_waits(tmp_path: Path, monkeypatch):
    """E-H7: heal.last_run.version went 0.15.1 → 0.14.0 on a customized upgrade."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_route.py").write_text("new\n", encoding="utf-8")
    base = _base(
        tmp_path, version="0.5.0",
        extra='heal:\n  auto_apply: true\n  stage: 1\n  last_run:\n    at: "2026-01-01"\n    version: "0.6.0"\n',
    )
    _with_engine_scripts(base)
    (base / "scripts" / "kb_route.py").write_text("custom\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base)]) == 2
    cfg = _config(base)
    assert cfg["instructions_version"] == "0.5.0"
    assert cfg["heal"]["last_run"]["version"] == "0.6.0"


@pytest.mark.parametrize("has_plan_summary, expected", [(True, "stage=3"), (False, "stage=1")])
def test_heal_summary_reports_the_stage_heal_reached(tmp_path: Path, has_plan_summary, expected):
    """Heal advances heal.stage inside apply_auto; the upgrade summary printed
    the stage kb.config.yml had before heal ran. An older kb_heal.py without
    plan_summary still gets the configured stage."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    stub = (
        "def collect_findings(root): return []\n"
        "def apply_auto(root, version=None): return []\n"
        "def write_plan(root): return None\n"
        "def summarize(findings, applied, stage): return f'stage={stage}'\n"
    )
    if has_plan_summary:
        stub += "def plan_summary(root, findings): return {'stage': 3}\n"
    (scripts / "kb_heal.py").write_text(stub, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", "-c", up.HEAL_DRIVER, str(scripts), str(tmp_path), "apply", "", "1", "1"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_upgrade_says_to_reinstall_an_outdated_git_hook(tmp_path: Path, monkeypatch, capsys):
    """install-hooks.sh copies shell/hooks/post-commit into .git/hooks; the
    upgrade refreshes only the base's shell/ copy, so it tells the owner."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    hook_src = repo / "knowledge-base" / "shell" / "hooks" / "post-commit"
    hook_src.parent.mkdir()
    hook_src.write_text(f"#!/bin/sh\n# {up.HOOK_MARKER} v2\n", encoding="utf-8")
    base = _base(tmp_path)
    assert subprocess.run(["git", "init", "-q", str(base)], check=False).returncode == 0
    installed = base / ".git" / "hooks" / "post-commit"
    installed.write_text(f"#!/bin/sh\n# {up.HOOK_MARKER} v1\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    assert (base / "shell" / "hooks" / "post-commit").read_bytes() == hook_src.read_bytes()
    out = capsys.readouterr().out
    assert "bash shell/install-hooks.sh" in out and str(installed) in out

    installed.write_bytes(hook_src.read_bytes())       # re-installed: nothing to say
    assert up.outdated_installed_hook(base) is None
    installed.write_text("#!/bin/sh\nmake lint\n", encoding="utf-8")   # a foreign hook
    assert up.outdated_installed_hook(base) is None
    assert up.outdated_installed_hook(tmp_path / "not-a-repo") is None


def test_upgrade_no_heal_skips_plan(tmp_path: Path, monkeypatch, capsys):
    _setup_fake_repo(tmp_path, monkeypatch)
    base = _base(tmp_path)

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    assert not (base / "review" / "needs-heal" / "HEAL_PLAN.md").is_file()
    assert "Heal skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Version never backwards
# ---------------------------------------------------------------------------


def test_a_base_newer_than_the_checkout_is_refused(tmp_path: Path, monkeypatch, capsys):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("older engine\n", encoding="utf-8")
    base = _base(tmp_path, version="0.10.0")
    before = (base / "kb.config.yml").read_text(encoding="utf-8")

    assert up.main(["--kb-root", str(base)]) == 3
    assert "never moves a base backwards" in capsys.readouterr().err
    assert (base / "kb.config.yml").read_text(encoding="utf-8") == before
    assert not (base / "scripts" / "kb_lint.py").exists()


def test_version_key_orders_numerically():
    assert up.version_key("0.10.0") > up.version_key("0.9.3")
    assert up.version_key("0.15") == up.version_key("0.15.0")
    assert up.version_key("unknown") is None


# ---------------------------------------------------------------------------
# AGENTS.md managed blocks (D12)
# ---------------------------------------------------------------------------


def _update(agents: Path, label: str, reference: str, *, base="0.7.0", repo="0.7.0",
            known=None, dry_run=False, records=None):
    return up.update_managed_block(
        agents, label, reference, base_version=base, repo_version=repo,
        known=known or up.KnownHashes(), dry_run=dry_run, records=records,
    )


def test_reference_blocks_come_from_the_agents_template(tmp_path: Path, monkeypatch):
    _setup_fake_repo(tmp_path, monkeypatch)
    assert up.reference_blocks() == {"VIEW": VIEW, "INDEX": INDEX, "STATUS": STATUS}


def test_deprecated_block_constants_still_resolve(tmp_path: Path, monkeypatch):
    """Code that read kb_upgrade.VIEW_BLOCK / INDEX_BLOCK before 0.16 keeps working."""
    _setup_fake_repo(tmp_path, monkeypatch)
    assert up.VIEW_BLOCK == VIEW
    assert up.INDEX_BLOCK == INDEX
    (tmp_path / "knowledge-base" / "templates" / "AGENTS.md.template").write_text("# none\n", encoding="utf-8")
    assert up.VIEW_BLOCK == ""
    with pytest.raises(AttributeError):
        up.NO_SUCH_CONSTANT  # noqa: B018


def test_engine_template_blocks_are_placeholder_free():
    template = (ENGINE_ROOT / "knowledge-base" / "templates" / "AGENTS.md.template").read_text(encoding="utf-8")
    blocks = up.extract_managed_blocks(template)
    assert "INDEX" in blocks
    assert not any("{{" in block for block in blocks.values())


def test_managed_block_is_appended_and_idempotent(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My custom instructions\n", encoding="utf-8")

    assert _update(agents, "VIEW", VIEW, dry_run=True).action == "would be appended"
    assert "!view" not in agents.read_text(encoding="utf-8")
    assert _update(agents, "VIEW", VIEW).action == "appended"
    first = agents.read_text(encoding="utf-8")
    assert first.startswith("# My custom instructions\n") and first.count(VIEW) == 1
    assert _update(agents, "VIEW", VIEW).state == "up_to_date"
    assert agents.read_text(encoding="utf-8") == first


def test_status_block_is_inserted_after_the_index_block(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"# Mine\n\n{INDEX}\n\n## Commands\n", encoding="utf-8")

    assert _update(agents, "STATUS", STATUS).action == "inserted after the INDEX block"
    assert agents.read_text(encoding="utf-8") == f"# Mine\n\n{INDEX}\n\n{STATUS}\n\n## Commands\n"


def test_missing_agents_file_is_created_with_the_block(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    assert _update(agents, "INDEX", INDEX).action == "created"
    assert agents.read_text(encoding="utf-8") == f"{INDEX}\n"


def test_block_missing_from_the_template_is_skipped(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Mine\n", encoding="utf-8")
    result = _update(agents, "STATUS", None)
    assert result.state == "no_reference" and not result.sidecar
    assert agents.read_text(encoding="utf-8") == "# Mine\n"


def test_known_old_block_is_replaced(tmp_path: Path):
    old = _block("INDEX", "### Index loading rules (old wording)")
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"# Mine\n\n{old}\n", encoding="utf-8")
    known = up.KnownHashes(blocks={"INDEX": {up.block_digest(old): ["0.6.0"]}})

    assert _update(agents, "INDEX", INDEX, base="0.6.0", known=known).action == "updated"
    assert agents.read_text(encoding="utf-8") == f"# Mine\n\n{INDEX}\n"


def test_local_block_edit_on_an_unchanged_reference_is_kept_silently(tmp_path: Path):
    """Q4 / D12: no merge when the reference did not change since the base's version."""
    edited = INDEX.replace("Route first", "Route first (our team: ask Olga)")
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"# Mine\n\n{edited}\n", encoding="utf-8")
    known = up.KnownHashes(blocks={"INDEX": {up.block_digest(INDEX): ["0.5.0", "0.7.0"]}})

    result = _update(agents, "INDEX", INDEX, base="0.5.0", known=known)

    assert result.state == "edited" and not result.sidecar
    assert "kept" in result.action
    assert not (tmp_path / "AGENTS.md.index-block.new").exists()
    assert agents.read_text(encoding="utf-8") == f"# Mine\n\n{edited}\n"


def test_block_merge_is_requested_once_and_the_upgrade_converges(tmp_path: Path, monkeypatch, capsys):
    """Q4 / E-H7: a merged block no longer blocks anything on the next run."""
    _setup_fake_repo(tmp_path, monkeypatch)
    old_index = _block("INDEX", "### Index loading rules\n\n- Load everything.")
    _write_known(tmp_path, blocks={"INDEX": {old_index: ["0.5.0"], INDEX: ["0.7.0"]}})
    edited = old_index.replace("Load everything.", "Load everything. (MINE)")
    base = _base(tmp_path, version="0.5.0", agents=f"# Local\n\n{edited}\n\n{STATUS}\n\n{VIEW}\n")
    sidecar = base / "AGENTS.md.index-block.new"

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    assert sidecar.read_text(encoding="utf-8") == f"{INDEX}\n"
    assert "AI merge required" in capsys.readouterr().out
    assert _config(base)["instructions_version"] == "0.7.0"   # blocks never hold the bump
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2   # merge still pending
    assert "AI merge pending" in capsys.readouterr().out

    merged = INDEX.replace("Route first", "Route first (MINE)")
    agents = base / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8").replace(edited, merged), encoding="utf-8")
    sidecar.unlink()

    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    assert not sidecar.exists()
    assert merged in agents.read_text(encoding="utf-8")
    assert "the reference was merged" in capsys.readouterr().out

    # A copy of the reference that turns up again later is a leftover, not a
    # new merge request (Q4: it used to exit 2 on every run).
    sidecar.write_text(f"{INDEX}\n", encoding="utf-8")
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
    assert not sidecar.exists()
    assert merged in agents.read_text(encoding="utf-8")


def test_a_leftover_block_sidecar_on_an_unchanged_reference_is_removed(tmp_path: Path, monkeypatch, capsys):
    """Q4: the pre-0.16 upgrader left AGENTS.md.<label>-block.new behind for a
    reference the local block already builds on — it must not exit 2 forever."""
    _setup_fake_repo(tmp_path, monkeypatch)
    older = _block("INDEX", "### Index loading rules\n\n- Load everything.")
    _write_known(tmp_path, blocks={"INDEX": {older: ["0.4.0"], INDEX: ["0.5.0", "0.7.0"]}})
    edited = INDEX.replace("Route first", "Route first (MY LOCAL INDEX RULE)")
    base = _base(tmp_path, version="0.5.0", agents=f"# Local\n\n{edited}\n\n{STATUS}\n\n{VIEW}\n")
    sidecar = base / "AGENTS.md.index-block.new"

    for leftover in (f"{INDEX}\n", f"{older}\n"):
        sidecar.write_text(leftover, encoding="utf-8")
        assert up.main(["--kb-root", str(base), "--no-heal"]) == 0
        output = capsys.readouterr().out
        assert not sidecar.exists()
        assert "removed AGENTS.md.index-block.new" in output
        assert edited in (base / "AGENTS.md").read_text(encoding="utf-8")

    # A sidecar that is not an engine copy is left alone.
    sidecar.write_text("my notes\n", encoding="utf-8")
    assert up.main(["--kb-root", str(base), "--no-heal"]) == 2
    assert "AI merge pending" in capsys.readouterr().out
    assert sidecar.read_text(encoding="utf-8") == "my notes\n"


def test_inserting_a_missing_block_drops_a_leftover_sidecar(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Mine\n", encoding="utf-8")
    sidecar = tmp_path / "AGENTS.md.view-block.new"
    sidecar.write_text(f"{VIEW}\n", encoding="utf-8")

    assert _update(agents, "VIEW", VIEW).action == "appended; removed AGENTS.md.view-block.new"
    assert not sidecar.exists()


def test_malformed_markers_get_a_sidecar(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    begin, _ = up.block_markers("INDEX")
    agents.write_text(f"# Mine\n\n{begin}\nno end marker here\n", encoding="utf-8")

    result = _update(agents, "INDEX", INDEX)

    assert result.state == "malformed"
    assert result.action.startswith("AI merge required (markers damaged)")
    assert "no end marker here" in agents.read_text(encoding="utf-8")
    assert (tmp_path / "AGENTS.md.index-block.new").is_file()


def test_crlf_agents_file_keeps_its_line_endings(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_bytes(b"# Mine\r\n")
    _update(agents, "VIEW", VIEW)
    raw = agents.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_upgrade_never_overwrites_invariant_blocks(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    custom = (
        '<!-- AI-KE:INVARIANT:BEGIN id="forbidden" -->\n'
        "## Forbidden\n- CUSTOM privacy rule\n"
        '<!-- AI-KE:INVARIANT:END id="forbidden" -->\n'
        '<!-- AI-KE:INVARIANT:BEGIN id="language" -->\n'
        "## Language\nru only\n"
        '<!-- AI-KE:INVARIANT:END id="language" -->\n'
    )
    agents.write_text(custom, encoding="utf-8")

    state, action = up.report_invariant_blocks(agents)
    assert state == "present"
    assert "never overwritten" in action

    _update(agents, "INDEX", INDEX)
    text = agents.read_text(encoding="utf-8")
    assert text.startswith('<!-- AI-KE:INVARIANT:BEGIN id="forbidden" -->')
    assert "CUSTOM privacy rule" in text and "ru only" in text


def test_upgrade_does_not_insert_missing_invariants(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Local\n## Forbidden\n- x\n", encoding="utf-8")
    state, action = up.report_invariant_blocks(agents)
    assert state == "missing"
    assert "heal" in action.lower()
    assert "AI-KE:INVARIANT" not in agents.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# kb.config.yml
# ---------------------------------------------------------------------------


def test_ensure_index_section_appends_once_and_keeps_comments(tmp_path: Path):
    cfg = tmp_path / "kb.config.yml"
    cfg.write_text("# my notes\nknowledge_base:\n  name: t   # keep me\n", encoding="utf-8")

    assert up.kb_config_index_state(tmp_path) == "missing"
    assert up.ensure_index_section(tmp_path, dry_run=True) == "would append"
    assert "index:" not in cfg.read_text(encoding="utf-8")

    assert up.ensure_index_section(tmp_path, dry_run=False) == "appended"
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# my notes\nknowledge_base:\n  name: t   # keep me\n")
    assert yaml.safe_load(text)["index"]["packs"] == "auto"
    assert "see kb-docs/05_INDEX.md" in text   # D5: the base has no root-level modules
    assert up.kb_config_index_state(tmp_path) == "present"
    assert up.ensure_index_section(tmp_path, dry_run=False) == "skipped (present)"
    assert cfg.read_text(encoding="utf-8") == text


def test_bump_keeps_the_trailing_comment(tmp_path: Path):
    """Q-LOW: `_bump_deployed_version` used to drop the comment on the line."""
    cfg = tmp_path / "kb.config.yml"
    cfg.write_text('instructions_version: "0.5.0"   # set by kb_upgrade\nmode: x\n', encoding="utf-8")

    assert up._bump_deployed_version(tmp_path, "0.7.0") is True

    assert cfg.read_text(encoding="utf-8") == 'instructions_version: "0.7.0"   # set by kb_upgrade\nmode: x\n'


def test_upgrade_survives_an_unparseable_config(tmp_path: Path, monkeypatch, capsys):
    """A YAML typo must not abort the file sync with a traceback."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path, extra='  name "unquoted-and-unkeyed"\n')
    (base / "scripts" / "kb_heal.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    before = (base / "kb.config.yml").read_text(encoding="utf-8")

    result = up.main(["--kb-root", str(base)])
    output = capsys.readouterr().out

    assert result == 2
    assert "heal skipped" in output.lower()
    assert "Fix kb.config.yml" in output
    assert "kb.config.yml does not parse" in output
    assert (base / "kb.config.yml").read_text(encoding="utf-8") == before
    assert (base / "scripts" / "kb_lint.py").read_text(encoding="utf-8") == "new\n"


def test_discover_kb_roots_scans_only_configured_kb_directories(tmp_path: Path):
    (tmp_path / "kb-one").mkdir()
    (tmp_path / "kb-one" / "kb.config.yml").write_text("", encoding="utf-8")
    (tmp_path / "kb-two").mkdir()
    (tmp_path / "kb-two" / "kb.config.yml").write_text("", encoding="utf-8")
    (tmp_path / "kb-no-config").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "kb.config.yml").write_text("", encoding="utf-8")

    assert [path.name for path in up.discover_kb_roots(tmp_path)] == ["kb-one", "kb-two"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def test_get_repo_version_reads_file(tmp_path: Path, monkeypatch):
    _setup_fake_repo(tmp_path, monkeypatch)
    assert up.get_repo_version() == "0.7.0"


def test_get_deployed_version_missing_config(tmp_path: Path):
    assert up.get_deployed_version(tmp_path) == "missing"


def test_get_deployed_version_reads_config(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        'instructions_version: "0.5.0"\nknowledge_base:\n  name: x\n', encoding="utf-8"
    )
    assert up.get_deployed_version(tmp_path) == "0.5.0"


def test_compute_plan_up_to_date(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    shutil.copy2(src, dst)
    assert up.compute_plan(src, dst, prev_version="0.5.0", force=False).state == "up_to_date"


def test_compute_plan_treats_crlf_and_lf_as_up_to_date(tmp_path: Path):
    src = tmp_path / "source.py"
    dst = tmp_path / "deployed.py"
    src.write_bytes(b"print('one')\nprint('two')\n")
    dst.write_bytes(b"print('one')\r\nprint('two')\r\n")
    assert up.compute_plan(src, dst, prev_version="unknown", force=False).state == "up_to_date"


def test_compute_plan_missing(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    plan = up.compute_plan(src, tmp_path / "deployed" / "kb_lint.py", prev_version="0.5.0", force=False)
    assert plan.state == "missing"


def test_compute_plan_customized_when_force_false(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 1\n# user customization\n", encoding="utf-8")
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    assert plan.state == "customized"
    assert plan.diff_lines > 0


def test_compute_plan_force_takes_upstream(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 99\n", encoding="utf-8")
    assert up.compute_plan(src, dst, prev_version="0.5.0", force=True).state == "accepted"


def test_apply_plan_dry_run_does_not_touch_dst(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="missing")
    assert "would" in up.apply_plan(plan, dry_run=True).lower()
    assert not dst.exists()


def test_apply_plan_creates_missing_file_and_marks_wrappers_executable(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "shell" / "lint.sh"
    src.write_text("#!/bin/sh\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "shell" / "lint.sh"
    plan = up.UpgradePlan(name="shell/lint.sh", src=src, dst=dst, state="missing")
    assert "copied" in up.apply_plan(plan, dry_run=False).lower()
    assert dst.read_text() == "#!/bin/sh\n"
    if sys.platform != "win32":
        assert dst.stat().st_mode & 0o111


def test_apply_plan_clean_overwrite(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("old\n", encoding="utf-8")
    up.apply_plan(up.UpgradePlan(name=src.name, src=src, dst=dst, state="clean_overwrite"), dry_run=False)
    assert dst.read_text() == "new\n"


def test_apply_plan_customized_writes_new_sidecar(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("old + customizations\n", encoding="utf-8")
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="customized")
    msg = up.apply_plan(plan, dry_run=False)
    assert dst.with_suffix(".py.new").read_text() == "new\n"
    assert dst.read_text() == "old + customizations\n"
    assert "WROTE" in msg and "--accept-local kb_lint.py" in msg


def test_main_dry_run_never_claims_sidecars_were_created(tmp_path: Path, monkeypatch, capsys):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path)
    (base / "scripts" / "kb_lint.py").write_text("custom\n", encoding="utf-8")

    result = up.main(["--kb-root", str(base), "--dry-run"])
    output = capsys.readouterr().out

    assert result == 2
    assert "wrote no .new sidecars" in output
    assert not list(base.rglob("*.new"))
    assert not (base / ".kb-state").exists()
    assert "!view" not in (base / "AGENTS.md").read_text(encoding="utf-8")


def test_main_selective_accept_updates_file_blocks_and_version(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text("new\n", encoding="utf-8")
    base = _base(tmp_path)
    target = base / "scripts" / "kb_lint.py"
    target.write_text("custom\n", encoding="utf-8")

    assert up.main(["--kb-root", str(base), "--no-heal", "--accept", "kb_lint.py"]) == 0

    assert target.read_text(encoding="utf-8") == "new\n"
    assert 'instructions_version: "0.7.0"' in (base / "kb.config.yml").read_text(encoding="utf-8")
    agents = (base / "AGENTS.md").read_text(encoding="utf-8")
    assert VIEW in agents and f"{INDEX}\n\n{STATUS}" in agents


def test_unknown_accept_name_is_reported(tmp_path: Path, monkeypatch, capsys):
    _setup_fake_repo(tmp_path, monkeypatch)
    base = _base(tmp_path)
    up.main(["--kb-root", str(base), "--no-heal", "--accept-local", "kb_nope.py"])
    assert "--accept-local kb_nope.py: no managed file by that name" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["kept", "held", "accepted_local"])
def test_apply_plan_never_writes_for_waiting_or_kept_files(tmp_path: Path, state: str):
    src = tmp_path / "src.py"
    dst = tmp_path / "dst.py"
    src.write_text("new\n", encoding="utf-8")
    dst.write_text("mine\n", encoding="utf-8")
    plan = up.UpgradePlan(name="dst.py", src=src, dst=dst, state=state, held_by="kb_common.py")
    up.apply_plan(plan, dry_run=False)
    assert dst.read_text(encoding="utf-8") == "mine\n"
    assert not (tmp_path / "dst.py.new").exists()
