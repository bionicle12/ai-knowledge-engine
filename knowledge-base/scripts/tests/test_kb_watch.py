"""Tests for kb_watch polling fallback logic."""
from __future__ import annotations

import os
from pathlib import Path

import kb_watch as kw


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
