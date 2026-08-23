"""Tests for the cross-platform reindex orchestration."""
from __future__ import annotations

import json
from pathlib import Path

import kb_reindex


def _write_md(path: Path, tokens: int) -> None:
    """Create a markdown file estimated at roughly `tokens` tokens."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chars = int(tokens * kb_reindex.CHARS_PER_TOKEN)
    path.write_text("x" * chars, encoding="utf-8")


def _kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    (root / "knowledge").mkdir(parents=True)
    (root / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    return root


def test_plan_packs_auto_core_sections_and_aux(tmp_path: Path):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/profile/me.md", 100)
    _write_md(root / "knowledge/voice/tone.md", 100)
    (root / "knowledge/routing-table.md").write_text("# rt", encoding="utf-8")
    _write_md(root / "knowledge/domain/big.md", 30_000)   # own pack
    _write_md(root / "knowledge/playbooks/small.md", 100)  # -> aux
    _write_md(root / "assets-index/docs.md", 50)           # -> aux

    plans = {p.name: p for p in kb_reindex.plan_packs(root, {})}

    assert set(plans) == {"core", "domain", "aux"}
    core = plans["core"]
    assert "knowledge/profile/**/*.md" in core.include
    assert "knowledge/voice/**/*.md" in core.include
    assert "knowledge/routing-table.md" in core.include
    assert "kb.config.yml" in core.include
    assert "AGENTS.md" not in core.include  # already in the system prompt
    assert plans["domain"].include == ["knowledge/domain/**/*.md"]
    assert "assets-index/**/*.md" in plans["aux"].include
    assert "knowledge/playbooks/**/*.md" in plans["aux"].include


def test_plan_packs_auto_splits_oversized_section_by_subfolder(tmp_path: Path):
    root = _kb(tmp_path)
    # library is way over the (default 80K) ceiling -> split per shelf
    _write_md(root / "knowledge/library/craft/book1.md", 60_000)
    _write_md(root / "knowledge/library/marketing/book2.md", 60_000)
    _write_md(root / "knowledge/library/index.md", 100)

    plans = {p.name: p for p in kb_reindex.plan_packs(root, {})}

    assert "library" not in plans
    assert plans["library-craft"].include == ["knowledge/library/craft/**/*.md"]
    assert plans["library-marketing"].include == ["knowledge/library/marketing/**/*.md"]
    assert plans["library-root"].include == ["knowledge/library/*.md"]


def test_plan_packs_respects_window_profile_ceiling(tmp_path: Path):
    root = _kb(tmp_path)
    # 70K section: over the 200k-profile ceiling (60K), under the 256k one
    _write_md(root / "knowledge/domain/sub/a.md", 70_000)

    auto_256 = {p.name for p in kb_reindex.plan_packs(root, {"window_profile": "256k"})}
    auto_200 = {p.name for p in kb_reindex.plan_packs(root, {"window_profile": "200k"})}

    assert "domain" in auto_256
    assert "domain-sub" in auto_200


def test_plan_packs_400k_ceiling_is_120k(tmp_path: Path):
    root = _kb(tmp_path)
    # 100K section: over the 256k ceiling (80K), under the 400k one (120K).
    _write_md(root / "knowledge/domain/sub/a.md", 100_000)

    assert kb_reindex.index_ceiling({"window_profile": "400k"}) == 120_000
    auto_256 = {p.name for p in kb_reindex.plan_packs(root, {"window_profile": "256k"})}
    auto_400 = {p.name for p in kb_reindex.plan_packs(root, {"window_profile": "400k"})}

    assert "domain-sub" in auto_256
    assert "domain" in auto_400
    assert "domain-sub" not in auto_400


def test_plan_packs_explicit_list(tmp_path: Path):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/library/craft/book.md", 500)
    cfg = {
        "packs": [
            {
                "name": "library-craft",
                "include": ["knowledge/library/craft/**"],
                "when_to_load": "writing craft questions",
            }
        ]
    }

    plans = kb_reindex.plan_packs(root, cfg)

    assert len(plans) == 1
    assert plans[0].name == "library-craft"
    assert plans[0].files  # globs resolved
    assert plans[0].when_to_load == "writing craft questions"


def test_write_pack_configs_inherits_base_and_keeps_compress_false(tmp_path: Path):
    root = _kb(tmp_path)
    (root / "repomix.config.json").write_text(
        json.dumps(
            {
                "output": {"compress": True, "style": "xml"},
                "ignore": {"customPatterns": ["raw/**"]},
            }
        ),
        encoding="utf-8",
    )
    plan = kb_reindex.PackPlan(name="domain", include=["knowledge/domain/**/*.md"])

    kb_reindex.write_pack_configs(root, [plan])

    cfg = json.loads((root / ".repomix/configs/domain.json").read_text("utf-8"))
    assert cfg["output"]["filePath"] == ".repomix/domain.xml"
    assert cfg["output"]["compress"] is False  # KB rule: never compress prose
    assert cfg["ignore"]["customPatterns"] == ["raw/**"]
    assert cfg["include"] == ["knowledge/domain/**/*.md"]


def test_run_pack_index_builds_skips_fresh_and_warns_oversized(
    tmp_path: Path, monkeypatch, capsys
):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 30_000)

    built: list[str] = []

    def fake_build(r: Path, config_rel: str) -> bool:
        built.append(config_rel)
        cfg = json.loads((r / config_rel).read_text("utf-8"))
        out = r / cfg["output"]["filePath"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("x" * 1000, encoding="utf-8")
        return True

    monkeypatch.setattr(kb_reindex.shutil, "which", lambda _: "/usr/bin/repomix")
    monkeypatch.setattr(kb_reindex, "_run_repomix_config", fake_build)

    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == [".repomix/configs/core.json", ".repomix/configs/domain.json"]
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "| domain |" in status

    # Second run: everything fresh, no rebuilds.
    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == []

    # Source changed -> only that pack rebuilds.
    built.clear()
    import os
    import time
    future = time.time() + 5
    os.utime(root / "knowledge/domain/a.md", (future, future))
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == [".repomix/configs/domain.json"]

    # Oversized warning: tiny ceiling makes the 1000-char output oversized.
    built.clear()
    capsys.readouterr()
    assert kb_reindex.run_pack_index(root, {"pack_token_ceiling": 10}, force=True)
    out = capsys.readouterr().out
    assert "over ceiling" in out


def test_run_pack_index_writes_audit_requests(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 100)
    monkeypatch.setattr(kb_reindex.shutil, "which", lambda _: None)
    kb_reindex.run_pack_index(root, {})
    audit = root / ".repomix" / "audit"
    assert (audit / "CROSS_PACK__request.md").is_file()
    pack_requests = [
        p for p in audit.glob("*__request.md") if p.name != "CROSS_PACK__request.md"
    ]
    assert pack_requests
    text = next(iter(pack_requests)).read_text(encoding="utf-8")
    assert "file:line" in text
    assert "new session" in text.lower()


def test_legacy_monolith_warning(tmp_path: Path, capsys):
    root = _kb(tmp_path)
    out_xml = root / ".repomix" / "output.xml"
    out_xml.parent.mkdir(parents=True)
    out_xml.write_text("x" * int(200_000 * kb_reindex.CHARS_PER_TOKEN), "utf-8")

    kb_reindex._warn_monolith(root)

    captured = capsys.readouterr().out
    assert "monolithic index" in captured
    assert "index:" in captured


def test_reindex_refreshes_routes_between_ingest_and_lint(
    tmp_path: Path, monkeypatch
):
    calls: list[tuple[str, tuple[str, ...]]] = []

    def record(script: str, *args: str, root: Path) -> int:
        calls.append((script, args))
        return 0

    monkeypatch.setattr(kb_reindex, "_py", record)

    assert (
        kb_reindex.reindex(
            tmp_path,
            quick=True,
            do_index=False,
            do_ingest=True,
        )
        == 0
    )
    assert calls == [
        ("kb_ingest.py", ()),
        ("kb_route.py", ()),
        ("kb_lint.py", ("--quick",)),
    ]
