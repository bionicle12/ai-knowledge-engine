#!/bin/sh
# pre-commit-translation-drift — git pre-commit hook for ai-knowledge-engine.
#
# Warns (does NOT block) when canonical knowledge-base/*.md files were edited
# without a corresponding update to i18n/<lang>/ translations.
#
# Install:
#   ln -sf ../../scripts/hooks/pre-commit-translation-drift.sh .git/hooks/pre-commit
#   chmod +x scripts/hooks/pre-commit-translation-drift.sh
#
# Or copy:
#   cp scripts/hooks/pre-commit-translation-drift.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Find canonical files staged for commit
CANONICAL_CHANGED=$(git diff --cached --name-only | grep -E '^(knowledge-base|quick-start)/.*\.md$' || true)

if [ -z "$CANONICAL_CHANGED" ]; then
  exit 0
fi

# Languages present in i18n/
if [ ! -d "i18n" ]; then
  exit 0
fi

LANGS=$(find i18n -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null || true)

if [ -z "$LANGS" ]; then
  exit 0
fi

DRIFT_REPORT=""
for f in $CANONICAL_CHANGED; do
  for lang in $LANGS; do
    translation="i18n/$lang/$f"
    if [ -f "$translation" ]; then
      # Check if the translation is also staged
      if ! git diff --cached --name-only | grep -qx "$translation"; then
        DRIFT_REPORT="$DRIFT_REPORT  - $translation (will be stale relative to $f)\n"
      fi
    fi
  done
done

if [ -n "$DRIFT_REPORT" ]; then
  printf '\n⚠️  Translation drift detected\n'
  printf 'You modified canonical files but did not update their translations:\n'
  printf "$DRIFT_REPORT"
  printf '\nThis is a warning, not a block. Translations will be marked stale by\n'
  printf 'scripts/check_translations.py until updated.\n\n'
  printf 'To update i18n/TRANSLATION_STATUS.md after committing:\n'
  printf '  python3 scripts/check_translations.py --update-status\n\n'
fi

exit 0
