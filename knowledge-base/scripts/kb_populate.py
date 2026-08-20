#!/usr/bin/env python3
"""kb_populate — generate DATA_PLACEMENT_EXAMPLES.md from a role template.

Pure templating: reads `placement_examples` from a role YAML and emits a
formatted Markdown file at the deployed KB root. No LLM calls, no tokens —
deterministic and reproducible across agents.

Workflow integration:
    1. Agent picks a role (from examples/) or asks user to describe one
    2. For custom roles, agent creates examples/<role>.yml (see templates/role.yml.template)
    3. Run kb_populate.py to generate DATA_PLACEMENT_EXAMPLES.md
    4. (Optional) Agent reviews the result and adds project-specific notes

Usage:
    python3 scripts/kb_populate.py --role programmer-senior
    python3 scripts/kb_populate.py --role custom --from path/to/role.yml
    python3 scripts/kb_populate.py --kb-root /path/to/deployed-kb
    python3 scripts/kb_populate.py --output FILENAME
    python3 scripts/kb_populate.py --create-samples       # also drop raw/_samples/
    python3 scripts/kb_populate.py --dry-run              # print to stdout
    python3 scripts/kb_populate.py --json                 # machine-readable

Exit codes:
    0 — generated successfully (or dry-run printed)
    1 — role file not found / invalid YAML / missing placement_examples
    2 — KB root invalid
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Examples directory resolution:
# - When deployed to a KB root, examples/ is sibling of scripts/ (i.e. REPO_ROOT/examples)
# - When run from the source repo, examples/ is at knowledge-base/examples/
# We try both; the first existing one wins.
_DEFAULT_EXAMPLES = REPO_ROOT / "examples"
_LEGACY_EXAMPLES = REPO_ROOT / "knowledge-base" / "examples"
EXAMPLES_DIR = _DEFAULT_EXAMPLES if _DEFAULT_EXAMPLES.is_dir() else _LEGACY_EXAMPLES
DEFAULT_OUTPUT = "DATA_PLACEMENT_EXAMPLES.md"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_role_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise SystemExit("PyYAML is required. Install: pip install pyyaml") from e
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def resolve_role_path(role: str | None, from_path: Path | None) -> Path:
    if from_path:
        return from_path.resolve()
    if not role:
        raise ValueError("Either --role or --from must be provided")
    candidate = EXAMPLES_DIR / f"{role}.yml"
    if candidate.is_file():
        return candidate
    candidate_yaml = EXAMPLES_DIR / f"{role}.yaml"
    if candidate_yaml.is_file():
        return candidate_yaml
    raise FileNotFoundError(
        f"Role '{role}' not found in {EXAMPLES_DIR}. "
        f"Use --from to point at a custom YAML."
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

GENERIC_TABLE = """\
| You have | Put it in |
|----------|-----------|
| A PDF/DOCX strategy doc, report, presentation | `raw/documents/unsorted/` |
| An interesting article saved from the web | `raw/reference/unsorted/` |
| An exported chat (Telegram, Slack, Discord) | `raw/chats/unsorted/` |
| Audio/video recording (meeting, voice memo) | `raw/media/unsorted/` |
| Random notes, screenshots, drafts | `raw/unsorted/` |
| Personal context (history, preferences) | `raw/personal-context/unsorted/` |
"""


CHAT_UPLOAD_RULES = """\
## Adding files through chat

If you attach a file directly in chat, the AI agent must ask before adding it to the main knowledge base:

