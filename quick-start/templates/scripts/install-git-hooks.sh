#!/bin/sh
# Copies hooks from .githooks/ into .git/hooks/.
# Deliberately avoids `git config core.hooksPath`: copying keeps any other
# locally installed hooks working and needs no git-config changes.
# Works on Linux, macOS, and Windows Git Bash (git runs .sh hooks through
# its bundled sh.exe on Windows).
set -u

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SRC="$ROOT/.githooks"
DST="$ROOT/.git/hooks"

if [ ! -d "$DST" ]; then
    printf '%s\n' "Not found: $DST — is this a git repository?"
    exit 1
fi

if [ ! -d "$SRC" ]; then
    printf '%s\n' "Not found: $SRC"
    exit 1
fi

installed=
for name in post-commit pre-push post-merge post-rewrite; do
    if [ ! -f "$SRC/$name" ]; then
        printf '%s\n' "Skip: no $SRC/$name"
        continue
    fi
    if [ -f "$DST/$name" ] && ! grep -q "update-repomix-index" "$DST/$name"; then
        cp "$DST/$name" "$DST/$name.pre-repomix.bak"
        printf '%s\n' "Note: existing $name hook backed up as $name.pre-repomix.bak — merge manually if it did something else."
    fi
    cp "$SRC/$name" "$DST/$name"
    chmod +x "$DST/$name" "$SRC/$name"
    installed="$installed $name"
done

printf '%s\n' "Git hooks installed:$installed"
printf '%s\n' "Events: commit (background), push (synchronous), pull/merge/rebase (background)."
