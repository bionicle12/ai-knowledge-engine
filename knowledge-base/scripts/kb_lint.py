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
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

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
)


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


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_frontmatter(
    pages: list[Path], root: Path, *, fix: bool, report: LintReport
) -> None:
    today_iso = _today().isoformat()
    for p in pages:
        try:
            meta, body = kbc.read_frontmatter_file(p)
        except Exception as e:  # noqa: BLE001
            report.issues.append(
                LintIssue(
                    check="frontmatter",
                    severity="error",
                    path=_relative_to_root(p, root),
                    message=f"failed to parse: {e}",
                )
            )
            continue

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
    pages: list[Path], root: Path, *, threshold_days: int, report: LintReport
) -> None:
    today = _today()
    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)
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


def _check_broken_links(pages: list[Path], root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    slugs = kbc.scan_knowledge_slugs(knowledge)
    for p in pages:
        text = p.read_text(encoding="utf-8")
        targets = kbc.extract_wikilinks(text)
        for target in targets:
            target = target.strip()
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


def _check_orphans(pages: list[Path], root: Path, report: LintReport) -> None:
    # Page is orphan if no other page wikilinks to its slug or its rel-path
    knowledge = root / "knowledge"
    incoming: dict[str, set[Path]] = {}
    for p in pages:
        text = p.read_text(encoding="utf-8")
        for target in kbc.extract_wikilinks(text):
            incoming.setdefault(target.strip(), set()).add(p)
    for p in pages:
        slug = p.stem
        rel_no_ext = str(p.relative_to(knowledge).with_suffix(""))
        sources = incoming.get(slug, set()) | incoming.get(rel_no_ext, set())
        sources_excluding_self = sources - {p}
        if sources_excluding_self:
            continue
        # Skip routing-table.md and routing/ pages (they are entry points)
        rel = p.relative_to(knowledge)
        if rel.parts and rel.parts[0] == "routing":
            continue
        if rel.name == "routing-table.md":
            continue
        report.issues.append(
            LintIssue(
                check="orphan",
                severity="warning",
                path=_relative_to_root(p, root),
                message="no inbound wikilinks from any other knowledge page",
            )
        )


def _check_source_hash(pages: list[Path], root: Path, report: LintReport) -> None:
    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)
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


def _check_duplicate_slugs(pages: list[Path], root: Path, report: LintReport) -> None:
    by_slug: dict[str, list[Path]] = {}
    for p in pages:
        by_slug.setdefault(p.stem, []).append(p)
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


def _check_superseded(pages: list[Path], root: Path, report: LintReport) -> None:
    knowledge = root / "knowledge"
    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)
        target = meta.get("supersedes")
        if not target:
            continue
        # target is a slug or relative path
        if "/" in target:
            replaced = knowledge / f"{target}.md"
        else:
            slugs = kbc.scan_knowledge_slugs(knowledge)
            candidates = slugs.get(target, [])
            replaced = candidates[0] if candidates else None
        if replaced is None or not replaced.exists():
            continue  # nothing to verify
        # Replaced should be in _archive/ (unless it's permanent)
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


def _check_expired_temporal(pages: list[Path], root: Path, report: LintReport) -> None:
    today = _today()
    knowledge = root / "knowledge"
    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)
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
    pages: list[Path], root: Path, report: LintReport, threshold: int
) -> None:
    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)
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
# Health metrics (--metrics flag)
# ---------------------------------------------------------------------------


def _compute_metrics(pages: list[Path], root: Path) -> dict:
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
    incoming: dict[str, set[Path]] = {}
    total_wikilinks = 0
    counts_per_subfolder: dict[str, int] = {}

    # Pre-pass: collect inbound wikilinks
    for p in pages:
        text = p.read_text(encoding="utf-8")
        for tgt in kbc.extract_wikilinks(text):
            incoming.setdefault(tgt.strip(), set()).add(p)
        total_wikilinks += len(kbc.extract_wikilinks(text))

    for p in pages:
        meta, _ = kbc.read_frontmatter_file(p)

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

    # Orphan rate
    orphans = 0
    for p in pages:
        slug = p.stem
        rel = p.relative_to(knowledge)
        rel_no_ext = str(rel.with_suffix(""))
        if rel.parts and rel.parts[0] == "routing":
            continue
        if rel.name == "routing-table.md":
            continue
        sources = incoming.get(slug, set()) | incoming.get(rel_no_ext, set())
        if not (sources - {p}):
            orphans += 1
    metrics["orphan_rate"] = round(orphans / len(pages), 3) if pages else 0.0

    # Wikilink density
    metrics["wikilink_density"] = round(total_wikilinks / len(pages), 2)

    # Entity coverage as ratio
    metrics["entity_coverage"] = round(metrics["entity_coverage"] / len(pages), 3)

    # Routing
    routing_pages = [p for p in pages if p.relative_to(knowledge).parts[0:1] == ("routing",)]
    metrics["routing"]["pages"] = len(routing_pages)
    if routing_pages:
        depths = [
            len(p.relative_to(knowledge).parts) for p in routing_pages
        ]
        metrics["routing"]["max_depth"] = max(depths)

    # Insight ratio
    insights = sum(
        1 for p in pages
        if p.relative_to(knowledge).parts[0:1] == ("insights",)
    )
    base = sum(
        1 for p in pages
        if p.relative_to(knowledge).parts[0:1] in (("domain",), ("playbooks",), ("insights",))
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
    pages = _knowledge_pages(root)
    report = LintReport(root=str(root), pages_scanned=len(pages))

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
