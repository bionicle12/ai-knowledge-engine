"""Tests for kb_reflect (trigger logic only — actual reflection is AI-driven)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import kb_common as kbc
import kb_reflect


def _write_config(root: Path, mode: str = "default", threshold: int = 25,
                  min_interval: int = 7, require_changes: bool = True,
                  trigger: str = "threshold+weekly") -> None:
    cfg = f"""
knowledge_base:
  name: test
  mode: {mode}
mode_profiles:
  {mode}:
    reflection:
      trigger: "{trigger}"
      importance_threshold: {threshold}
      min_interval_days: {min_interval}
      require_changes: {str(require_changes).lower()}
""".strip()
    (root / "kb.config.yml").write_text(cfg, encoding="utf-8")


def _add_log_entry(root: Path, op: str, title: str, when: dt.datetime | None = None) -> None:
    when = when or dt.datetime.now().astimezone()
    log = kbc.log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text("# Operations Log\n\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## [{when.replace(microsecond=0).isoformat()}] {op} | {title}\n")


def _add_metadata(root: Path, stable_filename: str, importance: int) -> None:
    md_dir = root / "processed" / "extracted-metadata"
    md_dir.mkdir(parents=True, exist_ok=True)
    p = md_dir / f"{Path(stable_filename).stem}.yml"
    p.write_text(
        f"stable_filename: {stable_filename}\nimportance: {importance}\n",
        encoding="utf-8",
    )


def test_skip_when_no_log(tmp_path: Path):
    _write_config(tmp_path)
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    # No changes, no marker → still WEEKLY_DUE-like? But require_changes=true
    # so first run with no changes → SKIP
    assert info["decision"] == "SKIP"


def test_threshold_met_triggers(tmp_path: Path):
    _write_config(tmp_path, threshold=10)
    # Add 3 ingests with importance 5 each → sum=15 >= 10
    for i in range(3):
        name = f"2026-05-{10+i:02d}__doc.md"
        _add_log_entry(tmp_path, "ingest", name)
        _add_metadata(tmp_path, name, importance=5)
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["decision"] == "THRESHOLD_MET"
    assert info["sum_importance"] == 15


def test_below_threshold_no_trigger(tmp_path: Path):
    _write_config(tmp_path, threshold=100, min_interval=7, require_changes=True)
    # Set marker to "just now" so weekly is not yet due
    kb_reflect._write_marker(
        tmp_path / kb_reflect.REFLECTION_MARKER,
        dt.datetime.now().astimezone(),
    )
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name)
    _add_metadata(tmp_path, name, importance=3)
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["decision"] == "SKIP"


def test_weekly_due_with_changes(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7, require_changes=True)
    # Mark last reflection 10 days ago
    marker_when = dt.datetime.now().astimezone() - dt.timedelta(days=10)
    kb_reflect._write_marker(tmp_path / kb_reflect.REFLECTION_MARKER, marker_when)
    # Add an ingest after the marker
    _add_log_entry(tmp_path, "ingest", "doc.md")
    _add_metadata(tmp_path, "doc.md", importance=2)
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["decision"] == "WEEKLY_DUE"


def test_weekly_due_no_changes_skips(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7, require_changes=True)
    marker_when = dt.datetime.now().astimezone() - dt.timedelta(days=10)
    kb_reflect._write_marker(tmp_path / kb_reflect.REFLECTION_MARKER, marker_when)
    # No ingests after the marker
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["decision"] == "SKIP"


def test_marker_not_updated_in_dry_run(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name)
    _add_metadata(tmp_path, name, importance=10)
    marker = tmp_path / kb_reflect.REFLECTION_MARKER
    assert not marker.exists()
    kb_reflect.determine_action(tmp_path, dry_run=True)
    assert not marker.exists(), "dry-run should not write marker"


def test_stagnation_skips_scheduled_after_two_zero_insights(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name)
    _add_metadata(tmp_path, name, importance=10)
    _add_log_entry(tmp_path, "reflect", "0 insights — valid")
    _add_log_entry(tmp_path, "reflect", "insights=0")
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["decision"] == "SKIP"
    assert info["stagnation"] is True


def test_record_result_zero_is_valid(tmp_path: Path):
    _write_config(tmp_path)
    kb_reflect.record_result(tmp_path, 0)
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "0 insights" in log
    assert "valid" in log


def test_meta_insight_requires_new_l0(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7)
    kb_reflect._write_marker(
        tmp_path / kb_reflect.REFLECTION_MARKER,
        dt.datetime.now().astimezone(),
    )
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert info["meta_insight_allowed"] is False
    assert info["honest_zero_ok"] is True
    assert info["max_insights_per_run"] == 3


def test_exploration_slot_in_determine_action(tmp_path: Path):
    _write_config(tmp_path)
    page = tmp_path / "knowledge" / "domain"
    page.mkdir(parents=True)
    (page / "alpha.md").write_text(
        "---\ntags: [alpha]\n---\n# Alpha\n", encoding="utf-8"
    )
    (tmp_path / "knowledge" / "projects").mkdir(parents=True)
    (tmp_path / "knowledge" / "projects" / "beta.md").write_text(
        "---\ntags: [beta]\n---\n# Beta\n", encoding="utf-8"
    )
    info = kb_reflect.determine_action(tmp_path, dry_run=True)
    assert len(info["exploration"]) == 1
    assert info["exploration"][0]["a"] == "domain/alpha"


def test_marker_updated_when_decision_made(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name)
    _add_metadata(tmp_path, name, importance=10)
    marker = tmp_path / kb_reflect.REFLECTION_MARKER
    info = kb_reflect.determine_action(tmp_path, dry_run=False)
    assert info["decision"] == "THRESHOLD_MET"
    assert marker.exists()
