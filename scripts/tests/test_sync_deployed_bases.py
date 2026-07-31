"""Tests for sync_deployed_bases — the maintenance helper for finalized bases."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import sync_deployed_bases as sdb

BASE_CONFIG = """\
instructions_version: "0.10.0"
knowledge_base:
  name: music-kb
  mode: default

autorun:
  watch_enabled: true
"""


def make_deployed_base(root: Path, name: str = "studio-kb") -> Path:
    base = root / name
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    (base / "shell").mkdir(parents=True, exist_ok=True)
    (base / "review" / "needs-ai-decision").mkdir(parents=True, exist_ok=True)
    (base / "kb.config.yml").write_text(BASE_CONFIG, encoding="utf-8")
    return base


def test_target_is_required(monkeypatch, capsys):
    monkeypatch.delenv(sdb.ENV_TARGET_VAR, raising=False)
    assert sdb.main([]) == 2
    assert sdb.ENV_TARGET_VAR in capsys.readouterr().err


def test_target_can_come_from_env(monkeypatch, tmp_path: Path):
    make_deployed_base(tmp_path)
    monkeypatch.setenv(sdb.ENV_TARGET_VAR, str(tmp_path))
    assert sdb.main(["--dry-run"]) == 0


def test_merge_layer_is_installed(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    sdb.main([str(tmp_path)])

    assert (base / "scripts" / "kb_export.py").is_file()
    assert (base / "scripts" / "kb_import.py").is_file()
    assert (base / "shell" / "export.sh").is_file()
    assert (base / "shell" / "import.sh").is_file()
    # Launchers land at the base root, where finalize.sh puts them.
    for launcher in ("export.command", "import.command", "export.bat", "import.bat"):
        assert (base / launcher).is_file(), launcher
    for sub in ("inbox", "outbox", "applied", "backups", "reports"):
        assert (base / "sync" / sub).is_dir(), sub
    assert (base / "review" / "needs-merge").is_dir()


def test_sync_config_section_is_added_once(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    sdb.main([str(tmp_path)])

    cfg = yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["sync"]["label"] == "studio-kb"
    assert cfg["sync"]["import"]["strategy"] == "safe"
    assert cfg["autorun"]["watch_enabled"] is True, "existing config must survive"

    before = (base / "kb.config.yml").read_text(encoding="utf-8")
    sdb.main([str(tmp_path)])
    assert (base / "kb.config.yml").read_text(encoding="utf-8") == before


def test_existing_sync_section_is_left_alone(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    (base / "kb.config.yml").write_text(
        BASE_CONFIG + '\nsync:\n  label: "my-own-label"\n', encoding="utf-8"
    )
    sdb.main([str(tmp_path)])

    cfg = yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["sync"]["label"] == "my-own-label"


def test_dry_run_writes_nothing(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    before = (base / "kb.config.yml").read_text(encoding="utf-8")

    sdb.main([str(tmp_path), "--dry-run"])

    assert (base / "kb.config.yml").read_text(encoding="utf-8") == before
    assert not (base / "sync").exists()
    assert not (base / "scripts" / "kb_export.py").exists()


def test_label_defaults_to_the_base_folder_name(tmp_path: Path):
    """Two bases synced from one repo must not end up with the same label."""
    make_deployed_base(tmp_path, "work-kb")
    make_deployed_base(tmp_path, "studio-kb")
    sdb.main([str(tmp_path)])

    labels = {
        yaml.safe_load((tmp_path / name / "kb.config.yml").read_text(encoding="utf-8"))
        ["sync"]["label"]
        for name in ("work-kb", "studio-kb")
    }
    assert labels == {"work-kb", "studio-kb"}


def test_knowledge_content_is_never_touched(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    page = base / "knowledge" / "domain" / "x.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# X\n\nMine.\n", encoding="utf-8")

    sdb.main([str(tmp_path)])

    assert page.read_text(encoding="utf-8") == "# X\n\nMine.\n"
