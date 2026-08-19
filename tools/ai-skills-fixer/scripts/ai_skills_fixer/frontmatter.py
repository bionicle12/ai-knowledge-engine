"""Tolerant SKILL.md frontmatter parsing.

Accepts `---`-delimited YAML frontmatter in UTF-8 with optional BOM and
LF or CRLF endings. Parse failures are reported as error codes, never
exceptions, so inventory can record broken skills instead of crashing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DELIMITER = "---"


@dataclass
class SkillDoc:
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    error: str | None = None


def parse_skill_text(text: str) -> SkillDoc:
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = text.split("\n")
    if not lines or lines[0].strip() != DELIMITER:
        return SkillDoc(body=text, error="missing-frontmatter")

    for idx in range(1, len(lines)):
        if lines[idx].strip() == DELIMITER:
            closing = idx
            break
    else:
        return SkillDoc(body=text, error="unterminated-frontmatter")

    raw_yaml = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1 :])
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return SkillDoc(body=body, error="invalid-yaml")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return SkillDoc(body=body, error="not-a-mapping")
    return SkillDoc(frontmatter=data, body=body)


def read_skill_file(path: Path) -> SkillDoc:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return SkillDoc(error="unreadable")
    return parse_skill_text(raw.decode("utf-8", errors="replace"))
