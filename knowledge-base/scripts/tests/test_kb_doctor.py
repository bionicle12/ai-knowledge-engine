"""Smoke coverage for kb_doctor: the built-in self-test must stay green.

The CI reference pipeline used to run `kb_doctor.py --self-test`; with CI
intentionally disabled this pytest wrapper keeps it part of the local run.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
