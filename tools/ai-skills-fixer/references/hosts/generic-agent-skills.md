# Generic agent-skill conventions

A skill is a directory whose root contains a readable `SKILL.md` with
`---`-delimited YAML frontmatter. Portable core:

- `name`: lowercase-hyphen, matches the folder name;
- `description`: one paragraph saying what the skill does AND when to
  use it — this is the only text most hosts load at startup, so
  trigger phrasing lives here;
- body: workflow instructions; anything long or host-specific moves to
  `references/` files linked relatively (progressive disclosure);
- `scripts/` for deterministic repeated work; scripts declare their
  prerequisites and use relative paths.

Portability rules for audits:

- host-specific fields and paths stay out of the portable core;
- referenced files must exist (a broken link is a lint error);
- treat every third-party skill as executable supply-chain content:
  never run bundled scripts during a static audit.
