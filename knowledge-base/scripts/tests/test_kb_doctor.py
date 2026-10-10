"""Smoke coverage for kb_doctor: the built-in self-test must stay green.

The CI reference pipeline used to run `kb_doctor.py --self-test`; with CI
intentionally disabled this pytest wrapper keeps it part of the local run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import kb_doctor

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
KIB = 1024


def test_doctor_self_test_passes():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "kb_doctor.py"),
            "--self-test",
            "--skip-nlp",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"kb_doctor self-test failed:\nstdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
    assert "0 error" in result.stdout


def test_doctor_help_runs():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "kb_doctor.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _by_name(results: list[kb_doctor.CheckResult]) -> dict[str, kb_doctor.CheckResult]:
    return {r.name: r for r in results}


def _healthy_base(tmp_path: Path) -> tuple[Path, Path]:
    """KB at git-root with a small AGENTS.md and an empty Codex home."""
    root = tmp_path / "kb"
    root.mkdir()
    _git_init(root)
    (root / "AGENTS.md").write_text("# small\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    return root, codex_home


def test_agent_env_healthy_base_is_clean(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    results = kb_doctor.check_agent_env(root, codex_home=codex_home)
    assert results, "expected the six Codex-environment checks"
    assert all(r.severity == "ok" for r in results), results


def test_agent_env_warns_when_agents_md_not_at_git_root(tmp_path: Path):
    git_root = tmp_path / "repo"
    kb = git_root / "nested-kb"
    kb.mkdir(parents=True)
    _git_init(git_root)
    (kb / "AGENTS.md").write_text("# nested only\n", encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(kb, codex_home=tmp_path / "empty"))
    check = results["agent-env:agents-at-git-root"]
    assert check.severity == "warn"
    assert "git" in check.message.lower()


def test_agent_env_errors_when_agents_md_missing(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.md").unlink()
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:agents-at-git-root"].severity == "error"


def test_agent_env_warns_when_agents_md_over_10kib(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.md").write_text("x" * (10 * KIB + 1), encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:agents-size"].severity == "warn"


def test_agent_env_warns_when_combined_agents_over_24kib(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.md").write_text("b" * (12 * KIB), encoding="utf-8")
    (codex_home / "AGENTS.md").write_text("g" * (13 * KIB), encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:codex-budget-75"].severity == "warn"
    assert results["agent-env:codex-budget-cap"].severity == "ok"


def test_agent_env_errors_when_combined_agents_over_32kib(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.md").write_text("b" * (16 * KIB), encoding="utf-8")
    (codex_home / "AGENTS.md").write_text("g" * (17 * KIB), encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:codex-budget-cap"].severity == "error"


def test_agent_env_errors_when_agents_override_present(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.override.md").write_text("override\n", encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:agents-override"].severity == "error"


def test_agent_env_warns_when_claude_md_missing_import(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "CLAUDE.md").write_text("# Claude-only copy\n", encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:claude-md-import"].severity == "warn"


def test_agent_env_ok_when_claude_md_imports_agents(tmp_path: Path):
    root, codex_home = _healthy_base(tmp_path)
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:claude-md-import"].severity == "ok"


def test_agent_env_warns_when_claude_code_has_no_claude_md(tmp_path: Path):
    """primary_agent: claude-code without CLAUDE.md = Claude Code never reads
    AGENTS.md; that is not "optional"."""
    root, codex_home = _healthy_base(tmp_path)
    (root / "kb.config.yml").write_text(
        'index:\n  primary_agent: "claude-code"\n', encoding="utf-8"
    )
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    check = results["agent-env:claude-md-import"]
    assert check.severity == "warn" and "@AGENTS.md" in check.message
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:claude-md-import"].severity == "ok"


def test_agent_env_counts_global_override_when_that_is_what_codex_loads(
    tmp_path: Path,
):
    root, codex_home = _healthy_base(tmp_path)
    (root / "AGENTS.md").write_text("b" * (16 * KIB), encoding="utf-8")
    (codex_home / "AGENTS.md").write_text("tiny\n", encoding="utf-8")
    (codex_home / "AGENTS.override.md").write_text("g" * (17 * KIB), encoding="utf-8")
    results = _by_name(kb_doctor.check_agent_env(root, codex_home=codex_home))
    assert results["agent-env:codex-budget-cap"].severity == "error"


def test_heal_warns_when_version_moved_without_heal(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    (root / "kb.config.yml").write_text(
        "instructions_version: \"0.15.0\"\n"
        "knowledge_base:\n  mode: default\n"
        "heal:\n  auto_apply: true\n  stage: 1\n"
        "  last_run:\n    at: 2026-01-01\n    version: \"0.11.0\"\n",
        encoding="utf-8",
    )
    results = _by_name(kb_doctor.check_heal(root))
    assert results["heal:after-upgrade"].severity == "warn"


def test_heal_warns_when_stage_stuck(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    (root / "kb.config.yml").write_text(
        "instructions_version: \"0.15.0\"\n"
        "knowledge_base:\n  mode: default\n"
        "heal:\n  auto_apply: true\n  stage: 3\n"
        "  last_run:\n    at: 2020-01-01\n    version: \"0.15.0\"\n",
        encoding="utf-8",
    )
    results = _by_name(kb_doctor.check_heal(root))
    assert results["heal:stage-stuck"].severity == "warn"


def test_check_mutations_kills_seven_l1(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    result = kb_doctor.check_mutations(root)
    assert result.severity == "ok"
    assert "7 mutations / 7 killed" in result.message


def test_self_test_does_not_run_mutations():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "kb_doctor.py"),
            "--self-test",
            "--skip-nlp",
            "--with-mutation",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "mutate:l1" not in result.stdout


# ---------------------------------------------------------------------------
# 0.16 audit regressions (Q18, D5, D8)
# ---------------------------------------------------------------------------


def _deployed_base(tmp_path: Path) -> Path:
    """A base with its own copy of the engine scripts (like a deployed one)."""
    root, _codex = _healthy_base(tmp_path)
    shutil.copytree(
        SCRIPTS_DIR, root / "scripts",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    return root


def test_doctor_never_writes_log(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    kb_doctor.run_all_checks(root, skip_nlp=True)
    assert not (root / "log.md").exists()
    (root / "log.md").write_text("# Operations Log\n", encoding="utf-8")
    kb_doctor.main(["--root", str(root), "--skip-nlp"])
    assert (root / "log.md").read_text(encoding="utf-8") == "# Operations Log\n"


def test_doctor_passes_with_warnings_only():
    warn = kb_doctor.CheckResult("x", "warn", "advice")
    ok = kb_doctor.CheckResult("y", "ok")
    error = kb_doctor.CheckResult("z", "error")
    assert kb_doctor.exit_code([ok, warn]) == 0
    assert kb_doctor.exit_code([ok, warn, error]) == 2
    assert "0 error — PASS (exit 0" in kb_doctor.render_text([ok, warn])
    assert "1 error — FAIL (exit 2" in kb_doctor.render_text([ok, warn, error])


def _which(available: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def test_repomix_missing_without_fallback_is_an_error(tmp_path: Path, monkeypatch):
    root, _codex = _healthy_base(tmp_path)
    monkeypatch.setattr(kb_doctor.shutil, "which", _which(set()))
    result = kb_doctor.check_repomix(root)
    assert result.severity == "error"
    assert "repomix@1.14.0" in result.message

    monkeypatch.setattr(kb_doctor.shutil, "which", _which({"npx", "node"}))
    assert kb_doctor.check_repomix(root).severity == "ok"

    (root / "kb.config.yml").write_text("index:\n  npx_fallback: false\n", encoding="utf-8")
    assert kb_doctor.check_repomix(root).severity == "error"

    monkeypatch.setattr(kb_doctor.shutil, "which", _which({"repomix"}))
    assert kb_doctor.check_repomix(root).severity == "ok"


def _packs_status(root: Path, rows: str) -> Path:
    status = root / ".repomix" / "PACKS_STATUS.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        "# Knowledge-base packs — build status\n\n"
        "| Pack | ~Tokens (o200k est.) | Last build | Load when |\n"
        "|------|----------------------|------------|-----------|\n"
        f"{rows}\nPack ceiling: 80,000 tokens. Route via routing-table.\n",
        encoding="utf-8",
    )
    return status


def test_packs_status_findings(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    assert kb_doctor.check_packs_status(root).severity == "warn"  # never built

    _packs_status(root, "| core | 7,000 | fresh | always |")
    assert kb_doctor.check_packs_status(root).severity == "ok"

    _packs_status(root, "| core | 7,000 | fresh | always |\n| domain | 0 | FAILED | x |")
    failed = kb_doctor.check_packs_status(root)
    assert failed.severity == "error" and failed.details == ["domain"]

    _packs_status(root, "| core | 95,000 | rebuilt | always |")
    over = kb_doctor.check_packs_status(root)
    assert over.severity == "warn" and "core" in over.details[0]

    status = _packs_status(root, "| core | 7,000 | fresh | always |")
    page = root / "knowledge" / "domain" / "new.md"
    page.parent.mkdir(parents=True)
    page.write_text("# new\n", encoding="utf-8")
    old = status.stat().st_mtime - 60
    os.utime(status, (old, old))
    stale = kb_doctor.check_packs_status(root)
    assert stale.severity == "warn" and "after the last reindex" in stale.message


def test_packs_status_warns_about_files_repomix_left_out(tmp_path: Path):
    """E-H3: a page repomix's security check dropped is not a healthy index."""
    root, _codex = _healthy_base(tmp_path)
    _packs_status(
        root,
        "| aux | 7,000 | rebuilt | x |\n\nLeft out by repomix (its security check found "
        "credential-looking text — …): aux: knowledge/domain/deploy.md.",
    )
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "warn" and "left files out" in result.message
    assert "knowledge/domain/deploy.md" in result.details[0]


