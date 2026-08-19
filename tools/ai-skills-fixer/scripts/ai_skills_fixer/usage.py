"""Advisory usage-telemetry scanning (spec §14).

Reads host session logs offline and records only aggregate counts,
evidence levels, and last-seen dates. Prompt or response content is
never extracted, stored, or reported. Absence of telemetry is
``not-observed`` — never proof of non-use.

Evidence levels used here:

- ``explicit`` — the host emitted a skill invocation event;
- ``strong`` — a session referenced the exact skill path;
- ``not-observed`` — no supported evidence found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SKILL_INVOKE_RE = re.compile(r'"skill"\s*:\s*"([^"]+)"')
SKILL_PATH_RE = re.compile(r"/skills/([A-Za-z0-9._-]+)/")

LEVEL_RANK = {"not-observed": 0, "strong": 1, "explicit": 2}


@dataclass
class UsageEvidence:
    skill: str
    host: str
    level: str
    count: int
    last_seen: str | None  # ISO date of the newest log file with a hit


def _file_date(path: Path) -> str:
    return datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    ).date().isoformat()


def _collect(hits: dict, skill: str, level: str, seen_date: str) -> None:
    entry = hits.setdefault(
        (skill, level), {"count": 0, "last_seen": None}
    )
    entry["count"] += 1
    if entry["last_seen"] is None or seen_date > entry["last_seen"]:
        entry["last_seen"] = seen_date


def _evidence_list(hits: dict, host: str) -> list[UsageEvidence]:
    return sorted(
        (
            UsageEvidence(
                skill=skill,
                host=host,
                level=level,
                count=entry["count"],
                last_seen=entry["last_seen"],
            )
            for (skill, level), entry in hits.items()
        ),
        key=lambda e: (e.skill, e.level),
    )


def scan_claude_usage(
    projects_dir: Path, installed: set[str]
) -> list[UsageEvidence]:
    projects_dir = Path(projects_dir)
    if not projects_dir.is_dir():
        return []
    hits: dict = {}
    for path in sorted(projects_dir.rglob("*.jsonl")):
        try:
            seen_date = _file_date(path)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    is_invocation = '"name":"Skill"' in line or '"name": "Skill"' in line
                    if is_invocation:
                        for name in SKILL_INVOKE_RE.findall(line):
                            if name in installed:
                                _collect(hits, name, "explicit", seen_date)
                    for name in SKILL_PATH_RE.findall(line):
                        if name in installed:
                            _collect(hits, name, "strong", seen_date)
        except OSError:
            continue
    return _evidence_list(hits, "claude")


def scan_codex_usage(
    session_dirs: list[Path], installed: set[str]
) -> list[UsageEvidence]:
    hits: dict = {}
    for base in session_dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            try:
                seen_date = _file_date(path)
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        for name in SKILL_PATH_RE.findall(line):
                            if name in installed:
                                _collect(hits, name, "strong", seen_date)
            except OSError:
                continue
    return _evidence_list(hits, "codex")


def merge_evidence(
    installed: set[str], evidence: list[UsageEvidence]
) -> list[UsageEvidence]:
    """One row per installed skill: the strongest level wins."""
    best: dict[str, UsageEvidence] = {}
    for item in evidence:
        current = best.get(item.skill)
        if current is None or LEVEL_RANK[item.level] > LEVEL_RANK[current.level]:
            best[item.skill] = item
    merged = []
    for skill in sorted(installed):
        if skill in best:
            merged.append(best[skill])
        else:
            merged.append(UsageEvidence(
                skill=skill, host="", level="not-observed", count=0,
                last_seen=None,
            ))
    return merged
