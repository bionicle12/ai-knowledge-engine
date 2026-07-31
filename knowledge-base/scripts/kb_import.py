#!/usr/bin/env python3
"""kb_import — merge a bundle produced by ``kb_export.py`` into this base.

The rule is simple: **nothing is ever overwritten silently.** The script does
the mechanical part of a merge — dedup, provenance tracking, additive copies —
and hands every genuinely ambiguous case to the AI agent through
``review/needs-merge/``, which the agent processes with ``!merge``
(see ``16_MERGE.md``).

Per incoming knowledge page, one of:

    new            no local counterpart          → copied in, provenance stamped
    identical      same content fingerprint      → skipped
    enriched       identical, richer metadata    → metadata merged (tags, counters)
    fast-forward   local untouched since the last
                   import of this same page      → updated (backup kept)
    duplicate      same content, different path  → skipped, reported
    conflict       both sides changed            → review/needs-merge/ + diff

Everything else merges additively: `assets-index/` block by block,
`interactions/` and provenance metadata file by file, the source `log.md` into
`log-archive/`.

Usage:
    python3 scripts/kb_import.py                      # every bundle in sync/inbox/
    python3 scripts/kb_import.py path/to/bundle.zip
    python3 scripts/kb_import.py --dry-run            # classify, change nothing
    python3 scripts/kb_import.py --strategy prefer-incoming
    python3 scripts/kb_import.py --keep-bundle

Exit codes:
    0 — merged cleanly, nothing left to decide
    1 — merged, but conflicts are waiting in review/needs-merge/ (run !merge)
    2 — error (no bundle, unreadable archive, unsupported format)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    raise

SUPPORTED_BUNDLE_FORMATS = (1,)
MANIFEST_NAME = "manifest.yml"
MERGE_QUEUE = "needs-merge"
INCOMING_DIRNAME = "_incoming"

STRATEGIES = ("safe", "prefer-incoming", "prefer-local")

# Similarity above which two differently-named pages are flagged as covering
# the same ground (a merge candidate for the agent, never an automatic action).
DEFAULT_SIMILARITY = 0.85
# Upper bound on pairwise comparisons per incoming page — keeps import fast on
# large bases; exceeding it only costs near-duplicate detection, never data.
MAX_SIMILARITY_CANDIDATES = 400

MAX_DIFF_LINES = 200


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    """What the merge decided for a single incoming knowledge page."""

    arcname: str
    action: str
    reason: str = ""
    near_duplicate_of: str | None = None
    conflict_package: str | None = None


@dataclass
class ImportResult:
    bundle: str
    label: str = ""
    source_name: str = ""
    exported_at: str = ""
    decisions: list[Decision] = field(default_factory=list)
    other: dict[str, list[str]] = field(default_factory=dict)
    new_entities: list[str] = field(default_factory=list)
    backup_dir: str | None = None
    report_path: str | None = None
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)

    def by_action(self, action: str) -> list[Decision]:
        return [d for d in self.decisions if d.action == action]

    @property
    def conflicts(self) -> list[Decision]:
        return self.by_action("conflict")

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.decisions:
            out[d.action] = out.get(d.action, 0) + 1
        return out


@dataclass
class LocalIndex:
    """Content-addressed view of the local knowledge/ tree."""

    by_relpath: dict[str, Path] = field(default_factory=dict)
    by_slug: dict[str, list[str]] = field(default_factory=dict)
    by_fingerprint: dict[str, list[str]] = field(default_factory=dict)
    fingerprint_of: dict[str, str] = field(default_factory=dict)
    meta_of: dict[str, dict[str, Any]] = field(default_factory=dict)
    body_of: dict[str, str] = field(default_factory=dict)


def build_local_index(root: Path) -> LocalIndex:
    idx = LocalIndex()
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return idx
    for path in sorted(knowledge.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = kbc.parse_frontmatter(text)
        fp = kbc.content_fingerprint(text)
        idx.by_relpath[rel] = path
        idx.by_slug.setdefault(path.stem, []).append(rel)
        idx.by_fingerprint.setdefault(fp, []).append(rel)
        idx.fingerprint_of[rel] = fp
        idx.meta_of[rel] = meta
        idx.body_of[rel] = body
    return idx


# ---------------------------------------------------------------------------
# Bundle reading
# ---------------------------------------------------------------------------


def _is_safe_member(name: str) -> bool:
    """Reject absolute paths, drive letters and ``..`` traversal (zip-slip)."""
    if not name or name.startswith(("/", "\\")):
        return False
    if ":" in name.split("/")[0]:
        return False
    return ".." not in Path(name.replace("\\", "/")).parts


def read_manifest(bundle: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle) as zf:
        if MANIFEST_NAME not in zf.namelist():
            raise ValueError(f"{bundle.name}: no {MANIFEST_NAME} — not a kb bundle")
        data = yaml.safe_load(zf.read(MANIFEST_NAME).decode("utf-8")) or {}
    fmt = data.get("bundle_format")
    if fmt not in SUPPORTED_BUNDLE_FORMATS:
        raise ValueError(
            f"{bundle.name}: bundle_format {fmt!r} is not supported "
            f"(this script reads {SUPPORTED_BUNDLE_FORMATS})"
        )
    return data


def extract_bundle(bundle: Path, dest: Path) -> list[str]:
    """Extract to `dest`, skipping unsafe member paths. Returns skipped names."""
    skipped: list[str] = []
    with zipfile.ZipFile(bundle) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            if not _is_safe_member(member.filename):
                skipped.append(member.filename)
                continue
            target = dest / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return skipped


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------


def _stamp_provenance(meta: dict[str, Any], *, label: str, bundle_name: str,
                      fingerprint: str) -> dict[str, Any]:
    """Record where an imported page came from, so later imports can fast-forward."""
    meta = dict(meta)
    meta["merged_from"] = label
    meta["merge_bundle"] = bundle_name
    meta["imported_at"] = kbc.now_iso()
    meta["merge_source_fingerprint"] = fingerprint
    return meta


def _merge_metadata(local: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Non-destructive frontmatter enrichment. Returns (merged, changed_keys)."""
    merged = dict(local)
    changed: list[str] = []

    local_tags = local.get("tags") or []
    incoming_tags = incoming.get("tags") or []
    if isinstance(local_tags, list) and isinstance(incoming_tags, list):
        union = list(local_tags) + [t for t in incoming_tags if t not in local_tags]
        if union != local_tags:
            merged["tags"] = union
            changed.append("tags")

    # Counters: keep the larger, they measure usage on either machine.
    for key in ("access_count",):
        try:
            if int(incoming.get(key, 0) or 0) > int(local.get(key, 0) or 0):
                merged[key] = incoming[key]
                changed.append(key)
        except (TypeError, ValueError):
            pass

    # Dates: keep the most recent verification/access.
    for key in ("last_verified", "last_accessed"):
        inc, loc = incoming.get(key), local.get(key)
        if inc and (not loc or str(inc) > str(loc)):
            merged[key] = inc
            changed.append(key)

    # Fill in genuinely missing fields, never replace existing ones.
    for key in ("importance", "lifecycle", "source", "source_hash", "valid_from"):
        if key not in merged or merged.get(key) in (None, ""):
            if incoming.get(key) not in (None, ""):
                merged[key] = incoming[key]
                changed.append(key)

    return merged, changed


