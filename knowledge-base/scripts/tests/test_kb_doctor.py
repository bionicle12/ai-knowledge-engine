"""Smoke coverage for kb_doctor: the built-in self-test must stay green.

The CI reference pipeline used to run `kb_doctor.py --self-test`; with CI
intentionally disabled this pytest wrapper keeps it part of the local run.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def test_doctor_self_test_passes():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "kb_doctor.py"),
            "--self-test",
            "--skip-nlp",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"kb_doctor self-test failed:\nstdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
    assert "0 error" in result.stdout


def test_doctor_help_runs():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "kb_doctor.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
