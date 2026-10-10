#!/usr/bin/env python3
"""kb_reflect — reflection trigger logic for AI Knowledge Engine.

This script does NOT run the actual reflection (that's an LLM task done by
the AI agent). It decides whether a reflection is due, based on:

  - the operating mode (`knowledge_base.mode`) and its `mode_profiles`
    reflection block
  - the weighted change score since the last reflection: every `ingest`
    in log.md weighs its importance (`default_ingest_importance`, 1, when it
    has none); every changed knowledge/ page weighs its `importance` (3 when
    unset); generated and archived pages and access tracking do not count
  - the days since the last reflection (weekly profiles); a base that never
    reflected counts them from its deployment (`deployed_at` in kb.config.yml,
    or the first log.md entry when that is older or `deployed_at` is unset)

Decisions (documented in kb-docs/13_AUTORUN.md):

  THRESHOLD_MET  — a reflection is due: the score reached the threshold
                   (importance_threshold; 1 once a weekly profile's
                   min_interval_days have passed)
  STAGNANT       — it would be due, but the last two reflections found 0
                   insights and no ingest arrived since
  SKIP           — nothing to do

Only --record-result writes state (`.last_reflection`, the page snapshot
`.kb-state/reflection-pages.json` and a `reflect` log entry); --generate
appends a `reflect-request` log entry when the decision is THRESHOLD_MET.
Every other mode is read-only.

Usage:
  python3 scripts/kb_reflect.py --check-threshold          # prints the decision
  python3 scripts/kb_reflect.py --check-threshold --json   # check() as JSON
  python3 scripts/kb_reflect.py --count-changes            # changes since last reflection
  python3 scripts/kb_reflect.py --json                     # full report + exploration pairs
  python3 scripts/kb_reflect.py --generate                 # log a request when due
  python3 scripts/kb_reflect.py --record-result 2          # reflection done, 2 insights
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

REFLECTION_MARKER = ".last_reflection"
# Page digests at the last --record-result (in .kb-state/, machine-local).
PAGE_SNAPSHOT = "reflection-pages.json"
REQUEST_OPERATION = "reflect-request"
DEFAULT_INGEST_IMPORTANCE = 1
DEFAULT_PAGE_IMPORTANCE = 3
LOG_HEADING_RE = re.compile(
    r"^## \[(?P<ts>[^\]]+)\]\s+(?P<op>[a-z\-]+)\s+\|\s+(?P<title>.+)$",
    re.MULTILINE,
)
# Before 0.16 `--generate` logged its request as a `reflect` entry.
_LEGACY_REQUEST_TITLE = "reflection requested"
# Access tracking (`last_accessed`, `access_count += 1` on pages that shaped
# an answer) is not a knowledge change.
_ACCESS_LINE_RE = re.compile(
    r"^(?:last_accessed|access_count)[ \t]*:.*(?:\r?\n|\Z)", re.MULTILINE
)
# Without a snapshot these dates are the only change evidence a clone keeps.
_PAGE_DATE_KEYS = ("extracted_at", "last_verified", "valid_from")
# --record-result logs its `reflect` entry (whole seconds), then writes the
# marker (sub-second): both belong to one record when this close.
_SAME_RECORD = _dt.timedelta(seconds=5)

LogEntry = tuple[_dt.datetime, str, str]


class _LastReflection(NamedTuple):
    when: _dt.datetime | None  # None: never reflected
    source: str | None  # "marker" (.last_reflection), "log" or None
    after: list[LogEntry]  # log entries written after it


def _read_marker(path: Path) -> _dt.datetime | None:
    if not path.is_file():
        return None
    try:
        ts = float(path.read_text(encoding="utf-8").strip())
        return _dt.datetime.fromtimestamp(ts).astimezone()
    except (ValueError, OSError, OverflowError):
        return None


def _marker_text(when: _dt.datetime) -> str:
    # Sub-second precision: insight pages written just before
    # --record-result must not count as changes after it.
    return f"{when.timestamp():.3f}"


def _write_marker(path: Path, when: _dt.datetime | None = None) -> None:
    kbc.atomic_write_text(path, _marker_text(when or _dt.datetime.now().astimezone()))


def _parse_timestamp(value: str) -> _dt.datetime | None:
    try:
        ts = _dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    # A naive timestamp (hand-written entry) is local time.
    return ts if ts.tzinfo else ts.astimezone()


def _parse_log(root: Path) -> list[LogEntry]:
    log = kbc.log_path(root)
    if not log.is_file():
        return []
    try:
        text, _encoding = kbc.read_text_auto(log)
    except OSError:
        return []
    out: list[LogEntry] = []
    for m in LOG_HEADING_RE.finditer(text):
        ts = _parse_timestamp(m.group("ts"))
        if ts is not None:
            out.append((ts, m.group("op"), m.group("title").strip()))
    return out


_ZERO_INSIGHT_RE = re.compile(r"\b(0|zero)\s+insights?\b", re.IGNORECASE)
_INSIGHT_COUNT_RE = re.compile(r"insights?\s*[=:]\s*(\d+)", re.IGNORECASE)


def _reflect_insight_count(title: str) -> int | None:
    match = _INSIGHT_COUNT_RE.search(title)
    if match:
        return int(match.group(1))
    if _ZERO_INSIGHT_RE.search(title):
        return 0
    return None


def _is_result(entry: LogEntry) -> bool:
    """A `reflect` entry that records a finished reflection (not a request)."""
    return entry[1] == "reflect" and entry[2].strip().lower() != _LEGACY_REQUEST_TITLE


def _last_reflection(root: Path, log_entries: list[LogEntry]) -> _LastReflection:
    """The newer of `.last_reflection` and the last recorded reflection in log.md.

    The log fallback keeps a base without the (gitignored) marker — a fresh
    clone — from recounting all its ingests. log.md is append-only with
    whole-second timestamps while the marker has sub-second precision, so the
    entries after the reflection are cut by position when the `reflect` entry
    belongs to it: an ingest logged in the same second right after
    --record-result still counts.
    """
    marker = _read_marker(root / REFLECTION_MARKER)
    index = next(
        (i for i in range(len(log_entries) - 1, -1, -1) if _is_result(log_entries[i])),
        None,
    )
    logged = log_entries[index][0] if index is not None else None
    same_record = (
        marker is not None and logged is not None and abs(marker - logged) < _SAME_RECORD
    )
    if index is not None and (same_record or marker is None or logged > marker):
        return _LastReflection(
            marker if same_record else logged,
            "marker" if same_record else "log",
            log_entries[index + 1:],
        )
    if marker is not None:
        second = marker.replace(microsecond=0)
        return _LastReflection(
            marker, "marker", [entry for entry in log_entries if entry[0] >= second]
        )
    return _LastReflection(None, None, list(log_entries))


def _stagnation(log_entries: list[LogEntry], last: _LastReflection) -> bool:
    """Last two reflections found 0 insights and no ingest arrived since."""
    results = [entry for entry in log_entries if _is_result(entry)]
    if len(results) < 2:
        return False
    if [_reflect_insight_count(title) for _ts, _op, title in results[-2:]] != [0, 0]:
        return False
    return not any(op == "ingest" for _ts, op, _title in last.after)


def _as_importance(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return None


def _ingest_importance(root: Path, stable_filename: str) -> int | None:
    """Importance recorded in the ingest metadata of one asset, if any."""
    md_dir = root / "processed" / "extracted-metadata"
    for name in (f"{Path(stable_filename).stem}.yml", f"{stable_filename}.yml"):
        path = md_dir / name
        if not path.is_file():
            continue
        try:
            data = kbc.yaml_load(kbc.read_text_auto(path)[0])
        except Exception:  # noqa: BLE001 — unreadable metadata weighs the default
            continue
        if isinstance(data, dict) and data.get("stable_filename") in (None, stable_filename):
            return _as_importance(data.get("importance"))
    return None


def _page_digest(text: str) -> str:
    """Digest of a page's content; access-tracking frontmatter lines excluded."""
    _meta, body = kbc.parse_frontmatter(text)
    text = text.lstrip("\ufeff")
    head = text[: len(text) - len(body)] if text.endswith(body) else ""
    payload = _ACCESS_LINE_RE.sub("", head) + "\0" + body
    return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _knowledge_pages(root: Path) -> list[tuple[Path, str]]:
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return []
    pages = []
    for page in sorted(knowledge.rglob("*.md")):
        rel = kbc.posix_relpath(page, root)
        if not kbc.is_archived(rel):
            pages.append((page, rel))
    return pages


