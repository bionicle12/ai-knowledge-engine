"""Tests for kb_lint reference implementation."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import kb_common as kbc
import kb_lint


def _make_page(
    knowledge: Path,
    relpath: str,
    *,
    body: str = "# Page\n\ncontent\n",
    **frontmatter,
) -> Path:
    p = knowledge / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "source": "raw/example.md",
        "extracted_at": dt.date.today().isoformat(),
        "tags": ["test"],
        "lifecycle": "evolving",
    }
    fm.update(frontmatter)
    kbc.write_frontmatter_file(p, fm, body)
    return p


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "knowledge").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# frontmatter check
# ---------------------------------------------------------------------------


def test_frontmatter_ok(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/caching.md")
    _make_page(kb_root / "knowledge", "principles/quality.md")
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "frontmatter"]


def test_frontmatter_missing_fields(kb_root: Path, tmp_path: Path):
    p = kb_root / "knowledge" / "domain" / "broken.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\nsource: raw/x.md\n---\nbody\n", encoding="utf-8")
    report = kb_lint.run_lint(kb_root)
    issues = [i for i in report.issues if i.check == "frontmatter"]
    assert any("missing required fields" in i.message for i in issues)
    assert any("lifecycle" in i.message for i in issues)


def test_frontmatter_invalid_lifecycle(kb_root: Path):
    _make_page(kb_root / "knowledge", "x.md", lifecycle="bogus")
    report = kb_lint.run_lint(kb_root)
    assert any(
        i.check == "frontmatter" and "invalid lifecycle" in i.message
        for i in report.issues
    )


def test_frontmatter_autofix(kb_root: Path):
    p = kb_root / "knowledge" / "x.md"
    p.write_text("---\nsource: raw/x.md\n---\nbody\n", encoding="utf-8")
    report = kb_lint.run_lint(kb_root, fix=True)
    # After autofix, missing tags+lifecycle+extracted_at should be gone
    meta, _ = kbc.read_frontmatter_file(p)
    assert "lifecycle" in meta and meta["lifecycle"] == "evolving"
    assert "tags" in meta
    assert "extracted_at" in meta
    assert any("frontmatter:" in entry for entry in report.fixed)


# ---------------------------------------------------------------------------
# stale check
# ---------------------------------------------------------------------------


def test_stale_warns_old_pages(kb_root: Path):
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    # THE stale rule dates a page by the newer of last_verified/extracted_at.
    _make_page(kb_root / "knowledge", "stale.md", last_verified=old, extracted_at=old)
    report = kb_lint.run_lint(kb_root, stale_days=30)
    assert any(i.check == "stale" for i in report.issues)


def test_stale_skips_permanent(kb_root: Path):
    old = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    _make_page(
        kb_root / "knowledge",
        "principles/style.md",
        last_verified=old,
        lifecycle="permanent",
    )
    report = kb_lint.run_lint(kb_root, stale_days=30)
    assert not [i for i in report.issues if i.check == "stale"]


# ---------------------------------------------------------------------------
# broken-link check
# ---------------------------------------------------------------------------


def test_broken_link_reported(kb_root: Path):
    _make_page(
        kb_root / "knowledge",
        "domain/a.md",
        body="see [[ghost]]\n",
    )
    report = kb_lint.run_lint(kb_root)
    assert any(i.check == "broken-link" and "ghost" in i.message for i in report.issues)


def test_broken_link_resolves_existing(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/target.md")
    _make_page(
        kb_root / "knowledge",
        "domain/source.md",
        body="see [[target]]\n",
    )
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "broken-link"]


def test_broken_link_full_path(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/target.md")
    _make_page(
        kb_root / "knowledge",
        "domain/source.md",
        body="see [[domain/target]]\n",
    )
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "broken-link"]


# ---------------------------------------------------------------------------
# orphan check
# ---------------------------------------------------------------------------


def test_orphan_detected(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/a.md", body="see [[b]]\n")
    _make_page(kb_root / "knowledge", "domain/b.md")
    _make_page(kb_root / "knowledge", "domain/lonely.md")
    report = kb_lint.run_lint(kb_root)
    orphans = [i.path for i in report.issues if i.check == "orphan"]
    # 'a' is orphan (nothing links to it), 'lonely' is orphan, 'b' is linked
    assert any("lonely" in p for p in orphans)


def test_orphan_skips_routing_pages(kb_root: Path):
    _make_page(kb_root / "knowledge", "routing-table.md")
    _make_page(kb_root / "knowledge", "routing/rt-x.md")
    report = kb_lint.run_lint(kb_root)
    orphans = [i.path for i in report.issues if i.check == "orphan"]
    assert not any("routing-table" in p for p in orphans)
    assert not any("rt-x" in p for p in orphans)


# ---------------------------------------------------------------------------
# duplicate-slug
# ---------------------------------------------------------------------------


def test_duplicate_slug(kb_root: Path):
    _make_page(kb_root / "knowledge", "a/shared.md")
    _make_page(kb_root / "knowledge", "b/shared.md")
    report = kb_lint.run_lint(kb_root)
    assert any(i.check == "duplicate-slug" for i in report.issues)


# ---------------------------------------------------------------------------
# source-hash
# ---------------------------------------------------------------------------


def test_source_hash_match(kb_root: Path):
    asset = kb_root / "raw" / "x.pdf"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"content")
    h = kbc.compute_source_hash(asset)
    _make_page(
        kb_root / "knowledge",
        "domain/from-x.md",
        source="raw/x.pdf",
        source_hash=h,
    )
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "source-hash"]


def test_source_hash_mismatch(kb_root: Path):
    asset = kb_root / "raw" / "x.pdf"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"content")
    _make_page(
        kb_root / "knowledge",
        "domain/from-x.md",
        source="raw/x.pdf",
        source_hash="sha256:0000000000000000",
    )
    report = kb_lint.run_lint(kb_root)
    assert any(i.check == "source-hash" and "mismatch" in i.message for i in report.issues)


def test_source_hash_skips_permanent(kb_root: Path):
    _make_page(
        kb_root / "knowledge",
        "principles/song.md",
        source="raw/never.txt",
        source_hash="sha256:1234",
        lifecycle="permanent",
    )
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "source-hash"]


# ---------------------------------------------------------------------------
# expired-temporal
# ---------------------------------------------------------------------------


def test_expired_temporal(kb_root: Path):
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    _make_page(
        kb_root / "knowledge",
        "decisions/q1.md",
        lifecycle="temporal",
        valid_until=yesterday,
    )
    report = kb_lint.run_lint(kb_root)
    assert any(i.check == "expired-temporal" for i in report.issues)


def test_temporal_still_valid_no_warning(kb_root: Path):
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    _make_page(
        kb_root / "knowledge",
        "decisions/q1.md",
        lifecycle="temporal",
        valid_until=future,
    )
    report = kb_lint.run_lint(kb_root)
    assert not [i for i in report.issues if i.check == "expired-temporal"]


# ---------------------------------------------------------------------------
# domain-overflow
# ---------------------------------------------------------------------------


def test_domain_overflow(kb_root: Path):
    for i in range(20):
        _make_page(kb_root / "knowledge", f"domain/p{i}.md")
    report = kb_lint.run_lint(kb_root, domain_overflow=15)
    assert any(i.check == "domain-overflow" for i in report.issues)


# ---------------------------------------------------------------------------
# annotation-overflow
# ---------------------------------------------------------------------------


def test_annotation_overflow(kb_root: Path):
    annotations = [{"date": "2026-05-01", "related": f"x{i}"} for i in range(7)]
    _make_page(
        kb_root / "knowledge",
        "domain/busy.md",
        context_annotations=annotations,
    )
    report = kb_lint.run_lint(kb_root, annotation_overflow=5)
    assert any(i.check == "annotation-overflow" for i in report.issues)


# ---------------------------------------------------------------------------
# only / quick
# ---------------------------------------------------------------------------


def test_only_filter(kb_root: Path):
    p = kb_root / "knowledge" / "x.md"
    p.write_text("---\nsource: raw/x.md\n---\nbody [[ghost]]\n", encoding="utf-8")
    # Run only 'frontmatter' — broken-link must not show up
    report = kb_lint.run_lint(kb_root, only={"frontmatter"})
    assert all(i.check == "frontmatter" for i in report.issues)


def test_quick_strips_warnings(kb_root: Path):
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    _make_page(kb_root / "knowledge", "x.md", last_verified=old)  # warning
    p = kb_root / "knowledge" / "broken.md"
    p.write_text("---\nsource: raw/x.md\n---\nbody\n", encoding="utf-8")  # error
    report = kb_lint.run_lint(kb_root, quick=True)
    assert all(i.severity == "error" for i in report.issues)


def test_exit_code_logic():
    r = kb_lint.LintReport(root="/tmp")
    assert kb_lint.exit_code(r) == 0
    r.issues.append(
        kb_lint.LintIssue(check="x", severity="warning", path="p", message="m")
    )
    assert kb_lint.exit_code(r) == 1
    r.issues.append(
        kb_lint.LintIssue(check="x", severity="error", path="p", message="m")
    )
    assert kb_lint.exit_code(r) == 2


# ---------------------------------------------------------------------------
# Health metrics (--metrics)
# ---------------------------------------------------------------------------


def test_metrics_basic(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/a.md", importance=8, lifecycle="permanent")
    _make_page(kb_root / "knowledge", "domain/b.md", importance=5, lifecycle="evolving")
    _make_page(kb_root / "knowledge", "decisions/c.md", importance=3, lifecycle="temporal")
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    assert m is not None
    assert m["total_pages"] == 3
    assert m["by_lifecycle"]["permanent"] == 1
    assert m["by_lifecycle"]["evolving"] == 1
    assert m["by_lifecycle"]["temporal"] == 1
    assert m["importance"]["avg"] == round((8 + 5 + 3) / 3, 2)


def test_metrics_orphan_rate(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/a.md")
    _make_page(kb_root / "knowledge", "domain/b.md", body="see [[a]]\n")
    _make_page(kb_root / "knowledge", "domain/lonely.md")
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    # 'a' has inbound from b; 'b' has no inbound; 'lonely' has no inbound
    assert m["orphan_rate"] == round(2 / 3, 3)


def test_metrics_freshness_buckets(kb_root: Path):
    today = dt.date.today()
    _make_page(kb_root / "knowledge", "fresh.md",
               last_verified=today.isoformat())
    _make_page(kb_root / "knowledge", "stale.md",
               last_verified=(today - dt.timedelta(days=45)).isoformat())
    _make_page(kb_root / "knowledge", "very_stale.md",
               last_verified=(today - dt.timedelta(days=120)).isoformat())
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    assert m["freshness"]["fresh_le_30d"] == 1
    assert m["freshness"]["stale_30_90d"] == 1
    assert m["freshness"]["very_stale_gt_90d"] == 1


def test_metrics_wikilink_density(kb_root: Path):
    _make_page(kb_root / "knowledge", "x.md", body="see [[y]] and [[z]]\n")
    _make_page(kb_root / "knowledge", "y.md", body="see [[z]]\n")
    _make_page(kb_root / "knowledge", "z.md")
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    # 3 wikilinks across 3 pages = 1.0
    assert m["wikilink_density"] == 1.0


def test_metrics_insight_ratio(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/a.md")
    _make_page(kb_root / "knowledge", "domain/b.md")
    _make_page(kb_root / "knowledge", "playbooks/c.md")
    _make_page(kb_root / "knowledge", "insights/d.md")
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    # 1 insight out of 4 in (domain+playbooks+insights) = 0.25
    assert m["insight_ratio"] == 0.25


def test_metrics_routing_depth(kb_root: Path):
    _make_page(kb_root / "knowledge", "routing-table.md")
    _make_page(kb_root / "knowledge", "routing/rt-x.md")
    report = kb_lint.run_lint(kb_root, metrics=True)
    m = report.metrics
    assert m["routing"]["pages"] == 1   # rt-x is in routing/
    assert m["routing"]["max_depth"] == 2  # routing/rt-x.md → 2 parts


def test_metrics_disabled_by_default(kb_root: Path):
    _make_page(kb_root / "knowledge", "x.md")
    report = kb_lint.run_lint(kb_root)
    assert report.metrics is None


def test_metrics_text_output_includes_section(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/a.md", importance=7)
    report = kb_lint.run_lint(kb_root, metrics=True)
    text = kb_lint.render_text(report)
    assert "Health metrics" in text
    assert "Lifecycle distribution" in text
    assert "Importance" in text


# ---------------------------------------------------------------------------
# robustness: unreadable files must not crash the run
# ---------------------------------------------------------------------------


def test_unreadable_file_reported_not_crashing(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/good.md")
    bad = kb_root / "knowledge" / "domain" / "garbage.md"
    bad.write_bytes(b"\xff\xfe\x00\x01 not valid utf-8 \xf0\x28\x8c\x28")

    report = kb_lint.run_lint(kb_root)

    unreadable = [i for i in report.issues if i.check == "unreadable"]
    assert len(unreadable) == 1
    assert "garbage.md" in unreadable[0].path
    assert report.pages_scanned == 2  # broken file still counted as scanned


def _write_agents(root: Path, body: str) -> Path:
    p = root / "AGENTS.md"
    p.write_text(body, encoding="utf-8")
    return p


def _wrapped(forbidden: str, language: str) -> str:
    return (
        f"<!-- AI-KE:INVARIANT:BEGIN id=\"forbidden\" -->\n{forbidden}\n"
        f"<!-- AI-KE:INVARIANT:END id=\"forbidden\" -->\n"
        f"<!-- AI-KE:INVARIANT:BEGIN id=\"language\" -->\n{language}\n"
        f"<!-- AI-KE:INVARIANT:END id=\"language\" -->\n"
    )


def test_invariants_error_when_markers_missing(kb_root: Path):
    _write_agents(kb_root, "## Forbidden\n\n- no wrap\n\n## Language\nen\n")
    report = kb_lint.run_lint(kb_root, only={"invariants"})
    issues = [i for i in report.issues if i.check == "invariants"]
    assert issues and issues[0].severity == "error"
    assert "forbidden" in issues[0].message


def test_invariants_ok_when_required_blocks_present(kb_root: Path):
    _write_agents(kb_root, _wrapped("## Forbidden\n- x\n", "## Language\nen\n"))
    report = kb_lint.run_lint(kb_root, only={"invariants"})
    assert not [i for i in report.issues if i.check == "invariants"]


def test_agents_bytes_warns_over_config_threshold(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "instructions_lint:\n  agents_max_bytes: 32\n",
        encoding="utf-8",
    )
    _write_agents(kb_root, _wrapped("## Forbidden\n", "## Language\n") + ("x" * 40))
    report = kb_lint.run_lint(kb_root, only={"agents-bytes"})
    issues = [i for i in report.issues if i.check == "agents-bytes"]
    assert issues and issues[0].severity == "warning"
    assert "!refactor" in issues[0].message


def test_instruction_absolutes_ignore_invariant_bodies(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "instructions_lint:\n  absolute_max_outside_invariants: 1\n",
        encoding="utf-8",
    )
    inside = "never always must forbidden never always must forbidden\n"
    _write_agents(
        kb_root,
        _wrapped(f"## Forbidden\n{inside}", "## Language\n") + "You must also skim voice.\n",
    )
    report = kb_lint.run_lint(kb_root, only={"instruction-absolutes"})
    # only the one "must" outside the block — under the threshold of 1? wait 1 means >1
    # threshold 1 → count > 1 warns. one "must" should be ok.
    assert not [i for i in report.issues if i.check == "instruction-absolutes"]


def test_instruction_absolutes_warns_when_over_threshold(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "instructions_lint:\n  absolute_max_outside_invariants: 1\n",
        encoding="utf-8",
    )
    _write_agents(
        kb_root,
        _wrapped("## Forbidden\n", "## Language\n")
        + "You must always never skip this.\n",
    )
    report = kb_lint.run_lint(kb_root, only={"instruction-absolutes"})
    issues = [i for i in report.issues if i.check == "instruction-absolutes"]
    assert issues and issues[0].severity == "warning"


def test_work_ordering_phrases_warn(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "instructions_lint:\n  work_ordering_phrases:\n    - thoroughly\n",
        encoding="utf-8",
    )
    _write_agents(
        kb_root,
        _wrapped("## Forbidden\n", "## Language\n") + "Review this thoroughly.\n",
    )
    report = kb_lint.run_lint(kb_root, only={"work-ordering"})
    issues = [i for i in report.issues if i.check == "work-ordering"]
    assert issues and issues[0].severity == "warning"
    assert "thoroughly" in issues[0].message


def test_instruction_duplicates_info(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "privacy:\n  raw_indexing_allowed: false\n",
        encoding="utf-8",
    )
    _write_agents(
        kb_root,
        "## Notes\n- Do not index `raw/` directly\n\n"
        + _wrapped("## Forbidden\n- x\n", "## Language\n"),
    )
    report = kb_lint.run_lint(kb_root, only={"instruction-duplicates"})
    issues = [i for i in report.issues if i.check == "instruction-duplicates"]
    assert issues and issues[0].severity == "info"


def test_instruction_duplicates_ignores_invariant_blocks(kb_root: Path):
    """A privacy rule inside an INVARIANT is the design (B1), not debt."""
    (kb_root / "kb.config.yml").write_text(
        "privacy:\n  raw_indexing_allowed: false\n"
        "language_policy:\n  primary: en\n",
        encoding="utf-8",
    )
    _write_agents(
        kb_root,
        _wrapped(
            "## Forbidden\n- Do not index `raw/` directly\n",
            "## Language\n\nPrimary language: **en**.\n",
        ),
    )
    report = kb_lint.run_lint(kb_root, only={"instruction-duplicates"})
    assert [i for i in report.issues if i.check == "instruction-duplicates"] == []


def test_instructions_review_stale_warns(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "instructions_review:\n  reviewed_at: 2020-01-01\n"
        "instructions_lint:\n  review_stale_days: 90\n",
        encoding="utf-8",
    )
    _write_agents(kb_root, _wrapped("## Forbidden\n", "## Language\n"))
    report = kb_lint.run_lint(kb_root, only={"instructions-review"})
    issues = [i for i in report.issues if i.check == "instructions-review"]
    assert issues and issues[0].severity == "warning"


def test_assumption_hotspot_info_when_area_repeats(kb_root: Path):
    from datetime import date

    day = date.today().isoformat()
    folder = kb_root / "interactions" / "sessions" / f"{day}__x"
    folder.mkdir(parents=True)
    bullets = "\n".join(
        f"- parked note in `domain/` because routing was unclear ({i})"
        for i in range(4)
    )
    (folder / f"{day}__summary.md").write_text(
        f"---\nsession_date: {day}\n---\n\n# S\n\n## Assumptions\n"
        + bullets
        + "\n",
        encoding="utf-8",
    )
    report = kb_lint.run_lint(kb_root, only={"assumption-hotspot"})
    issues = [i for i in report.issues if i.check == "assumption-hotspot"]
    assert issues and issues[0].severity == "info"
    assert "domain" in issues[0].message


def test_profile_review_stale_warns(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "profile_review:\n  reviewed_at: 2020-01-01\n",
        encoding="utf-8",
    )
    report = kb_lint.run_lint(kb_root, only={"profile-review"})
    issues = [i for i in report.issues if i.check == "profile-review"]
    assert issues and issues[0].severity == "warning"


def test_instruction_checks_are_registered():
    for name in (
        "invariants",
        "agents-bytes",
        "instruction-absolutes",
        "work-ordering",
        "instruction-duplicates",
        "instructions-review",
        "assumption-hotspot",
        "profile-review",
    ):
        assert name in kb_lint.ALL_CHECKS


def test_instruction_checks_skip_when_agents_md_missing(kb_root: Path):
    report = kb_lint.run_lint(
        kb_root,
        only={
            "invariants",
            "agents-bytes",
            "instruction-absolutes",
            "work-ordering",
            "instruction-duplicates",
            "instructions-review",
            "assumption-hotspot",
            "profile-review",
        },
    )
    assert report.issues == []


def test_bom_page_parses_cleanly(kb_root: Path):
    p = kb_root / "knowledge" / "domain" / "bom.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "---\nsource: raw/x.md\nextracted_at: 2026-08-01\n"
        "tags: [t]\nlifecycle: evolving\n---\n# T\n\nbody\n"
    )
    p.write_text(content, encoding="utf-8-sig")

    report = kb_lint.run_lint(kb_root, only={"frontmatter"})

    assert not report.issues  # BOM must not hide the frontmatter


# ---------------------------------------------------------------------------
# 0.16 audit regressions (Q5, Q12, Q13, Q17, I6, I11, D4, D9)
# ---------------------------------------------------------------------------


def _issues(report, check: str) -> list:
    return [i for i in report.issues if i.check == check]


def _old(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def _posix(path: str) -> str:
    return path.replace("\\", "/")


@pytest.mark.parametrize(
    "frontmatter",
    [
        "source: raw/x.md\ntags: [x, y\nlifecycle: permanent\n",  # unclosed list (Q5)
        "- just\n- a list\n",                                      # not a mapping (Q12)
        "source: " + "[" * 300 + "\n",                             # nesting bomb
    ],
    ids=["unclosed-list", "list-frontmatter", "deep-nesting"],
)
def test_fix_leaves_unparsable_frontmatter_alone(kb_root: Path, frontmatter: str):
    page = kb_root / "knowledge" / "domain" / "broken.md"
    page.parent.mkdir(parents=True)
    original = f"---\n{frontmatter}---\n# Body\n"
    page.write_text(original, encoding="utf-8")

    report = kb_lint.run_lint(kb_root, fix=True)

    assert page.read_text(encoding="utf-8") == original
    assert not report.fixed
    yaml_errors = _issues(report, "frontmatter-yaml")
    assert len(yaml_errors) == 1 and not yaml_errors[0].fixable
    assert not _issues(report, "frontmatter")  # no "missing fields (fixable)"


def test_unclosed_frontmatter_is_reported_not_fixed(kb_root: Path):
    page = kb_root / "knowledge" / "domain" / "open.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource: raw/x.md\n# never closed\n", encoding="utf-8")
    report = kb_lint.run_lint(kb_root, fix=True)
    assert "not closed" in _issues(report, "frontmatter-yaml")[0].message
    assert page.read_text(encoding="utf-8") == "---\nsource: raw/x.md\n# never closed\n"


def test_wrong_field_types_do_not_crash_the_run(kb_root: Path):
    asset = kb_root / "raw" / "a.md"
    asset.parent.mkdir(parents=True)
    asset.write_text("a\n", encoding="utf-8")
    k = kb_root / "knowledge"
    _make_page(k, "domain/multi-source.md", source=["raw/a.md", "raw/b.md"],
               source_hash="sha256:0000")
    _make_page(k, "domain/old-a.md")
    _make_page(k, "domain/old-b.md")
    _make_page(k, "domain/new.md", supersedes=["old-a", "old-b"],
               lifecycle="temporal", body="[[old-a]] [[old-b]] [[multi-source]]\n")
    _make_page(k, "domain/odd.md", supersedes={"x": 1}, citations="nope",
               lifecycle=["evolving"])

    report = kb_lint.run_lint(kb_root, metrics=True)

    types = {(_posix(i.path), i.message.split("`")[1])
             for i in _issues(report, "frontmatter-type")}
    assert ("knowledge/domain/multi-source.md", "source") in types
    assert ("knowledge/domain/odd.md", "supersedes") in types
    assert ("knowledge/domain/odd.md", "citations") in types
    superseded = {_posix(i.path) for i in _issues(report, "superseded")}
    assert superseded == {"knowledge/domain/old-a.md", "knowledge/domain/old-b.md"}
    assert report.metrics["by_lifecycle"]["unset"] == 1


def test_a_crash_on_one_page_is_isolated(kb_root: Path, monkeypatch):
    k = kb_root / "knowledge"
    _make_page(k, "domain/bad.md", last_verified=_old(99), extracted_at=_old(99))
    _make_page(k, "domain/good.md", last_verified=_old(99), extracted_at=_old(99),
               body="[[bad]]\n")
    real = kb_lint._check_stale

    def flaky(page, ctx):
        if page.path.name == "bad.md":
            raise RuntimeError("boom")
        real(page, ctx)

    monkeypatch.setattr(kb_lint, "_check_stale", flaky)
    report = kb_lint.run_lint(kb_root)
    stale = {(_posix(i.path), i.severity) for i in _issues(report, "stale")}
    assert ("knowledge/domain/bad.md", "error") in stale
    assert ("knowledge/domain/good.md", "warning") in stale


def test_broken_config_is_one_error_not_a_crash(kb_root: Path):
    (kb_root / "kb.config.yml").write_text("lifecycle: [unclosed\n", encoding="utf-8")
    _make_page(kb_root / "knowledge", "domain/a.md", body="[[ghost]]\n")
    report = kb_lint.run_lint(kb_root)
    assert _issues(report, "config")[0].severity == "error"
    assert _issues(report, "broken-link")


def test_cli_crash_exits_2_not_warnings(kb_root: Path):
    (kb_root / "lint-report.md").mkdir()  # the report cannot be written
    result = subprocess.run(
        [sys.executable, str(Path(kb_lint.__file__)), "--root", str(kb_root),
         "--output", "report"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 2, result.stderr


def test_wikilink_forms_resolve(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "domain/target.md", body="[[source]]\n")
    _make_page(
        k, "domain/source.md",
        body=(
            "[[target#section]] [[target.md]] [[knowledge/domain/target]] "
            "[[Target]] [[domain/TARGET|alias]] ![[diagram.png]]\n"
            "`[[in-inline-code]]`\n```\n[[in-fenced-code]]\n```\n"
        ),
    )
    report = kb_lint.run_lint(kb_root)
    assert not _issues(report, "broken-link"), report.issues


def test_case_insensitive_link_counts_as_inbound(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "domain/hub.md", body="[[Leaf]]\n")
    _make_page(k, "domain/leaf.md", body="[[hub]]\n")
    report = kb_lint.run_lint(kb_root)
    assert not _issues(report, "orphan")


def test_archive_is_not_orphan_stale_or_duplicate(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "_archive/old-page.md", last_verified=_old(400), extracted_at=_old(400))
    _make_page(k, "_archive/shared.md")
    _make_page(k, "domain/shared.md", body="[[hub]]\n")
    _make_page(k, "domain/hub.md", body="[[shared]]\n")
    report = kb_lint.run_lint(kb_root)
    assert not _issues(report, "orphan")
    assert not _issues(report, "stale")
    assert not _issues(report, "duplicate-slug")


def test_source_hash_is_cached_per_run_and_across_runs(kb_root: Path, monkeypatch):
    asset = kb_root / "assets" / "big.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"x" * 1000)
    digest = kbc.compute_source_hash(asset)
    for i in range(3):
        _make_page(kb_root / "knowledge", f"domain/p{i}.md",
                   source="assets/big.bin", source_hash=digest)
    calls: list[Path] = []
    real = kbc.compute_source_hash

    def counting(path, *args, **kwargs):
        calls.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(kbc, "compute_source_hash", counting)
    assert not _issues(kb_lint.run_lint(kb_root, quick=True), "source-hash")
    assert len(calls) == 1  # three pages, one source → hashed once
    assert not _issues(kb_lint.run_lint(kb_root, quick=True), "source-hash")
    assert len(calls) == 1  # unchanged source → served from .kb-state/
    assert (kb_root / ".kb-state" / "lint-hash-cache.json").is_file()

    asset.write_bytes(b"y" * 1001)
    report = kb_lint.run_lint(kb_root, quick=True)
    assert len(calls) == 2
    assert len(_issues(report, "source-hash")) == 3


def test_quick_skips_warning_only_checks(kb_root: Path, monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(kb_lint, "_check_stale", lambda page, ctx: called.append("stale"))
    monkeypatch.setattr(kb_lint, "_check_orphans", lambda pages, ctx: called.append("orphan"))
    _make_page(kb_root / "knowledge", "domain/a.md")
    report = kb_lint.run_lint(kb_root, quick=True)
    assert called == []
    assert report.scope == "quick"


def test_valid_until_in_future_is_not_stale(kb_root: Path):
    future = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    _make_page(kb_root / "knowledge", "domain/fact.md",
               last_verified=_old(300), extracted_at=_old(300), valid_until=future)
    assert not _issues(kb_lint.run_lint(kb_root), "stale")


def test_folder_lifecycle_policy_and_config_threshold(kb_root: Path):
    k = kb_root / "knowledge"
    for rel in ("decisions/adr-1.md", "profile/me.md", "principles/p.md"):
        _make_page(k, rel, last_verified=_old(200), extracted_at=_old(200))
    _make_page(k, "domain/recent.md", last_verified=_old(20), extracted_at=_old(20))
    assert not _issues(kb_lint.run_lint(kb_root), "stale")

    (kb_root / "kb.config.yml").write_text(
        "lifecycle:\n  stale_warning_days: 10\n", encoding="utf-8"
    )
    stale = [_posix(i.path) for i in _issues(kb_lint.run_lint(kb_root), "stale")]
    assert stale == ["knowledge/domain/recent.md"]


def test_fix_uses_configured_default_lifecycle(kb_root: Path):
    (kb_root / "kb.config.yml").write_text(
        "lifecycle:\n  default: temporal\n", encoding="utf-8"
    )
    page = kb_root / "knowledge" / "x.md"
    page.write_text("---\nsource: raw/x.md\n---\nbody\n", encoding="utf-8")
    report = kb_lint.run_lint(kb_root, fix=True)
    meta, _ = kbc.read_frontmatter_file(page)
    assert meta["lifecycle"] == "temporal"
    assert [_posix(f) for f in report.fixed] == [
        "frontmatter:knowledge/x.md (extracted_at+tags+lifecycle defaults applied)"
    ]


def test_generated_pages_are_not_stale_or_orphan(kb_root: Path):
    _make_page(kb_root / "knowledge", "domain/generated.md",
               generated_by="kb_route.py", last_verified=_old(99), extracted_at=_old(99))
    report = kb_lint.run_lint(kb_root)
    assert not _issues(report, "stale")
    assert not _issues(report, "orphan")


def test_stock_empty_folders_are_compatibility_shelves(kb_root: Path):
    for name in kbc.KNOWLEDGE_DIRS:
        (kb_root / "knowledge" / name).mkdir()
    (kb_root / "knowledge" / "my-custom").mkdir()
    empty = [_posix(i.path) for i in _issues(kb_lint.run_lint(kb_root), "empty-category")]
    assert empty == ["knowledge/my-custom/"]


def test_archive_does_not_overflow(kb_root: Path):
    for i in range(20):
        _make_page(kb_root / "knowledge", f"_archive/p{i}.md")
    assert not _issues(kb_lint.run_lint(kb_root), "domain-overflow")


def test_nested_archive_does_not_overflow(kb_root: Path):
    k = kb_root / "knowledge"
    for i in range(10):
        _make_page(k, f"work/p{i}.md")
        _make_page(k, f"work/_archive/old{i}.md")
        _make_page(k, f"work/sub/_archive/older{i}.md")
    assert not _issues(kb_lint.run_lint(kb_root), "domain-overflow")
    for i in range(10, 16):
        _make_page(k, f"work/p{i}.md")
    hits = _issues(kb_lint.run_lint(kb_root), "domain-overflow")
    assert [(_posix(i.path), i.message.split(" ")[0]) for i in hits] == [("knowledge/work/", "16")]


def test_source_hash_never_reads_outside_the_base(kb_root: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "id_rsa"
    outside.write_text("secret key\n", encoding="utf-8")
    link = kb_root / "raw" / "innocent.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    k = kb_root / "knowledge"
    rel = os.path.relpath(outside, kb_root)
    _make_page(k, "domain/a.md", source=rel, source_hash="sha256:00")
    _make_page(k, "domain/b.md", source="raw/innocent.txt", source_hash="sha256:00")
    report = kb_lint.run_lint(kb_root)
    hits = _issues(report, "source-hash")
    assert [(i.severity, "outside this base" in i.message) for i in hits] == [
        ("warning", True), ("warning", True)
    ]
    real = kbc.compute_source_hash(outside)
    assert all(real not in i.message for i in hits)
    cache = kb_root / ".kb-state" / kb_lint.HASH_CACHE_FILENAME
    assert not cache.exists() or str(outside) not in cache.read_text(encoding="utf-8")


def test_partial_path_wikilink_resolves_like_obsidian(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "work/sub/deep.md", body="[[adv]]\n")
    _make_page(k, "domain/adv.md", body="[[sub/deep]] [[Work/Sub/Deep#part]]\n")
    report = kb_lint.run_lint(kb_root)
    assert not _issues(report, "broken-link"), report.issues
    assert not _issues(report, "orphan"), report.issues
    _make_page(k, "domain/bad.md", body="[[other/deep]] [[b/sub/deep]] [[adv]]\n")
    broken = [i.message for i in _issues(kb_lint.run_lint(kb_root), "broken-link")]
    assert len(broken) == 2, broken


def _script_copy(tmp_path: Path) -> Path:
    scripts = tmp_path / "base" / "scripts"
    shutil.copytree(
        Path(kb_lint.__file__).parent, scripts,
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    (scripts.parent / "knowledge").mkdir()
    return scripts


def test_cli_partial_upgrade_exits_2_with_a_message(tmp_path: Path):
    """A kept, older kb_common.py next to the updated kb_lint.py (Q6): lint
    must say so and exit 2, not die at import with a traceback and exit 1."""
    scripts = _script_copy(tmp_path)
    common = scripts / "kb_common.py"
    common.write_text(
        common.read_text(encoding="utf-8") + "\ndel LIFECYCLES\ndel stale_status\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-B", str(scripts / "kb_lint.py"), "--root", str(scripts.parent)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    assert "partial upgrade" in result.stderr
    assert "LIFECYCLES, stale_status" in result.stderr


def test_every_logged_operation_is_documented():
    """10_LOG.md's operation table names every operation a script logs."""
    scripts = Path(kb_lint.__file__).parent
    doc = scripts.parent / "10_LOG.md"
    if not doc.is_file():
        pytest.skip("10_LOG.md is not next to scripts/ (a deployed base)")
    table = set(re.findall(r"^\| `([a-z-]+)` \|", doc.read_text(encoding="utf-8"), re.M))
    logged: set[str] = set()
    for path in scripts.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        logged |= set(re.findall(r"\boperation=\"([a-z-]+)\"", text))
        logged |= set(re.findall(r"^[A-Z_]*OPERATION = \"([a-z-]+)\"", text, re.M))
    assert "lint" in logged
    assert logged <= table, sorted(logged - table)


