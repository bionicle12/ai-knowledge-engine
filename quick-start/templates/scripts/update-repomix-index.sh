#!/bin/sh
# Rebuilds the local Repomix AI index (.repomix/*.xml).
#
# Design constraints (learned from production incidents):
#   - Git hooks and IDEs often run with PATH=/usr/bin:/bin (no nvm) -> we
#     bootstrap PATH ourselves and fall back to `npx --yes repomix`.
#   - Git sends SIGHUP to background children of hooks -> background mode
#     re-executes itself under `nohup`.
#   - Hooks must NEVER block git -> every exit path returns 0.
#   - pre-push feeds refs into stdin -> stdin is closed immediately.
#   - Runs on Linux, macOS (no flock: guarded), and Windows Git Bash
#     (nvm-windows / %APPDATA%\npm paths are probed).
#
# Modes:
#   with repomix.packs.json at the repo root -> builds every pack listed in
#     the manifest (skipping packs whose sources are older than the output),
#     then writes .repomix/PACKS_STATUS.md with fresh token estimates.
#   without a manifest (legacy monolith)     -> plain `repomix` build, plus a
#     warning when the monolith exceeds the reinit threshold.
#
# Flags: --force (-f) rebuild everything, --background (-b) detach via nohup.

set -u

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 0

REPOMIX_DIR="$ROOT/.repomix"
LOG_FILE="$REPOMIX_DIR/update.log"
LOCK="$REPOMIX_DIR/update.lock"
MANIFEST="$ROOT/repomix.packs.json"
STATUS_MD="$REPOMIX_DIR/PACKS_STATUS.md"
# o200k_base: ~3.8 characters per token for mixed code/text.
CHARS_PER_TOKEN=4
MONOLITH_REINIT_TOKENS=150000
BACKGROUND=0
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --background|-b) BACKGROUND=1 ;;
        --force|-f) FORCE=1 ;;
    esac
done

log() {
    mkdir -p "$REPOMIX_DIR"
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"
}

say() {
    printf '%s\n' "$*"
}

if [ "$BACKGROUND" -eq 1 ]; then
    mkdir -p "$REPOMIX_DIR"
    extra=
    [ "$FORCE" -eq 1 ] && extra=--force
    # nohup: git kills background children of hooks with SIGHUP otherwise.
    nohup "$0" $extra >>"$LOG_FILE" 2>&1 </dev/null &
    say "Repomix: index update started in background (pid $!)"
    exit 0
fi

exec </dev/null

prepend_path() {
    [ -d "$1" ] || return 0
    case ":$PATH:" in
        *":$1:"*) ;;
        *) PATH="$1:$PATH" ;;
    esac
}

# Git GUIs / IDE hooks often provide a bare PATH without node managers.
NVM_DIR="${NVM_DIR:-${HOME:-}/.nvm}"
if [ -d "$NVM_DIR/versions/node" ]; then
    latest=$(ls -1d "$NVM_DIR/versions/node/"*/bin 2>/dev/null | sort -V | tail -1)
    [ -n "$latest" ] && prepend_path "$latest"
fi
prepend_path "${HOME:-}/.local/bin"
prepend_path /usr/local/bin
prepend_path /opt/homebrew/bin              # macOS arm64 Homebrew
if [ -n "${APPDATA:-}" ]; then              # Windows Git Bash
    prepend_path "$APPDATA/npm"
    prepend_path "$APPDATA/nvm"
fi
[ -n "${NVM_HOME:-}" ] && prepend_path "$NVM_HOME"          # nvm-windows
[ -n "${NVM_SYMLINK:-}" ] && prepend_path "$NVM_SYMLINK"
export PATH

REPOMIX=
if command -v repomix >/dev/null 2>&1; then
    REPOMIX="repomix"
elif command -v npx >/dev/null 2>&1; then
    REPOMIX="npx --yes repomix"
else
    say "Repomix: command not found (nvm/npx unavailable). Skipping."
    log "SKIP: repomix not on PATH=$PATH"
    exit 0
fi

NODE=
command -v node >/dev/null 2>&1 && NODE=node

mkdir -p "$REPOMIX_DIR"
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
    flock 9   # absent on macOS / Git Bash: guarded, lock is best-effort there
fi

estimate_tokens() {
    # $1 = file; prints an o200k_base token estimate (chars / CHARS_PER_TOKEN)
    [ -f "$1" ] || { printf '0'; return; }
    chars=$(wc -c <"$1" | tr -d '[:space:]')
    printf '%s' "$((chars / CHARS_PER_TOKEN))"
}

# ---------------------------------------------------------------------------
# Legacy mode: no manifest -> single monolithic build via repomix.config.json
# ---------------------------------------------------------------------------
if [ ! -f "$MANIFEST" ]; then
    OUTPUT="$REPOMIX_DIR/output.xml"
    fresh=1
    if [ "$FORCE" -eq 0 ] && [ -f "$OUTPUT" ]; then
        newer=$(find . \
            \( -path ./.git -o -path ./.repomix -o -path ./node_modules \
               -o -path ./vendor -o -path ./dist -o -path ./var \) -prune \
            -o \( -type f -newer "$OUTPUT" -print \) 2>/dev/null | head -1)
        [ -z "$newer" ] || fresh=0
    else
        fresh=0
    fi
    if [ "$fresh" -eq 1 ]; then
        say "Repomix: index is fresh, skipping"
        log "SKIP: index is fresh"
        exit 0
    fi
    say "Repomix: rebuilding monolithic index..."
    log "START(legacy): $REPOMIX"
    if $REPOMIX --quiet; then
        tokens=$(estimate_tokens "$OUTPUT")
        say "Repomix: index updated ($OUTPUT, ~${tokens} tokens)"
        log "OK(legacy): updated $OUTPUT ~${tokens} tokens"
        if [ "$tokens" -gt "$MONOLITH_REINIT_TOKENS" ]; then
            say "Repomix WARNING: monolithic index is ~${tokens} tokens (> ${MONOLITH_REINIT_TOKENS})."
            say "  Split it into domain packs: run the reinit mode of the Repomix init guide."
            log "WARN(legacy): monolith ~${tokens} tokens exceeds ${MONOLITH_REINIT_TOKENS}"
        fi
    else
        say "Repomix: build failed, see $LOG_FILE"
        log "FAIL(legacy): $REPOMIX exit $?"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Pack mode: iterate over the manifest