1. Summarize the attached file(s) and propose the best `raw/<category>/unsorted/` destination
2. Ask: "Add this to the main knowledge base?"
3. Only after confirmation, stage the file into `raw/` and run `./shell/reindex.sh` or confirm the watcher processed it
4. If the file looks low-value or unrelated, ask whether to keep it as an asset, archive it, or ignore it
"""


def _safe(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


def render_markdown(role_data: dict[str, Any], *, source_path: Path) -> str:
    role = _safe(role_data.get("role")) or "Unknown role"
    pe = role_data.get("placement_examples") or {}
    if not isinstance(pe, dict):
        raise ValueError(
            f"{source_path}: 'placement_examples' must be a mapping (got {type(pe).__name__})"
        )

    intro = _safe(pe.get("intro"))
    by_artifact = pe.get("by_artifact") or []
    quickstart = pe.get("quickstart") or []
    do_not_drop = pe.get("do_not_drop") or []

    today = _dt.date.today().isoformat()
    lines: list[str] = []
    lines.append(f"# Data Placement Examples — {role}")
    lines.append("")
    lines.append(
        f"> Generated by `kb_populate.py` on {today} from "
        f"`{source_path.relative_to(REPO_ROOT) if source_path.is_relative_to(REPO_ROOT) else source_path}`."
    )
    lines.append("> Re-run after editing the source YAML to refresh.")
    lines.append("")

    if intro:
        lines.append("## Why this file")
        lines.append("")
        lines.append(intro.strip())
        lines.append("")

    # Generic mapping
    lines.append("## You have → put it in (generic)")
    lines.append("")
    lines.append(GENERIC_TABLE)
    lines.append("")
    lines.append(CHAT_UPLOAD_RULES)
    lines.append("")

    # Role-specific summary table
    if by_artifact:
        lines.append("## Role-specific quick map")
        lines.append("")
        lines.append("| Artifact | Destination | Knowledge target |")
        lines.append("|----------|-------------|------------------|")
        for entry in by_artifact:
            if not isinstance(entry, dict):
                continue
            artifact = _safe(entry.get("artifact"))
            destination = _safe(entry.get("destination"))
            target = _safe(entry.get("knowledge_target")) or "—"
            lines.append(
                f"| {artifact} | `{destination}` | "
                f"{f'`{target}`' if target != '—' else '—'} |"
            )
        lines.append("")

        # Detailed sections
        lines.append("## Role-specific examples")
        lines.append("")
        for entry in by_artifact:
            if not isinstance(entry, dict):
                continue
            artifact = _safe(entry.get("artifact"))
            destination = _safe(entry.get("destination"))
            examples = entry.get("examples") or []
            tip = _safe(entry.get("tip"))
            target = _safe(entry.get("knowledge_target"))

            lines.append(f"### {artifact}")
            lines.append("")
            lines.append(f"**Drop into:** `{destination}`")
            if examples:
                lines.append("")
                lines.append("Examples:")
                for ex in examples:
                    lines.append(f"- `{_safe(ex)}`")
            if target:
                lines.append("")
                lines.append(f"→ Will be extracted to `{target}`")
            if tip:
                lines.append("")
                lines.append(f"> 💡 {tip}")
            lines.append("")

    if quickstart:
        lines.append("## 5-minute quickstart")
        lines.append("")
        for i, step in enumerate(quickstart, start=1):
            lines.append(f"{i}. {_safe(step)}")
        lines.append("")

    if do_not_drop:
        lines.append("## Do NOT drop")
        lines.append("")
        for item in do_not_drop:
            lines.append(f"- {_safe(item)}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("## Next steps")
    lines.append("")
    lines.append("1. Drop a few files into the matching `raw/*/unsorted/` folder")
    lines.append("2. Run `./shell/reindex.sh` (or start `./shell/watcher.sh` for auto-processing)")
    lines.append("3. Check `log.md` to see what happened")
    lines.append("4. Open `.repomix/output.xml` once the AI has indexed your knowledge")
    lines.append("")
    lines.append(
        "If something feels off, edit the source YAML and re-run "
        "`python3 scripts/kb_populate.py --role <role>`."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sample-file generation
# ---------------------------------------------------------------------------


SAMPLE_TEMPLATE = """\
<!--
This is a FORMAT EXAMPLE. Files in raw/_samples/ are NOT picked up by the
ingest pipeline. Copy this file into a real raw/<sub>/unsorted/ folder,
rename it to a meaningful name, fill it in, and the pipeline will process it.

Generated for artifact: {artifact}
Suggested destination: {destination}
Knowledge target: {knowledge_target}
-->

# {artifact} — example

(Replace this with your actual content.)

## Context
What prompted this artifact?

## Body
The actual content.

