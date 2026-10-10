"""Tests for kb_watch: event routing, polling fallback, autorun keys and
the shell/watcher.sh wrapper."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import kb_common as kbc
import kb_route
import kb_watch as kw

SHELL_DIR = Path(__file__).resolve().parents[2] / "shell"


def _make_raw_file(root: Path, name: str = "doc.txt", content: bytes = b"hello") -> Path:
    unsorted = root / "raw" / "documents" / "unsorted"
    unsorted.mkdir(parents=True, exist_ok=True)
    p = unsorted / name
    p.write_bytes(content)
    return p


def test_poll_once_new_file_not_ready_immediately(tmp_path: Path):
    _make_raw_file(tmp_path)
    seen: dict[str, kw._PollEntry] = {}
    ready = kw._poll_once(tmp_path, seen, now=1000.0, debounce_raw=5)
    assert ready == []
    assert len(seen) == 1


def test_poll_once_stable_file_becomes_ready_once(tmp_path: Path):
    p = _make_raw_file(tmp_path)
    seen: dict[str, kw._PollEntry] = {}
    kw._poll_once(tmp_path, seen, now=1000.0, debounce_raw=5)
    # Still inside the debounce window
    assert kw._poll_once(tmp_path, seen, now=1003.0, debounce_raw=5) == []
    # Window elapsed, file unchanged → ready exactly once
    ready = kw._poll_once(tmp_path, seen, now=1006.0, debounce_raw=5)
    assert ready == [p]
    # Marked processed: never returned again while unchanged
    assert kw._poll_once(tmp_path, seen, now=2000.0, debounce_raw=5) == []


def test_poll_once_modification_resets_debounce(tmp_path: Path):
    p = _make_raw_file(tmp_path, content=b"part")
    seen: dict[str, kw._PollEntry] = {}
    kw._poll_once(tmp_path, seen, now=1000.0, debounce_raw=5)
    # File grows while the window is still open (a copy in progress)
    p.write_bytes(b"part-two-much-longer")
    ready = kw._poll_once(tmp_path, seen, now=1006.0, debounce_raw=5)
    assert ready == []  # (mtime, size) changed → stability clock restarted
    ready = kw._poll_once(tmp_path, seen, now=1012.0, debounce_raw=5)
    assert ready == [p]


def test_poll_once_processed_file_reappears_after_change(tmp_path: Path):
    """A failed ingest leaves the file behind; only a new change re-queues it."""
    p = _make_raw_file(tmp_path, content=b"v1")
    seen: dict[str, kw._PollEntry] = {}
    kw._poll_once(tmp_path, seen, now=1000.0, debounce_raw=5)
    assert kw._poll_once(tmp_path, seen, now=1006.0, debounce_raw=5) == [p]
    # Unchanged → stays quiet (no retry loop)
    assert kw._poll_once(tmp_path, seen, now=1100.0, debounce_raw=5) == []
    # User replaces the file → tracked as a fresh candidate
    p.write_bytes(b"v2 with different size")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 10))
    assert kw._poll_once(tmp_path, seen, now=1200.0, debounce_raw=5) == []
    assert kw._poll_once(tmp_path, seen, now=1206.0, debounce_raw=5) == [p]


def test_poll_once_ignores_directories(tmp_path: Path):
    unsorted = tmp_path / "raw" / "documents" / "unsorted"
    (unsorted / "subdir").mkdir(parents=True)
    seen: dict[str, kw._PollEntry] = {}
    assert kw._poll_once(tmp_path, seen, now=1000.0, debounce_raw=5) == []
    assert seen == {}


# ---------------------------------------------------------------------------
# Event routing, scope and autorun keys
# ---------------------------------------------------------------------------


def _base(root: Path, config_extra: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n  mode: default\n" + config_extra, encoding="utf-8"
    )
    (root / "raw" / "documents" / "unsorted").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "domain").mkdir(parents=True, exist_ok=True)
    return root


def _page(root: Path, rel: str, title: str = "Page") -> Path:
    page = root / "knowledge" / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    kbc.write_frontmatter_file(page, {"source": "manual", "lifecycle": "evolving"}, f"# {title}\n")
    return page


def test_generated_routing_pages_never_queue_an_edit(tmp_path: Path):
    """kb_route output under knowledge/ re-triggered lint + reindex forever (C1)."""
    root = _base(tmp_path)
    queue = kw.ChangeQueue(root, kw.WatchScope())
    for rel in ("knowledge/routing/domain.md", "knowledge/routing-table.md"):
        for event in ("created", "modified", "deleted"):
            queue.on_event(event, str(root / rel), now=100.0)
    queue.on_event("moved", str(root / "knowledge/routing/.domain.md.tmp"),
                   str(root / "knowledge/routing/domain.md"), now=100.0)
    assert queue.pop_edit(200.0, 2) is False
    queue.on_event("modified", str(root / "knowledge/domain/a.md"), now=100.0)
    assert queue.pop_edit(200.0, 2) is True


def test_polling_watcher_reacts_once_to_an_edit_not_to_its_own_reindex(
    tmp_path: Path, monkeypatch
):
    """Polling ignored knowledge/ entirely; with it watched, the reindex's own
    routing writes must not start another round (C1, M12)."""
    root = _base(tmp_path)
    _page(root, "domain/a.md")
    kb_route.generate_routes(root)
    calls: list[str] = []
    monkeypatch.setattr(kw, "_run_quick_lint", lambda root, **_: calls.append("lint"))

    def fake_reindex(root: Path, **_) -> None:
        calls.append("reindex")
        kb_route.generate_routes(root)

    monkeypatch.setattr(kw, "_run_reindex", fake_reindex)
    ticks: list[int] = []

    def fake_sleep(_seconds: float) -> None:
        ticks.append(1)
        if len(ticks) == 1:
            _page(root, "domain/b.md")  # the owner adds a page
        if len(ticks) >= 6:
            kw._running = False

    monkeypatch.setattr(kw.time, "sleep", fake_sleep)
    monkeypatch.setattr(kw, "_running", True)

    kw.watch_polling(root, kw.WatchScope(), kw.WatchOptions(debounce_knowledge=0))

    assert calls == ["lint", "reindex"]
    assert "[[domain/b]]" in (root / "knowledge/routing/domain.md").read_text(encoding="utf-8")


def test_created_moved_and_deleted_pages_count_as_edits(tmp_path: Path):
    """Only on_modified was handled: atomic saves (temp + rename), new and
    deleted pages never reached lint/reindex (M12)."""
    root = _base(tmp_path)
    queue = kw.ChangeQueue(root, kw.WatchScope())
    page = str(root / "knowledge/domain/a.md")
    for event in (
        ("created", page, ""),
        ("moved", str(root / "knowledge/domain/.a.md.swp"), page),
        ("deleted", page, ""),
        ("moved", page, str(root / "knowledge/_archive/a.md")),
    ):
        queue.on_event(event[0], event[1], event[2], now=100.0)
        assert queue.pop_edit(200.0, 2) is True, event
    queue.on_event("moved", str(root / "knowledge/old"), str(root / "knowledge/_archive/old"),
                   is_directory=True, now=100.0)
    assert queue.pop_edit(200.0, 2) is True
    queue.on_event("modified", str(root / "knowledge/domain/image.png"), now=100.0)
    queue.on_event("opened", page, now=100.0)
    assert queue.pop_edit(200.0, 2) is False


def test_raw_events_nested_folders_and_ignored_names(tmp_path: Path):
    root = _base(tmp_path)
    unsorted = root / "raw" / "documents" / "unsorted"
    nested = unsorted / "Project X"
    nested.mkdir()
    (nested / "nested.md").write_text("x", encoding="utf-8")
    queue = kw.ChangeQueue(root, kw.WatchScope())
    # A folder moved in brings files that emit no events of their own.
    queue.on_event("moved", str(tmp_path.parent / "Project X"), str(nested),
                   is_directory=True, now=100.0)
    for name in ("report.docx", "~$report.docx", ".DS_Store", "movie.mkv.part"):
        (unsorted / name).write_bytes(b"x")
        queue.on_event("created", str(unsorted / name), now=100.0)
    queue.on_event("deleted", str(unsorted / "gone.txt"), now=100.0)
    queue.on_event("created", str(root / "raw/documents/kept.txt"), now=100.0)
    assert queue.pop_ready_raw(103.0, 5) == []
    assert queue.pop_ready_raw(106.0, 5) == [nested / "nested.md", unsorted / "report.docx"]


def test_poll_once_sees_nested_files_and_skips_ignored_names(tmp_path: Path):
    """rglob('unsorted/*') missed unsorted/Project X/…; .DS_Store went to ingest."""
    root = _base(tmp_path)
    unsorted = root / "raw" / "documents" / "unsorted"
    (unsorted / "Project X").mkdir()
    nested = unsorted / "Project X" / "nested.md"
    nested.write_text("x", encoding="utf-8")
    (unsorted / ".DS_Store").write_bytes(b"x")
    (unsorted / "~$draft.docx").write_bytes(b"x")
    seen: dict[str, kw._PollEntry] = {}
    kw._poll_once(root, seen, now=1000.0, debounce_raw=5)
    assert kw._poll_once(root, seen, now=1006.0, debounce_raw=5) == [nested]


def _fake_watchdog(monkeypatch) -> list[str]:
    import types

    scheduled: list[str] = []

    class FakeObserver:
        def schedule(self, handler, path, recursive=False):  # noqa: ARG002
            scheduled.append(path)

        def start(self):
            pass

        def stop(self):
            pass

        def join(self, timeout=None):  # noqa: ARG002
            pass

    events = types.ModuleType("watchdog.events")
    events.FileSystemEventHandler = object
    observers = types.ModuleType("watchdog.observers")
    observers.Observer = FakeObserver
    monkeypatch.setitem(sys.modules, "watchdog", types.ModuleType("watchdog"))
    monkeypatch.setitem(sys.modules, "watchdog.events", events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers)
    return scheduled


def test_watchdog_mode_ingests_files_waiting_at_start(tmp_path: Path, monkeypatch):
    """Files dropped while no watcher ran emit no events; the watchdog mode
    never scanned raw/ at start (E, M12)."""
    root = _base(tmp_path)
    waiting = _make_raw_file(root, "waiting.txt")
    scheduled = _fake_watchdog(monkeypatch)
    batches: list[list[Path]] = []
    monkeypatch.setattr(kw, "handle_changes",
                        lambda root, ready, edit_due, opts: batches.append(ready))

    def fake_sleep(_seconds: float) -> None:
        kw._running = False

    monkeypatch.setattr(kw.time, "sleep", fake_sleep)
    monkeypatch.setattr(kw, "_running", True)

    assert kw.watch_with_watchdog(root, kw.WatchScope(), kw.WatchOptions(debounce_raw=0)) == 0
    assert batches == [[waiting]]
    assert scheduled == [str(root / "knowledge"), str(root / "raw")]


def test_handle_changes_batches_ingest_and_honours_autorun_keys(tmp_path: Path, monkeypatch):
    root = _base(tmp_path)
    files = [_make_raw_file(root, f"doc-{i}.txt") for i in range(3)]
    calls: list[list[str]] = []
    monkeypatch.setattr(kw, "_run", lambda cmd, root, verbose: calls.append(cmd))

    kw.handle_changes(root, files, True, kw.WatchOptions(auto_nlp=False))

    scripts = [Path(cmd[1]).name for cmd in calls]
    assert scripts == ["kb_ingest.py", "kb_lint.py", "kb_reindex.py"]
    assert "--no-nlp" in calls[0]
    assert [c for c in calls[0] if c.endswith(".txt")] == [str(f) for f in files]

    calls.clear()
    kw.handle_changes(root, [], True, kw.WatchOptions(auto_lint=False, auto_reindex=False))
    assert calls == []
    kw.handle_changes(root, files, False, kw.WatchOptions(do_reindex=False))
    assert [Path(cmd[1]).name for cmd in calls] == ["kb_ingest.py"]


def test_watch_dirs_decide_the_scope(tmp_path: Path, capsys):
    root = _base(tmp_path, 'autorun:\n  watch_dirs: ["raw/*/unsorted/", "../outside", "*/x"]\n')
    scope = kw.WatchScope.from_config(kbc.load_config(root))
    assert scope.raw_patterns == ("raw/*/unsorted", "raw/unsorted")
    assert scope.edit_patterns == ()
    assert not scope.is_edit("knowledge/domain/a.md")
    assert scope.is_raw("raw/documents/unsorted/a.txt")
    assert "ignoring autorun.watch_dirs entry '../outside'" in capsys.readouterr().err


def test_main_honours_watch_enabled_false(tmp_path: Path, monkeypatch, capsys):
    root = _base(tmp_path, "autorun:\n  watch_enabled: false\n")

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("watcher started although autorun.watch_enabled is false")

    monkeypatch.setattr(kw, "watch_with_watchdog", must_not_run)
    assert kw.main(["--root", str(root)]) == 0
    assert "watch_enabled: false" in capsys.readouterr().out


def test_main_resolves_a_relative_root_and_requires_a_base(tmp_path: Path, monkeypatch):
    """`--root kbw` with children run in cwd=root created kbw/kbw/… (M11)."""
    base = _base(tmp_path / "kbw")
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    def fake_watch(root: Path, scope: kw.WatchScope, opts: kw.WatchOptions) -> int:
        seen["root"], seen["opts"] = root, opts
        return 0

    monkeypatch.setattr(kw, "watch_with_watchdog", fake_watch)
    assert kw.main(["--root", "kbw"]) == 0
    assert seen["root"] == base.resolve()
    assert seen["root"].is_absolute()

    (tmp_path / "plain").mkdir()
    assert kw.main(["--root", "plain"]) == 2
    assert list((tmp_path / "plain").iterdir()) == []


def test_only_one_watcher_per_base(tmp_path: Path):
    root = _base(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("KB_LOCK_")}
    with kbc.kb_lock(root, "watch", timeout=0):
        result = subprocess.run(
            [sys.executable, str(Path(kw.__file__)), "--root", str(root)],
            capture_output=True, text=True, timeout=60, env=env,
        )
    assert result.returncode == 1
    assert "already running" in result.stderr


# ---------------------------------------------------------------------------
# shell/watcher.sh
# ---------------------------------------------------------------------------

needs_posix_shell = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("ps") is None,
    reason="needs bash, ps and POSIX signals",
)

_SLOW_STOP_WATCHER = """\
import signal, sys, time
def finish(*_):
    time.sleep(1.5)  # finishing the current ingest / reindex
    sys.exit(0)
