#!/usr/bin/env python3
"""kb_watch — file system watcher for AI Knowledge Engine.

Monitors raw/*/unsorted/ for new files and knowledge/ for edits.
On raw events:  ingest → reindex.
On knowledge events: quick lint → reindex.

Requires `watchdog`. Falls back to a lightweight polling watcher if watchdog
is not installed (slower, less efficient, but works).

Usage:
  python3 scripts/kb_watch.py
  python3 scripts/kb_watch.py --verbose
  python3 scripts/kb_watch.py --no-reindex     # skip auto-reindex
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


_running = True


def _stop(signum, frame):  # noqa: ARG001
    global _running
    _running = False


def _run_ingest_for(root: Path, path: Path, *, verbose: bool) -> None:
    cmd = [
        kbc.detect_python_executable(),
        str(SCRIPT_DIR / "kb_ingest.py"),
        "--root",
        str(root),
        str(path),
    ]
    if verbose:
        print(f"[watch] {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


def _run_quick_lint(root: Path, *, verbose: bool) -> None:
    cmd = [
        kbc.detect_python_executable(),
        str(SCRIPT_DIR / "kb_lint.py"),
        "--root",
        str(root),
        "--quick",
    ]
    if verbose:
        print(f"[watch] {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


def _run_reindex(root: Path, *, verbose: bool) -> None:
    """Reindex cross-platform.

    Prefer the Python orchestrator (kb_reindex.py) so this works identically on
    Windows without Git Bash / WSL. Fall back to bash reindex.sh only if the
    Python script is unavailable (older deployments).
    """
    reindex_py = SCRIPT_DIR / "kb_reindex.py"
    if reindex_py.is_file():
        cmd = [
            kbc.detect_python_executable(),
            str(reindex_py),
            "--root",
            str(root),
            "--no-ingest",  # the watcher already ran ingest for the changed file
        ]
        if verbose:
            print(f"[watch] {' '.join(cmd)}")
        subprocess.run(cmd, check=False, cwd=str(root))
        return

    reindex_sh = root / "reindex.sh"
    if not reindex_sh.is_file():
        return
    if verbose:
        print(f"[watch] running {reindex_sh}")
    subprocess.run(["bash", str(reindex_sh)], check=False, cwd=str(root))


def watch_with_watchdog(
    root: Path,
    *,
    debounce_raw: int,
    debounce_knowledge: int,
    do_reindex: bool,
    verbose: bool,
) -> int:
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-untyped]
        from watchdog.observers import Observer  # type: ignore[import-untyped]
    except ImportError:
        return -1  # signal caller to use polling fallback

    # pending_raw is written from watchdog's dispatch thread and read from the
    # main loop — every access goes through the lock.
    lock = threading.Lock()
    pending_raw: dict[str, float] = {}
    pending_knowledge: list[float] = [0.0]

    def _is_unsorted(path: str) -> bool:
        return "/unsorted/" in path or "\\unsorted\\" in path

    class RawHandler(FileSystemEventHandler):
        def _touch(self, path: str) -> None:
            if not path or not _is_unsorted(path):
                return
            with lock:
                pending_raw[path] = time.time()

        def on_created(self, event):
            if not event.is_directory:
                self._touch(event.src_path)

        def on_modified(self, event):
            # A file still being copied keeps emitting modified events; refresh
            # the timestamp so the debounce window restarts and we never ingest
            # a half-copied file.
            if not event.is_directory:
                self._touch(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                self._touch(getattr(event, "dest_path", ""))

    class KnowledgeHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory or not event.src_path.endswith(".md"):
                return
            pending_knowledge[0] = time.time()

    observer = Observer()
    raw_dir = root / "raw"
    knowledge_dir = root / "knowledge"
    if raw_dir.is_dir():
        observer.schedule(RawHandler(), str(raw_dir), recursive=True)
    if knowledge_dir.is_dir():
        observer.schedule(KnowledgeHandler(), str(knowledge_dir), recursive=True)
    observer.start()
    print(f"[watch] watching {root} (Ctrl+C to stop)")

    try:
        while _running:
            now = time.time()
            with lock:
                ready = [p for p, t in pending_raw.items() if now - t > debounce_raw]
                for p in ready:
                    del pending_raw[p]
            ingested = False
            for p in ready:
                path = Path(p)
                if path.exists():
                    _run_ingest_for(root, path, verbose=verbose)
                    ingested = True
            if ingested and do_reindex:
                _run_reindex(root, verbose=verbose)
            if (
                pending_knowledge[0]
                and now - pending_knowledge[0] > debounce_knowledge
            ):
                pending_knowledge[0] = 0.0
                _run_quick_lint(root, verbose=verbose)
                if do_reindex:
                    _run_reindex(root, verbose=verbose)
            time.sleep(0.5)
    finally:
        observer.stop()
        observer.join(timeout=2.0)
    return 0


@dataclass
class _PollEntry:
    """Tracking state for one file seen by the polling watcher."""

    mtime: float
    size: int
    stable_since: float  # wall-clock moment this exact (mtime, size) was first seen
    processed: bool = False


def _poll_once(
    root: Path,
    seen: dict[str, _PollEntry],
    now: float,
    debounce_raw: float,
) -> list[Path]:
    """One polling pass: update tracking state, return files ready to ingest.

    A file is ready when its ``(mtime, size)`` has stayed unchanged for at
    least ``debounce_raw`` seconds of observation — measured against our own
    clock, not the file's mtime, so clock skew on network shares cannot stall
    or rush the debounce. Files already handed to ingest are skipped until
    they change again: kb_ingest normally moves them out of ``unsorted/``, and
    one that stays behind failed and must not retry in a tight loop.
    """
    ready: list[Path] = []
    for p in (root / "raw").rglob("unsorted/*"):
        if not p.is_file():
            continue
        key = str(p.resolve())
        try:
            st = p.stat()
        except OSError:
            continue
        entry = seen.get(key)
        if entry is None or (entry.mtime, entry.size) != (st.st_mtime, st.st_size):
            seen[key] = _PollEntry(st.st_mtime, st.st_size, now)
            continue
        if entry.processed:
            continue
        if now - entry.stable_since >= debounce_raw:
            entry.processed = True
            ready.append(p)
    return ready


def watch_polling(
    root: Path,
    *,
    debounce_raw: int,
    do_reindex: bool,
    verbose: bool,
) -> int:
    """Simple polling fallback when watchdog is not installed."""
    print(f"[watch] (polling fallback) watching {root}")
    seen: dict[str, _PollEntry] = {}
    while _running:
        ready = _poll_once(root, seen, time.time(), debounce_raw)
        for p in ready:
            _run_ingest_for(root, p, verbose=verbose)
        if ready and do_reindex:
            _run_reindex(root, verbose=verbose)
        # Drop tracking for files ingest moved away so the map stays small.
        for key in [k for k, e in seen.items() if e.processed and not Path(k).exists()]:
            del seen[key]
        time.sleep(2.0)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — file watcher")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-reindex", action="store_true")
    parser.add_argument(
        "--debounce-raw",
        type=int,
        default=None,
        help="Seconds to wait after a raw file appears (default from config or 5)",
    )
    parser.add_argument(
        "--debounce-knowledge",
        type=int,
        default=None,
        help="Seconds to wait after knowledge edits (default from config or 2)",
    )
    args = parser.parse_args(argv)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    root = args.root or kbc.find_kb_root()
    cfg = kbc.load_config(root)

    debounce_raw = args.debounce_raw
    if debounce_raw is None:
        debounce_raw = int(cfg.autorun.get("debounce_raw_seconds", 5))
    debounce_knowledge = args.debounce_knowledge
    if debounce_knowledge is None:
        debounce_knowledge = int(cfg.autorun.get("debounce_knowledge_seconds", 2))

    if not (root / "raw").is_dir():
        print(f"[watch] no raw/ in {root}; nothing to watch")
        return 1

    code = watch_with_watchdog(
        root,
        debounce_raw=debounce_raw,
        debounce_knowledge=debounce_knowledge,
        do_reindex=not args.no_reindex,
        verbose=args.verbose,
    )
    if code == -1:
        print("[watch] watchdog not installed; using polling fallback")
        code = watch_polling(
            root,
            debounce_raw=debounce_raw,
            do_reindex=not args.no_reindex,
            verbose=args.verbose,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
