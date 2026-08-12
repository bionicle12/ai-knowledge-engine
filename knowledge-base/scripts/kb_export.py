#!/usr/bin/env python3
"""kb_export — pack the transferable part of a knowledge base into a bundle.

Companion of ``kb_import.py``. Together they let two deployments of the same
knowledge base (e.g. a work laptop and a studio laptop) exchange knowledge
without overwriting each other. See ``16_MERGE.md`` for the full contract.

What goes into a bundle:

  * ``knowledge/**.md``                 — the clean knowledge itself
  * ``assets-index/**.md``              — descriptions of binary assets
  * ``interactions/**``                 — session logs and insights (append-only)
  * ``meta/extracted-metadata/*.yml``   — provenance for ingested sources
  * ``meta/nlp-meta/*.yml``             — NLP enrichment metadata
  * ``config/entities.yml``             — role, language and tracked entities
  * ``log.md``                          — the source base's operations log
  * ``assets/**``                       — binary originals, only with --with-assets

What never goes into a bundle: ``raw/``, ``processed/`` payloads, ``review/``
queues, ``sync/`` itself, ``.repomix/`` output, and secrets-bearing operational
state. Raw material stays on the machine that produced it.

Usage:
    python3 scripts/kb_export.py                       # → sync/outbox/<bundle>.zip
    python3 scripts/kb_export.py --label studio-laptop
    python3 scripts/kb_export.py --with-assets
    python3 scripts/kb_export.py --since 2026-06-01
    python3 scripts/kb_export.py --only knowledge,assets-index
    python3 scripts/kb_export.py --out /tmp/kb.zip --dry-run

Exit codes:
    0 — bundle written (or dry-run completed)
    1 — nothing to export (base is empty)
    2 — environment error (no knowledge base found)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - kb_common already raises a clear error
    raise

BUNDLE_FORMAT = 1
MANIFEST_NAME = "manifest.yml"

# Sections that can be selected with --only / skipped with --skip.
SECTIONS = ("knowledge", "assets-index", "interactions", "meta", "config", "log", "assets")
DEFAULT_SECTIONS = ("knowledge", "assets-index", "interactions", "meta", "config", "log")


@dataclass
class BundleFile:
    """One file staged for the bundle."""

    arcname: str            # path inside the zip
    source: Path            # path on disk
    size: int
    sha256: str             # raw-bytes hash
    fingerprint: str = ""   # content fingerprint (knowledge pages only)
    info: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _iter_markdown(directory: Path) -> Iterable[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*.md") if p.is_file())


def _page_updated(meta: dict[str, Any]) -> str | None:
    """Best available "when was this last touched" date from frontmatter."""
    for key in ("last_verified", "extracted_at", "valid_from", "session_date"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def _passes_since(path: Path, meta: dict[str, Any], since: _dt.date | None) -> bool:
    """True if the page is new enough for a --since filtered export."""
    if since is None:
        return True
    updated = _page_updated(meta)
    if updated:
        try:
            return _dt.date.fromisoformat(str(updated)[:10]) >= since
        except ValueError:
            pass
    # No usable frontmatter date — fall back to mtime so nothing is silently lost.
    return _dt.date.fromtimestamp(path.stat().st_mtime) >= since


def _title_from(meta: dict[str, Any], body: str, path: Path) -> str:
    if meta.get("title"):
        return str(meta["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def collect_knowledge(root: Path, since: _dt.date | None) -> list[BundleFile]:
    out: list[BundleFile] = []
    knowledge = root / "knowledge"
    for path in _iter_markdown(knowledge):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        meta, body = kbc.parse_frontmatter(text)
        if not _passes_since(path, meta, since):
            continue
        rel = path.relative_to(root).as_posix()
        out.append(
            BundleFile(
                arcname=rel,
                source=path,
                size=path.stat().st_size,
                sha256=kbc.compute_source_hash(path, prefix_len=64),
                fingerprint=kbc.content_fingerprint(text),
                info={
                    "title": _title_from(meta, body, path),
                    "slug": path.stem,
                    "section": rel.split("/")[1] if "/" in rel else "",
                    "lifecycle": meta.get("lifecycle"),
                    "importance": meta.get("importance"),
                    "updated": _page_updated(meta),
                },
            )
        )
    return out


def _collect_plain(root: Path, rel_dir: str, *, suffixes: tuple[str, ...] | None = None,
                   arc_prefix: str | None = None) -> list[BundleFile]:
    """Collect files from a directory verbatim (no frontmatter interpretation)."""
    out: list[BundleFile] = []
    directory = root / rel_dir
    if not directory.is_dir():
        return out
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        arcname = rel if arc_prefix is None else f"{arc_prefix}/{path.relative_to(directory).as_posix()}"
        out.append(
            BundleFile(
                arcname=arcname,
                source=path,
                size=path.stat().st_size,
                sha256=kbc.compute_source_hash(path, prefix_len=64),
            )
        )
    return out


def build_config_snapshot(cfg: kbc.KbConfig) -> str:
    """Role/entity slice of kb.config.yml — never the whole config.

    Paths, machine-specific settings and privacy switches stay home; only the
    parts that describe *what this base knows about* travel.
    """
    kb = cfg.raw.get("knowledge_base", {}) or {}
    snapshot = {
        "name": kb.get("name"),
        "roles": kb.get("roles", {}),
        "language": (cfg.raw.get("language_policy", {}) or {}).get("primary", cfg.primary_language),
        "entities": cfg.raw.get("entities", {}) or {},
    }
    return yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False)


def collect(root: Path, *, sections: tuple[str, ...], since: _dt.date | None) -> list[BundleFile]:
    files: list[BundleFile] = []
    if "knowledge" in sections:
        files += collect_knowledge(root, since)
    if "assets-index" in sections:
        files += _collect_plain(root, "assets-index", suffixes=(".md",))
    if "interactions" in sections:
        files += _collect_plain(root, "interactions", suffixes=(".md", ".yml", ".yaml"))
    if "meta" in sections:
        files += _collect_plain(
            root, "processed/extracted-metadata", suffixes=(".yml",),
            arc_prefix="meta/extracted-metadata",
        )
        files += _collect_plain(
            root, "processed/nlp-meta", suffixes=(".yml",),
            arc_prefix="meta/nlp-meta",
        )
    if "assets" in sections:
        files += _collect_plain(root, "assets")
    if "log" in sections:
        log = kbc.log_path(root)
        if log.is_file():
            files.append(
                BundleFile(
                    arcname="log.md",
                    source=log,
                    size=log.stat().st_size,
                    sha256=kbc.compute_source_hash(log, prefix_len=64),
                )
            )
    return files


# ---------------------------------------------------------------------------
# Manifest & writing
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    cfg: kbc.KbConfig,
    label: str,
    files: list[BundleFile],
    with_assets: bool,
    since: _dt.date | None,
    sections: tuple[str, ...],
    extras: dict[str, str] | None = None,
) -> dict[str, Any]:
    kb = cfg.raw.get("knowledge_base", {}) or {}
    counts: dict[str, int] = {}
    for arcname in [bf.arcname for bf in files] + list(extras or {}):
        top = arcname.split("/")[0] if "/" in arcname else arcname
        counts[top] = counts.get(top, 0) + 1
    return {
        "bundle_format": BUNDLE_FORMAT,
        "generator": "kb_export.py",
        "instructions_version": cfg.instructions_version,
        "exported_at": kbc.now_iso(),
        "source": {
            "name": kb.get("name") or cfg.root.name,
            "label": label,
            "role": (kb.get("roles", {}) or {}).get("primary"),
            "language": cfg.primary_language,
            "mode": cfg.mode,
        },
        "options": {
            "sections": list(sections),
            "with_assets": with_assets,
            "since": since.isoformat() if since else None,
        },
        "counts": counts,
        "files": [
            {
                "path": bf.arcname,
                "bytes": bf.size,
                "sha256": bf.sha256,
                **({"fingerprint": bf.fingerprint} if bf.fingerprint else {}),
                **{k: v for k, v in bf.info.items() if v not in (None, "")},
            }
            for bf in files
        ],
    }


def default_bundle_name(label: str) -> str:
    return f"kb-bundle__{kbc.slugify(label)}__{_dt.date.today().isoformat()}.zip"


def write_bundle(
    out_path: Path,
    files: list[BundleFile],
    manifest: dict[str, Any],
    extras: dict[str, str] | None = None,
) -> Path:
    """Write the zip. `extras` are generated members (arcname → text)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            MANIFEST_NAME,
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        )
        for arcname, text in (extras or {}).items():
            zf.writestr(arcname, text)
        for bf in files:
            zf.write(bf.source, bf.arcname)
    return out_path


