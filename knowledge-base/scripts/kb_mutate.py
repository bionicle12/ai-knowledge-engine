#!/usr/bin/env python3
"""kb_mutate — plant known L1 defects and see which lint checks fire.

Copies the base (or a tiny seed) into a temp tree, applies seven L1
mutations, runs ``kb_lint.py``, and reports killed / survivors. No LLM.

L2 contradictions are out of scope (iteration D2 / ``!audit``).

See ``09_LINT.md``.
"""
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402
import kb_lint  # noqa: E402

_SKIP_COPY = {".venv", "venv", ".git", ".kb-backups", "node_modules", "__pycache__", ".repomix"}


@dataclass
class Mutation:
    id: str
    expected_check: str
    detail: str


@dataclass
class MutationReport:
    total: int = 0
    killed: list[str] = field(default_factory=list)
    survivors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    work: Path | None = None

    @property
    def line(self) -> str:
        return (
            f"{self.total} mutations / {len(self.killed)} killed / "
            f"{len(self.survivors)} survivors"
        )


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("broken-link", "broken-link", "plant [[no-such-mutate-page]]"),
    Mutation("duplicate-slug", "duplicate-slug", "same slug in two folders"),
    Mutation("source-hash", "source-hash", "wrong source_hash on a page"),
    Mutation("stale", "stale", "last_verified older than 30 days"),
    Mutation("orphan", "orphan", "drop all inbound wikilinks to a page"),
    Mutation("expired-temporal", "expired-temporal", "valid_until in the past"),
    Mutation("frontmatter", "frontmatter", "drop a required frontmatter field"),
)


def _write_md(path: Path, body: str, **meta: object) -> None:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            inner = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{inner}]")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", "", body.rstrip(), ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _copy_base(src: Path, dest: Path) -> None:
    def ignore(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n in _SKIP_COPY]

    if src.is_dir() and any(src.iterdir()):
        shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=True)


def seed_fixture(root: Path) -> None:
    """Write a tiny healthy cluster so all seven mutations have a target."""
    raw = root / "raw" / "reference" / "unsorted" / "mutate-src.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("seed source\n", encoding="utf-8")
    digest = kbc.compute_source_hash(raw)
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    common = dict(
        source="raw/reference/unsorted/mutate-src.md",
        extracted_at=today,
        tags=["mutate-seed"],
        lifecycle="evolving",
        last_verified=today,
        source_hash=digest,
    )
    _write_md(
        root / "knowledge" / "domain" / "mutate-alpha.md",
        "See [[mutate-beta]], [[mutate-gamma]], [[mutate-delta]], [[mutate-epsilon]].",
        **common,
    )
    _write_md(
        root / "knowledge" / "domain" / "mutate-beta.md",
        "See [[mutate-alpha]].",
        **common,
    )
    _write_md(
        root / "knowledge" / "insights" / "mutate-gamma.md",
        "Insight seed.",
        **common,
    )
    _write_md(
        root / "knowledge" / "playbooks" / "mutate-delta.md",
        "Playbook seed.",
        **{**common, "lifecycle": "temporal", "valid_until": future},
    )
    _write_md(
        root / "knowledge" / "decisions" / "mutate-epsilon.md",
        "Decision seed.",
        **common,
    )


def apply_mutations(root: Path) -> None:
    alpha = root / "knowledge" / "domain" / "mutate-alpha.md"
    text = alpha.read_text(encoding="utf-8")
    alpha.write_text(
        text.replace("[[mutate-gamma]]", "[[no-such-mutate-page]]"),
        encoding="utf-8",
    )
    # drop inbound to gamma (orphan) — the replace above already removed it
    beta = root / "knowledge" / "domain" / "mutate-beta.md"
    dest = root / "knowledge" / "playbooks" / "mutate-beta.md"
    dest.write_text(beta.read_text(encoding="utf-8"), encoding="utf-8")
    alpha.write_text(
        alpha.read_text(encoding="utf-8").replace(
            "source_hash: sha256:", "source_hash: sha256:deadbeef"
        ),
        encoding="utf-8",
    )
    old = (date.today() - timedelta(days=90)).isoformat()
    gamma = root / "knowledge" / "insights" / "mutate-gamma.md"
    gamma.write_text(
        gamma.read_text(encoding="utf-8").replace(
            f"last_verified: {date.today().isoformat()}",
            f"last_verified: {old}",
        ),
        encoding="utf-8",
    )
    delta = root / "knowledge" / "playbooks" / "mutate-delta.md"
    dtext = delta.read_text(encoding="utf-8")
    dtext = re.sub(r"valid_until:\s*\S+", "valid_until: 2020-01-01", dtext, count=1)
    delta.write_text(dtext, encoding="utf-8")
    epsilon = root / "knowledge" / "decisions" / "mutate-epsilon.md"
    lines = [
        ln
        for ln in epsilon.read_text(encoding="utf-8").splitlines()
        if not ln.startswith("source:")
    ]
    epsilon.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fired_checks(root: Path) -> set[str]:
    report = kb_lint.run_lint(root)
    return {issue.check for issue in report.issues}


def run_mutations(
    root: Path,
    *,
    work: Path | None = None,
    keep: bool = False,
) -> MutationReport:
    root = root.resolve()
    cleanup = work is None and not keep
    if work is None:
        work = Path(tempfile.mkdtemp(prefix="kb-mutate-"))
    work.mkdir(parents=True, exist_ok=True)
    _copy_base(root, work)
    seed_fixture(work)
    apply_mutations(work)
    fired = _fired_checks(work)
    out = MutationReport(total=len(MUTATIONS), work=work)
    for mut in MUTATIONS:
        if mut.expected_check in fired:
            out.killed.append(mut.id)
        else:
            out.survivors.append(mut.id)
    if cleanup:
        shutil.rmtree(work, ignore_errors=True)
        out.work = None
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — plant L1 defects and score lint"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--keep", action="store_true", help="keep the temp copy")
    parser.add_argument("--work", type=Path, default=None, help="use this dir as the copy")
    args = parser.parse_args(argv)
    root = (args.root or kbc.find_kb_root()).resolve()
    report = run_mutations(root, work=args.work, keep=args.keep)
    print(report.line)
    if report.killed:
        print("killed: " + ", ".join(report.killed))
    if report.survivors:
        print("survivors: " + ", ".join(report.survivors))
    if report.work:
        print(f"work: {report.work}")
    return 1 if report.survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