signal.signal(signal.SIGTERM, finish)
print("ARGS", sys.argv[1:], flush=True)
if "--once" in sys.argv:
    sys.exit(0)
while True:
    time.sleep(0.1)
"""


def _stage_wrapper(root: Path) -> Path:
    (root / "shell").mkdir(parents=True)
    (root / "scripts").mkdir()
    for name in ("watcher.sh", "_kbpy.sh"):
        shutil.copy2(SHELL_DIR / name, root / "shell" / name)
    (root / "scripts" / "kb_watch.py").write_text(_SLOW_STOP_WATCHER, encoding="utf-8")
    return Path(os.path.realpath(root))


def _sh(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KB_PYTHON": sys.executable}
    return subprocess.run(["bash", str(root / "shell" / "watcher.sh"), *args],
                          capture_output=True, text=True, timeout=60, env=env)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@needs_posix_shell
def test_watcher_sh_stop_waits_until_the_watcher_exits(tmp_path: Path):
    """--stop used to report success while the watcher was still running."""
    root = _stage_wrapper(tmp_path / "kb")
    started = _sh(root, "--daemon")
    assert started.returncode == 0, started.stdout + started.stderr
    pid = int((root / ".watcher.pid").read_text(encoding="utf-8"))
    try:
        deadline = time.time() + 10
        log = root / ".watcher.log"
        while "ARGS" not in (log.read_text(encoding="utf-8") if log.exists() else ""):
            assert time.time() < deadline, "stub watcher never started"
            time.sleep(0.05)
        assert "✅ watcher running" in _sh(root, "--status").stdout
        stopped = _sh(root, "--stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert "watcher stopped" in stopped.stdout
        assert not _alive(pid)
        assert not (root / ".watcher.pid").exists()
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


_CHATTY_WATCHER = """\
import time
print("[watch] polling fallback")  # no flush: a daemon's stdout is a file
while True:
    time.sleep(0.1)
