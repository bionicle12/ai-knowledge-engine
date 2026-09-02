"""Cross-platform host skill-root discovery (spec §8).

Every candidate location is reported with evidence and confidence, and
absent locations stay in the result marked ``exists=False`` — discovery
never invents paths and never searches outside bounded roots. Env
overrides replace the default candidate for their host.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass
class SkillRoot:
    host: str
    path: Path
    kind: str  # user | project | plugin | system
    exists: bool
    evidence: str
    confidence: str  # high | medium | low


def _root(host: str, path: Path, kind: str, evidence: str | None = None) -> SkillRoot:
    exists = path.is_dir()
    if evidence is None:
        evidence = "default-location-exists" if exists else "default-location-missing"
    confidence = "high" if exists else "low"
    return SkillRoot(
        host=host,
        path=path,
        kind=kind,
        exists=exists,
        evidence=evidence,
        confidence=confidence,
    )


def discover_roots(
    home: Path | None = None,
    project_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[SkillRoot]:
    home = Path(home) if home is not None else Path.home()
    env = os.environ if env is None else env
    roots: list[SkillRoot] = []

    claude_config = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    claude_evidence = "env-override" if env.get("CLAUDE_CONFIG_DIR") else None
    roots.append(_root("claude", claude_config / "skills", "user", claude_evidence))
    roots.append(_root("claude", claude_config / "plugins" / "cache", "plugin"))
    if project_dir is not None:
        roots.append(
            _root(
                "claude",
                Path(project_dir) / ".claude" / "skills",
                "project",
                "project-local",
            )
        )

    codex_home = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else home / ".codex"
    codex_evidence = "env-override" if env.get("CODEX_HOME") else None
    roots.append(_root("codex", codex_home / "skills", "user", codex_evidence))

    roots.append(_root("cursor", home / ".cursor" / "skills", "user"))
    roots.append(_root("cursor", home / ".cursor" / "skills-cursor", "system"))

    roots.append(_root("antigravity", home / ".antigravity" / "skills", "user"))
    gemini_config = (
        Path(env["GEMINI_CONFIG_DIR"])
        if env.get("GEMINI_CONFIG_DIR")
        else home / ".gemini" / "config"
    )
    roots.append(_root("antigravity", gemini_config / "plugins", "plugin"))

    return sorted(roots, key=lambda r: (r.host, r.kind, str(r.path)))