# ---------------------------------------------------------------------------
if [ -z "$NODE" ]; then
    # repomix itself needs node, so this should never happen with a global
    # install; npx-only environments still expose node.
    say "Repomix: node not found, cannot parse $MANIFEST. Skipping."
    log "SKIP: node not available for manifest parsing"
    exit 0
fi

# Emits one line per pack: name|output|config|watch1;watch2;...
PACKS=$("$NODE" -e '
const m = require(process.argv[1]);
for (const p of (m.packs || [])) {
  const watch = (p.watch || []).join(";");
  console.log([p.name, p.output, p.config, watch].join("|"));
}' "$MANIFEST" 2>/dev/null)

if [ -z "$PACKS" ]; then
    say "Repomix: manifest $MANIFEST has no packs (or is invalid). Skipping."
    log "SKIP: empty/invalid manifest"
    exit 0
fi

CEILING=$("$NODE" -e 'console.log(require(process.argv[1]).pack_token_ceiling || 80000)' "$MANIFEST" 2>/dev/null)
[ -n "$CEILING" ] || CEILING=80000

pack_is_fresh() {
    # $1 = output file, $2 = semicolon-separated watch roots
    [ "$FORCE" -eq 1 ] && return 1
    [ -f "$1" ] || return 1
    old_ifs=$IFS; IFS=';'
    for w in $2; do
        IFS=$old_ifs
        [ -e "$w" ] || continue
        newer=$(find "$w" -type f -newer "$1" -print 2>/dev/null | head -1)
        [ -n "$newer" ] && return 1
        old_ifs=$IFS; IFS=';'
    done
    IFS=$old_ifs
    # Manifest or pack config changed -> rebuild too.
    for meta in "$MANIFEST" "$3"; do
        [ -f "$meta" ] && [ "$meta" -nt "$1" ] && return 1
    done
    return 0
}

built=0
skipped=0
failed=0
oversized=""
status_rows=""

old_ifs=$IFS
IFS='
'
for line in $PACKS; do
    IFS=$old_ifs
    name=${line%%|*};   rest=${line#*|}
    output=${rest%%|*}; rest=${rest#*|}
    config=${rest%%|*}
    watch=${rest#*|}

    if [ -z "$config" ] || [ ! -f "$config" ]; then
        say "Repomix: pack '$name' has no config ($config), skipping"
        log "SKIP($name): missing config $config"
        failed=$((failed + 1))
        continue
    fi

    if pack_is_fresh "$output" "$watch" "$config"; then
        skipped=$((skipped + 1))
        tokens=$(estimate_tokens "$output")
        status_rows="$status_rows$name|$tokens|fresh
"
        continue
    fi

    say "Repomix: building pack '$name'..."
    log "START($name): $REPOMIX -c $config"
    if $REPOMIX -c "$config" --quiet; then
        built=$((built + 1))
        tokens=$(estimate_tokens "$output")
        log "OK($name): $output ~${tokens} tokens"
        status_rows="$status_rows$name|$tokens|rebuilt
"
        if [ "$tokens" -gt "$CEILING" ]; then
            oversized="$oversized $name(~${tokens})"
            say "Repomix WARNING: pack '$name' is ~${tokens} tokens (ceiling $CEILING)."
        fi
    else
        failed=$((failed + 1))
        say "Repomix: pack '$name' failed, see $LOG_FILE"
        log "FAIL($name): $REPOMIX exit $?"
    fi
done
IFS=$old_ifs

# Fresh numbers for agents: AGENTS.md points here instead of hardcoding sizes.
{
    printf '# Repomix packs — build status\n\n'
    printf 'Auto-generated by scripts/update-repomix-index.sh. Do not edit.\n\n'
    printf '| Pack | ~Tokens (o200k est.) | Last build |\n'
    printf '|------|----------------------|------------|\n'
    printf '%s' "$status_rows" | while IFS='|' read -r n t s; do
        [ -n "$n" ] && printf '| %s | %s | %s |\n' "$n" "$t" "$s"
    done
    printf '\nPack ceiling: %s tokens. ' "$CEILING"
    printf 'Load the catalog plus AT MOST ONE domain pack per task.\n'
} >"$STATUS_MD"

say "Repomix: done (built $built, fresh $skipped, failed $failed)"
log "DONE: built=$built fresh=$skipped failed=$failed"

if [ -n "$oversized" ]; then
    say "Repomix WARNING: oversized packs:$oversized"
    say "  Split them (by subfolder, or move tests/one-offs out) via the reinit mode of the init guide."
    log "WARN: oversized packs:$oversized"
fi

exit 0
