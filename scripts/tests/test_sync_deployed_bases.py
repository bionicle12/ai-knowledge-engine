"""Tests for sync_deployed_bases — now a deprecated wrapper over kb_upgrade."""
from __future__ import annotations

from pathlib import Path

import yaml

import kb_upgrade as up
import sync_deployed_bases as sdb

BASE_CONFIG = """\
instructions_version: "0.12.0"
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
    (base / "AGENTS.md").write_text("# Studio\n", encoding="utf-8")
    return base


def test_target_is_required(monkeypatch, capsys):
    monkeypatch.delenv(sdb.ENV_TARGET_VAR, raising=False)
    assert sdb.main([]) == 2
    err = capsys.readouterr().err
    assert sdb.ENV_TARGET_VAR in err
    assert "[DEPRECATED]" in err


def test_target_can_come_from_env(monkeypatch, tmp_path: Path, capsys):
    make_deployed_base(tmp_path)
    monkeypatch.setenv(sdb.ENV_TARGET_VAR, str(tmp_path))
    assert sdb.main(["--dry-run"]) == 0
    assert "kb_upgrade.py" in capsys.readouterr().err


def test_local_patches_survive_and_the_version_waits(tmp_path: Path):
    """Q2: the old helper copied over adapted scripts and bumped the version."""
    base = make_deployed_base(tmp_path)
    patched = base / "scripts" / "kb_ingest.py"
    patched.write_text("# MY IMPORTANT LOCAL PATCH\n", encoding="utf-8")

    assert sdb.main([str(tmp_path)]) == 2

    assert patched.read_text(encoding="utf-8") == "# MY IMPORTANT LOCAL PATCH\n"
    assert (base / "scripts" / "kb_ingest.py.new").is_file()
    cfg = yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["instructions_version"] == "0.12.0"
    assert cfg["autorun"]["watch_enabled"] is True
    # Everything that does not depend on the customized file is installed; the
    # rest (scripts importing or running kb_ingest.py, docs describing them, …)
    # waits for it. Which files those are depends on the engine's code, so the
    # check is about consistency, not a fixed list.
    after = {plan.name: plan for plan in up.collect_plans(base, "0.12.0", False)}
    assert after["kb_ingest.py"].state == "customized"
    assert after["kb_common.py"].state == "up_to_date"
    assert after["kb_viewer/app.js"].state in ("up_to_date", "held")
    for name, plan in after.items():
        if name == "kb_ingest.py":
            continue
        assert plan.state == "up_to_date" or (
            plan.state == "held" and plan.held_by == "kb_ingest.py" and not plan.dst.exists()
        ), (name, plan.state, plan.held_by)


def test_the_engine_layer_is_installed_like_kb_upgrade_does(tmp_path: Path):
    base = make_deployed_base(tmp_path)

    assert sdb.main([str(tmp_path)]) == 0

    assert (base / "scripts" / "kb_export.py").is_file()
    assert (base / "scripts" / "kb_import.py").is_file()
    assert (base / "shell" / "export.sh").is_file()
    assert (base / "shell" / "import.sh").is_file()
    # Launchers land at the base root, where finalize.sh puts them.
    for launcher in ("export.command", "import.command", "export.bat", "import.bat"):
        assert (base / launcher).is_file(), launcher
    assert (base / "requirements-media.txt").is_file()
    cfg = yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))
    assert cfg["instructions_version"] == up.get_repo_version()
    assert cfg["heal"]["last_run"]["version"] == up.get_repo_version()
    # What the old sync_deployed_bases.py patched in by hand now comes from
    # heal's media-sync-sections migration, which the upgrade runs.
    assert "media" in cfg and cfg["sync"]["label"] == base.name
    assert all(
        (base / "sync" / d).is_dir() for d in ("inbox", "outbox", "applied", "backups", "reports")
    )


def test_every_base_in_the_folder_is_upgraded(tmp_path: Path):
    make_deployed_base(tmp_path, "work-kb")
    make_deployed_base(tmp_path, "studio-kb")

    assert sdb.main([str(tmp_path), "--dry-run"]) == 0
    assert [base.name for base in sdb.find_bases(tmp_path)] == ["studio-kb", "work-kb"]


def test_dry_run_writes_nothing(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    before = (base / "kb.config.yml").read_text(encoding="utf-8")

    sdb.main([str(tmp_path), "--dry-run"])

    assert (base / "kb.config.yml").read_text(encoding="utf-8") == before
    assert not (base / "scripts" / "kb_export.py").exists()
    assert (base / "AGENTS.md").read_text(encoding="utf-8") == "# Studio\n"


def test_knowledge_content_is_never_touched(tmp_path: Path):
    base = make_deployed_base(tmp_path)
    page = base / "knowledge" / "domain" / "x.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# X\n\nMine.\n", encoding="utf-8")

    sdb.main([str(tmp_path)])

    assert page.read_text(encoding="utf-8") == "# X\n\nMine.\n"
