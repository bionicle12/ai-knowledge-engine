"""Tests for kb_import — merging a bundle from another deployment.

The invariant under test everywhere: **local knowledge is never lost.**
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

import kb_common as kbc
import kb_export
import kb_import
import kb_ingest


def _config(label: str) -> str:
    return f"""
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
  plugins: {{}}
sync:
  label: {label}
""".strip()


def make_base(path: Path, label: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "kb.config.yml").write_text(_config(label) + "\n", encoding="utf-8")
    kb_ingest.main(["--root", str(path), "--init-dirs"])
    return path


@pytest.fixture()
def local(tmp_path: Path) -> Path:
    return make_base(tmp_path / "local", "work-laptop")


@pytest.fixture()
def remote(tmp_path: Path) -> Path:
    return make_base(tmp_path / "remote", "studio-laptop")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def make_bundle(remote: Path, local: Path, *, extra_args: list[str] | None = None) -> Path:
    """Export from `remote` and drop the bundle into `local`'s inbox."""
    assert kb_export.main(["--root", str(remote), *(extra_args or [])]) == 0
    bundle = next((remote / "sync" / "outbox").glob("*.zip"))
    inbox = kbc.ensure_dir(kbc.sync_dir(local, "inbox"))
    target = inbox / bundle.name
    shutil.copy2(bundle, target)
    return target


def actions(result: kb_import.ImportResult) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in result.decisions:
        out.setdefault(d.action, []).append(d.arcname)
    return out


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------


def test_new_page_is_added_with_provenance(local: Path, remote: Path):
    write(remote / "knowledge/insights/ai-detection.md", """
---
title: "AI markers"
importance: 9
---

# AI markers

Even timing, no breath between lines.
""")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    target = local / "knowledge/insights/ai-detection.md"
    assert target.is_file()
    meta, body = kbc.read_frontmatter_file(target)
    assert meta["merged_from"] == "studio-laptop"
    assert meta["merge_bundle"] == bundle.name
    assert meta["merge_source_fingerprint"].startswith("sha256:")
    assert meta["importance"] == 9
    assert "Even timing" in body
    assert actions(result)["new"] == ["knowledge/insights/ai-detection.md"]


def test_identical_page_is_skipped(local: Path, remote: Path):
    page = """
---
title: "Shared"
---

# Shared

Same on both machines.
"""
    write(local / "knowledge/voice/shared.md", page)
    write(remote / "knowledge/voice/shared.md", page)
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert actions(result)["identical"] == ["knowledge/voice/shared.md"]


def test_reading_a_page_locally_does_not_create_a_conflict(local: Path, remote: Path):
    """Volatile counters must not count as a content change."""
    write(remote / "knowledge/voice/shared.md", """
---
title: "Shared"
access_count: 0
last_accessed: 2026-07-01
---

# Shared

Body.
""")
    write(local / "knowledge/voice/shared.md", """
---
title: "Shared"
access_count: 17
last_accessed: 2026-07-30
---

# Shared

Body.
""")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert not result.conflicts
    assert set(actions(result)) <= {"identical", "enriched"}


def test_conflict_leaves_local_untouched_and_queues_a_package(local: Path, remote: Path):
    write(local / "knowledge/domain/plugins.md", """
---
title: "Plugins"
importance: 7
last_verified: 2026-07-01
---

# Plugins

- Serum
- FabFilter Pro-Q 3
""")
    write(remote / "knowledge/domain/plugins.md", """
---
title: "Plugins"
importance: 8
last_verified: 2026-07-20
---

# Plugins

- Serum
- iZotope RX
""")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    local_text = (local / "knowledge/domain/plugins.md").read_text(encoding="utf-8")
    assert "FabFilter Pro-Q 3" in local_text, "local knowledge must survive untouched"
    assert "iZotope" not in local_text

    assert len(result.conflicts) == 1
    package = local / "review/needs-merge/plugins__from-studio-laptop.md"
    assert package.is_file()
    package_text = package.read_text(encoding="utf-8")
    assert "```diff" in package_text
    assert "iZotope" in package_text

    staged = local / "review/needs-merge/_incoming/knowledge/domain/plugins.md"
    assert staged.is_file()
    assert "iZotope" in staged.read_text(encoding="utf-8")


def test_duplicate_content_under_another_name_is_not_re_added(local: Path, remote: Path):
    body = """
---
title: "Mixing"
---

# Mixing

Vocals in stacks of three.
"""
    write(local / "knowledge/playbooks/mixing.md", body)
    write(remote / "knowledge/domain/mixing-notes.md", body)
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert actions(result)["duplicate"] == ["knowledge/domain/mixing-notes.md"]
    assert not (local / "knowledge/domain/mixing-notes.md").exists()


