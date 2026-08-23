"""Tests for kb_heal — catch-up repair after upgrade (iteration F)."""
from __future__ import annotations

from pathlib import Path

import yaml

import kb_heal


MIGRATIONS_FIXTURE = """\
# Migrations

## 0.15.0

- id: instruction-lint-config
  bucket: auto
  detect: "kb.config.yml has no top-level instructions_lint:"
  fix: "append the default instructions_lint block"

- id: eval-bootstrap
  bucket: human
  detect: "eval/QUESTIONS.md is missing"
  fix: "ask the owner for three typical questions"

- id: agents-md-invariants
  bucket: assisted
  detect: "AGENTS.md lacks AI-KE:INVARIANT wrappers"
  fix: "wrap Forbidden and Language; show the diff"
"""


def _write_config(root: Path, raw: dict) -> None:
    (root / "kb.config.yml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _base(tmp_path: Path, **cfg_extra) -> Path:
    root = tmp_path / "kb"
    root.mkdir()
    raw = {
        "instructions_version": "0.11.0",
        "knowledge_base": {"name": "t", "mode": "default"},
        "language_policy": {"primary": "en"},
        "privacy": {"raw_indexing_allowed": False},
        "mode_profiles": {"default": {"lint": {"level2_trigger": "manual"}}},
    }
    raw.update(cfg_extra)
    _write_config(root, raw)
    (root / "AGENTS.md").write_text("## Forbidden\n- x\n\n## Language\nen\n", encoding="utf-8")
    return root


def test_parse_migrations_reads_buckets_and_ids():
    steps = kb_heal.parse_migrations(MIGRATIONS_FIXTURE)
    ids = [s.id for s in steps]
    assert ids == [
        "instruction-lint-config",
        "eval-bootstrap",
        "agents-md-invariants",
    ]
    by_id = {s.id: s for s in steps}
    assert by_id["instruction-lint-config"].bucket == "auto"
    assert by_id["eval-bootstrap"].bucket == "human"
    assert by_id["agents-md-invariants"].version == "0.15.0"


def test_plan_writes_heal_plan_without_changing_config(tmp_path: Path):
    root = _base(tmp_path)
    before = (root / "kb.config.yml").read_text(encoding="utf-8")
    plan_path = kb_heal.write_plan(
        root, migrations_text=MIGRATIONS_FIXTURE
    )
    assert plan_path == root / "review" / "needs-heal" / "HEAL_PLAN.md"
    text = plan_path.read_text(encoding="utf-8")
    assert "instruction-lint-config" in text
    assert "eval-bootstrap" in text
    assert "## auto" in text
    assert "## human" in text
    assert (root / "kb.config.yml").read_text(encoding="utf-8") == before


def test_plan_honest_zero(tmp_path: Path):
    root = _base(
        tmp_path,
        instructions_lint={"agents_max_bytes": 10240},
        heal={"auto_apply": True, "stage": 1, "assisted_batch": 20},
        instructions_review={"reviewed_at": "2026-08-23"},
        index={"primary_agent": "cursor", "window_profile": "256k"},
    )
    (root / "AGENTS.md").write_text(
        '<!-- AI-KE:INVARIANT:BEGIN id="forbidden" -->\n## Forbidden\n'
        '<!-- AI-KE:INVARIANT:END id="forbidden" -->\n'
        '<!-- AI-KE:INVARIANT:BEGIN id="language" -->\n## Language\n'
        '<!-- AI-KE:INVARIANT:END id="language" -->\n'
        "| `!refactor` | trim | ~5K |\n"
        "| `!profile-review` | profile | ~5K |\n"
        "| `!quiz` | exam | ~5K |\n",
        encoding="utf-8",
    )
    (root / "eval" / "results").mkdir(parents=True)
    (root / "eval" / "QUESTIONS.md").write_text(
        "## Q1. a\n## Q2. b\n## Q3. c\n", encoding="utf-8"
    )
    path = kb_heal.write_plan(root, migrations_text=MIGRATIONS_FIXTURE)
    text = path.read_text(encoding="utf-8")
    assert "No findings" in text or "in order" in text.lower()


def test_quiz_command_detected_on_old_agents(tmp_path: Path):
    root = _base(tmp_path)
    findings = kb_heal.collect_findings(root, migrations_text="")
    hit = [f for f in findings if f.id == "quiz-command"]
    assert hit and hit[0].bucket == "assisted"


def test_eval_bootstrap_detected_without_migrations_file(tmp_path: Path):
    root = _base(tmp_path)
    findings = kb_heal.collect_findings(root, migrations_text="")
    hit = [f for f in findings if f.id == "eval-bootstrap"]
    assert hit and hit[0].bucket == "human"


def test_plan_lists_sidecars_as_assisted(tmp_path: Path):
    root = _base(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "kb_lint.py.new").write_text("upstream\n", encoding="utf-8")
    findings = kb_heal.collect_findings(root, migrations_text=MIGRATIONS_FIXTURE)
    sidecars = [f for f in findings if f.source == "sidecar"]
    assert sidecars
    assert all(f.bucket == "assisted" for f in sidecars)
    assert any("kb_lint.py.new" in f.title or "kb_lint.py.new" in f.detail for f in sidecars)


def test_plan_lists_stale_packs_as_auto(tmp_path: Path):
    root = _base(tmp_path)
    knowledge = root / "knowledge" / "domain"
    knowledge.mkdir(parents=True)
    page = knowledge / "note.md"
    page.write_text("# n\n", encoding="utf-8")
    packs = root / ".repomix"
    packs.mkdir()
    pack = packs / "core.xml"
    pack.write_text("<pack/>\n", encoding="utf-8")
    older = page.stat().st_mtime - 120
    import os

    os.utime(pack, (older, older))
    findings = kb_heal.collect_findings(root, migrations_text=MIGRATIONS_FIXTURE)
    stale = [f for f in findings if f.id == "packs-stale"]
    assert stale and stale[0].bucket == "auto"


def test_apply_auto_is_idempotent_and_skips_other_buckets(tmp_path: Path):
    root = _base(tmp_path)
    first = kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    assert any(a.id == "instruction-lint-config" for a in first)
    assert all(a.bucket == "auto" for a in first)
    cfg = (root / "kb.config.yml").read_text(encoding="utf-8")
    assert "instructions_lint:" in cfg
    assert not (root / "eval" / "QUESTIONS.md").is_file()
    assert (root / "eval" / "results").is_dir()
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "AI-KE:INVARIANT" not in agents
    second = kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    assert not any(a.id == "instruction-lint-config" for a in second)


def test_apply_auto_sets_codex_window_profile(tmp_path: Path):
    root = _base(
        tmp_path,
        index={"primary_agent": "codex", "window_profile": "256k"},
    )
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    cfg = yaml.safe_load((root / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["index"]["window_profile"] == "400k"


def test_apply_auto_writes_backup(tmp_path: Path):
    root = _base(tmp_path)
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    backups = list((root / ".kb-backups").iterdir())
    assert backups


def test_verify_rolls_back_on_eval_regression(tmp_path: Path):
    root = _base(tmp_path)
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    assert "instructions_lint:" in (root / "kb.config.yml").read_text(encoding="utf-8")
    results = root / "eval" / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "2026-08-23__after-heal.md").write_text(
        "eval: regressed\n", encoding="utf-8"
    )
    action = kb_heal.verify(root)
    assert "roll" in action.lower()
    assert "instructions_lint:" not in (root / "kb.config.yml").read_text(
        encoding="utf-8"
    )


def test_stage_4_locked_until_measure(tmp_path: Path):
    root = _base(tmp_path)
    (root / "AGENTS.md").write_text(
        "always never must forbidden always never must forbidden always\n" * 20,
        encoding="utf-8",
    )
    findings = kb_heal.collect_findings(root, migrations_text=MIGRATIONS_FIXTURE)
    trim = [f for f in findings if f.stage == 4]
    assert trim
    assert all(f.locked for f in trim)
    (root / "eval").mkdir()
    (root / "eval" / "QUESTIONS.md").write_text(
        "## Q1. cache?\n## Q2. voice?\n## Q3. role?\n", encoding="utf-8"
    )
    unlocked = kb_heal.collect_findings(root, migrations_text=MIGRATIONS_FIXTURE)
    trim2 = [f for f in unlocked if f.stage == 4]
    assert trim2
    assert all(not f.locked for f in trim2)


def test_heal_module_locks_trim_behind_measure():
    text = (
        Path(__file__).resolve().parents[3] / "knowledge-base" / "18_HEAL.md"
    ).read_text(encoding="utf-8")
    assert "Stage 4 is physically unavailable until stage 3 is closed" in text
    assert "assisted_batch" in text


def test_detects_c2_trim_and_missing_refactor(tmp_path: Path):
    root = _base(tmp_path)
    (root / "AGENTS.md").write_text(
        "## Token budget\n\nAuto-detects when meaningful material has accumulated\n"
        "If you've loaded > 5, stop\n",
        encoding="utf-8",
    )
    findings = kb_heal.collect_findings(root, migrations_text="")
    ids = {f.id for f in findings}
    assert "agents-md-c2-trim" in ids
    assert "refactor-command" in ids
    trim = next(f for f in findings if f.id == "agents-md-c2-trim")
    assert trim.bucket == "assisted"
    assert trim.stage == 4
    assert trim.locked is True


def test_apply_auto_bumps_agents_max_bytes_to_10kib(tmp_path: Path):
    root = _base(tmp_path, instructions_lint={"agents_max_bytes": 8192})
    kb_heal.apply_auto(root, migrations_text="")
    cfg = yaml.safe_load((root / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["instructions_lint"]["agents_max_bytes"] == 10240


def test_apply_auto_appends_instructions_review(tmp_path: Path):
    root = _base(tmp_path)
    kb_heal.apply_auto(root, migrations_text="")
    text = (root / "kb.config.yml").read_text(encoding="utf-8")
    assert "instructions_review:" in text


def test_apply_auto_never_applies_assisted_or_human(tmp_path: Path):
    root = _base(tmp_path)
    applied = kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    assert not any(a.bucket in {"assisted", "human"} for a in applied)


# ---------------------------------------------------------------------------
# Regression locks: heal edits kb.config.yml in place (2026-08-23 acceptance)
# ---------------------------------------------------------------------------

COMMENTED_CONFIG = """\
# AI Knowledge Engine — kb.config.yml
instructions_version: "0.11.0"          # bumped by kb_upgrade

knowledge_base:
  name: "t"                             # human-readable
  mode: "default"

# Catch-up repair after an upgrade (18_HEAL.md)
heal:
  auto_apply: true                      # kb_upgrade applies the auto bucket
  stage: 1                              # 1 safe … 5 content
  assisted_batch: 20
  # last_run:
  #   at: "2026-01-15"
  #   version: "0.11.0"

language_policy:
  primary: "en"                         # keep terms in the original
"""


def _commented_base(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    root.mkdir()
    (root / "kb.config.yml").write_text(COMMENTED_CONFIG, encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "## Forbidden\n- x\n\n## Language\nen\n", encoding="utf-8"
    )
    return root


def test_apply_auto_keeps_every_comment_in_the_config(tmp_path: Path):
    root = _commented_base(tmp_path)
    before = COMMENTED_CONFIG.count("#")
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE)
    after = (root / "kb.config.yml").read_text(encoding="utf-8")
    # The commented-out last_run placeholder is replaced by a real one; every
    # other comment survives.
    assert after.count("#") == before - 3
    assert "# bumped by kb_upgrade" in after
    assert "# 1 safe … 5 content" in after
    assert "# keep terms in the original" in after
    assert yaml.safe_load(after)["heal"]["last_run"]["version"] == "0.11.0"


def test_apply_auto_stamps_the_version_the_caller_passes(tmp_path: Path):
    root = _commented_base(tmp_path)
    kb_heal.apply_auto(
        root, migrations_text=MIGRATIONS_FIXTURE, version="0.15.0"
    )
    cfg = yaml.safe_load((root / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["heal"]["last_run"]["version"] == "0.15.0"
    assert cfg["heal"]["auto_apply"] is True
    assert cfg["heal"]["assisted_batch"] == 20


def test_touch_last_run_appends_a_heal_block_when_there_is_none(tmp_path: Path):
    root = tmp_path / "kb"
    root.mkdir()
    (root / "kb.config.yml").write_text(
        'instructions_version: "0.11.0"   # keep me\n', encoding="utf-8"
    )
    kb_heal._touch_last_run(root, version="0.15.0")
    text = (root / "kb.config.yml").read_text(encoding="utf-8")
    assert "# keep me" in text
    cfg = yaml.safe_load(text)
    assert cfg["heal"]["last_run"]["version"] == "0.15.0"
    assert cfg["heal"]["stage"] == 1


def test_apply_auto_is_idempotent_on_a_commented_config(tmp_path: Path):
    root = _commented_base(tmp_path)
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE, version="0.15.0")
    once = (root / "kb.config.yml").read_text(encoding="utf-8")
    kb_heal.apply_auto(root, migrations_text=MIGRATIONS_FIXTURE, version="0.15.0")
    assert (root / "kb.config.yml").read_text(encoding="utf-8") == once


def test_locked_trim_findings_are_listed_once(tmp_path: Path):
    root = _base(tmp_path)
    (root / "AGENTS.md").write_text(
        "## Token budget\nx\n\n## Forbidden\n- x\n\n## Language\nen\n",
        encoding="utf-8",
    )
    findings = kb_heal.collect_findings(root, migrations_text=(
        MIGRATIONS_FIXTURE
        + "\n- id: agents-md-c2-trim\n  bucket: assisted\n"
        '  detect: "AGENTS.md still has ## Token budget"\n'
        '  fix: "apply C2 verdicts"\n'
    ))
    locked = [f for f in findings if f.locked]
    assert locked, "stage-4 trim must be locked while measure is open"
    plan = kb_heal.render_plan(root, findings)
    for item in locked:
        assert plan.count(f"`{item.id}`") == 1
