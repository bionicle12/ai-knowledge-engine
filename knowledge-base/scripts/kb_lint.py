#!/usr/bin/env python3
"""kb_lint — Level-1 health check for the knowledge base.

Runs deterministic checks on knowledge/**.md without using any LLM.
Level 2 (AI review) is performed by the agent on demand via !audit.

Checks:
  * frontmatter:      required fields (source, extracted_at, tags, lifecycle);
                      also reports `frontmatter-yaml` (the block does not
                      parse — --fix never touches such a page) and
                      `frontmatter-type` (source/supersedes/citations of the
                      wrong type)
  * stale:            kb_common.stale_status — newest of last_verified /
                      extracted_at older than lifecycle.stale_warning_days;
                      never for _archive/, generated pages, permanent
                      (incl. lifecycle.by_folder) or valid_until >= today
  * broken-link:      [[wikilinks]] that resolve to no knowledge page
                      (case-insensitive; #section, .md, knowledge/ prefix,
                      partial paths, embeds and links in code handled)
  * orphan:           pages without inbound wikilinks (skips routing,
                      _archive/ and generated pages)
  * source-hash:      hash mismatch between knowledge page and asset
                      (skips permanent; never reads a source outside the
                      base; hashes cached in .kb-state/)
  * duplicate-slug:   same filename in different subfolders (outside _archive/)
  * empty-category:   custom knowledge/<sub>/ with no .md (the stock folders
                      kb_ingest --init-dirs creates are exempt)
  * superseded:       supersedes: <x> but x not in _archive/
  * domain-overflow:  > 15 .md in a single subfolder (_archive/ exempt)
  * expired-temporal: lifecycle=temporal with valid_until in the past
  * annotation-overflow: > 5 context_annotations on a page
  * citation:            citations[].source_span points to a missing file or
                         past its last line (#Lx-Ly)
  * low-importance:      importance < 3 + temporal + not accessed for 90 days
  * invariants:           required AI-KE:INVARIANT blocks in AGENTS.md
  * agents-bytes:         AGENTS.md larger than configured byte budget
  * instruction-absolutes: always/never/must/forbidden (and Russian
                           всегда/никогда/обязательно/запрещено/нельзя)
                           outside INVARIANT
  * work-ordering:        phrases that inflate reasoning ("thoroughly", …)
  * instruction-duplicates: AGENTS.md restates privacy/language_policy
  * instructions-review:  instructions_review.reviewed_at older than N days
  * assumption-hotspot:   >N ## Assumptions bullets for one knowledge/ area in 30 days
  * profile-review:       profile_review.reviewed_at older than 30 days

A page that breaks a check is reported on that page; it never stops the run.

Exit codes:
  0 — no issues
  1 — only warnings (or info)
  2 — at least one error (a crash of the script itself, or a kb_common.py
      older than this script — a partial upgrade — also exits 2)

Every CLI run without --only writes .kb-state/lint-summary.json; only
--log appends an entry to log.md.

Usage:
  python3 scripts/kb_lint.py
  python3 scripts/kb_lint.py --quick           # error-level checks only
  python3 scripts/kb_lint.py --only frontmatter,broken-link
  python3 scripts/kb_lint.py --output report   # write to lint-report.md
  python3 scripts/kb_lint.py --json
  python3 scripts/kb_lint.py --fix             # add missing frontmatter fields
  python3 scripts/kb_lint.py --metrics         # include health metrics
  python3 scripts/kb_lint.py --log             # also record the run in log.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_UPGRADE_ADVICE = (
    "merge scripts/kb_common.py.new, or take the engine's copy: "
    "kb_upgrade.py --kb-root <this base> --accept kb_common.py; "
    "python3 scripts/kb_doctor.py shows the details"
)

# A broken install is a crash, and a crash exits 2 — never 1 ("warnings only").
try:
    import yaml  # noqa: E402

    import kb_common as kbc  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    if __name__ != "__main__":
        raise
    print(
        f"❌ [lint] cannot import its modules ({type(_exc).__name__}: {_exc}) — "
        f"install the requirements (pip install -r requirements.txt), or {_UPGRADE_ADVICE}",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def _missing_kb_common_names() -> list[str]:
    """kb_common names this script uses that scripts/kb_common.py lacks: a
    partial upgrade (an older, customized kb_common.py was kept)."""
    try:
        own = Path(__file__).read_text(encoding="utf-8")
    except OSError:
        return []
    used = set(re.findall(r"\bkbc\.([A-Za-z_]\w*)", own))
    return sorted(name for name in used if not hasattr(kbc, name))


if _missing := _missing_kb_common_names():
    _PARTIAL_UPGRADE = (
        f"scripts/kb_common.py is older than kb_lint.py (it has no "
        f"{', '.join(_missing)}) — a partial upgrade: {_UPGRADE_ADVICE}"
    )
    if __name__ == "__main__":
        print(f"❌ [lint] {_PARTIAL_UPGRADE}", file=sys.stderr)
        raise SystemExit(2)
    raise ImportError(_PARTIAL_UPGRADE)


REQUIRED_FRONTMATTER_FIELDS = ("source", "extracted_at", "tags", "lifecycle")
VALID_LIFECYCLES = kbc.LIFECYCLES
DEFAULT_DOMAIN_OVERFLOW = 15
DEFAULT_ANNOTATION_OVERFLOW = 5
LOW_IMPORTANCE_BELOW = 3
LOW_IMPORTANCE_IDLE_DAYS = 90

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
    "citation",
    "low-importance",
    "invariants",
    "agents-bytes",
    "instruction-absolutes",
    "work-ordering",
    "instruction-duplicates",
    "instructions-review",
    "assumption-hotspot",
    "profile-review",
    "secret",
)

# The only checks that can report an error. `--quick` runs just these, so it
# really is quicker, not the full run with the warnings filtered out.
ERROR_CHECKS = frozenset(
    {"frontmatter", "broken-link", "source-hash", "duplicate-slug", "invariants", "secret"}
)
# A token or a private key in a page is an error; a `password: …` style
# assignment may be prose about passwords, so it only warns.
SECRET_WARNING_KINDS = frozenset({"password/secret assignment"})

LINT_SUMMARY_FILENAME = "lint-summary.json"
HASH_CACHE_FILENAME = "lint-hash-cache.json"

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
_ABSOLUTE_RE = re.compile(
    r"\b(always|never|must|forbidden"
    r"|всегда|никогда|обязательно|запрещено|запрещается|нельзя)\b",
    re.IGNORECASE,
)
_LINE_SPAN_RE = re.compile(r"L(\d+)(?:-L?(\d+))?")


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
    scope: str = "full"      # "full" | "quick" | "partial" (--only)

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


def _mapping(value) -> dict:
    """A config section as a dict; anything else (a hand-edit typo) → {}."""
    return value if isinstance(value, dict) else {}


def _int_setting(section: dict, key: str, default: int) -> int:
    try:
        return int(section.get(key, default))
    except (TypeError, ValueError):
        return default


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
    rel: str                 # posix path relative to knowledge/
    shown: str               # path relative to the base root, as reported
    meta: dict
    body: str
    links: list[kbc.WikiLink] = field(default_factory=list)  # non-embed only
    fm_error: str | None = None  # frontmatter present but unusable
    secrets: list[str] = field(default_factory=list)  # kbc.find_secrets() hits

    @property
    def rel_no_ext(self) -> str:
        return self.rel[:-3] if self.rel.endswith(".md") else self.rel


@dataclass
class LintContext:
    """What every check needs: paths, config, the report and link indexes."""

    root: Path
    cfg: kbc.KbConfig
    report: LintReport
    today: _dt.date
    stale_days: int
    domain_overflow: int = DEFAULT_DOMAIN_OVERFLOW
    annotation_overflow: int = DEFAULT_ANNOTATION_OVERFLOW
    # casefolded slug → files; casefolded knowledge-relative path (no .md) →
    # file. Built from every knowledge/**.md, readable or not.
    slugs: dict[str, list[Path]] = field(default_factory=dict)
    ids: dict[str, Path] = field(default_factory=dict)
    path_ids: dict[Path, str] = field(default_factory=dict)  # reverse of ids
    pages_by_path: dict[Path, PageData] = field(default_factory=dict)
    hashes: SourceHashCache | None = None
    line_counts: dict[Path, int] = field(default_factory=dict)
    cited_files: dict[str, Path | None] = field(default_factory=dict)

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    def rel(self, p: Path) -> str:
        return _relative_to_root(p, self.root)

    def add(
        self, check: str, severity: str, path: str, message: str, *, fixable: bool = False
    ) -> None:
        self.report.issues.append(
            LintIssue(check=check, severity=severity, path=path, message=message, fixable=fixable)
        )

    def lifecycle(self, page: PageData) -> str:
        """Effective lifecycle: the page's own value, else lifecycle.by_folder."""
        return kbc.effective_lifecycle(
            page.meta, page.rel, self.cfg.lifecycle_by_folder,
            default=self.cfg.lifecycle_default,
        )

    def resolve(self, link: kbc.WikiLink) -> list[Path]:
        """Knowledge files a wikilink points to (case-insensitive)."""
        key = link.page_id.casefold()
        if "/" not in key:
            return self.slugs.get(key, [])
        hit = self.ids.get(key)
        if hit:
            return [hit]
        # Like Obsidian, a partial path matches by its end: [[sub/deep]] →
        # knowledge/work/sub/deep.md.
        tail = "/" + key
        return [
            p for p in self.slugs.get(key.rsplit("/", 1)[1], [])
            if self.path_ids.get(p, "").endswith(tail)
        ]


