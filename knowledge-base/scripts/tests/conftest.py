"""Pytest configuration: ensure parent scripts/ dir is importable."""
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def _isolate_kb_environment(monkeypatch):
    """Tests never inherit a caller's pipeline lock or interpreter choice.

    kb_common.kb_lock shares a lock with child processes through
    ``KB_LOCK_<NAME>`` and shell/_kbpy.sh honours ``KB_PYTHON``; a test run
    started from inside a locked pipeline (e.g. a git hook) must not see them.
    """
    for key in list(os.environ):
        if key.startswith("KB_LOCK_") or key == "KB_PYTHON":
            monkeypatch.delenv(key, raising=False)