"""


@needs_posix_shell
def test_watcher_sh_daemon_log_is_written_while_it_runs(tmp_path: Path):
    """Residual e2e: in --daemon mode stdout is .watcher.log and Python
    block-buffered it, so the watcher's own lines appeared only at exit."""
    root = _stage_wrapper(tmp_path / "kb")
    (root / "scripts" / "kb_watch.py").write_text(_CHATTY_WATCHER, encoding="utf-8")
    started = _sh(root, "--daemon")
    assert started.returncode == 0, started.stdout + started.stderr
    pid = int((root / ".watcher.pid").read_text(encoding="utf-8"))
    try:
        log = root / ".watcher.log"
        deadline = time.time() + 5
        while "[watch] polling fallback" not in (log.read_text(encoding="utf-8") if log.exists() else ""):
            assert _alive(pid), "stub watcher exited"
            assert time.time() < deadline, "the running daemon's line never reached the log"
            time.sleep(0.05)
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


@needs_posix_shell
def test_watcher_sh_never_signals_a_foreign_process(tmp_path: Path):
    """A stale pidfile (reboot, PID reuse) made --stop kill whatever had the PID."""
    root = _stage_wrapper(tmp_path / "kb")
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (root / ".watcher.pid").write_text(str(sleeper.pid), encoding="utf-8")
        assert "not running" in _sh(root, "--status").stdout
        assert "stale pidfile removed" in _sh(root, "--stop").stdout
        time.sleep(0.3)
        assert sleeper.poll() is None
    finally:
        sleeper.kill()
        sleeper.wait()


