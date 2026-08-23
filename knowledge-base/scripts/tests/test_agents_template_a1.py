"""Regression locks for iteration A1: opening-line insurance, no !-stopper."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = REPO_ROOT / "knowledge-base" / "templates"


def test_agents_template_stays_under_10kib():
    data = (TEMPLATES / "AGENTS.md.template").read_bytes()
    assert len(data) <= 10240, f"AGENTS.md.template is {len(data)} B (limit 10240)"


def test_deployed_agents_md_stays_under_the_lint_threshold():
    """What lint and doctor measure is the deployed file, not the template.

    `kb_upgrade` appends the managed `!view` block on the first upgrade, so the
    template alone is not the number that has to fit `agents_max_bytes`.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import kb_upgrade

    import kb_lint

    template = (TEMPLATES / "AGENTS.md.template").read_bytes()
    deployed = len(template) + len(kb_upgrade.VIEW_BLOCK.encode("utf-8"))
    assert deployed <= kb_lint.DEFAULT_AGENTS_MAX_BYTES, (
        f"deployed AGENTS.md would be {deployed} B "
        f"(template {len(template)} B + !view block), over "
        f"{kb_lint.DEFAULT_AGENTS_MAX_BYTES} B — trim the template or raise "
        "instructions_lint.agents_max_bytes everywhere"
    )


def test_agents_template_has_no_bang_command_stopper():
    text = (TEMPLATES / "AGENTS.md.template").read_text(encoding="utf-8")
    assert "If the user issues a `!`-command before that opening line" not in text
    assert "re-issue the command" not in text


def test_start_here_does_not_claim_agent_is_blind_without_opening_line():
    text = (TEMPLATES / "START_HERE.md.template").read_text(encoding="utf-8")
    assert "the agent has no idea this knowledge base exists" not in text
    assert "Codex environment" in text
    assert "Используй AGENTS.md как основную инструкцию" in text
    assert "`!refactor`" in text
    assert "`!quiz`" in text
    assert "17_REFACTOR.md" in text


def test_agents_template_wraps_required_invariants():
    import kb_common as kbc

    text = (TEMPLATES / "AGENTS.md.template").read_text(encoding="utf-8")
    assert '<!-- AI-KE:INVARIANT:BEGIN id="forbidden" -->' in text
    assert '<!-- AI-KE:INVARIANT:END id="forbidden" -->' in text
    assert '<!-- AI-KE:INVARIANT:BEGIN id="language" -->' in text
    assert '<!-- AI-KE:INVARIANT:END id="language" -->' in text
    assert kbc.REQUIRED_INVARIANT_IDS <= kbc.invariant_ids(text)
    assert kbc.invariant_problems(text) == []


def test_agents_template_c2_owner_verdicts():
    text = (TEMPLATES / "AGENTS.md.template").read_text(encoding="utf-8")
    assert "## Token budget" not in text
    assert "Auto-detects when meaningful material has accumulated" not in text
    assert "If you've loaded > 5" not in text
    assert "If you have loaded > 5" not in text
    assert "at most 7" in text
    assert "only when the page actually influenced the answer" in text
    assert "1. Treat it as candidate source material" in text
    assert "8. If the file is low-signal" in text
    assert "`knowledge/decisions/`" in text
    assert "insights → opinions → domain" in text
    assert "knowledge/profile/" in text
    assert "| `default` |" in text
    assert "### default mode" not in text
    assert "health triage" not in text
    assert "`!export` → `python3 scripts/kb_export.py`" not in text
    assert "`!refactor`" in text
    assert "`!profile-review`" in text
    assert "`!quiz`" in text
    assert ".repomix/audit/" in text
    assert "17_REFACTOR.md" in text
    assert "--global" in text
    assert '<!-- AI-KE:INDEX:BEGIN' in text
    assert "Never read a full-base index dump" in text


def test_refactor_module_is_two_step_and_global_is_report_only():
    text = (
        REPO_ROOT / "knowledge-base" / "17_REFACTOR.md"
    ).read_text(encoding="utf-8")
    assert "Step 1 — audit" in text
    assert "Step 2 — rewrite from decisions only" in text
    assert "report only" in text.lower()
    assert "Do not write" in text
    assert "~/.codex/AGENTS.md" in text
    assert "kb_refactor.py" in text and "no" in text.lower()


def test_config_template_has_instructions_review():
    text = (TEMPLATES / "kb.config.yml.template").read_text(encoding="utf-8")
    assert "instructions_review:" in text
    assert "reviewed_at:" in text
    assert "reviewed_model:" in text
    assert "clean_run_baseline:" in text


def test_eval_questions_template_has_three_slots():
    text = (TEMPLATES / "eval" / "QUESTIONS.md.template").read_text(
        encoding="utf-8"
    )
    assert "## Q1." in text
    assert "## Q2." in text
    assert "## Q3." in text
    assert "must cite" in text
    assert "must mention" in text
    assert "must NOT propose" in text
