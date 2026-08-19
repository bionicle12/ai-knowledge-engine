# Host: Claude Code (`claude`)

## Skill locations

- User: `~/.claude/skills/<skill>/SKILL.md` (override the config dir
  with `CLAUDE_CONFIG_DIR`; skills live in `<config>/skills`).
- Project: `<project>/.claude/skills/`.
- Plugins: `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/`
  — plugin-managed; change only via the plugin/marketplace mechanism,
  never by editing files.

## Capabilities

- Symlinked skill directories are followed; symlink is the preferred
  managed-install strategy on POSIX.
- No documented per-skill disabled state in the user directory: for
  `occasional` skills fall back to catalog-only.
- Discovery loads frontmatter `name` and `description` at startup;
  long descriptions may be truncated in listings.

## Usage telemetry (advisory)

Session transcripts under `~/.claude/projects/<project-slug>/` may show
skill invocations (`Skill` tool calls). Parse offline, aggregate
counts only, never quote user prompts into reports.
