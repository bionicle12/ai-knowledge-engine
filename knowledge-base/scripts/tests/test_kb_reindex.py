"""Tests for the cross-platform reindex orchestration."""
from __future__ import annotations

import errno
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import kb_common as kbc
import kb_reindex


def _write_md(path: Path, tokens: int) -> None:
    """Create a markdown file estimated at roughly `tokens` tokens."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chars = int(tokens * kb_reindex.CHARS_PER_TOKEN)
    path.write_text("x" * chars, encoding="utf-8")


def _kb(tmp_path: Path, extra_config: str = "") -> Path:
    root = tmp_path / "kb"
    (root / "knowledge").mkdir(parents=True)
    (root / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n" + extra_config, encoding="utf-8"
    )
    return root


PACK_MODE = "index:\n  enabled: true\n  packs: auto\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ignored(rel: str, patterns: list[str]) -> bool:
    """repomix-style ignore matching, enough for the patterns used here."""
    for pattern in patterns:
        if pattern.endswith("/**") and rel.startswith(pattern[:-2]):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], pattern[3:]):
            return True
        if fnmatch.fnmatchcase(rel, pattern):
            return True
    return False


def _fake_repomix(monkeypatch, *, write: bool = True) -> list[str]:
    """Stand-in for repomix: packs the files its config selects (include
    globs minus ignore patterns and the exact paths listed in the root
    .gitignore) into the `-o` path, so a test can grep a pack for a marker."""
    built: list[str] = []

    def fake_build(r: Path, config_rel: str, _cmd: list[str], output_rel: str) -> bool:
        built.append(config_rel)
        if not write:
            return True
        cfg = json.loads((r / config_rel).read_text("utf-8"))
        ignore = list(cfg.get("ignore", {}).get("customPatterns", []))
        gitignore = r / ".gitignore"
        if gitignore.is_file():
            ignore += [line.strip() for line in gitignore.read_text("utf-8").splitlines() if line.strip()]
        hits = {
            Path(hit)
            for pattern in cfg["include"]
            for hit in glob.glob(str(r / pattern), recursive=True)
        }
        files = sorted(
            f
            for f in hits
            if f.is_file() and not _ignored(f.relative_to(r).as_posix(), ignore)
        )
        out = r / output_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(f.read_text("utf-8") for f in files) or "(empty pack)",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(kb_reindex.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(kb_reindex, "_run_repomix_config", fake_build)
    return built


def test_plan_packs_auto_core_sections_and_aux(tmp_path: Path):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/profile/me.md", 100)
    _write_md(root / "knowledge/voice/tone.md", 100)
    (root / "knowledge/routing-table.md").write_text("# rt", encoding="utf-8")
    _write_md(root / "knowledge/domain/big.md", 30_000)   # own pack
    _write_md(root / "knowledge/playbooks/small.md", 100)  # -> aux
    _write_md(root / "assets-index/docs.md", 50)           # -> aux
    (root / "README.md").write_text("# My project\n", encoding="utf-8")  # the project's
    (root / "KNOWLEDGE_STRUCTURE.md").write_text("# ks\n", encoding="utf-8")

    plans = {p.name: p for p in kb_reindex.plan_packs(root, {})}

    assert set(plans) == {"core", "domain", "aux"}
    core = plans["core"]
    assert "knowledge/profile/**/*.md" in core.include
    assert "knowledge/voice/**/*.md" in core.include
    assert "knowledge/routing-table.md" in core.include
    # AGENTS.md has the agent read kb.config.yml at session start; a packed
    # copy charged its tokens twice (residual audit: context budget).
    assert "kb.config.yml" not in core.include
    assert "KNOWLEDGE_STRUCTURE.md" in core.include
    assert "AGENTS.md" not in core.include  # already in the system prompt
    assert "README.md" not in core.include  # a finalized base shares the project root
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
    # The base patterns come first; the forced privacy floor is appended.
    patterns = cfg["ignore"]["customPatterns"]
    assert patterns[0] == "raw/**"
    assert patterns.count("raw/**") == 1
    assert {"review/**", "interactions/**", "kb-docs/**", "STATUS.md"} <= set(patterns)
    assert cfg["include"] == ["knowledge/domain/**/*.md"]


def test_run_pack_index_builds_skips_fresh_and_warns_oversized(
    tmp_path: Path, monkeypatch, capsys
):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 30_000)

    built: list[str] = []

    def fake_build(r: Path, config_rel: str, _cmd: list[str], output_rel: str) -> bool:
        built.append(config_rel)
        # repomix writes where -o says, not to the config's filePath.
        assert output_rel == json.loads((r / config_rel).read_text("utf-8"))["output"][
            "filePath"
        ] + kb_reindex.BUILD_SUFFIX
        out = r / output_rel
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

    # A touch without a content change is not a change.
    future = time.time() + 5
    os.utime(root / "knowledge/domain/a.md", (future, future))
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == []

    # Source changed -> only that pack rebuilds.
    _write_md(root / "knowledge/domain/a.md", 30_001)
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == [".repomix/configs/domain.json"]

    # Oversized warning: tiny ceiling makes the 1000-char output oversized.
    built.clear()
    capsys.readouterr()
    assert kb_reindex.run_pack_index(root, {"pack_token_ceiling": 10}, force=True)
    out = capsys.readouterr().out
    assert "over ceiling" in out
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    # kb_doctor.py's layout: tokens (+ ⚠ OVER) in cell 2, the build in cell 3.
    assert re.search(r"^\| domain \| [\d,]+ ⚠ OVER \| rebuilt ", status, re.M)
    assert "OVER ceiling: 2 (core, domain)" in status


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


# ---------------------------------------------------------------------------
# Q8 — pack freshness by manifest (membership + content), orphan cleanup
# ---------------------------------------------------------------------------


def _fake_legacy_repomix(calls: list[list[str]], *, write: bool = True):
    """Stand-in for a legacy repomix run: writes the `-o` file."""

    def run(cmd: list[str], r: Path) -> int:
        calls.append(cmd)
        if write:
            out = r / cmd[cmd.index("-o") + 1]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("MONOLITH", encoding="utf-8")
        return 0

    return run


def _packs_status_rows(root: Path) -> dict[str, list[str]]:
    """PACKS_STATUS.md rows split the way kb_doctor.py reads them:
    cells[1] the tokens (+ ⚠ OVER), cells[2] the last build."""
    rows: dict[str, list[str]] = {}
    for line in (root / ".repomix/PACKS_STATUS.md").read_text("utf-8").splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) >= 3 and re.match(r"~?\s*\d[\d,]*", cells[1]):
            rows[cells[0]] = cells
    return rows


def test_deleted_page_leaves_the_pack_on_the_next_run(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write(root, "knowledge/notes/keep.md", "KEEP-ME\n")
    secret = _write(root, "knowledge/notes/secret.md", "SECRET-TOKEN-XYZ\n")
    built = _fake_repomix(monkeypatch)

    assert kb_reindex.run_pack_index(root, {}) is True
    assert "SECRET-TOKEN-XYZ" in (root / ".repomix/aux.xml").read_text("utf-8")

    secret.unlink()
    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == [".repomix/configs/aux.json"]
    assert "SECRET-TOKEN-XYZ" not in (root / ".repomix/aux.xml").read_text("utf-8")
    members = kb_reindex.read_manifest(root)["packs"]["aux"]["files"]
    assert list(members) == ["knowledge/notes/keep.md"]


def test_packs_that_left_the_plan_are_removed(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 100)
    _fake_repomix(monkeypatch)
    explicit = {"packs": [{"name": "everything", "include": ["knowledge/**/*.md"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is True
    assert (root / ".repomix/everything.xml").is_file()
    legacy = _write(root, ".repomix/output.xml", "old monolith")

    assert kb_reindex.run_pack_index(root, {}) is True  # back to `packs: auto`

    assert not (root / ".repomix/everything.xml").exists()
    assert not (root / ".repomix/configs/everything.json").exists()
    assert not (root / ".repomix/audit/everything__request.md").exists()
    assert (root / ".repomix/core.xml").is_file()
    assert legacy.is_file()  # never ours to delete
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "Removed orphan packs: everything." in status
    assert "everything" not in kb_reindex.read_manifest(root)["packs"]


def test_a_build_that_writes_nothing_is_failed_not_rebuilt(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 30_000)
    _fake_repomix(monkeypatch, write=False)

    assert kb_reindex.run_pack_index(root, {}) is False

    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "rebuilt" not in status
    assert "FAILED: 2 (core, domain)" in status
    assert kb_reindex.read_manifest(root)["packs"]["domain"]["state"] == "FAILED"


def test_a_build_that_writes_nothing_keeps_the_old_copy_failed(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    page = _write(root, "knowledge/notes/a.md", "OLD SECRET\n")
    _fake_repomix(monkeypatch)
    assert kb_reindex.run_pack_index(root, {}) is True
    assert "OLD SECRET" in (root / ".repomix/aux.xml").read_text("utf-8")

    page.write_text("new text\n", encoding="utf-8")
    built = _fake_repomix(monkeypatch, write=False)  # exit 0, no output
    assert kb_reindex.run_pack_index(root, {}) is False

    entry = kb_reindex.read_manifest(root)["packs"]["aux"]
    assert entry["state"] == "FAILED" and entry["files"] is None
    assert _packs_status_rows(root)["aux"][2].startswith("FAILED; copy from ")
    # The old copy is kept as it was and never counts as fresh.
    assert "OLD SECRET" in (root / ".repomix/aux.xml").read_text("utf-8")
    assert not list((root / ".repomix").glob("*" + kb_reindex.BUILD_SUFFIX))
    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is False
    assert built == [".repomix/configs/aux.json"]

    # A builder that ignores -o and rewrites the pack in place is no better.
    def in_place(r: Path, config_rel: str, _cmd, _output_rel: str) -> bool:
        (r / ".repomix/aux.xml").write_text("in place", encoding="utf-8")
        return True

    monkeypatch.setattr(kb_reindex, "_run_repomix_config", in_place)
    assert kb_reindex.run_pack_index(root, {}) is False
    assert kb_reindex.read_manifest(root)["packs"]["aux"]["state"] == "FAILED"


def test_gitignore_changes_rebuild_the_packs(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write(root, "knowledge/work/open.md", "OPEN-PAGE\n")
    _write(root, "knowledge/work/hidden.md", "GITIGNORED-SECRET\n")
    built = _fake_repomix(monkeypatch)
    assert kb_reindex.run_pack_index(root, {}) is True
    assert "GITIGNORED-SECRET" in (root / ".repomix/aux.xml").read_text("utf-8")

    # Hiding a packed page with .gitignore must rebuild its pack.
    _write(root, ".gitignore", "knowledge/work/hidden.md\n")
    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is True
    assert ".repomix/configs/aux.json" in built
    assert "GITIGNORED-SECRET" not in (root / ".repomix/aux.xml").read_text("utf-8")

    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is True
    assert built == []  # unchanged ignore files: fresh

    # A nested .gitignore (or .repomixignore) of a member's folder counts too.
    _write(root, "knowledge/work/.repomixignore", "draft.md\n")
    assert kb_reindex.run_pack_index(root, {}) is True
    assert ".repomix/configs/aux.json" in built

    # Un-ignoring brings the page back.
    (root / ".gitignore").write_text("", encoding="utf-8")
    built.clear()
    assert kb_reindex.run_pack_index(root, {}) is True
    assert "GITIGNORED-SECRET" in (root / ".repomix/aux.xml").read_text("utf-8")


def test_ignore_digest_follows_gitignore_files_up_to_the_git_root(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git" / "info").mkdir(parents=True)
    root = _kb(repo)  # repo/kb: a base inside a larger git work tree
    members = {"knowledge/a.md": "x"}
    first = kb_reindex._ignore_digest(root, members)

    (repo / ".gitignore").write_text("kb/knowledge/a.md\n", encoding="utf-8")
    second = kb_reindex._ignore_digest(root, members)
    (repo / ".git" / "info" / "exclude").write_text("x\n", encoding="utf-8")  # not root's
    assert kb_reindex._ignore_digest(root, members) == second != first

    (root / ".git" / "info").mkdir(parents=True)
    (root / ".git" / "info" / "exclude").write_text("knowledge/a.md\n", encoding="utf-8")
    # The base is its own repo now: its exclude counts, the outer .gitignore not.
    own = kb_reindex._ignore_digest(root, members)
    (repo / ".gitignore").write_text("", encoding="utf-8")
    assert kb_reindex._ignore_digest(root, members) == own


def test_packs_status_never_claims_rebuilt_when_repomix_is_gone(
    tmp_path: Path, monkeypatch
):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 30_000)
    _fake_repomix(monkeypatch)
    assert kb_reindex.run_pack_index(root, {}) is True

    _write_md(root / "knowledge/domain/a.md", 30_010)
    monkeypatch.setattr(kb_reindex.shutil, "which", lambda _: None)
    assert kb_reindex.run_pack_index(root, {}) is False

    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "rebuilt" not in status
    assert "| core |" in status and "fresh (built " in status
    assert "STALE — repomix unavailable; copy from" in status
    assert kb_reindex.read_manifest(root)["packs"]["domain"]["state"] == "STALE"


# ---------------------------------------------------------------------------
# Q10 — privacy floor in code; a broken base config stops the build
# ---------------------------------------------------------------------------

PRIVATE_MARKERS = {
    "raw/chats/unsorted/chat.md": "RAW-PRIVATE-CHAT",
    "review/needs-ai-decision/r.md": "REVIEW-PRIVATE",
    "interactions/sessions/s.md": "SESSION-PRIVATE",
    "processed/p.md": "PROCESSED-PRIVATE",
    "kb-docs/05_INDEX.md": "KB-DOCS-COPY",
    "eval/results/e.md": "EVAL-RESULT",
    "STATUS.md": "STATUS-HANDOFF",
    "log.md": "LOG-ENTRY",
}


def test_invalid_base_config_stops_the_build(tmp_path: Path, monkeypatch, capsys):
    root = _kb(tmp_path)
    # repomix itself accepts the trailing commas (JSON5); json does not, and
    # the old fallback to `{}` dropped the whole ignore list.
    _write(
        root,
        "repomix.config.json",
        '{"ignore": {"customPatterns": ["raw/**", "review/**",],},}',
    )
    for rel, marker in PRIVATE_MARKERS.items():
        _write(root, rel, marker + "\n")
    _write_md(root / "knowledge/domain/a.md", 100)
    built = _fake_repomix(monkeypatch)

    explicit = {"packs": [{"name": "everything", "include": ["**/*.md"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is False

    assert built == []
    assert not (root / ".repomix/everything.xml").exists()
    assert "not valid JSON" in capsys.readouterr().out
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "**Index not built:** repomix.config.json is not valid JSON" in status
    assert kb_reindex.read_manifest(root)["packs"]["everything"]["state"] == "FAILED"


def test_private_folders_never_reach_a_pack(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    # A valid base config whose ignore list was trimmed by hand.
    _write(root, "repomix.config.json", json.dumps({"ignore": {"customPatterns": []}}))
    for rel, marker in PRIVATE_MARKERS.items():
        _write(root, rel, marker + "\n")
    _write(root, "knowledge/domain/a.md", "PUBLIC-KNOWLEDGE\n")
    _fake_repomix(monkeypatch)

    explicit = {"packs": [{"name": "everything", "include": ["**/*.md"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is True

    text = (root / ".repomix/everything.xml").read_text("utf-8")
    assert "PUBLIC-KNOWLEDGE" in text
    for marker in PRIVATE_MARKERS.values():
        assert marker not in text
    cfg = json.loads((root / ".repomix/configs/everything.json").read_text("utf-8"))
    patterns = set(cfg["ignore"]["customPatterns"])
    assert {
        "raw/**", "review/**", "interactions/**", "processed/**", "assets/**",
        "kb-docs/**", "eval/**", ".kb-state/**", ".kb-backups/**", "STATUS.md",
    } <= patterns
    members = kb_reindex.read_manifest(root)["packs"]["everything"]["files"]
    assert list(members) == ["knowledge/domain/a.md"]


def test_template_base_config_lists_the_whole_privacy_floor():
    template = (
        Path(kb_reindex.__file__).resolve().parents[1]
        / "templates"
        / "repomix.config.json.template"
    )
    patterns = set(json.loads(template.read_text("utf-8"))["ignore"]["customPatterns"])
    floor = set(kb_reindex.ALWAYS_IGNORED) | {p for _, p in kb_reindex.PRIVACY_GATED}
    assert floor <= patterns


def test_privacy_flags_open_only_their_own_folder(tmp_path: Path):
    root = _kb(
        tmp_path,
        "privacy:\n  raw_indexing_allowed: true\n  review_indexing_allowed: false\n"
        "status:\n  file: \"handoff/NOW.md\"\n",
    )
    patterns = kb_reindex.forced_ignore_patterns(kbc.load_config(root))
    assert "raw/**" not in patterns
    assert "review/**" in patterns and "interactions/**" in patterns
    assert "handoff/NOW.md" in patterns and "STATUS.md" in patterns


def test_legacy_build_gets_the_privacy_floor_and_refuses_broken_json(
    tmp_path: Path, monkeypatch
):
    root = _kb(tmp_path)  # no index: section -> legacy monolith
    calls: list[list[str]] = []
    monkeypatch.setattr(kb_reindex.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(kb_reindex, "_run_repomix", _fake_legacy_repomix(calls))

    assert kb_reindex.run_index(root, kbc.load_config(root)) is True
    ignore = calls[0][calls[0].index("--ignore") + 1].split(",")
    assert {"raw/**", "review/**", "interactions/**", "kb-docs/**", "STATUS.md"} <= set(ignore)

    calls.clear()
    _write(root, "repomix.config.json", "{,}")
    assert kb_reindex.run_index(root, kbc.load_config(root)) is False
    assert calls == []


def test_switching_back_to_legacy_retires_packs_and_updates_status(
    tmp_path: Path, monkeypatch
):
    import kb_status

    root = _kb(tmp_path, PACK_MODE)
    _write(root, "repomix.config.json", json.dumps({"output": {"filePath": ".repomix/output.xml"}}))
    _write(root, "knowledge/domain/a.md", "PAGE\n")
    _fake_repomix(monkeypatch)
    explicit = {"packs": [{"name": "everything", "include": ["knowledge/**/*.md"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is True
    assert (root / ".repomix/everything.xml").is_file()

    # The index: section is removed -> legacy monolith.
    (root / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(kb_reindex, "_run_repomix", _fake_legacy_repomix(calls))
    assert kb_reindex.run_index(root, kbc.load_config(root)) is True

    assert (root / ".repomix/output.xml").read_text("utf-8") == "MONOLITH"
    assert calls[0][calls[0].index("-o") + 1] == ".repomix/output.xml" + kb_reindex.BUILD_SUFFIX
    assert not (root / ".repomix/everything.xml").exists()  # nobody refreshes it any more
    assert not (root / ".repomix/configs/everything.json").exists()
    assert not (root / ".repomix/audit/CROSS_PACK__request.md").exists()
    manifest = kb_reindex.read_manifest(root)
    assert manifest["mode"] == "legacy" and manifest["packs"] == {}
    assert manifest["legacy"]["state"] == "rebuilt"
    rows = _packs_status_rows(root)
    assert list(rows) == ["output.xml (legacy monolith)"]
    assert rows["output.xml (legacy monolith)"][2].startswith("rebuilt ")
    assert [i.key for i in kb_status.collect_items(root) if i.key == "index"] == []

    # A legacy build that exits 0 without writing is FAILED, and STATUS says so.
    monkeypatch.setattr(kb_reindex, "_run_repomix", _fake_legacy_repomix([], write=False))
    assert kb_reindex.run_index(root, kbc.load_config(root)) is False
    assert (root / ".repomix/output.xml").read_text("utf-8") == "MONOLITH"
    assert _packs_status_rows(root)["output.xml (legacy monolith)"][2].startswith(
        "FAILED; copy from "
    )
    [index] = [i for i in kb_status.collect_items(root) if i.key == "index"]
    assert index.line == "- index: legacy output.xml FAILED → see .repomix/PACKS_STATUS.md"


def test_reindex_refuses_a_folder_without_kb_config(tmp_path: Path, monkeypatch, capsys):
    folder = tmp_path / "engine-checkout"
    folder.mkdir()
    _write(folder, "notes.md", "not a base\n")
    monkeypatch.setattr(kb_reindex, "_py", lambda *a, **k: pytest.fail("ran a step"))
    monkeypatch.setattr(kb_reindex, "run_index", lambda *a, **k: pytest.fail("built an index"))

    assert kb_reindex.main(["--root", str(folder), "--index-only"]) == 2
    assert kb_reindex.main(["--root", str(folder)]) == 2
    assert kb_reindex.main(["--root", str(folder), "--hook"]) == 0  # never fails a commit

    assert sorted(p.name for p in folder.iterdir()) == ["notes.md"]  # no phantom base
    assert "not a knowledge base" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Q11 — reserved pack names, knowledge/ root pages, safe explicit names
# ---------------------------------------------------------------------------


def test_section_named_like_a_reserved_pack_keeps_core_intact(tmp_path: Path):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/profile/me.md", 100)
    _write_md(root / "knowledge/core/big.md", 30_000)
    _write_md(root / "knowledge/aux/big.md", 30_000)
    _write_md(root / "knowledge/playbooks/small.md", 100)

    plans = kb_reindex.plan_packs(root, {})
    names = [p.name for p in plans]
    by_name = {p.name: p for p in plans}

    assert len(names) == len(set(names))
    assert "knowledge/profile/**/*.md" in by_name["core"].include
    assert by_name["knowledge-core"].include == ["knowledge/core/**/*.md"]
    assert by_name["knowledge-aux"].include == ["knowledge/aux/**/*.md"]
    assert by_name["aux"].include == ["knowledge/playbooks/**/*.md"]

    # Merged into aux, the section keeps its non-reserved name in the hint.
    small = _kb(tmp_path / "small")
    _write_md(small / "knowledge/core/c.md", 100)
    aux = {p.name: p for p in kb_reindex.plan_packs(small, {})}["aux"]
    assert aux.when_to_load == "Merged small sections: knowledge-core."


def test_pages_at_the_knowledge_root_are_packed(tmp_path: Path):
    root = _kb(tmp_path)
    (root / "knowledge/routing-table.md").write_text("# rt", encoding="utf-8")
    _write_md(root / "knowledge/glossary.md", 100)
    _write_md(root / "knowledge/domain/a.md", 30_000)

    plans = {p.name: p for p in kb_reindex.plan_packs(root, {})}
    assert root / "knowledge/glossary.md" in plans["aux"].files
    assert "knowledge/*.md" in plans["aux"].include
    assert "knowledge/routing-table.md" in plans["aux"].exclude
    kb_reindex.write_pack_configs(root, list(plans.values()))
    aux_cfg = json.loads((root / ".repomix/configs/aux.json").read_text("utf-8"))
    assert "knowledge/routing-table.md" in aux_cfg["ignore"]["customPatterns"]

    # A big root page gets its own pack; every page sits in exactly one pack.
    _write_md(root / "knowledge/glossary.md", 20_000)
    plans = {p.name: p for p in kb_reindex.plan_packs(root, {})}
    assert plans["knowledge-root"].files == [root / "knowledge/glossary.md"]
    assert plans["knowledge-root"].exclude == ["knowledge/routing-table.md"]
    packed = [f for p in plans.values() for f in p.files if "knowledge" in f.parts]
    assert sorted(packed) == sorted(set(packed))
    assert set(packed) == set(kb_reindex._md_files(root / "knowledge"))


def test_explicit_pack_names_are_safe_file_names(tmp_path: Path, capsys):
    root = _kb(tmp_path)
    _write_md(root / "knowledge/domain/a.md", 100)
    entries = [
        {"name": "../../evil", "include": ["knowledge/**/*.md"]},
        {"name": "dup", "include": ["knowledge/**/*.md"]},
        {"name": "dup", "include": ["knowledge/domain/*.md"]},
        "not-a-mapping",
    ]
    plans = kb_reindex.plan_packs(root, {"packs": entries})

    names = [p.name for p in plans]
    assert names[1:] == ["dup", "dup-2"]
    assert "/" not in names[0] and not names[0].startswith(".")
    for plan in plans:
        target = (root / plan.output_rel).resolve()
        assert target.parent == (root / ".repomix").resolve()
    assert "is built as 'dup-2'" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# repomix resolution, exit codes, CLI modes (Q-LOW, D6, D8)
# ---------------------------------------------------------------------------


def test_npx_fallback_is_pinned_and_optional(tmp_path: Path, monkeypatch, capsys):
    root = _kb(tmp_path, PACK_MODE + '  repomix_version: "1.14.0"\n')
    _write_md(root / "knowledge/domain/a.md", 100)
    monkeypatch.setattr(
        kb_reindex.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None
    )
    cfg = kbc.load_config(root)
    assert kb_reindex.repomix_command(cfg) == ["/usr/bin/npx", "--yes", "repomix@1.14.0"]

    seen: list[list[str]] = []

    def fake_build(r: Path, config_rel: str, cmd: list[str], output_rel: str) -> bool:
        seen.append(cmd)
        (r / output_rel).write_text("x", encoding="utf-8")
        return True

    monkeypatch.setattr(kb_reindex, "_run_repomix_config", fake_build)
    assert kb_reindex.run_pack_index(root, cfg.index, cfg=cfg) is True
    assert seen and all(cmd[-1] == "repomix@1.14.0" for cmd in seen)
    assert "repomix not on PATH — using npx repomix@1.14.0" in capsys.readouterr().out
    assert kb_reindex.read_manifest(root)["builder"] == "npx repomix@1.14.0"

    off = _kb(tmp_path / "off", PACK_MODE + "  npx_fallback: false\n")
    assert kb_reindex.repomix_command(kbc.load_config(off)) is None


def test_index_only_fails_loudly_without_repomix(tmp_path: Path, monkeypatch, capsys):
    root = _kb(tmp_path, PACK_MODE)
    _write_md(root / "knowledge/domain/a.md", 100)
    monkeypatch.setattr(kb_reindex.shutil, "which", lambda _: None)

    assert kb_reindex.main(["--root", str(root), "--index-only"]) == 1

    out = capsys.readouterr().out
    assert "neither repomix nor npx is on PATH" in out
    assert "npm install -g repomix@1.14.0" in out
    assert "kb-docs/05_INDEX.md" in out  # setup/05_INDEX.md is gone after finalize
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "STALE: 2 (core, aux)" in status
    assert "rebuilt" not in status


def test_full_run_exit_code_reports_ingest_and_index_failures(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def fake_py(script: str, *args: str, root: Path) -> int:
        calls.append(script)
        return 1 if script == "kb_ingest.py" else 0

    monkeypatch.setattr(kb_reindex, "_py", fake_py)
    assert kb_reindex.reindex(tmp_path, quick=True, do_index=False) == 1
    assert calls == ["kb_ingest.py", "kb_route.py", "kb_lint.py"]

    monkeypatch.setattr(kb_reindex, "_py", lambda script, *a, root: 0)
    monkeypatch.setattr(kb_reindex, "run_index", lambda r, cfg, force=False: False)
    assert kb_reindex.reindex(tmp_path, quick=True) == 1
    monkeypatch.setattr(kb_reindex, "run_index", lambda r, cfg, force=False: True)
    assert kb_reindex.reindex(tmp_path, quick=True) == 0


def test_consolidation_requests_reflection_only_when_threshold_met(
    tmp_path: Path, monkeypatch
):
    calls: list[tuple[str, tuple[str, ...]]] = []
    decision = {"value": "THRESHOLD_MET"}

    def fake_py(script: str, *args: str, root: Path) -> int:
        calls.append((script, args))
        return 0

    def fake_capture(script: str, *args: str, root: Path) -> tuple[int, str]:
        calls.append((script, args))
        return 0, decision["value"] + "\n"

    monkeypatch.setattr(kb_reindex, "_py", fake_py)
    monkeypatch.setattr(kb_reindex, "_py_capture", fake_capture)

    def run(base: Path, config: str = "") -> list[tuple[str, tuple[str, ...]]]:
        base.mkdir(parents=True, exist_ok=True)
        (base / "kb.config.yml").write_text(
            "knowledge_base:\n  name: t\n" + config, encoding="utf-8"
        )
        calls.clear()
        kb_reindex.reindex(base, do_index=False, do_ingest=False)
        return list(calls)

    due = run(tmp_path / "due")
    assert ("kb_reflect.py", ("--check-threshold",)) in due
    assert ("kb_reflect.py", ("--generate",)) in due

    decision["value"] = "SKIP"
    skip = run(tmp_path / "skip")
    assert ("kb_reflect.py", ("--check-threshold",)) in skip
    assert ("kb_reflect.py", ("--generate",)) not in skip

    decision["value"] = "THRESHOLD_MET"
    off = run(tmp_path / "off", "autorun:\n  consolidation_on_reindex: false\n")
    assert ("kb_lint.py", ("--output", "report")) in off
    assert not [c for c in off if c[0] == "kb_reflect.py"]


def test_no_watch_is_a_deprecated_alias_of_quick(tmp_path: Path, monkeypatch, capsys):
    root = _kb(tmp_path)
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb_reindex, "_py", lambda script, *a, root: calls.append((script, a)) or 0
    )

    assert kb_reindex.main(["--root", str(root), "--no-watch", "--no-index"]) == 0

    assert "deprecated" in capsys.readouterr().err
    assert [c[0] for c in calls] == ["kb_ingest.py", "kb_route.py", "kb_lint.py"]


def test_every_mode_ends_with_status_md(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    monkeypatch.setattr(kb_reindex, "_py", lambda script, *a, root: 0)
    monkeypatch.setattr(kb_reindex, "run_index", lambda r, cfg, force=False: True)
    status = root / "STATUS.md"

    assert kb_reindex.main(["--root", str(root), "--quick"]) == 0
    assert status.read_text("utf-8").startswith("# KB status — ")
    status.unlink()
    assert kb_reindex.main(["--root", str(root), "--index-only"]) == 0
    assert status.is_file()
    status.unlink()
    assert kb_reindex.main(["--root", str(root), "--hook"]) == 0
    assert status.is_file()
    status.unlink()

    (root / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\nstatus:\n  enabled: false\n", encoding="utf-8"
    )
    assert kb_reindex.main(["--root", str(root), "--index-only"]) == 0
    assert not status.exists()


def test_hook_mode_builds_index_and_status_only(tmp_path: Path, monkeypatch, capsys):
    root = _kb(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        kb_reindex, "_py", lambda script, *a, root: calls.append(script) or 0
    )
    monkeypatch.setattr(
        kb_reindex,
        "_py_capture",
        lambda script, *a, root: (calls.append(script), (0, ""))[1],
    )
    monkeypatch.setattr(
        kb_reindex, "run_index", lambda r, cfg, force=False: calls.append("index") or True
    )

    assert kb_reindex.main(["--root", str(root), "--hook"]) == 0

    assert calls == ["index"]  # no ingest, routing, lint or reflection
    assert (root / "STATUS.md").is_file()
    log = (root / ".kb-state" / "hooks.log").read_text("utf-8")
    assert "kb_reindex --hook" in log and "hook: done" in log
    assert capsys.readouterr().out == ""  # everything went to the log


def test_busy_pipeline_hook_skips_quietly_and_manual_run_gives_up(
    tmp_path: Path, monkeypatch, capsys
):
    root = _kb(tmp_path)
    holder_code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(Path(kb_reindex.__file__).parent)!r})\n"
        "import kb_common as kbc\n"
        f"with kbc.kb_lock({str(root)!r}, 'pipeline', timeout=5):\n"
        "    print('locked', flush=True)\n"
        "    time.sleep(60)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        monkeypatch.setattr(kb_reindex, "HOOK_LOCK_TIMEOUT", 0.2)
        monkeypatch.setattr(kb_reindex, "PIPELINE_LOCK_TIMEOUT", 0.2)

        def must_not_run(*_a, **_k):
            raise AssertionError("ran while the pipeline was busy")

        monkeypatch.setattr(kb_reindex, "run_index", must_not_run)

        assert kb_reindex.main(["--root", str(root), "--hook"]) == 0
        log = (root / ".kb-state" / "hooks.log").read_text("utf-8")
        assert "holds the pipeline lock; skipped" in log

        assert kb_reindex.main(["--root", str(root), "--index-only"]) == 1
        captured = capsys.readouterr()
        assert "waiting up to" in captured.out
        assert "still busy" in captured.err
    finally:
        holder.kill()
        holder.wait()


def test_hook_mode_survives_a_filesystem_without_locks(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)

    def no_locks(*_a, **_k):
        raise OSError(errno.ENOLCK, "No locks available")

    def must_not_run(*_a, **_k):
        raise AssertionError("ran without the lock")

    monkeypatch.setattr(kb_reindex.kbc, "kb_lock", no_locks)
    monkeypatch.setattr(kb_reindex, "run_index", must_not_run)

    assert kb_reindex.main(["--root", str(root), "--hook"]) == 0
    log = (root / ".kb-state" / "hooks.log").read_text("utf-8")
    assert "cannot take the pipeline lock" in log


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="needs a POSIX bash"
)
def test_reindex_sh_is_a_thin_wrapper(tmp_path: Path):
    shell_src = Path(kb_reindex.__file__).resolve().parents[1] / "shell"
    base = tmp_path / "base"
    (base / "shell").mkdir(parents=True)
    (base / "scripts").mkdir()
    for name in ("reindex.sh", "_kbpy.sh"):
        (base / "shell" / name).write_text(
            (shell_src / name).read_text("utf-8"), encoding="utf-8"
        )
    (base / "scripts" / "kb_reindex.py").write_text(
        "import os, sys\nprint('ARGS', *sys.argv[1:])\nprint('CWD', os.getcwd())\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    env = {**os.environ, "KB_PYTHON": sys.executable}

    result = subprocess.run(
        ["bash", str(base / "shell" / "reindex.sh"), "--quick", "--no-index"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 3  # the script's status, not a blanket "done"
    assert "ARGS --quick --no-index" in result.stdout
    assert f"CWD {base.resolve()}" in result.stdout
    assert "done" not in result.stdout


# ---------------------------------------------------------------------------
# E-H3 — a member repomix leaves out (security check) is reported, not lost
# ---------------------------------------------------------------------------


def _fake_xml_repomix(monkeypatch, *, drop: str) -> None:
    """repomix-like XML output that silently omits every file containing
    `drop`, as repomix's security check does under --quiet."""

    def fake_build(r: Path, config_rel: str, _cmd: list[str], output_rel: str) -> bool:
        cfg = json.loads((r / config_rel).read_text("utf-8"))
        paths = sorted(
            {
                Path(hit).relative_to(r).as_posix()
                for pattern in cfg["include"]
                for hit in glob.glob(str(r / pattern), recursive=True)
                if Path(hit).is_file()
            }
        )
        body = "".join(
            f'<file path="{rel}">\n{(r / rel).read_text("utf-8")}</file>\n\n'
            for rel in paths
            if drop not in (r / rel).read_text("utf-8")
        )
        (r / output_rel).write_text(
            "<files>\nThis section contains the contents of the repository's files.\n\n"
            + body + "</files>\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(kb_reindex.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(kb_reindex, "_run_repomix_config", fake_build)


def test_member_left_out_by_repomix_is_reported(tmp_path: Path, monkeypatch, capsys):
    import kb_status

    root = _kb(tmp_path)
    _write(root, "knowledge/decisions/use-rabbitmq.md", "clean\n")
    _write(root, "knowledge/domain/deploy.md", "SECRET-TOKEN\n")
    _fake_xml_repomix(monkeypatch, drop="SECRET-TOKEN")
    explicit = {"packs": [{"name": "everything", "include": ["knowledge/**/*.md"]}]}

    assert kb_reindex.run_pack_index(root, explicit) is True
    entry = kb_reindex.read_manifest(root)["packs"]["everything"]
    assert entry["state"] == "rebuilt"
    assert entry["left_out"] == ["knowledge/domain/deploy.md"]
    assert "left out 1 file(s) — knowledge/domain/deploy.md" in capsys.readouterr().out
    status = (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert "Left out by repomix" in status
    assert "everything: knowledge/domain/deploy.md" in status

    # A fresh pack keeps reporting it; STATUS.md carries it to the session.
    assert kb_reindex.run_pack_index(root, explicit) is True
    entry = kb_reindex.read_manifest(root)["packs"]["everything"]
    assert (entry["state"], entry["left_out"]) == ("fresh", ["knowledge/domain/deploy.md"])
    assert [item.line for item in kb_status._index_items(root)] == [
        "- index: 1 file left out by repomix → see .repomix/PACKS_STATUS.md"
    ]

    # Redacted → rebuilt → the report is gone.
    _write(root, "knowledge/domain/deploy.md", "<redacted>\n")
    assert kb_reindex.run_pack_index(root, explicit) is True
    assert kb_reindex.read_manifest(root)["packs"]["everything"]["left_out"] == []
    assert "Left out" not in (root / ".repomix/PACKS_STATUS.md").read_text("utf-8")
    assert kb_status._index_items(root) == []


def test_output_that_is_not_xml_is_not_compared(tmp_path: Path, monkeypatch):
    root = _kb(tmp_path)
    _write(root, "knowledge/domain/a.md", "PUBLIC\n")
    _fake_repomix(monkeypatch)  # plain concatenation, no <files> section
    explicit = {"packs": [{"name": "everything", "include": ["knowledge/**/*.md"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is True
    assert kb_reindex.read_manifest(root)["packs"]["everything"]["left_out"] == []


def test_privacy_floor_holds_without_repomix_default_patterns(tmp_path: Path, monkeypatch):
    """Q10: repomix.config.json switches off repomix's own defaults and a
    catch-all pack asks for everything — .git/ and node_modules/ stay out."""
    root = _kb(tmp_path)
    _write(
        root,
        "repomix.config.json",
        json.dumps(
            {"ignore": {"useGitignore": False, "useDefaultPatterns": False, "customPatterns": []}}
        ),
    )
    _write(root, ".git/config", "[remote] url = https://user:GIT-CREDENTIAL@host/x\n")
    _write(root, "node_modules/pkg/README.md", "NODE-MODULE-README\n")
    _write(root, "knowledge/domain/a.md", "PUBLIC-KNOWLEDGE\n")
    _fake_repomix(monkeypatch)

    explicit = {"packs": [{"name": "everything", "include": ["**/*.md", "**/*"]}]}
    assert kb_reindex.run_pack_index(root, explicit) is True

    cfg = json.loads((root / ".repomix/configs/everything.json").read_text("utf-8"))
    assert {".git/**", "node_modules/**"} <= set(cfg["ignore"]["customPatterns"])
    text = (root / ".repomix/everything.xml").read_text("utf-8")
    assert "PUBLIC-KNOWLEDGE" in text and "NODE-MODULE-README" not in text
    members = kb_reindex.read_manifest(root)["packs"]["everything"]["files"]
    assert not [m for m in members if m.startswith((".git/", "node_modules/"))]
