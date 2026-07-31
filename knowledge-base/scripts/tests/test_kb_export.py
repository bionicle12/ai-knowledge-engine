"""Tests for kb_export — packing a transferable knowledge bundle."""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import pytest
import yaml

import kb_export
import kb_ingest

CONFIG = """
instructions_version: "0.11.0"
knowledge_base:
  name: test-kb
  mode: default
  roles:
    primary: "Battle rap producer"
language_policy:
  primary: ru
nlp:
  enabled: false
entities:
  plugins: {}
sync:
  label: studio-laptop
""".strip()


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "kb.config.yml").write_text(CONFIG + "\n", encoding="utf-8")
    kb_ingest.main(["--root", str(tmp_path), "--init-dirs"])
    return tmp_path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def seed(root: Path) -> None:
    write(root / "knowledge/domain/plugins.md", """
---
title: "Plugins"
importance: 7
tags: [plugins]
last_verified: 2026-07-01
---

# Plugins

Serum, FabFilter.
""")
    write(root / "knowledge/insights/flow.md", """
---
title: "Flow"
importance: 9
---

# Flow

Write hooks first.
""")
    write(root / "assets-index/media.md", "# Media\n\n## 2026-07-01__take\n\n- Type: media\n")
    write(root / "interactions/sessions/2026-07-01__work.md", "# Session\n\nNotes.\n")
    write(root / "processed/extracted-metadata/2026-07-01__take.yml", "source_hash: sha256:abc\n")
    (root / "assets" / "media").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "media" / "2026-07-01__take.mp3").write_bytes(b"audio-bytes")


def names_in(bundle: Path) -> list[str]:
    with zipfile.ZipFile(bundle) as zf:
        return sorted(zf.namelist())


def test_export_writes_bundle_into_outbox(kb_root: Path):
    seed(kb_root)
    code = kb_export.main(["--root", str(kb_root)])
    assert code == 0

    bundles = list((kb_root / "sync" / "outbox").glob("*.zip"))
    assert len(bundles) == 1
    assert bundles[0].name.startswith("kb-bundle__studio-laptop__")

    names = names_in(bundles[0])
    assert "manifest.yml" in names
    assert "knowledge/domain/plugins.md" in names
    assert "knowledge/insights/flow.md" in names
    assert "assets-index/media.md" in names
    assert "interactions/sessions/2026-07-01__work.md" in names
    assert "meta/extracted-metadata/2026-07-01__take.yml" in names


def test_export_excludes_raw_processed_review_and_assets_by_default(kb_root: Path):
    seed(kb_root)
    write(kb_root / "raw/documents/unsorted/secret.md", "# Secret\n")
    write(kb_root / "review/needs-ai-decision/pending.md", "# Pending\n")
    write(kb_root / "processed/markdown/2026-07-01__take.md", "# Converted\n")

    kb_export.main(["--root", str(kb_root)])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))

    assert not any(n.startswith("raw/") for n in names)
    assert not any(n.startswith("review/") for n in names)
    assert not any(n.startswith("assets/") for n in names)
    assert not any(n.startswith("processed/") for n in names)


def test_export_with_assets_includes_binaries(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root), "--with-assets"])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "assets/media/2026-07-01__take.mp3" in names


def test_manifest_carries_source_and_fingerprints(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root)])
    bundle = next((kb_root / "sync" / "outbox").glob("*.zip"))
    with zipfile.ZipFile(bundle) as zf:
        manifest = yaml.safe_load(zf.read("manifest.yml").decode("utf-8"))

    assert manifest["bundle_format"] == kb_export.BUNDLE_FORMAT
    assert manifest["source"]["label"] == "studio-laptop"
    assert manifest["source"]["name"] == "test-kb"
    assert manifest["source"]["role"] == "Battle rap producer"

    pages = {f["path"]: f for f in manifest["files"]}
    plugins = pages["knowledge/domain/plugins.md"]
    assert plugins["fingerprint"].startswith("sha256:")
    assert plugins["title"] == "Plugins"
    assert plugins["importance"] == 7


def test_config_snapshot_carries_entities_not_privacy(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root)])
    bundle = next((kb_root / "sync" / "outbox").glob("*.zip"))
    with zipfile.ZipFile(bundle) as zf:
        snapshot = yaml.safe_load(zf.read("config/entities.yml").decode("utf-8"))
    assert "plugins" in snapshot["entities"]
    assert "privacy" not in snapshot


def test_dry_run_writes_nothing(kb_root: Path):
    seed(kb_root)
    code = kb_export.main(["--root", str(kb_root), "--dry-run"])
    assert code == 0
    assert not list((kb_root / "sync" / "outbox").glob("*.zip"))


def test_since_filters_by_frontmatter_date(kb_root: Path):
    seed(kb_root)
    write(kb_root / "knowledge/domain/old.md", """
---
title: "Old"
last_verified: 2020-01-01
---

# Old
""")
    kb_export.main(["--root", str(kb_root), "--since", "2026-01-01"])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/domain/old.md" not in names
    assert "knowledge/domain/plugins.md" in names


def test_only_section_restricts_contents(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root), "--only", "knowledge"])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert all(n == "manifest.yml" or n.startswith("knowledge/") for n in names)


def test_config_sync_export_section_is_honored(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        CONFIG + '\n  export:\n    sections: ["knowledge"]\n    with_assets: false\n',
        encoding="utf-8",
    )
    kb_ingest.main(["--root", str(tmp_path), "--init-dirs"])
    seed(tmp_path)
    kb_export.main(["--root", str(tmp_path)])
    names = names_in(next((tmp_path / "sync" / "outbox").glob("*.zip")))
    assert not any(n.startswith("interactions/") for n in names)


def test_empty_base_reports_nothing_to_export(kb_root: Path):
    assert kb_export.main(["--root", str(kb_root)]) == 1


def test_missing_knowledge_dir_is_environment_error(tmp_path: Path):
    assert kb_export.main(["--root", str(tmp_path)]) == 2


def test_export_appends_to_log(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root)])
    log = (kb_root / "log.md").read_text(encoding="utf-8")
    assert "export |" in log


def test_bundle_name_uses_today(kb_root: Path):
    seed(kb_root)
    kb_export.main(["--root", str(kb_root)])
    bundle = next((kb_root / "sync" / "outbox").glob("*.zip"))
    assert dt.date.today().isoformat() in bundle.name