def _write_page_snapshot(root: Path, stamp: str) -> None:
    digests: dict[str, str] = {}
    for page, rel in _knowledge_pages(root):
        try:
            digests[rel] = _page_digest(kbc.read_text_auto(page)[0])
        except (OSError, UnicodeError):
            continue
    kbc.atomic_write_text(
        kbc.state_dir(root) / PAGE_SNAPSHOT,
        json.dumps({"at": stamp, "pages": digests}, ensure_ascii=False, sort_keys=True),
    )


def _read_page_snapshot(root: Path) -> dict[str, str] | None:
    """Digests stored by the --record-result that wrote the current marker."""
    try:
        data = json.loads((root / kbc.STATE_DIR / PAGE_SNAPSHOT).read_text(encoding="utf-8"))
        stamp = (root / REFLECTION_MARKER).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("at") != stamp:
        return None
    pages = data.get("pages")
    return pages if isinstance(pages, dict) else None


def _page_date(value: Any) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return (value.astimezone() if value.tzinfo else value).date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _dated_on_or_after(meta: dict[str, Any], day: _dt.date) -> bool:
    dates = (_page_date(meta.get(key)) for key in _PAGE_DATE_KEYS)
    return any(date is not None and date >= day for date in dates)


def _changed_pages(root: Path, last: _LastReflection) -> list[tuple[str, int]]:
    """(page, importance) for knowledge/ pages changed since the last reflection.

    Evidence, best first: the page snapshot of the --record-result that wrote
    `.last_reflection` (the content changed; access tracking excluded);
    `.last_reflection` alone (bases from before 0.16): the mtime; the log
    alone (a fresh clone, whose checkout reset every mtime, or a reflection
    recorded on another machine): a frontmatter date on or after the day of
    the last reflection. An mtime at or before
    the last reflection always means unchanged. Generated and archived pages
    never count.
    """
    since = last.when
    cutoff = since.timestamp() if since else None
    snapshot = _read_page_snapshot(root) if last.source == "marker" else None
    out: list[tuple[str, int]] = []
    for page, rel in _knowledge_pages(root):
        try:
            if cutoff is not None and page.stat().st_mtime <= cutoff:
                continue
            text, _encoding = kbc.read_text_auto(page)
        except (OSError, UnicodeError):
            continue
        meta, _body = kbc.parse_frontmatter(text)
        if kbc.is_generated(meta):
            continue
        if snapshot is not None:
            if snapshot.get(rel) == _page_digest(text):
                continue
        elif last.source == "log" and not _dated_on_or_after(meta, since.date()):
            continue
        importance = _as_importance(meta.get("importance"))
        out.append((rel, DEFAULT_PAGE_IMPORTANCE if importance is None else importance))
    return out


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _profile_settings(cfg: kbc.KbConfig) -> dict[str, Any]:
    profile = cfg.profile()
    profiles = cfg.raw.get("mode_profiles")
    mode_profile = profiles.get(cfg.mode) if isinstance(profiles, dict) else None
    reflection = mode_profile.get("reflection") if isinstance(mode_profile, dict) else None
    ingest_importance = _as_importance(
        reflection.get("default_ingest_importance") if isinstance(reflection, dict) else None
    )
    return {
        "trigger": str(profile.reflection_trigger or ""),
        "threshold": _non_negative_int(profile.reflection_importance_threshold, 25),
        "min_interval_days": _non_negative_int(profile.reflection_min_interval_days, 7),
        "require_changes": profile.reflection_require_changes is not False,
        "max_insights_per_run": profile.reflection_max_insights_per_run,
        "ingest_importance": (
            DEFAULT_INGEST_IMPORTANCE if ingest_importance is None else ingest_importance
        ),
    }