def _similar_local_page(
    incoming_body: str, section: str, idx: LocalIndex, threshold: float
) -> tuple[str | None, float]:
    """Best same-section local page covering the same ground, if any."""
    candidates = [
        rel for rel in idx.by_relpath
        if rel.split("/")[1:2] == [section] if section
    ] or list(idx.by_relpath)
    if len(candidates) > MAX_SIMILARITY_CANDIDATES:
        return None, 0.0
    best_rel, best_ratio = None, 0.0
    incoming_norm = " ".join(incoming_body.split())
    if len(incoming_norm) < 80:  # too short to judge similarity meaningfully
        return None, 0.0
    for rel in candidates:
        local_norm = " ".join(idx.body_of.get(rel, "").split())
        if not local_norm:
            continue
        matcher = difflib.SequenceMatcher(None, incoming_norm, local_norm)
        if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_rel, best_ratio = rel, ratio
    return (best_rel, best_ratio) if best_ratio >= threshold else (None, 0.0)


def _unified_diff(local_text: str, incoming_text: str, rel: str) -> str:
    diff = list(
        difflib.unified_diff(
            local_text.splitlines(),
            incoming_text.splitlines(),
            fromfile=f"local/{rel}",
            tofile=f"incoming/{rel}",
            lineterm="",
            n=3,
        )
    )
    if len(diff) > MAX_DIFF_LINES:
        diff = diff[:MAX_DIFF_LINES] + [
            f"… diff truncated at {MAX_DIFF_LINES} lines "
            "(open both files for the full picture)"
        ]
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# Conflict packages
# ---------------------------------------------------------------------------


