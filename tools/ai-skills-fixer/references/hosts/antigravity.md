# Host: Antigravity (`antigravity`)

## Skill locations

- User (scanned, reconcile target): `~/.antigravity/skills/<skill>/SKILL.md`.
- Plugins (scanned, never planned): `<gemini-config>/plugins/<plugin>/skills/<skill>/SKILL.md`,
  where `<gemini-config>` is `$GEMINI_CONFIG_DIR` (evidence `env-override`)
  or `~/.gemini/config`.
- Not scanned: `~/.gemini/config/skills/`. If skills live there, report
  them to the user as unmanaged; the tool will not see or plan them.
- Gemini CLI is not a separate host: `GEMINI_CONFIG_DIR` only moves the
  Antigravity plugin root above, and no Gemini CLI skill location is
  discovered (spec §22 Phase 6: adapters only for clients in real use).

## Capabilities

- Symlinked skill directories work; symlink is the preferred managed
  strategy.
- No documented per-skill disabled state: `occasional` falls back to
  catalog-only.

## Usage telemetry (advisory)

No documented uniform skill-invocation log. Treat usage as
`not-observed` rather than unused; ask the user (`manual` evidence).

