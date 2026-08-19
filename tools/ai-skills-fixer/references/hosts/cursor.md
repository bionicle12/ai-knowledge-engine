# Host: Cursor (`cursor`)

## Skill locations

- User: `~/.cursor/skills/<skill>/SKILL.md`.
- System-bundled: `~/.cursor/skills-cursor/` — owned by the client,
  inventoried as `system`, never modified by this tool.

## Capabilities

- Symlinked skill directories work; symlink is the preferred managed
  strategy.
- No documented per-skill disabled state: `occasional` falls back to
  catalog-only.

## Usage telemetry (advisory)

No documented uniform skill-invocation log. Treat usage as
`not-observed` rather than unused; ask the user (`manual` evidence).
