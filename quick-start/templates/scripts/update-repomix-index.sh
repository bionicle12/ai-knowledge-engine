#!/bin/sh
# Rebuilds the local Repomix AI index (.repomix/*.xml).
#
# Design constraints (learned from production incidents):
#   - Git hooks and IDEs often run with PATH=/usr/bin:/bin (no nvm) -> we
#     bootstrap PATH ourselves and fall back to `npx --yes repomix@<version>`
#     (pinned: the version the template ignore globs were verified on).
#   - Git sends SIGHUP to background children of hooks -> background mode
#     re-executes itself (by absolute path) under `nohup`.
#   - Hooks must NEVER block git -> every exit path returns 0 (only --check
#     reports problems through its exit status), and hook runs never wait
#     for a build that is already running: they leave .repomix/update.pending
#     and the running build checks once more when it finishes. A rebase of
#     N commits therefore usually costs two builds; one run never does more
#     than three passes, and a re-check queued after its last one waits for
#     the next run (freshness is decided by content: delayed, never lost).
#   - pre-push feeds refs into stdin -> stdin is closed immediately.
#   - Runs on Linux, macOS and Windows Git Bash (no flock there: an atomic
#     mkdir lock is used instead; nvm-windows / %APPDATA%\npm are probed).
#
# Modes:
#   with repomix.packs.json at the repo root -> rebuilds every pack whose
#     sources changed (files added, removed, renamed or edited under its
#     `watch` paths, or its manifest entry / config edited), checks EVERY
#     pack against the token ceiling, checks coverage (files under the watch
#     paths that are in no pack or in several), scans the packs for
#     secret-like strings, removes leftover pack XMLs that are no longer in
#     the manifest, and writes .repomix/PACKS_STATUS.md — the one place with
#     sizes, OVER/FAILED flags and problems.
#   without a manifest (legacy monolith)     -> plain `repomix` build, plus a
#     warning when the monolith exceeds the reinit threshold.
#
# Flags: --force (-f) rebuild everything, --background (-b) detach via nohup,
#   --no-wait: when another build is running, queue a re-check and exit,
#   --check: build nothing, refresh PACKS_STATUS.md; exit 1 if it has warnings.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 0
SELF="$SCRIPT_DIR/$(basename -- "$0")"
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd) || exit 0
cd "$ROOT" || exit 0

REPOMIX_DIR="$ROOT/.repomix"
LOG_FILE="$REPOMIX_DIR/update.log"
LOCK="$REPOMIX_DIR/update.lock"          # flock(1) lock file
LOCK_DIR="$REPOMIX_DIR/update.lock.d"     # mkdir lock where flock is missing
PENDING="$REPOMIX_DIR/update.pending"
STATE="$REPOMIX_DIR/packs.state"
COVERAGE="$REPOMIX_DIR/coverage.txt"
MANIFEST="$ROOT/repomix.packs.json"
STATUS_MD="$REPOMIX_DIR/PACKS_STATUS.md"
# Fallback estimate only: the token count repomix reports is used when present.
CHARS_PER_TOKEN=4
MONOLITH_REINIT_TOKENS=150000
DEFAULT_CEILING=80000
# The repomix version the template ignore globs were verified on. The npx
# fallback runs exactly this version unless the manifest sets "repomix_version".
DEFAULT_REPOMIX_VERSION=1.14.0
LOG_MAX_BYTES=1048576   # update.log is moved to update.log.1 above this size
LOCK_WAIT=300           # seconds a manual run waits for a running build
BUILD_TIMEOUT=900       # seconds per repomix run (where `timeout` exists)
# Token formats that must never sit in a pack: GitHub, AWS, Slack, Stripe,
# OpenAI/Anthropic-style keys, PEM private keys. Only file paths are reported.
SECRET_RE='(^|[^A-Za-z0-9_])(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|(AKIA|ASIA)[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|[rs]k_live_[A-Za-z0-9]{16,}|sk-(proj-|ant-)?[A-Za-z0-9_-]{20,})|-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----'
ESC=$(printf '\033')
BACKGROUND=0
FORCE=0
NO_WAIT=0
CHECK=0

for arg in "$@"; do
    case "$arg" in
        --background|-b) BACKGROUND=1 ;;
        --force|-f) FORCE=1 ;;
        --no-wait) NO_WAIT=1 ;;
        --check) CHECK=1 ;;
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
    # $SELF is absolute, so a relative $0 (`../scripts/...`) works too.
    nohup sh "$SELF" --no-wait $extra >>"$LOG_FILE" 2>&1 </dev/null &
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

