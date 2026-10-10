#!/bin/sh
# Copies hooks from .githooks/ into the folder git actually runs hooks from:
# `git rev-parse --git-path hooks` (.git/hooks, or the shared hooks folder of
# the main checkout when run from a linked worktree).
# Deliberately avoids setting `core.hooksPath`: copying keeps any other
# locally installed hooks working and needs no git-config changes. When
# core.hooksPath is already set (husky, lefthook, ...), git ignores .git/hooks
# and that folder belongs to the hook manager — nothing is copied; the script
# prints the lines to add to the manager's hooks instead.
# A hook that differs from the new copy is backed up and the diff is shown, so
# a project-specific hook (e.g. a CI gate in pre-push) is never lost silently.
# Works on Linux, macOS, and Windows Git Bash (git runs .sh hooks through
# its bundled sh.exe on Windows).
set -u

HOOKS="post-commit pre-push post-merge post-rewrite post-checkout"

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd) || exit 1
SRC="$ROOT/.githooks"
cd "$ROOT" || exit 1

if [ ! -d "$SRC" ]; then
    printf '%s\n' "Not found: $SRC"
    exit 1
fi

DST=$(git rev-parse --git-path hooks 2>/dev/null) || DST=
if [ -z "$DST" ]; then
    printf '%s\n' "Not a git repository: $ROOT — hooks not installed." \
        "Rebuild the index manually with scripts/update-repomix-index.sh."
    exit 1
fi
case "$DST" in
    /*|[A-Za-z]:*) ;;
    *) DST="$ROOT/$DST" ;;
esac

HOOKS_PATH=$(git config --get core.hooksPath 2>/dev/null) || HOOKS_PATH=
if [ -n "$HOOKS_PATH" ]; then
    if [ "$(CDPATH= cd -- "$DST" 2>/dev/null && pwd -P)" = "$(CDPATH= cd -- "$SRC" && pwd -P)" ]; then
        # core.hooksPath=.githooks: git runs the committed hooks directly.
        for name in $HOOKS; do
            [ -f "$SRC/$name" ] && chmod +x "$SRC/$name"
        done
        printf '%s\n' "core.hooksPath points at .githooks: git runs these hooks directly, nothing to copy."
        exit 0
    fi
    printf '%s\n' \
        "Not installed: core.hooksPath is set to '$HOOKS_PATH', so git runs hooks from" \
        "  $DST" \
        "and ignores .git/hooks. That folder belongs to your hook manager (husky," \
        "lefthook, ...); copying files there would replace its hooks. Add these lines" \
        "to the manager's hooks instead:" \
        "  post-commit, post-merge, post-rewrite:  sh scripts/update-repomix-index.sh --background" \
        "  post-checkout:  [ \"\$3\" = 1 ] && sh scripts/update-repomix-index.sh --background" \
        "  pre-push:  sh scripts/update-repomix-index.sh --no-wait </dev/null" \
        "Or unset core.hooksPath (git config --unset core.hooksPath) and re-run this script."
    exit 1
fi
mkdir -p "$DST"

installed=
unchanged=
for name in $HOOKS; do
    if [ ! -f "$SRC/$name" ]; then
        printf '%s\n' "Skip: no $SRC/$name"
        continue
    fi
    chmod +x "$SRC/$name"
    if [ -f "$DST/$name" ]; then
        if cmp -s "$SRC/$name" "$DST/$name"; then
            chmod +x "$DST/$name"
            unchanged="$unchanged $name"
            continue
        fi
        backup="$DST/$name.bak-$(date +%Y%m%d-%H%M%S)"
        cp "$DST/$name" "$backup"
        printf '%s\n' "Note: replacing the existing $name hook; old copy: $backup"
        if command -v diff >/dev/null 2>&1; then
            printf '%s\n' "  Changes (- old, + new):"
            diff -u "$backup" "$SRC/$name" | sed -e '1,2d' -e 's/^/    /'
        fi
        printf '%s\n' "  If the old hook did something project-specific, move that part into" \
            "  .githooks/$name.local (executable): the new hook runs it, and template" \
            "  refreshes never touch it."
    fi
    cp "$SRC/$name" "$DST/$name"
    chmod +x "$DST/$name"
    installed="$installed $name"
done

printf '%s\n' "Git hooks installed into $DST:${installed:- (none)}"
[ -n "$unchanged" ] && printf '%s\n' "Already up to date:$unchanged"
printf '%s\n' "Events: commit, pull/merge, rebase/amend, branch checkout (background); push (synchronous, never waits for a running build)."
exit 0
