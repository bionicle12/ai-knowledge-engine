#!/bin/sh
# pre-commit-translation-drift — git pre-commit hook for ai-knowledge-engine.
#
# Warns (does NOT block) when a canonical EN source is staged without its
# i18n/<lang>/ translation, or deleted (or renamed) while a translation of it
# is left behind. Canonical sources are the set
# scripts/check_translations.py tracks (CANONICAL_GLOBS / NON_DOC_DIRS):
# README.md, knowledge-base/**/*.md and quick-start/**/*.md, except files in
# scripts/, templates/, tests/, vendor/ and dot-folders.
#
# Install (from the repo root; works in linked worktrees too):
#   chmod +x scripts/hooks/pre-commit-translation-drift.sh
#   ln -sf "$(pwd)/scripts/hooks/pre-commit-translation-drift.sh" "$(git rev-parse --git-path hooks)/pre-commit"
#
# Or copy:
#   cp scripts/hooks/pre-commit-translation-drift.sh "$(git rev-parse --git-path hooks)/pre-commit"
#   chmod +x "$(git rev-parse --git-path hooks)/pre-commit"

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

[ -d i18n ] || exit 0

# core.quotePath=false: non-ASCII paths come out verbatim, not "\320\237…";
# --no-renames: a renamed source shows up as its old path (D) + new path (A).
STAGED=$(git -c core.quotePath=false diff --cached --name-only --no-renames --diff-filter=ACMD)
DELETED=$(git -c core.quotePath=false diff --cached --name-only --no-renames --diff-filter=D)

# Canonical files staged for commit (paths may contain spaces or '%')
CANONICAL_CHANGED=$(printf '%s\n' "$STAGED" \
  | grep -E '^(README\.md|(knowledge-base|quick-start)/.+\.md)$' \
  | grep -Ev '(^|/)(scripts|templates|tests|vendor|\.[^/]*)/' || true)

[ -n "$CANONICAL_CHANGED" ] || exit 0

NL='
'
DRIFT_REPORT=""
ORPHAN_REPORT=""
while IFS= read -r f; do
  for lang_dir in i18n/*/; do
    [ -d "$lang_dir" ] || continue
    translation="${lang_dir}${f}"
    [ -f "$translation" ] || continue
    # Is the translation staged too?
    printf '%s\n' "$STAGED" | grep -qxF -- "$translation" && continue
    if printf '%s\n' "$DELETED" | grep -qxF -- "$f"; then
      ORPHAN_REPORT="${ORPHAN_REPORT}  - $translation (its source $f is deleted or renamed)${NL}"
    else
      DRIFT_REPORT="${DRIFT_REPORT}  - $translation (will be stale relative to $f)${NL}"
    fi
  done
done <<EOF
$CANONICAL_CHANGED
EOF

if [ -n "$DRIFT_REPORT" ]; then
  printf '\n⚠️  Translation drift detected\n'
  printf 'You modified canonical files but did not update their translations:\n'
  printf '%s' "$DRIFT_REPORT"
  printf '\nThis is a warning, not a block. Translations will be marked stale by\n'
  printf 'scripts/check_translations.py until updated.\n\n'
  printf 'After this commit, once a translation matches, stamp only the files you\n'
  printf 'updated (a run without --files would hide the drift of the others), then\n'
  printf 'refresh the report:\n'
  printf '  python3 scripts/sync_translations.py --to-source --files <the translations you updated>\n'
  printf '  python3 scripts/check_translations.py --update-status\n\n'
fi

if [ -n "$ORPHAN_REPORT" ]; then
  printf '\n⚠️  Translations left without their source\n'
  printf '%s' "$ORPHAN_REPORT"
  printf '\nMove each one next to the renamed source (and fix translation_of:), or\n'
  printf 'delete it. scripts/check_translations.py reports it as an orphan until then.\n\n'
fi

exit 0
