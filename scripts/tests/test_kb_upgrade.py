"""Tests for scripts/kb_upgrade.py."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import kb_upgrade as up


def test_script_files_includes_all_shipped_kb_scripts():
    """Upgrade must sync every kb_*.py shipped under knowledge-base/scripts/."""
    shipped = {
        p.name
        for p in (up.SRC_SCRIPTS_DIR).glob("kb_*.py")
        if p.is_file()
    }
    listed = set(up.SCRIPT_FILES)
    missing = shipped - listed
    assert not missing, f"SCRIPT_FILES missing: {sorted(missing)}"
    assert "kb_save_session.py" in listed


def test_file_hash_matches_for_identical(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello\n", encoding="utf-8")
    b.write_text("hello\n", encoding="utf-8")
    assert up.file_hash(a) == up.file_hash(b)


def test_file_hash_empty_string_for_missing():
    p = Path("/tmp/__definitely_not_a_real_file__")
    assert up.file_hash(p) == ""


def test_file_hash_changes_with_content(tmp_path: Path):
    a = tmp_path / "a.txt"
    a.write_text("one", encoding="utf-8")
    h1 = up.file_hash(a)
    a.write_text("two", encoding="utf-8")
    h2 = up.file_hash(a)
    assert h1 != h2


def _setup_fake_repo(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake source repo layout so kb_upgrade can resolve paths."""
    (tmp_path / "knowledge-base" / "scripts").mkdir(parents=True)
    (tmp_path / "knowledge-base" / "shell").mkdir(parents=True)
    (tmp_path / "VERSION").write_text("0.7.0\n", encoding="utf-8")
    monkeypatch.setattr(up, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(up, "SRC_SCRIPTS_DIR", tmp_path / "knowledge-base" / "scripts")
    monkeypatch.setattr(up, "SRC_SHELL_DIR", tmp_path / "knowledge-base" / "shell")
    monkeypatch.setattr(up, "VERSION_FILE", tmp_path / "VERSION")
    return tmp_path


def test_get_repo_version_reads_file(tmp_path: Path, monkeypatch):
    _setup_fake_repo(tmp_path, monkeypatch)
    assert up.get_repo_version() == "0.7.0"


def test_get_deployed_version_missing_config(tmp_path: Path):
    assert up.get_deployed_version(tmp_path) == "missing"


def test_get_deployed_version_reads_config(tmp_path: Path):
    (tmp_path / "kb.config.yml").write_text(
        'instructions_version: "0.5.0"\nknowledge_base:\n  name: x\n',
        encoding="utf-8",
    )
    assert up.get_deployed_version(tmp_path) == "0.5.0"


def test_compute_plan_up_to_date(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    deployed_dir = tmp_path / "deployed"
    deployed_dir.mkdir()
    dst = deployed_dir / "kb_lint.py"
    shutil.copy2(src, dst)
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    assert plan.state == "up_to_date"


def test_compute_plan_missing(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    assert plan.state == "missing"


def test_compute_plan_customized_when_force_false(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 1\n# user customization\n", encoding="utf-8")
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=False)
    # Without git history available, it falls back to "customized"
    assert plan.state == "customized"
    assert plan.diff_lines > 0


def test_compute_plan_force_overwrites(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("x = 99\n", encoding="utf-8")
    plan = up.compute_plan(src, dst, prev_version="0.5.0", force=True)
    assert plan.state == "clean_overwrite"


def test_apply_plan_dry_run_does_not_touch_dst(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="missing")
    msg = up.apply_plan(plan, dry_run=True)
    assert "would" in msg.lower()
    assert not dst.exists()


def test_apply_plan_creates_missing_file(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new content\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="missing")
    msg = up.apply_plan(plan, dry_run=False)
    assert dst.is_file()
    assert dst.read_text() == "new content\n"
    assert "copied" in msg.lower()


def test_apply_plan_clean_overwrite(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("old\n", encoding="utf-8")
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="clean_overwrite")
    up.apply_plan(plan, dry_run=False)
    assert dst.read_text() == "new\n"


def test_apply_plan_customized_writes_new_sidecar(tmp_path: Path, monkeypatch):
    repo = _setup_fake_repo(tmp_path, monkeypatch)
    src = repo / "knowledge-base" / "scripts" / "kb_lint.py"
    src.write_text("new\n", encoding="utf-8")
    dst = tmp_path / "deployed" / "kb_lint.py"
    dst.parent.mkdir()
    dst.write_text("old + customizations\n", encoding="utf-8")
    plan = up.UpgradePlan(name=src.name, src=src, dst=dst, state="customized")
    msg = up.apply_plan(plan, dry_run=False)
    sidecar = dst.with_suffix(dst.suffix + ".new")
    assert sidecar.is_file()
    assert sidecar.read_text() == "new\n"
    # Original is untouched
    assert dst.read_text() == "old + customizations\n"
    assert "WROTE" in msg or "wrote" in msg.lower()
