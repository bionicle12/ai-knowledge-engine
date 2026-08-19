"""Structural skill lint (spec §11.1, deterministic Phase 1 checks).

These checks are evidence for the audit, not verdicts: they flag what
can be verified mechanically — frontmatter validity, portable naming,
description bounds, body size, and broken references.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import read_skill_file

DESCRIPTION_MAX_CHARS = 1024
BODY_MAX_CHARS = 12000
PORTABLE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#?\s]+)")

ABSOLUTE_RULE_RE = re.compile(r"\b(always|never|must)\b", re.IGNORECASE)
MODEL_REFERENCE_RE = re.compile(
    r"\bgpt-?[0-9o][\w.-]*\b|\bclaude[- ][0-9][\w.-]*\b"
    r"|\bo[13](?:-mini|-preview)?\b|\bgemini\b|\bllama\b|\bdavinci\b",
    re.IGNORECASE,
)
GENERIC_PROMPTING_PHRASES = (
    "think step by step",
    "step-by-step reasoning",
    "you are an expert",
    "you are a world-class",
    "do not hallucinate",
    "do not make up",
    "take a deep breath",
    "act as an expert",
    "i will tip",
)
MIN_DUPLICATE_PARAGRAPH_CHARS = 80
EXCERPT_MAX_CHARS = 120


@dataclass
class Finding:
    skill: str
    check: str
    severity: str  # error | warning | info
    message: str


@dataclass
class DebtSignal:
    """Deterministic evidence for the agent's prompt-debt classification.

    A signal is a flag with a hint at the §11.2 classes it may indicate.
    Classification and any removal recommendation stay with the agent.
    """

    signal: str
    line: int
    excerpt: str
    hint: str


def _excerpt(text: str) -> str:
    text = text.strip()
    return text[:EXCERPT_MAX_CHARS]


def _normalize_paragraph(paragraph: str) -> str:
    return re.sub(r"\s+", " ", paragraph).strip().lower()


def _paragraphs_with_lines(text: str):
    current: list[str] = []
    start = 1
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            if not current:
                start = lineno
            current.append(line)
        elif current:
            yield start, "\n".join(current)
            current = []
    if current:
        yield start, "\n".join(current)


def debt_signals(text: str) -> list[DebtSignal]:
    signals: list[DebtSignal] = []

    for lineno, line in enumerate(text.split("\n"), start=1):
        if ABSOLUTE_RULE_RE.search(line):
            signals.append(DebtSignal(
                signal="absolute-rule",
                line=lineno,
                excerpt=_excerpt(line),
                hint="conditional-rule or process-overconstraint candidate — "
                     "verify the rule really is unconditional",
            ))
        if MODEL_REFERENCE_RE.search(line):
            signals.append(DebtSignal(
                signal="model-reference",
                line=lineno,
                excerpt=_excerpt(line),
                hint="model-specific content — check against current model "
                     "guidance before keeping",
            ))
        lowered = line.lower()
        if any(phrase in lowered for phrase in GENERIC_PROMPTING_PHRASES):
            signals.append(DebtSignal(
                signal="generic-prompting",
                line=lineno,
                excerpt=_excerpt(line),
                hint="trained-default or relic candidate — current models do "
                     "this without being told",
            ))

    seen: dict[str, int] = {}
    for start, paragraph in _paragraphs_with_lines(text):
        normalized = _normalize_paragraph(paragraph)
        if len(normalized) < MIN_DUPLICATE_PARAGRAPH_CHARS:
            continue
        if normalized in seen:
            signals.append(DebtSignal(
                signal="duplicate-paragraph",
                line=start,
                excerpt=_excerpt(paragraph),
                hint=f"duplicate of the paragraph at line {seen[normalized]}",
            ))
        else:
            seen[normalized] = start

    signals.sort(key=lambda s: (s.line, s.signal))
    return signals


def cross_skill_duplicates(skill_texts: dict[str, str]) -> list[dict]:
    """Find paragraphs shared verbatim between different skills."""
    by_paragraph: dict[str, dict] = {}
    for skill_name, text in sorted(skill_texts.items()):
        for _, paragraph in _paragraphs_with_lines(text):
            normalized = _normalize_paragraph(paragraph)
            if len(normalized) < MIN_DUPLICATE_PARAGRAPH_CHARS:
                continue
            entry = by_paragraph.setdefault(
                normalized, {"skills": set(), "excerpt": _excerpt(paragraph)}
            )
            entry["skills"].add(skill_name)

    shared = [
        {"skills": sorted(entry["skills"]), "excerpt": entry["excerpt"],
         "count": len(entry["skills"])}
        for entry in by_paragraph.values()
        if len(entry["skills"]) > 1
    ]
    shared.sort(key=lambda e: (-e["count"], e["excerpt"]))
    return shared


def lint_skill_dir(path: Path) -> list[Finding]:
    path = Path(path)
    skill = path.name
    findings: list[Finding] = []

    doc = read_skill_file(path / "SKILL.md")
    if doc.error is not None:
        findings.append(
            Finding(skill, "frontmatter", "error", f"frontmatter problem: {doc.error}")
        )
        return findings

    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        findings.append(Finding(skill, "name-missing", "error", "no name in frontmatter"))
    else:
        if not PORTABLE_NAME_RE.match(name):
            findings.append(
                Finding(
                    skill,
                    "portable-name",
                    "warning",
                    f"name {name!r} is not lowercase-hyphen portable",
                )
            )
        if name != path.name:
            findings.append(
                Finding(
                    skill,
                    "name-folder-mismatch",
                    "warning",
                    f"frontmatter name {name!r} differs from folder {path.name!r}",
                )
            )

    description = doc.frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append(
            Finding(skill, "description-missing", "error", "no description in frontmatter")
        )
    elif len(description) > DESCRIPTION_MAX_CHARS:
        findings.append(
            Finding(
                skill,
                "description-length",
                "warning",
                f"description is {len(description)} chars; hosts may truncate "
                f"beyond {DESCRIPTION_MAX_CHARS}",
            )
        )

    if len(doc.body) > BODY_MAX_CHARS:
        findings.append(
            Finding(
                skill,
                "body-length",
                "warning",
                f"SKILL.md body is {len(doc.body)} chars; consider progressive "
                "disclosure into references/",
            )
        )

    for target in MD_LINK_RE.findall(doc.body):
        if "://" in target or target.startswith(("mailto:", "/", "~")):
            continue
        if not (path / target).exists():
            findings.append(
                Finding(
                    skill,
                    "broken-reference",
                    "error",
                    f"referenced file {target!r} does not exist",
                )
            )

    return findings
