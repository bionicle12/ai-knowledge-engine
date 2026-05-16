#!/usr/bin/env python3
"""kb_reflect — reflection trigger logic for AI Knowledge Engine.

This script does NOT run the actual reflection (that's an LLM task done by
the AI agent). It computes whether reflection should be triggered, based on:

  - Current operating mode (default | super) and its profile
  - Cumulative importance score of ingest entries since the last reflection
  - Time since last reflection
  - Whether there have been any changes in `log.md`

It outputs a status that the agent (or reindex.sh) can act on:

  THRESHOLD_MET    — start reflection now
  WEEKLY_DUE       — start weekly reflection
  SKIP             — nothing to do

Usage:
  python3 scripts/kb_reflect.py --check-threshold --dry-run
  python3 scripts/kb_reflect.py --check-threshold     # writes marker on hit
  python3 scripts/kb_reflect.py --count-changes       # how many ingests since last reflection
  python3 scripts/kb_reflect.py --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

REFLECTION_MARKER = ".last_reflection"
LOG_HEADING_RE = re.compile(
    r"^## \[(?P<ts>[^\]]+)\]\s+(?P<op>[a-z\-]+)\s+\|\s+(?P<title>.+)$",
    re.MULTILINE,
)
IMPORTANCE_LINE_RE = re.compile(
    r"importance[^\d]*(\d+)", re.IGNORECASE
)


def _read_marker(path: Path) -> _dt.datetime | None:
    if not path.is_file():
        return None
    try:
        ts = float(path.read_text(encoding="utf-8").strip())
        return _dt.datetime.fromtimestamp(ts).astimezone()
    except (ValueError, OSError):
        return None


def _write_marker(path: Path, when: _dt.datetime | None = None) -> None:
    when = when or _dt.datetime.now().astimezone()
    path.write_text(str(int(when.timestamp())), encoding="utf-8")


def _parse_log(root: Path) -> list[tuple[_dt.datetime, str, str]]:
    log = kbc.log_path(root)
    if not log.is_file():
        return []
    text = log.read_text(encoding="utf-8")
    out: list[tuple[_dt.datetime, str, str]] = []
    for m in LOG_HEADING_RE.finditer(text):
        try:
            ts = _dt.datetime.fromisoformat(m.group("ts"))
        except ValueError:
            continue
        out.append((ts, m.group("op"), m.group("title")))
    return out


def _importance_since(
    log_entries: list[tuple[_dt.datetime, str, str]],
    *,
    since: _dt.datetime | None,
    root: Path,
) -> tuple[int, int]:
    """Return (count_changes, sum_importance) for ingest entries since `since`.

    Importance is read from extracted-metadata yamls when available, otherwise
    inferred from a log line "importance: N".
    """
    md_dir = root / "processed" / "extracted-metadata"
    importance_by_filename: dict[str, int] = {}
    if md_dir.is_dir():
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            yaml = None
        if yaml is not None:
            for yml in md_dir.glob("*.yml"):
                try:
                    data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
                    if "importance" in data and "stable_filename" in data:
                        importance_by_filename[data["stable_filename"]] = int(
                            data["importance"]
                        )
                except Exception:
                    continue

    count = 0
    total = 0
    for ts, op, title in log_entries:
        if since and ts <= since:
            continue
        if op != "ingest":
            continue
        count += 1
        # Match by filename in title
        imp = importance_by_filename.get(title.strip(), None)
        if imp is None:
            # Try regex in details (handled in caller-level — log doesn't include
            # details by default in our parser). Fall back to a default.
            imp = 5  # reasonable default
        total += imp
    return count, total


def determine_action(root: Path, *, dry_run: bool = False) -> dict:
    cfg = kbc.load_config(root)
    profile = cfg.profile()

    marker_path = root / REFLECTION_MARKER
    last_reflection = _read_marker(marker_path)
    now = _dt.datetime.now().astimezone()

    log_entries = _parse_log(root)
    count_changes, sum_importance = _importance_since(
        log_entries, since=last_reflection, root=root
    )

    threshold = profile.reflection_importance_threshold
    min_interval_days = profile.reflection_min_interval_days
    require_changes = profile.reflection_require_changes

    elapsed_days = (
        (now - last_reflection).days if last_reflection else 99999
    )

    decision = "SKIP"
    reasons: list[str] = []

    if sum_importance >= threshold:
        decision = "THRESHOLD_MET"
        reasons.append(
            f"sum(importance)={sum_importance} >= threshold={threshold}"
        )

    if decision == "SKIP" and profile.reflection_trigger.startswith("threshold+weekly"):
        if elapsed_days >= min_interval_days:
            if require_changes and count_changes == 0:
                reasons.append("weekly due but no changes since last reflection")
            else:
                decision = "WEEKLY_DUE"
                reasons.append(
                    f"elapsed={elapsed_days}d >= {min_interval_days}d, "
                    f"changes={count_changes}"
                )

    if (
        decision == "SKIP"
        and profile.reflection_trigger == "on-demand"
        and not require_changes
        and elapsed_days >= min_interval_days
    ):
        decision = "ON_DEMAND_DUE"
        reasons.append("super mode + on-demand + interval reached")

    if decision != "SKIP" and not dry_run:
        _write_marker(marker_path, now)

    return {
        "mode": cfg.mode,
        "decision": decision,
        "reasons": reasons,
        "elapsed_days": elapsed_days,
        "count_changes": count_changes,
        "sum_importance": sum_importance,
        "threshold": threshold,
        "min_interval_days": min_interval_days,
        "last_reflection": last_reflection.isoformat() if last_reflection else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — reflection trigger")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--check-threshold", action="store_true",
                        help="Compute decision; print THRESHOLD_MET/WEEKLY_DUE/SKIP")
    parser.add_argument("--count-changes", action="store_true",
                        help="Print count of ingests since last reflection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Do not update the marker even if decision != SKIP")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--generate", action="store_true",
                        help="Placeholder for AI-driven reflection (not implemented in Python)")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    info = determine_action(root, dry_run=args.dry_run or args.generate)

    if args.count_changes:
        print(info["count_changes"])
        return 0

    if args.generate:
        # The actual reflection is performed by the AI agent. This script only
        # records that the trigger was acknowledged.
        kbc.append_log(
            operation="reflect",
            title="reflection requested",
            details=[
                f"mode={info['mode']}",
                f"decision={info['decision']}",
                f"sum_importance={info['sum_importance']}",
                f"changes_since_last={info['count_changes']}",
                "Note: the AI agent must read knowledge/insights/ and generate "
                "the actual insight files.",
            ],
            root=root,
        )

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.check_threshold:
        print(info["decision"])
    else:
        print(
            f"mode={info['mode']} decision={info['decision']} "
            f"sum_importance={info['sum_importance']} "
            f"changes={info['count_changes']} elapsed_days={info['elapsed_days']}"
        )
        for r in info["reasons"]:
            print(f"  reason: {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
