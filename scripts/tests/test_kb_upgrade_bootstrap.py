"""Tests for the thin updater shipped inside deployed knowledge bases."""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_PATH = REPO_ROOT / "knowledge-base" / "scripts" / "kb_update.py"


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("kb_upgrade_bootstrap", BOOTSTRAP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_is_shipped_with_deployed_scripts() -> None:
    assert BOOTSTRAP_PATH.is_file()


def test_bootstrap_discovers_sibling_source_repo(tmp_path: Path) -> None:
    bootstrap = _load_bootstrap()
    main = tmp_path / "main"
    source_repo = main / "ai-knowledge-engine"
    (source_repo / "scripts").mkdir(parents=True)
    (source_repo / "scripts" / "kb_upgrade.py").write_text(
        "# central updater\n", encoding="utf-8"
    )
    (source_repo / "knowledge-base").mkdir()
    (source_repo / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    kb_root = main / "brain-my-ai" / "kb-demo"
    kb_root.mkdir(parents=True)
    (kb_root / "kb.config.yml").write_text("", encoding="utf-8")

    discovered = bootstrap.find_source_repo(
        explicit=None,
        start=kb_root,
        script_path=kb_root / "scripts" / "kb_update.py",
        environment={},
    )

    assert discovered == source_repo


def test_bootstrap_builds_current_kb_command(tmp_path: Path) -> None:
    bootstrap = _load_bootstrap()
    source_repo = tmp_path / "ai-knowledge-engine"
    central = source_repo / "scripts" / "kb_upgrade.py"
    central.parent.mkdir(parents=True)
    central.write_text("# central updater\n", encoding="utf-8")
    (source_repo / "knowledge-base").mkdir()
    (source_repo / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    kb_root = tmp_path / "kb-demo"
    kb_root.mkdir()
    (kb_root / "kb.config.yml").write_text("", encoding="utf-8")

    command = bootstrap.build_command(
        source_repo=source_repo,
        kb_root=kb_root,
        passthrough=["--dry-run"],
    )

    assert command[1] == str(central)
    assert command[2:] == ["--kb-root", str(kb_root), "--dry-run"]