def test_every_operation_the_modules_tell_the_agent_to_log_is_documented():
    """The runtime modules name agent-written operations (`Log operation
    `meta-review``); 10_LOG.md's table must list each one."""
    kit = Path(kb_lint.__file__).parent.parent
    doc = kit / "10_LOG.md"
    if not doc.is_file():
        pytest.skip("10_LOG.md is not next to scripts/ (a deployed base)")
    table = set(re.findall(r"^\| `([a-z-]+)` \|", doc.read_text(encoding="utf-8"), re.M))
    told: set[str] = set()
    for path in kit.glob("[0-9][0-9]_*.md"):
        text = " ".join(path.read_text(encoding="utf-8").split())
        told |= set(re.findall(r"\b[Ll]og operation `([a-z-]+)`", text))
    assert {"meta-review", "quiz", "refactor"} <= told
    assert told <= table, sorted(told - table)


def test_citation_validity(kb_root: Path):
    src = kb_root / "assets" / "documents" / "notes.md"
    src.parent.mkdir(parents=True)
    src.write_text("one\ntwo\nthree\n", encoding="utf-8")
    _make_page(
        kb_root / "knowledge", "domain/cited.md",
        citations=[
            {"claim": "ok", "source_span": "assets/documents/notes.md#L1-L3"},
            {"claim": "pdf", "source_span": "assets/documents/notes.md#page=3"},
            {"claim": "past end", "source_span": "assets/documents/notes.md#L2-L9"},
            {"claim": "gone", "source_span": "assets/documents/missing.pdf#page=1"},
            {"claim": "escape", "source_span": "../outside.md#L1"},
            {"claim": "no span"},
        ],
    )
    messages = [i.message for i in _issues(kb_lint.run_lint(kb_root), "citation")]
    assert len(messages) == 4, messages
    assert any("citations[2]" in m and "3 lines" in m for m in messages)
    assert any("citations[3]" in m and "missing.pdf" in m for m in messages)
    assert any("citations[4]" in m for m in messages)
    assert any("citations[5]" in m and "no source_span" in m for m in messages)