# A layout with a Ceiling column of its own between ~Tokens and Last build
# (kb_reindex itself writes four columns; see test_packs_status_from_kb_reindex_itself).
PACKS_STATUS_0_16 = """# Knowledge-base packs — build status

Auto-generated by kb_reindex.py. Do not edit.
Checked: 2026-09-24T10:00:00+03:00 · builder: repomix

| Pack | ~Tokens (o200k est.) | Ceiling | Last build | Load when |
|------|----------------------|---------|------------|-----------|
{rows}

Pack ceiling: 80,000 tokens. OVER ceiling: 0 · FAILED: 0 · STALE: 0.
Route via knowledge/routing-table.md; load AT MOST ONE domain pack per task.
"""


def _packs_status_0_16(root: Path, *rows: str) -> None:
    status = root / ".repomix" / "PACKS_STATUS.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(PACKS_STATUS_0_16.format(rows="\n".join(rows)), encoding="utf-8")


def test_packs_status_reads_the_0_16_rows(tmp_path: Path):
    """FAILED / STALE / OVER are found by column name, not by position."""
    root, _codex = _healthy_base(tmp_path)
    failed = "| core | 7,000 | ok | FAILED; copy from 2026-09-20T10:00 kept | always |"
    stale = "| domain | 1,200 | ok | STALE — repomix unavailable | domain \\| ops |"
    over = "| aux | 900 | ⚠ OVER | rebuilt 2026-09-24T10:00 | rarely |"
    fresh = "| extra | 800 | ok | fresh (built 2026-09-24T10:00) | x |"
    _packs_status_0_16(root, failed, stale, over, fresh)
    result = kb_doctor.check_packs_status(root)
    assert (result.severity, result.details) == ("error", ["core"])

    _packs_status_0_16(root, stale, over, fresh)
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "warn"
    assert result.details == ["aux (~900 tokens)", "domain"]
    assert "not rebuilt" in result.message and "over the ceiling" in result.message

    _packs_status_0_16(root, fresh)
    assert kb_doctor.check_packs_status(root).severity == "ok"


