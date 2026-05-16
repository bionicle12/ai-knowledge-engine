#!/usr/bin/env python3
"""kb_nlp_batch — re-run NLP enrichment over already-processed materials.

Use cases:
  - You upgraded spaCy or installed a better model
  - You added a new entity to kb.config.yml and want to re-resolve
  - Periodic refresh during consolidation (called from reindex.sh)

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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402
import kb_ingest  # noqa: E402


@dataclass
class NlpRunResult:
    processed_path: str
    nlp_meta_path: str
    skipped: bool = False
    reason: str = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — batch NLP")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process files that don't yet have a corresponding nlp-meta yml",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    cfg = kbc.load_config(root)
    processed = root / "processed" / "markdown"
    nlp_dir = root / "processed" / "nlp-meta"
    nlp_dir.mkdir(parents=True, exist_ok=True)

    if not processed.is_dir():
        print(f"[nlp-batch] no {processed}; nothing to do")
        return 0

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        kbc.print_err("PyYAML required for batch NLP")
        return 2

    results: list[NlpRunResult] = []
    for md in sorted(processed.glob("*.md")):
        target = nlp_dir / f"{md.stem}.yml"
        if args.incremental and target.exists():
            results.append(
                NlpRunResult(
                    processed_path=str(md.relative_to(root)),
                    nlp_meta_path=str(target.relative_to(root)),
                    skipped=True,
                    reason="incremental: nlp-meta already exists",
                )
            )
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            kbc.print_err(f"[nlp-batch] cannot read {md}: {e}")
            continue
        meta = kb_ingest.nlp_enrich(text, cfg, knowledge_dir=root / "knowledge")
        target.write_text(
            yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        results.append(
            NlpRunResult(
                processed_path=str(md.relative_to(root)),
                nlp_meta_path=str(target.relative_to(root)),
            )
        )

    kbc.append_log(
        operation="nlp-batch",
        title=f"batch NLP ({len(results)} files)",
        details=[
            f"incremental={args.incremental}",
            f"skipped={sum(1 for r in results if r.skipped)}",
            f"refreshed={sum(1 for r in results if not r.skipped)}",
        ],
        root=root,
    )

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        print(
            f"[nlp-batch] {len(results)} files; "
            f"refreshed={sum(1 for r in results if not r.skipped)}, "
            f"skipped={sum(1 for r in results if r.skipped)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
