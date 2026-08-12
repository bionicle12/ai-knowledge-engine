#!/usr/bin/env python3
"""Refresh one or more deployed knowledge bases from this source repository.

Compares a deployed KB's `instructions_version` (in `kb.config.yml`) with the
source repo's `VERSION`, then optionally syncs:

  * Reference Python scripts (`scripts/kb_*.py`)
  * Local graph viewer assets (`scripts/kb_viewer/**`)
  * Shell wrappers under `shell/`
  * A small managed `!view` command block in `AGENTS.md`

User customizations are detected via SHA-256 comparison: if the deployed file's
hash matches the previous-version hash in the repo, it's a clean copy and is
overwritten with the new version. If it differs, the user has customized it
— the upgrade script writes a `.new` sibling and reports the divergence
without overwriting.

Usage:
    python3 scripts/kb_upgrade.py --kb-root /path/to/deployed-kb
    python3 scripts/kb_upgrade.py --dry-run
    python3 scripts/kb_upgrade.py --all-root /path/to/kbs --dry-run
    python3 scripts/kb_upgrade.py --accept kb_ingest.py
    python3 scripts/kb_upgrade.py --force  # discard all script customizations

Exit codes:
    0 — up to date or upgraded successfully
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
    "kb_export.py",
    "kb_import.py",
    "kb_ingest.py",
    "kb_lint.py",
    "kb_nlp_batch.py",
    "kb_ocr.py",
    "kb_populate.py",
    "kb_reflect.py",
    "kb_reindex.py",
    "kb_route.py",
    "kb_save_session.py",
    "kb_stt.py",
    "kb_update.py",
    "kb_view.py",
    "kb_watch.py",
)

SHELL_FILES = (
    "reindex.sh",
    "watcher.sh",
    "lint.sh",
    "doctor.sh",
    "export.sh",
    "import.sh",
)

VIEW_BLOCK_BEGIN = "<!-- AI-KE:VIEW:BEGIN — managed by kb_upgrade.py -->"
VIEW_BLOCK_END = "<!-- AI-KE:VIEW:END -->"
VIEW_BLOCK = f"""\
{VIEW_BLOCK_BEGIN}
## Local knowledge graph viewer

Use the deterministic local viewer for these commands. Do not rebuild the
graph with AI:

- `!view` → Windows: `python scripts/kb_view.py --background`;
  macOS/Linux: `python3 scripts/kb_view.py --background`. Report the URL.
