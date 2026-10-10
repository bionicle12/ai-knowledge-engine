"""Tests for kb_export — packing a transferable knowledge bundle."""
from __future__ import annotations

import datetime as dt
import os
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


def _age(path: Path, day: str) -> None:
    stamp = dt.datetime.fromisoformat(day).timestamp()
    os.utime(path, (stamp, stamp))


def test_since_filters_by_frontmatter_date(kb_root: Path):
    seed(kb_root)
    write(kb_root / "knowledge/domain/old.md", """
---
title: "Old"
last_verified: 2020-01-01
---

# Old
""")
    _age(kb_root / "knowledge/domain/old.md", "2020-01-01")
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


# ---------------------------------------------------------------------------
# Audit 2026-09 regressions (MV10, MV15, MV22, D9, D10)
# ---------------------------------------------------------------------------


def test_since_includes_pages_edited_after_their_frontmatter_date(kb_root: Path):
    """MV10: a page edited today with an old last_verified still travels."""
    write(kb_root / "knowledge/domain/edited.md", """
---
title: "Edited"
last_verified: 2020-01-01
---

# Edited today
""")
    kb_export.main(["--root", str(kb_root), "--since", "2026-01-01"])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/domain/edited.md" in names


def test_since_ignores_valid_from(kb_root: Path):
    """MV10: valid_from is when the fact became true, not when the page changed."""
    seed(kb_root)
    page = kb_root / "knowledge/domain/fact.md"
    write(page, """
---
title: "Fact"
valid_from: 2026-09-01
---

# Fact
""")
    _age(page, "2020-01-01")
    kb_export.main(["--root", str(kb_root), "--since", "2026-01-01"])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/domain/fact.md" not in names


def test_list_frontmatter_page_does_not_crash_export(kb_root: Path):
    """MV15: a page whose frontmatter is a YAML list is exported, not a traceback."""
    write(kb_root / "knowledge/domain/odd.md", "---\n- a\n- b\n---\n\n# Odd\n")
    assert kb_export.main(["--root", str(kb_root)]) == 0
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/domain/odd.md" in names


def test_dry_run_creates_no_sync_dirs(tmp_path: Path):
    """MV22: --dry-run must not create sync/."""
    (tmp_path / "kb.config.yml").write_text(CONFIG + "\n", encoding="utf-8")
    write(tmp_path / "knowledge/domain/x.md", "# X\n\nbody\n")
    assert kb_export.main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "sync").exists()


def test_generated_pages_are_not_exported(kb_root: Path):
    """D9: script-written pages are rebuilt on the other side, never shipped."""
    seed(kb_root)
    write(kb_root / "knowledge/routing/domain.md", """
---
generated_by: kb_route.py
---

# Domain Routing
""")
    kb_export.main(["--root", str(kb_root)])
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/routing/domain.md" not in names
    assert "knowledge/domain/plugins.md" in names


def test_export_refuses_files_with_secrets(kb_root: Path, capsys):
    """D10: a token in a page stops the export; the secret itself is never printed."""
    seed(kb_root)
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    write(kb_root / "knowledge/domain/deploy.md", f"# Deploy\n\nUse {token} for the API.\n")
    write(kb_root / "interactions/sessions/2026-07-02__s.md", "# S\n\nDB_PASSWORD=hunter2hunter2\n")

    assert kb_export.main(["--root", str(kb_root)]) == 3

    assert not list((kb_root / "sync" / "outbox").glob("*.zip"))
    err = capsys.readouterr().err
    assert "knowledge/domain/deploy.md" in err and "github-token" in err
    assert "interactions/sessions/2026-07-02__s.md" in err
    assert token not in err and "hunter2" not in err
    assert "--allow-secrets" in err


def test_allow_secrets_exports_anyway(kb_root: Path):
    seed(kb_root)
    write(kb_root / "knowledge/domain/deploy.md", "# Deploy\n\nkey AKIAABCDEFGHIJKLMNOP\n")
    assert kb_export.main(["--root", str(kb_root), "--allow-secrets"]) == 0
    names = names_in(next((kb_root / "sync" / "outbox").glob("*.zip")))
    assert "knowledge/domain/deploy.md" in names


