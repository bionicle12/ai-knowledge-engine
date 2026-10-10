#!/usr/bin/env python3
"""kb_nlp_batch — re-run NLP enrichment over already-processed materials.

Use cases:
  - You upgraded spaCy or installed a better model
  - You added a new entity to kb.config.yml and want to re-resolve
  - Periodic refresh during consolidation (``kb_reindex.py`` runs ``--incremental``)

Follows the same NLP rules as ingest: nothing runs when ``nlp.enabled`` is
false, and files ingested from ``nlp.skip_extensions`` types or archive
listings are skipped (an nlp-meta file an older run wrote for them is removed).
A refreshed file's ``nlp_meta_path`` is recorded in its
``processed/extracted-metadata/`` entry, re-read and written under the
pipeline lock (``.kb-state/locks/pipeline.lock``) so a concurrent
``kb_ingest.py --mark-extracted`` is kept.

Usage:
  python3 scripts/kb_nlp_batch.py                  # full re-run
  python3 scripts/kb_nlp_batch.py --incremental    # only files without nlp-meta yet
  python3 scripts/kb_nlp_batch.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402
import kb_ingest  # noqa: E402

TEXT_DIRS = ("markdown", "transcripts", "ocr", "tables")


@dataclass
class NlpRunResult:
    processed_path: str
    nlp_meta_path: str
    skipped: bool = False
    reason: str = ""


def _write_yaml(path: Path, data: dict) -> None:
    kbc.atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _ingest_metadata(path: Path, processed_rel: str) -> dict:
    """The extracted-metadata entry of ``processed_rel`` (``{}`` if none)."""
    try:
        meta = kbc.yaml_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    if isinstance(meta, dict) and meta.get("processed_path") == processed_rel:
        return meta
    return {}


def _set_nlp_meta_path(
    root: Path, metadata_path: Path, processed_rel: str, value: str | None
) -> None:
    """Record *value* as the ``nlp_meta_path`` of the file's metadata entry.

    The entry is read again under the pipeline lock, so a ``--mark-extracted``
    or re-process that ran while NLP was busy is not undone by writing back
    an older copy (inside ``kb_reindex`` the lock it holds is shared)."""
    with kbc.kb_lock(root, "pipeline", timeout=kb_ingest.LOCK_TIMEOUT):
        metadata = _ingest_metadata(metadata_path, processed_rel)
        if metadata and metadata.get("nlp_meta_path") != value:
            metadata["nlp_meta_path"] = value
            _write_yaml(metadata_path, metadata)


def _skip_reason(meta: dict, skip_extensions: set[str]) -> str:
    """Why ingest runs no NLP on this file ("" = it does)."""
    if meta.get("strategy") == "archive":
        return "archive listing"
    file_type = str(meta.get("file_type") or "").lower()
    if file_type and f".{file_type}" in skip_extensions:
        return f"nlp.skip_extensions (.{file_type})"
    return ""


def _remove_stale_nlp_meta(
    root: Path, target: Path, processed_rel: str, metadata: dict, metadata_path: Path
) -> bool:
    """Drop the nlp-meta an older batch wrote for a file ingest runs no NLP on
    (one without ``source``, as older batches wrote, or whose ``source`` is
    this file) and unlink it from the metadata."""
    if not target.is_file():
        return False
    try:
        nlp_meta = kbc.yaml_load(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    if not isinstance(nlp_meta, dict) or nlp_meta.get("source") not in (None, processed_rel):
        return False
    target.unlink()
    if metadata.get("nlp_meta_path") == kbc.posix_relpath(target, root):
        _set_nlp_meta_path(root, metadata_path, processed_rel, None)
    return True


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except kbc.KbLockTimeout as e:
        kbc.print_err(
            f"❌ [nlp-batch] {e}. Another ingest/reindex/watch run is working on "
            "this base; retry when it finishes."
        )
        return 2


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — batch NLP")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process files that don't yet have a corresponding nlp-meta yml",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        kbc.print_err(
            f"❌ [nlp-batch] {root} is not a knowledge base (no kb.config.yml); "
            "pass --root <base>"
        )
        return 2
    cfg = kbc.load_config(root)
    if not cfg.nlp_enabled:
        print("[nlp-batch] nlp.enabled is false in kb.config.yml; nothing to do")
        return 0
    available_dirs = [
        path for path in (root / "processed" / name for name in TEXT_DIRS) if path.is_dir()
    ]
    if not available_dirs:
        print("[nlp-batch] no processed text directories; nothing to do")
        return 0

    nlp_dir = root / "processed" / "nlp-meta"
    nlp_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir = root / "processed" / "extracted-metadata"
    skip_extensions = {
        "." + str(ext).strip().lower().lstrip(".") for ext in cfg.skip_extensions
    }
    results: list[NlpRunResult] = []
    for directory in available_dirs:
        for md in sorted(directory.glob("*.md")):
            processed_rel = kbc.posix_relpath(md, root)
            target = nlp_dir / f"{md.stem}.yml"
            target_rel = kbc.posix_relpath(target, root)
            # Ingest names the metadata, the processed text and the nlp-meta alike.
            metadata_path = metadata_dir / f"{md.stem}.yml"
            metadata = _ingest_metadata(metadata_path, processed_rel)
            reason = _skip_reason(metadata, skip_extensions)
            if reason:
                if _remove_stale_nlp_meta(root, target, processed_rel, metadata, metadata_path):
                    reason += "; stale nlp-meta removed"
                results.append(
                    NlpRunResult(processed_rel, "", skipped=True, reason=reason)
                )
                continue
            if args.incremental and target.exists():
                results.append(
                    NlpRunResult(
                        processed_path=processed_rel,
                        nlp_meta_path=target_rel,
                        skipped=True,
                        reason="incremental: nlp-meta already exists",
                    )
                )
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                kbc.print_err(f"[nlp-batch] cannot read {md}: {e}")
                continue
            nlp_meta = kb_ingest.nlp_enrich(text, cfg, knowledge_dir=root / "knowledge")
            _write_yaml(
                target, {"source": processed_rel, "processed_at": kbc.now_iso(), **nlp_meta}
            )
            if metadata and metadata.get("nlp_meta_path") != target_rel:
                _set_nlp_meta_path(root, metadata_path, processed_rel, target_rel)
            results.append(NlpRunResult(processed_rel, target_rel))

    refreshed = sum(1 for r in results if not r.skipped)
    skipped = len(results) - refreshed
    if refreshed:
        kbc.append_log(
            operation="nlp-batch",
            title=f"batch NLP ({len(results)} files)",
            details=[
                f"incremental={args.incremental}",
                f"skipped={skipped}",
                f"refreshed={refreshed}",
            ],
            root=root,
        )

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        print(
            f"[nlp-batch] {len(results)} files; "
            f"refreshed={refreshed}, skipped={skipped}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