HAVE_REPOMIX=0
HAVE_NPX=0
command -v repomix >/dev/null 2>&1 && HAVE_REPOMIX=1
command -v npx >/dev/null 2>&1 && HAVE_NPX=1
if [ "$HAVE_REPOMIX" -eq 0 ] && [ "$HAVE_NPX" -eq 0 ] && [ "$CHECK" -eq 0 ]; then
    say "Repomix: command not found (nvm/npx unavailable). Skipping."
    log "SKIP: repomix not on PATH=$PATH"
    exit 0
fi

NODE=
command -v node >/dev/null 2>&1 && NODE=node
TIMEOUT_CMD=
command -v timeout >/dev/null 2>&1 && TIMEOUT_CMD=timeout
IN_GIT=0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 && IN_GIT=1

mkdir -p "$REPOMIX_DIR"
TMPD=$(mktemp -d "${TMPDIR:-/tmp}/repomix-index.XXXXXX" 2>/dev/null) || TMPD=
if [ -z "$TMPD" ] || [ ! -d "$TMPD" ]; then
    TMPD="$REPOMIX_DIR/tmp.$$"
    mkdir -p "$TMPD" || exit 0
fi
MKDIR_LOCK=0

cleanup() {
    rm -f "$TMPD"/* 2>/dev/null
    rmdir "$TMPD" 2>/dev/null
    if [ "$MKDIR_LOCK" -eq 1 ]; then
        rm -f "$LOCK_DIR/pid"
        rmdir "$LOCK_DIR" 2>/dev/null
    fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

# ---------------------------------------------------------------------------
# One build at a time. flock where it exists; otherwise (macOS, Git Bash) an
# atomic mkdir lock holding the owner's pid, taken over when the owner died.
# ---------------------------------------------------------------------------
lock_owner_gone() {
    owner=$(cat "$LOCK_DIR/pid" 2>/dev/null)
    if [ -n "$owner" ]; then
        kill -0 "$owner" 2>/dev/null && return 1
        return 0
    fi
    # No pid yet: the owner is between mkdir and writing it — unless the
    # directory is old (the owner was killed right there).
    [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]
}

acquire_lock() {
    if command -v flock >/dev/null 2>&1; then
        exec 9>"$LOCK"
        flock -n 9 && return 0
        [ "$NO_WAIT" -eq 1 ] && return 1
        say "Repomix: another index build is running, waiting up to ${LOCK_WAIT}s..."
        flock -w "$LOCK_WAIT" 9
        return
    fi
    waited=0
    while ! mkdir "$LOCK_DIR" 2>/dev/null; do
        if lock_owner_gone; then
            rm -f "$LOCK_DIR/pid"
            rmdir "$LOCK_DIR" 2>/dev/null
            continue
        fi
        [ "$NO_WAIT" -eq 1 ] && return 1
        [ "$waited" -ge "$LOCK_WAIT" ] && return 1
        [ "$waited" -eq 0 ] && say "Repomix: another index build is running, waiting up to ${LOCK_WAIT}s..."
        sleep 1
        waited=$((waited + 1))
    done
    MKDIR_LOCK=1
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    return 0
}

estimate_tokens() {
    # $1 = file; prints an o200k_base token estimate (chars / CHARS_PER_TOKEN)
    [ -f "$1" ] || { printf '0'; return; }
    chars=$(wc -c <"$1" | tr -d '[:space:]')
    printf '%s' "$((chars / CHARS_PER_TOKEN))"
}

# Runs repomix with the given arguments. The output (stdout + stderr, without
# spinner control codes) lands in $TMPD/out; the exit status in RC — read
# right after the command, before anything else can overwrite $?.
run_repomix() {
    if [ -n "$TIMEOUT_CMD" ]; then
        $TIMEOUT_CMD "$BUILD_TIMEOUT" $REPOMIX "$@" >"$TMPD/raw" 2>&1
    else
        $REPOMIX "$@" >"$TMPD/raw" 2>&1
    fi
    RC=$?
    tr -d '\r' <"$TMPD/raw" | sed "s/${ESC}\[[0-9;?]*[A-Za-z]//g" >"$TMPD/out"
}

reported_tokens() {
    # The "Total Tokens: 217 049 tokens" figure of the last repomix run.
    sed -n 's/.*Total Tokens:\(.*\)tokens.*/\1/p' "$TMPD/out" | head -1 | tr -cd '0-9'
}

log_security_report() {
    # $1 = pack name. repomix's own secret check excludes suspicious files
    # from the pack; record which ones (the report used to be silenced).
    sed -n '/Security Check:/,/Pack Summary:/p' "$TMPD/out" \
        | sed -n 's/^[0-9][0-9]*\. \(.*\)$/\1/p' >"$TMPD/excluded"
    EXCLUDED=$(wc -l <"$TMPD/excluded" | tr -d '[:space:]')
    [ "$EXCLUDED" -gt 0 ] || return 0
    log "SECURITY($1): repomix excluded $EXCLUDED suspicious file(s):"
    sed 's/^/    | /' "$TMPD/excluded" >>"$LOG_FILE"
}

