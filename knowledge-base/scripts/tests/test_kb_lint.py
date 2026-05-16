"""Tests for kb_lint reference implementation."""
from __future__ import annotations

import datetime as dt
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
    _make_page(kb_root / "knowledge", "stale.md", last_verified=old)
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
