#!/usr/bin/env python3
"""Refresh one or more deployed knowledge bases from this source repository.

Compares a deployed KB's `instructions_version` (in `kb.config.yml`) with the
source repo's `VERSION`, then syncs the engine-owned files:

  * Reference Python scripts (`scripts/kb_*.py`) and the local graph viewer
    assets (`scripts/kb_viewer/**`)
  * Shell wrappers and helpers under `shell/` (`_kbpy.sh`, `hooks/`, …);
    `finalize.sh` is a deploy-time helper and is left alone. The copy of
    `shell/hooks/post-commit` installed in the git hooks folder is not
    touched: when it differs, the summary says to re-run
    `bash shell/install-hooks.sh`
  * Double-click launchers (`*.bat`, `*.command`) — at the base root, or in
    `shell/` when the base keeps them there
  * `requirements.txt`, `requirements-media.txt`, … at the base root
  * The runtime instruction modules: every `NN_*.md` plus `README.md` into
    `kb-docs/`
  * Managed blocks in `AGENTS.md` (`AI-KE:VIEW`, `AI-KE:INDEX`,
    `AI-KE:STATUS`), read from `knowledge-base/templates/AGENTS.md.template`
    at run time. `AI-KE:INVARIANT` blocks are reported only — never written.
  * An additive `index:` section in `kb.config.yml` (switches the base from
    the monolithic output.xml to pack-based indexing, see 05_INDEX.md)

A deployed file equal to a known upstream version (`scripts/known_hashes.json`,
built from git history by `scripts/build_known_hashes.py`; this checkout's git
history as a fallback) is overwritten. Anything else is a local customization:
it is kept, and when upstream changed it since the base's version the upgrade
writes a `.new` sidecar and holds back the files that depend on it (import
it, run it, describe it). The version is bumped only when no file waits for a
merge, and never moves backwards.

Usage:
    python3 scripts/kb_upgrade.py --kb-root /path/to/deployed-kb
    python3 scripts/kb_upgrade.py --dry-run
    python3 scripts/kb_upgrade.py --all-root /path/to/kbs --dry-run
    python3 scripts/kb_upgrade.py --accept kb_ingest.py        # take upstream
    python3 scripts/kb_upgrade.py --accept-local kb_ingest.py  # keep the merged local file
    python3 scripts/kb_upgrade.py --force  # take upstream wherever a .new would be written

Exit codes:
    0 — up to date or upgraded successfully
    2 — review required (a merge, a held file, a failed heal, a config that
        cannot be edited)
    3 — error (no kb.config.yml, base newer than this checkout, etc.)
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import difflib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_KB_DIR = REPO_ROOT / "knowledge-base"
SRC_SCRIPTS_DIR = SRC_KB_DIR / "scripts"
if str(SRC_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_SCRIPTS_DIR))
import kb_common as kbc  # noqa: E402
SRC_TEMPLATES_DIR = SRC_KB_DIR / "templates"
VERSION_FILE = REPO_ROOT / "VERSION"
KNOWN_HASHES_FILE = REPO_ROOT / "scripts" / "known_hashes.json"

# Order of the plan table; also the classification of managed sources.
PLAN_GROUPS = ("scripts", "viewer", "shell", "launchers", "requirements", "kb-docs")
LOCAL_ACCEPTS_FILE = "upgrade-local.json"   # under .kb-state/
BACKUPS_DIR = "upgrade-backups"             # under .kb-state/

# Plan states that write the deployed file, and those that wait for the owner.
_WRITES = frozenset({"missing", "clean_overwrite", "accepted"})
_UNRESOLVED = frozenset({"customized", "held"})

MANAGED_BLOCK_LABELS = ("VIEW", "INDEX", "STATUS")

AI_MERGE_PROMPT = (
    "Compare AGENTS.md with {sidecar}: integrate the improvements from the new "
    "reference block into the corresponding managed section of AGENTS.md "
    "WITHOUT losing any local customizations, then delete {sidecar}."
)

# Additive kb.config.yml patch: switches an upgraded base to pack mode.
# See knowledge-base/05_INDEX.md and templates/kb.config.yml.template.
INDEX_YAML_BLOCK = """\
# Pack-based index (added by kb_upgrade.py, see kb-docs/05_INDEX.md). One monolithic
# output.xml stops fitting a context window as the base grows; packs keep
# every load under a ceiling. compress stays false: wording is the payload.
index:
  enabled: true
  window_profile: "256k"            # 400k (Codex, 120K) | 256k (80K) | 200k (60K) | 1m (150K)
  packs: auto
"""

# Runs kb_heal from a scripts folder in a fresh interpreter, so the heal that
# follows an upgrade uses the base's own (possibly held-back) modules, never
# the engine's. collect_findings runs lint and doctor; apply_auto and
# write_plan call it again, so the findings are reused until an applied auto
# fix changes the base.
HEAL_DRIVER = """\
import sys
from pathlib import Path

scripts, root, mode, version, auto_apply, stage = sys.argv[1:7]
sys.path.insert(0, scripts)
import kb_heal

root = Path(root)
collect = kb_heal.collect_findings
latest = [collect(root)]
kb_heal.collect_findings = lambda *args, **kwargs: latest[0]
if mode == "detect":
    counts = " ".join(
        f"{bucket}={sum(1 for item in latest[0] if item.bucket == bucket)}"
        for bucket in ("auto", "assisted", "human")
    )
    print(f"Heal detect (dry-run, engine scripts, not written): {counts}")
    print('→ next: скажи агенту "!heal"')
    raise SystemExit(0)
applied = []
if auto_apply == "1":
    applied = kb_heal.apply_auto(root, version=version or None)
    if applied:
        latest[0] = collect(root)
kb_heal.write_plan(root)
# Heal advances heal.stage itself; report the stage the plan shows (an
# older kb_heal.py without plan_summary: the configured one).
plan_summary = getattr(kb_heal, "plan_summary", None)
if plan_summary is not None:
    stage = plan_summary(root, latest[0])["stage"]