log_output_tail() {
    tail -n 20 "$TMPD/out" | sed 's/^/    | /' >>"$LOG_FILE"
}

secret_files() {
    # $1 = pack XML; prints the packed files that contain secret-like strings.
    grep -n -E "$SECRET_RE" "$1" 2>/dev/null | cut -d: -f1 >"$TMPD/hits"
    [ -s "$TMPD/hits" ] || return 0
    awk 'NR == FNR { hit[$1] = 1; next }
         /^<file path="/ { p = $0; sub(/^<file path="/, "", p); sub(/">.*$/, "", p) }
         (FNR in hit) && p != "" { print p }' "$TMPD/hits" "$1" | sort -u
}

repomix_command() {
    # Sets REPOMIX for version $1 (pinned for npx) and REPOMIX_SHOWN.
    if [ "$HAVE_REPOMIX" -eq 1 ]; then
        REPOMIX="repomix"
        REPOMIX_SHOWN="repomix"
    elif [ "$HAVE_NPX" -eq 1 ]; then
        REPOMIX="npx --yes repomix@$1"
        REPOMIX_SHOWN="npx repomix@$1"
    else
        REPOMIX=
        REPOMIX_SHOWN="repomix (not found)"
    fi
}

# ---------------------------------------------------------------------------
# Legacy mode: no manifest -> single monolithic build via repomix.config.json
# ---------------------------------------------------------------------------
run_legacy() {
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
        return 0
    fi
    if [ "$CHECK" -eq 1 ]; then
        say "Repomix: monolithic index is stale (no repomix.packs.json: --check only reports freshness)"
        CHECK_WARNINGS=1
        return 0
    fi
    repomix_command "$DEFAULT_REPOMIX_VERSION"
    say "Repomix: rebuilding monolithic index..."
    log "START(legacy): $REPOMIX_SHOWN"
    run_repomix
    if [ "$RC" -eq 0 ]; then
        log_security_report legacy
        tokens=$(reported_tokens)
        [ -n "$tokens" ] || tokens=$(estimate_tokens "$OUTPUT")
        say "Repomix: index updated ($OUTPUT, ~${tokens} tokens)"
        log "OK(legacy): updated $OUTPUT ~${tokens} tokens"
        if [ "$tokens" -gt "$MONOLITH_REINIT_TOKENS" ]; then
            say "Repomix WARNING: monolithic index is ~${tokens} tokens (> ${MONOLITH_REINIT_TOKENS})."
            say "  Split it into domain packs: run the reinit mode of the Repomix init guide."
            log "WARN(legacy): monolith ~${tokens} tokens exceeds ${MONOLITH_REINIT_TOKENS}"
        fi
    else
        say "Repomix: build failed (exit $RC), see $LOG_FILE"
        log "FAIL(legacy): $REPOMIX_SHOWN exit $RC"
        log_output_tail
    fi
}

# ---------------------------------------------------------------------------
# Pack mode helpers
# ---------------------------------------------------------------------------
problem() {
    PROBLEMS="$PROBLEMS$*
"
}

list_sources() {
    # Every file under the given watch paths: the freshness key changes when
    # a file is added, removed or renamed (mtimes alone never show that).
    [ "$#" -gt 0 ] || return 0
    if [ "$IN_GIT" -eq 1 ]; then
        git -c core.quotePath=false ls-files -s -- "$@" 2>/dev/null
        git -c core.quotePath=false ls-files -d -o --exclude-standard -- "$@" 2>/dev/null
    else
        find "$@" -type f 2>/dev/null | LC_ALL=C sort
    fi
}

pack_key() {
    # $1 = manifest entry, $2 = pack config, $3... = existing watch paths
    entry=$1
    cfg=$2
    shift 2
    { printf '%s\n' "$entry"; cat "$cfg"; list_sources "$@"; } | cksum | tr -s ' \t' '--'
}

sources_newer_than() {
    # $1 = output file, $2... = watch paths: any file edited since the build?
    out=$1
    shift
    [ "$#" -gt 0 ] || return 1
    [ -n "$(find "$@" -type f -newer "$out" -print 2>/dev/null | head -1)" ]
}

state_of() {
    # $1 = pack name -> its line in packs.state ("pack|name|key|tokens|excluded")
    [ -f "$STATE" ] || return 0
    awk -F'|' -v n="$1" '$1 == "pack" && $2 == n { print; exit }' "$STATE"
}

