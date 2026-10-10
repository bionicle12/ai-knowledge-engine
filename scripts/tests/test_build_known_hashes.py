"""Tests for scripts/build_known_hashes.py."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import build_known_hashes as bkh
import kb_upgrade as up

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

LEGACY_UPGRADER = '''\
VIEW_BLOCK_BEGIN = "<!-- AI-KE:VIEW:BEGIN — managed by kb_upgrade.py -->"
VIEW_BLOCK_END = "<!-- AI-KE:VIEW:END -->"
VIEW_BLOCK = f"""\\
{VIEW_BLOCK_BEGIN}
## Viewer (0.1)
{VIEW_BLOCK_END}"""
'''


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True)


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _index(body: str) -> str:
    begin, end = up.block_markers("INDEX")
    return f"{begin}\n{body}\n{end}"


@pytest.fixture
def history(tmp_path: Path) -> Path:
    repo = tmp_path / "engine"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "VERSION", "0.1.0\n")
    _write(repo, "knowledge-base/scripts/kb_x.py", "x = 1\n")
    _write(repo, "knowledge-base/scripts/tests/test_x.py", "ignored\n")
    _write(repo, "knowledge-base/templates/AGENTS.md.template", f"# A\n\n{_index('rules v1')}\n")
    _write(repo, "scripts/kb_upgrade.py", LEGACY_UPGRADER)
    _commit(repo, "0.1.0")
    _write(repo, "knowledge-base/scripts/kb_x.py", "x = 2  # dev\n")
    _commit(repo, "dev work after 0.1.0")
    _write(repo, "VERSION", "0.2.0\n")
    _write(repo, "knowledge-base/scripts/kb_x.py", "x = 3\n")
    _commit(repo, "0.2.0")
    return repo


def test_registry_lists_every_committed_version_and_its_releases(history: Path):
    data = bkh.build_registry(history)
    kb_x = data["files"]["knowledge-base/scripts/kb_x.py"]

    assert kb_x == {
        up.content_digest(b"x = 1\n"): ["0.1.0"],
        up.content_digest(b"x = 2  # dev\n"): [],   # committed, never released
        up.content_digest(b"x = 3\n"): ["0.2.0"],
    }
    assert "knowledge-base/scripts/tests/test_x.py" not in data["files"]
    assert data["blocks"]["INDEX"] == {up.block_digest(_index("rules v1")): ["0.1.0", "0.2.0"]}
    view = up.block_markers("VIEW")
    legacy = f"{view[0]}\n## Viewer (0.1)\n{view[1]}"
    assert data["blocks"]["VIEW"] == {up.block_digest(legacy): ["0.1.0", "0.2.0"]}


def test_working_tree_is_the_release_of_a_new_version(history: Path):
    _write(history, "VERSION", "0.3.0\n")
    _write(history, "knowledge-base/scripts/kb_x.py", "x = 4\r\n")
    _write(history, "knowledge-base/templates/AGENTS.md.template", f"# A\n\n{_index('rules v3')}\n")

    data = bkh.build_registry(history)

    assert data["files"]["knowledge-base/scripts/kb_x.py"][up.content_digest(b"x = 4\n")] == ["0.3.0"]
    assert data["blocks"]["INDEX"][up.block_digest(_index("rules v3"))] == ["0.3.0"]


def test_uncommitted_edits_under_a_released_version_are_known_but_not_released(history: Path):
    _write(history, "knowledge-base/scripts/kb_x.py", "x = 5\n")
    data = bkh.build_registry(history)
    assert data["files"]["knowledge-base/scripts/kb_x.py"][up.content_digest(b"x = 5\n")] == []


def test_cli_writes_a_registry_kb_upgrade_can_read(history: Path, tmp_path: Path):
    output = tmp_path / "known.json"

    assert bkh.main(["--repo", str(history), "--output", str(output)]) == 0

    known = up.load_known_hashes(output)
    assert known.file_versions("knowledge-base/scripts/kb_x.py", up.content_digest(b"x = 1\n")) == ["0.1.0"]
    assert json.loads(output.read_text(encoding="utf-8"))["generated_by"] == "scripts/build_known_hashes.py"


def test_cli_refuses_a_folder_without_git_history(tmp_path: Path, capsys):
    assert bkh.main(["--repo", str(tmp_path), "--output", str(tmp_path / "k.json")]) == 2
    assert "not a git checkout" in capsys.readouterr().err
    assert not (tmp_path / "k.json").exists()
