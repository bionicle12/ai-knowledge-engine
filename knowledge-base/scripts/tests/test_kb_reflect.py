"""Tests for kb_reflect (trigger logic only — actual reflection is AI-driven)."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import kb_common as kbc
import kb_reflect


def _write_config(root: Path, mode: str = "default", threshold: int = 25,
                  min_interval: int = 7, require_changes: bool = True,
                  trigger: str = "threshold+weekly", extra: str = "") -> None:
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
{extra}
""".strip()
    (root / "kb.config.yml").write_text(cfg + "\n", encoding="utf-8")


def _add_log_entry(root: Path, op: str, title: str, when: dt.datetime | None = None,
                   *, naive: bool = False) -> None:
    when = (when or dt.datetime.now().astimezone()).replace(microsecond=0)
    if naive:
        when = when.replace(tzinfo=None)
    log = kbc.log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text("# Operations Log\n\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## [{when.isoformat()}] {op} | {title}\n")


def _add_metadata(root: Path, stable_filename: str, importance: int) -> None:
    md_dir = root / "processed" / "extracted-metadata"
    md_dir.mkdir(parents=True, exist_ok=True)
    p = md_dir / f"{Path(stable_filename).stem}.yml"
    p.write_text(
        f"stable_filename: {stable_filename}\nimportance: {importance}\n",
        encoding="utf-8",
    )


def _ago(**delta: float) -> dt.datetime:
    return dt.datetime.now().astimezone() - dt.timedelta(**delta)


def _set_marker(root: Path, when: dt.datetime) -> None:
    kb_reflect._write_marker(root / kb_reflect.REFLECTION_MARKER, when)


def _page(root: Path, rel: str, meta: str = "", *, mtime: float | None = None) -> Path:
    page = root / "knowledge" / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"---\nsource: manual\n{meta}---\n# Page\n", encoding="utf-8")
    if mtime is not None:
        os.utime(page, (mtime, mtime))
    return page


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_skip_when_no_log(tmp_path: Path):
    _write_config(tmp_path)
    info = kb_reflect.determine_action(tmp_path)
    # require_changes=true and nothing happened → SKIP
    assert info["decision"] == "SKIP"


def test_threshold_met_triggers(tmp_path: Path):
    _write_config(tmp_path, threshold=10)
    # 3 ingests with importance 5 each → score 15 >= 10
    for i in range(3):
        name = f"2026-05-{10+i:02d}__doc.md"
        _add_log_entry(tmp_path, "ingest", name)
        _add_metadata(tmp_path, name, importance=5)
    info = kb_reflect.determine_action(tmp_path)
    assert info["decision"] == "THRESHOLD_MET"
    assert info["trigger"] == "importance"
    assert info["changes"] == info["sum_importance"] == 15


def test_below_threshold_no_trigger(tmp_path: Path):
    _write_config(tmp_path, threshold=100, min_interval=7, require_changes=True)
    # Marker "just now" → weekly is not yet due
    _set_marker(tmp_path, _ago(seconds=5))
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name)
    _add_metadata(tmp_path, name, importance=3)
    info = kb_reflect.determine_action(tmp_path)
    assert info["decision"] == "SKIP"


def test_weekly_due_with_changes(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7, require_changes=True)
    _set_marker(tmp_path, _ago(days=10))
    _add_log_entry(tmp_path, "ingest", "doc.md")
    _add_metadata(tmp_path, "doc.md", importance=2)
    result = kb_reflect.check(tmp_path)
    # Weekly: once min_interval_days passed, any change is due — reported as
    # THRESHOLD_MET with the threshold that applied, so "changes ≥ threshold"
    # stays true for STATUS.md.
    assert result["decision"] == "THRESHOLD_MET"
    assert result["trigger"] == "weekly"
    assert result["threshold"] == 1
    assert result["changes"] >= result["threshold"]


def test_weekly_due_no_changes_skips(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7, require_changes=True)
    _set_marker(tmp_path, _ago(days=10))
    info = kb_reflect.determine_action(tmp_path)
    assert info["decision"] == "SKIP"