abs_path() {
    # A relative manifest path is spelled canonically (`./x`, `a//x`, `a/./x`
    # -> `a/x`), so remove_leftovers recognises the pack it just built.
    case "$1" in
        /*|[A-Za-z]:*) printf '%s' "$1" ;;
        *) printf '%s/%s' "$ROOT" "$(printf '%s' "$1" \
               | sed -e 's|//*|/|g' -e ':a' -e 's|^\./||' -e 's|/\./|/|' -e 'ta')" ;;
    esac
}

check_coverage() {
    # $1 = file with all existing watch paths, $2 = file with "pack<TAB>output"
    roots_file=$1
    outputs_file=$2
    ORPHANS=0
    DUPLICATES=0
    if [ "$IN_GIT" -eq 0 ]; then
        # A note, not a problem: a correct non-git project must stay clean.
        COVERAGE_NOTE="Coverage not checked: not a git work tree."
        return 0
    fi
    [ -s "$roots_file" ] || return 0
    set --
    while IFS= read -r w; do set -- "$@" "$w"; done <"$roots_file"
    # Never packed on purpose (the template pack configs exclude them: agent
    # instructions and secret files) + the manifest's "coverage_ignore".
    set -- "$@" ':(exclude).repomix' ':(exclude,glob)**/AGENTS.md' ':(exclude,glob)**/CLAUDE.md'
    for g in .env '.env.*' '*.env' '*.pem' '*.key' '*.p12' '*.pfx' '*.jks' '*.keystore' \
             'id_rsa*' 'id_ecdsa*' 'id_ed25519*'; do
        set -- "$@" ":(exclude,glob)**/$g"
    done
    while IFS= read -r g; do
        [ -n "$g" ] && set -- "$@" ":(exclude)$g"
    done <"$TMPD/ignore"
    # Text files under the watch paths (git's binary check, .gitignore honoured).
    git -c core.quotePath=false grep -I -l --untracked -e '' -- "$@" 2>/dev/null \
        | LC_ALL=C sort -u >"$TMPD/universe"
    : >"$TMPD/members"
    tab=$(printf '\t')
    while IFS="$tab" read -r pname pout; do
        [ -f "$pout" ] || continue
        sed -n 's/^<file path="\(.*\)">$/\1/p' "$pout" \
            | sed 's/&quot;/"/g; s/&apos;/'"'"'/g; s/&lt;/</g; s/&gt;/>/g; s/&amp;/\&/g' \
            | tr '\\' '/' | LC_ALL=C sort -u | sed "s|^|$pname$tab|" >>"$TMPD/members"
    done <"$outputs_file"
    cut -f2- "$TMPD/members" | LC_ALL=C sort -u >"$TMPD/packed"
    LC_ALL=C comm -23 "$TMPD/universe" "$TMPD/packed" >"$TMPD/orphans"
    awk -F'\t' '{ n[$2]++; p[$2] = p[$2] " " $1 } END { for (f in n) if (n[f] > 1) print f ":" p[f] }' \
        "$TMPD/members" | LC_ALL=C sort >"$TMPD/dups"
    ORPHANS=$(wc -l <"$TMPD/orphans" | tr -d '[:space:]')
    DUPLICATES=$(wc -l <"$TMPD/dups" | tr -d '[:space:]')
    {
        printf '# Coverage of the watch paths in repomix.packs.json (%s)\n' "$NOW"
        printf '# Files in no pack (%s) — add them to a pack, or to "coverage_ignore" when that is intended:\n' "$ORPHANS"
        cat "$TMPD/orphans"
        printf '# Files in two or more packs (%s) — give the losing pack an ignore:\n' "$DUPLICATES"
        cat "$TMPD/dups"
    } >"$COVERAGE"
    if [ "$ORPHANS" -gt 0 ]; then
        top=$(sed -e 's|/[^/]*$||' -e 't' -e 's|.*|.|' "$TMPD/orphans" | LC_ALL=C sort | uniq -c \
            | sort -rn | head -3 | awk '{ n = $1; $1 = ""; sub(/^ /, ""); printf "%s%s (%s)", sep, $0, n; sep = ", " }')
        problem "- Coverage: $ORPHANS file(s) under the watch paths are in no pack (top folders: $top). Full list: \`.repomix/coverage.txt\`."
    fi
    if [ "$DUPLICATES" -gt 0 ]; then
        first=$(head -1 "$TMPD/dups")
        problem "- Coverage: $DUPLICATES file(s) are in two or more packs (e.g. $first). Full list: \`.repomix/coverage.txt\`."
    fi
}

