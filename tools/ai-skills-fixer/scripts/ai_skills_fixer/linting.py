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


@dataclass
class Finding:
    skill: str
    check: str
    severity: str  # error | warning | info
    message: str


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