def _deployed_at(cfg: kbc.KbConfig, log_entries: list[LogEntry]) -> _dt.datetime | None:
    """When the base started: the older of `deployed_at` and the first log entry.

    Starts the weekly clock of a base that never reflected, so its first
    ingest is not a reflection on its own.
    """
    value = cfg.raw.get("deployed_at")
    if isinstance(value, _dt.datetime):
        deployed = value if value.tzinfo else value.astimezone()
    elif isinstance(value, _dt.date):
        deployed = _dt.datetime.combine(value, _dt.time()).astimezone()
    elif isinstance(value, str):
        deployed = _parse_timestamp(value)
    else:
        deployed = None
    candidates = [when for when in (deployed, log_entries[0][0] if log_entries else None) if when]
    return min(candidates) if candidates else None


def _evaluate(root: Path) -> dict[str, Any]:
    """Everything check() and determine_action() report. Never writes."""
    cfg = kbc.load_config(root)
    settings = _profile_settings(cfg)
    log_entries = _parse_log(root)
    last = _last_reflection(root, log_entries)
    since = last.when
    now = _dt.datetime.now().astimezone()

    ingests = [title for _ts, op, title in last.after if op == "ingest"]
    ingest_score = 0
    for title in ingests:
        importance = _ingest_importance(root, title)
        ingest_score += settings["ingest_importance"] if importance is None else importance
    pages = _changed_pages(root, last)
    count = len(ingests) + len(pages)
    score = ingest_score + sum(importance for _page, importance in pages)

    # Never reflected: count the weekly interval from the deployment.
    deployed = None if since else _deployed_at(cfg, log_entries)
    clock = since or deployed
    elapsed_days = (now - clock).days if clock else None
    threshold = settings["threshold"]
    trigger: str | None = None
    if count > 0 and score >= threshold:
        trigger = "importance"
    elif settings["trigger"].startswith("threshold+weekly") and (
        elapsed_days is None or elapsed_days >= settings["min_interval_days"]
    ):
        # Weekly profiles: once min_interval_days passed, any change is due
        # (with require_changes: false even none).
        weekly_threshold = 1 if settings["require_changes"] else 0
        if score >= weekly_threshold:
            trigger, threshold = "weekly", min(threshold, weekly_threshold)

    stagnated = _stagnation(log_entries, last)
    if trigger is None:
        decision = "SKIP"
    else:
        decision = "STAGNANT" if stagnated else "THRESHOLD_MET"

    if trigger == "weekly":
        if since:
            ago = f"last reflection {elapsed_days} days ago"
        elif deployed:
            ago = f"no reflection since deployment {elapsed_days} days ago"
        else:
            ago = "last reflection never"
        reason = f"weekly: {ago}, change score {score}"
    else:
        relation = "≥" if trigger else "<"
        reason = f"change score {score} {relation} threshold {threshold}"
    if decision == "STAGNANT":
        reason += "; stagnation: the last two reflections found 0 insights, no ingest since"

    return {
        "cfg": cfg,
        "settings": settings,
        "decision": decision,
        "changes": score,
        "count": count,
        "ingests": len(ingests),
        "pages": [page for page, _importance in pages],
        "threshold": threshold,
        "trigger": trigger,
        "reason": reason,
        "since": since,
        "elapsed_days": elapsed_days,
        "stagnation": stagnated,
    }


