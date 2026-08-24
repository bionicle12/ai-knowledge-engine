"""Make the ai_skills_fixer package importable from the sibling scripts dir."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def _isolated_store_env(tmp_path, monkeypatch):
    """Keep every test away from the developer's real store.

    The default store root resolves to a sibling of the repository, which
    exists on real machines; tests must never read or write it.
    """
    monkeypatch.setenv(
        "AI_SKILLS_FIXER_STORE_ROOT", str(tmp_path / "default-store")
    )


@pytest.fixture
def directory_link():
    """Create a real directory link supported by the current platform."""
    def create(link: Path, target: Path) -> None:
        if os.name == "nt":
            proc = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                pytest.skip(f"cannot create Windows junction: {proc.stderr.strip()}")
        else:
            link.symlink_to(target, target_is_directory=True)

    return create
