#!/usr/bin/env python3
"""kb_reindex — cross-platform reindex orchestrator for AI Knowledge Engine.

A pure-Python equivalent of ``shell/reindex.sh`` so the pipeline runs
identically on Windows (no Git Bash / WSL required), macOS, and Linux. The file
watcher (``kb_watch.py``) calls this instead of shelling out to ``bash``.

Steps:
  1. ingest        — python kb_ingest.py
  2. routing       — python kb_route.py
  3. quick lint    — python kb_lint.py --quick
  4. consolidation — lint report + nlp batch + reflection trigger (throttled by
                     a ``.last_consolidation`` marker; default every 24h)
  5. index         — repomix (if installed)

Usage:
  python3 scripts/kb_reindex.py                # full pipeline
  python3 scripts/kb_reindex.py --quick        # ingest + index only
  python3 scripts/kb_reindex.py --no-index     # skip repomix
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

CONSOLIDATION_MARKER = ".last_consolidation"
DAY_SECONDS = 86400


def _py(script: str, *args: str, root: Path) -> int:
    """Run a sibling kb_*.py script with the current interpreter."""
    script_path = SCRIPT_DIR / script
    if not script_path.is_file():
        return 0  # optional step, silently skip
    cmd = [kbc.detect_python_executable(), str(script_path), "--root", str(root), *args]
    return subprocess.run(cmd, check=False).returncode


def _consolidation_due(root: Path, interval_hours: int) -> bool:
    marker = root / CONSOLIDATION_MARKER
    if not marker.is_file():
        return True
    try:
        last = float(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True
    return (time.time() - last) > interval_hours * 3600


def _touch_consolidation(root: Path) -> None:
    (root / CONSOLIDATION_MARKER).write_text(str(int(time.time())), encoding="utf-8")


def run_repomix(root: Path) -> bool:
    """Generate the Repomix index. Returns True if it ran."""
    repomix = shutil.which("repomix")
    if not repomix:
        print("⚠️  [reindex] repomix not installed; skipping index generation")
        print("    install: npm install -g repomix")
        return False
    print("📦 [reindex] generating Repomix index...")
    result = subprocess.run([repomix, "--quiet"], check=False, cwd=str(root))
    if result.returncode != 0:
        subprocess.run([repomix], check=False, cwd=str(root))
    return True


def reindex(
    root: Path,
    *,
    quick: bool = False,
    do_index: bool = True,
    do_ingest: bool = True,
) -> int:
    cfg = kbc.load_config(root)

    if do_ingest:
        print("🔄 [reindex] ingest pipeline...")
        _py("kb_ingest.py", root=root)

    print("🧭 [reindex] routing pages...")
    _py("kb_route.py", root=root)

    print("🩺 [reindex] quick lint...")
    _py("kb_lint.py", "--quick", root=root)

    if not quick:
        interval = int(cfg.autorun.get("consolidation_interval_hours", 24))
        if _consolidation_due(root, interval):
            print("🧰 [reindex] consolidation...")
            _py("kb_lint.py", "--output", "report", root=root)
            _py("kb_nlp_batch.py", "--incremental", root=root)
            # reflection: trigger logic lives in kb_reflect.py
            reflect = SCRIPT_DIR / "kb_reflect.py"
            if reflect.is_file():
                _py("kb_reflect.py", "--check-threshold", "--dry-run", root=root)
            _touch_consolidation(root)

    if do_index:
        run_repomix(root)

    print("✅ [reindex] done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — cross-platform reindex orchestrator"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--quick", action="store_true", help="ingest + index only")
    parser.add_argument("--no-index", action="store_true", help="skip repomix")
    parser.add_argument("--no-ingest", action="store_true", help="skip ingest step")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    return reindex(
        root,
        quick=args.quick,
        do_index=not args.no_index,
        do_ingest=not args.no_ingest,
    )


if __name__ == "__main__":
    raise SystemExit(main())
