#!/usr/bin/env python3
"""sync_deployed_bases — DEPRECATED, use scripts/kb_upgrade.py.

Kept as a thin wrapper so existing commands keep working. It finds the bases
the old helper found (the target folder itself when it holds kb.config.yml,
plus every immediate subfolder that does) and runs the regular upgrade on
each: customized files get `.new` sidecars instead of being overwritten,
launchers and requirements files are refreshed, heal adds the `media:` /
`sync:` config sections and the `sync/` workspace (MIGRATIONS.md), and the
version moves only when the upgrade completes.

Usage:
  python3 scripts/sync_deployed_bases.py <target-root> [--dry-run]
  KB_SYNC_TARGET=/path/to/bases python3 scripts/sync_deployed_bases.py

Exit codes are kb_upgrade.py's (the worst over all bases); 2 also when no
target or no base is found.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import kb_upgrade  # noqa: E402

# The target is machine-specific, so there is no hardcoded default: pass it as
# an argument or export KB_SYNC_TARGET.
ENV_TARGET_VAR = "KB_SYNC_TARGET"

DEPRECATION = (
    "[DEPRECATED] sync_deployed_bases.py is replaced by kb_upgrade.py and now "
    "runs it for each base. Use:\n"
    "  python3 scripts/kb_upgrade.py --kb-root <base> [--dry-run]\n"
    "  python3 scripts/kb_upgrade.py --all-root <folder with kb-* bases> [--dry-run]"
)


def find_bases(target_root: Path) -> list[Path]:
    """The target itself and every immediate subdirectory with a kb.config.yml."""
    bases: list[Path] = []
    if (target_root / "kb.config.yml").is_file():
        bases.append(target_root)
    for child in sorted(target_root.iterdir()):
        if child.is_dir() and (child / "kb.config.yml").is_file():
            bases.append(child)
    return bases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DEPRECATED: runs kb_upgrade.py for every deployed base in a folder"
    )
    parser.add_argument("target", nargs="?", type=Path, default=None,
                        help="Folder containing one or more deployed bases "
                             f"(or set ${ENV_TARGET_VAR})")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print(DEPRECATION, file=sys.stderr)

    target: Path | None = args.target
    if target is None:
        env_target = os.environ.get(ENV_TARGET_VAR, "").strip()
        if not env_target:
            print(
                "target folder required: pass it as an argument or set "
                f"${ENV_TARGET_VAR}\n"
                "  python3 scripts/sync_deployed_bases.py /path/to/deployed-bases",
                file=sys.stderr,
            )
            return 2
        target = Path(env_target)

    if not target.is_dir():
        print(f"target not found: {target}", file=sys.stderr)
        return 2
    bases = find_bases(target)
    if not bases:
        print(f"no deployed bases (kb.config.yml) found under {target}", file=sys.stderr)
        return 2

    upgrade_args = kb_upgrade.build_parser().parse_args(
        ["--dry-run"] if args.dry_run else []
    )
    result = 0
    for index, base in enumerate(bases):
        if index:
            print("")
        print(f"=== {base.name} ===")
        result = max(result, kb_upgrade.upgrade_one(base.resolve(), upgrade_args))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