print(kb_heal.summarize(latest[0], applied, int(stage)))
"""

_HISTORY_MATCH_CACHE: dict[tuple[str, str], bool] = {}
# What a wrapper or launcher runs: a script (not the `setup/scripts/…` probe
# that detects the deploy layout), the `_kbpy.sh` helper, another wrapper.
_SHELL_DEP_RE = re.compile(
    r"(?<!setup[\\/])scripts[\\/](kb_\w+\.py)"
    r"|(?:shell[\\/])?(_kbpy\.sh)"
    r"|shell[\\/]([\w.-]+\.sh)"
)
_SH_COMMENT_RE = re.compile(r"\s*#")
_BAT_COMMENT_RE = re.compile(r"\s*(?:rem\b|::)", re.IGNORECASE)
# A string constant naming a script a Python script runs as a subprocess.
_SCRIPT_CONST_RE = re.compile(r"(?:scripts[\\/])?(kb_\w+\.py)")
# A script an instruction module describes.
_SCRIPT_MENTION_RE = re.compile(r"\b(kb_\w+\.py)\b")
_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")

# The module every engine script imports; a local copy must define what they use.
SHARED_MODULE = "kb_common.py"
_KBC_NAME_RE = re.compile(r"\bkbc\.([A-Za-z_]\w*)")

# Scripts a managed AGENTS.md block describes, besides those it names.
BLOCK_SCRIPTS = {"VIEW": ("kb_view.py",), "INDEX": ("kb_reindex.py",), "STATUS": ("kb_status.py",)}


@dataclass
class UpgradePlan:
    name: str
    src: Path
    dst: Path
    # "missing" | "up_to_date" | "clean_overwrite" | "customized" | "accepted"
    # | "accepted_local" | "kept" | "held"
    state: str
    diff_lines: int = 0
    rel: str = ""        # deployed path relative to the base root
    held_by: str = ""    # the unresolved file a "held" plan waits for
    # --accept-local refused: names the engine scripts use that the local
    # shared module lacks.
    lacks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnownHashes:
    """`scripts/known_hashes.json`: every upstream version of each file and
    managed block, as ``{path|label: {sha256: [VERSION, …]}}``."""

    files: dict = field(default_factory=dict)
    blocks: dict = field(default_factory=dict)

    @staticmethod
    def _lookup(table: dict, key: str, digest: str) -> list[str] | None:
        entry = table.get(key)
        versions = entry.get(digest) if isinstance(entry, dict) else None
        return [str(v) for v in versions] if isinstance(versions, list) else None

    def file_versions(self, path: str, digest: str) -> list[str] | None:
        return self._lookup(self.files, path, digest)

    def block_versions(self, label: str, digest: str) -> list[str] | None:
        return self._lookup(self.blocks, label, digest)


@dataclass
class BlockResult:
    label: str
    state: str      # no_reference | missing_file | missing | malformed | up_to_date | outdated | edited | held
    action: str
    sidecar: str = ""   # set while an AI merge is required or pending


def _normalise_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def content_digest(data: bytes) -> str:
    """SHA-256 of `data` with CRLF read as LF — the key of known_hashes.json."""
    return hashlib.sha256(_normalise_newlines(data)).hexdigest()


def _norm_block(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def block_digest(block: str) -> str:
    return hashlib.sha256(_norm_block(block).encode("utf-8")).hexdigest()


def version_key(value: object) -> tuple[int, ...] | None:
    match = _VERSION_RE.match(str(value).strip())
    if not match:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def get_repo_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "unknown"


def get_deployed_version(kb_root: Path) -> str:
    cfg = kb_root / "kb.config.yml"
    if not cfg.is_file():
        return "missing"
    try:
        data = kbc.yaml_load(cfg.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return "unparseable"
    if not isinstance(data, dict):
        return "unparseable"
    value = data.get("instructions_version")
    return "unknown" if value in (None, "") else str(value)


def load_known_hashes(path: Path | None = None) -> KnownHashes:
    """Read the registry; a missing or broken file means "nothing known"."""
    try:
        data = json.loads((path or KNOWN_HASHES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return KnownHashes()
    if not isinstance(data, dict):
        return KnownHashes()
    files, blocks = data.get("files"), data.get("blocks")
    return KnownHashes(
        files=files if isinstance(files, dict) else {},
        blocks=blocks if isinstance(blocks, dict) else {},
    )


def _repo_relative(src: Path) -> str | None:
    try:
        return src.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None


def file_matches_repo_history(src: Path, deployed_bytes: bytes) -> bool:
    """Fallback for files the registry does not know: search this checkout's
    git history (absent in a ZIP download, partial in a shallow clone)."""
    relative = _repo_relative(src)
    if relative is None:
        return False
    deployed = _normalise_newlines(deployed_bytes)
    cache_key = (relative, content_digest(deployed))
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
    found = False
    if history.returncode == 0:
        for commit in history.stdout.splitlines():
            blob = subprocess.run(
                ["git", "show", f"{commit}:{relative}"],
                capture_output=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            if blob.returncode == 0 and _normalise_newlines(blob.stdout) == deployed:
                found = True
                break
    _HISTORY_MATCH_CACHE[cache_key] = found
    return found


def is_known_upstream(
    src: Path, deployed_bytes: bytes, known: KnownHashes, source_path: str | None
) -> bool:
    """True when the deployed bytes equal some released or committed upstream
    version of `src` — replacing them loses nothing."""
    if source_path and known.file_versions(source_path, content_digest(deployed_bytes)) is not None:
        return True
    return file_matches_repo_history(src, deployed_bytes)


def upstream_unchanged_since(
    base_version: str,
    repo_version: str,
    versions: list[str] | None,
) -> bool:
    """Did the current reference already exist at `base_version`?

    `versions` lists the VERSION values under which the current reference
    content was published (None: the registry does not know it, e.g. a
    development checkout — then only an equal version counts)."""
    if version_key(base_version) is None:
        return False
    if versions is not None:
        return base_version in versions
    return base_version == repo_version


def _classify(rel: str) -> str | None:
    """Plan group of a repo-relative source path, or None when unmanaged."""
    parts = rel.split("/")
    if (
        len(parts) < 2
        or parts[0] != "knowledge-base"
        or "__pycache__" in parts
        or rel.endswith(".pyc")
        or parts[-1].startswith(".")   # .DS_Store and other local debris
    ):
        return None
    top, name = parts[1], parts[-1]
    if len(parts) == 2:
        is_module = fnmatch.fnmatchcase(top, "[0-9][0-9]_*.md") or top == "README.md"
        return "kb-docs" if is_module else None
    if top == "scripts":
        if len(parts) == 3 and fnmatch.fnmatchcase(name, "kb_*.py"):
            return "scripts"
        return "viewer" if parts[2] == "kb_viewer" and len(parts) > 3 else None
    if top == "shell":
        if name == "finalize.sh":
            return None
        if len(parts) == 3 and name.endswith((".bat", ".command")):
            return "launchers"
        return "shell"
    if (
        top == "templates"
        and len(parts) == 3
        and fnmatch.fnmatchcase(name, "requirements*.txt")
        and name != "requirements-dev.txt"
    ):
        return "requirements"
    return None


def is_managed_source(rel: str) -> bool:
    """Does kb_upgrade deliver this repo-relative path into deployed bases?"""
    return _classify(rel) is not None


def _target(kb_root: Path, rel: str, group: str) -> tuple[str, Path]:
    """Plan name and deployed path of a managed source."""
    parts = rel.split("/")
    if group in ("scripts", "viewer"):
        name = "/".join(parts[2:])
        return name, kb_root / "scripts" / name
    if group == "shell":
        sub = "/".join(parts[2:])
        return f"shell/{sub}", kb_root / "shell" / sub
    if group == "launchers":
        # finalize.sh promotes launchers to the base root; a base that was
        # never finalized keeps them in shell/. A launcher new to the base
        # goes where the base keeps the others, so the layout never splits.
        in_shell, at_root = kb_root / "shell" / parts[2], kb_root / parts[2]
        if in_shell.is_file() or at_root.is_file():
            return parts[2], in_shell if in_shell.is_file() else at_root
        return parts[2], in_shell if _launchers_in_shell(kb_root) else at_root
    if group == "requirements":
        return parts[2], kb_root / parts[2]
    return f"{kbc.KB_DOCS_DIR}/{parts[1]}", kb_root / kbc.KB_DOCS_DIR / parts[1]


def _launchers_in_shell(kb_root: Path) -> bool:
    """True when the base keeps the shipped launchers in shell/ (none of
    them at its root)."""
    names = [
        p.name for p in (SRC_KB_DIR / "shell").glob("*")
        if p.suffix in (".bat", ".command") and p.is_file()
    ]
    return any((kb_root / "shell" / n).is_file() for n in names) and not any(
        (kb_root / n).is_file() for n in names
    )


def compute_plan(
    src: Path,
    dst: Path,
    prev_version: str,
    force: bool,
    *,
    accept_local: bool = False,
    known: KnownHashes | None = None,
    repo_version: str | None = None,
    source_path: str | None = None,
) -> UpgradePlan:
    name = src.name
    if not dst.is_file():
        return UpgradePlan(name=name, src=src, dst=dst, state="missing")
    source_bytes = _normalise_newlines(src.read_bytes())
    deployed_bytes = _normalise_newlines(dst.read_bytes())
    if source_bytes == deployed_bytes:
        return UpgradePlan(name=name, src=src, dst=dst, state="up_to_date")
    if accept_local:
        return UpgradePlan(name=name, src=src, dst=dst, state="accepted_local")
    known = known if known is not None else load_known_hashes()
    source_path = source_path or _repo_relative(src)
    if is_known_upstream(src, deployed_bytes, known, source_path):
        return UpgradePlan(name=name, src=src, dst=dst, state="clean_overwrite")
    if force:
        return UpgradePlan(name=name, src=src, dst=dst, state="accepted")
    versions = (
        known.file_versions(source_path, content_digest(source_bytes))
        if source_path
        else None
    )
    if upstream_unchanged_since(
        prev_version, repo_version or get_repo_version(), versions
    ):
        # Local edits on top of the reference this base already carries:
        # nothing new to merge.
        return UpgradePlan(name=name, src=src, dst=dst, state="kept")
    diff = difflib.unified_diff(
        deployed_bytes.decode("utf-8", errors="replace").splitlines(),
        source_bytes.decode("utf-8", errors="replace").splitlines(),
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


def _load_local_accepts(kb_root: Path) -> dict:
    path = kb_root / kbc.STATE_DIR / LOCAL_ACCEPTS_FILE
    try:
        data = kbc.read_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _local_accept_record(plan: UpgradePlan) -> dict[str, str]:
    return {
        "local": content_digest(plan.dst.read_bytes()),
        "source": content_digest(plan.src.read_bytes()),
    }


def _recorded_local_accept(records: dict, rel: str, src: Path, dst: Path) -> bool:
    """`--accept-local` given on an earlier run, for these exact contents."""
    record = records.get(rel)
    if not isinstance(record, dict) or not dst.is_file():
        return False
    return record.get("local") == content_digest(dst.read_bytes()) and record.get(
        "source"
    ) == content_digest(src.read_bytes())


def _python_dependencies(source: bytes) -> set[str]:
    """Modules a script imports and scripts it runs (a string constant that is
    exactly a script name, as in ``_py("kb_lint.py", …)``)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules = [node.module]
        else:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                match = _SCRIPT_CONST_RE.fullmatch(node.value)
                if match:
                    deps.add(match.group(1))
            continue
        deps.update(f"{module.split('.')[0]}.py" for module in modules)
    return deps