def _help_flags(main, capsys) -> set[str]:
    with pytest.raises(SystemExit):
        main(["--help"])
    return set(re.findall(r"--[a-z][a-z-]*", capsys.readouterr().out))


def test_autorun_doc_describes_only_real_code(capsys):
    """13_AUTORUN.md embedded drifted copies of watcher.sh / reindex.sh that
    wrote .last_reflection themselves and read a top-level `mode` (I18, I4),
    promised an auto-extract threshold nothing reads (E-H2) and a hand-made
    .git/hooks/post-commit instead of the shipped one."""
    import kb_reflect

    text = (SHELL_DIR.parent / "13_AUTORUN.md").read_text(encoding="utf-8")
    for drifted in ('> ".last_reflection"', "get('mode'", 'case "${1:-}"',
                    "auto-processed", "Access decay", "auto-extract",
                    "chmod +x .git/hooks"):
        assert drifted not in text, drifted
    assert "shell/install-hooks.sh" in text and "shell/hooks/post-commit" in text
    watch_flags = _help_flags(kw.main, capsys)
    valid = {
        "kb_reflect.py": _help_flags(kb_reflect.main, capsys),
        "kb_watch.py": watch_flags,
        "watcher.sh": watch_flags | set(re.findall(
            r"(--[a-z]+)\)", (SHELL_DIR / "watcher.sh").read_text(encoding="utf-8"))),
    }
    token = re.compile(r"[\w-]+\.(?:py|sh)|(?<![\w-])--[a-z][a-z-]*")
    for line in text.splitlines():
        named = [name for name in valid if name in line]
        # A flag belongs to the script named last before it on the line (or
        # to the line's only script); flags of other scripts are not checked.
        owner = named[0] if len(named) == 1 else None
        for item in token.findall(line):
            if not item.startswith("--"):
                owner = item
            elif owner in valid:
                assert item in valid[owner], f"{owner} has no {item}: {line}"


