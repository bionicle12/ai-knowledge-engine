#!/usr/bin/env python3
"""kb_lint — Level-1 health check for the knowledge base.

Runs deterministic checks on knowledge/**.md without using any LLM.
Level 2 (AI review) is performed by the agent on demand via !audit.

Checks:
  * frontmatter:      required fields (source, extracted_at, tags, lifecycle)
  * stale:            last_verified > N days (skips lifecycle: permanent)
  * broken-link:      [[wikilinks]] pointing to nonexistent files
  * orphan:           pages without inbound wikilinks
  * source-hash:      hash mismatch between knowledge page and asset
                      (skips lifecycle: permanent)
  * duplicate-slug:   same filename in different subfolders
  * empty-category:   knowledge/<sub>/ with no .md
  * superseded:       supersedes:<x> but x not in _archive/
  * domain-overflow:  > 15 .md in a single subfolder
  * expired-temporal: lifecycle=temporal with valid_until in the past
  * annotation-overflow: > 5 context_annotations on a page
  * invariants:           required AI-KE:INVARIANT blocks in AGENTS.md
  * agents-bytes:         AGENTS.md larger than configured byte budget
  * instruction-absolutes: always/never/must/forbidden outside INVARIANT
  * work-ordering:        phrases that inflate reasoning ("thoroughly", …)
  * instruction-duplicates: AGENTS.md restates privacy/language_policy
  * instructions-review:  instructions_review.reviewed_at older than N days
  * assumption-hotspot:   >N ## Assumptions bullets for one knowledge/ area in 30 days
  * profile-review:       profile_review.reviewed_at older than 30 days

Exit codes:
  0 — no issues
  1 — only warnings (or info)
  2 — at least one error

Usage:
  python3 scripts/kb_lint.py
  python3 scripts/kb_lint.py --quick           # errors only
  python3 scripts/kb_lint.py --only frontmatter,broken-link
  python3 scripts/kb_lint.py --output report   # write to lint-report.md
  python3 scripts/kb_lint.py --json
  python3 scripts/kb_lint.py --fix             # apply safe auto-fixes
  python3 scripts/kb_lint.py --metrics         # include health metrics
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


REQUIRED_FRONTMATTER_FIELDS = ("source", "extracted_at", "tags", "lifecycle")
VALID_LIFECYCLES = ("permanent", "evolving", "temporal")
DEFAULT_STALE_DAYS = 30
DEFAULT_DOMAIN_OVERFLOW = 15
DEFAULT_ANNOTATION_OVERFLOW = 5

ALL_CHECKS = (
    "frontmatter",
    "stale",
    "broken-link",
    "orphan",
    "source-hash",
    "duplicate-slug",
    "empty-category",
    "superseded",
    "domain-overflow",
    "expired-temporal",
    "annotation-overflow",
    "invariants",
    "agents-bytes",
    "instruction-absolutes",
    "work-ordering",
    "instruction-duplicates",
    "instructions-review",
    "assumption-hotspot",
    "profile-review",
)

# Instruction-budget knobs live in top-level `instructions_lint:` (not under
# mode_profiles.*.lint, which is L2). Numbers are defaults for old bases.
DEFAULT_AGENTS_MAX_BYTES = 10240
DEFAULT_ABSOLUTE_MAX_OUTSIDE_INVARIANTS = 8
DEFAULT_REVIEW_STALE_DAYS = 90
DEFAULT_ASSUMPTION_MAX_PER_AREA = 3
DEFAULT_ASSUMPTION_WINDOW_DAYS = 30
DEFAULT_PROFILE_REVIEW_DAYS = 30
_AREA_RE = re.compile(
    r"(?:knowledge/)?(domain|decisions|playbooks|insights|profile|"
    r"principles|voice|opinions|routing)/"
)
_ASSUMPTION_BULLET_RE = re.compile(r"^[-*]\s+\S", re.MULTILINE)
DEFAULT_WORK_ORDERING_PHRASES = (
    "максимально тщательно",
    "рассмотри все варианты",
    "перепроверь несколько раз",
    "добейся полной уверенности",
    "thoroughly",
    "consider all",
    "be maximally",
)
_ABSOLUTE_RE = re.compile(r"\b(always|never|must|forbidden)\b", re.IGNORECASE)


@dataclass
class LintIssue:
    check: str
    severity: str            # "error" | "warning" | "info"
    path: str
    message: str
    fixable: bool = False


@dataclass
class LintReport:
    root: str
    pages_scanned: int = 0
    issues: list[LintIssue] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    metrics: dict | None = None

    @property
    def errors(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def infos(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> _dt.date:
    return _dt.date.today()


def _parse_date(value) -> _dt.date | None:
    if value is None:
        return None
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _knowledge_pages(root: Path) -> list[Path]:
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return []
    return sorted(p for p in knowledge.rglob("*.md") if p.is_file())


def _relative_to_root(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


@dataclass
class PageData:
    """One knowledge page, read and parsed exactly once per lint run."""

    path: Path
    meta: dict
    body: str
    text: str
    wikilinks: list[str] = field(default_factory=list)


def _load_pages(root: Path, report: LintReport) -> list[PageData]:
    """Read every knowledge page once and cache (meta, body, wikilinks).

    A file that cannot be read or parsed becomes a single ``unreadable``
    error instead of crashing the whole run, and is excluded from the
    per-page checks (they could only misreport on garbage anyway).
    """
    out: list[PageData] = []
    for p in _knowledge_pages(root):
        try:
            text = p.read_text(encoding="utf-8-sig")
            meta, body = kbc.parse_frontmatter(text)
        except Exception as e:  # noqa: BLE001
            report.issues.append(
                LintIssue(
                    check="unreadable",
                    severity="error",
                    path=_relative_to_root(p, root),
                    message=f"failed to read/parse: {e}",
                )
            )
            continue
        out.append(
            PageData(
                path=p,
                meta=meta,
                body=body,
                text=text,
                wikilinks=[t.strip() for t in kbc.extract_wikilinks(text)],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_frontmatter(
    pages: list[PageData], root: Path, *, fix: bool, report: LintReport
) -> None:
    today_iso = _today().isoformat()
    for page in pages:
        p, meta, body = page.path, page.meta, page.body
        missing = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in meta]
        invalid_lifecycle = (
            "lifecycle" in meta and meta["lifecycle"] not in VALID_LIFECYCLES
        )

        # Auto-fixable: missing lifecycle, missing tags, missing extracted_at
        fix_made = False
        if fix and missing:
            for f in list(missing):
                if f == "lifecycle":
                    meta["lifecycle"] = "evolving"
                    missing.remove(f)
                    fix_made = True
                elif f == "tags":
                    meta["tags"] = []
                    missing.remove(f)
                    fix_made = True
                elif f == "extracted_at":
                    meta["extracted_at"] = today_iso
                    missing.remove(f)
                    fix_made = True
            if fix_made:
                kbc.write_frontmatter_file(p, meta, body)
                report.fixed.append(
                    f"frontmatter:{_relative_to_root(p, root)} "
                    f"({'+'.join(REQUIRED_FRONTMATTER_FIELDS)} defaults applied)"
                )

        if missing:
            report.issues.append(
                LintIssue(
                    check="frontmatter",
                    severity="error",
                    path=_relative_to_root(p, root),
                    message=f"missing required fields: {', '.join(missing)}",
                    fixable=any(
                        m in ("lifecycle", "tags", "extracted_at") for m in missing
                    ),
                )
            )

        if invalid_lifecycle:
            report.issues.append(
                LintIssue(
                    check="frontmatter",
                    severity="error",
                    path=_relative_to_root(p, root),
                    message=(
                        f"invalid lifecycle: {meta['lifecycle']!r} "
                        f"(must be one of {VALID_LIFECYCLES})"
                    ),
                )
            )


def _check_stale(
    pages: list[PageData], root: Path, *, threshold_days: int, report: LintReport
) -> None:
    today = _today()
    for page in pages:
        p, meta = page.path, page.meta
        if meta.get("lifecycle") == "permanent":
            continue
        verified = _parse_date(meta.get("last_verified") or meta.get("extracted_at"))
        if verified is None:
            continue
        age = (today - verified).days
        if age > threshold_days:
            report.issues.append(
                LintIssue(
                    check="stale",
                    severity="warning",
                    path=_relative_to_root(p, root),
                    message=f"last_verified is {age} days old (threshold: {threshold_days})",
                )
            )


def _check_broken_links(pages: list[PageData], root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    slugs = kbc.scan_knowledge_slugs(knowledge)
    for page in pages:
        p = page.path
        for target in page.wikilinks:
            if "/" in target:
                # explicit path: knowledge/path/slug
                candidate = knowledge / f"{target}.md"
                if not candidate.is_file():
                    report.issues.append(
                        LintIssue(
                            check="broken-link",
                            severity="error",
                            path=_relative_to_root(p, root),
                            message=f"[[{target}]] does not resolve to a knowledge file",
                        )
                    )
            else:
                if target not in slugs:
                    report.issues.append(
                        LintIssue(
                            check="broken-link",
                            severity="error",
                            path=_relative_to_root(p, root),
                            message=f"[[{target}]] does not resolve",
                        )
                    )


def _orphan_paths(pages: list[PageData], knowledge: Path) -> set[Path]:
    """Pages with no inbound wikilink from any *other* page.

    routing/ pages and routing-table.md are entry points and never counted.
    Single source of truth for both the orphan check and the metrics, so the
    two never drift apart again.
    """
    incoming: dict[str, set[Path]] = {}
    for page in pages:
        for target in page.wikilinks:
            incoming.setdefault(target, set()).add(page.path)
    orphans: set[Path] = set()
    for page in pages:
        p = page.path
        rel = p.relative_to(knowledge)
        if rel.parts and rel.parts[0] == "routing":
            continue
        if rel.name == "routing-table.md":
            continue
        rel_no_ext = kbc.posix_relpath(p, knowledge, without_suffix=True)
        sources = incoming.get(p.stem, set()) | incoming.get(rel_no_ext, set())
        if not (sources - {p}):
            orphans.add(p)
    return orphans


def _check_orphans(pages: list[PageData], root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    for p in sorted(_orphan_paths(pages, knowledge)):
        report.issues.append(
            LintIssue(
                check="orphan",
                severity="warning",
                path=_relative_to_root(p, root),
                message="no inbound wikilinks from any other knowledge page",
            )
        )


def _check_source_hash(pages: list[PageData], root: Path, report: LintReport) -> None:
    for page in pages:
        p, meta = page.path, page.meta
        if meta.get("lifecycle") == "permanent":
            continue
        recorded = meta.get("source_hash")
        source = meta.get("source")
        if not recorded or not source:
            continue
        source_path = (root / source).resolve()
        if not source_path.is_file():
            report.issues.append(
                LintIssue(
                    check="source-hash",
                    severity="warning",
                    path=_relative_to_root(p, root),
                    message=f"source file not found: {source}",
                )
            )
            continue
        actual = kbc.compute_source_hash(source_path)
        if actual != recorded:
            report.issues.append(
                LintIssue(
                    check="source-hash",
                    severity="error",
                    path=_relative_to_root(p, root),
                    message=(
                        f"source_hash mismatch: expected {recorded}, actual {actual}. "
                        "Source has been modified — knowledge may be stale."
                    ),
                )
            )


def _check_duplicate_slugs(pages: list[PageData], root: Path, report: LintReport) -> None:
    by_slug: dict[str, list[Path]] = {}
    for page in pages:
        by_slug.setdefault(page.path.stem, []).append(page.path)
    for slug, owners in by_slug.items():
        if len(owners) > 1:
            owners_str = ", ".join(_relative_to_root(o, root) for o in owners)
            report.issues.append(
                LintIssue(
                    check="duplicate-slug",
                    severity="error",
                    path=owners_str,
                    message=f"slug '{slug}' is used by {len(owners)} files",
                )
            )


def _check_empty_categories(root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return
    for sub in sorted(knowledge.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        if sub.name == "_archive":
            continue
        if not any(sub.rglob("*.md")):
            report.issues.append(
                LintIssue(
                    check="empty-category",
                    severity="warning",
                    path=_relative_to_root(sub, root) + "/",
                    message="category contains no .md files",
                )
            )


def _check_superseded(pages: list[PageData], root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    meta_by_path = {page.path: page.meta for page in pages}
    slugs: dict[str, list[Path]] | None = None
    for page in pages:
        p, meta = page.path, page.meta
        target = meta.get("supersedes")
        if not target:
            continue
        # target is a slug or relative path
        if "/" in target:
            replaced = knowledge / f"{target}.md"
        else:
            if slugs is None:
                slugs = kbc.scan_knowledge_slugs(knowledge)
            candidates = slugs.get(target, [])
            replaced = candidates[0] if candidates else None
        if replaced is None or not replaced.exists():
            continue  # nothing to verify
        # Replaced should be in _archive/ (unless it's permanent)
        replaced_meta = meta_by_path.get(replaced)
        if replaced_meta is None:
            replaced_meta, _ = kbc.read_frontmatter_file(replaced)
        if replaced_meta.get("lifecycle") == "permanent":
            continue
        rel = replaced.relative_to(knowledge)
        if rel.parts and rel.parts[0] != "_archive":
            report.issues.append(
                LintIssue(
                    check="superseded",
                    severity="warning",
                    path=_relative_to_root(replaced, root),
                    message=(
                        f"superseded by {_relative_to_root(p, root)} but not in _archive/"
                    ),
                )
            )


def _check_domain_overflow(root: Path, report: LintReport, threshold: int) -> None:
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return
    for sub in knowledge.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        count = sum(1 for _ in sub.rglob("*.md"))
        if count > threshold:
            report.issues.append(
                LintIssue(
                    check="domain-overflow",
                    severity="warning",
                    path=_relative_to_root(sub, root) + "/",
                    message=(
                        f"{count} .md files (threshold: {threshold}). "
                        "Consider creating a routing page."
                    ),
                )
            )


def _check_expired_temporal(pages: list[PageData], root: Path, report: LintReport) -> None:
    today = _today()
    knowledge = root / "knowledge"
    for page in pages:
        p, meta = page.path, page.meta
        if meta.get("lifecycle") != "temporal":
            continue
        valid_until = _parse_date(meta.get("valid_until"))
        if valid_until is None or valid_until >= today:
            continue
        # Expired
        rel = p.relative_to(knowledge)
        if rel.parts and rel.parts[0] == "_archive":
            continue
        report.issues.append(
            LintIssue(
                check="expired-temporal",
                severity="warning",
                path=_relative_to_root(p, root),
                message=(
                    f"valid_until={valid_until.isoformat()} is in the past; "
                    "consider archiving"
                ),
            )
        )


def _check_annotation_overflow(
    pages: list[PageData], root: Path, report: LintReport, threshold: int
) -> None:
    for page in pages:
        p, meta = page.path, page.meta
        ann = meta.get("context_annotations") or []
        if isinstance(ann, list) and len(ann) > threshold:
            report.issues.append(
                LintIssue(
                    check="annotation-overflow",
                    severity="info",
                    path=_relative_to_root(p, root),
                    message=(
                        f"{len(ann)} annotations (threshold: {threshold}). "
                        "Consider consolidating into an insight."
                    ),
                )
            )


# ---------------------------------------------------------------------------
# Instruction-budget checks (AGENTS.md + kb.config.yml)
# ---------------------------------------------------------------------------


def _instructions_lint_settings(root: Path) -> tuple[dict, kbc.KbConfig]:
    cfg = kbc.load_config(root)
    raw = (cfg.raw.get("instructions_lint") or {}) if cfg.raw else {}
    phrases = raw.get("work_ordering_phrases")
    if phrases is None:
        phrase_list = list(DEFAULT_WORK_ORDERING_PHRASES)
    else:
        phrase_list = [str(p) for p in phrases]
    settings = {
        "agents_max_bytes": int(
            raw.get("agents_max_bytes", DEFAULT_AGENTS_MAX_BYTES)
        ),
        "absolute_max_outside_invariants": int(
            raw.get(
                "absolute_max_outside_invariants",
                DEFAULT_ABSOLUTE_MAX_OUTSIDE_INVARIANTS,
            )
        ),
        "review_stale_days": int(
            raw.get("review_stale_days", DEFAULT_REVIEW_STALE_DAYS)
        ),
        "work_ordering_phrases": phrase_list,
    }
    return settings, cfg


def _read_agents_md(root: Path) -> tuple[Path, str] | None:
    path = root / "AGENTS.md"
    if not path.is_file():
        return None
    return path, path.read_text(encoding="utf-8")


def _check_invariants(root: Path, report: LintReport) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, text = loaded
    problems = kbc.invariant_problems(text)
    if not problems:
        return
    report.issues.append(
        LintIssue(
            check="invariants",
            severity="error",
            path=_relative_to_root(path, root),
            message="; ".join(problems),
        )
    )


def _check_agents_bytes(
    root: Path, report: LintReport, *, max_bytes: int
) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, _text = loaded
    size = path.stat().st_size
    if size <= max_bytes:
        return
    report.issues.append(
        LintIssue(
            check="agents-bytes",
            severity="warning",
            path=_relative_to_root(path, root),
            message=(
                f"AGENTS.md is {size} bytes (threshold: {max_bytes}). "
                "Propose `!refactor` to shrink instructions."
            ),
        )
    )


def _check_instruction_absolutes(
    root: Path, report: LintReport, *, max_outside: int
) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, text = loaded
    outside = kbc.strip_invariant_bodies(text)
    hits = _ABSOLUTE_RE.findall(outside)
    if len(hits) <= max_outside:
        return
    report.issues.append(
        LintIssue(
            check="instruction-absolutes",
            severity="warning",
            path=_relative_to_root(path, root),
            message=(
                f"{len(hits)} always/never/must/forbidden outside INVARIANT "
                f"blocks (threshold: {max_outside})."
            ),
        )
    )


def _check_work_ordering(
    root: Path, report: LintReport, *, phrases: list[str]
) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, text = loaded
    lowered = text.lower()
    found = [
        phrase for phrase in phrases if phrase and phrase.lower() in lowered
    ]
    if not found:
        return
    report.issues.append(
        LintIssue(
            check="work-ordering",
            severity="warning",
            path=_relative_to_root(path, root),
            message=(
                "work-ordering phrase(s) inflate reasoning: "
                + ", ".join(found)
            ),
        )
    )


def _check_instruction_duplicates(root: Path, report: LintReport) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, text = loaded
    cfg = kbc.load_config(root)
    privacy = (cfg.raw.get("privacy") or {}) if cfg.raw else {}
    language = (cfg.raw.get("language_policy") or {}) if cfg.raw else {}
    # INVARIANT blocks restate privacy and Language on purpose (B1): they must
    # survive any trim, so a copy there is the design, not debt.
    lower = kbc.strip_invariant_bodies(text).lower()
    dupes: list[str] = []
    if privacy.get("raw_indexing_allowed") is False and (
        "do not index `raw/`" in lower or "do not index raw/" in lower
    ):
        dupes.append("privacy.raw_indexing_allowed")
    if privacy.get("review_indexing_allowed") is False and (
        "do not index `review/`" in lower or "do not index review/" in lower
    ):
        dupes.append("privacy.review_indexing_allowed")
    if privacy.get("interactions_indexing_allowed") is False and (
        "do not index `interactions/`" in lower
        or "do not index interactions/" in lower
    ):
        dupes.append("privacy.interactions_indexing_allowed")
    if language.get("primary") and "primary language" in lower:
        dupes.append("language_policy.primary")
    if not dupes:
        return
    report.issues.append(
        LintIssue(
            check="instruction-duplicates",
            severity="info",
            path=_relative_to_root(path, root),
            message=(
                "AGENTS.md restates config already in kb.config.yml: "
                + ", ".join(dupes)
            ),
        )
    )


def _check_instructions_review(
    root: Path, report: LintReport, *, stale_days: int
) -> None:
    if _read_agents_md(root) is None:
        return
    cfg = kbc.load_config(root)
    review = (cfg.raw.get("instructions_review") or {}) if cfg.raw else {}
    raw_date = review.get("reviewed_at")
    if not raw_date:
        return
    parsed = _parse_date(raw_date)
    if parsed is None:
        return
    age = (_today() - parsed).days
    if age <= stale_days:
        return
    report.issues.append(
        LintIssue(
            check="instructions-review",
            severity="warning",
            path="kb.config.yml",
            message=(
                f"instructions_review.reviewed_at is {age} days old "
                f"(threshold: {stale_days})."
            ),
        )
    )


def _session_date(path: Path, meta: dict) -> _dt.date | None:
    parsed = _parse_date(meta.get("session_date"))
    if parsed:
        return parsed
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if match:
        return _parse_date(match.group(1))
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.parent.name)
    if match:
        return _parse_date(match.group(1))
    return None


def _assumption_bullets(body: str) -> list[str]:
    idx = re.search(r"^##\s+Assumptions\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not idx:
        return []
    rest = body[idx.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    block = rest[: nxt.start()] if nxt else rest
    return [ln.strip() for ln in block.splitlines() if _ASSUMPTION_BULLET_RE.match(ln)]


def _check_assumption_hotspot(root: Path, report: LintReport) -> None:
    sessions = root / "interactions" / "sessions"
    if not sessions.is_dir():
        return
    cutoff = _today() - _dt.timedelta(days=DEFAULT_ASSUMPTION_WINDOW_DAYS)
    per_area: dict[str, int] = {}
    for path in sessions.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            meta, body = kbc.parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        when = _session_date(path, meta)
        if when is None or when < cutoff:
            continue
        for bullet in _assumption_bullets(body):
            hit = _AREA_RE.search(bullet)
            if not hit:
                continue
            area = hit.group(1)
            per_area[area] = per_area.get(area, 0) + 1
    for area, count in sorted(per_area.items()):
        if count <= DEFAULT_ASSUMPTION_MAX_PER_AREA:
            continue
        report.issues.append(
            LintIssue(
                check="assumption-hotspot",
                severity="info",
                path=f"knowledge/{area}/",
                message=(
                    f"{count} assumptions about knowledge/{area}/ in the last "
                    f"{DEFAULT_ASSUMPTION_WINDOW_DAYS} days "
                    f"(threshold: {DEFAULT_ASSUMPTION_MAX_PER_AREA}). "
                    "Tighten DATA_PLACEMENT_EXAMPLES.md for that area."
                ),
            )
        )


def _check_profile_review(root: Path, report: LintReport) -> None:
    cfg = kbc.load_config(root)
    raw = cfg.raw or {}
    block = raw.get("profile_review") or {}
    raw_date = block.get("reviewed_at") or raw.get("profile_reviewed_at")
    if not raw_date:
        return
    parsed = _parse_date(raw_date)
    if parsed is None:
        return
    age = (_today() - parsed).days
    if age <= DEFAULT_PROFILE_REVIEW_DAYS:
        return
    report.issues.append(
        LintIssue(
            check="profile-review",
            severity="warning",
            path="kb.config.yml",
            message=(
                f"profile_review.reviewed_at is {age} days old "
                f"(threshold: {DEFAULT_PROFILE_REVIEW_DAYS}). "
                "Run !profile-review."
            ),
        )
    )


# ---------------------------------------------------------------------------
# Health metrics (--metrics flag)
# ---------------------------------------------------------------------------


def _compute_metrics(pages: list[PageData], root: Path) -> dict:
    """Aggregate health metrics for the knowledge base.

    Returns a dict with:
      - total_pages
      - by_lifecycle: counts of permanent / evolving / temporal
      - by_subfolder: counts per knowledge/ subfolder
      - importance: avg / median / distribution
      - freshness: pages with last_verified <= 30d / 30-90d / >90d / no date
      - orphan_rate: orphans / total
      - wikilink_density: avg outbound links per page
      - entity_coverage: pages with NLP nlp_meta linked
      - routing_depth: number of routing pages and depth
      - insight_ratio: insights / (domain + playbooks + insights)
      - annotation_overflow_count
    """
    knowledge = root / "knowledge"
    metrics: dict = {
        "total_pages": len(pages),
        "by_lifecycle": {"permanent": 0, "evolving": 0, "temporal": 0, "unset": 0},
        "by_subfolder": {},
        "importance": {"avg": 0.0, "median": 0.0, "distribution": {}},
        "freshness": {
            "fresh_le_30d": 0,
            "stale_30_90d": 0,
            "very_stale_gt_90d": 0,
            "no_date": 0,
        },
        "orphan_rate": 0.0,
        "wikilink_density": 0.0,
        "entity_coverage": 0.0,
        "routing": {"pages": 0, "max_depth": 0},
        "insight_ratio": 0.0,
        "annotation_overflow_count": 0,
        "with_source_hash": 0,
    }
    if not pages:
        return metrics

    today = _today()
    importances: list[int] = []
    importance_dist = {"1-2": 0, "3-4": 0, "5-6": 0, "7-8": 0, "9-10": 0}
    total_wikilinks = 0
    counts_per_subfolder: dict[str, int] = {}

    # Pre-pass: outbound link volume
    for page in pages:
        total_wikilinks += len(page.wikilinks)

    for page in pages:
        p, meta = page.path, page.meta

        # Subfolder
        rel = p.relative_to(knowledge)
        sub = rel.parts[0] if len(rel.parts) > 1 else "_root"
        counts_per_subfolder[sub] = counts_per_subfolder.get(sub, 0) + 1

        # Lifecycle
        lc = meta.get("lifecycle", "unset")
        if lc not in metrics["by_lifecycle"]:
            metrics["by_lifecycle"]["unset"] += 1
        else:
            metrics["by_lifecycle"][lc] += 1

        # Importance
        imp = meta.get("importance")
        if isinstance(imp, int) and 1 <= imp <= 10:
            importances.append(imp)
            if imp <= 2:
                importance_dist["1-2"] += 1
            elif imp <= 4:
                importance_dist["3-4"] += 1
            elif imp <= 6:
                importance_dist["5-6"] += 1
            elif imp <= 8:
                importance_dist["7-8"] += 1
            else:
                importance_dist["9-10"] += 1

        # Freshness
        verified = _parse_date(meta.get("last_verified") or meta.get("extracted_at"))
        if verified is None:
            metrics["freshness"]["no_date"] += 1
        else:
            age = (today - verified).days
            if age <= 30:
                metrics["freshness"]["fresh_le_30d"] += 1
            elif age <= 90:
                metrics["freshness"]["stale_30_90d"] += 1
            else:
                metrics["freshness"]["very_stale_gt_90d"] += 1

        # Source hash
        if meta.get("source_hash"):
            metrics["with_source_hash"] += 1

        # NLP meta presence
        if meta.get("nlp_meta_path"):
            metrics["entity_coverage"] += 1

        # Annotation overflow
        ann = meta.get("context_annotations") or []
        if isinstance(ann, list) and len(ann) > 5:
            metrics["annotation_overflow_count"] += 1

    metrics["by_subfolder"] = counts_per_subfolder

    # Importance summary
    if importances:
        importances_sorted = sorted(importances)
        metrics["importance"]["avg"] = round(sum(importances) / len(importances), 2)
        metrics["importance"]["median"] = importances_sorted[len(importances_sorted) // 2]
        metrics["importance"]["distribution"] = importance_dist

    # Orphan rate — same rules as the orphan check (see _orphan_paths)
    orphans = len(_orphan_paths(pages, knowledge))
    metrics["orphan_rate"] = round(orphans / len(pages), 3) if pages else 0.0

    # Wikilink density
    metrics["wikilink_density"] = round(total_wikilinks / len(pages), 2)

    # Entity coverage as ratio
    metrics["entity_coverage"] = round(metrics["entity_coverage"] / len(pages), 3)

    # Routing
    routing_pages = [
        page.path for page in pages
        if page.path.relative_to(knowledge).parts[0:1] == ("routing",)
    ]
    metrics["routing"]["pages"] = len(routing_pages)
    if routing_pages:
        depths = [
            len(p.relative_to(knowledge).parts) for p in routing_pages
        ]
        metrics["routing"]["max_depth"] = max(depths)

    # Insight ratio
    insights = sum(
        1 for page in pages
        if page.path.relative_to(knowledge).parts[0:1] == ("insights",)
    )
    base = sum(
        1 for page in pages
        if page.path.relative_to(knowledge).parts[0:1]
        in (("domain",), ("playbooks",), ("insights",))
    )
    metrics["insight_ratio"] = round(insights / base, 3) if base else 0.0

    return metrics


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_lint(
    root: Path,
    *,
    only: set[str] | None = None,
    quick: bool = False,
    fix: bool = False,
    stale_days: int = DEFAULT_STALE_DAYS,
    domain_overflow: int = DEFAULT_DOMAIN_OVERFLOW,
    annotation_overflow: int = DEFAULT_ANNOTATION_OVERFLOW,
    metrics: bool = False,
) -> LintReport:
    report = LintReport(root=str(root))
    pages = _load_pages(root, report)
    unreadable = sum(1 for i in report.issues if i.check == "unreadable")
    report.pages_scanned = len(pages) + unreadable

    def enabled(name: str) -> bool:
        if only and name not in only:
            return False
        return True

    if enabled("frontmatter"):
        _check_frontmatter(pages, root, fix=fix, report=report)
    if enabled("stale"):
        _check_stale(pages, root, threshold_days=stale_days, report=report)
    if enabled("broken-link"):
        _check_broken_links(pages, root, report)
    if enabled("orphan"):
        _check_orphans(pages, root, report)
    if enabled("source-hash"):
        _check_source_hash(pages, root, report)
    if enabled("duplicate-slug"):
        _check_duplicate_slugs(pages, root, report)
    if enabled("empty-category"):
        _check_empty_categories(root, report)
    if enabled("superseded"):
        _check_superseded(pages, root, report)
    if enabled("domain-overflow"):
        _check_domain_overflow(root, report, threshold=domain_overflow)
    if enabled("expired-temporal"):
        _check_expired_temporal(pages, root, report)
    if enabled("annotation-overflow"):
        _check_annotation_overflow(
            pages, root, report, threshold=annotation_overflow
        )

    instr_settings, _instr_cfg = _instructions_lint_settings(root)
    if enabled("invariants"):
        _check_invariants(root, report)
    if enabled("agents-bytes"):
        _check_agents_bytes(
            root, report, max_bytes=instr_settings["agents_max_bytes"]
        )
    if enabled("instruction-absolutes"):
        _check_instruction_absolutes(
            root,
            report,
            max_outside=instr_settings["absolute_max_outside_invariants"],
        )
    if enabled("work-ordering"):
        _check_work_ordering(
            root,
            report,
            phrases=instr_settings["work_ordering_phrases"],
        )
    if enabled("instruction-duplicates"):
        _check_instruction_duplicates(root, report)
    if enabled("instructions-review"):
        _check_instructions_review(
            root, report, stale_days=instr_settings["review_stale_days"]
        )
    if enabled("assumption-hotspot"):
        _check_assumption_hotspot(root, report)
    if enabled("profile-review"):
        _check_profile_review(root, report)

    if metrics:
        report.metrics = _compute_metrics(pages, root)

    if quick:
        report.issues = [i for i in report.issues if i.severity == "error"]

    return report


def render_text(report: LintReport) -> str:
    icon = {"error": "🔴", "warning": "🟡", "info": "ℹ️ "}
    lines = [
        f"# Lint Report — {_today().isoformat()}",
        "",
        "## Summary",
        f"- Pages scanned: {report.pages_scanned}",
        f"- Errors: {report.errors}",
        f"- Warnings: {report.warnings}",
        f"- Info: {report.infos}",
        f"- Auto-fixed: {len(report.fixed)}",
    ]
    by_severity: dict[str, list[LintIssue]] = {
        "error": [],
        "warning": [],
        "info": [],
    }
    for issue in report.issues:
        by_severity.setdefault(issue.severity, []).append(issue)

    for severity in ("error", "warning", "info"):
        issues = by_severity.get(severity, [])
        if not issues:
            continue
        lines.append("")
        title = {"error": "Errors", "warning": "Warnings", "info": "Info"}[severity]
        lines.append(f"## {icon[severity]} {title}")
        for issue in issues:
            lines.append(
                f"- **[{issue.check}]** `{issue.path}` — {issue.message}"
                + (" *(fixable)*" if issue.fixable else "")
            )

    if report.fixed:
        lines.append("")
        lines.append("## Auto-fixed")
        for entry in report.fixed:
            lines.append(f"- {entry}")

    if report.metrics:
        lines.append("")
        lines.append("## 📊 Health metrics")
        m = report.metrics
        lines.append(f"- Total pages: **{m['total_pages']}**")
        if m["total_pages"]:
            lines.append("")
            lines.append("### Lifecycle distribution")
            for k, v in m["by_lifecycle"].items():
                if v:
                    lines.append(f"- {k}: {v}")

            lines.append("")
            lines.append("### Pages per subfolder")
            for sub, cnt in sorted(m["by_subfolder"].items(), key=lambda x: -x[1]):
                lines.append(f"- `{sub}/`: {cnt}")

            imp = m["importance"]
            if imp.get("distribution"):
                lines.append("")
                lines.append(
                    f"### Importance — avg **{imp['avg']}**, median **{imp['median']}**"
                )
                for bucket, cnt in imp["distribution"].items():
                    if cnt:
                        lines.append(f"- {bucket}: {cnt}")

            lines.append("")
            lines.append("### Freshness")
            for k, v in m["freshness"].items():
                if v:
                    lines.append(f"- {k.replace('_', ' ')}: {v}")

            lines.append("")
            lines.append("### Connectivity")
            lines.append(f"- Wikilink density: {m['wikilink_density']} avg outbound/page")
            lines.append(f"- Orphan rate: {m['orphan_rate'] * 100:.1f}%")
            lines.append(f"- Entity coverage (NLP linked): {m['entity_coverage'] * 100:.1f}%")
            lines.append(f"- Pages with source_hash: {m['with_source_hash']}")

            lines.append("")
            lines.append("### Structure")
            lines.append(f"- Routing pages: {m['routing']['pages']}")
            lines.append(f"- Max routing depth: {m['routing']['max_depth']}")
            lines.append(f"- Insight ratio (insights / domain+playbooks+insights): {m['insight_ratio'] * 100:.1f}%")
            lines.append(f"- Annotation overflow pages (>5): {m['annotation_overflow_count']}")

    return "\n".join(lines) + "\n"


def exit_code(report: LintReport) -> int:
    if report.errors:
        return 2
    if report.warnings or report.infos:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — lint level 1")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--quick", action="store_true", help="errors only")
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=f"comma-separated check names ({', '.join(ALL_CHECKS)})",
    )
    parser.add_argument(
        "--output",
        choices=("stdout", "report"),
        default="stdout",
        help="'report' writes lint-report.md",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON")
    parser.add_argument("--fix", action="store_true", help="apply safe auto-fixes")
    parser.add_argument(
        "--stale-days", type=int, default=DEFAULT_STALE_DAYS,
        help=f"stale threshold in days (default: {DEFAULT_STALE_DAYS})",
    )
    parser.add_argument(
        "--metrics", action="store_true",
        help="compute and include health metrics in the output",
    )
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    only_set: set[str] | None = None
    if args.only:
        only_set = {s.strip() for s in args.only.split(",") if s.strip()}
        invalid = only_set - set(ALL_CHECKS)
        if invalid:
            kbc.print_err(f"Unknown checks: {', '.join(sorted(invalid))}")
            kbc.print_err(f"Available: {', '.join(ALL_CHECKS)}")
            return 2

    report = run_lint(
        root,
        only=only_set,
        quick=args.quick,
        fix=args.fix,
        stale_days=args.stale_days,
        metrics=args.metrics,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "root": report.root,
                    "pages_scanned": report.pages_scanned,
                    "issues": [asdict(i) for i in report.issues],
                    "fixed": report.fixed,
                    "metrics": report.metrics,
                    "exit_code": exit_code(report),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        text = render_text(report)
        if args.output == "report":
            target = kbc.lint_report_path(root)
            target.write_text(text, encoding="utf-8")
            print(f"Report written to {target}")
        else:
            print(text)

    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