def _shell_dependencies(text: str, *, batch: bool) -> set[str]:
    """Scripts and wrappers a shell file runs; comment lines do not count."""
    comment = _BAT_COMMENT_RE if batch else _SH_COMMENT_RE
    code = "\n".join(line for line in text.splitlines() if not comment.match(line))
    deps: set[str] = set()
    for script, helper, wrapper in _SHELL_DEP_RE.findall(code):
        deps.add(script or f"shell/{helper or wrapper}")
    return deps


def _dependencies(plan: UpgradePlan, names: set[str]) -> set[str]:
    """Plan names the new version of `plan` needs installed alongside it."""
    deps: set[str] = set()
    if plan.src.suffix == ".py":
        deps = _python_dependencies(plan.src.read_bytes())
        if plan.name == "kb_view.py":
            deps.update(name for name in names if name.startswith("kb_viewer/"))
    elif plan.name.startswith("kb_viewer/"):
        deps.add("kb_view.py")
    elif plan.name.startswith("shell/") or plan.src.suffix in (".bat", ".command"):
        text = plan.src.read_bytes().decode("utf-8", errors="replace")
        deps = _shell_dependencies(text, batch=plan.src.suffix == ".bat")
    elif plan.name.startswith(f"{kbc.KB_DOCS_DIR}/"):
        # A new module describes the new scripts: it waits with them.
        text = plan.src.read_bytes().decode("utf-8", errors="replace")
        deps = set(_SCRIPT_MENTION_RE.findall(text))
    deps.discard(plan.name)
    return deps & names