def test_stagnation_skips_scheduled_after_two_zero_insights(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    name = "x.md"
    _add_log_entry(tmp_path, "ingest", name, _ago(minutes=10))
    _add_metadata(tmp_path, name, importance=10)
    _add_log_entry(tmp_path, "reflect", "0 insights — valid", _ago(minutes=5))
    _add_log_entry(tmp_path, "reflect", "insights=0", _ago(minutes=1))
    info = kb_reflect.determine_action(tmp_path)
    assert info["decision"] == "SKIP"
    assert info["stagnation"] is True


def test_record_result_zero_is_valid(tmp_path: Path):
    _write_config(tmp_path)
    kb_reflect.record_result(tmp_path, 0)
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "reflect | insights: 0" in log
    assert "valid" in log


def test_meta_insight_requires_new_l0(tmp_path: Path):
    _write_config(tmp_path, threshold=999, min_interval=7)
    _set_marker(tmp_path, _ago(seconds=5))
    info = kb_reflect.determine_action(tmp_path)
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
    info = kb_reflect.determine_action(tmp_path)
    assert len(info["exploration"]) == 1
    assert info["exploration"][0]["a"] == "domain/alpha"


# --- D6: only --record-result writes the marker (I3, H4) -------------------


def test_record_result_writes_marker_and_resets_trigger(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md", _ago(minutes=1))
    marker = tmp_path / kb_reflect.REFLECTION_MARKER
    assert kb_reflect.check(tmp_path)["decision"] == "THRESHOLD_MET"
    assert not marker.exists()

    kb_reflect.record_result(tmp_path, 2)

    assert marker.is_file()
    result = kb_reflect.check(tmp_path)
    assert result["decision"] == "SKIP"
    assert result["count"] == 0


def test_generate_logs_a_request_and_keeps_the_trigger(tmp_path: Path):
    """Old --generate forced dry-run and logged a `reflect` entry: the marker
    never moved and the request broke the stagnation detector."""
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md", _ago(minutes=1))

    assert kb_reflect.main(["--root", str(tmp_path), "--generate"]) == 0

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "] reflect-request | reflection requested (THRESHOLD_MET)" in log
    assert "] reflect |" not in log
    assert not (tmp_path / kb_reflect.REFLECTION_MARKER).exists()
    # The request is pending, not done: the trigger stays until the result.
    assert kb_reflect.check(tmp_path)["decision"] == "THRESHOLD_MET"


def test_generate_does_not_stack_requests(tmp_path: Path, capsys):
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md", _ago(minutes=1))
    kb_reflect.main(["--root", str(tmp_path), "--generate"])
    kb_reflect.main(["--root", str(tmp_path), "--generate"])
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert log.count("reflect-request |") == 1
    assert "already pending" in capsys.readouterr().err


def test_stagnation_detected_across_requests(tmp_path: Path):
    """generate → record 0 → generate → record 0 must read as [0, 0]; the old
    `reflect | reflection requested` entries of pre-0.16 logs are ignored."""
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md", _ago(minutes=20))
    _add_log_entry(tmp_path, "reflect", "insights=0", _ago(minutes=15))
    _add_log_entry(tmp_path, "reflect", "reflection requested", _ago(minutes=14))
    _add_log_entry(tmp_path, "ingest", "y.md", _ago(minutes=12))
    kb_reflect.main(["--root", str(tmp_path), "--generate"])
    kb_reflect.record_result(tmp_path, 0)
    assert kb_reflect.determine_action(tmp_path)["stagnation"] is True


def test_stagnant_decision_until_a_new_ingest(tmp_path: Path):
    _write_config(tmp_path, threshold=5)
    _add_log_entry(tmp_path, "reflect", "insights: 0", _ago(hours=2))
    _add_log_entry(tmp_path, "reflect", "insights: 0", _ago(hours=1))
    _set_marker(tmp_path, _ago(hours=1))
    # Page edits alone (importance 8 ≥ 5) would be due …
    _page(tmp_path, "domain/a.md", "importance: 8\n")
    result = kb_reflect.check(tmp_path)
    assert result["decision"] == "STAGNANT"
    assert "stagnation" in result["reason"]
    # … a new level-0 fact (ingest) lifts the brake.
    _add_log_entry(tmp_path, "ingest", "new.md")
    assert kb_reflect.check(tmp_path)["decision"] == "THRESHOLD_MET"


def test_read_only_modes_do_not_write(tmp_path: Path, capsys):
    """No flags, --json, --count-changes and --check-threshold used to move
    the marker and swallow the trigger (3, then 0, then SKIP)."""
    _write_config(tmp_path, threshold=1)
    for i in range(3):
        _add_log_entry(tmp_path, "ingest", f"doc-{i}.md", _ago(minutes=5))
    before = _snapshot(tmp_path)
    root = str(tmp_path)
    for argv in ([], ["--json"], ["--check-threshold"], ["--check-threshold", "--json"],
                 ["--count-changes"], ["--check-threshold", "--dry-run"]):
        assert kb_reflect.main(["--root", root, *argv]) == 0
    assert _snapshot(tmp_path) == before
    capsys.readouterr()
    kb_reflect.main(["--root", root, "--count-changes"])
    assert capsys.readouterr().out.strip() == "3"
    kb_reflect.main(["--root", root, "--check-threshold"])
    assert capsys.readouterr().out.strip() == "THRESHOLD_MET"


def test_dry_run_is_deprecated_but_accepted(tmp_path: Path, capsys):
    _write_config(tmp_path)
    assert kb_reflect.main(["--root", str(tmp_path), "--check-threshold", "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "SKIP"
    assert "--dry-run is deprecated" in captured.err


def test_check_threshold_json_is_the_check_dict(tmp_path: Path, capsys):
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md")
    kb_reflect.main(["--root", str(tmp_path), "--check-threshold", "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert printed == kb_reflect.check(tmp_path)
    assert {"decision", "changes", "threshold", "mode"} <= set(printed)
    assert printed["mode"] == "default"


def test_super_mode_without_changes_skips(tmp_path: Path):
    """Super mode used to answer ON_DEMAND_DUE on every run with 0 changes."""
    _write_config(tmp_path, mode="super", threshold=5, min_interval=0,
                  require_changes=False, trigger="on-demand")
    assert kb_reflect.check(tmp_path)["decision"] == "SKIP"
    _add_log_entry(tmp_path, "reflect", "insights: 1", _ago(days=3))
    assert kb_reflect.check(tmp_path)["decision"] == "SKIP"


def test_unscored_ingests_weigh_one(tmp_path: Path):
    """Every ingest used to weigh 5, so any five files met threshold 25."""
    _write_config(tmp_path, threshold=25)
    _set_marker(tmp_path, _ago(days=1))
    for i in range(5):
        _add_log_entry(tmp_path, "ingest", f"doc-{i}.md")
    result = kb_reflect.check(tmp_path)
    assert result["changes"] == 5
    assert result["decision"] == "SKIP"


def test_unscored_ingest_weight_is_configurable(tmp_path: Path):
    _write_config(tmp_path, threshold=25,
                  extra="      default_ingest_importance: 5")
    _set_marker(tmp_path, _ago(days=1))
    for i in range(5):
        _add_log_entry(tmp_path, "ingest", f"doc-{i}.md")
    result = kb_reflect.check(tmp_path)
    assert result["changes"] == 25
    assert result["decision"] == "THRESHOLD_MET"


def test_knowledge_page_edits_weigh_their_importance(tmp_path: Path):
    _write_config(tmp_path, threshold=11, min_interval=30)
    marker_time = _ago(hours=1)
    _set_marker(tmp_path, marker_time)
    before = marker_time.timestamp() - 60
    _page(tmp_path, "domain/old.md", "importance: 9\n", mtime=before)
    _page(tmp_path, "domain/scored.md", "importance: 8\n")
    _page(tmp_path, "domain/plain.md")  # no importance → 3
    _page(tmp_path, "_archive/gone.md", "importance: 9\n")
    _page(tmp_path, "routing/domain.md", "generated_by: kb_route.py\nimportance: 9\n")
    result = kb_reflect.check(tmp_path)
    assert result["count"] == 2
    assert result["changes"] == 11
    assert result["decision"] == "THRESHOLD_MET"


def test_insights_written_before_record_result_do_not_count(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    _page(tmp_path, "insights/new-insight.md", "importance: 7\n")
    kb_reflect.record_result(tmp_path, 1)
    assert kb_reflect.check(tmp_path)["count"] == 0


def test_last_reflection_falls_back_to_the_log(tmp_path: Path):
    """A clone without the gitignored marker must not recount all history."""
    _write_config(tmp_path, threshold=2, min_interval=30)
    _add_log_entry(tmp_path, "ingest", "a.md", _ago(days=3))
    _add_log_entry(tmp_path, "ingest", "b.md", _ago(days=3))
    _add_log_entry(tmp_path, "reflect", "insights: 2", _ago(days=2))
    _add_log_entry(tmp_path, "ingest", "c.md", _ago(days=1))
    result = kb_reflect.check(tmp_path)
    assert result["count"] == 1
    assert result["decision"] == "SKIP"


def test_clone_without_marker_does_not_recount_pages(tmp_path: Path):
    """A clone (checkout, copy) resets every mtime: with only the log's
    `reflect` entry left, all pages counted again (score 50 ≥ 25)."""
    _write_config(tmp_path, threshold=25, min_interval=30)
    reflected = _ago(days=2)
    _add_log_entry(tmp_path, "reflect", "insights: 2", reflected)
    old_day = (reflected - dt.timedelta(days=3)).date().isoformat()
    for i in range(10):  # mtime now, as after a clone
        _page(tmp_path, f"work/p{i}.md",
              f"importance: 5\nextracted_at: {old_day}\nlast_verified: {old_day}\n")
    result = kb_reflect.check(tmp_path)
    assert (result["count"], result["decision"]) == (0, "SKIP")
    # Same when the local marker is older than the logged reflection (it was
    # recorded on another machine and pulled): the log wins.
    _set_marker(tmp_path, _ago(days=4))
    assert kb_reflect.check(tmp_path)["count"] == 0
    # A page extracted after the reflection still counts.
    _page(tmp_path, "work/new.md",
          f"importance: 5\nextracted_at: {dt.date.today().isoformat()}\n")
    result = kb_reflect.check(tmp_path)
    assert (result["count"], result["changes"]) == (1, 5)


def test_touched_pages_do_not_count_after_record_result(tmp_path: Path):
    """mtime alone decided: a checkout, restore or `touch` recounted every
    page with its importance. --record-result now stores page digests."""
    _write_config(tmp_path, threshold=25, min_interval=30)
    pages = [_page(tmp_path, f"work/p{i}.md", "importance: 5\n") for i in range(10)]
    kb_reflect.record_result(tmp_path, 1)
    later = time.time() + 60
    for page in pages:
        os.utime(page, (later, later))
    assert kb_reflect.check(tmp_path)["count"] == 0
    pages[0].write_text(pages[0].read_text(encoding="utf-8") + "A new fact.\n",
                        encoding="utf-8")
    os.utime(pages[0], (later, later))
    result = kb_reflect.check(tmp_path)
    assert (result["count"], result["changes"]) == (1, 5)


def test_access_tracking_is_not_a_knowledge_change(tmp_path: Path):
    """Updating last_accessed / access_count after an answer (AGENTS.md
    access tracking) counted as a page edit weighing its importance."""
    _write_config(tmp_path, threshold=5, min_interval=30)
    tracked = _page(tmp_path, "work/tracked.md",
                    "importance: 8\nlast_accessed: 2026-09-01\naccess_count: 2\n")
    fresh = _page(tmp_path, "work/fresh.md", "importance: 8\n")
    kb_reflect.record_result(tmp_path, 1)
    later = time.time() + 60
    tracked.write_text(
        tracked.read_text(encoding="utf-8")
        .replace("last_accessed: 2026-09-01", "last_accessed: 2026-09-24")
        .replace("access_count: 2", "access_count: 3"),
        encoding="utf-8",
    )
    fresh.write_text(
        fresh.read_text(encoding="utf-8").replace(
            "importance: 8\n", "importance: 8\nlast_accessed: 2026-09-24\naccess_count: 1\n"
        ),
        encoding="utf-8",
    )
    for page in (tracked, fresh):
        os.utime(page, (later, later))
    result = kb_reflect.check(tmp_path)
    assert (result["count"], result["decision"]) == (0, "SKIP")


def test_ingest_in_the_same_second_after_record_result_counts(tmp_path: Path):
    """log.md has whole seconds, the marker milliseconds: an ingest logged in
    the same second right after --record-result was lost for good and never
    lifted the stagnation brake."""
    _write_config(tmp_path, threshold=1, min_interval=30)
    kb_reflect.record_result(tmp_path, 0)
    kb_reflect.record_result(tmp_path, 0)
    marker = float((tmp_path / kb_reflect.REFLECTION_MARKER).read_text(encoding="utf-8"))
    _add_log_entry(tmp_path, "ingest", "n8.txt",
                   dt.datetime.fromtimestamp(int(marker)).astimezone())
    result = kb_reflect.check(tmp_path)
    assert result["count"] == 1
    assert result["decision"] == "THRESHOLD_MET"


def test_generate_logs_nothing_unless_threshold_met(tmp_path: Path, capsys):
    """--generate logged a request on SKIP and STAGNANT too; that request then
    counted as pending and swallowed the next real one."""
    _write_config(tmp_path, threshold=5, min_interval=30)
    root = str(tmp_path)
    log = kbc.log_path(tmp_path)
    assert kb_reflect.main(["--root", root, "--generate"]) == 0
    assert "no reflection due (SKIP)" in capsys.readouterr().err
    kb_reflect.record_result(tmp_path, 0)
    kb_reflect.record_result(tmp_path, 0)
    _page(tmp_path, "work/edited.md", "importance: 9\n", mtime=time.time() + 60)
    assert kb_reflect.check(tmp_path)["decision"] == "STAGNANT"
    assert kb_reflect.main(["--root", root, "--generate"]) == 0
    assert "no reflection due (STAGNANT)" in capsys.readouterr().err
    assert "reflect-request |" not in log.read_text(encoding="utf-8")
    # A real THRESHOLD_MET afterwards is logged, not "already pending".
    _add_log_entry(tmp_path, "ingest", "new.md")
    assert kb_reflect.main(["--root", root, "--generate"]) == 0
    assert log.read_text(encoding="utf-8").count("reflect-request |") == 1
    assert "already pending" not in capsys.readouterr().err


def test_exploration_is_built_only_when_used(tmp_path: Path, monkeypatch):
    """The no-flag report and a deduplicated --generate built the whole graph
    (kb_view.exploration_pairs, minutes on large bases) and never used it."""
    calls: list[Path] = []
    monkeypatch.setattr(kb_reflect, "exploration_slot",
                        lambda root: calls.append(root) or [])
    _write_config(tmp_path, threshold=1)
    _add_log_entry(tmp_path, "ingest", "x.md")
    root = str(tmp_path)
    for argv in ([], ["--check-threshold"], ["--count-changes"]):
        assert kb_reflect.main(["--root", root, *argv]) == 0
    assert calls == []
    kb_reflect.main(["--root", root, "--generate"])  # logs a request → built once
    kb_reflect.main(["--root", root, "--generate"])  # already pending → not built
    assert len(calls) == 1
    kb_reflect.main(["--root", root, "--json"])
    assert len(calls) == 2


def test_naive_log_timestamps_are_local_time(tmp_path: Path):
    """`## [2026-09-22T10:00:00] ingest | …` crashed with TypeError (L4)."""
    _write_config(tmp_path, threshold=2, min_interval=30)
    _set_marker(tmp_path, _ago(hours=2))
    _add_log_entry(tmp_path, "ingest", "old.md", _ago(hours=3), naive=True)
    _add_log_entry(tmp_path, "ingest", "new-1.md", _ago(hours=1), naive=True)
    _add_log_entry(tmp_path, "ingest", "new-2.md", naive=True)
    result = kb_reflect.check(tmp_path)
    assert result["count"] == 2
    assert result["decision"] == "THRESHOLD_MET"


def test_mode_comes_from_knowledge_base_mode(tmp_path: Path):
    _write_config(tmp_path, threshold=1)
    text = (tmp_path / "kb.config.yml").read_text(encoding="utf-8")
    (tmp_path / "kb.config.yml").write_text("mode: super\n" + text, encoding="utf-8")
    assert kb_reflect.check(tmp_path)["mode"] == "default"


def test_main_refuses_a_folder_without_kb_config(tmp_path: Path, capsys):
    """A wrong --root must not create a phantom base (M11)."""
    target = tmp_path / "not-a-base"
    target.mkdir()
    assert kb_reflect.main(["--root", str(target), "--record-result", "1"]) == 2
    assert list(target.iterdir()) == []
    assert "no kb.config.yml" in capsys.readouterr().err


def test_relative_root_is_resolved(tmp_path: Path, monkeypatch):
    base = tmp_path / "kb"
    base.mkdir()
    _write_config(base)
    monkeypatch.chdir(tmp_path)
    assert kb_reflect.main(["--root", "kb", "--record-result", "0"]) == 0
    assert (base / kb_reflect.REFLECTION_MARKER).is_file()