def test_low_importance_temporal_suggests_archive(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "domain/dusty.md", importance=2, lifecycle="temporal",
               last_accessed=_old(120))
    _make_page(k, "domain/used.md", importance=2, lifecycle="temporal",
               last_accessed=_old(10))
    _make_page(k, "domain/valuable.md", importance=8, lifecycle="temporal",
               last_accessed=_old(120))
    hits = _issues(kb_lint.run_lint(kb_root), "low-importance")
    assert [_posix(i.path) for i in hits] == ["knowledge/domain/dusty.md"]
    assert hits[0].severity == "info"


def test_russian_absolutes_are_counted(kb_root: Path):
    body = "Всегда отвечай кратко. Никогда не выдумывай. " * 5
    _write_agents(kb_root, _wrapped("f", "l") + body)
    report = kb_lint.run_lint(kb_root, only={"instruction-absolutes"})
    assert _issues(report, "instruction-absolutes")


def test_cli_logs_only_with_flag(kb_root: Path):
    (kb_root / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    _make_page(kb_root / "knowledge", "domain/a.md")
    log = kb_root / "log.md"
    kb_lint.main(["--root", str(kb_root)])
    assert not log.exists()
    kb_lint.main(["--root", str(kb_root), "--log"])
    text = log.read_text(encoding="utf-8")
    assert "] lint | Health-check" in text
    assert "- Checked: 1 pages" in text


def test_cli_writes_lint_summary(kb_root: Path):
    (kb_root / "kb.config.yml").write_text("knowledge_base:\n  name: t\n", encoding="utf-8")
    k = kb_root / "knowledge"
    _make_page(k, "domain/a.md", body="[[ghost]]\n")  # 1 error; orphan = warning
    summary = kb_root / ".kb-state" / "lint-summary.json"

    kb_lint.main(["--root", str(kb_root)])
    full = json.loads(summary.read_text(encoding="utf-8"))
    assert (full["errors"], full["warnings"], full["scope"]) == (1, 1, "full")
    assert full["full_at"] == full["at"]

    page = k / "domain" / "a.md"
    page.write_text(page.read_text(encoding="utf-8").replace("[[ghost]]", ""),
                    encoding="utf-8")
    kb_lint.main(["--root", str(kb_root), "--quick"])
    quick = json.loads(summary.read_text(encoding="utf-8"))
    assert (quick["errors"], quick["warnings"], quick["scope"]) == (0, 1, "quick")
    assert quick["full_at"] == full["at"]

    kb_lint.main(["--root", str(kb_root), "--only", "frontmatter"])
    assert json.loads(summary.read_text(encoding="utf-8")) == quick


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="needs a POSIX bash"
)
@pytest.mark.parametrize("wrapper", ["lint.sh", "doctor.sh"])
def test_wrapper_takes_python_from_kbpy(tmp_path: Path, wrapper: str):
    """shell/lint.sh and shell/doctor.sh source shell/_kbpy.sh ($KB_PYTHON
    first), run from the base root and pass arguments and exit status through."""
    shell_src = Path(kb_lint.__file__).resolve().parents[1] / "shell"
    base = tmp_path / "base"
    (base / "shell").mkdir(parents=True)
    for name in (wrapper, "_kbpy.sh"):
        shutil.copy2(shell_src / name, base / "shell" / name)
    script = "kb_lint.py" if wrapper == "lint.sh" else "kb_doctor.py"
    (base / "scripts").mkdir()
    (base / "scripts" / script).write_text("raise SystemExit(0)\n", encoding="utf-8")
    fake = tmp_path / "fake-python"
    fake.write_text('#!/bin/sh\necho "fake python $* in $(pwd -P)"\nexit 3\n',
                    encoding="utf-8")
    fake.chmod(0o755)

    result = subprocess.run(
        ["bash", str(base / "shell" / wrapper), "--quick"],
        cwd=str(tmp_path), env={**os.environ, "KB_PYTHON": str(fake)},
        capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert f"fake python scripts/{script} --quick in {base.resolve()}" in result.stdout


def test_cli_refuses_a_folder_that_is_not_a_base(kb_root: Path, capsys):
    """No kb.config.yml → exit 2 and no phantom .kb-state/ (M11), like the
    other pipeline scripts."""
    _make_page(kb_root / "knowledge", "domain/a.md", source_hash="0" * 64)
    assert kb_lint.main(["--root", str(kb_root)]) == 2
    assert "is not a knowledge base" in capsys.readouterr().err
    assert not (kb_root / ".kb-state").exists()


# ---------------------------------------------------------------------------
# secret check (E-H3): repomix drops such a page from the index silently
# ---------------------------------------------------------------------------

GH_TOKEN = "ghp_" + "A1b2C3d4E5" * 4


def test_secret_in_a_knowledge_page_is_an_error_without_the_value(kb_root: Path):
    k = kb_root / "knowledge"
    page = _make_page(k, "domain/deploy.md", body=f"# Deploy\n\ntoken {GH_TOKEN}\n")
    _make_page(k, "domain/clean.md", body="# Clean\n\nnothing here\n")
    lines = page.read_text(encoding="utf-8").splitlines()
    line = next(n for n, text in enumerate(lines, 1) if GH_TOKEN in text)
    report = kb_lint.run_lint(kb_root)
    issues = _issues(report, "secret")
    assert [(i.severity, i.path) for i in issues] == [
        ("error", os.path.join("knowledge", "domain", "deploy.md"))
    ]
    # Line numbers are the file's, frontmatter included.
    assert line > 4 and f"GitHub token (line {line})" in issues[0].message
    assert GH_TOKEN not in issues[0].message
    assert "review/needs-redaction/" in issues[0].message
    quick = kb_lint.run_lint(kb_root, quick=True)
    assert [i.check for i in quick.issues] == ["secret"]


def test_password_assignment_only_warns_and_scan_can_be_off(kb_root: Path):
    k = kb_root / "knowledge"
    _make_page(k, "domain/db.md", body="# DB\n\ndb_password: hunter2hunter\n")
    issues = _issues(kb_lint.run_lint(kb_root), "secret")
    assert [i.severity for i in issues] == ["warning"]
    assert "hunter2hunter" not in issues[0].message

    _make_page(k, "domain/deploy.md", body=f"token {GH_TOKEN}\n")
    (kb_root / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\nprivacy:\n  secret_scan: false\n", encoding="utf-8"
    )
    assert not _issues(kb_lint.run_lint(kb_root), "secret")