def check(root: Path) -> dict[str, Any]:
    """Read-only reflection decision (the ``--check-threshold --json`` shape).

    ``changes`` is the weighted change score compared with ``threshold``;
    ``count`` is the number of changed items; ``reason`` is one line for
    humans (STATUS.md).
    """
    info = _evaluate(root)
    return {
        "decision": info["decision"],
        "changes": info["changes"],
        "threshold": info["threshold"],
        "mode": info["cfg"].mode,
        "count": info["count"],
        "trigger": info["trigger"],
        "reason": info["reason"],
    }


def determine_action(root: Path, *, exploration: bool = True) -> dict[str, Any]:
    """Full, read-only report: check() plus the agent's reflection brief.

    ``exploration=False`` leaves ``exploration`` as None: building the graph
    is the costly part, needed only for --json and a logged request.
    """
    info = _evaluate(root)
    settings = info["settings"]
    since = info["since"]
    return {
        "mode": info["cfg"].mode,
        "decision": info["decision"],
        "reason": info["reason"],
        "trigger": info["trigger"],
        "changes": info["changes"],
        "count": info["count"],
        # Pre-0.16 names, kept for agents reading older docs.
        "count_changes": info["count"],
        "sum_importance": info["changes"],
        "ingests_since": info["ingests"],
        "pages_changed": info["pages"],
        "threshold": info["threshold"],
        "importance_threshold": settings["threshold"],
        "min_interval_days": settings["min_interval_days"],
        "elapsed_days": info["elapsed_days"],
        "last_reflection": since.isoformat() if since else None,
        "max_insights_per_run": settings["max_insights_per_run"],
        "honest_zero_ok": True,
        # Level-2 meta-insights need new level-0 facts (ingests).
        "meta_insight_allowed": info["ingests"] > 0,
        "stagnation": info["stagnation"],
        "exploration": exploration_slot(root) if exploration else None,
    }


