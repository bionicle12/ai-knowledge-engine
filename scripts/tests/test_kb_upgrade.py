"""Tests for scripts/kb_upgrade.py."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import kb_upgrade as up


def test_script_files_includes_all_shipped_kb_scripts():
    """Upgrade must sync every kb_*.py shipped under knowledge-base/scripts/."""
    shipped = {
        p.name
        for p in (up.SRC_SCRIPTS_DIR).glob("kb_*.py")
        if p.is_file()
    }
    listed = set(up.SCRIPT_FILES)
    missing = shipped - listed
    assert not missing, f"SCRIPT_FILES missing: {sorted(missing)}"
    assert "kb_save_session.py" in listed


def test_collect_plans_recursively_includes_viewer_bundle(
    tmp_path: Path, monkeypatch
):
    """Dropping a nested viewer asset must add it to deployed upgrade plans."""
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    viewer = repo / "knowledge-base" / "scripts" / "kb_viewer"
    (viewer / "vendor").mkdir(parents=True)
    (viewer / "index.html").write_text("<main></main>", encoding="utf-8")
    (viewer / "vendor" / "graph.js").write_text("graph();", encoding="utf-8")
    deployed = tmp_path / "deployed"

    plans = up.collect_plans(
        deployed,
        prev_version="0.7.0",
        force=False,
    )

    viewer_plans = {
        plan.name: plan.dst.relative_to(deployed).as_posix()
        for plan in plans
        if plan.name.startswith("kb_viewer/")
    }
    assert viewer_plans == {
        "kb_viewer/index.html": "scripts/kb_viewer/index.html",
        "kb_viewer/vendor/graph.js": "scripts/kb_viewer/vendor/graph.js",
    }


def test_collect_plans_keeps_posix_wrappers_in_shell_directory(
    tmp_path: Path, monkeypatch
):
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


def test_collect_plans_can_accept_one_customized_file_only(
    tmp_path: Path, monkeypatch
):
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
        tmp_path / "deployed",
        prev_version="0.0.0",
        force=False,
        accepted={"kb_stt.py"},
    )
    states = {plan.name: plan.state for plan in plans}

    assert states["kb_stt.py"] == "clean_overwrite"
    assert states["kb_lint.py"] == "customized"


def test_managed_view_block_is_appended_and_replaced_idempotently(
    tmp_path: Path,
):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My custom instructions\n", encoding="utf-8")

    assert up.managed_view_block_state(agents) == "missing"
    assert up.update_managed_view_block(agents, dry_run=True) == "would append"
    assert "!view" not in agents.read_text(encoding="utf-8")

    assert up.update_managed_view_block(agents, dry_run=False) == "appended"
    first = agents.read_text(encoding="utf-8")
    assert "# My custom instructions" in first
    assert first.count(up.VIEW_BLOCK_BEGIN) == 1
    assert up.managed_view_block_state(agents) == "up_to_date"

    # A locally customized block is NEVER overwritten: AGENTS.md is a live
    # file agents evolve while working — the upgrade writes a .new sidecar
    # and asks the user's AI agent to merge instead.
    customized = first.replace("python3 scripts/kb_view.py", "python MINE.py")
    agents.write_text(customized, encoding="utf-8")
    assert up.managed_view_block_state(agents) == "outdated"
    action = up.update_managed_view_block(agents, dry_run=False)
    assert action.startswith("AI merge required (local edits kept)")
    assert agents.read_text(encoding="utf-8") == customized  # untouched
    sidecar = agents.with_name("AGENTS.md.view-block.new")
    assert sidecar.is_file()
    assert up.VIEW_BLOCK in sidecar.read_text(encoding="utf-8")


def test_managed_index_block_matches_agents_template():
    template = (
        up.SRC_TEMPLATES_DIR / "AGENTS.md.template"
    ).read_text(encoding="utf-8")
    start = template.index(up.INDEX_BLOCK_BEGIN)
    end = template.index(up.INDEX_BLOCK_END) + len(up.INDEX_BLOCK_END)
    assert template[start:end] == up.INDEX_BLOCK


def test_managed_index_block_is_appended_and_replaced_idempotently(
    tmp_path: Path,
):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My custom instructions\n", encoding="utf-8")

    assert up.managed_index_block_state(agents) == "missing"
    assert up.update_managed_index_block(agents, dry_run=False) == "appended"
    first = agents.read_text(encoding="utf-8")
    assert "# My custom instructions" in first
    assert first.count(up.INDEX_BLOCK_BEGIN) == 1
    assert up.managed_index_block_state(agents) == "up_to_date"
    assert (
        up.update_managed_index_block(agents, dry_run=False)
        == "skipped (up to date)"
    )

    # Local customization -> sidecar + AI merge, original preserved.
    customized = first.replace("routing-table.md", "MY-ROUTING.md")
    agents.write_text(customized, encoding="utf-8")
    assert up.managed_index_block_state(agents) == "outdated"
    action = up.update_managed_index_block(agents, dry_run=False)
    assert action.startswith("AI merge required (local edits kept)")
    assert agents.read_text(encoding="utf-8") == customized


def test_managed_block_auto_updates_known_previous_version(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    old_block = (
        f"{up.INDEX_BLOCK_BEGIN}\n### Index loading rules (old wording)\n"
        f"{up.INDEX_BLOCK_END}"
    )
    agents.write_text(f"# Mine\n\n{old_block}\n", encoding="utf-8")

    action = up._update_managed_block(
        agents,
        up.INDEX_BLOCK_BEGIN,
        up.INDEX_BLOCK_END,
        up.INDEX_BLOCK,
        label="index",
        previous=(old_block,),
        dry_run=False,
    )

    assert action == "updated"
    text = agents.read_text(encoding="utf-8")
    assert "old wording" not in text
    assert up.INDEX_BLOCK in text
    assert "# Mine" in text


def test_managed_block_malformed_markers_get_sidecar(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        f"# Mine\n\n{up.INDEX_BLOCK_BEGIN}\nno end marker here\n",
        encoding="utf-8",
    )

    assert up.managed_index_block_state(agents) == "malformed"
    action = up.update_managed_index_block(agents, dry_run=False)
    assert action.startswith("AI merge required (markers damaged)")
    assert "no end marker here" in agents.read_text(encoding="utf-8")
    assert agents.with_name("AGENTS.md.index-block.new").is_file()


def test_ensure_index_section_appends_once(tmp_path: Path):
    cfg = tmp_path / "kb.config.yml"
    cfg.write_text("knowledge_base:\n  name: t\n", encoding="utf-8")

    assert up.kb_config_index_state(tmp_path) == "missing"
    assert up.ensure_index_section(tmp_path, dry_run=True) == "would append"
    assert "index:" not in cfg.read_text(encoding="utf-8")

    assert up.ensure_index_section(tmp_path, dry_run=False) == "appended"
    text = cfg.read_text(encoding="utf-8")
    assert "index:" in text
    assert "packs: auto" in text
    assert up.kb_config_index_state(tmp_path) == "present"
    assert up.ensure_index_section(tmp_path, dry_run=False) == "skipped (present)"
    assert cfg.read_text(encoding="utf-8") == text


def test_discover_kb_roots_scans_only_configured_kb_directories(tmp_path: Path):
    (tmp_path / "kb-one").mkdir()
    (tmp_path / "kb-one" / "kb.config.yml").write_text("", encoding="utf-8")
    (tmp_path / "kb-two").mkdir()
    (tmp_path / "kb-two" / "kb.config.yml").write_text("", encoding="utf-8")
    (tmp_path / "kb-no-config").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "kb.config.yml").write_text("", encoding="utf-8")

    assert [path.name for path in up.discover_kb_roots(tmp_path)] == [
        "kb-one",
        "kb-two",
    ]


def test_file_hash_matches_for_identical(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello\n", encoding="utf-8")
    b.write_text("hello\n", encoding="utf-8")
    assert up.file_hash(a) == up.file_hash(b)


def test_file_hash_empty_string_for_missing():
    p = Path("/tmp/__definitely_not_a_real_file__")
    assert up.file_hash(p) == ""


def test_file_hash_changes_with_content(tmp_path: Path):
    a = tmp_path / "a.txt"
    a.write_text("one", encoding="utf-8")
    h1 = up.file_hash(a)
    a.write_text("two", encoding="utf-8")
    h2 = up.file_hash(a)
    assert h1 != h2


def _setup_fake_repo(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake source repo layout so kb_upgrade can resolve paths."""
    (tmp_path / "knowledge-base" / "scripts").mkdir(parents=True)
    (tmp_path / "knowledge-base" / "shell").mkdir(parents=True)
    (tmp_path / "VERSION").write_text("0.7.0\n", encoding="utf-8")
    monkeypatch.setattr(up, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(up, "SRC_SCRIPTS_DIR", tmp_path / "knowledge-base" / "scripts")
    monkeypatch.setattr(up, "SRC_SHELL_DIR", tmp_path / "knowledge-base" / "shell")
    monkeypatch.setattr(up, "VERSION_FILE", tmp_path / "VERSION")
    return tmp_path


def test_get_repo_version_reads_file(tmp_path: Path, monkeypatch):
    _setup_fake_repo(tmp_path, monkeypatch)
    assert up.get_repo_version() == "0.7.0"


def test_get_deployed_version_missing_config(tmp_path: Path):
    assert up.get_deployed_version(tmp_path) == "missing"


def test_get_deployed_version_reads_config(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        'instructions_version: "0.5.0"\nknowledge_base:\n  name: x\n',
        encoding="utf-8",
    )
    assert up.get_deployed_version(tmp_path) == "0.5.0"


def test_compute_plan_up_to_date(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    deployed_dir = tmp_path / "deployed"
    deployed_dir.mkdir()
    dst = deployed_dir / "kb_lint.py"
    shutil.copy2(src, dst)
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    assert plan.state == "up_to_date"


def test_compute_plan_treats_crlf_and_lf_as_up_to_date(tmp_path: Path):
    src = tmp_path / "source.py"
    dst = tmp_path / "deployed.py"
    src.write_bytes(b"print('one')\nprint('two')\n")
    dst.write_bytes(b"print('one')\r\nprint('two')\r\n")

    plan = up.compute_plan(src, dst, prev_version="unknown", force=False)

    assert plan.state == "up_to_date"


def test_compute_plan_missing(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    assert plan.state == "missing"


def test_compute_plan_customized_when_force_false(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 1\n# user customization\n", encoding="utf-8")
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    # Without git history available, it falls back to "customized"
    assert plan.state == "customized"
    assert plan.diff_lines > 0


def test_compute_plan_force_overwrites(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 99\n", encoding="utf-8")
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=True)
    assert plan.state == "clean_overwrite"


def test_apply_plan_dry_run_does_not_touch_dst(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="missing")
    msg = up.apply_plan(plan, dry_run=True)
    assert "would" in msg.lower()
    assert not dst.exists()


def test_apply_plan_creates_missing_file(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new content\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="missing")
    msg = up.apply_plan(plan, dry_run=False)
    assert dst.is_file()
    assert dst.read_text() == "new content\n"
    assert "copied" in msg.lower()


def test_apply_plan_clean_overwrite(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("old\n", encoding="utf-8")
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="clean_overwrite")
    up.apply_plan(plan, dry_run=False)
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
    sidecar = dst.with_suffix(dst.suffix + ".new")
    assert sidecar.is_file()
    assert sidecar.read_text() == "new\n"
    # Original is untouched
    assert dst.read_text() == "old + customizations\n"
    assert "WROTE" in msg or "wrote" in msg.lower()


def test_main_dry_run_never_claims_sidecars_were_created(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ("kb_lint.py",))
    monkeypatch.setattr(up, "SHELL_FILES", ())
    source = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    source.write_text("new\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    (deployed / "scripts").mkdir(parents=True)
    (deployed / "scripts" / "kb_lint.py").write_text(
        "custom\n", encoding="utf-8"
    )
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\n', encoding="utf-8"
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    result = up.main(["--kb-root", str(deployed), "--dry-run"])
    output = capsys.readouterr().out

    assert result == 2
    assert "wrote no .new sidecars" in output
    assert not list(deployed.rglob("*.new"))
    assert "!view" not in (deployed / "AGENTS.md").read_text(encoding="utf-8")


def test_main_selective_accept_updates_file_block_and_version(
    tmp_path: Path, monkeypatch
):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ("kb_lint.py",))
    monkeypatch.setattr(up, "SHELL_FILES", ())
    source = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    source.write_text("new\n", encoding="utf-8")
    deployed = tmp_path / "deployed"
    (deployed / "scripts").mkdir(parents=True)
    target = deployed / "scripts" / "kb_lint.py"
    target.write_text("custom\n", encoding="utf-8")
    config = deployed / "kb.config.yml"
    config.write_text('instructions_version: "0.0.0"\n', encoding="utf-8")
    agents = deployed / "AGENTS.md"
    agents.write_text("# Local\n", encoding="utf-8")

    result = up.main(
        ["--kb-root", str(deployed), "--accept", "kb_lint.py"]
    )

    assert result == 0
    assert target.read_text(encoding="utf-8") == "new\n"
    assert 'instructions_version: "0.7.0"' in config.read_text(encoding="utf-8")
    assert up.VIEW_BLOCK_BEGIN in agents.read_text(encoding="utf-8")


def test_upgrade_dry_run_does_not_write_heal_plan(
    tmp_path: Path, monkeypatch, capsys
):
    _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ())
    monkeypatch.setattr(up, "SHELL_FILES", ())
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\nknowledge_base:\n  mode: default\n',
        encoding="utf-8",
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    result = up.main(["--kb-root", str(deployed), "--dry-run"])
    output = capsys.readouterr().out
    assert result in (0, 2)
    assert not (deployed / "review" / "needs-heal" / "HEAL_PLAN.md").is_file()
    assert "!heal" in output or "heal" in output.lower()


def test_upgrade_runs_heal_when_customized(tmp_path: Path, monkeypatch, capsys):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ("kb_lint.py",))
    monkeypatch.setattr(up, "SHELL_FILES", ())
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text(
        "new\n", encoding="utf-8"
    )
    deployed = tmp_path / "deployed"
    (deployed / "scripts").mkdir(parents=True)
    (deployed / "scripts" / "kb_lint.py").write_text("custom\n", encoding="utf-8")
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\nknowledge_base:\n  mode: default\n',
        encoding="utf-8",
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    result = up.main(["--kb-root", str(deployed)])
    output = capsys.readouterr().out
    assert result == 2
    assert (deployed / "review" / "needs-heal" / "HEAL_PLAN.md").is_file()
    assert "!heal" in output


def test_upgrade_no_heal_skips_plan(tmp_path: Path, monkeypatch, capsys):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ("kb_lint.py",))
    monkeypatch.setattr(up, "SHELL_FILES", ())
    (repo / "knowledge-base" / "scripts" / "kb_lint.py").write_text(
        "new\n", encoding="utf-8"
    )
    deployed = tmp_path / "deployed"
    (deployed / "scripts").mkdir(parents=True)
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\nknowledge_base:\n  mode: default\n',
        encoding="utf-8",
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    result = up.main(["--kb-root", str(deployed), "--no-heal"])
    output = capsys.readouterr().out
    assert result == 0
    assert not (deployed / "review" / "needs-heal" / "HEAL_PLAN.md").is_file()
    assert "Heal skipped" in output or "--no-heal" in output


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

    up.update_managed_index_block(agents, dry_run=False)
    assert agents.read_text(encoding="utf-8").startswith(
        '<!-- AI-KE:INVARIANT:BEGIN id="forbidden" -->'
    )
    assert "CUSTOM privacy rule" in agents.read_text(encoding="utf-8")
    assert "ru only" in agents.read_text(encoding="utf-8")


def test_upgrade_does_not_insert_missing_invariants(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Local\n## Forbidden\n- x\n", encoding="utf-8")
    state, action = up.report_invariant_blocks(agents)
    assert state == "missing"
    assert "heal" in action.lower()
    assert "AI-KE:INVARIANT" not in agents.read_text(encoding="utf-8")


def test_upgrade_survives_an_unparseable_config(tmp_path: Path, monkeypatch, capsys):
    """A YAML typo must not abort the file sync with a traceback."""
    _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ())
    monkeypatch.setattr(up, "SHELL_FILES", ())
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\nknowledge_base:\n  mode: default\n'
        '  name "unquoted-and-unkeyed"\n',
        encoding="utf-8",
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    result = up.main(["--kb-root", str(deployed)])
    output = capsys.readouterr().out
    assert result in (0, 2)
    assert "heal skipped" in output.lower()
    assert "kb.config.yml" in output


def test_upgrade_stamps_heal_last_run_with_the_new_version(
    tmp_path: Path, monkeypatch
):
    """Otherwise doctor warns 'version moved without heal' on a clean upgrade."""
    import yaml

    _setup_fake_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "SCRIPT_FILES", ())
    monkeypatch.setattr(up, "SHELL_FILES", ())
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / "kb.config.yml").write_text(
        'instructions_version: "0.0.0"\nknowledge_base:\n  mode: default\n',
        encoding="utf-8",
    )
    (deployed / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

    assert up.main(["--kb-root", str(deployed)]) == 0
    cfg = yaml.safe_load((deployed / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["instructions_version"] == cfg["heal"]["last_run"]["version"]