remove_leftovers() {
    # Pack XMLs in .repomix/ that no manifest pack produces any more (renamed
    # or dropped packs) would still be found and loaded by agents.
    for f in "$REPOMIX_DIR"/*.xml; do
        [ -f "$f" ] || continue
        grep -qxF "$f" "$TMPD/outputs" && continue
        base=${f##*/}
        if [ "$base" = output.xml ]; then
            problem "- \`.repomix/output.xml\` is the old monolithic index, not a pack: do not load it; delete it once the packs replace it (reinit step 6)."
            continue
        fi
        head -n 5 "$f" | grep -q 'Repomix' || continue   # not a repomix output: not ours
        if [ "$CHECK" -eq 1 ]; then
            problem "- \`.repomix/$base\` is not in the manifest (leftover; the next build removes it). Do not load it."
        else
            rm -f "$f"
            say "Repomix: removed leftover .repomix/$base (not in the manifest)"
            log "REMOVED: .repomix/$base (not in the manifest)"
        fi
    done
}

write_status() {
    {
        printf '# Repomix packs — build status\n\n'
        printf 'Generated by scripts/update-repomix-index.sh on %s (HEAD %s, %s). Do not edit.\n\n' \
            "$NOW" "$HEAD_SHORT" "$VERSION_SHOWN"
        [ -n "$MANIFEST_ERROR" ] && \
            printf '> **FAILED: repomix.packs.json cannot be read (%s).** No pack was checked or built.\n' "$MANIFEST_ERROR"
        [ -n "$OVER_LIST" ] && \
            printf '> **OVER the %s-token ceiling:%s.** Never load these packs whole: use catalog.xml + Grep/Read on the real files, and offer the user a re-split (reinit mode of the init guide).\n' "$CEILING" "$OVER_LIST"
        [ -n "$FAILED_LIST" ] && \
            printf '> **FAILED:%s.** Their XML is missing or an old copy — see .repomix/update.log; do not trust it.\n' "$FAILED_LIST"
        [ -n "$STALE_LIST" ] && \
            printf '> **STALE (sources changed, not rebuilt yet):%s.** Run scripts/update-repomix-index.sh.\n' "$STALE_LIST"
        if [ -n "$PROBLEMS" ]; then
            printf '> **%s problem(s) — see "Problems" below.**\n' "$(printf '%s' "$PROBLEMS" | grep -c '^- ')"
        fi
        if [ -z "$MANIFEST_ERROR$OVER_LIST$FAILED_LIST$STALE_LIST$PROBLEMS" ]; then
            if [ -n "$COVERAGE_NOTE" ]; then
                printf 'All packs fresh and under the ceiling.\n'
            else
                printf 'All packs fresh and under the ceiling; every file under the watch paths is in exactly one pack.\n'
            fi
        fi
        [ -n "$COVERAGE_NOTE" ] && printf '%s\n' "$COVERAGE_NOTE"
        printf '\n| Pack | Tokens (o200k) | Ceiling | State | Built |\n'
        printf '|------|----------------|---------|-------|-------|\n'
        printf '%s' "$STATUS_ROWS" | while IFS='|' read -r n t c s b; do
            [ -n "$n" ] && printf '| %s | %s | %s | %s | %s |\n' "$n" "$t" "$c" "$s" "$b"
        done
        if [ -n "$PROBLEMS" ]; then
            printf '\n## Problems\n\n%s' "$PROBLEMS"
        fi
        printf '\nPack ceiling: %s tokens. Load the catalog plus AT MOST ONE domain pack per task; ' "$CEILING"
        printf 'never load an OVER, FAILED or STALE pack whole.\n'
    } >"$STATUS_MD.tmp" && mv -f "$STATUS_MD.tmp" "$STATUS_MD"
}