@needs_posix_shell
def test_watcher_sh_passes_options_and_an_absolute_root(tmp_path: Path):
    root = _stage_wrapper(tmp_path / "kb")
    result = _sh(root, "--verbose", "--no-reindex", "--once")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"'--root', '{root}', '--verbose', '--no-reindex'" in result.stdout


def test_catch_all_raw_unsorted_is_an_inbox(tmp_path: Path):
    """Residual E-M8: `raw/*/unsorted` never matched the catch-all raw/unsorted/
    that ingest scans, so a file dropped there was never ingested by the watcher."""
    root = _base(tmp_path)
    (root / "raw" / "unsorted").mkdir()
    misc = root / "raw" / "unsorted" / "misc-note.txt"
    misc.write_text("note\n", encoding="utf-8")
    for extra in ("", 'autorun:\n  watch_dirs: ["raw/*/unsorted/", "knowledge/"]\n'):
        _base(root, extra)
        scope = kw.WatchScope.from_config(kbc.load_config(root))
        assert scope.is_raw("raw/unsorted/x.txt")
        assert scope.is_raw("raw/work/unsorted/x.txt")
        assert kw._raw_files(root, scope) == [misc]
    assert kw.WatchScope().is_raw("raw/unsorted/x.txt")
    # An owner who lists only one category inbox gets only that one.
    _base(root, 'autorun:\n  watch_dirs: ["raw/documents/unsorted/"]\n')
    scope = kw.WatchScope.from_config(kbc.load_config(root))
    assert not scope.is_raw("raw/unsorted/x.txt")