def test_packs_status_index_not_built_or_unreadable(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    status = root / ".repomix" / "PACKS_STATUS.md"
    _packs_status_0_16(root)
    text = status.read_text(encoding="utf-8").replace(
        "\n| Pack", "\n**Index not built:** invalid repomix.config.json\n\n| Pack", 1
    )
    status.write_text(text, encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "error" and "invalid repomix.config.json" in result.message

    status.write_text("# packs\n\nsomething else entirely\n", encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "warn" and "no pack rows" in result.message


def test_packs_status_from_kb_reindex_itself(tmp_path: Path):
    """Round trip through the real writer: doctor reads what kb_reindex writes."""
    import kb_reindex

    render = kb_reindex.render_packs_status
    root, _codex = _healthy_base(tmp_path)
    manifest = {
        "ceiling": 80000, "checked_at": "2026-09-24T10:00:00+03:00", "builder": "repomix",
        "packs": {
            "core": {"state": "FAILED", "tokens": 7000, "when_to_load": "always"},
            "domain": {"state": "STALE", "tokens": 1200, "when_to_load": "domain"},
            "aux": {"state": "rebuilt", "tokens": 900, "over_ceiling": True,
                    "built_at": "x", "when_to_load": "rarely"},
        },
    }
    status = root / ".repomix" / "PACKS_STATUS.md"
    status.parent.mkdir(parents=True)
    status.write_text(render(root, manifest), encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert (result.severity, result.details) == ("error", ["core"])
    manifest["packs"]["core"]["state"] = "fresh"
    status.write_text(render(root, manifest), encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "warn"
    assert result.details == ["aux (~900 tokens)", "domain"]

    # Legacy mode: one monolith row; a build that stopped as a whole.
    legacy = {
        "mode": "legacy", "ceiling": 150000, "checked_at": "x", "builder": "repomix",
        "legacy": {"state": "FAILED", "tokens": 0, "output": ".repomix/output.xml"},
    }
    status.write_text(render(root, legacy), encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert (result.severity, result.details) == ("error", ["output.xml (legacy monolith)"])
    legacy["legacy"].update(state="rebuilt", tokens=1000, built_at="x")
    status.write_text(render(root, legacy), encoding="utf-8")
    assert kb_doctor.check_packs_status(root).severity == "ok"
    status.write_text(render(root, {**manifest, "error": "no knowledge/ pages"}), encoding="utf-8")
    result = kb_doctor.check_packs_status(root)
    assert result.severity == "error" and "no knowledge/ pages" in result.message


def test_hanging_sidecars_are_reported(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    assert kb_doctor.check_sidecars(root).severity == "ok"
    (root / "scripts").mkdir()
    (root / "scripts" / "kb_lint.py.new").write_text("x", encoding="utf-8")
    (root / "AGENTS.md.INDEX-block.new").write_text("x", encoding="utf-8")
    result = kb_doctor.check_sidecars(root)
    assert result.severity == "warn"
    assert result.details == ["AGENTS.md.INDEX-block.new", "scripts/kb_lint.py.new"]


def test_scripts_consistency_ok_for_matching_scripts(tmp_path: Path, monkeypatch):
    root = _deployed_base(tmp_path)
    assert kb_doctor.check_scripts(root).severity == "ok"
    monkeypatch.chdir(tmp_path)  # `--root kb` from the parent folder
    assert kb_doctor.check_scripts(Path(root.name)).severity == "ok"


def test_scripts_consistency_catches_partial_upgrade(tmp_path: Path):
    root = _deployed_base(tmp_path)
    common = root / "scripts" / "kb_common.py"
    # A customized, older kb_common.py kept while the other scripts moved on.
    common.write_text(
        common.read_text(encoding="utf-8") + "\ndel invariant_problems\n", encoding="utf-8"
    )
    (root / "scripts" / "kb_route.py").write_text("def broken(:\n", encoding="utf-8")
    result = kb_doctor.check_scripts(root)
    assert result.severity == "error"
    joined = "\n".join(result.details)
    assert "kb_lint.py uses kb_common.invariant_problems" in joined
    assert "kb_route.py does not import: SyntaxError" in joined


def test_doctor_reports_partial_upgrade_instead_of_crashing(tmp_path: Path):
    """The Q6 scenario end to end: the base keeps its customized, older
    kb_common.py (kb_common.py.new beside it) while the other scripts were
    updated. The base's own doctor must run, name the mismatch and exit 2 —
    not die at import with a traceback and exit 1."""
    root = _deployed_base(tmp_path)
    scripts = root / "scripts"
    common = scripts / "kb_common.py"
    (scripts / "kb_common.py.new").write_text(common.read_text(encoding="utf-8"),
                                              encoding="utf-8")
    common.write_text(
        common.read_text(encoding="utf-8")
        + "\ndel KB_DOCS_DIR\ndel LIFECYCLES\n",
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-B", str(scripts / "kb_doctor.py"), "--root", str(root),
         "--skip-nlp"],
        capture_output=True, text=True, timeout=180, env=env,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 2, out
    assert "Traceback" not in out
    assert "❌ scripts:consistency: engine scripts do not match" in out
    assert "kb_lint.py does not import: ImportError: scripts/kb_common.py is older" in out
    assert "kb_doctor.py uses kb_common.KB_DOCS_DIR" not in out  # doctor copes
    assert "upgrade:sidecars" in out and "kb_common.py.new" in out
    assert "check crashed" not in out


def test_repomix_check_reads_a_pre_0_16_config(tmp_path: Path, monkeypatch):
    """An older kb_common.KbConfig has no index_* attributes (partial
    upgrade): the check falls back to the raw `index:` section."""
    import types

    old_cfg = types.SimpleNamespace(index={"repomix_version": "1.2.3"})
    monkeypatch.setattr(kb_doctor, "_config_or_defaults", lambda root: old_cfg)
    monkeypatch.setattr(kb_doctor.shutil, "which", _which(set()))
    result = kb_doctor.check_repomix(tmp_path)
    assert result.severity == "error" and "repomix@1.2.3" in result.message
    monkeypatch.setattr(kb_doctor.shutil, "which", _which({"npx", "node"}))
    assert kb_doctor.check_repomix(tmp_path).severity == "ok"


def test_kb_docs_references_must_exist(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    assert kb_doctor.check_kb_docs(root).severity == "warn"  # pre-0.16 base
    (root / "AGENTS.md").write_text(
        "`!heal` → read kb-docs/18_HEAL.md; `!merge` → kb-docs/16_MERGE.md\n",
        encoding="utf-8",
    )
    missing = kb_doctor.check_kb_docs(root)
    assert missing.severity == "error"
    assert missing.details == [
        "kb-docs/16_MERGE.md (referenced by AGENTS.md)",
        "kb-docs/18_HEAL.md (referenced by AGENTS.md)",
    ]
    (root / "kb-docs").mkdir()
    for name in ("16_MERGE.md", "18_HEAL.md"):
        (root / "kb-docs" / name).write_text("# m\n", encoding="utf-8")
    assert kb_doctor.check_kb_docs(root).severity == "ok"


def test_no_base_venv_is_a_warning_not_ok(tmp_path: Path, monkeypatch):
    """E-H8: without <base>/.venv the wrappers run python3, so NLP and the
    other optional packages go unused — doctor must not call that ok."""
    root, _codex = _healthy_base(tmp_path)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)  # not in any venv
    [missing] = kb_doctor.check_venv(root)
    assert (missing.name, missing.severity) == ("venv:missing", "warn")
    assert "01_PREREQUISITES" in missing.message

    # Doctor itself runs in a venv outside the base: the wrappers never use it.
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "elsewhere" / ".venv"))
    [running] = kb_doctor.check_venv(root)
    assert (running.name, running.severity) == ("venv:stranded", "warn")

    # The old 01 left the venv in knowledge-base/ after finalize.
    (root / "knowledge-base" / ".venv").mkdir(parents=True)
    (root / "knowledge-base" / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    [left] = kb_doctor.check_venv(root)
    assert (left.name, left.severity) == ("venv:stranded", "warn")
    assert "knowledge-base/.venv" in left.message


def test_venv_problems_are_detected(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)

    venv = root / ".venv"
    (venv / ".venv").mkdir(parents=True)
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    bindir.mkdir()
    (bindir / "activate").write_text(  # the Python 3.12 layout, Cygwin branch first
        'if [ "${OSTYPE:-}" = "cygwin" ] ; then\n'
        "    export VIRTUAL_ENV=$(cygpath /somewhere/else/knowledge-base/.venv)\n"
        "else\n"
        "    export VIRTUAL_ENV=/somewhere/else/knowledge-base/.venv\n"
        "fi\n",
        encoding="utf-8",
    )
    (bindir / "pip").write_text(
        "#!/somewhere/else/knowledge-base/.venv/bin/python3\nimport pip\n",
        encoding="utf-8",
    )
    names = {r.name: r.severity for r in kb_doctor.check_venv(root)}
    assert names["venv:nested"] == "warn"
    assert names["venv:moved"] == "warn"
    assert names["venv:active"] == "warn"  # this test runs outside that venv
    if os.name != "nt":
        assert names["venv:pip"] == "warn"


def test_venv_in_place_is_clean(tmp_path: Path):
    root, _codex = _healthy_base(tmp_path)
    venv = root / ".venv"
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    bindir.mkdir(parents=True)
    (bindir / "activate").write_text(
        f"    export VIRTUAL_ENV=$(cygpath {venv})\n    export VIRTUAL_ENV={venv}\n",
        encoding="utf-8",
    )
    (bindir / "pip").write_text(f"#!{sys.executable}\nimport pip\n", encoding="utf-8")
    names = [r.name for r in kb_doctor.check_venv(root)]
    assert names == ["venv:active"]  # only: this test's interpreter is elsewhere


def test_venv_in_deploy_layout_is_the_project_one(tmp_path: Path):
    project = tmp_path / "project"
    base = project / "knowledge-base"
    base.mkdir(parents=True)
    (project / "setup" / "scripts").mkdir(parents=True)
    (project / "setup" / "scripts" / "kb_common.py").write_text("", encoding="utf-8")
    (project / ".venv" / ".venv").mkdir(parents=True)
    names = [r.name for r in kb_doctor.check_venv(base)]
    assert "venv:nested" in names


def _fake_nltk(monkeypatch, *, data: bool) -> None:
    import types

    def lookup(*_a, **_k):
        if not data:
            raise LookupError("Resource stopwords not found.")
        return ["the"]

    corpus = types.ModuleType("nltk.corpus")
    corpus.stopwords = types.SimpleNamespace(words=lookup)
    tokenize = types.ModuleType("nltk.tokenize")
    tokenize.sent_tokenize = lookup
    for name, module in (
        ("rake_nltk", types.ModuleType("rake_nltk")),
        ("nltk", types.ModuleType("nltk")),
        ("nltk.corpus", corpus),
        ("nltk.tokenize", tokenize),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def test_nltk_data_missing_is_a_warning(monkeypatch):
    _fake_nltk(monkeypatch, data=False)
    result = kb_doctor.check_nltk_data()
    assert result.severity == "warn"
    assert "nltk.downloader stopwords punkt" in result.message
    _fake_nltk(monkeypatch, data=True)
    assert kb_doctor.check_nltk_data().severity == "ok"


def test_nltk_check_skipped_without_rake(monkeypatch):
    monkeypatch.setitem(sys.modules, "rake_nltk", None)  # import → ImportError
    assert kb_doctor.check_nltk_data() is None


def test_a_crashing_check_does_not_stop_doctor(tmp_path: Path, monkeypatch):
    root, _codex = _healthy_base(tmp_path)

    def boom(_root):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(kb_doctor, "check_heal", boom)
    results = _by_name(kb_doctor.run_all_checks(root, skip_nlp=True))
    assert results["heal"].severity == "error"
    assert "kaputt" in results["heal"].message
    assert "log:writable" in results


def test_missing_keybert_names_the_file_that_installs_it(monkeypatch):
    """KeyBERT left requirements.txt: the hint names requirements-nlp.txt."""
    real_import = kb_doctor.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "keybert":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(kb_doctor.importlib, "import_module", fake_import)
    result = next(r for r in kb_doctor.check_optional_packages() if r.name == "opt:keybert")
    assert result.severity == "warn"
    assert "pip install -r requirements-nlp.txt" in result.message
    assert "download.pytorch.org/whl/cpu" in result.message


def test_media_ocr_reports_missing_tesseract_language_data(tmp_path: Path, monkeypatch):
    """The OCR setup-failure message sends the owner to kb_doctor: it must
    name the missing language data, as `kb_ocr.py --check` does."""
    import kb_ocr

    root = tmp_path / "kb"
    root.mkdir()
    (root / "kb.config.yml").write_text("language_policy:\n  primary: ru\n", encoding="utf-8")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg: ["tesseract"])
    monkeypatch.setattr(kb_ocr, "tesseract_installed_languages", lambda: {"eng"})
    ocr = next(r for r in kb_doctor.check_media(root) if r.name == "media:ocr")
    assert ocr.severity == "warn"
    assert any("missing rus" in d for d in ocr.details)

    monkeypatch.setattr(kb_ocr, "tesseract_installed_languages", lambda: {"eng", "rus"})
    ocr = next(r for r in kb_doctor.check_media(root) if r.name == "media:ocr")
    assert (ocr.severity, ocr.details) == ("ok", [])