def export_bundle(
    *,
    root: Path,
    label: str | None = None,
    out: Path | None = None,
    with_assets: bool = False,
    since: _dt.date | None = None,
    only: tuple[str, ...] | None = None,
    skip: tuple[str, ...] = (),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Collect and (unless dry_run) write a bundle. Returns a summary dict."""
    cfg = kbc.load_config(root)
    label = label or cfg.sync_label

    # CLI wins; kb.config.yml `sync.export` is the fallback; then the built-ins.
    configured = cfg.sync_export
    if only:
        sections = tuple(only)
    else:
        configured_sections = configured.get("sections")
        sections = (
            tuple(s for s in configured_sections if s in SECTIONS)
            if isinstance(configured_sections, list) and configured_sections
            else DEFAULT_SECTIONS
        )
    if with_assets or configured.get("with_assets"):
        if "assets" not in sections:
            sections = sections + ("assets",)
    sections = tuple(s for s in sections if s not in skip)

    files = collect(root, sections=sections, since=since)
    extras: dict[str, str] = {}
    if "config" in sections:
        extras["config/entities.yml"] = build_config_snapshot(cfg)
    manifest = build_manifest(
        cfg=cfg, label=label, files=files, with_assets="assets" in sections,
        since=since, sections=sections, extras=extras,
    )

    if out is None:
        out = kbc.ensure_sync_dirs(root) / "outbox" / default_bundle_name(label)

    summary: dict[str, Any] = {
        "bundle": str(out),
        "label": label,
        "files": len(files),
        "bytes": sum(bf.size for bf in files),
        "counts": manifest["counts"],
        "sections": list(sections),
        "dry_run": dry_run,
    }
    if dry_run or not files:
        return summary

    write_bundle(out, files, manifest, extras)
    summary["bundle_bytes"] = out.stat().st_size
    kbc.append_log(
        operation="export",
        title=out.name,
        details=[
            f"Label: {label}",
            f"Files: {len(files)} ({', '.join(f'{k}: {v}' for k, v in manifest['counts'].items())})",
            f"Bundle: {out}",
        ],
        root=root,
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_section_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = tuple(p.strip() for p in value.split(",") if p.strip())
    unknown = [p for p in parts if p not in SECTIONS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown section(s): {', '.join(unknown)}. Known: {', '.join(SECTIONS)}"
        )
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — export a transferable knowledge bundle"
    )
    parser.add_argument("--root", type=Path, default=None, help="KB root (default: auto-detect)")
    parser.add_argument("--out", type=Path, default=None, help="Bundle path (default: sync/outbox/…)")
    parser.add_argument("--label", default=None,
                        help="Name this base carries into the other one (default: knowledge_base.name)")
    parser.add_argument("--with-assets", action="store_true",
                        help="Include binary originals from assets/ (bundles get large)")
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                        help="Only knowledge updated on/after this date")
    parser.add_argument("--only", type=_parse_section_list, default=None,
                        help=f"Comma-separated subset of: {', '.join(SECTIONS)}")
    parser.add_argument("--skip", type=_parse_section_list, default=(),
                        help="Comma-separated sections to leave out")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be packed")
    parser.add_argument("--json", action="store_true", help="Machine-readable summary")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    if not (root / "knowledge").is_dir():
        kbc.print_err(f"❌ No knowledge/ directory under {root} — is this a deployed base?")
        return 2

    since: _dt.date | None = None
    if args.since:
        try:
            since = _dt.date.fromisoformat(args.since)
        except ValueError:
            kbc.print_err(f"❌ --since must be YYYY-MM-DD, got {args.since!r}")
            return 2

    summary = export_bundle(
        root=root,
        label=args.label,
        out=args.out,
        with_assets=args.with_assets,
        since=since,
        only=args.only or None,
        skip=args.skip,
        dry_run=args.dry_run,
    )

    if args.json:
        import json

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        counts = ", ".join(f"{k}: {v}" for k, v in summary["counts"].items()) or "nothing"
        print(f"📦 Export from {root}")
        print(f"   label:    {summary['label']}")
        print(f"   sections: {', '.join(summary['sections'])}")
        print(f"   contents: {counts}")
        print(f"   files:    {summary['files']} ({summary['bytes'] / 1024:.1f} KiB uncompressed)")
        if summary["dry_run"]:
            print("   (dry-run: nothing written)")
        elif summary["files"]:
            size_kib = summary.get("bundle_bytes", 0) / 1024
            print(f"✅ Bundle: {summary['bundle']} ({size_kib:.1f} KiB)")
            print("   Copy it to the other machine's sync/inbox/ and run import.")

    if not summary["files"]:
        kbc.print_err("⚠️  Nothing to export — no matching files.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