def _write_conflict_package(
    *,
    root: Path,
    rel: str,
    local_path: Path,
    incoming_file: Path,
    label: str,
    bundle_name: str,
    idx: LocalIndex,
) -> str:
    """Stage the incoming version + a diff for the agent. Local file untouched."""
    queue = root / "review" / MERGE_QUEUE
    staged = queue / INCOMING_DIRNAME / rel
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(incoming_file, staged)

    local_text = local_path.read_text(encoding="utf-8", errors="replace")
    incoming_text = incoming_file.read_text(encoding="utf-8", errors="replace")
    local_meta = idx.meta_of.get(rel, {})
    incoming_meta, _ = kbc.parse_frontmatter(incoming_text)

    def _describe(meta: dict[str, Any]) -> str:
        bits = []
        for key in ("last_verified", "importance", "lifecycle", "confidence"):
            if meta.get(key) not in (None, ""):
                bits.append(f"{key}: {meta[key]}")
        return ", ".join(bits) or "no metadata"

    slug = Path(rel).stem
    package = queue / f"{slug}__from-{kbc.slugify(label)}.md"
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text(
        "\n".join(
            [
                f"# Merge conflict: {rel}",
                "",
                "Both bases changed this page. Nothing was overwritten — decide and merge.",
                "",
                "## Sides",
                "",
                f"- **Local** — `{rel}` ({_describe(local_meta)})",
                f"- **Incoming** — `review/{MERGE_QUEUE}/{INCOMING_DIRNAME}/{rel}` "
                f"({_describe(incoming_meta)})",
                f"- Bundle: `{bundle_name}` from base **{label}**",
                "",
                "## Diff (local → incoming)",
                "",
                "```diff",
                _unified_diff(local_text, incoming_text, rel),
                "```",
                "",
                "## What to do (`!merge`)",
                "",
                "1. Read both versions in full.",
                "2. Produce one merged page at the **local** path: keep every fact that is",
                "   true in either version; prefer the more specific formulation.",
                "3. If the two sides genuinely contradict, keep the better-sourced claim and",
                "   record the other in `knowledge/open-questions/` with both sources.",
                "4. Refresh `last_verified`; keep the higher `importance`; union the `tags`.",
                "5. Set `merge_source_fingerprint` to the incoming page's fingerprint so the",
                "   next import from this base can fast-forward.",
                f"6. Delete this package and `{INCOMING_DIRNAME}/{rel}` when done.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return package.relative_to(root).as_posix()


def _write_merge_candidate(
    *,
    root: Path,
    incoming_rel: str,
    local_rel: str,
    ratio: float,
    label: str,
    bundle_name: str,
) -> str:
    """Two differently-named pages cover the same ground — let the agent decide."""
    queue = root / "review" / MERGE_QUEUE
    queue.mkdir(parents=True, exist_ok=True)
    slug = Path(incoming_rel).stem
    package = queue / f"{slug}__near-duplicate.md"
    package.write_text(
        "\n".join(
            [
                f"# Merge candidate: {incoming_rel}",
                "",
                f"Imported from **{label}** (`{bundle_name}`). It was added to the base,",
                f"but it overlaps ~{ratio:.0%} with an existing page.",
                "",
                "## Pages",
                "",
                f"- Imported: `{incoming_rel}`",
                f"- Existing: `{local_rel}`",
                "",
                "## What to do (`!merge`)",
                "",
                "1. Read both. If they are the same knowledge under different names,",
                "   consolidate into the better-named page and archive the other into",
                "   `knowledge/_archive/` with a `supersedes:` note.",
                "2. If they are genuinely different, add `[[wikilinks]]` between them and",
                "   delete this package.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return package.relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# Knowledge merge
# ---------------------------------------------------------------------------


def merge_knowledge(
    *,
    root: Path,
    staging: Path,
    idx: LocalIndex,
    label: str,
    bundle_name: str,
    strategy: str,
    similarity: float,
    backup: "Backup",
    dry_run: bool,
) -> list[Decision]:
    decisions: list[Decision] = []
    incoming_root = staging / "knowledge"
    if not incoming_root.is_dir():
        return decisions

    for incoming_file in sorted(incoming_root.rglob("*.md")):
        if not incoming_file.is_file():
            continue
        rel = incoming_file.relative_to(staging).as_posix()
        text = incoming_file.read_text(encoding="utf-8", errors="replace")
        meta, body = kbc.parse_frontmatter(text)
        fp = kbc.content_fingerprint(text)
        target = root / rel
        section = rel.split("/")[1] if rel.count("/") >= 2 else ""

        local_rel = rel if rel in idx.by_relpath else None
        # Same slug in a different folder counts as the same page.
        if local_rel is None:
            same_slug = [
                r for r in idx.by_slug.get(Path(rel).stem, [])
                if idx.fingerprint_of.get(r) != fp
            ]
            if same_slug:
                local_rel = same_slug[0]

        # --- same body already at this path --------------------------------
        same_content = idx.by_fingerprint.get(fp, [])
        if rel in same_content:
            local_meta = idx.meta_of.get(rel, {})
            merged_meta, changed = _merge_metadata(local_meta, meta)
            if kbc.stable_metadata(merged_meta) == kbc.stable_metadata(local_meta):
                changed = []
            if changed:
                if not dry_run:
                    backup.save(root / rel)
                    local_body = idx.body_of.get(rel, "")
                    kbc.write_frontmatter_file(root / rel, merged_meta, local_body)
                decisions.append(
                    Decision(rel, "enriched", f"metadata merged: {', '.join(sorted(set(changed)))}")
                )
            else:
                decisions.append(Decision(rel, "identical", "same content, same path"))
            continue
        if same_content:
            decisions.append(
                Decision(rel, "duplicate", f"same content already at {same_content[0]}")
            )
            continue

        # --- no local counterpart → straight add ---------------------------
        if local_rel is None:
            similar_rel, ratio = _similar_local_page(body, section, idx, similarity)
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                kbc.write_frontmatter_file(
                    target,
                    _stamp_provenance(meta, label=label, bundle_name=bundle_name, fingerprint=fp),
                    body,
                )
            package = None
            if similar_rel:
                if not dry_run:
                    package = _write_merge_candidate(
                        root=root, incoming_rel=rel, local_rel=similar_rel,
                        ratio=ratio, label=label, bundle_name=bundle_name,
                    )
                decisions.append(
                    Decision(rel, "new", f"added; overlaps {ratio:.0%} with {similar_rel}",
                             near_duplicate_of=similar_rel, conflict_package=package)
                )
            else:
                decisions.append(Decision(rel, "new", "no local counterpart"))
            continue

        # --- both sides have this page, content differs --------------------
        local_path = root / local_rel
        local_meta = idx.meta_of.get(local_rel, {})
        recorded = local_meta.get("merge_source_fingerprint")
        local_fp = idx.fingerprint_of.get(local_rel)

        if recorded and recorded == local_fp:
            # Local body has not been edited since it was imported → safe update.
            # Incoming metadata is authoritative, but local-only fields survive.
            if not dry_run:
                backup.save(local_path)
                forwarded, _ = _merge_metadata(meta, local_meta)
                kbc.write_frontmatter_file(
                    local_path,
                    _stamp_provenance(
                        forwarded, label=label, bundle_name=bundle_name, fingerprint=fp
                    ),
                    body,
                )
            decisions.append(
                Decision(local_rel, "fast-forward", "local copy untouched since last import")
            )
            continue

        if strategy == "prefer-incoming":
            if not dry_run:
                backup.save(local_path)
                kbc.write_frontmatter_file(
                    local_path,
                    _stamp_provenance(meta, label=label, bundle_name=bundle_name, fingerprint=fp),
                    body,
                )
            decisions.append(Decision(local_rel, "fast-forward", "strategy=prefer-incoming"))
            continue

        if strategy == "prefer-local":
            decisions.append(Decision(local_rel, "skipped", "strategy=prefer-local"))
            continue

        package = None
        if not dry_run:
            package = _write_conflict_package(
                root=root, rel=local_rel, local_path=local_path,
                incoming_file=incoming_file, label=label,
                bundle_name=bundle_name, idx=idx,
            )
        decisions.append(
            Decision(local_rel, "conflict", "both sides changed", conflict_package=package)
        )

    return decisions


# ---------------------------------------------------------------------------
# Other sections
# ---------------------------------------------------------------------------


class Backup:
    """Copies every file the import is about to modify into sync/backups/<ts>/."""

    def __init__(self, root: Path, enabled: bool, dry_run: bool):
        self.root = root
        self.enabled = enabled and not dry_run
        self.dir = kbc.sync_dir(root, "backups") / kbc.timestamp_slug()
        self.saved: list[str] = []

    def save(self, path: Path) -> None:
        if not self.enabled or not path.is_file():
            return
        rel = path.relative_to(self.root)
        dst = self.dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        self.saved.append(rel.as_posix())


def _parse_asset_blocks(text: str) -> dict[str, str]:
    """Split an assets-index page into ``## heading`` → block text."""
    blocks: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                blocks[current] = "\n".join(buffer).rstrip() + "\n"
            current = line[3:].strip()
            buffer = [line]
        elif current is not None:
            buffer.append(line)
    if current is not None:
        blocks[current] = "\n".join(buffer).rstrip() + "\n"
    return blocks


def merge_assets_index(
    *, root: Path, staging: Path, label: str, backup: Backup, dry_run: bool
) -> list[str]:
    """Add asset blocks that this base does not know about yet."""
    notes: list[str] = []
    incoming_root = staging / "assets-index"
    if not incoming_root.is_dir():
        return notes
    for incoming_file in sorted(incoming_root.rglob("*.md")):
        rel = incoming_file.relative_to(staging).as_posix()
        target = root / rel
        incoming_blocks = _parse_asset_blocks(
            incoming_file.read_text(encoding="utf-8", errors="replace")
        )
        if not target.is_file():
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(incoming_file, target)
            notes.append(f"{rel}: added ({len(incoming_blocks)} entries)")
            continue

        local_text = target.read_text(encoding="utf-8", errors="replace")
        local_blocks = _parse_asset_blocks(local_text)
        missing = [h for h in incoming_blocks if h not in local_blocks]
        if not missing:
            continue
        additions: list[str] = []
        for heading in missing:
            block = incoming_blocks[heading].rstrip()
            # The binary itself stays on the other machine unless --with-assets
            # was used; say so instead of leaving a dangling path.
            asset_line = next(
                (ln for ln in block.splitlines() if ln.strip().startswith("- Original:")),
                "",
            )
            asset_rel = asset_line.split("`")[1] if "`" in asset_line else ""
            if asset_rel and not (root / asset_rel).exists():
                block += f"\n- Note: original file not present in this base (imported from {label})"
            additions.append(block)
        if not dry_run:
            backup.save(target)
            with target.open("a", encoding="utf-8") as fh:
                if not local_text.endswith("\n"):
                    fh.write("\n")
                fh.write("\n" + "\n\n".join(additions) + "\n")
        notes.append(f"{rel}: +{len(missing)} entries")
    return notes


def copy_additive(
    *, root: Path, staging: Path, src_rel: str, dst_rel: str, label: str,
    suffixes: tuple[str, ...] | None, dry_run: bool
) -> list[str]:
    """Copy files that do not exist locally; never overwrite, never lose."""
    notes: list[str] = []
    src_root = staging / src_rel
    if not src_root.is_dir():
        return notes
    added = collided = 0
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        if suffixes and src.suffix.lower() not in suffixes:
            continue
        target = root / dst_rel / src.relative_to(src_root)
        if target.is_file():
            same = target.read_bytes() == src.read_bytes()
            if same:
                continue
            target = target.with_name(
                f"{target.stem}__from-{kbc.slugify(label)}{target.suffix}"
            )
            if target.is_file():
                continue
            collided += 1
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        added += 1
    if added:
        note = f"{dst_rel}: +{added} files"
        if collided:
            note += f" ({collided} kept side by side under a __from-{kbc.slugify(label)} name)"
        notes.append(note)
    return notes


def archive_source_log(
    *, root: Path, staging: Path, label: str, exported_at: str, dry_run: bool
) -> list[str]:
    src = staging / "log.md"
    if not src.is_file():
        return []
    day = (exported_at or kbc.now_iso())[:10]
    target = root / "log-archive" / f"imported__{kbc.slugify(label)}__{day}.md"
    if target.is_file():
        return []
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return [f"log-archive/{target.name}: source log archived"]


def compare_entities(*, root: Path, staging: Path) -> list[str]:
    """Report entities the incoming base tracks that this one does not.

    Reported, never applied: changing `entities` reshapes the whole knowledge
    layout, which is the agent's call during `!merge`.
    """
    src = staging / "config" / "entities.yml"
    if not src.is_file():
        return []
    try:
        incoming = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    incoming_entities = incoming.get("entities") or {}
    local_entities = (kbc.load_config(root).raw.get("entities") or {})
    if not isinstance(incoming_entities, dict) or not isinstance(local_entities, dict):
        return []
    return sorted(k for k in incoming_entities if k not in local_entities)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render_report(result: ImportResult) -> str:
    counts = result.counts()
    lines = [
        f"# Import report — {result.label or 'unknown base'}",
        "",
        f"- Bundle: `{result.bundle}`",
        f"- Source base: {result.source_name or '—'} (label: {result.label or '—'})",
        f"- Exported at: {result.exported_at or '—'}",
        f"- Imported at: {kbc.now_iso()}",
    ]
    if result.dry_run:
        lines.append("- **Dry run — nothing was written**")
    if result.backup_dir:
        lines.append(f"- Backup of every touched file: `{result.backup_dir}`")
    lines += ["", "## Knowledge pages", ""]
    if counts:
        lines.append("| Outcome | Pages |")
        lines.append("|---------|------:|")
        for action in ("new", "fast-forward", "enriched", "identical", "duplicate",
                       "skipped", "conflict"):
            if counts.get(action):
                lines.append(f"| {action} | {counts[action]} |")
    else:
        lines.append("_No knowledge pages in this bundle._")

    for action, heading in (
        ("new", "Added"),
        ("fast-forward", "Updated (local copy was untouched)"),
        ("enriched", "Metadata enriched"),
        ("duplicate", "Skipped — same content already present"),
        ("skipped", "Skipped"),
        ("conflict", "Conflicts — waiting for `!merge`"),
    ):
        items = result.by_action(action)
        if not items:
            continue
        lines += ["", f"### {heading} ({len(items)})", ""]
        for d in items:
            suffix = f" — {d.reason}" if d.reason else ""
            lines.append(f"- `{d.arcname}`{suffix}")
            if d.conflict_package:
                lines.append(f"  - package: `{d.conflict_package}`")

    if result.other:
        lines += ["", "## Other sections", ""]
        for section, notes in result.other.items():
            if not notes:
                continue
            lines.append(f"**{section}**")
            lines += [f"- {n}" for n in notes]
            lines.append("")

    if result.new_entities:
        lines += [
            "",
            "## Entities the other base tracks and this one does not",
            "",
            *[f"- `{e}`" for e in result.new_entities],
            "",
            "Not applied automatically — decide during `!merge` whether this base should",
            "track them too (editing `entities` in `kb.config.yml` reshapes routing).",
        ]

    if result.errors:
        lines += ["", "## Problems", "", *[f"- {e}" for e in result.errors]]

    lines += [
        "",
        "## Next step",
        "",
    ]
    if result.conflicts or any(d.near_duplicate_of for d in result.decisions):
        lines += [
            "Run **`!merge`** in the AI chat. The agent will resolve every package in",
            "`review/needs-merge/`, audit the merged pages for contradictions, cross-link",
            "the new knowledge, and reindex.",
        ]
    else:
        lines += [
            "Nothing to decide — the merge was mechanical. Still worth running **`!merge`**",
            "so the agent cross-links the imported pages and checks for contradictions.",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def resolve_defaults(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """CLI flags win; `sync.import` in kb.config.yml is the fallback."""
    configured = kbc.load_config(root).sync_import
    strategy = args.strategy or configured.get("strategy") or "safe"
    if strategy not in STRATEGIES:
        strategy = "safe"
    try:
        similarity = float(
            args.similarity
            if args.similarity is not None
            else configured.get("similarity_threshold", DEFAULT_SIMILARITY)
        )
    except (TypeError, ValueError):
        similarity = DEFAULT_SIMILARITY
    backup = configured.get("backup", True) if not args.no_backup else False
    keep_bundle = args.keep_bundle or not configured.get("move_applied", True)
    return {
        "strategy": strategy,
        "similarity": min(max(similarity, 0.0), 1.0),
        "backup_enabled": bool(backup),
        "keep_bundle": bool(keep_bundle),
    }


def import_bundle(
    *,
    root: Path,
    bundle: Path,
    strategy: str = "safe",
    similarity: float = DEFAULT_SIMILARITY,
    dry_run: bool = False,
    backup_enabled: bool = True,
    keep_bundle: bool = False,
) -> ImportResult:
    result = ImportResult(bundle=bundle.name, dry_run=dry_run)
    manifest = read_manifest(bundle)
    source = manifest.get("source", {}) or {}
    result.label = str(source.get("label") or source.get("name") or bundle.stem)
    result.source_name = str(source.get("name") or "")
    result.exported_at = str(manifest.get("exported_at") or "")

    kbc.ensure_sync_dirs(root)
    (root / "review" / MERGE_QUEUE).mkdir(parents=True, exist_ok=True)

    backup = Backup(root, backup_enabled, dry_run)
    idx = build_local_index(root)

    with tempfile.TemporaryDirectory(prefix="kb-import-") as tmp:
        staging = Path(tmp)
        skipped = extract_bundle(bundle, staging)
        if skipped:
            result.errors.append(
                f"{len(skipped)} unsafe path(s) skipped: {', '.join(skipped[:5])}"
            )

        result.decisions = merge_knowledge(
            root=root, staging=staging, idx=idx, label=result.label,
            bundle_name=bundle.name, strategy=strategy, similarity=similarity,
            backup=backup, dry_run=dry_run,
        )
        result.other = {
            "assets-index": merge_assets_index(
                root=root, staging=staging, label=result.label,
                backup=backup, dry_run=dry_run,
            ),
            "interactions": copy_additive(
                root=root, staging=staging, src_rel="interactions",
                dst_rel="interactions", label=result.label,
                suffixes=(".md", ".yml", ".yaml"), dry_run=dry_run,
            ),
            "provenance metadata": (
                copy_additive(
                    root=root, staging=staging, src_rel="meta/extracted-metadata",
                    dst_rel="processed/extracted-metadata", label=result.label,
                    suffixes=(".yml",), dry_run=dry_run,
                )
                + copy_additive(
                    root=root, staging=staging, src_rel="meta/nlp-meta",
                    dst_rel="processed/nlp-meta", label=result.label,
                    suffixes=(".yml",), dry_run=dry_run,
                )
            ),
            "assets": copy_additive(
                root=root, staging=staging, src_rel="assets", dst_rel="assets",
                label=result.label, suffixes=None, dry_run=dry_run,
            ),
            "log": archive_source_log(
                root=root, staging=staging, label=result.label,
                exported_at=result.exported_at, dry_run=dry_run,
            ),
        }
        result.new_entities = compare_entities(root=root, staging=staging)

    if backup.saved:
        result.backup_dir = backup.dir.relative_to(root).as_posix()

    if not dry_run:
        report_dir = kbc.ensure_dir(kbc.sync_dir(root, "reports"))
        report = report_dir / f"{kbc.timestamp_slug()}__import__{kbc.slugify(result.label)}.md"
        report.write_text(render_report(result), encoding="utf-8")
        result.report_path = report.relative_to(root).as_posix()

        counts = result.counts()
        kbc.append_log(
            operation="import",
            title=bundle.name,
            details=[
                f"Source base: {result.label}",
                "Pages: " + (", ".join(f"{k}: {v}" for k, v in counts.items()) or "none"),
                f"Conflicts pending: {len(result.conflicts)}",
                f"Report: {result.report_path}",
            ],
            root=root,
        )

        if not keep_bundle:
            applied = kbc.ensure_dir(kbc.sync_dir(root, "applied"))
            destination = applied / bundle.name
            if destination.resolve() != bundle.resolve():
                if destination.exists():
                    destination = applied / f"{bundle.stem}__{kbc.timestamp_slug()}{bundle.suffix}"
                shutil.move(str(bundle), str(destination))

    return result


def discover_bundles(root: Path) -> list[Path]:
    inbox = kbc.sync_dir(root, "inbox")
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.glob("*.zip") if p.is_file())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_summary(result: ImportResult) -> None:
    counts = result.counts()
    print(f"\n📥 {result.bundle} → base '{result.label}'")
    if result.dry_run:
        print("   (dry-run: nothing written)")
    if counts:
        for action in ("new", "fast-forward", "enriched", "identical", "duplicate",
                       "skipped", "conflict"):
            if counts.get(action):
                print(f"   {action:<13} {counts[action]}")
    else:
        print("   no knowledge pages in this bundle")
    for section, notes in result.other.items():
        for note in notes:
            print(f"   {section}: {note}")
    if result.new_entities:
        print(f"   new entities reported: {', '.join(result.new_entities)}")
    if result.backup_dir:
        print(f"   backup: {result.backup_dir}")
    if result.report_path:
        print(f"   report: {result.report_path}")
    for err in result.errors:
        kbc.print_err(f"   ⚠️  {err}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — merge a bundle from another base"
    )
    parser.add_argument("bundle", nargs="*", type=Path,
                        help="Bundle file(s). Default: every *.zip in sync/inbox/")
    parser.add_argument("--root", type=Path, default=None, help="KB root (default: auto-detect)")
    parser.add_argument("--strategy", choices=STRATEGIES, default=None,
                        help="How to handle pages changed on both sides "
                             "(default: sync.import.strategy, else 'safe')")
    parser.add_argument("--similarity", type=float, default=None,
                        help="Near-duplicate threshold 0-1 (default: "
                             f"sync.import.similarity_threshold, else {DEFAULT_SIMILARITY})")
    parser.add_argument("--dry-run", action="store_true", help="Classify only, write nothing")
    parser.add_argument("--no-backup", action="store_true",
                        help="Do not snapshot modified files into sync/backups/")
    parser.add_argument("--keep-bundle", action="store_true",
                        help="Leave the bundle in place instead of moving it to sync/applied/")
    parser.add_argument("--json", action="store_true", help="Machine-readable summary")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    if not (root / "knowledge").is_dir():
        kbc.print_err(f"❌ No knowledge/ directory under {root} — is this a deployed base?")
        return 2

    bundles: list[Path] = list(args.bundle) or discover_bundles(root)
    if not bundles:
        inbox = kbc.sync_dir(root, "inbox")
        kbc.ensure_sync_dirs(root)
        kbc.print_err(
            f"❌ No bundle to import.\n"
            f"   Drop a .zip produced by kb_export.py into {inbox}/ and run this again."
        )
        return 2

    defaults = resolve_defaults(root, args)
    results: list[ImportResult] = []
    failed = False
    for bundle in bundles:
        if not bundle.is_file():
            kbc.print_err(f"❌ Not found: {bundle}")
            failed = True
            continue
        try:
            results.append(
                import_bundle(
                    root=root,
                    bundle=bundle,
                    dry_run=args.dry_run,
                    **defaults,
                )
            )
        except (ValueError, zipfile.BadZipFile) as exc:
            kbc.print_err(f"❌ {exc}")
            failed = True

    if args.json:
        import json
        from dataclasses import asdict

        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            _print_summary(result)

    if failed and not results:
        return 2

    conflicts = sum(len(r.conflicts) for r in results)
    candidates = sum(
        1 for r in results for d in r.decisions if d.near_duplicate_of
    )
    if not args.json:
        print("")
        if conflicts or candidates:
            print(
                f"⚠️  {conflicts} conflict(s) and {candidates} merge candidate(s) "
                f"are waiting in review/needs-merge/."
            )
            print("   Next: tell the agent `!merge`.")
        else:
            print("✅ Merged cleanly. Next: tell the agent `!merge` so it cross-links "
                  "and audits the imported knowledge.")
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
