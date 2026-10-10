#!/usr/bin/env python3
"""kb_watch — file system watcher for AI Knowledge Engine.

Watches the folders listed in `autorun.watch_dirs` (default
`raw/*/unsorted/` and `knowledge/`; `raw/*/unsorted/` includes the catch-all
`raw/unsorted/` inbox):

  - new files under a `raw/…` entry → one batched kb_ingest → reindex
  - `.md` pages created, edited, moved or deleted under any other entry →
    quick lint (`autorun.auto_lint_on_change`) → reindex
    (`autorun.auto_reindex_on_change`)

Files already waiting in the inboxes when the watcher starts are
ingested too. The routing pages kb_reindex regenerates
(`knowledge/routing/`, `knowledge/routing-table.md`) are ignored, so the
watcher never reacts to its own reindex. `ingest.ignore_globs` (`.DS_Store`,
`~$*`, `*.part`, …) are never handed to ingest.

Requires `watchdog`. Falls back to polling every 2 s (raw inbox and
knowledge pages) if watchdog is not installed. `autorun.watch_enabled: false`
turns the watcher off; one watcher runs per base (lock
`.kb-state/locks/watch.lock`).

Usage:
  python3 scripts/kb_watch.py
  python3 scripts/kb_watch.py --verbose
  python3 scripts/kb_watch.py --no-reindex     # never reindex
"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterable, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

# Written by kb_route during every reindex — never a reason to reindex again.
GENERATED_DIRS = ("knowledge/routing/",)
GENERATED_FILES = ("knowledge/routing-table.md",)
INGEST_BATCH = 100  # paths per kb_ingest call (keeps the command line short)
POLL_SECONDS = 2.0

_running = True


def _stop(signum, frame):  # noqa: ARG001
    global _running
    _running = False


def _normalize_pattern(entry: Any) -> str | None:
    pattern = str(entry).strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.strip("/")
    parts = pattern.split("/")
    if not pattern or ".." in parts or ":" in parts[0]:
        return None
    if any(ch in parts[0] for ch in "*?["):
        return None  # must start with a folder name: never watch the whole base
    return pattern


CATCH_ALL_INBOX = "raw/unsorted"  # kb_ingest's inbox for files of no category


def _static_prefix(pattern: str) -> str:
    parts: list[str] = []
    for part in pattern.split("/"):
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def _under(rel: str, patterns: Iterable[str]) -> bool:
    """True when a folder above `rel` matches one of the patterns."""
    parts = rel.split("/")
    ancestors = ["/".join(parts[:i]) for i in range(1, len(parts))]
    return any(fnmatch.fnmatchcase(a, p) for a in ancestors for p in patterns)


@dataclass(frozen=True)
class WatchScope:
    """What the watcher reacts to, from `autorun.watch_dirs`.

    Entries under `raw/` are ingest inboxes; any other entry is watched for
    `.md` edits. Entries are folder globs relative to the base root.
    `raw/*/unsorted` also covers the catch-all `raw/unsorted/` that ingest
    scans (the category "unsorted").
    """

    raw_patterns: tuple[str, ...] = ("raw/*/unsorted", CATCH_ALL_INBOX)
    edit_patterns: tuple[str, ...] = ("knowledge",)
    ignore_globs: tuple[str, ...] = kbc.DEFAULT_INGEST_IGNORE_GLOBS

    @classmethod
    def from_config(cls, cfg: kbc.KbConfig) -> "WatchScope":
        raw: list[str] = []
        edit: list[str] = []
        for entry in cfg.autorun_watch_dirs:
            pattern = _normalize_pattern(entry)
            if pattern is None:
                kbc.print_err(f"⚠️  [watch] ignoring autorun.watch_dirs entry {entry!r}")
                continue
            target = raw if pattern.split("/")[0] == "raw" else edit
            if pattern not in target:
                target.append(pattern)
        if "raw/*/unsorted" in raw and CATCH_ALL_INBOX not in raw:
            raw.append(CATCH_ALL_INBOX)
        return cls(tuple(raw), tuple(edit), tuple(cfg.ingest_ignore_globs))

    def prefixes(self) -> list[str]:
        """Folders to observe: the static part of every pattern, outermost only."""
        out: list[str] = []
        for prefix in sorted({_static_prefix(p) for p in (*self.raw_patterns, *self.edit_patterns)}):
            if not any(prefix == o or prefix.startswith(o + "/") for o in out):
                out.append(prefix)
        return out

    def is_raw(self, rel: str) -> bool:
        name = rel.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatchcase(name, glob) for glob in self.ignore_globs):
            return False
        return _under(rel, self.raw_patterns)

    def is_edit(self, rel: str) -> bool:
        if not rel.endswith(".md") or self.is_generated(rel):
            return False
        return _under(rel, self.edit_patterns)

    def is_edit_dir(self, rel: str) -> bool:
        if self.is_generated(rel + "/"):
            return False
        return _under(rel + "/x.md", self.edit_patterns)

    @staticmethod
    def is_generated(rel: str) -> bool:
        return rel in GENERATED_FILES or rel.startswith(GENERATED_DIRS)


def _rel(root: Path, path: str | Path) -> str | None:
    try:
        return PurePath(path).relative_to(root).as_posix()
    except ValueError:
        return None


def _iter_files(root: Path, prefixes: Iterable[str], pattern: str = "*") -> Iterator[Path]:
    for prefix in prefixes:
        base = root / prefix
        if base.is_dir():
            for path in sorted(base.rglob(pattern)):
                if path.is_file():
                    yield path


def _raw_files(root: Path, scope: WatchScope) -> list[Path]:
    prefixes = WatchScope(scope.raw_patterns, ()).prefixes()
    return [p for p in _iter_files(root, prefixes) if scope.is_raw(_rel(root, p) or "")]


def _edit_snapshot(root: Path, scope: WatchScope) -> dict[str, tuple[float, int]]:
    prefixes = WatchScope((), scope.edit_patterns).prefixes()
    snapshot: dict[str, tuple[float, int]] = {}
    for path in _iter_files(root, prefixes, "*.md"):
        rel = _rel(root, path)
        if rel is None or not scope.is_edit(rel):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        snapshot[rel] = (st.st_mtime, st.st_size)
    return snapshot


class ChangeQueue:
    """Debounced changes, fed by watchdog's thread or by polling.

    Every access goes through the lock: watchdog dispatches events from its
    own thread while the main loop drains the queue.
    """

    def __init__(self, root: Path, scope: WatchScope) -> None:
        self.root = root
        self.scope = scope
        self._lock = threading.Lock()
        self._raw: dict[Path, float] = {}
        self._edit_at = 0.0

    def touch_raw(self, paths: Iterable[Path], now: float) -> None:
        with self._lock:
            for path in paths:
                self._raw[Path(path)] = now

    def touch_edit(self, now: float) -> None:
        with self._lock:
            self._edit_at = now

    def on_event(
        self,
        event_type: str,
        src: str,
        dest: str = "",
        *,
        is_directory: bool = False,
        now: float | None = None,
    ) -> None:
        """Route one file-system event (watchdog's event_type names)."""
        now = time.time() if now is None else now
        if event_type not in ("created", "modified", "moved", "deleted", "closed"):
            return
        if event_type != "deleted":
            target = dest if event_type == "moved" else src
            self.touch_raw(self._raw_candidates(target, is_directory, event_type), now)
        if event_type == "closed":
            return
        for path in (src, dest):
            rel = _rel(self.root, path) if path else None
            if rel is None:
                continue
            if is_directory:
                # A page folder moved or removed; new folders bring their
                # own file events.
                edited = event_type in ("moved", "deleted") and self.scope.is_edit_dir(rel)
            else:
                edited = self.scope.is_edit(rel)
            if edited:
                self.touch_edit(now)

    def _raw_candidates(self, target: str, is_directory: bool, event_type: str) -> list[Path]:
        rel = _rel(self.root, target) if target else None
        if rel is None:
            return []
        if not is_directory:
            return [Path(target)] if self.scope.is_raw(rel) else []
        # A folder dropped into the inbox brings files that emit no events.
        if event_type not in ("created", "moved") or not _under(rel + "/x", self.scope.raw_patterns):
            return []
        return [
            p for p in Path(target).rglob("*")
            if p.is_file() and self.scope.is_raw(_rel(self.root, p) or "")
        ]

    def pop_ready_raw(self, now: float, debounce: float) -> list[Path]:
        with self._lock:
            ready = sorted(p for p, t in self._raw.items() if now - t >= debounce)
            for path in ready:
                del self._raw[path]
        return ready

    def pop_edit(self, now: float, debounce: float) -> bool:
        with self._lock:
            if self._edit_at and now - self._edit_at >= debounce:
                self._edit_at = 0.0
                return True
        return False


@dataclass(frozen=True)
class WatchOptions:
    debounce_raw: float = 5.0
    debounce_knowledge: float = 2.0
    do_reindex: bool = True
    auto_nlp: bool = True
    auto_lint: bool = True
    auto_reindex: bool = True
    verbose: bool = False


def _run(cmd: list[str], *, root: Path, verbose: bool) -> None:
    if verbose:
        print(f"[watch] {' '.join(cmd)}")
    subprocess.run(cmd, check=False, cwd=str(root))


def _run_ingest(root: Path, paths: list[Path], *, nlp: bool, verbose: bool) -> None:
    for start in range(0, len(paths), INGEST_BATCH):
        cmd = [kbc.detect_python_executable(), str(SCRIPT_DIR / "kb_ingest.py"),
               "--root", str(root)]
        if not nlp:
            cmd.append("--no-nlp")
        cmd.extend(str(p) for p in paths[start:start + INGEST_BATCH])
        _run(cmd, root=root, verbose=verbose)


def _run_quick_lint(root: Path, *, verbose: bool) -> None:
    _run([kbc.detect_python_executable(), str(SCRIPT_DIR / "kb_lint.py"),
          "--root", str(root), "--quick"], root=root, verbose=verbose)


def _run_reindex(root: Path, *, verbose: bool) -> None:
    # The watcher ingests raw files itself, so reindex skips its ingest step.
    _run([kbc.detect_python_executable(), str(SCRIPT_DIR / "kb_reindex.py"),
          "--root", str(root), "--no-ingest"], root=root, verbose=verbose)


def handle_changes(root: Path, ready_raw: list[Path], edit_due: bool, opts: WatchOptions) -> None:
    """Ingest ready raw files in one batch, lint, then reindex at most once."""
    paths = [p for p in ready_raw if p.is_file()]
    ingested = bool(paths) and _running
    if ingested:
        print(f"[watch] ingesting {len(paths)} file(s)")
        _run_ingest(root, paths, nlp=opts.auto_nlp, verbose=opts.verbose)
    if edit_due and opts.auto_lint and _running:
        _run_quick_lint(root, verbose=opts.verbose)
    if opts.do_reindex and _running and (ingested or (edit_due and opts.auto_reindex)):
        _run_reindex(root, verbose=opts.verbose)


def watch_with_watchdog(root: Path, scope: WatchScope, opts: WatchOptions) -> int:
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-untyped]
        from watchdog.observers import Observer  # type: ignore[import-untyped]
    except ImportError:
        return -1  # signal caller to use polling fallback

    queue = ChangeQueue(root, scope)

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            queue.on_event(
                event.event_type,
                str(event.src_path),
                str(getattr(event, "dest_path", "") or ""),
                is_directory=event.is_directory,
            )

    observer = Observer()
    for prefix in scope.prefixes():
        if (root / prefix).is_dir():
            observer.schedule(Handler(), str(root / prefix), recursive=True)
    observer.start()
    # Files that arrived while no watcher ran emit no events.
    queue.touch_raw(_raw_files(root, scope), time.time())
    print(f"[watch] watching {root} (Ctrl+C to stop)")

    try:
        while _running:
            now = time.time()
            handle_changes(
                root,
                queue.pop_ready_raw(now, opts.debounce_raw),
                queue.pop_edit(now, opts.debounce_knowledge),
                opts,
            )
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
    scope: WatchScope | None = None,
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
    for p in _raw_files(root, scope or WatchScope()):
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


