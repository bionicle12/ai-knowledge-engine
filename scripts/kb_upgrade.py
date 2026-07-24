#!/usr/bin/env python3
"""kb_upgrade — refresh reference scripts in a deployed knowledge base.

Compares a deployed KB's `instructions_version` (in `kb.config.yml`) with the
source repo's `VERSION`, then optionally syncs:

  * Reference Python scripts (`scripts/kb_*.py`)
  * Shell wrappers (`reindex.sh`, `watcher.sh`, `lint.sh`, `doctor.sh`)
  * The `repomix.config.json` template — if user accepts (it's parameterized)

User customizations are detected via SHA-256 comparison: if the deployed file's
hash matches the previous-version hash in the repo, it's a clean copy and is
overwritten with the new version. If it differs, the user has customized it
— the upgrade script writes a `.new` sibling and reports the divergence
without overwriting.

Usage:
    python3 scripts/kb_upgrade.py --kb-root /path/to/deployed-kb
    python3 scripts/kb_upgrade.py --kb-root . --dry-run
    python3 scripts/kb_upgrade.py --kb-root . --diff             # show diff
    python3 scripts/kb_upgrade.py --kb-root . --force            # ignore customization

Exit codes:
    0 — already up to date
    1 — upgraded successfully
    2 — manual merge required (customizations detected)
    3 — error (no kb.config.yml, etc.)
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_SCRIPTS_DIR = REPO_ROOT / "knowledge-base" / "scripts"
SRC_SHELL_DIR = REPO_ROOT / "knowledge-base" / "shell"
SRC_TEMPLATES_DIR = REPO_ROOT / "knowledge-base" / "templates"
VERSION_FILE = REPO_ROOT / "VERSION"

# Files that get refreshed in a deployed KB.
SCRIPT_FILES = (
    "kb_common.py",
    "kb_doctor.py",
    "kb_ingest.py",
    "kb_lint.py",
    "kb_nlp_batch.py",
    "kb_ocr.py",
    "kb_populate.py",
    "kb_reflect.py",
    "kb_reindex.py",
    "kb_save_session.py",
    "kb_stt.py",
    "kb_watch.py",
)

SHELL_FILES = (
    "reindex.sh",
    "watcher.sh",
    "lint.sh",
    "doctor.sh",
)


@dataclass
class UpgradePlan:
    name: str
    src: Path
    dst: Path
    state: str          # "missing" | "up_to_date" | "clean_overwrite" | "customized"
    diff_lines: int = 0


def file_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_repo_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text().strip()
    return "unknown"


def get_deployed_version(kb_root: Path) -> str:
    cfg = kb_root / "kb.config.yml"
    if not cfg.is_file():
        return "missing"
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        return data.get("instructions_version", "unknown")
    except Exception:  # noqa: BLE001
        return "unparseable"


def file_at_commit(repo_path: Path, commit: str) -> bytes | None:
    """Read `repo_path` (relative to repo root) at `commit` via git, or None."""
    if not commit or commit in ("unknown", "missing", "unparseable"):
        return None
    rel = str(repo_path.relative_to(REPO_ROOT))
    try:
        result = subprocess.run(
            ["git", "show", f"v{commit}:{rel}"],
            capture_output=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass
    return None


def compute_plan(
    src: Path, dst: Path, prev_version: str, force: bool
) -> UpgradePlan:
    name = src.name
    if not dst.is_file():
        return UpgradePlan(name=name, src=src, dst=dst, state="missing")
    if file_hash(src) == file_hash(dst):
        return UpgradePlan(name=name, src=src, dst=dst, state="up_to_date")
    # Try to fetch the previous-version content from git tag
    prev_blob = file_at_commit(src, prev_version)
    deployed_bytes = dst.read_bytes()
    if prev_blob is not None and prev_blob == deployed_bytes:
        # Deployed file matches the previous release exactly → clean overwrite is safe
        return UpgradePlan(name=name, src=src, dst=dst, state="clean_overwrite")
    if force:
        return UpgradePlan(name=name, src=src, dst=dst, state="clean_overwrite")
    # User customization detected
    diff = difflib.unified_diff(
        deployed_bytes.decode("utf-8", errors="replace").splitlines(),
        src.read_text(encoding="utf-8").splitlines(),
        lineterm="",
        n=2,
    )
    diff_lines = sum(1 for _ in diff)
    return UpgradePlan(
        name=name, src=src, dst=dst, state="customized", diff_lines=diff_lines
    )


def collect_plans(kb_root: Path, prev_version: str, force: bool) -> list[UpgradePlan]:
    plans: list[UpgradePlan] = []
    for fname in SCRIPT_FILES:
        plans.append(
            compute_plan(
                src=SRC_SCRIPTS_DIR / fname,
                dst=kb_root / "scripts" / fname,
                prev_version=prev_version,
                force=force,
            )
        )
    for fname in SHELL_FILES:
        plans.append(
            compute_plan(
                src=SRC_SHELL_DIR / fname,
                dst=kb_root / fname,
                prev_version=prev_version,
                force=force,
            )
        )
    return plans


def apply_plan(plan: UpgradePlan, *, dry_run: bool) -> str:
    if plan.state in ("up_to_date",):
        return "skipped (up to date)"
    if plan.state == "missing":
        if dry_run:
            return "would copy (missing)"
        plan.dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan.src, plan.dst)
        if plan.dst.suffix == ".sh":
            plan.dst.chmod(0o755)
        return "copied (was missing)"
    if plan.state == "clean_overwrite":
        if dry_run:
            return "would overwrite (clean)"
        shutil.copy2(plan.src, plan.dst)
        if plan.dst.suffix == ".sh":
            plan.dst.chmod(0o755)
        return "overwritten"
    if plan.state == "customized":
        new_path = plan.dst.with_suffix(plan.dst.suffix + ".new")
        if dry_run:
            return f"would write {new_path.name} (customized; {plan.diff_lines}-line diff)"
        shutil.copy2(plan.src, new_path)
        if plan.dst.suffix == ".sh":
            new_path.chmod(0o755)
        return (
            f"WROTE {new_path.name} ({plan.diff_lines}-line diff vs deployed; "
            "review and merge manually)"
        )
    return "unknown state"


def write_diff_text(plans: list[UpgradePlan]) -> str:
    chunks: list[str] = []
    for plan in plans:
        if plan.state != "customized":
            continue
        deployed = plan.dst.read_text(encoding="utf-8", errors="replace").splitlines()
        new = plan.src.read_text(encoding="utf-8").splitlines()
        diff = difflib.unified_diff(
            deployed,
            new,
            fromfile=f"deployed/{plan.dst.name}",
            tofile=f"new/{plan.src.name}",
            lineterm="",
            n=3,
        )
        chunks.append(f"=== {plan.name} ===\n" + "\n".join(diff))
    return "\n\n".join(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upgrade a deployed KB's reference scripts")
    parser.add_argument("--kb-root", type=Path, required=True,
                        help="Root of the deployed knowledge base")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--diff", action="store_true",
                        help="Show unified diffs for customized files")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite even if user customizations detected")
    args = parser.parse_args(argv)

    kb_root: Path = args.kb_root.resolve()
    if not (kb_root / "kb.config.yml").is_file():
        print(f"❌ {kb_root}: kb.config.yml not found", file=sys.stderr)
        return 3

    repo_version = get_repo_version()
    deployed_version = get_deployed_version(kb_root)
    print(f"Repo version:     {repo_version}")
    print(f"Deployed version: {deployed_version}")
    if deployed_version == repo_version:
        print("Already up to date.")
        return 0

    plans = collect_plans(kb_root, prev_version=deployed_version, force=args.force)

    print("")
    print("Upgrade plan:")
    print(f"{'file':<25} {'state':<20} {'action'}")
    print("-" * 70)
    customized = 0
    for plan in plans:
        action = apply_plan(plan, dry_run=args.dry_run)
        if plan.state == "customized":
            customized += 1
        print(f"{plan.name:<25} {plan.state:<20} {action}")

    if args.diff and customized:
        print("\n=== Diffs ===\n")
        print(write_diff_text(plans))

    if not args.dry_run and customized == 0:
        # Update the deployed config's instructions_version
        cfg_file = kb_root / "kb.config.yml"
        text = cfg_file.read_text(encoding="utf-8")
        new_text = []
        bumped = False
        for line in text.splitlines(keepends=True):
            if line.lstrip().startswith("instructions_version:"):
                indent = line[: len(line) - len(line.lstrip())]
                new_text.append(f'{indent}instructions_version: "{repo_version}"\n')
                bumped = True
            else:
                new_text.append(line)
        if not bumped:
            new_text.insert(0, f'instructions_version: "{repo_version}"\n')
        cfg_file.write_text("".join(new_text), encoding="utf-8")
        print(f"\n✅ instructions_version bumped to {repo_version}")

    if customized:
        print(
            f"\n⚠️  {customized} file(s) had local customizations. "
            ".new sidecars were created. Review and merge manually."
        )
        return 2
    return 1 if any(p.state != "up_to_date" for p in plans) else 0


if __name__ == "__main__":
    raise SystemExit(main())