# ---------------------------------------------------------------------------
# Pack mode: iterate over the manifest
# ---------------------------------------------------------------------------
run_packs() {
    NOW=$(date '+%Y-%m-%d %H:%M')
    HEAD_SHORT=$(git rev-parse --short HEAD 2>/dev/null) || HEAD_SHORT=
    [ -n "$HEAD_SHORT" ] || HEAD_SHORT=none
    PROBLEMS=
    COVERAGE_NOTE=
    MANIFEST_ERROR=
    OVER_LIST=
    FAILED_LIST=
    STALE_LIST=
    STATUS_ROWS=
    CEILING=$DEFAULT_CEILING
    VERSION_SHOWN="repomix version unknown"

    if [ -z "$NODE" ]; then
        # repomix itself needs node, so this should never happen with a global
        # install; npx-only environments still expose node.
        say "Repomix: node not found, cannot parse $MANIFEST. Skipping."
        log "SKIP: node not available for manifest parsing"
        return 0
    fi

    # One line per item: C|ceiling, V|repomix_version, I|coverage_ignore
    # entry, P|name|output|config|watch1;watch2, X|name|<config output.filePath>
    # when that is not the pack's manifest "output" — or E|<parse error>.
    "$NODE" -e '
const fs = require("fs");
const path = require("path");
const one = (v) => String(v == null ? "" : v).replace(/[|\r\n;]/g, " ").trim();
let m;
try {
  m = JSON.parse(fs.readFileSync(process.argv[1], "utf8").replace(/^﻿/, ""));
} catch (e) {
  console.log("E|" + one(String(e.message).split("\n")[0]));
  process.exit(0);
}
if (!m || typeof m !== "object" || !Array.isArray(m.packs) || m.packs.length === 0) {
  console.log("E|no \"packs\" list");
  process.exit(0);
}
console.log("C|" + one(m.pack_token_ceiling));
console.log("V|" + one(m.repomix_version));
for (const g of (Array.isArray(m.coverage_ignore) ? m.coverage_ignore : [])) console.log("I|" + one(g));
for (const p of m.packs) {
  const w = Array.isArray(p && p.watch) ? p.watch : [];
  console.log(["P", one(p && p.name), one(p && p.output), one(p && p.config), w.map(one).join(";")].join("|"));
  try {  // repomix writes output.filePath (its default when unset), not our "output"
    const c = JSON.parse(fs.readFileSync(String(p.config), "utf8").replace(/^\uFEFF/, ""));
    const fp = c && c.output && typeof c.output.filePath === "string" ? c.output.filePath : "repomix-output.xml";
    if (p.output && path.resolve(fp) !== path.resolve(String(p.output))) console.log("X|" + one(p.name) + "|" + one(fp));
  } catch (e) { /* unreadable config: the build reports it */ }
}' "$MANIFEST" >"$TMPD/manifest" 2>&1

    MANIFEST_ERROR=$(sed -n 's/^E|//p' "$TMPD/manifest" | head -1)
    if [ -z "$MANIFEST_ERROR" ] && ! grep -q '^P|' "$TMPD/manifest"; then
        MANIFEST_ERROR=$(head -1 "$TMPD/manifest")
        [ -n "$MANIFEST_ERROR" ] || MANIFEST_ERROR="no output from node"
    fi
    if [ -n "$MANIFEST_ERROR" ]; then
        say "Repomix: manifest $MANIFEST is invalid ($MANIFEST_ERROR). Nothing built."
        log "FAIL: invalid manifest: $MANIFEST_ERROR"
        FAILED_LIST=" manifest"
        write_status
        CHECK_WARNINGS=1
        return 0
    fi

    c=$(sed -n 's/^C|//p' "$TMPD/manifest")
    case "$c" in ''|*[!0-9]*) ;; *) CEILING=$c ;; esac
    version=$(sed -n 's/^V|//p' "$TMPD/manifest")
    case "$version" in ''|*[!0-9A-Za-z.+-]*) version=$DEFAULT_REPOMIX_VERSION ;; esac
    sed -n 's/^I|//p' "$TMPD/manifest" >"$TMPD/ignore"
    sed -n 's/^P|//p' "$TMPD/manifest" >"$TMPD/packs"
    repomix_command "$version"
    old_version=$(sed -n 's/^repomix|//p' "$STATE" 2>/dev/null | head -1)
    [ -n "$old_version" ] && VERSION_SHOWN="repomix $old_version"
    version_checked=0

    built=0
    skipped=0
    failed=0
    : >"$TMPD/roots"
    : >"$TMPD/pack_outputs"
    : >"$TMPD/outputs"
    : >"$TMPD/state"

    while IFS= read -r line <&3; do
        name=${line%%|*};   rest=${line#*|}
        output=${rest%%|*}; rest=${rest#*|}
        config=${rest%%|*}
        watch=${rest#*|}
        [ -n "$name" ] || name="(unnamed)"

        if [ -z "$output" ]; then
            problem "- Pack '$name' has no \"output\" in repomix.packs.json."
            FAILED_LIST="$FAILED_LIST $name"
            STATUS_ROWS="$STATUS_ROWS$name|–|–|FAILED (no output path)|–
"
            failed=$((failed + 1))
            continue
        fi
        out_abs=$(abs_path "$output")
        printf '%s\n' "$out_abs" >>"$TMPD/outputs"
        printf '%s\t%s\n' "$name" "$out_abs" >>"$TMPD/pack_outputs"
        old=$(state_of "$name")
        old_key=$(printf '%s' "$old" | cut -d'|' -f3)
        old_tokens=$(printf '%s' "$old" | cut -d'|' -f4)
        old_excluded=$(printf '%s' "$old" | cut -d'|' -f5)

        # Watch entries are paths (folders or files), not globs or prefixes.
        set --
        set -f
        old_ifs=$IFS; IFS=';'
        for w in $watch; do
            IFS=$old_ifs
            if [ -e "$w" ]; then
                set -- "$@" "$w"
                printf '%s\n' "$w" >>"$TMPD/roots"
            else
                problem "- Pack '$name': watch path \`$w\` does not exist — watch entries are folders or files (not name prefixes or globs), so changes there are not detected."
            fi
            old_ifs=$IFS; IFS=';'
        done
        IFS=$old_ifs
        set +f
        [ "$#" -gt 0 ] || [ -n "$watch" ] || \
            problem "- Pack '$name' has no watch paths: only edits of its config trigger a rebuild."

        if [ -z "$config" ] || [ ! -f "$config" ]; then
            say "Repomix: pack '$name' has no config ($config), skipping"
            log "SKIP($name): missing config $config"
            failed=$((failed + 1))
            FAILED_LIST="$FAILED_LIST $name"
            state_label="FAILED (no config \`$config\`)"
            [ -f "$out_abs" ] && state_label="FAILED (no config \`$config\`; old copy)"
            tokens=$old_tokens
            [ -n "$tokens" ] || tokens=$(estimate_tokens "$out_abs")
            [ -f "$out_abs" ] || tokens=
            STATUS_ROWS="$STATUS_ROWS$name|${tokens:-–}|–|$state_label|–
"
            continue
        fi

        cfg_out=$(awk -F'|' -v n="$name" '$1 == "X" && $2 == n { sub(/^X[|][^|]*[|]/, ""); print; exit }' "$TMPD/manifest")
        if [ -n "$cfg_out" ]; then
            # Building would leave the manifest's file untouched (reported as
            # rebuilt) and write one that the leftover cleanup deletes.
            problem "- Pack '$name': \`$config\` writes \`$cfg_out\` but the manifest \"output\" is \`$output\` — make the two paths equal. Not built."
            failed=$((failed + 1))
            FAILED_LIST="$FAILED_LIST $name"
            state_label="config writes \`$cfg_out\`"
            [ -f "$out_abs" ] && state_label="$state_label; old copy"
            state_label="FAILED ($state_label)"
            STATUS_ROWS="$STATUS_ROWS$name|${old_tokens:-–}|–|$state_label|–
"
            continue
        fi

        key=$(pack_key "$line" "$config" "$@")
        state_label=
        new_key=$old_key
        tokens=
        excluded=$old_excluded
        if [ "$FORCE" -eq 0 ] && [ -f "$out_abs" ] && [ "$key" = "$old_key" ] \
            && ! sources_newer_than "$out_abs" "$@"; then
            skipped=$((skipped + 1))
            state_label=fresh
            tokens=$old_tokens
        elif [ "$CHECK" -eq 1 ]; then
            state_label="STALE"
            [ -f "$out_abs" ] || state_label="STALE (not built)"
            STALE_LIST="$STALE_LIST $name"
            tokens=$old_tokens
        elif [ -z "$REPOMIX" ]; then
            failed=$((failed + 1))
            FAILED_LIST="$FAILED_LIST $name"
            state_label="FAILED (repomix not found)"
            tokens=$old_tokens
        else
            if [ "$version_checked" -eq 0 ]; then
                run_repomix --version
                v=$(grep -E '^[0-9]+\.[0-9]+' "$TMPD/out" | head -1)
                [ -n "$v" ] && VERSION_SHOWN="repomix $v"
                [ "$HAVE_REPOMIX" -eq 0 ] && VERSION_SHOWN="$VERSION_SHOWN via npx"
                version_checked=1
            fi
            say "Repomix: building pack '$name'..."
            log "START($name): $REPOMIX_SHOWN -c $config"
            run_repomix -c "$config"
            if [ "$RC" -eq 0 ] && [ -f "$out_abs" ]; then
                built=$((built + 1))
                state_label=rebuilt
                new_key=$key
                log_security_report "$name"
                excluded=$EXCLUDED
                tokens=$(reported_tokens)
                [ -n "$tokens" ] || tokens=$(estimate_tokens "$out_abs")
                log "OK($name): $output $tokens tokens"
            else
                failed=$((failed + 1))
                FAILED_LIST="$FAILED_LIST $name"
                new_key=-
                tokens=$old_tokens
                if [ -f "$out_abs" ]; then
                    state_label="FAILED (old copy)"
                else
                    state_label="FAILED (no output)"
                fi
                [ "$RC" -eq 0 ] && RC="0, but no $output was written"
                say "Repomix: pack '$name' failed (exit $RC), see $LOG_FILE"
                log "FAIL($name): $REPOMIX_SHOWN exit $RC"
                log_output_tail
            fi
        fi

        shown_tokens=–
        ceiling_flag=–
        if [ -f "$out_abs" ]; then
            if [ -z "$tokens" ]; then
                tokens=$(estimate_tokens "$out_abs")
                shown_tokens="~$tokens (est.)"
            else
                shown_tokens=$tokens
            fi
            ceiling_flag=ok
            if [ "$tokens" -gt "$CEILING" ]; then
                ceiling_flag=OVER
                OVER_LIST="$OVER_LIST $name"
                say "Repomix WARNING: pack '$name' is ~${tokens} tokens (ceiling $CEILING)."
            fi
            secrets=$(secret_files "$out_abs" | tr '\n' ' ' | sed 's/ $//')
            if [ -n "$secrets" ]; then
                problem "- Security: pack '$name' contains secret-like strings from: $secrets — exclude these files in \`$config\` (or remove the secret) and rebuild; never share this pack."
                log "SECURITY($name): secret-like strings in: $secrets"
            fi
            if [ -n "$excluded" ] && [ "$excluded" -gt 0 ] 2>/dev/null; then
                problem "- Security: repomix's secret check excluded $excluded suspicious file(s) from pack '$name' (list in \`.repomix/update.log\`)."
            fi
            built_at=$(date -r "$out_abs" '+%Y-%m-%d %H:%M' 2>/dev/null) || built_at=–
        else
            built_at=–
            tokens=
        fi
        STATUS_ROWS="$STATUS_ROWS$name|$shown_tokens|$ceiling_flag|$state_label|$built_at
"
        [ -n "$new_key" ] && printf 'pack|%s|%s|%s|%s\n' "$name" "$new_key" "$tokens" "$excluded" >>"$TMPD/state"
    done 3<"$TMPD/packs"

    if [ "$CHECK" -eq 0 ]; then
        {
            printf '# Written by scripts/update-repomix-index.sh: freshness keys. Do not edit.\n'
            printf 'repomix|%s\n' "${VERSION_SHOWN#repomix }"
            cat "$TMPD/state"
        } >"$STATE.tmp" && mv -f "$STATE.tmp" "$STATE"
    fi

    LC_ALL=C sort -u "$TMPD/roots" >"$TMPD/roots.sorted"
    check_coverage "$TMPD/roots.sorted" "$TMPD/pack_outputs"
    remove_leftovers
    if [ "$IN_GIT" -eq 1 ] && ! git check-ignore -q "$STATE" 2>/dev/null; then
        problem "- \`.gitignore\` does not cover the build files in \`.repomix/\` (e.g. packs.state, update.log.1, backup-*/): replace its Repomix lines with the block from the init guide (Phase 5)."
    fi
    write_status

    if [ "$CHECK" -eq 1 ]; then
        say "Repomix: checked (fresh $skipped, stale $(printf '%s' "$STALE_LIST" | wc -w | tr -d ' '), failed $failed) — see $STATUS_MD"
    else
        say "Repomix: done (built $built, fresh $skipped, failed $failed)"
        log "DONE: built=$built fresh=$skipped failed=$failed"
    fi
    if [ -n "$OVER_LIST" ]; then
        say "Repomix WARNING: packs over the ceiling:$OVER_LIST"
        say "  Split them (by subfolder, or move tests/one-offs out) via the reinit mode of the init guide."
        log "WARN: packs over the ceiling:$OVER_LIST"
    fi
    if [ -n "$PROBLEMS" ]; then
        say "Repomix: $(printf '%s' "$PROBLEMS" | grep -c '^- ') problem(s) listed in $STATUS_MD"
    fi
    [ -z "$OVER_LIST$FAILED_LIST$STALE_LIST$PROBLEMS" ] || CHECK_WARNINGS=1
}

# ---------------------------------------------------------------------------
# Main: run, then once more if a hook queued a re-check meanwhile.
# ---------------------------------------------------------------------------
CHECK_WARNINGS=0
# --check only reads and rewrites PACKS_STATUS.md / coverage.txt (atomically),
# so it takes no lock and leaves a queued re-check to the running build.
if [ "$CHECK" -eq 0 ]; then
    if ! acquire_lock; then
        : >"$PENDING"
        if [ "$NO_WAIT" -eq 1 ]; then
            say "Repomix: another index build is running; it will re-check when it finishes."
            log "QUEUED: another build is running (re-check requested)"
        else
            say "Repomix: another index build is still running after ${LOCK_WAIT}s; queued a re-check."
            log "QUEUED: lock wait timed out after ${LOCK_WAIT}s"
        fi
        exit 0
    fi
    if [ -f "$LOG_FILE" ] && [ "$(wc -c <"$LOG_FILE" | tr -d '[:space:]')" -gt "$LOG_MAX_BYTES" ]; then
        mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
    rm -f "$PENDING"
fi
pass=1
while :; do
    if [ -f "$MANIFEST" ]; then
        run_packs
    else
        run_legacy
    fi
    [ "$CHECK" -eq 0 ] && [ "$pass" -lt 3 ] && [ -f "$PENDING" ] || break
    rm -f "$PENDING"
    pass=$((pass + 1))
    log "RERUN: changes were queued during the build"
done

if [ "$CHECK" -eq 1 ] && [ "$CHECK_WARNINGS" -eq 1 ]; then
    exit 1
fi
exit 0