def watch_polling(root: Path, scope: WatchScope, opts: WatchOptions) -> int:
    """Polling fallback when watchdog is not installed."""
    print(f"[watch] (polling fallback) watching {root}")
    seen: dict[str, _PollEntry] = {}
    queue = ChangeQueue(root, scope)
    edits = _edit_snapshot(root, scope)
    while _running:
        now = time.time()
        ready = _poll_once(root, seen, now, opts.debounce_raw, scope)
        current = _edit_snapshot(root, scope)
        if current != edits:
            queue.touch_edit(now)
        edits = current
        handle_changes(root, ready, queue.pop_edit(now, opts.debounce_knowledge), opts)
        # Drop tracking for files ingest moved away so the map stays small.
        for key in [k for k, e in seen.items() if e.processed and not Path(k).exists()]:
            del seen[key]
        time.sleep(POLL_SECONDS)
    return 0


def _seconds(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    global _running
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — file watcher")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-reindex", action="store_true", help="never run kb_reindex")
    parser.add_argument(
        "--debounce-raw",
        type=float,
        default=None,
        help="Seconds a new raw file must stay unchanged (default from config or 5)",
    )
    parser.add_argument(
        "--debounce-knowledge",
        type=float,
        default=None,
        help="Seconds to wait after knowledge edits (default from config or 2)",
    )
    args = parser.parse_args(argv)

    # A relative --root must not follow the children's cwd (phantom bases).
    root = (args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        kbc.print_err(
            f"❌ [watch] {root} is not a knowledge base (no kb.config.yml); "
            "pass --root <base>"
        )
        return 2
    cfg = kbc.load_config(root)
    if not cfg.autorun_watch_enabled:
        print("[watch] disabled in kb.config.yml (autorun.watch_enabled: false)")
        return 0

    scope = WatchScope.from_config(cfg)
    if not any((root / prefix).is_dir() for prefix in scope.prefixes()):
        print(f"[watch] none of autorun.watch_dirs exists in {root}; nothing to watch")
        return 1
    opts = WatchOptions(
        debounce_raw=args.debounce_raw if args.debounce_raw is not None
        else _seconds(cfg.autorun.get("debounce_raw_seconds"), 5.0),
        debounce_knowledge=args.debounce_knowledge if args.debounce_knowledge is not None
        else _seconds(cfg.autorun.get("debounce_knowledge_seconds"), 2.0),
        do_reindex=not args.no_reindex,
        auto_nlp=cfg.autorun_auto_nlp,
        auto_lint=cfg.autorun_auto_lint_on_change,
        auto_reindex=cfg.autorun_auto_reindex_on_change,
        verbose=args.verbose,
    )

    _running = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(kbc.kb_lock(root, "watch", timeout=0))
        except kbc.KbLockTimeout:
            kbc.print_err(f"❌ [watch] another watcher is already running for {root}")
            return 1
        except OSError as exc:
            kbc.print_err(f"⚠️  [watch] no single-instance lock ({exc}); continuing")
        code = watch_with_watchdog(root, scope, opts)
        if code == -1:
            print("[watch] watchdog not installed; using polling fallback")
            code = watch_polling(root, scope, opts)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