@pytest.mark.parametrize(
    "text, expected",
    [
        ("token ghp_" + "a" * 36, "github-token"),
        ("github_pat_" + "B" * 30, "github-token"),
        ("AKIAABCDEFGHIJKLMNOP", "aws-access-key"),
        ("xoxb-1234567890-abcdefghij", "slack-token"),
        ("sk_live_" + "c" * 24, "stripe-key"),
        ("sk-proj-" + "d" * 30, "openai-key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private-key"),
        ("-----BEGIN PGP PRIVATE KEY BLOCK-----", "private-key"),
        ("password = s3cr3tvalue", "password-assignment"),
        ("CLIENT_SECRET=abcd1234", "password-assignment"),
        # Security review: the YAML/JSON forms and Stripe test keys passed export.
        ("password: hunter2secret", "password-assignment"),
        ('"api_secret": "abcd1234xyz"', "password-assignment"),
        ("secret: s3cr3tvalue", "password-assignment"),
        ("sk_test_abcdefghijklmnop1234", "stripe-key"),
    ],
)
def test_secret_patterns_match(text: str, expected: str):
    assert expected in kb_export.scan_secrets(text)


def test_export_refuses_a_yaml_password_in_interactions(kb_root: Path, capsys):
    """Security review: `password: …` in interactions/*.yml left in a bundle."""
    write(kb_root / "interactions/2026-09/session.yml", "user: me\npassword: hunter2secret\n")
    assert kb_export.main(["--root", str(kb_root), "--only", "interactions"]) == 3
    err = capsys.readouterr().err
    assert "interactions/2026-09/session.yml" in err
    assert "hunter2secret" not in err


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_symlinks_leading_out_of_the_base_are_not_exported(
    kb_root: Path, tmp_path_factory: pytest.TempPathFactory, capsys
):
    """Security review: a page or interaction symlinked to a file outside the base
    was read through and packed into the bundle."""
    outside = tmp_path_factory.mktemp("outside") / "outside.md"
    outside.write_text("# Private\n\nnot part of this base\n", encoding="utf-8")
    write(kb_root / "knowledge/domain/kept.md", "---\ntitle: Kept\n---\n\n# Kept\n")
    (kb_root / "knowledge/domain/leak.md").symlink_to(outside)
    (kb_root / "interactions").mkdir(exist_ok=True)
    (kb_root / "interactions/leak2.md").symlink_to(outside)

    files = {bf.arcname for bf in kb_export.collect(
        kb_root, sections=("knowledge", "interactions"), since=None)}
    assert "knowledge/domain/kept.md" in files
    assert "knowledge/domain/leak.md" not in files
    assert "interactions/leak2.md" not in files

    assert kb_export.main(["--root", str(kb_root), "--only", "knowledge,interactions"]) == 0
    captured = capsys.readouterr()
    assert "knowledge/domain/leak.md" in captured.err
    assert "interactions/leak2.md" in captured.err
    bundle = next((kb_root / "sync" / "outbox").glob("*.zip"))
    with zipfile.ZipFile(bundle) as zf:
        assert not {"knowledge/domain/leak.md", "interactions/leak2.md"} & set(zf.namelist())


@pytest.mark.parametrize(
    "text",
    [
        "Our password policy requires 12 characters.",
        "The secret sauce is timing.",
        "sk-short",
        "password=",
    ],
)
def test_secret_patterns_ignore_prose(text: str):
    assert kb_export.scan_secrets(text) == []


@pytest.mark.parametrize("unit", ["a1-", "a.", "x_password-"])
def test_password_pattern_is_linear_on_long_key_runs(unit: str):
    # The unbounded `[\w.-]*` on both sides of the keyword backtracked
    # quadratically: 60 KB of `a1-a1-…` took over a minute to scan.
    import time

    text = unit * 20000
    started = time.perf_counter()
    assert kb_export.scan_secrets(text) == []
    assert kb_export.scan_secrets(text + "=hunter2hunter2") == []  # key > 128 chars
    assert time.perf_counter() - started < 2.0