class SourceHashCache:
    """``compute_source_hash`` memo, persisted in ``.kb-state/``.

    An entry is reused while the source's size and mtime (ns) are unchanged,
    so a 200 MB source cited by 20 pages is hashed once, not 20 times per run.
    Only entries used by the current run are written back.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / kbc.STATE_DIR / HASH_CACHE_FILENAME
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        self.entries: dict = loaded if isinstance(loaded, dict) else {}
        self.used: dict = {}
        self._real_root = root.resolve()

    def _key(self, path: Path) -> str:
        try:
            return path.relative_to(self._real_root).as_posix()
        except ValueError:
            return str(path)

    def get(self, path: Path) -> str:
        key = self._key(path)
        if key in self.used:
            return self.used[key]["hash"]
        st = path.stat()
        sig = [st.st_size, st.st_mtime_ns]
        entry = self.entries.get(key)
        if not (
            isinstance(entry, dict)
            and entry.get("sig") == sig
            and isinstance(entry.get("hash"), str)
        ):
            entry = {"sig": sig, "hash": kbc.compute_source_hash(path)}
        self.used[key] = entry
        return entry["hash"]

    def save(self) -> None:
        if not self.used or self.used == self.entries:
            return
        try:
            kbc.write_json(kbc.state_dir(self.root) / HASH_CACHE_FILENAME, self.used)
        except OSError:
            pass  # a read-only base still lints; it just hashes again next time


def _load_pages(
    root: Path, report: LintReport, *, scan_secrets: bool = False
) -> tuple[list[PageData], list[tuple[Path, str]]]:
    """Read every knowledge page once and cache (meta, body, wikilinks).

    Returns ``(pages, files)``: the parsed pages and ``(path, posix path
    relative to knowledge/)`` of every knowledge/**.md (unreadable ones
    included, so links to them still resolve). A file that cannot be read
    becomes a single ``unreadable`` error and is excluded from the per-page
    checks (they could only misreport on garbage). With `scan_secrets` the
    whole text (frontmatter included) is scanned for credentials here, while
    it is at hand.
    """
    knowledge = root / "knowledge"
    # rglob yields knowledge/<rel>; slicing the string is much cheaper than
    # Path.relative_to on thousands of pages.
    cut = len(str(knowledge)) + 1
    files = [(p, str(p)[cut:].replace(os.sep, "/")) for p in _knowledge_pages(root)]
    out: list[PageData] = []
    for p, rel in files:
        shown = os.path.join("knowledge", *rel.split("/"))
        try:
            text = p.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            report.issues.append(
                LintIssue(
                    check="unreadable",
                    severity="error",
                    path=shown,
                    message=f"failed to read (the page must be UTF-8 text): {e}",
                )
            )
            continue
        meta, body = kbc.parse_frontmatter(text)
        # parse_frontmatter returns {} for broken YAML too; only then is the
        # (second) parse to tell "no frontmatter" from "unusable" worth it.
        fm_error = None if meta else kbc.frontmatter_error(text)
        out.append(
            PageData(
                path=p,
                rel=rel,
                shown=shown,
                meta=meta,
                body=body,
                links=[link for link in kbc.iter_wikilinks(text) if not link.is_embed],
                fm_error=fm_error,
                secrets=kbc.find_secrets(text) if scan_secrets else [],
            )
        )
    return out, files


def _index_files(ctx: LintContext, files: list[tuple[Path, str]]) -> None:
    for p, rel in files:
        page_id = rel[: -len(p.suffix)].casefold()
        ctx.slugs.setdefault(p.stem.casefold(), []).append(p)
        ctx.ids[page_id] = p
        ctx.path_ids[p] = page_id


def _for_each_page(
    check: str,
    pages: list[PageData],
    ctx: LintContext,
    fn: Callable[[PageData, LintContext], None],
) -> None:
    """Run a per-page check; an exception on one page becomes an error on
    that page instead of ending the whole run."""
    for page in pages:
        try:
            fn(page, ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.add(
                check, "error", page.shown,
                f"check failed on this page ({type(exc).__name__}: {exc}) — "
                "fix the frontmatter by hand",
            )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _type_problems(meta: dict) -> list[str]:
    """Fields the checks read, present with a type they cannot use."""
    problems: list[str] = []
    for key in ("source", "source_hash"):
        value = meta.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(f"`{key}` must be a string (got {type(value).__name__})")
    supersedes = meta.get("supersedes")
    if supersedes is not None and not isinstance(supersedes, str) and not (
        isinstance(supersedes, list) and all(isinstance(s, str) for s in supersedes)
    ):
        problems.append(
            "`supersedes` must be a page slug/path or a list of them "
            f"(got {type(supersedes).__name__})"
        )
    citations = meta.get("citations")
    if citations is not None:
        if not isinstance(citations, list):
            problems.append(
                f"`citations` must be a list (got {type(citations).__name__})"
            )
        else:
            for i, item in enumerate(citations):
                if not isinstance(item, dict):
                    problems.append(
                        f"`citations[{i}]` must be a mapping with claim/source_span "
                        f"(got {type(item).__name__})"
                    )
    return problems


def _make_frontmatter_check(fix: bool) -> Callable[[PageData, LintContext], None]:
    def check(page: PageData, ctx: LintContext) -> None:
        path = page.shown
        if page.fm_error:
            # Never "fix" what did not parse: new frontmatter on top of the old
            # block would push the real metadata into the body (Q5).
            ctx.add(
                "frontmatter-yaml", "error", path,
                f"{page.fm_error} — repair it by hand; --fix leaves this page alone",
            )
            return
        meta = page.meta
        for problem in _type_problems(meta):
            ctx.add("frontmatter-type", "error", path, problem)

        missing = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in meta]
        lifecycle_default = ctx.cfg.lifecycle_default
        defaults = {
            "lifecycle": lifecycle_default if lifecycle_default in VALID_LIFECYCLES else "evolving",
            "tags": [],
            "extracted_at": ctx.today.isoformat(),
        }
        if fix and missing:
            applied = [f for f in missing if f in defaults]
            if applied:
                for f in applied:
                    meta[f] = defaults[f]
                missing = [f for f in missing if f not in applied]
                kbc.write_frontmatter_file(page.path, meta, page.body)
                ctx.report.fixed.append(
                    f"frontmatter:{path} ({'+'.join(applied)} defaults applied)"
                )
        if missing:
            ctx.add(
                "frontmatter", "error", path,
                f"missing required fields: {', '.join(missing)}",
                fixable=any(m in defaults for m in missing),
            )
        if "lifecycle" in meta and meta["lifecycle"] not in VALID_LIFECYCLES:
            ctx.add(
                "frontmatter", "error", path,
                f"invalid lifecycle: {meta['lifecycle']!r} (must be one of {VALID_LIFECYCLES})",
            )

    return check


def _check_stale(page: PageData, ctx: LintContext) -> None:
    stale, why = kbc.stale_status(
        page.meta, page.rel,
        today=ctx.today,
        stale_days=ctx.stale_days,
        by_folder=ctx.cfg.lifecycle_by_folder,
        default_lifecycle=ctx.cfg.lifecycle_default,
    )
    if stale:
        ctx.add("stale", "warning", page.shown, why)


def _check_broken_links(page: PageData, ctx: LintContext) -> None:
    for link in page.links:
        if not ctx.resolve(link):
            where = "to a knowledge file" if "/" in link.page_id else ""
            ctx.add(
                "broken-link", "error", page.shown,
                f"[[{link.target}]] does not resolve {where}".rstrip(),
            )


def _orphan_paths(pages: list[PageData]) -> set[Path]:
    """Pages with no inbound wikilink from any *other* page.

    routing/ pages and routing-table.md are entry points; _archive/ pages and
    generated pages (``generated_by:``) are not expected to be linked. Single
    source of truth for both the orphan check and the metrics.
    """
    incoming: dict[str, set[Path]] = {}
    for page in pages:
        for link in page.links:
            incoming.setdefault(link.page_id.casefold(), set()).add(page.path)
    orphans: set[Path] = set()
    for page in pages:
        if page.rel.split("/")[0] == "routing" or page.path.name == "routing-table.md":
            continue
        if kbc.is_archived(page.rel) or kbc.is_generated(page.meta):
            continue
        # The slug, the full path and every partial path ending (`sub/deep`
        # for work/sub/deep) — the forms ctx.resolve accepts.
        parts = page.rel_no_ext.casefold().split("/")
        sources: set[Path] = set()
        for i in range(len(parts)):
            sources |= incoming.get("/".join(parts[i:]), set())
        if not (sources - {page.path}):
            orphans.add(page.path)
    return orphans


def _check_orphans(pages: list[PageData], ctx: LintContext) -> None:
    for p in sorted(_orphan_paths(pages)):
        ctx.add("orphan", "warning", ctx.pages_by_path[p].shown,
                "no inbound wikilinks from any other knowledge page")


def _check_source_hash(page: PageData, ctx: LintContext) -> None:
    meta = page.meta
    recorded, source = meta.get("source_hash"), meta.get("source")
    if not (isinstance(recorded, str) and recorded and isinstance(source, str) and source):
        return  # nothing to compare (wrong types are `frontmatter-type` errors)
    if ctx.lifecycle(page) == "permanent":
        return
    path = page.shown
    # Symlink-safe: a page (say, from a merged bundle) must not make lint hash,
    # print or cache a file outside the base (`source: ../../.ssh/id_rsa`).
    source_path = kbc.resolve_under(ctx.root, source)
    if source_path is None:
        ctx.add(
            "source-hash", "warning", path,
            f"source is outside this base, not checked: {source}",
        )
        return
    if not source_path.is_file():
        ctx.add("source-hash", "warning", path, f"source file not found: {source}")
        return
    actual = ctx.hashes.get(source_path) if ctx.hashes else kbc.compute_source_hash(source_path)
    if actual != recorded:
        ctx.add(
            "source-hash", "error", path,
            f"source_hash mismatch: expected {recorded}, actual {actual}. "
            "Source has been modified — knowledge may be stale.",
        )


def _check_duplicate_slugs(pages: list[PageData], ctx: LintContext) -> None:
    # An archived copy next to the live page is history, not a clash (Q13).
    by_slug: dict[str, list[Path]] = {}
    for page in pages:
        if not kbc.is_archived(page.rel):
            by_slug.setdefault(page.path.stem.casefold(), []).append(page.path)
    for owners in by_slug.values():
        if len(owners) > 1:
            ctx.add(
                "duplicate-slug", "error",
                ", ".join(ctx.pages_by_path[o].shown for o in owners),
                f"slug '{owners[0].stem}' is used by {len(owners)} files",
            )


def _check_empty_categories(ctx: LintContext) -> None:
    knowledge = ctx.knowledge
    if not knowledge.is_dir():
        return
    for sub in sorted(knowledge.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        # The stock folders `kb_ingest.py --init-dirs` creates are compatibility
        # shelves (02_INIT): empty is their normal state.
        if sub.name in kbc.KNOWLEDGE_DIRS:
            continue
        if not any(sub.rglob("*.md")):
            ctx.add(
                "empty-category", "warning", ctx.rel(sub) + "/",
                "category contains no .md files",
            )


def _check_superseded(page: PageData, ctx: LintContext) -> None:
    targets = page.meta.get("supersedes")
    if isinstance(targets, str):
        targets = [targets]
    if not isinstance(targets, list):
        return
    for target in targets:
        if not isinstance(target, str) or not target.strip():
            continue
        text = target if "[[" in target else f"[[{target.strip()}]]"
        for link in kbc.iter_wikilinks(text):
            for replaced in ctx.resolve(link):
                if replaced == page.path:
                    continue
                replaced_page = ctx.pages_by_path.get(replaced)
                if replaced_page is None or kbc.is_archived(replaced_page.rel):
                    continue
                if ctx.lifecycle(replaced_page) == "permanent":
                    continue  # permanent pages are never archived automatically
                ctx.add(
                    "superseded", "warning", replaced_page.shown,
                    f"superseded by {page.shown} but not in _archive/",
                )


def _check_domain_overflow(ctx: LintContext) -> None:
    knowledge = ctx.knowledge
    if not knowledge.is_dir():
        return
    threshold = ctx.domain_overflow
    for sub in knowledge.iterdir():
        if not sub.is_dir() or sub.name.startswith(".") or kbc.is_archived(sub.name):
            continue
        # Archived pages anywhere below (<sub>/_archive/, <sub>/x/_archive/)
        # are history, not part of the folder's working set.
        count = sum(
            1 for p in sub.rglob("*.md") if not kbc.is_archived(p.relative_to(sub))
        )
        if count > threshold:
            ctx.add(
                "domain-overflow", "warning", ctx.rel(sub) + "/",
                f"{count} .md files (threshold: {threshold}). "
                "Consider creating a routing page.",
            )


def _check_expired_temporal(page: PageData, ctx: LintContext) -> None:
    if kbc.is_archived(page.rel) or ctx.lifecycle(page) != "temporal":
        return
    valid_until = _parse_date(page.meta.get("valid_until"))
    if valid_until is None or valid_until >= ctx.today:
        return
    ctx.add(
        "expired-temporal", "warning", page.shown,
        f"valid_until={valid_until.isoformat()} is in the past; consider archiving",
    )


def _check_annotation_overflow(page: PageData, ctx: LintContext) -> None:
    ann = page.meta.get("context_annotations") or []
    if isinstance(ann, list) and len(ann) > ctx.annotation_overflow:
        ctx.add(
            "annotation-overflow", "info", page.shown,
            f"{len(ann)} annotations (threshold: {ctx.annotation_overflow}). "
            "Consider consolidating into an insight.",
        )


def _line_count(ctx: LintContext, path: Path) -> int:
    if path not in ctx.line_counts:
        count = 0
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                count += chunk.count(b"\n")
        ctx.line_counts[path] = count
    return ctx.line_counts[path]


def _check_citations(page: PageData, ctx: LintContext) -> None:
    """``citations[].source_span`` must name an existing file inside the base;
    a ``#Lx-Ly`` span must not run past the file's last line."""
    citations = page.meta.get("citations")
    if not isinstance(citations, list):
        return
    path = page.shown
    for i, item in enumerate(citations):
        if not isinstance(item, dict):
            continue  # reported as frontmatter-type
        span = item.get("source_span")
        if not isinstance(span, str) or not span.strip():
            ctx.add("citation", "warning", path, f"citations[{i}] has no source_span")
            continue
        file_part, _, fragment = span.strip().partition("#")
        if file_part not in ctx.cited_files:
            ctx.cited_files[file_part] = (
                kbc.resolve_under(ctx.root, file_part) if file_part else None
            )
        target = ctx.cited_files[file_part]
        if target is None or not target.is_file():
            ctx.add(
                "citation", "warning", path,
                f"citations[{i}]: {file_part or span} is not a file in this base",
            )
            continue
        lines = _LINE_SPAN_RE.fullmatch(fragment)
        if lines:
            last = int(lines.group(2) or lines.group(1))
            total = _line_count(ctx, target)
            if last > total:
                ctx.add(
                    "citation", "warning", path,
                    f"citations[{i}]: {span} ends past the last line "
                    f"({file_part} has {total} lines)",
                )


def _check_secrets(page: PageData, ctx: LintContext) -> None:
    """Credential-looking text in a knowledge page (kinds and line numbers,
    never the value). repomix's security check silently leaves such a page
    out of its pack, and knowledge/ is committed."""
    errors = [hit for hit in page.secrets if hit.split(" (")[0] not in SECRET_WARNING_KINDS]
    warnings = [hit for hit in page.secrets if hit not in errors]
    advice = (
        "remove the value (keep a placeholder such as <redacted>), or move the page "
        "to review/needs-redaction/ for the owner; until then repomix's security "
        "check keeps the page out of the index"
    )
    if errors:
        ctx.add(
            "secret", "error", page.shown,
            f"looks like a credential: {'; '.join(errors)} — {advice}",
        )
    if warnings:
        ctx.add(
            "secret", "warning", page.shown,
            f"may hold a password: {'; '.join(warnings)} — if it is a real value, {advice}",
        )


def _check_low_importance(page: PageData, ctx: LintContext) -> None:
    meta = page.meta
    importance = meta.get("importance")
    if (
        not isinstance(importance, int)
        or isinstance(importance, bool)
        or importance >= LOW_IMPORTANCE_BELOW
    ):
        return
    if kbc.is_archived(page.rel) or kbc.is_generated(meta) or ctx.lifecycle(page) != "temporal":
        return
    last = _parse_date(meta.get("last_accessed"))
    field_name = "last_accessed"
    if last is None:
        dated = [
            (d, name)
            for name in ("last_verified", "extracted_at")
            if (d := _parse_date(meta.get(name))) is not None
        ]
        if not dated:
            return
        last, field_name = max(dated)
    idle = (ctx.today - last).days
    if idle > LOW_IMPORTANCE_IDLE_DAYS:
        ctx.add(
            "low-importance", "info", page.shown,
            f"importance {importance}, temporal, {field_name} {last.isoformat()} "
            f"({idle} days ago) — consider moving it to knowledge/_archive/",
        )


# ---------------------------------------------------------------------------
# Instruction-budget checks (AGENTS.md + kb.config.yml)
# ---------------------------------------------------------------------------


def _instructions_lint_settings(cfg: kbc.KbConfig) -> dict:
    raw = _mapping(cfg.raw.get("instructions_lint")) if cfg.raw else {}
    phrases = raw.get("work_ordering_phrases")
    if isinstance(phrases, list):
        phrase_list = [str(p) for p in phrases]
    else:
        phrase_list = list(DEFAULT_WORK_ORDERING_PHRASES)
    return {
        "agents_max_bytes": _int_setting(raw, "agents_max_bytes", DEFAULT_AGENTS_MAX_BYTES),
        "absolute_max_outside_invariants": _int_setting(
            raw, "absolute_max_outside_invariants", DEFAULT_ABSOLUTE_MAX_OUTSIDE_INVARIANTS
        ),
        "review_stale_days": _int_setting(raw, "review_stale_days", DEFAULT_REVIEW_STALE_DAYS),
        "work_ordering_phrases": phrase_list,
    }


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
                f"{len(hits)} always/never/must/forbidden (or Russian "
                f"всегда/никогда/…) outside INVARIANT blocks "
                f"(threshold: {max_outside})."
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


def _check_instruction_duplicates(
    root: Path, report: LintReport, *, cfg: kbc.KbConfig
) -> None:
    loaded = _read_agents_md(root)
    if loaded is None:
        return
    path, text = loaded
    privacy = _mapping(cfg.raw.get("privacy")) if cfg.raw else {}
    language = _mapping(cfg.raw.get("language_policy")) if cfg.raw else {}
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
    root: Path, report: LintReport, *, stale_days: int, cfg: kbc.KbConfig
) -> None:
    if _read_agents_md(root) is None:
        return
    review = _mapping(cfg.raw.get("instructions_review")) if cfg.raw else {}
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


def _check_profile_review(root: Path, report: LintReport, *, cfg: kbc.KbConfig) -> None:
    raw = cfg.raw or {}
    block = _mapping(raw.get("profile_review"))
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
        total_wikilinks += len(page.links)

    for page in pages:
        p, meta = page.path, page.meta

        # Subfolder
        rel = p.relative_to(knowledge)
        sub = rel.parts[0] if len(rel.parts) > 1 else "_root"
        counts_per_subfolder[sub] = counts_per_subfolder.get(sub, 0) + 1

        # Lifecycle
        lc = meta.get("lifecycle")
        if isinstance(lc, str) and lc in VALID_LIFECYCLES:
            metrics["by_lifecycle"][lc] += 1
        else:
            metrics["by_lifecycle"]["unset"] += 1

        # Importance
        imp = meta.get("importance")
        if isinstance(imp, int) and not isinstance(imp, bool) and 1 <= imp <= 10:
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
    orphans = len(_orphan_paths(pages))
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


def _load_lint_config(root: Path, report: LintReport) -> kbc.KbConfig:
    """kb.config.yml, or code defaults plus one `config` error when it does
    not parse — a broken config must not hide the page checks."""
    try:
        return kbc.load_config(root)
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        report.issues.append(
            LintIssue(
                check="config",
                severity="error",
                path=kbc.DEFAULT_CONFIG_FILENAME,
                message=f"cannot read it, using defaults: {str(e).splitlines()[0]}",
            )
        )
        return kbc.KbConfig(raw={}, root=root)


def _guarded(check: str, ctx: LintContext, fn: Callable[[], None]) -> None:
    """Run a whole-base check; a crash becomes one error, not a dead run."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        ctx.add(check, "error", "-", f"check crashed ({type(exc).__name__}: {exc})")


def run_lint(
    root: Path,
    *,
    only: set[str] | None = None,
    quick: bool = False,
    fix: bool = False,
    stale_days: int | None = None,
    domain_overflow: int = DEFAULT_DOMAIN_OVERFLOW,
    annotation_overflow: int = DEFAULT_ANNOTATION_OVERFLOW,
    metrics: bool = False,
) -> LintReport:
    """Lint the base at `root`.

    `stale_days` defaults to ``lifecycle.stale_warning_days`` (30). `quick`
    runs only the checks that can report an error (``ERROR_CHECKS``) and
    keeps only errors.
    """
    report = LintReport(
        root=str(root), scope="partial" if only else ("quick" if quick else "full")
    )
    cfg = _load_lint_config(root, report)

    def enabled(name: str) -> bool:
        if only and name not in only:
            return False
        return not quick or name in ERROR_CHECKS

    pages, files = _load_pages(
        root, report, scan_secrets=enabled("secret") and cfg.privacy_secret_scan
    )
    report.pages_scanned = len(files)
    ctx = LintContext(
        root=root,
        cfg=cfg,
        report=report,
        today=_today(),
        stale_days=cfg.lifecycle_stale_warning_days if stale_days is None else stale_days,
        domain_overflow=domain_overflow,
        annotation_overflow=annotation_overflow,
        pages_by_path={page.path: page for page in pages},
    )
    _index_files(ctx, files)

    per_page: tuple[tuple[str, Callable[[PageData, LintContext], None]], ...] = (
        ("frontmatter", _make_frontmatter_check(fix)),
        ("stale", _check_stale),
        ("broken-link", _check_broken_links),
        ("source-hash", _check_source_hash),
        ("superseded", _check_superseded),
        ("expired-temporal", _check_expired_temporal),
        ("annotation-overflow", _check_annotation_overflow),
        ("citation", _check_citations),
        ("low-importance", _check_low_importance),
        ("secret", _check_secrets),
    )
    if enabled("source-hash"):
        ctx.hashes = SourceHashCache(root)
    for name, fn in per_page:
        if enabled(name):
            _for_each_page(name, pages, ctx, fn)
    if ctx.hashes is not None:
        ctx.hashes.save()

    settings = _instructions_lint_settings(cfg)
    whole_base: tuple[tuple[str, Callable[[], None]], ...] = (
        ("orphan", lambda: _check_orphans(pages, ctx)),
        ("duplicate-slug", lambda: _check_duplicate_slugs(pages, ctx)),
        ("empty-category", lambda: _check_empty_categories(ctx)),
        ("domain-overflow", lambda: _check_domain_overflow(ctx)),
        ("invariants", lambda: _check_invariants(root, report)),
        ("agents-bytes", lambda: _check_agents_bytes(
            root, report, max_bytes=settings["agents_max_bytes"])),
        ("instruction-absolutes", lambda: _check_instruction_absolutes(
            root, report, max_outside=settings["absolute_max_outside_invariants"])),
        ("work-ordering", lambda: _check_work_ordering(
            root, report, phrases=settings["work_ordering_phrases"])),
        ("instruction-duplicates", lambda: _check_instruction_duplicates(
            root, report, cfg=cfg)),
        ("instructions-review", lambda: _check_instructions_review(
            root, report, stale_days=settings["review_stale_days"], cfg=cfg)),
        ("assumption-hotspot", lambda: _check_assumption_hotspot(root, report)),
        ("profile-review", lambda: _check_profile_review(root, report, cfg=cfg)),
    )
    for name, fn in whole_base:
        if enabled(name):
            _guarded(name, ctx, fn)

    if metrics:
        report.metrics = _compute_metrics(pages, root)

    if quick:
        report.issues = [i for i in report.issues if i.severity == "error"]

    return report


def write_summary(root: Path, report: LintReport) -> Path | None:
    """Write ``.kb-state/lint-summary.json`` (read by kb_status.py).

    ``{"errors", "warnings", "infos", "at", "scope", "full_at"}``. A --quick
    run measures errors only, so it keeps the warning/info counts of the
    last full run (``full_at`` says when that was). A partial (--only) run
    measures neither and writes nothing.
    """
    if report.scope == "partial":
        return None
    path = kbc.state_dir(root) / LINT_SUMMARY_FILENAME
    now = kbc.now_iso()
    summary = {
        "errors": report.errors,
        "warnings": report.warnings,
        "infos": report.infos,
        "at": now,
        "scope": report.scope,
        "full_at": now,
    }
    if report.scope == "quick":
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        previous = previous if isinstance(previous, dict) else {}
        for key in ("warnings", "infos"):
            value = previous.get(key)
            summary[key] = value if isinstance(value, int) and not isinstance(value, bool) else 0
        summary["full_at"] = previous.get("full_at") if isinstance(previous.get("full_at"), str) else None
    kbc.write_json(path, summary)
    return path


def log_run(root: Path, report: LintReport, *, report_file: Path | None = None) -> None:
    """Append a `lint` entry to log.md (only on --log; see 10_LOG.md)."""
    details = [
        f"Mode: {report.scope}",
        f"Checked: {report.pages_scanned} pages",
        f"Errors: {report.errors}",
        f"Warnings: {report.warnings}",
        f"Info: {report.infos}",
        f"Auto-fixed: {len(report.fixed)}",
    ]
    if report_file is not None:
        details.append(f"Report: {_relative_to_root(report_file, root)}")
    kbc.append_log(operation="lint", title="Health-check", details=details, root=root)


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
    if report.scope == "quick":
        lines.append("- Mode: quick (error-level checks only)")
    elif report.scope == "partial":
        lines.append("- Mode: partial (--only)")
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
    parser.add_argument(
        "--quick", action="store_true",
        help="run only the checks that can report an error; print errors only",
    )
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
    parser.add_argument(
        "--fix", action="store_true",
        help="add missing lifecycle/tags/extracted_at with defaults (nothing else)",
    )
    parser.add_argument(
        "--stale-days", type=int, default=None,
        help="stale threshold in days (default: lifecycle.stale_warning_days, 30)",
    )
    parser.add_argument(
        "--metrics", action="store_true",
        help="compute and include health metrics in the output",
    )
    parser.add_argument(
        "--log", action="store_true",
        help="append a `lint` entry to log.md (off by default)",
    )
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    if not kbc.kb_config_path(root).is_file():
        # Like every other pipeline script: no phantom .kb-state/ in a folder
        # that is not a base.
        kbc.print_err(
            f"❌ [lint] {root} is not a knowledge base (no {kbc.DEFAULT_CONFIG_FILENAME}); "
            "run it from the base root or pass --root"
        )
        return 2
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
    try:
        write_summary(root, report)
    except OSError as e:
        kbc.print_err(f"⚠️  [lint] could not write {kbc.STATE_DIR}/{LINT_SUMMARY_FILENAME}: {e}")

    report_file: Path | None = None
    if args.json:
        print(
            json.dumps(
                {
                    "root": report.root,
                    "scope": report.scope,
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
            report_file = kbc.lint_report_path(root)
            kbc.atomic_write_text(report_file, text)
            print(f"Report written to {report_file}")
        else:
            print(text)

    if args.log:
        log_run(root, report, report_file=report_file)

    return exit_code(report)


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001 — a crash must not read as "warnings only" (1)
        traceback.print_exc()
        code = 2
    raise SystemExit(code)