def test_fast_forward_when_local_copy_was_never_edited(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", """
---
title: "Flow"
importance: 5
---

# Flow

Version one.
""")
    first = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=first)
    assert "Version one" in (local / "knowledge/insights/flow.md").read_text(encoding="utf-8")

    # The other machine keeps working on the page; this one never touched it.
    write(remote / "knowledge/insights/flow.md", """
---
title: "Flow"
importance: 6
---

# Flow

Version two, with more detail.
""")
    second = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=second)

    assert actions(result)["fast-forward"] == ["knowledge/insights/flow.md"]
    text = (local / "knowledge/insights/flow.md").read_text(encoding="utf-8")
    assert "Version two" in text
    assert result.backup_dir, "the replaced version must be backed up"
    backup = local / result.backup_dir / "knowledge/insights/flow.md"
    assert "Version one" in backup.read_text(encoding="utf-8")


def test_locally_edited_page_conflicts_instead_of_fast_forwarding(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", """
---
title: "Flow"
---

# Flow

Version one.
""")
    first = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=first)

    # Both sides move on.
    write(local / "knowledge/insights/flow.md", """
---
title: "Flow"
---

# Flow

Version one, plus my own local note.
""")
    write(remote / "knowledge/insights/flow.md", """
---
title: "Flow"
---

# Flow

Version two from the other machine.
""")
    second = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=second)

    assert len(result.conflicts) == 1
    assert "my own local note" in (local / "knowledge/insights/flow.md").read_text(encoding="utf-8")


def test_near_duplicate_is_added_and_flagged(local: Path, remote: Path):
    write(local / "knowledge/domain/gear.md", """
---
title: "Gear"
---

# Gear

I record through a Shure SM7B into a Focusrite interface, monitoring on
Yamaha HS5 speakers, and I keep the room treated with foam panels behind
the desk to control early reflections during vocal takes.
""")
    write(remote / "knowledge/domain/studio-gear.md", """
---
title: "Studio gear"
---

# Studio gear

I record through a Shure SM7B into a Focusrite interface, monitoring on
Yamaha HS5 speakers, and I keep the room treated with foam panels behind
the desk to control early reflections during vocal takes and mixing.
""")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    added = [d for d in result.decisions if d.action == "new"]
    assert len(added) == 1
    assert added[0].near_duplicate_of == "knowledge/domain/gear.md"
    assert (local / "knowledge/domain/studio-gear.md").is_file(), "knowledge is never withheld"
    assert (local / "review/needs-merge/studio-gear__near-duplicate.md").is_file()


def test_enriched_merges_metadata_without_touching_the_body(local: Path, remote: Path):
    write(local / "knowledge/domain/tools.md", """
---
title: "Tools"
tags: [daw]
access_count: 2
---

# Tools

Body text.
""")
    write(remote / "knowledge/domain/tools.md", """
---
title: "Tools"
tags: [daw, plugins]
access_count: 9
importance: 8
---

# Tools

Body text.
""")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert actions(result)["enriched"] == ["knowledge/domain/tools.md"]
    meta, body = kbc.read_frontmatter_file(local / "knowledge/domain/tools.md")
    assert meta["tags"] == ["daw", "plugins"]
    assert meta["access_count"] == 9
    assert meta["importance"] == 8
    assert body.strip() == "# Tools\n\nBody text.".strip()


# ---------------------------------------------------------------------------
# Strategies, safety, idempotency
# ---------------------------------------------------------------------------


def test_strategy_prefer_incoming_overwrites_with_backup(local: Path, remote: Path):
    write(local / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nlocal\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nincoming\n")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle, strategy="prefer-incoming")

    assert "incoming" in (local / "knowledge/domain/x.md").read_text(encoding="utf-8")
    assert not result.conflicts
    backup = local / result.backup_dir / "knowledge/domain/x.md"
    assert "local" in backup.read_text(encoding="utf-8")


def test_strategy_prefer_local_discards_incoming(local: Path, remote: Path):
    write(local / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nlocal\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nincoming\n")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle, strategy="prefer-local")

    assert "local" in (local / "knowledge/domain/x.md").read_text(encoding="utf-8")
    assert actions(result)["skipped"] == ["knowledge/domain/x.md"]
    assert not result.conflicts
    assert not list((local / "review/needs-merge").glob("*.md")), (
        "prefer-local settles the question itself — nothing to queue"
    )


def test_dry_run_changes_nothing(local: Path, remote: Path):
    write(remote / "knowledge/insights/new.md", "---\ntitle: N\n---\n\n# N\n\nbody\n")
    write(local / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nlocal\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nincoming\n")
    bundle = make_bundle(remote, local)

    result = kb_import.import_bundle(root=local, bundle=bundle, dry_run=True)

    assert not (local / "knowledge/insights/new.md").exists()
    assert "local" in (local / "knowledge/domain/x.md").read_text(encoding="utf-8")
    assert not list((local / "review/needs-merge").glob("*.md"))
    assert not list(kbc.sync_dir(local, "reports").glob("*.md"))
    assert bundle.is_file(), "dry-run must not consume the bundle"
    assert len(result.conflicts) == 1


def test_reimporting_the_same_bundle_is_a_no_op(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", "---\ntitle: F\n---\n\n# F\n\nbody\n")
    bundle = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=bundle, keep_bundle=True)
    first = (local / "knowledge/insights/flow.md").read_text(encoding="utf-8")

    result = kb_import.import_bundle(root=local, bundle=bundle, keep_bundle=True)

    assert actions(result).get("new") is None
    assert set(actions(result)) <= {"identical", "enriched"}
    assert (local / "knowledge/insights/flow.md").read_text(encoding="utf-8") == first


def test_bundle_moves_to_applied_and_report_is_written(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", "---\ntitle: F\n---\n\n# F\n\nbody\n")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert not bundle.exists()
    assert (kbc.sync_dir(local, "applied") / bundle.name).is_file()
    assert result.report_path
    report = (local / result.report_path).read_text(encoding="utf-8")
    assert "Import report" in report
    assert "studio-laptop" in report


def test_import_appends_to_log(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", "---\ntitle: F\n---\n\n# F\n\nbody\n")
    bundle = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=bundle)
    assert "import |" in (local / "log.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Non-knowledge sections
# ---------------------------------------------------------------------------


def test_assets_index_blocks_merge_and_missing_originals_are_annotated(local: Path, remote: Path):
    write(local / "assets-index/media.md", """
# Media

## 2026-07-01__local-take

- Type: media
- Original: `assets/media/2026-07-01__local-take.mp3`
""")
    write(remote / "assets-index/media.md", """
# Media

## 2026-07-20__remote-take

- Type: media
- Original: `assets/media/2026-07-20__remote-take.mp3`
""")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nbody\n")
    bundle = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=bundle)

    text = (local / "assets-index/media.md").read_text(encoding="utf-8")
    assert "2026-07-01__local-take" in text
    assert "2026-07-20__remote-take" in text
    assert "original file not present in this base" in text


def test_interactions_are_additive_and_collisions_kept_side_by_side(local: Path, remote: Path):
    write(local / "interactions/sessions/2026-07-01__s.md", "# Local session\n")
    write(remote / "interactions/sessions/2026-07-01__s.md", "# Remote session\n")
    write(remote / "interactions/sessions/2026-07-20__other.md", "# Other\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nbody\n")
    bundle = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=bundle)

    sessions = sorted(p.name for p in (local / "interactions/sessions").glob("*.md"))
    assert "2026-07-01__s.md" in sessions
    assert "2026-07-01__s__from-studio-laptop.md" in sessions
    assert "2026-07-20__other.md" in sessions
    assert "Local session" in (local / "interactions/sessions/2026-07-01__s.md").read_text(
        encoding="utf-8"
    )


def test_source_log_is_archived_not_merged(local: Path, remote: Path):
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nbody\n")
    kbc.append_log(operation="ingest", title="remote-thing", root=remote)
    write(local / "log.md", "# Operations Log\n\nlocal entries\n")
    bundle = make_bundle(remote, local)
    kb_import.import_bundle(root=local, bundle=bundle)

    archived = list((local / "log-archive").glob("imported__studio-laptop__*.md"))
    assert len(archived) == 1
    assert "remote-thing" in archived[0].read_text(encoding="utf-8")
    assert "local entries" in (local / "log.md").read_text(encoding="utf-8")


def test_new_entities_are_reported_but_not_applied(local: Path, remote: Path):
    cfg_path = remote / "kb.config.yml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8").replace(
            "entities:\n  plugins: {}", "entities:\n  plugins: {}\n  ai_analysis: {}"
        ),
        encoding="utf-8",
    )
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nbody\n")
    bundle = make_bundle(remote, local)
    result = kb_import.import_bundle(root=local, bundle=bundle)

    assert result.new_entities == ["ai_analysis"]
    local_cfg = yaml.safe_load((local / "kb.config.yml").read_text(encoding="utf-8"))
    assert "ai_analysis" not in local_cfg["entities"], "entities are the agent's call"


# ---------------------------------------------------------------------------
# Bundle validation
# ---------------------------------------------------------------------------


def test_bundle_without_manifest_is_rejected(local: Path, tmp_path: Path):
    bogus = tmp_path / "bogus.zip"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("knowledge/x.md", "# X\n")
    with pytest.raises(ValueError, match="not a kb bundle"):
        kb_import.import_bundle(root=local, bundle=bogus)


def test_unsupported_bundle_format_is_rejected(local: Path, tmp_path: Path):
    bogus = tmp_path / "future.zip"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("manifest.yml", "bundle_format: 99\n")
    with pytest.raises(ValueError, match="not supported"):
        kb_import.import_bundle(root=local, bundle=bogus)


def test_zip_slip_members_are_refused(local: Path, tmp_path: Path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("manifest.yml", "bundle_format: 1\nsource:\n  label: evil\n")
        zf.writestr("../../escaped.md", "# nope\n")
        zf.writestr("knowledge/domain/ok.md", "---\ntitle: OK\n---\n\n# OK\n\nbody\n")
    result = kb_import.import_bundle(root=local, bundle=evil)

    assert not (local.parent / "escaped.md").exists()
    assert any("unsafe path" in e for e in result.errors)
    assert (local / "knowledge/domain/ok.md").is_file()


def test_corrupt_manifest_yaml_is_a_clean_error(local: Path, tmp_path: Path):
    bogus = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("manifest.yml", "bundle_format: [unclosed\n  ::: not yaml")
    with pytest.raises(ValueError, match="unreadable manifest.yml"):
        kb_import.import_bundle(root=local, bundle=bogus)
    # And through the CLI it is a clean exit 2, not a traceback
    assert kb_import.main(["--root", str(local), str(bogus)]) == 2


def test_bundle_with_too_many_members_is_refused(
    local: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(kb_import, "MAX_BUNDLE_MEMBERS", 3)
    fat = tmp_path / "fat.zip"
    with zipfile.ZipFile(fat, "w") as zf:
        zf.writestr("manifest.yml", "bundle_format: 1\nsource:\n  label: fat\n")
        for i in range(5):
            zf.writestr(f"knowledge/domain/n{i}.md", f"# {i}\n")
    with pytest.raises(ValueError, match="file limit"):
        kb_import.import_bundle(root=local, bundle=fat)


def test_bundle_exceeding_unpacked_size_is_refused(
    local: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(kb_import, "MAX_BUNDLE_UNPACKED_BYTES", 1024)
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.yml", "bundle_format: 1\nsource:\n  label: bomb\n")
        zf.writestr("knowledge/domain/big.md", "x" * 100_000)
    with pytest.raises(ValueError, match="zip bomb"):
        kb_import.import_bundle(root=local, bundle=bomb)


def test_unsafe_member_names():
    assert kb_import._is_safe_member("knowledge/x.md")
    assert not kb_import._is_safe_member("../x.md")
    assert not kb_import._is_safe_member("/etc/passwd")
    assert not kb_import._is_safe_member("C:/Windows/x.md")
    assert not kb_import._is_safe_member("knowledge/../../x.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_discovers_bundles_in_inbox(local: Path, remote: Path):
    write(remote / "knowledge/insights/flow.md", "---\ntitle: F\n---\n\n# F\n\nbody\n")
    make_bundle(remote, local)

    code = kb_import.main(["--root", str(local)])

    assert code == 0
    assert (local / "knowledge/insights/flow.md").is_file()


def test_cli_returns_1_when_conflicts_are_pending(local: Path, remote: Path):
    write(local / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nlocal\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nincoming\n")
    make_bundle(remote, local)

    assert kb_import.main(["--root", str(local)]) == 1


def test_cli_without_bundles_is_an_error(local: Path):
    assert kb_import.main(["--root", str(local)]) == 2


def test_cli_honors_config_strategy(local: Path, remote: Path):
    cfg_path = local / "kb.config.yml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8")
        + "  import:\n    strategy: prefer-incoming\n",
        encoding="utf-8",
    )
    write(local / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nlocal\n")
    write(remote / "knowledge/domain/x.md", "---\ntitle: X\n---\n\n# X\n\nincoming\n")
    make_bundle(remote, local)

    assert kb_import.main(["--root", str(local)]) == 0
    assert "incoming" in (local / "knowledge/domain/x.md").read_text(encoding="utf-8")
