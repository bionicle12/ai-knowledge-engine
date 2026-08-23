#!/usr/bin/env python3
"""kb_heal — catch-up repair after an upgrade. No LLM.

``--plan`` collects doctor, lint L1, MIGRATIONS.md, hanging ``.new``
sidecars, and stale packs into ``review/needs-heal/HEAL_PLAN.md``.
``--apply auto`` applies only the auto bucket (idempotent, with a
``.kb-backups/`` snapshot). Assisted and human buckets are never applied
here — they are the ``!heal`` queue.

See ``18_HEAL.md``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402
import kb_doctor  # noqa: E402
import kb_lint  # noqa: E402

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


HEAL_PLAN_NAME = "HEAL_PLAN.md"
BACKUP_ROOT = ".kb-backups"
DEFAULT_ASSISTED_BATCH = 20
STUCK_DAYS = 14
STAGE_NAMES = {1: "safe", 2: "hygiene", 3: "measure", 4: "trim", 5: "content"}

DEFAULT_INSTRUCTIONS_LINT = """\
instructions_lint:
  agents_max_bytes: 10240
  absolute_max_outside_invariants: 8
  review_stale_days: 90
  work_ordering_phrases:
    - "максимально тщательно"
    - "рассмотри все варианты"
    - "перепроверь несколько раз"
    - "добейся полной уверенности"
    - "thoroughly"
    - "consider all"
    - "be maximally"
"""

DEFAULT_HEAL = """\
heal:
  auto_apply: true
  stage: 1
  assisted_batch: 20
"""

DEFAULT_INSTRUCTIONS_REVIEW = """\
instructions_review:
  reviewed_at: ""
  reviewed_model: ""
  clean_run_baseline: ""
