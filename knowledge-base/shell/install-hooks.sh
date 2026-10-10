#!/usr/bin/env bash
# install-hooks.sh — install the Full-mode git post-commit hook
# (shell/hooks/post-commit; see kb-docs/13_AUTORUN.md). Safe to re-run.
#
# Usage:
#   bash shell/install-hooks.sh
#
# - The hooks folder comes from `git rev-parse --git-path hooks`, so linked
#   worktrees and core.hooksPath work. A core.hooksPath (husky, lefthook, ...)
#   gets a warning: the tool that owns that folder may overwrite the hook.
# - An existing post-commit hook that differs from shell/hooks/post-commit (a
#   foreign hook, an older copy of ours, or one edited by hand) is moved to
#   post-commit.backup-<timestamp> first (never deleted) and reported. To keep
#   own post-commit commands, keep your own hook and call shell/hooks/post-commit
#   from it instead of running this script.
# - When the base sits below the top of the work tree, its path is recorded in
#   `git config kb.root` so the hook finds it; the hook falls back to the top
#   of the work tree when that path is gone (e.g. after finalize.sh).
#
# Exit codes: 0 installed or already current; 1 no git / not a work tree /
# cannot write the hook; 2 base files missing.
#
# Plain POSIX sh on purpose: `sh shell/install-hooks.sh` works as well.

KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2

SRC="$KB_SHELL_DIR/hooks/post-commit"
MARKER="ai-knowledge-engine post-commit hook"

if [ ! -f "$SRC" ]; then
  echo "❌ $SRC not found" >&2
  exit 2
fi
if ! command -v git >/dev/null 2>&1; then
  echo "❌ git not found on PATH" >&2
  exit 1
fi
if ! prefix=$(git -C "$KB_ROOT" rev-parse --show-prefix 2>/dev/null); then
  echo "❌ $KB_ROOT is not inside a git work tree — run \`git init\` first." >&2
  exit 1
fi
hooks=$(git -C "$KB_ROOT" rev-parse --git-path hooks) || exit 1
case $hooks in
  /*|[A-Za-z]:*) ;;
  *) hooks="$KB_ROOT/$hooks" ;;   # relative to the -C folder
esac

hooks_path=$(git -C "$KB_ROOT" config --get core.hooksPath 2>/dev/null || true)
if [ -n "$hooks_path" ]; then
  echo "⚠️  core.hooksPath is set ($hooks_path); installing into $hooks."
  echo "   If a tool manages that folder (husky, lefthook, ...), it may overwrite"
  echo "   or bypass this hook — then call shell/hooks/post-commit from its own hook."
fi

mkdir -p "$hooks" || exit 1
dst="$hooks/post-commit"
if [ -f "$dst" ] && cmp -s "$SRC" "$dst"; then
  echo "✅ post-commit hook already installed: $dst"
else
  if [ -e "$dst" ]; then
    backup="$dst.backup-$(date +%Y%m%d-%H%M%S)"
    if [ -e "$backup" ]; then
      backup="$backup-$$"
    fi
    mv "$dst" "$backup" || exit 1
    if grep -q "$MARKER" "$backup" 2>/dev/null; then
      echo "📦 the installed hook differed from shell/hooks/post-commit (an older"
      echo "   version or local edits); the previous copy is kept as $backup"
    else
      echo "📦 moved the existing post-commit hook to $backup"
      echo "   Its commands no longer run. To keep them, restore it and call"
      echo "   shell/hooks/post-commit from it instead."
    fi
  fi
  cp "$SRC" "$dst" || exit 1
  chmod +x "$dst" 2>/dev/null || true
  echo "✅ installed post-commit hook: $dst"
fi

# Let the hook find a base that is not the top of the work tree.
if [ -n "$prefix" ]; then
  git -C "$KB_ROOT" config kb.root "${prefix%/}" || exit 1
  echo "   base folder recorded: git config kb.root = ${prefix%/}"
elif [ -n "$(git -C "$KB_ROOT" config --get kb.root 2>/dev/null)" ]; then
  git -C "$KB_ROOT" config --unset kb.root || true
fi

echo "   Each commit now refreshes the index packs and STATUS.md in the background"
echo "   (scripts/kb_reindex.py --hook); output: .kb-state/hooks.log"
