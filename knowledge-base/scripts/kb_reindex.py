#!/usr/bin/env python3
"""kb_reindex — cross-platform reindex orchestrator for AI Knowledge Engine.

A pure-Python equivalent of ``shell/reindex.sh`` so the pipeline runs
identically on Windows (no Git Bash / WSL required), macOS, and Linux. The file
watcher (``kb_watch.py``) calls this instead of shelling out to ``bash``.

Steps:
  1. ingest        — python kb_ingest.py
  2. routing       — python kb_route.py
  3. quick lint    — python kb_lint.py --quick
  4. consolidation — lint report + nlp batch + reflection trigger (throttled by
                     a ``.last_consolidation`` marker; default every 24h)
  5. index         — repomix (if installed)

Usage:
  python3 scripts/kb_reindex.py                # full pipeline
  python3 scripts/kb_reindex.py --quick        # ingest + index only
  python3 scripts/kb_reindex.py --no-index     # skip repomix
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

CONSOLIDATION_MARKER = ".last_consolidation"
DAY_SECONDS = 86400

# --- Pack-based index constants ---------------------------------------------
# o200k_base averages ~3.8 chars/token on prose; used for estimates only.
CHARS_PER_TOKEN = 3.8
WINDOW_CEILINGS = {"256k": 80_000, "200k": 60_000, "1m": 150_000}
DEFAULT_MERGE_BELOW = 15_000
# A legacy monolithic output.xml above this deserves a loud warning.
MONOLITH_WARN_TOKENS = 150_000
# Sections that form the always-loadable "core" pack. Small by design:
# who the author is, how they think, how they write, plus routing tables.
CORE_SECTIONS = ("profile", "principles", "voice", "routing")
# AGENTS.md is intentionally NOT indexed: it is already in the system prompt,
# indexing it charges its tokens twice.
META_FILES = (
    "README.md",
    "KNOWLEDGE_STRUCTURE.md",
    "DATA_PLACEMENT_EXAMPLES.md",
    "kb.config.yml",
)
PACK_HEADER = (
    "Knowledge-base pack '{name}'. Full text (compress:false — wording and "
    "nuance are the payload). Route via knowledge/routing-table.md and load "
    "AT MOST ONE domain pack per task."
)


def _py(script: str, *args: str, root: Path) -> int:
    """Run a sibling kb_*.py script with the current interpreter."""
    script_path = SCRIPT_DIR / script
    if not script_path.is_file():
        return 0  # optional step, silently skip
    cmd = [kbc.detect_python_executable(), str(script_path), "--root", str(root), *args]
    return subprocess.run(cmd, check=False).returncode


def _consolidation_due(root: Path, interval_hours: int) -> bool:
    marker = root / CONSOLIDATION_MARKER
    if not marker.is_file():
        return True
    try:
        last = float(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True
    return (time.time() - last) > interval_hours * 3600


def _touch_consolidation(root: Path) -> None:
    (root / CONSOLIDATION_MARKER).write_text(str(int(time.time())), encoding="utf-8")


def run_repomix(root: Path) -> bool:
    """Generate the legacy monolithic Repomix index. Returns True if it ran."""
    repomix = shutil.which("repomix")
    if not repomix:
        print("⚠️  [reindex] repomix not installed; skipping index generation")
        print("    install: npm install -g repomix")
        return False
    print("📦 [reindex] generating Repomix index...")
    result = subprocess.run([repomix, "--quiet"], check=False, cwd=str(root))
    if result.returncode != 0:
        subprocess.run([repomix], check=False, cwd=str(root))
    _warn_monolith(root)
    return True


def _warn_monolith(root: Path) -> None:
    """Loudly flag a legacy single-file index that outgrew a context window."""
    output = root / ".repomix" / "output.xml"
    if not output.is_file():
        return
    tokens = int(output.stat().st_size / CHARS_PER_TOKEN)
    if tokens > MONOLITH_WARN_TOKENS:
        print(
            f"⚠️  [reindex] monolithic index is ~{tokens:,} tokens "
            f"(> {MONOLITH_WARN_TOKENS:,}). Agents can no longer read it whole."
        )
        print(
            "    Enable pack mode: add an `index:` section to kb.config.yml "
            "(see 05_INDEX.md) and rerun."
        )


# ---------------------------------------------------------------------------
# Pack-based index (index: section in kb.config.yml)
# ---------------------------------------------------------------------------


@dataclass
class PackPlan:
    name: str
    include: list[str]
    files: list[Path] = field(default_factory=list)
    when_to_load: str = ""
    est_tokens: int = 0

    @property
    def output_rel(self) -> str:
        return f".repomix/{self.name}.xml"

    @property
    def config_rel(self) -> str:
        return f".repomix/configs/{self.name}.json"


def _md_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def _estimate_tokens(files: list[Path]) -> int:
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            continue
    return int(total / CHARS_PER_TOKEN)


def _resolve_globs(root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        for hit in globmod.glob(str(root / pattern), recursive=True):
            p = Path(hit)
            if p.is_file():
                files.append(p)
    return sorted(set(files))


def index_ceiling(index_cfg: dict) -> int:
    profile = str(index_cfg.get("window_profile", "256k")).lower()
    default = WINDOW_CEILINGS.get(profile, WINDOW_CEILINGS["256k"])
    return int(index_cfg.get("pack_token_ceiling", default))


def plan_packs(root: Path, index_cfg: dict) -> list[PackPlan]:
    """Turn the `index:` config section into a concrete pack list.

    ``packs: auto`` (default): core pack (meta + profile/principles/voice +
    routing) plus one pack per top-level ``knowledge/`` section; sections over
    the ceiling are split by subfolder; sections under the merge threshold are
    collected into a shared ``aux`` pack.
    Explicit ``packs:`` list: taken as-is (name + include globs).
    """
    packs_cfg = index_cfg.get("packs", "auto")
    if isinstance(packs_cfg, list):
        plans = []
        for entry in packs_cfg:
            include = list(entry.get("include", []))
            files = _resolve_globs(root, include)
            plans.append(
                PackPlan(
                    name=str(entry.get("name", "unnamed")),
                    include=include,
                    files=files,
                    when_to_load=str(entry.get("when_to_load", "")),
                    est_tokens=_estimate_tokens(files),
                )
            )
        return plans

    ceiling = index_ceiling(index_cfg)
    merge_below = int(index_cfg.get("merge_below_tokens", DEFAULT_MERGE_BELOW))
    knowledge = root / "knowledge"

    core_include: list[str] = [f for f in META_FILES if (root / f).is_file()]
    core_files: list[Path] = [root / f for f in core_include]
    if (knowledge / "routing-table.md").is_file():
        core_include.append("knowledge/routing-table.md")
        core_files.append(knowledge / "routing-table.md")
    for section in CORE_SECTIONS:
        sec_dir = knowledge / section
        if sec_dir.is_dir():
            core_include.append(f"knowledge/{section}/**/*.md")
            core_files.extend(_md_files(sec_dir))

    plans = [
        PackPlan(
            name="core",
            include=core_include,
            files=core_files,
            when_to_load="Always loadable: author profile, principles, voice, routing.",
            est_tokens=_estimate_tokens(core_files),
        )
    ]

    aux_include: list[str] = []
    aux_files: list[Path] = []
    aux_parts: list[str] = []

    sections = []
    if knowledge.is_dir():
        sections = sorted(
            d
            for d in knowledge.iterdir()
            if d.is_dir()
            and not d.name.startswith((".", "_"))
            and d.name not in CORE_SECTIONS
        )

    for sec_dir in sections:
        sec = sec_dir.name
        files = _md_files(sec_dir)
        if not files:
            continue
        est = _estimate_tokens(files)
        if est < merge_below:
            aux_include.append(f"knowledge/{sec}/**/*.md")
            aux_files.extend(files)
            aux_parts.append(sec)
            continue
        subdirs = sorted(
            d for d in sec_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        )
        if est > ceiling and subdirs:
            # Oversized section -> one pack per subfolder ("library" becomes
            # library-craft, library-marketing, ...). Loose files at the
            # section root become <section>-root.
            root_files = sorted(
                f for f in sec_dir.glob("*.md") if f.is_file()
            )
            if root_files:
                plans.append(
                    PackPlan(
                        name=f"{sec}-root",
                        include=[f"knowledge/{sec}/*.md"],
                        files=root_files,
                        when_to_load=f"Top-level pages of '{sec}'.",
                        est_tokens=_estimate_tokens(root_files),
                    )
                )
            for sub in subdirs:
                sub_files = _md_files(sub)
                if not sub_files:
                    continue
                plans.append(
                    PackPlan(
                        name=f"{sec}-{sub.name}",
                        include=[f"knowledge/{sec}/{sub.name}/**/*.md"],
                        files=sub_files,
                        when_to_load=f"Only for tasks about '{sec}/{sub.name}'.",
                        est_tokens=_estimate_tokens(sub_files),
                    )
                )
        else:
            plans.append(
                PackPlan(
                    name=sec,
                    include=[f"knowledge/{sec}/**/*.md"],
                    files=files,
                    when_to_load=f"Tasks about '{sec}'.",
                    est_tokens=est,
                )
            )

    assets_index = root / "assets-index"
    ai_files = _md_files(assets_index)
    if ai_files:
        aux_include.append("assets-index/**/*.md")
        aux_files.extend(ai_files)
        aux_parts.append("assets-index")

    if aux_include:
        plans.append(
            PackPlan(
                name="aux",
                include=aux_include,
                files=aux_files,
                when_to_load="Merged small sections: " + ", ".join(aux_parts) + ".",
                est_tokens=_estimate_tokens(aux_files),
            )
        )
    return plans


def _base_repomix_config(root: Path) -> dict:
    cfg_path = root / "repomix.config.json"
    if cfg_path.is_file():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def write_pack_configs(root: Path, plans: list[PackPlan]) -> None:
    """Generate .repomix/configs/<pack>.json, inheriting the base config.

    Inherits ignore/security/tokenCount and output options from the root
    repomix.config.json, then overrides per-pack path/include/header.
    compress stays false for knowledge bases: full text IS the payload.
    """
    base = _base_repomix_config(root)
    configs_dir = root / ".repomix" / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        cfg = json.loads(json.dumps(base)) if base else {}
        output = dict(cfg.get("output", {}))
        output["filePath"] = plan.output_rel
        output.setdefault("style", "xml")
        output["compress"] = False
        output["removeComments"] = False
        output["headerText"] = PACK_HEADER.format(name=plan.name)
        cfg["output"] = output
        cfg["include"] = plan.include
        cfg.setdefault("ignore", {"useGitignore": True, "useDefaultPatterns": True})
        cfg.setdefault("security", {"enableSecurityCheck": True})
        cfg.setdefault("tokenCount", {"encoding": "o200k_base"})
        target = configs_dir / f"{plan.name}.json"
        payload = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
        # Write only on change: an untouched mtime keeps skip-if-fresh working.
        try:
            if target.is_file() and target.read_text(encoding="utf-8") == payload:
                continue
        except OSError:
            pass
        target.write_text(payload, encoding="utf-8")


def _pack_is_fresh(root: Path, plan: PackPlan) -> bool:
    output = root / plan.output_rel
    if not output.is_file():
        return False
    try:
        built_at = output.stat().st_mtime
    except OSError:
        return False
    config = root / plan.config_rel
    if config.is_file() and config.stat().st_mtime > built_at:
        return False
    for f in plan.files:
        try:
            if f.stat().st_mtime > built_at:
                return False
        except OSError:
            continue
    return True


def _run_repomix_config(root: Path, config_rel: str) -> bool:
    """Build one pack. Separate function so tests can monkeypatch it."""
    repomix = shutil.which("repomix")
    if not repomix:
        return False
    result = subprocess.run(
        [repomix, "-c", config_rel, "--quiet"], check=False, cwd=str(root)
    )
    return result.returncode == 0


def write_packs_status(root: Path, rows: list[tuple[str, int, str, str]], ceiling: int) -> None:
    status = root / ".repomix" / "PACKS_STATUS.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge-base packs — build status",
        "",
        "Auto-generated by kb_reindex.py. Do not edit.",
        "",
        "| Pack | ~Tokens (o200k est.) | Last build | Load when |",
        "|------|----------------------|------------|-----------|",
    ]
    for name, tokens, state, when in rows:
        lines.append(f"| {name} | {tokens:,} | {state} | {when} |")
    lines += [
        "",
        f"Pack ceiling: {ceiling:,} tokens. "
        "Route via knowledge/routing-table.md; load AT MOST ONE domain pack per task.",
        "",
    ]
    status.write_text("\n".join(lines), encoding="utf-8")


def run_pack_index(root: Path, index_cfg: dict, *, force: bool = False) -> bool:
    """Build the pack-based index. Returns True if repomix ran."""
    if shutil.which("repomix") is None:
        print("⚠️  [reindex] repomix not installed; skipping index generation")
        print("    install: npm install -g repomix")
        return False

    ceiling = index_ceiling(index_cfg)
    plans = plan_packs(root, index_cfg)
    if not plans:
        print("⚠️  [reindex] index.packs produced an empty plan; nothing to build")
        return False

    write_pack_configs(root, plans)

    rows: list[tuple[str, int, str, str]] = []
    oversized: list[str] = []
    built = skipped = failed = 0
    for plan in plans:
        if not force and _pack_is_fresh(root, plan):
            skipped += 1
            state = "fresh"
        elif _run_repomix_config(root, plan.config_rel):
            built += 1
            state = "rebuilt"
        else:
            failed += 1
            state = "FAILED"
        output = root / plan.output_rel
        tokens = (
            int(output.stat().st_size / CHARS_PER_TOKEN) if output.is_file() else 0
        )
        if tokens > ceiling:
            oversized.append(f"{plan.name} (~{tokens:,})")
        rows.append((plan.name, tokens, state, plan.when_to_load))

    write_packs_status(root, rows, ceiling)
    print(
        f"📦 [reindex] packs: built {built}, fresh {skipped}, failed {failed} "
        f"→ .repomix/PACKS_STATUS.md"
    )
    for warn in oversized:
        print(f"⚠️  [reindex] pack over ceiling ({ceiling:,}): {warn}")
    if oversized:
        print(
            "    Split it further: sub-split the section by subfolder or list "
            "explicit packs in kb.config.yml (index.packs)."
        )
    stale_monolith = root / ".repomix" / "output.xml"
    if stale_monolith.is_file():
        print(
            "ℹ️  [reindex] legacy .repomix/output.xml still on disk; "
            "packs replace it — safe to delete."
        )
    return True


def reindex(
    root: Path,
    *,
    quick: bool = False,
    do_index: bool = True,
    do_ingest: bool = True,
    force_index: bool = False,
) -> int:
    cfg = kbc.load_config(root)

    if do_ingest:
        print("🔄 [reindex] ingest pipeline...")
        _py("kb_ingest.py", root=root)

    print("🧭 [reindex] routing pages...")
    _py("kb_route.py", root=root)

    print("🩺 [reindex] quick lint...")
    _py("kb_lint.py", "--quick", root=root)

    if not quick:
        interval = int(cfg.autorun.get("consolidation_interval_hours", 24))
        if _consolidation_due(root, interval):
            print("🧰 [reindex] consolidation...")
            _py("kb_lint.py", "--output", "report", root=root)
            _py("kb_nlp_batch.py", "--incremental", root=root)
            # reflection: trigger logic lives in kb_reflect.py
            reflect = SCRIPT_DIR / "kb_reflect.py"
            if reflect.is_file():
                _py("kb_reflect.py", "--check-threshold", "--dry-run", root=root)
            _touch_consolidation(root)

    if do_index:
        run_index(root, cfg, force=force_index)

    print("✅ [reindex] done")
    return 0


def run_index(root: Path, cfg: "kbc.KbConfig", *, force: bool = False) -> bool:
    """Build the index only: packs when configured, legacy monolith otherwise."""
    index_cfg = cfg.index or {}
    if index_cfg and index_cfg.get("enabled", True):
        return run_pack_index(root, index_cfg, force=force)
    return run_repomix(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — cross-platform reindex orchestrator"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--quick", action="store_true", help="ingest + index only")
    parser.add_argument("--no-index", action="store_true", help="skip repomix")
    parser.add_argument("--no-ingest", action="store_true", help="skip ingest step")
    parser.add_argument(
        "--force", action="store_true", help="rebuild all packs even if fresh"
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="only (re)generate the Repomix index, skip ingest/lint/consolidation",
    )
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    if args.index_only:
        run_index(root, kbc.load_config(root), force=args.force)
        return 0
    return reindex(
        root,
        quick=args.quick,
        do_index=not args.no_index,
        do_ingest=not args.no_ingest,
        force_index=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