def record_result(root: Path, insights: int) -> None:
    """Log a finished reflection and reset the trigger. 0 insights is valid."""
    insights = max(insights, 0)
    kbc.append_log(
        operation="reflect",
        title=f"insights: {min(insights, 999)}",
        details=[
            "zero insights is a valid expected outcome"
            if insights == 0
            else "ceiling is max_insights_per_run (not a quota)",
        ],
        root=root,
    )
    # After the log entry, so the marker is never older than it. Snapshot
    # first: a crash in between leaves a snapshot no marker matches (ignored).
    when = _dt.datetime.now().astimezone()
    _write_page_snapshot(root, _marker_text(when))
    _write_marker(root / REFLECTION_MARKER, when)


def request_reflection(root: Path, info: dict[str, Any]) -> str:
    """Log a `reflect-request` when one is due and none is waiting.

    Returns "logged", "pending" (a request since the last reflection is still
    open) or "not-due" (the decision is not THRESHOLD_MET: nothing logged).
    """
    if info["decision"] != "THRESHOLD_MET":
        return "not-due"
    last = _last_reflection(root, _parse_log(root))
    if any(op == REQUEST_OPERATION for _ts, op, _title in last.after):
        return "pending"
    if info.get("exploration") is None:
        info["exploration"] = exploration_slot(root)
    exploration = info["exploration"] or []
    kbc.append_log(
        operation=REQUEST_OPERATION,
        title=f"reflection requested ({info['decision']})",
        details=[
            f"mode={info['mode']}",
            f"decision={info['decision']}",
            f"reason={info['reason']}",
            f"changes={info['changes']} (count {info['count']})",
            f"max_insights_per_run={info['max_insights_per_run']} (ceiling, not a quota)",
            "zero insights is a valid expected outcome",
            f"meta_insight_allowed={info['meta_insight_allowed']}",
            f"exploration_pairs={len(exploration)}",
            *[f"exploration: {item.get('prompt')}" for item in exploration],
            "Note: the AI agent must read knowledge/insights/ and generate "
            "the actual insight files, then run "
            "`python3 scripts/kb_reflect.py --record-result N`. At most two "
            "exploration questions (disconnected graph components, overlap "
            "< 0.8); skip if none.",
        ],
        root=root,
    )
    return "logged"


def exploration_slot(root: Path) -> list[dict]:
    """1–2 graph gaps for the reflection write-up. Empty is valid."""
    try:
        import kb_view
    except Exception:
        return []
    try:
        graph = kb_view.build_graph(root)
        return kb_view.exploration_pairs(graph)
    except Exception:
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — reflection trigger")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--check-threshold", action="store_true",
                        help="print the decision: THRESHOLD_MET / STAGNANT / SKIP")
    parser.add_argument("--count-changes", action="store_true",
                        help="print the number of changes since the last reflection")
    parser.add_argument("--dry-run", action="store_true",
                        help="deprecated: checks never write (only --record-result does)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--generate", action="store_true",
                        help="on THRESHOLD_MET, log a `reflect-request` for the AI agent "
                             "(the reflection itself is AI work)")
    parser.add_argument(
        "--record-result",
        type=int,
        default=None,
        metavar="N",
        help="log a finished reflection with N insights (0 is valid) and reset the trigger",
    )
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        kbc.print_err(
            f"❌ [reflect] {root} is not a knowledge base (no kb.config.yml); "
            "pass --root <base>"
        )
        return 2
    if args.dry_run:
        kbc.print_err(
            "ℹ️  [reflect] --dry-run is deprecated: checks never write "
            "(only --record-result does)"
        )

    if args.record_result is not None:
        record_result(root, args.record_result)
        print(f"recorded insights={max(args.record_result, 0)}")
        return 0

    if args.count_changes:
        print(check(root)["count"])
        return 0

    if args.check_threshold and not args.generate:
        result = check(root)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
              else result["decision"])
        return 0

    info = determine_action(root, exploration=args.json)
    if args.generate:
        status = request_reflection(root, info)
        if status == "pending":
            kbc.print_err("ℹ️  [reflect] a reflection request is already pending; "
                          "finish it with --record-result N")
        elif status == "not-due":
            kbc.print_err(f"ℹ️  [reflect] no reflection due ({info['decision']}); "
                          "nothing logged")

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.check_threshold:
        print(info["decision"])
    else:
        print(
            f"mode={info['mode']} decision={info['decision']} "
            f"changes={info['changes']} threshold={info['threshold']} "
            f"count={info['count']} elapsed_days={info['elapsed_days']}"
        )
        print(f"  reason: {info['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