## Notes / open questions
What you are still unsure about.
"""


def write_samples(kb_root: Path, role_data: dict[str, Any]) -> list[Path]:
    pe = role_data.get("placement_examples") or {}
    by_artifact = pe.get("by_artifact") or []
    samples_dir = kb_root / "raw" / "_samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for entry in by_artifact:
        if not isinstance(entry, dict):
            continue
        artifact = _safe(entry.get("artifact"))
        destination = _safe(entry.get("destination")) or "raw/<sub>/unsorted/"
        target = _safe(entry.get("knowledge_target")) or "knowledge/<category>/"
        if not artifact:
            continue
        # Use a slug-like filename
        try:
            from slugify import slugify  # type: ignore[import-untyped]
            slug = slugify(artifact)
        except ImportError:
            slug = artifact.lower().replace(" ", "-").replace("/", "-")
        out = samples_dir / f"{slug}.example.md"
        out.write_text(
            SAMPLE_TEMPLATE.format(
                artifact=artifact,
                destination=destination,
                knowledge_target=target,
            ),
            encoding="utf-8",
        )
        written.append(out)
    # Add README to _samples/
    readme = samples_dir / "README.md"
    readme.write_text(
        "# raw/_samples/ — format examples\n\n"
        "These files are NOT picked up by the ingest pipeline (the folder name "
        "starts with `_`). Copy any of them into the matching `raw/<sub>/unsorted/` "
        "folder to use as a starting template.\n",
        encoding="utf-8",
    )
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate DATA_PLACEMENT_EXAMPLES.md from a role template"
    )
    parser.add_argument("--role", help="Role name (matches examples/<role>.yml)")
    parser.add_argument("--from", dest="from_path", type=Path,
                        help="Path to a custom role YAML")
    parser.add_argument("--kb-root", type=Path,
                        help="Deployed KB root (defaults to current dir)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output filename (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--create-samples", action="store_true",
                        help="Also create raw/_samples/ with placeholder files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print result to stdout without writing")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable summary")
    args = parser.parse_args(argv)

    if not args.role and not args.from_path:
        parser.error("Either --role or --from must be specified")
        return 1

    try:
        role_path = resolve_role_path(args.role, args.from_path)
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    try:
        role_data = load_role_yaml(role_path)
    except (ValueError, Exception) as e:
        print(f"❌ Failed to load {role_path}: {e}", file=sys.stderr)
        return 1

    if role_data.get("easter_egg"):
        # This role never deploys anything. That's the whole joke.
        responses = role_data.get("easter_egg_response") or {}
        text = "\n\n".join(
            str(responses[lang]).strip()
            for lang in ("ru", "en")
            if responses.get(lang)
        ) or "Nice try. Pick another role. 😏"
        if args.json:
            print(json.dumps({"easter_egg": True, "response": text},
                             ensure_ascii=False))
        else:
            print(text)
        return 0

    if not role_data.get("placement_examples"):
        print(
            f"❌ {role_path}: missing 'placement_examples' section",
            file=sys.stderr,
        )
        print(
            "   See knowledge-base/examples/programmer-senior.yml for the schema.",
            file=sys.stderr,
        )
        return 1

    try:
        markdown = render_markdown(role_data, source_path=role_path)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    kb_root = (args.kb_root or Path.cwd()).resolve()
    output_path = kb_root / args.output

    samples_written: list[Path] = []
    if args.create_samples and not args.dry_run:
        if not kb_root.is_dir():
            print(f"❌ KB root not found: {kb_root}", file=sys.stderr)
            return 2
        samples_written = write_samples(kb_root, role_data)

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "role_source": str(role_path),
                "would_write": str(output_path),
                "markdown_length": len(markdown),
            }, indent=2))
        else:
            print(markdown)
        return 0

    if not kb_root.is_dir():
        print(f"❌ KB root not found: {kb_root}", file=sys.stderr)
        return 2

    output_path.write_text(markdown, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "role_source": str(role_path),
            "written": str(output_path),
            "markdown_length": len(markdown),
            "samples_created": [str(p) for p in samples_written],
        }, indent=2))
    else:
        print(f"✅ Wrote {output_path.relative_to(kb_root) if output_path.is_relative_to(kb_root) else output_path}")
        if samples_written:
            print(f"📂 Created {len(samples_written)} sample file(s) in raw/_samples/")
        print("")
        print("Next: ask the AI agent to review the file and add any project-")
        print("specific notes that aren't capturable in YAML.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