- `!view status` → run the same command with `--status`.
- `!view stop` → run the same command with `--stop`.
{VIEW_BLOCK_END}"""

_HISTORY_MATCH_CACHE: dict[tuple[str, str], bool] = {}


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
    # git show expects forward slashes; str() would produce backslashes on
    # Windows and silently miss every path.
    rel = repo_path.relative_to(REPO_ROOT).as_posix()
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


def _normalise_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def file_matches_repo_history(src: Path, deployed_bytes: bytes) -> bool:
    """Return true when a deployed file is an unmodified historical source."""
    try:
        relative = src.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return False
    deployed_digest = hashlib.sha256(
        _normalise_newlines(deployed_bytes)
    ).hexdigest()
    cache_key = (relative, deployed_digest)
    if cache_key in _HISTORY_MATCH_CACHE:
        return _HISTORY_MATCH_CACHE[cache_key]
    try:
        history = subprocess.run(
            ["git", "log", "--format=%H", "--", relative],
            capture_output=True,
            check=False,
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
        )
    except (FileNotFoundError, OSError):
        _HISTORY_MATCH_CACHE[cache_key] = False
        return False
    if history.returncode != 0:
        _HISTORY_MATCH_CACHE[cache_key] = False
        return False
    for commit in history.stdout.splitlines():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            capture_output=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
        if (
            blob.returncode == 0
            and _normalise_newlines(blob.stdout)
            == _normalise_newlines(deployed_bytes)
        ):
            _HISTORY_MATCH_CACHE[cache_key] = True
            return True
    _HISTORY_MATCH_CACHE[cache_key] = False
    return False


def compute_plan(
    src: Path, dst: Path, prev_version: str, force: bool
) -> UpgradePlan:
    name = src.name
    if not dst.is_file():
        return UpgradePlan(name=name, src=src, dst=dst, state="missing")
    if file_hash(src) == file_hash(dst):
        return UpgradePlan(name=name, src=src, dst=dst, state="up_to_date")
    source_bytes = src.read_bytes()
    deployed_bytes = dst.read_bytes()
    if _normalise_newlines(source_bytes) == _normalise_newlines(deployed_bytes):
        return UpgradePlan(name=name, src=src, dst=dst, state="up_to_date")
    # Try to fetch the previous-version content from git tag
    prev_blob = file_at_commit(src, prev_version)
    if prev_blob is not None and _normalise_newlines(
        prev_blob
    ) == _normalise_newlines(deployed_bytes):
        # Deployed file matches the previous release exactly → clean overwrite is safe
        return UpgradePlan(name=name, src=src, dst=dst, state="clean_overwrite")
    if file_matches_repo_history(src, deployed_bytes):
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


def _normalise_accept_name(value: str) -> str:
    name = value.strip().replace("\\", "/").lstrip("./")
    return name.removeprefix("scripts/")


def _plan_is_accepted(name: str, accepted: set[str]) -> bool:
    canonical = _normalise_accept_name(name)
    return canonical in accepted or Path(canonical).name in accepted


def collect_plans(
    kb_root: Path,
    prev_version: str,
    force: bool,
    accepted: set[str] | None = None,
) -> list[UpgradePlan]:
    accepted_names = {
        _normalise_accept_name(name) for name in (accepted or set())
    }
    plans: list[UpgradePlan] = []
    for fname in SCRIPT_FILES:
        plan_name = fname
        plans.append(
            compute_plan(
                src=SRC_SCRIPTS_DIR / fname,
                dst=kb_root / "scripts" / fname,
                prev_version=prev_version,
                force=force or _plan_is_accepted(plan_name, accepted_names),
            )
        )
    viewer_dir = SRC_SCRIPTS_DIR / "kb_viewer"
    if viewer_dir.is_dir():
        for src in sorted(path for path in viewer_dir.rglob("*") if path.is_file()):
            relative = src.relative_to(SRC_SCRIPTS_DIR)
            plan_name = relative.as_posix()
            plan = compute_plan(
                src=src,
                dst=kb_root / "scripts" / relative,
                prev_version=prev_version,
                force=force or _plan_is_accepted(plan_name, accepted_names),
            )
            plan.name = plan_name
            plans.append(plan)
    for fname in SHELL_FILES:
        plan_name = f"shell/{fname}"
        plan = compute_plan(
            src=SRC_SHELL_DIR / fname,
            dst=kb_root / "shell" / fname,
            prev_version=prev_version,
            force=force or _plan_is_accepted(plan_name, accepted_names),
        )
        plan.name = plan_name
        plans.append(
            plan
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


def managed_view_block_state(agents_file: Path) -> str:
    if not agents_file.is_file():
        return "missing_file"
    text = agents_file.read_text(encoding="utf-8")
    has_begin = VIEW_BLOCK_BEGIN in text
    has_end = VIEW_BLOCK_END in text
    if has_begin != has_end:
        return "malformed"
    if not has_begin:
        return "missing"
    start = text.index(VIEW_BLOCK_BEGIN)
    end = text.index(VIEW_BLOCK_END, start) + len(VIEW_BLOCK_END)
    return "up_to_date" if text[start:end] == VIEW_BLOCK else "outdated"


def update_managed_view_block(agents_file: Path, *, dry_run: bool) -> str:
    state = managed_view_block_state(agents_file)
    if state == "up_to_date":
        return "skipped (up to date)"
    if state == "malformed":
        return "manual review required (managed markers are incomplete)"
    if dry_run:
        if state == "missing_file":
            return "would create"
        if state == "missing":
            return "would append"
        return "would update"

    if state == "missing_file":
        agents_file.write_text(f"{VIEW_BLOCK}\n", encoding="utf-8")
        return "created"
    text = agents_file.read_text(encoding="utf-8")
    if state == "missing":
        separator = "\n" if text.endswith("\n") else "\n\n"
        agents_file.write_text(
            f"{text}{separator}{VIEW_BLOCK}\n",
            encoding="utf-8",
        )
        return "appended"
    start = text.index(VIEW_BLOCK_BEGIN)
    end = text.index(VIEW_BLOCK_END, start) + len(VIEW_BLOCK_END)
    agents_file.write_text(
        f"{text[:start]}{VIEW_BLOCK}{text[end:]}",
        encoding="utf-8",
    )
    return "updated"


def discover_kb_roots(parent: Path) -> list[Path]:
    root = parent.resolve()
    if not root.is_dir():
        return []
    return sorted(
        (
            path.resolve()
            for path in root.glob("kb-*")
            if path.is_dir() and (path / "kb.config.yml").is_file()
        ),
        key=lambda path: path.name.casefold(),
    )


def _bump_deployed_version(kb_root: Path, repo_version: str) -> None:
    cfg_file = kb_root / "kb.config.yml"
    text = cfg_file.read_text(encoding="utf-8")
    new_text: list[str] = []
    bumped = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("instructions_version:"):
            indent = line[: len(line) - len(line.lstrip())]
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            new_text.append(
                f'{indent}instructions_version: "{repo_version}"{newline}'
            )
            bumped = True
        else:
            new_text.append(line)
    if not bumped:
        new_text.insert(0, f'instructions_version: "{repo_version}"\n')
    cfg_file.write_text("".join(new_text), encoding="utf-8")


def upgrade_one(kb_root: Path, args: argparse.Namespace) -> int:
    if not (kb_root / "kb.config.yml").is_file():
        print(f"[ERROR] {kb_root}: kb.config.yml not found", file=sys.stderr)
        return 3

    repo_version = get_repo_version()
    deployed_version = get_deployed_version(kb_root)
    print(f"Repo version:     {repo_version}")
    print(f"Deployed version: {deployed_version}")
    plans = collect_plans(
        kb_root,
        prev_version=deployed_version,
        force=args.force,
        accepted=set(args.accept),
    )
    agents_file = kb_root / "AGENTS.md"
    view_block_state = managed_view_block_state(agents_file)

    print("")
    print("Upgrade plan:")
    print(f"{'file':<46} {'state':<20} {'action'}")
    print("-" * 92)
    customized = 0
    changed = False
    for plan in plans:
        action = apply_plan(plan, dry_run=args.dry_run)
        if plan.state == "customized":
            customized += 1
        if plan.state != "up_to_date":
            changed = True
        print(f"{plan.name:<46} {plan.state:<20} {action}")

    view_action = update_managed_view_block(agents_file, dry_run=args.dry_run)
    print(f"{'AGENTS.md (!view block)':<46} {view_block_state:<20} {view_action}")
    if view_block_state not in ("up_to_date",):
        changed = True
    if view_block_state == "malformed":
        customized += 1

    if args.diff and customized:
        print("\n=== Diffs ===\n")
        print(write_diff_text(plans))

    if not args.dry_run and customized == 0:
        _bump_deployed_version(kb_root, repo_version)
        print(f"\n[OK] instructions_version set to {repo_version}")

    if customized:
        if args.dry_run:
            print(
                f"\n[WARN] {customized} item(s) require review. "
                "Dry-run made no changes and wrote no .new sidecars."
            )
        else:
            print(
                f"\n[WARN] {customized} item(s) require review. "
                "Customized files received .new sidecars; managed-marker "
                "conflicts were left untouched."
            )
        return 2
    if args.dry_run and changed:
        print("\n[OK] Dry-run complete; no files were changed.")
    elif not changed and deployed_version == repo_version:
        print("\nAlready up to date.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upgrade deployed KB reference files from this source repo"
    )
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument(
        "--kb-root",
        "--root",
        dest="kb_root",
        type=Path,
        help="Deployed KB root (default: current directory); --root is "
        "accepted as an alias for consistency with the other scripts",
    )
    targets.add_argument(
        "--all-root",
        type=Path,
        help="Upgrade each immediate kb-* directory under this parent",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Show unified diffs for customized files",
    )
    parser.add_argument(
        "--accept",
        action="append",
        default=[],
        metavar="FILE",
        help="Accept upstream for one customized file (repeatable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite every customized reference file",
    )
    args = parser.parse_args(argv)

    if args.all_root is not None:
        roots = discover_kb_roots(args.all_root)
        if not roots:
            print(
                f"[ERROR] No configured kb-* directories under "
                f"{args.all_root.resolve()}",
                file=sys.stderr,
            )
            return 3
        result = 0
        for index, kb_root in enumerate(roots):
            if index:
                print("")
            print(f"=== {kb_root.name} ===")
            result = max(result, upgrade_one(kb_root, args))
        return result

    kb_root = (args.kb_root or Path.cwd()).resolve()
    return upgrade_one(kb_root, args)


if __name__ == "__main__":
    raise SystemExit(main())
