# Host: Codex (`codex`)

## Skill locations

- User: `~/.codex/skills/<skill>/SKILL.md` (override the home with
  `CODEX_HOME`; skills live in `<home>/skills`).
- System-bundled: `~/.codex/skills/.system/<skill>/` — owned by the
  client, inventoried as `system`, never modified by this tool.

## Capabilities

- Symlinked skill directories work; symlink is the preferred managed
  strategy.
- No documented per-skill disabled state: `occasional` falls back to
  catalog-only.

## Usage telemetry (advisory)

`~/.codex/sessions/` and `~/.codex/archived_sessions/` may contain
session logs referencing skill paths. Offline parsing only; aggregate
counts, no prompt content in reports.