def _module_names(body: list[ast.stmt]) -> set[str]:
    """Names bound at module level (also inside if/try/with blocks)."""
    names: set[str] = set()
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(
                n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        else:
            for attr in ("body", "orelse", "finalbody"):
                names |= _module_names(getattr(node, attr, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                names |= _module_names(handler.body)
    return names


def _defined_names(source: bytes) -> set[str] | None:
    """Top-level names a module defines; ``None`` when it does not parse."""
    try:
        return _module_names(ast.parse(source).body)
    except (SyntaxError, ValueError):
        return None


def refuse_unsafe_local_accepts(plans: list[UpgradePlan]) -> None:
    """--accept-local of a kb_common.py that lacks names the engine scripts
    installed next to it use would release them into an ImportError (Q6).
    Such a plan stays "customized": the .new is kept, dependents stay held."""
    common = next(
        (p for p in plans if p.name == SHARED_MODULE and p.state == "accepted_local"), None
    )
    if common is None:
        return
    defined = _defined_names(common.dst.read_bytes())
    if defined is not None and "__getattr__" in defined:
        return  # names resolved at run time: nothing to compare
    used: set[str] = set()
    for plan in plans:
        if (
            plan.src.suffix == ".py"
            and plan.name != SHARED_MODULE
            and plan.state in _WRITES | {"up_to_date"}
        ):
            text = plan.src.read_bytes().decode("utf-8", errors="replace")
            used.update(_KBC_NAME_RE.findall(text))
    lacks = sorted(used) if defined is None else sorted(used - defined)
    if lacks:
        common.state = "customized"
        common.lacks = lacks


def hold_dependents(plans: list[UpgradePlan]) -> None:
    """Do not install a new file next to an unmerged dependency.

    A customized `kb_common.py` stays at its old version; the new scripts that
    import it would crash against it, so they wait ("held") until it is
    resolved with --accept / --accept-local. The same goes for the scripts a
    new script runs, the wrappers a launcher runs and the scripts a new
    `kb-docs/` module describes. Holding propagates. A module the base does
    not have yet has no older text to protect: it waits only for scripts the
    base does not have at all.
    """
    by_name = {plan.name: plan for plan in plans}
    names = set(by_name)
    deps = {plan.name: _dependencies(plan, names) for plan in plans if plan.state in _WRITES}
    changed = True
    while changed:
        changed = False
        for plan in plans:
            if plan.state not in _WRITES:
                continue
            new_doc = plan.state == "missing" and plan.name.startswith(f"{kbc.KB_DOCS_DIR}/")
            blocker = next(
                (
                    by_name[d]
                    for d in sorted(deps[plan.name])
                    if by_name[d].state in _UNRESOLVED
                    and not (new_doc and by_name[d].dst.is_file())
                ),
                None,
            )
            if blocker is None:
                continue
            plan.state = "held"
            plan.held_by = blocker.held_by or blocker.name
            changed = True


def collect_plans(
    kb_root: Path,
    prev_version: str,
    force: bool,
    accepted: set[str] | None = None,
    *,
    accepted_local: set[str] | None = None,
    repo_version: str | None = None,
    known: KnownHashes | None = None,
) -> list[UpgradePlan]:
    accepted_names = {_normalise_accept_name(name) for name in (accepted or set())}
    local_names = {_normalise_accept_name(name) for name in (accepted_local or set())}
    known = known if known is not None else load_known_hashes()
    repo_version = repo_version if repo_version is not None else get_repo_version()
    records = _load_local_accepts(kb_root)
    entries: list[tuple[int, str, Path, Path, str]] = []
    for src in SRC_KB_DIR.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(REPO_ROOT).as_posix()
        group = _classify(rel)
        if group is None:
            continue
        name, dst = _target(kb_root, rel, group)
        entries.append((PLAN_GROUPS.index(group), name, src, dst, rel))

    plans: list[UpgradePlan] = []
    for _, name, src, dst, rel in sorted(entries):
        deployed_rel = dst.relative_to(kb_root).as_posix()
        explicit_local = _plan_is_accepted(name, local_names)
        # --accept FILE takes upstream for that file even when it is `kept` or
        # was resolved with --accept-local earlier; --force only replaces the
        # files that would otherwise get a .new sidecar.
        explicit_accept = _plan_is_accepted(name, accepted_names) and not explicit_local
        accept_local = explicit_local or (
            not explicit_accept and _recorded_local_accept(records, deployed_rel, src, dst)
        )
        plan = compute_plan(
            src,
            dst,
            prev_version,
            explicit_accept,
            accept_local=accept_local,
            known=known,
            repo_version=repo_version,
            source_path=rel,
        )
        if force and plan.state == "customized":
            plan.state = "accepted"
        plan.name = name
        plan.rel = deployed_rel
        plans.append(plan)
    refuse_unsafe_local_accepts(plans)
    hold_dependents(plans)
    return plans


def unresolved_files(plans: list[UpgradePlan]) -> dict[str, str]:
    """Plan name of every file that is not installed yet → the customized
    file it ultimately waits for."""
    return {
        plan.name: plan.held_by or plan.name
        for plan in plans
        if plan.state in _UNRESOLVED
    }


def _sidecar_path(dst: Path) -> Path:
    return dst.with_name(dst.name + ".new")


def _install(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    kbc.atomic_write_bytes(dst, src.read_bytes())
    if src.suffix in (".sh", ".command") or src.stat().st_mode & 0o111:
        dst.chmod(0o755)


def _drop_stale_sidecar(
    plan: UpgradePlan, *, dry_run: bool, known: KnownHashes | None = None
) -> str:
    """Remove `<file>.new` once the live file holds (or supersedes) it.

    Called only when the live file is the current reference or builds on it.
    A sidecar is an engine copy, never local work: one equal to the current
    reference or to any earlier engine version (e.g. written by a pre-0.16
    upgrader) is obsolete. Anything else is left for the owner.
    """
    sidecar = _sidecar_path(plan.dst)
    if not sidecar.is_file():
        return ""
    data = sidecar.read_bytes()
    what = ""
    if _normalise_newlines(data) != _normalise_newlines(plan.src.read_bytes()):
        known = known if known is not None else load_known_hashes()
        if not is_known_upstream(plan.src, data, known, _repo_relative(plan.src)):
            return f"; left {sidecar.name} (not an engine version — check it by hand)"
        what = " (an older engine version)"
    if dry_run:
        return f"; would remove {sidecar.name}{what}"
    sidecar.unlink()
    return f"; removed {sidecar.name}{what}"


def _backup(plan: UpgradePlan, backup_dir: Path) -> Path:
    dest = backup_dir / (plan.rel or plan.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    kbc.atomic_write_bytes(dest, plan.dst.read_bytes())
    return dest


def apply_plan(
    plan: UpgradePlan,
    *,
    dry_run: bool,
    backup_dir: Path | None = None,
    known: KnownHashes | None = None,
) -> str:
    state = plan.state

    def drop_sidecar() -> str:
        return _drop_stale_sidecar(plan, dry_run=dry_run, known=known)

    if state == "up_to_date":
        return "skipped (up to date)" + drop_sidecar()
    if state == "missing":
        if dry_run:
            return "would copy (missing)" + drop_sidecar()
        _install(plan.src, plan.dst)
        return "copied (was missing)" + drop_sidecar()
    if state == "clean_overwrite":
        if dry_run:
            return "would overwrite (clean)" + drop_sidecar()
        _install(plan.src, plan.dst)
        return "overwritten" + drop_sidecar()
    if state == "accepted":
        if dry_run:
            return "would overwrite (upstream accepted; local copy backed up)" + drop_sidecar()
        if backup_dir is None:
            raise ValueError("accepted plans need a backup_dir")
        saved = _backup(plan, backup_dir)
        _install(plan.src, plan.dst)
        return f"overwritten (local copy → {saved})" + drop_sidecar()
    if state == "accepted_local":
        prefix = "would keep" if dry_run else "kept"
        return f"{prefix} local version (accepted)" + drop_sidecar()
    if state == "kept":
        # The local file builds on the current reference already.
        return (
            "kept (local edits; upstream unchanged since this base's version)"
            + drop_sidecar()
        )
    if state == "held":
        return f"held until {plan.held_by} is resolved"
    if state == "customized":
        new_path = _sidecar_path(plan.dst)
        lacks = (
            f"--accept-local refused: the local {plan.name} lacks "
            f"{', '.join(plan.lacks)}, used by the new scripts; merge {new_path.name}, "
            f"or take upstream: --accept {plan.name}"
        )
        if dry_run:
            if plan.lacks:
                return f"would keep {new_path.name} ({lacks})"
            return f"would write {new_path.name} (customized; {plan.diff_lines}-line diff)"
        if not (new_path.is_file() and new_path.read_bytes() == plan.src.read_bytes()):
            _install(plan.src, new_path)
        if plan.lacks:
            return f"KEPT {new_path.name} ({lacks})"
        return (
            f"WROTE {new_path.name} ({plan.diff_lines}-line diff vs deployed; "
            f"merge it, then --accept-local {plan.name})"
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


# ---------------------------------------------------------------------------
# AGENTS.md managed blocks
# ---------------------------------------------------------------------------


def block_markers(label: str) -> tuple[str, str]:
    return (
        f"<!-- AI-KE:{label}:BEGIN — managed by kb_upgrade.py -->",
        f"<!-- AI-KE:{label}:END -->",
    )


def _block_span(text: str, label: str) -> tuple[int, int] | None | str:
    """(start, stop) of the block, None when absent, "malformed" when the
    markers are unpaired or out of order."""
    begin, end = block_markers(label)
    if begin not in text and end not in text:
        return None
    if text.count(begin) != 1 or text.count(end) != 1:
        return "malformed"
    start = text.index(begin)
    stop = text.find(end, start)
    if stop == -1:
        return "malformed"
    return start, stop + len(end)


def extract_managed_blocks(text: str) -> dict[str, str]:
    """Well-formed managed blocks of `text` (markers included) by label."""
    blocks: dict[str, str] = {}
    for label in MANAGED_BLOCK_LABELS:
        span = _block_span(text, label)
        if isinstance(span, tuple):
            blocks[label] = text[span[0] : span[1]]
    return blocks


def reference_blocks() -> dict[str, str]:
    """The current managed blocks, from templates/AGENTS.md.template."""
    template = SRC_TEMPLATES_DIR / "AGENTS.md.template"
    if not template.is_file():
        return {}
    return extract_managed_blocks(template.read_text(encoding="utf-8"))


_DEPRECATED_BLOCK_CONSTANTS = {"VIEW_BLOCK": "VIEW", "INDEX_BLOCK": "INDEX"}


def __getattr__(name: str) -> str:
    """Deprecated pre-0.16 constants `VIEW_BLOCK` / `INDEX_BLOCK`: the current
    reference block from the template ("" when the template has none)."""
    label = _DEPRECATED_BLOCK_CONSTANTS.get(name)
    if label is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return reference_blocks().get(label, "")


def block_dependencies(label: str, reference: str | None, names: set[str]) -> set[str]:
    """Plan names of the scripts a managed block describes."""
    deps = set(BLOCK_SCRIPTS.get(label, ()))
    deps.update(_SCRIPT_MENTION_RE.findall(reference or ""))
    return deps & names


def _read_agents(agents_file: Path) -> tuple[str, str]:
    raw = agents_file.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def _write_agents(agents_file: Path, text: str, newline: str) -> None:
    kbc.atomic_write_text(agents_file, text.replace("\n", newline))


def update_managed_block(
    agents_file: Path,
    label: str,
    reference: str | None,
    *,
    base_version: str,
    repo_version: str,
    known: KnownHashes,
    dry_run: bool,
    records: dict | None = None,
    held_by: str = "",
) -> BlockResult:
    """Bring one managed block of AGENTS.md to the reference text.

    AGENTS.md is a LIVE, user-owned file. A block equal to a known upstream
    version is replaced; a locally edited one is kept. It needs an AI merge
    (a `.new` sidecar) only when the reference changed since the version the
    base carries — otherwise the local block already builds on it. A merge is
    requested once per reference (remembered in `records`): once the agent
    has merged and deleted the sidecar, the block is kept. `held_by` names
    the unresolved file a script the block describes waits for: the block
    is then left as it is.
    """
    records = records if records is not None else {}
    record_key = f"{agents_file.name}#{label}"
    if reference is None:
        return BlockResult(
            label, "no_reference", "skipped (not in templates/AGENTS.md.template)"
        )
    sidecar = agents_file.with_name(f"{agents_file.name}.{label.lower()}-block.new")

    def drop_sidecar() -> str:
        return _drop_block_sidecar(sidecar, label, reference, known, dry_run=dry_run)

    if held_by:
        current = ""
        if agents_file.is_file():
            text, _ = _read_agents(agents_file)
            span = _block_span(text, label)
            if isinstance(span, tuple):
                current = text[span[0] : span[1]]
        if _norm_block(current) == _norm_block(reference):
            return BlockResult(label, "up_to_date", "skipped (up to date)")
        return BlockResult(label, "held", f"held until {held_by} is resolved")
    if not agents_file.is_file():
        if dry_run:
            return BlockResult(label, "missing_file", "would create")
        kbc.atomic_write_text(agents_file, f"{reference}\n")
        return BlockResult(label, "missing_file", "created")

    text, newline = _read_agents(agents_file)
    span = _block_span(text, label)
    if span == "malformed":
        # Markers damaged during live editing: never guess — hand the fresh
        # reference block to the user's AI agent for a semantic merge.
        if not dry_run:
            kbc.atomic_write_text(sidecar, f"{reference}\n")
        return BlockResult(
            label, "malformed", f"AI merge required (markers damaged) → {sidecar.name}",
            sidecar=sidecar.name,
        )
    if span is None:
        index_span = _block_span(text, "INDEX") if label == "STATUS" else None
        if isinstance(index_span, tuple):
            where = "inserted after the INDEX block"
            stop = index_span[1]
            new_text = f"{text[:stop]}\n\n{reference}{text[stop:]}"
        else:
            where = "appended"
            separator = "\n" if text.endswith("\n") else "\n\n"
            new_text = f"{text}{separator}{reference}\n"
        if dry_run:
            return BlockResult(label, "missing", f"would be {where}" + drop_sidecar())
        _write_agents(agents_file, new_text, newline)
        return BlockResult(label, "missing", where + drop_sidecar())

    start, stop = span
    deployed = text[start:stop]
    reference_digest = block_digest(reference)
    if _norm_block(deployed) == _norm_block(reference):
        if not dry_run:
            records.pop(record_key, None)
        return BlockResult(label, "up_to_date", "skipped (up to date)" + drop_sidecar())
    if known.block_versions(label, block_digest(deployed)) is not None:
        if dry_run:
            return BlockResult(label, "outdated", "would update" + drop_sidecar())
        _write_agents(agents_file, f"{text[:start]}{reference}{text[stop:]}", newline)
        records.pop(record_key, None)
        return BlockResult(label, "outdated", "updated" + drop_sidecar())
    record = records.get(record_key)
    requested = isinstance(record, dict) and record.get("source") == reference_digest
    pending = requested and not record.get("merged")
    versions = known.block_versions(label, reference_digest)
    if requested or upstream_unchanged_since(base_version, repo_version, versions):
        kept = (
            "kept (local edits; the reference was merged)"
            if requested
            else "kept (local edits; reference unchanged since this base's version)"
        )
        if not sidecar.is_file():
            if pending and not dry_run:
                # The agent merged and deleted the sidecar.
                records[record_key] = {"source": reference_digest, "merged": True}
            return BlockResult(label, "edited", kept)
        if not pending and _block_sidecar_is_engine_copy(sidecar, label, reference, known):
            # No merge is open for this reference: the sidecar was left by an
            # earlier upgrade (e.g. a pre-0.16 one) or reappeared after the
            # merge, and the local block already builds on the reference.
            return BlockResult(label, "edited", kept + drop_sidecar())
        # A requested merge still open, or a sidecar someone changed: leave it.
        return BlockResult(
            label, "edited", f"AI merge pending (local edits kept) → {sidecar.name}",
            sidecar=sidecar.name,
        )
    # The reference moved on and the block was customized while working in
    # the base — replacing it would destroy those improvements. AI merge.
    if not dry_run:
        kbc.atomic_write_text(sidecar, f"{reference}\n")
        records[record_key] = {"source": reference_digest}
    return BlockResult(
        label, "edited", f"AI merge required (local edits kept) → {sidecar.name}",
        sidecar=sidecar.name,
    )


def _block_sidecar_is_engine_copy(
    sidecar: Path, label: str, reference: str, known: KnownHashes
) -> bool:
    """The sidecar holds the reference block or an earlier one — no local work."""
    content = sidecar.read_text(encoding="utf-8", errors="replace")
    return (
        _norm_block(content) == _norm_block(reference)
        or known.block_versions(label, block_digest(content)) is not None
    )


def _drop_block_sidecar(
    sidecar: Path, label: str, reference: str, known: KnownHashes, *, dry_run: bool
) -> str:
    """Remove a block sidecar equal to the reference or to an earlier one."""
    if not sidecar.is_file():
        return ""
    if not _block_sidecar_is_engine_copy(sidecar, label, reference, known):
        return f"; left {sidecar.name} (not an engine version — check it by hand)"
    if dry_run:
        return f"; would remove {sidecar.name}"
    sidecar.unlink()
    return f"; removed {sidecar.name}"


def report_invariant_blocks(agents_file: Path) -> tuple[str, str]:
    """Report INVARIANT presence. Never writes or wraps the file.

    Returns ``(state, action)``. Missing wrappers are left for ``!heal``.
    """
    if not agents_file.is_file():
        return "missing", "left for !heal"
    text = agents_file.read_text(encoding="utf-8")
    present = kbc.invariant_ids(text)
    required = kbc.REQUIRED_INVARIANT_IDS
    if required <= present and not kbc.invariant_problems(text):
        return "present", "respected (never overwritten)"
    return "missing", "left for !heal"


# ---------------------------------------------------------------------------
# kb.config.yml
# ---------------------------------------------------------------------------


def kb_config_index_state(kb_root: Path) -> str:
    cfg_file = kb_root / "kb.config.yml"
    if not cfg_file.is_file():
        return "missing_file"
    for line in cfg_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("index:"):
            return "present"
    return "missing"


def ensure_index_section(kb_root: Path, *, dry_run: bool) -> str:
    """Additively append the `index:` pack config to kb.config.yml."""
    state = kb_config_index_state(kb_root)
    if state == "present":
        return "skipped (present)"
    if state == "missing_file":
        return "skipped (no kb.config.yml)"
    if dry_run:
        return "would append"
    try:
        kbc.update_config_file(
            kb_root, [lambda text: kbc.config_append_block(text, "index", INDEX_YAML_BLOCK)]
        )
    except kbc.ConfigEditError as exc:
        return f"skipped ({exc})"
    return "appended"


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


def _bump_deployed_version(kb_root: Path, repo_version: str) -> bool:
    """Set `instructions_version` in place (its trailing comment survives).

    Raises ``kbc.ConfigEditError`` when kb.config.yml cannot be edited safely.
    """
    return kbc.update_config_file(kb_root, {"instructions_version": repo_version})


def _heal_settings(kb_root: Path) -> tuple[bool, int, str]:
    """(auto_apply, stage, heal.last_run.version); raises for invalid YAML."""
    cfg = kbc.load_config(kb_root)
    heal = cfg.raw.get("heal") if isinstance(cfg.raw.get("heal"), dict) else {}
    try:
        stage = int(heal.get("stage") or 1)
    except (TypeError, ValueError):
        stage = 1
    last_run = heal.get("last_run")
    last_version = str(last_run.get("version") or "") if isinstance(last_run, dict) else ""
    return bool(heal.get("auto_apply", True)), stage, last_version


def _latest_version(*versions: str) -> str | None:
    comparable = [v for v in versions if version_key(v) is not None]
    return max(comparable, key=version_key) if comparable else None


# ---------------------------------------------------------------------------
# Heal
# ---------------------------------------------------------------------------


def run_post_upgrade_heal(
    kb_root: Path,
    *,
    dry_run: bool,
    enabled: bool,
    target_version: str | None = None,
) -> str:
    """Detect (always) and apply the auto bucket unless dry-run / disabled.

    Runs the BASE's `scripts/kb_heal.py` in a separate interpreter (dry-run:
    the engine's, as a preview), so a base left inconsistent by the file sync
    fails here instead of being reported as healed. `target_version` is
    stamped into `heal.last_run.version`. Returns "ok", "skipped" or
    "failed"; a failure is reported, never raised.
    """
    if not enabled:
        print("Heal skipped (--no-heal)")
        return "skipped"
    scripts_dir = SRC_SCRIPTS_DIR if dry_run else kb_root / "scripts"
    if not (scripts_dir / "kb_heal.py").is_file():
        print(f"[WARN] heal skipped: {scripts_dir / 'kb_heal.py'} not found")
        return "skipped"
    try:
        auto_apply, stage, _ = _heal_settings(kb_root)
    except Exception as exc:  # noqa: BLE001 — heal must not abort the upgrade
        print(f"[WARN] heal skipped: {type(exc).__name__}: {exc}")
        print("  Fix kb.config.yml, then run: python3 scripts/kb_heal.py --plan")
        return "failed"
    env = {
        **os.environ,
        "AI_KNOWLEDGE_ENGINE_HOME": str(REPO_ROOT),
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            HEAL_DRIVER,
            str(scripts_dir),
            str(kb_root),
            "detect" if dry_run else "apply",
            target_version or "",
            "1" if auto_apply else "0",
            str(stage),
        ],
        capture_output=True,
        check=False,
        cwd=str(kb_root),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.returncode == 0:
        return "ok"
    tail = "\n".join(result.stderr.strip().splitlines()[-6:])
    print(f"[WARN] heal failed in {scripts_dir} (exit {result.returncode}):")
    if tail:
        print(tail)
    print(
        "  The base's scripts may be inconsistent. Run python3 scripts/kb_doctor.py "
        "in the base, then python3 scripts/kb_heal.py --plan."
    )
    return "failed"


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def _warn_unknown_names(plans: list[UpgradePlan], flag: str, values: list[str]) -> None:
    names = {plan.name for plan in plans}
    for value in values:
        wanted = {_normalise_accept_name(value)}
        if not any(_plan_is_accepted(name, wanted) for name in names):
            print(f"[WARN] {flag} {value}: no managed file by that name")


HOOK_MARKER = "ai-knowledge-engine post-commit hook"   # first comment line of shell/hooks/post-commit


def outdated_installed_hook(kb_root: Path) -> Path | None:
    """The installed git post-commit hook, when it is a copy of ours that
    differs from the base's ``shell/hooks/post-commit``.

    ``shell/install-hooks.sh`` copies the hook into the repository's hooks
    folder, so updating ``shell/hooks/post-commit`` does not reach it. A
    foreign hook (no marker line) is not reported.
    """
    shipped = kb_root / "shell" / "hooks" / "post-commit"
    if not shipped.is_file():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(kb_root), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    hooks = result.stdout.strip()
    if result.returncode != 0 or not hooks:
        return None
    installed = Path(hooks)
    if not installed.is_absolute():
        installed = kb_root / installed   # relative to the -C folder
    installed = installed / "post-commit"
    try:
        data = installed.read_bytes()
        current = shipped.read_bytes()
    except OSError:
        return None
    if HOOK_MARKER.encode() not in data or data == current:
        return None
    return installed


def upgrade_one(kb_root: Path, args: argparse.Namespace) -> int:
    if not (kb_root / "kb.config.yml").is_file():
        print(f"[ERROR] {kb_root}: kb.config.yml not found", file=sys.stderr)
        return 3

    repo_version = get_repo_version()
    deployed_version = get_deployed_version(kb_root)
    print(f"Repo version:     {repo_version}")
    print(f"Deployed version: {deployed_version}")
    deployed_key, repo_key = version_key(deployed_version), version_key(repo_version)
    if deployed_key and repo_key and deployed_key > repo_key:
        print(
            f"[ERROR] {kb_root}: the base is at {deployed_version}, newer than this "
            f"engine checkout ({repo_version}). Update the checkout; an upgrade "
            "never moves a base backwards.",
            file=sys.stderr,
        )
        return 3
    accept_local = list(getattr(args, "accept_local", []) or [])
    both = {_normalise_accept_name(v) for v in args.accept} & {
        _normalise_accept_name(v) for v in accept_local
    }
    if both:
        print(
            f"[ERROR] both --accept and --accept-local given for: {', '.join(sorted(both))}",
            file=sys.stderr,
        )
        return 3

    known = load_known_hashes()
    plans = collect_plans(
        kb_root,
        prev_version=deployed_version,
        force=args.force,
        accepted=set(args.accept),
        accepted_local=set(accept_local),
        repo_version=repo_version,
        known=known,
    )
    _warn_unknown_names(plans, "--accept", args.accept)
    _warn_unknown_names(plans, "--accept-local", accept_local)
    backup_dir = None
    if not args.dry_run and any(plan.state == "accepted" for plan in plans):
        stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup_dir = kbc.state_dir(kb_root) / BACKUPS_DIR / stamp

    print("")
    print("Upgrade plan:")
    print(f"{'file':<46} {'state':<20} {'action'}")
    print("-" * 92)
    changed = False
    records = _load_local_accepts(kb_root)
    records_before = dict(records)
    for plan in plans:
        action = apply_plan(plan, dry_run=args.dry_run, backup_dir=backup_dir, known=known)
        if plan.state not in ("up_to_date", "kept", "accepted_local"):
            changed = True
        if plan.state == "accepted_local" and not args.dry_run:
            records[plan.rel] = _local_accept_record(plan)
        print(f"{plan.name:<46} {plan.state:<20} {action}")

    agents_file = kb_root / "AGENTS.md"
    references = reference_blocks()
    unresolved = unresolved_files(plans)
    merge_sidecars: list[str] = []
    for label in MANAGED_BLOCK_LABELS:
        waits_for = sorted(block_dependencies(label, references.get(label), set(unresolved)))
        result = update_managed_block(
            agents_file,
            label,
            references.get(label),
            base_version=deployed_version,
            repo_version=repo_version,
            known=known,
            dry_run=args.dry_run,
            records=records,
            held_by=unresolved[waits_for[0]] if waits_for else "",
        )
        row = f"AGENTS.md ({label.lower()} block)"
        print(f"{row:<46} {result.state:<20} {result.action}")
        if result.state not in ("up_to_date", "no_reference", "edited"):
            changed = True
        if result.sidecar:
            merge_sidecars.append(result.sidecar)
    if records != records_before:
        kbc.write_json(kbc.state_dir(kb_root) / LOCAL_ACCEPTS_FILE, records)

    invariant_state, invariant_action = report_invariant_blocks(agents_file)
    print(
        f"{'AGENTS.md (INVARIANT blocks)':<46} {invariant_state:<20} "
        f"{invariant_action}"
    )

    if merge_sidecars:
        print(
            "\nAGENTS.md has local improvements in managed blocks — they were "
            "NOT overwritten.\nAsk your AI agent to merge, e.g.:"
        )
        for sidecar in merge_sidecars:
            print(f'  "{AI_MERGE_PROMPT.format(sidecar=sidecar)}"')

    index_cfg_state = kb_config_index_state(kb_root)
    index_cfg_action = ensure_index_section(kb_root, dry_run=args.dry_run)
    print(f"{'kb.config.yml (index: section)':<46} {index_cfg_state:<20} {index_cfg_action}")
    if index_cfg_state == "missing":
        changed = True

    customized = [plan for plan in plans if plan.state == "customized"]
    held = [plan for plan in plans if plan.state == "held"]
    config_ok = deployed_version != "unparseable"
    will_bump = not args.dry_run and not customized and not held and config_ok

    # Heal runs before the version bump on purpose: it needs the *old*
    # instructions_version to pick the MIGRATIONS.md range. It stamps the
    # version the base is about to carry — never an older one than it has.
    last_heal_version = ""
    if config_ok:
        try:
            last_heal_version = _heal_settings(kb_root)[2]
        except Exception:  # noqa: BLE001 — reported by the heal step below
            pass
    stamp = (
        repo_version
        if will_bump
        else _latest_version(deployed_version, last_heal_version)
    )
    heal_state = run_post_upgrade_heal(
        kb_root,
        dry_run=args.dry_run,
        enabled=not getattr(args, "no_heal", False),
        target_version=stamp,
    )
    if heal_state == "failed":
        will_bump = False

    if args.diff and customized:
        print("\n=== Diffs ===\n")
        print(write_diff_text(plans))

    bump_failed = False
    if will_bump:
        try:
            if _bump_deployed_version(kb_root, repo_version):
                print(f"\n[OK] instructions_version set to {repo_version}")
        except kbc.ConfigEditError as exc:
            bump_failed = True
            print(f"\n[WARN] instructions_version not updated: {exc}")
    elif not args.dry_run and not config_ok:
        bump_failed = True
        print(
            "\n[WARN] kb.config.yml does not parse — instructions_version not "
            "updated. Fix it and re-run the upgrade."
        )

    review = len(customized) + len(held) + len(merge_sidecars)
    if customized and not args.dry_run:
        print(
            f"\n[WARN] {len(customized)} customized file(s) got a .new sidecar. "
            "Merge each into the live file, then re-run with --accept-local <file> "
            "(keep your merged file) or --accept <file> (take upstream; your copy "
            f"is saved under {kbc.STATE_DIR}/{BACKUPS_DIR}/)."
        )
    if held:
        print(
            f"\n[WARN] {len(held)} file(s) held back until the customized file "
            "they depend on is resolved: "
            + ", ".join(sorted({plan.held_by for plan in held}))
        )
    stale_hook = None if args.dry_run else outdated_installed_hook(kb_root)
    if stale_hook is not None:
        print(
            f"\n[INFO] The installed git hook {stale_hook} is an older copy of "
            "shell/hooks/post-commit. Re-run `bash shell/install-hooks.sh` "
            "(it keeps the old copy as post-commit.backup-<timestamp>)."
        )
    problems = bool(review) or heal_state == "failed" or bump_failed
    if args.dry_run:
        if review:
            print(
                f"\n[WARN] {review} item(s) require review. "
                "Dry-run made no changes and wrote no .new sidecars."
            )
        elif changed:
            print("\n[OK] Dry-run complete; no files were changed.")
        return 2 if problems else 0
    if not will_bump or bump_failed:
        print(f"\n[WARN] instructions_version stays at {deployed_version}.")
    if problems:
        return 2
    if not changed and deployed_version == repo_version:
        print("\nAlready up to date.")
    return 0


def build_parser() -> argparse.ArgumentParser:
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
        help="Take upstream for one customized file (repeatable); the local "
        f"copy is saved under {kbc.STATE_DIR}/{BACKUPS_DIR}/",
    )
    parser.add_argument(
        "--accept-local",
        action="append",
        default=[],
        metavar="FILE",
        help="Keep the local version of one customized file — you merged its "
        ".new sidecar (repeatable; remembered until either side changes)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Take upstream for every customized file, i.e. every file that would "
        "get a .new sidecar (local copies are backed up); kept and --accept-local "
        "files are left alone — name them with --accept",
    )
    parser.add_argument(
        "--no-heal",
        action="store_true",
        help="Skip post-upgrade detect / auto-heal (heal.auto_apply still applies otherwise)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