"""

_SKIP_SIDECAR_PARTS = {".venv", "venv", ".git", ".kb-backups", "node_modules", "__pycache__"}
_HYGIENE_LINT = {
    "frontmatter",
    "broken-link",
    "source-hash",
    "duplicate-slug",
    "expired-temporal",
    "orphan",
    "stale",
    "invariants",
    "superseded",
}
_TRIM_LINT = {"agents-bytes", "instruction-absolutes", "work-ordering"}
_CONTENT_LINT = {"instructions-review", "profile-review"}


@dataclass
class MigrationStep:
    version: str
    id: str
    bucket: str
    detect: str = ""
    fix: str = ""


@dataclass
class Finding:
    id: str
    bucket: str
    title: str
    detail: str = ""
    source: str = ""
    stage: int = 1
    locked: bool = False
    fix: str = ""


def parse_migrations(text: str) -> list[MigrationStep]:
    steps: list[MigrationStep] = []
    current_version = "0.0.0"
    current: MigrationStep | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            rest = line[3:].strip().split()[0]
            if re.match(r"^\d+\.\d+", rest):
                current_version = rest
            continue
        id_m = re.match(r"- id:\s*(\S+)\s*$", line)
        if id_m:
            if current is not None:
                steps.append(current)
            current = MigrationStep(
                version=current_version, id=id_m.group(1), bucket=""
            )
            continue
        if current is None:
            continue
        field_m = re.match(r"  (bucket|detect|fix):\s*(.*)$", line)
        if not field_m:
            continue
        value = field_m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        setattr(current, field_m.group(1), value)
    if current is not None:
        steps.append(current)
    return steps


def load_migrations_text(
    *, migrations_text: str | None = None, migrations_path: Path | None = None
) -> str:
    if migrations_text is not None:
        return migrations_text
    path = migrations_path or find_migrations_file()
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def find_migrations_file() -> Path | None:
    env = os.environ.get("AI_KNOWLEDGE_ENGINE_HOME", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / "MIGRATIONS.md")
    here = SCRIPT_DIR
    for parent in (here, *here.parents):
        candidates.append(parent / "MIGRATIONS.md")
        candidates.append(parent / "ai-knowledge-engine" / "MIGRATIONS.md")
    try:
        import kb_update

        repo = kb_update.find_source_repo(
            explicit=None,
            start=Path.cwd(),
            script_path=Path(__file__),
        )
        candidates.append(repo / "MIGRATIONS.md")
    except Exception:
        pass
    seen: set[str] = set()
    for cand in candidates:
        try:
            key = str(cand.resolve())
        except OSError:
            key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return None


def _config_text(root: Path) -> str:
    path = root / "kb.config.yml"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _has_top_level_key(text: str, key: str) -> bool:
    return bool(re.search(rf"^{re.escape(key)}:", text, re.MULTILINE))


def measure_closed(root: Path) -> bool:
    questions = root / kbc.EVAL_ROOT / "QUESTIONS.md"
    if not questions.is_file():
        return False
    text = questions.read_text(encoding="utf-8")
    if "{{EVAL_" in text:
        return False
    return all(f"## Q{i}." in text for i in (1, 2, 3))


def _heal_settings(root: Path) -> dict:
    cfg = kbc.load_config(root)
    raw = (cfg.raw.get("heal") or {}) if cfg.raw else {}
    return {
        "auto_apply": bool(raw.get("auto_apply", True)),
        "stage": int(raw.get("stage") or 1),
        "assisted_batch": int(raw.get("assisted_batch") or DEFAULT_ASSISTED_BATCH),
        "last_run": raw.get("last_run") or {},
        "instructions_version": cfg.instructions_version,
    }


def _detect_instruction_lint(root: Path) -> bool:
    return not _has_top_level_key(_config_text(root), "instructions_lint")


def _detect_heal_config(root: Path) -> bool:
    return not _has_top_level_key(_config_text(root), "heal")


def _detect_instructions_review(root: Path) -> bool:
    return not _has_top_level_key(_config_text(root), "instructions_review")


def _detect_agents_max_bytes(root: Path) -> bool:
    if not _has_top_level_key(_config_text(root), "instructions_lint"):
        return False
    cfg = kbc.load_config(root)
    raw = (cfg.raw.get("instructions_lint") or {}) if cfg.raw else {}
    val = raw.get("agents_max_bytes")
    if val is None:
        return True
    try:
        return int(val) < 10240
    except (TypeError, ValueError):
        return True


def _detect_agents_c2_trim(root: Path) -> bool:
    path = root / "AGENTS.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return (
        "## Token budget" in text
        or "Auto-detects when meaningful material has accumulated" in text
        or "If you've loaded > 5" in text
        or "If you have loaded > 5" in text
    )


def _detect_refactor_command(root: Path) -> bool:
    path = root / "AGENTS.md"
    if not path.is_file():
        return False
    return "!refactor" not in path.read_text(encoding="utf-8")


def _detect_profile_review_command(root: Path) -> bool:
    path = root / "AGENTS.md"
    if not path.is_file():
        return False
    return "!profile-review" not in path.read_text(encoding="utf-8")


def _detect_quiz_command(root: Path) -> bool:
    path = root / "AGENTS.md"
    if not path.is_file():
        return False
    return "!quiz" not in path.read_text(encoding="utf-8")


def _detect_eval_skeleton(root: Path) -> bool:
    return not (root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR).is_dir()


def _detect_eval_bootstrap(root: Path) -> bool:
    return not (root / kbc.EVAL_ROOT / "QUESTIONS.md").is_file()


def _detect_invariants(root: Path) -> bool:
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return False
    return bool(kbc.invariant_problems(agents.read_text(encoding="utf-8")))


def _detect_codex_window(root: Path) -> bool:
    cfg = kbc.load_config(root)
    index = cfg.index or {}
    if str(index.get("primary_agent") or "").lower() != "codex":
        return False
    profile = str(index.get("window_profile") or "")
    return profile in {"", "256k"}


def _detect_doctor_codex_env(root: Path) -> bool:
    script = root / "scripts" / "kb_doctor.py"
    if not script.is_file():
        return False
    return "def check_agent_env" not in script.read_text(encoding="utf-8")


def _detect_start_here_opening(root: Path) -> bool:
    path = root / "START_HERE.md"
    if not path.is_file():
        return False
    return "the agent has no idea this knowledge base exists" in path.read_text(
        encoding="utf-8"
    )


def _detect_agents_stopper(root: Path) -> bool:
    path = root / "AGENTS.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return (
        "If the user issues a `!`-command before that opening line" in text
        or "re-issue the command" in text
    )


def _detect_claude_md_bridge(root: Path) -> bool:
    path = root / "CLAUDE.md"
    if not path.is_file():
        return False
    return "@AGENTS.md" not in path.read_text(encoding="utf-8")


DETECT_BY_ID = {
    "instruction-lint-config": _detect_instruction_lint,
    "heal-config": _detect_heal_config,
    "instructions-review-config": _detect_instructions_review,
    "agents-max-bytes-10kib": _detect_agents_max_bytes,
    "agents-md-c2-trim": _detect_agents_c2_trim,
    "refactor-command": _detect_refactor_command,
    "profile-review-command": _detect_profile_review_command,
    "quiz-command": _detect_quiz_command,
    "eval-skeleton": _detect_eval_skeleton,
    "eval-bootstrap": _detect_eval_bootstrap,
    "agents-md-invariants": _detect_invariants,
    "codex-window-profile": _detect_codex_window,
    "doctor-codex-env": _detect_doctor_codex_env,
    "start-here-opening-line": _detect_start_here_opening,
    "agents-md-stopper": _detect_agents_stopper,
    "claude-md-bridge": _detect_claude_md_bridge,
}

STAGE_BY_ID = {
    "instruction-lint-config": 1,
    "heal-config": 1,
    "instructions-review-config": 1,
    "agents-max-bytes-10kib": 1,
    "refactor-command": 2,
    "profile-review-command": 2,
    "quiz-command": 2,
    "agents-md-c2-trim": 4,
    "eval-skeleton": 1,
    "codex-window-profile": 1,
    "doctor-codex-env": 1,
    "packs-stale": 1,
    "agents-md-invariants": 1,
    "start-here-opening-line": 2,
    "agents-md-stopper": 2,
    "eval-bootstrap": 3,
    "claude-md-bridge": 3,
}

AUTO_BUILTINS = (
    ("instruction-lint-config", "auto", "kb.config.yml has no instructions_lint:"),
    ("heal-config", "auto", "kb.config.yml has no heal:"),
    ("instructions-review-config", "auto", "kb.config.yml has no instructions_review:"),
    ("agents-max-bytes-10kib", "auto", "instructions_lint.agents_max_bytes is below 10240"),
    ("refactor-command", "assisted", "AGENTS.md command table has no !refactor"),
    ("profile-review-command", "assisted", "AGENTS.md command table has no !profile-review"),
    ("quiz-command", "assisted", "AGENTS.md command table has no !quiz"),
    ("agents-md-c2-trim", "assisted", "AGENTS.md still has Token budget / auto-detect / >5 stop"),
    ("eval-skeleton", "auto", "eval/results/ is missing"),
    ("codex-window-profile", "auto", "Codex base still on window_profile 256k"),
    ("doctor-codex-env", "auto", "deployed kb_doctor.py has no check_agent_env"),
    ("packs-stale", "auto", "Repomix packs are older than knowledge/"),
    ("eval-bootstrap", "human", "eval/QUESTIONS.md is missing"),
    ("agents-md-invariants", "assisted", "AGENTS.md lacks AI-KE:INVARIANT wrappers"),
    ("start-here-opening-line", "assisted", "START_HERE.md still uses the blind-agent opening-line claim"),
    ("agents-md-stopper", "assisted", "AGENTS.md still has the !-command stopper"),
    ("claude-md-bridge", "human", "CLAUDE.md exists but does not import @AGENTS.md"),
)


def _sidecars(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not root.is_dir():
        return findings
    for path in root.rglob("*.new"):
        if any(part in _SKIP_SIDECAR_PARTS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        findings.append(
            Finding(
                id=f"sidecar:{rel}",
                bucket="assisted",
                title=rel,
                detail="hanging upgrade sidecar — merge, then delete .new",
                source="sidecar",
                stage=2,
                fix="ask the agent to merge the sidecar into the live file",
            )
        )
    return findings


def _packs_stale(root: Path) -> bool:
    knowledge = root / "knowledge"
    packs = root / ".repomix"
    if not knowledge.is_dir() or not packs.is_dir():
        return False
    md = [p for p in knowledge.rglob("*.md") if p.is_file()]
    xml = [p for p in packs.glob("*.xml") if p.is_file()]
    if not md or not xml:
        return False
    return max(p.stat().st_mtime for p in md) > max(p.stat().st_mtime for p in xml) + 1


def _lint_findings(root: Path) -> list[Finding]:
    report = kb_lint.run_lint(root)
    out: list[Finding] = []
    for issue in report.issues:
        if issue.severity == "info":
            continue
        if issue.check in _TRIM_LINT:
            stage, bucket = 4, "human"
        elif issue.check in _CONTENT_LINT:
            stage, bucket = 5, "human"
        elif issue.check in _HYGIENE_LINT or issue.severity == "error":
            stage, bucket = 2, "assisted"
        else:
            continue
        out.append(
            Finding(
                id=f"lint:{issue.check}:{issue.path}",
                bucket=bucket,
                title=f"[{issue.check}] {issue.path}",
                detail=issue.message,
                source="lint",
                stage=stage,
                fix="see 09_LINT.md / !heal hygiene",
            )
        )
    return out


def _doctor_findings(root: Path) -> list[Finding]:
    results = kb_doctor.run_all_checks(root, skip_nlp=True, ephemeral_log=True)
    out: list[Finding] = []
    for item in results:
        if item.severity != "error":
            continue
        if item.name.startswith("heal:"):
            continue
        out.append(
            Finding(
                id=f"doctor:{item.name}",
                bucket="assisted",
                title=item.name,
                detail=item.message,
                source="doctor",
                stage=1,
                fix="see kb_doctor output",
            )
        )
    return out


def collect_findings(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    seen: set[str] = set()

    def add(finding: Finding) -> None:
        if finding.id in seen:
            return
        seen.add(finding.id)
        findings.append(finding)

    text = load_migrations_text(
        migrations_text=migrations_text, migrations_path=migrations_path
    )
    steps = parse_migrations(text) if text else []
    for step in steps:
        detector = DETECT_BY_ID.get(step.id)
        if detector is None:
            continue
        if not detector(root):
            continue
        add(
            Finding(
                id=step.id,
                bucket=step.bucket or "assisted",
                title=step.id,
                detail=step.detect,
                source="migration",
                stage=STAGE_BY_ID.get(step.id, 2),
                fix=step.fix,
            )
        )

    for mid, bucket, detail in AUTO_BUILTINS:
        detector = DETECT_BY_ID.get(mid)
        hit = _packs_stale(root) if mid == "packs-stale" else (
            detector(root) if detector else False
        )
        if not hit:
            continue
        add(
            Finding(
                id=mid,
                bucket=bucket,
                title=mid,
                detail=detail,
                source="auto",
                stage=STAGE_BY_ID.get(mid, 1),
                fix="deterministic apply (--apply auto)" if bucket == "auto" else "",
            )
        )

    for finding in _sidecars(root):
        add(finding)
    for finding in _lint_findings(root):
        add(finding)
    for finding in _doctor_findings(root):
        add(finding)

    closed = measure_closed(root)
    for finding in findings:
        if finding.stage == 4 and not closed:
            finding.locked = True
    return findings


def render_plan(root: Path, findings: list[Finding]) -> str:
    settings = _heal_settings(root)
    batch = settings["assisted_batch"]
    # Locked items get their own section; listing them in a bucket too would
    # double-count them in the summary and read as work that can start now.
    auto = [f for f in findings if f.bucket == "auto" and not f.locked]
    assisted = [f for f in findings if f.bucket == "assisted" and not f.locked]
    human = [f for f in findings if f.bucket == "human" and not f.locked]
    locked = [f for f in findings if f.locked]
    shown, deferred = assisted[:batch], assisted[batch:]
    today = _dt.date.today().isoformat()
    lines = [
        f"# Heal plan — {today}",
        "",
        f"Catch-up from `instructions_version` {settings['instructions_version']}.",
        f"heal.stage: {settings['stage']} ({STAGE_NAMES.get(settings['stage'], '?')})",
        f"assisted_batch: {batch}",
        "",
        "## Summary",
        f"- auto: {len(auto)}",
        f"- assisted: {len(assisted)} (showing {len(shown)}, {len(deferred)} deferred)",
        f"- human: {len(human)}",
        f"- locked (stage 4 trim): {len(locked)}",
        "",
    ]
    if not findings:
        lines += [
            "No findings. The base is in order.",
            "",
            '→ next: nothing to do — `!heal` ends here.',
            "",
        ]
        return "\n".join(lines)

    def dump(title: str, items: list[Finding]) -> None:
        lines.append(f"## {title}")
        if not items:
            lines.append("- (none)")
            lines.append("")
            return
        for item in items:
            lock = " *(locked until stage 3 measure is closed)*" if item.locked else ""
            lines.append(f"- [ ] `{item.id}` — {item.title}{lock}")
            if item.detail:
                lines.append(f"  - {item.detail}")
            if item.fix:
                lines.append(f"  - fix: {item.fix}")
        lines.append("")

    dump("auto", auto)
    dump("assisted", shown)
    if deferred:
        dump("assisted (deferred to later sessions)", deferred)
    dump("human", human)
    if locked:
        dump("Locked (stage 4 trim — wait for measure)", locked)
    lines.append('→ next: скажи агенту "!heal"')
    lines.append("")
    return "\n".join(lines)


def write_plan(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
) -> Path:
    findings = collect_findings(
        root, migrations_text=migrations_text, migrations_path=migrations_path
    )
    dest = root / "review" / "needs-heal" / HEAL_PLAN_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_plan(root, findings), encoding="utf-8")
    return dest


def create_backup(root: Path) -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = root / BACKUP_ROOT / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("kb.config.yml", "AGENTS.md", "START_HERE.md"):
        src = root / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    (dest / "MANIFEST.txt").write_text("kb_heal backup\n", encoding="utf-8")
    return dest


def latest_backup(root: Path) -> Path | None:
    parent = root / BACKUP_ROOT
    if not parent.is_dir():
        return None
    dirs = sorted((p for p in parent.iterdir() if p.is_dir()), reverse=True)
    return dirs[0] if dirs else None


def restore_backup(root: Path, backup: Path | None = None) -> Path | None:
    backup = backup or latest_backup(root)
    if backup is None:
        return None
    for src in backup.iterdir():
        if src.name == "MANIFEST.txt":
            continue
        shutil.copy2(src, root / src.name)
    return backup


def eval_regressed(root: Path) -> bool:
    results = root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR
    if not results.is_dir():
        return False
    after = sorted(
        (p for p in results.glob("*.md") if "after" in p.name.lower()),
        key=lambda p: p.stat().st_mtime,
    )
    if not after:
        return False
    text = after[-1].read_text(encoding="utf-8").lower()
    return any(
        marker in text
        for marker in ("eval: regressed", "verdict: failed", "регресс")
    )


def verify(root: Path) -> str:
    if not eval_regressed(root):
        return "ok"
    restored = restore_backup(root)
    if restored is None:
        return "eval regressed; no backup to roll back"
    return f"rolled back from {restored.name}"


def _append_block(root: Path, block: str) -> None:
    path = root / "kb.config.yml"
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    sep = "\n" if current.endswith("\n") else "\n\n"
    path.write_text(f"{current}{sep}{block.lstrip()}", encoding="utf-8")


def _set_window_profile(root: Path, value: str) -> None:
    path = root / "kb.config.yml"
    text = path.read_text(encoding="utf-8")
    if re.search(r"window_profile:", text):
        text = re.sub(
            r"(window_profile:\s*)([\"']?)[\w.]+\2",
            rf"\g<1>\g<2>{value}\g<2>",
            text,
            count=1,
        )
        path.write_text(text, encoding="utf-8")
        return
    if yaml is None:
        return
    data = yaml.safe_load(text) or {}
    index = data.setdefault("index", {})
    index["window_profile"] = value
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _set_agents_max_bytes(root: Path, value: int) -> None:
    path = root / "kb.config.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if re.search(r"agents_max_bytes:\s*\d+", text):
        path.write_text(
            re.sub(r"(agents_max_bytes:\s*)\d+", rf"\g<1>{value}", text, count=1),
            encoding="utf-8",
        )
        return
    if yaml is None:
        return
    data = yaml.safe_load(text) or {}
    lint = data.setdefault("instructions_lint", {})
    lint["agents_max_bytes"] = value
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


_HEAL_KEY_RE = re.compile(r"^heal:\s*(#.*)?$")
_LAST_RUN_KEYS = ("last_run:", "at:", "version:")


def _is_last_run_line(line: str) -> bool:
    """True for `last_run:` and its children, commented out or not."""
    content = line.strip()
    while content.startswith("#"):
        content = content[1:].strip()
    return content.startswith(_LAST_RUN_KEYS)


def _touch_last_run(root: Path, version: str | None = None) -> None:
    """Stamp `heal.last_run` in place.

    Line surgery, not a YAML round-trip: `kb.config.yml` is a commented,
    hand-edited file and `safe_dump` would strip every comment in it.

    ``version`` is the version the base will carry *after* the caller is done.
    Upgrade stamps it explicitly, because heal runs before the version bump
    (it needs the old value to compute the `MIGRATIONS.md` range).
    """
    path = root / "kb.config.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if version is None:
        found = re.search(
            r"(?m)^instructions_version:\s*[\"']?([^\"'\s#]+)", text
        )
        version = found.group(1) if found else ""
    stamp = [
        "  last_run:",
        f'    at: "{_dt.date.today().isoformat()}"',
        f'    version: "{version}"',
    ]

    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if _HEAL_KEY_RE.match(line)), None
    )
    if start is None:
        sep = "" if text.endswith("\n") else "\n"
        block = DEFAULT_HEAL.rstrip("\n") + "\n" + "\n".join(stamp) + "\n"
        path.write_text(f"{text}{sep}\n{block}", encoding="utf-8")
        return

    end = start + 1
    while end < len(lines) and (
        not lines[end].strip() or lines[end].startswith((" ", "\t"))
    ):
        end += 1
    body = [line for line in lines[start + 1 : end] if not _is_last_run_line(line)]
    trailing: list[str] = []
    while body and not body[-1].strip():
        trailing.insert(0, body.pop())
    lines[start + 1 : end] = body + stamp + trailing
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_one(root: Path, finding: Finding) -> bool:
    if finding.id == "instruction-lint-config":
        _append_block(root, DEFAULT_INSTRUCTIONS_LINT)
        return True
    if finding.id == "heal-config":
        _append_block(root, DEFAULT_HEAL)
        return True
    if finding.id == "instructions-review-config":
        _append_block(root, DEFAULT_INSTRUCTIONS_REVIEW)
        return True
    if finding.id == "agents-max-bytes-10kib":
        _set_agents_max_bytes(root, 10240)
        return True
    if finding.id == "eval-skeleton":
        (root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR).mkdir(
            parents=True, exist_ok=True
        )
        return True
    if finding.id == "codex-window-profile":
        _set_window_profile(root, "400k")
        return True
    if finding.id == "packs-stale":
        return False
    if finding.id == "doctor-codex-env":
        return False
    return False


def apply_auto(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
    version: str | None = None,
) -> list[Finding]:
    root = root.resolve()
    create_backup(root)
    findings = collect_findings(
        root, migrations_text=migrations_text, migrations_path=migrations_path
    )
    applied: list[Finding] = []
    for finding in findings:
        if finding.bucket != "auto" or finding.locked:
            continue
        if _apply_one(root, finding):
            applied.append(finding)
    _touch_last_run(root, version=version)
    if eval_regressed(root):
        restore_backup(root)
        return []
    kbc.append_log(
        operation="heal",
        title="apply auto",
        details=[f"`{item.id}`" for item in applied] or ["(nothing to apply)"],
        root=root,
    )
    return applied


def summarize(findings: list[Finding], applied: list[Finding], stage: int) -> str:
    remaining_a = sum(
        1 for f in findings if f.bucket == "assisted" and not f.locked
    )
    remaining_h = sum(1 for f in findings if f.bucket == "human" and not f.locked)
    locked = sum(1 for f in findings if f.locked)
    tail = f" locked={locked}" if locked else ""
    return (
        f"Heal: applied {len(applied)} auto; remaining assisted={remaining_a} "
        f"human={remaining_h}{tail}; stage={stage} "
        f"({STAGE_NAMES.get(stage, '?')})\n"
        '→ next: скажи агенту "!heal"'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — heal")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--plan", action="store_true", help="write HEAL_PLAN.md")
    parser.add_argument(
        "--apply",
        choices=("auto",),
        default=None,
        help="apply one bucket (only 'auto' is allowed)",
    )
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--verify", action="store_true", help="rollback if eval regressed")
    parser.add_argument("--migrations", type=Path, default=None)
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if yaml is not None and (root / "kb.config.yml").is_file():
        try:
            yaml.safe_load((root / "kb.config.yml").read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(
                f"[ERROR] kb.config.yml is not valid YAML — fix it first:\n{exc}",
                file=sys.stderr,
            )
            return 3
    if args.rollback:
        restored = restore_backup(root)
        print(f"Restored {restored}" if restored else "No backup found")
        return 0 if restored else 1
    if args.verify:
        print(verify(root))
        return 0
    if args.apply == "auto":
        applied = apply_auto(root, migrations_path=args.migrations)
        print(f"Applied {len(applied)} auto fix(es)")
        return 0
    path = write_plan(root, migrations_path=args.migrations)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
