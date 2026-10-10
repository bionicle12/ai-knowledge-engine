#!/usr/bin/env bash
# finalize.sh — POST-deploy flattening helper.
#
# Run this AFTER the agent has fully deployed the knowledge base inside
# <project-root>/knowledge-base/ and kb_doctor exits 0. It promotes the
# deployed base from knowledge-base/ up to the project root, fills kb-docs/
# with the instruction modules from setup/, then removes the now-empty
# knowledge-base/ folder and the original setup/ folder.
#
# Layout BEFORE finalize:
#   my-project/
#   ├── .venv/                   ← the venv lives at the project root
#   ├── setup/                   ← upstream instructions (source)
#   │   ├── 00_OVERVIEW.md … 18_HEAL.md, README.md
#   │   └── shell/finalize.sh    ← this file
#   └── knowledge-base/          ← deployed base (agent-built)
#       ├── AGENTS.md, kb.config.yml, kb-docs/, ...
#       └── scripts/, shell/, raw/, knowledge/, ...
#
# Layout AFTER finalize:
#   my-project/
#   ├── .venv/                   ← untouched
#   ├── AGENTS.md, kb.config.yml, START_HERE.md, ...
#   ├── kb-docs/                 ← 00_OVERVIEW.md … 18_HEAL.md, README.md
#   ├── scripts/, shell/, templates/, examples/
#   ├── raw/, knowledge/, processed/, assets/, ...
#   ├── reindex.command, reindex.bat, ... (launchers promoted from shell/)
#   └── (no setup/, no knowledge-base/)
#
# Usage:
#   bash setup/shell/finalize.sh [flags]
#
# Flags:
#   --kb-dir <path>   deployed base location (default: ./knowledge-base)
#   --dry-run         print what would happen without touching anything
#   --keep-setup      do NOT delete setup/ at the end
#   --force           move conflicting project-root entries to
#                     .kb-finalize-backup/<timestamp>/ instead of refusing
#   --resume          continue a run that stopped part-way (reads the
#                     .kb-finalize.journal it left at the project root)
#   --claude-md       write a one-line CLAUDE.md (`@AGENTS.md`) without asking
#   --no-claude-md    never write CLAUDE.md
#
# Never moved or deleted: .git and virtualenvs (.venv, or any folder holding
# pyvenv.cfg) — a moved venv breaks. A knowledge-base/.venv stays where it is
# with a warning; create the venv at the project root instead
# (kb-docs/01_PREREQUISITES.md).
#
# Only the kit's copy runs (setup/shell/finalize.sh): the folder above this
# script's shell/ is deleted at the end, so a deployed base's own copy (every
# base ships shell/) refuses to run.
#
# .gitignore / .gitattributes: when the project root already has one, the
# base's rules it lacks are added at its top, so the project's own rules keep
# precedence (a later matching line wins). A catch-all `* ...` attribute rule
# is left out: the project's line-ending defaults stay as they were.
#
# CLAUDE.md: without a flag it is written when kb.config.yml sets
# `index.primary_agent: claude-code`; otherwise the script asks (no answer,
# e.g. a non-interactive run, means no).
#
# Exit codes:
#   0 — finalized
#   1 — refused before anything changed (preconditions, conflicts, flags)
#   2 — stopped part-way: .kb-finalize.journal records the run. Fix the
#       reported problem, then re-run with --resume.

set -euo pipefail

KB_DIR=""
DRY_RUN=false
KEEP_SETUP=false
FORCE=false
RESUME=false
CLAUDE_MD=""   # "" = decide from kb.config.yml / ask; yes/no = explicit

while [ $# -gt 0 ]; do
  case "$1" in
    --kb-dir)
      if [ $# -lt 2 ]; then
        echo "--kb-dir needs a path" >&2
        exit 1
      fi
      KB_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --keep-setup)
      KEEP_SETUP=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --resume)
      RESUME=true
      shift
      ;;
    --claude-md)
      CLAUDE_MD="yes"
      shift
      ;;
    --no-claude-md)
      CLAUDE_MD="no"
      shift
      ;;
    -h|--help)
      awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 1
      ;;
  esac
done

# Resolve where this script was launched from.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SETUP_DIR/.." && pwd)"
JOURNAL="$PROJECT_ROOT/.kb-finalize.journal"
BACKUP_DIR=""
APPLYING=false

_journal_get() {
  sed -n "s/^$1=//p" "$JOURNAL" | head -n 1
}

# Refuse (exit 1, nothing changed). With --resume the refused values come from
# the journal, which is then unusable.
_refuse() {
  echo "❌ Refusing: $1" >&2
  if [ "$RESUME" = true ]; then
    echo "   The journal $JOURNAL cannot be used; this run changed nothing." >&2
    echo "   Check what the interrupted run already moved into $PROJECT_ROOT," >&2
    echo "   delete the journal, then run finalize again without --resume" >&2
    echo "   (or finish the remaining steps by hand)." >&2
  fi
  exit 1
}

# SETUP_DIR is deleted at the end: it must be the engine kit (the upstream
# knowledge-base/ folder copied as setup/), never a deployed base — every base
# ships shell/finalize.sh too, and running that copy would delete the base.
if [ ! -f "$SETUP_DIR/00_OVERVIEW.md" ] || [ -e "$SETUP_DIR/kb.config.yml" ] \
    || [ -e "$SETUP_DIR/AGENTS.md" ]; then
  echo "❌ Refusing: $SETUP_DIR is not the engine kit (setup/)." >&2
  echo "   finalize.sh deletes the folder that holds its shell/ at the end, so only" >&2
  echo "   the kit's copy runs: bash setup/shell/finalize.sh. This copy belongs to" >&2
  echo "   a deployed base; nothing was changed." >&2
  exit 1
fi

# -------- journal from an interrupted run --------

if [ "$RESUME" = true ]; then
  if [ ! -f "$JOURNAL" ]; then
    echo "❌ Refusing --resume: no interrupted run found ($JOURNAL is missing)." >&2
    exit 1
  fi
  # The journal is written in one go and ends with end=ok: anything else is a
  # damaged file (e.g. a full disk), never a plan to act on.
  if [ "$(_journal_get end)" != "ok" ]; then
    _refuse "the journal is empty or cut short."
  fi
  if [ "$(_journal_get project_root)" != "$PROJECT_ROOT" ]; then
    _refuse "the journal was written for another project root ($(_journal_get project_root))."
  fi
  KB_DIR="$(_journal_get kb_dir)"
  BACKUP_DIR="$(_journal_get backup_dir)"
  case "$BACKUP_DIR" in
    */..|*/../*) _refuse "the journal names an unexpected backup folder ($BACKUP_DIR)." ;;
    "$PROJECT_ROOT"/.kb-finalize-backup/?*) ;;
    *) _refuse "the journal names an unexpected backup folder ($BACKUP_DIR)." ;;
  esac
  [ "$(_journal_get keep_setup)" = true ] && KEEP_SETUP=true
  [ "$(_journal_get force)" = true ] && FORCE=true
  if [ -z "$CLAUDE_MD" ]; then
    CLAUDE_MD="$(_journal_get claude_md)"
  fi
elif [ -f "$JOURNAL" ]; then
  echo "❌ Refusing: a previous finalize stopped part-way ($JOURNAL)." >&2
  echo "   Re-run with --resume to continue it. If --resume reports the journal" >&2
  echo "   as unusable, delete it and run finalize again." >&2
  exit 1
fi

# Resolve the deployed knowledge-base location
if [ "$RESUME" = true ]; then
  :   # recorded in the journal; the folder may already be gone
elif [ -n "$KB_DIR" ]; then
  if [ ! -d "$KB_DIR" ]; then
    echo "❌ Refusing: deployed base not found at $KB_DIR" >&2
    exit 1
  fi
  KB_DIR="$(cd "$KB_DIR" && pwd)"
else
  KB_DIR="$PROJECT_ROOT/knowledge-base"
fi

# Every entry of KB_DIR is moved into the project root, and SETUP_DIR is
# deleted at the end: KB_DIR must be an absolute path that is neither the
# project root nor one of its ancestors, and must not be or sit in SETUP_DIR.
case "$KB_DIR" in
  ""|/) _refuse "no usable knowledge-base folder (got '$KB_DIR')." ;;
  */..|*/../*|*/.|*/./*) _refuse "the knowledge-base path is not normalized: $KB_DIR" ;;
  /*) ;;
  *) _refuse "the knowledge-base path is not absolute: $KB_DIR" ;;
esac
if [ "$KB_DIR" = "$PROJECT_ROOT" ]; then
  _refuse "knowledge-base equals project root — already flat."
fi
case "$PROJECT_ROOT/" in
  "$KB_DIR"/*) _refuse "the project root lies inside the knowledge-base folder ($KB_DIR)." ;;
esac
# The folder removed at the end must not hold the base: its kept .git/.venv
# would go too.
case "$KB_DIR" in
  "$SETUP_DIR")
    _refuse "the knowledge-base folder is the setup folder itself ($KB_DIR),
   which finalize deletes at the end." ;;
  "$SETUP_DIR"/*)
    _refuse "the base sits inside $SETUP_DIR, which finalize deletes at the end.
   Move it out first (e.g. to ./knowledge-base) and run finalize again." ;;
esac

case "$KB_DIR" in
  "$PROJECT_ROOT"/*) KB_LABEL="${KB_DIR#"$PROJECT_ROOT"/}" ;;
  *) KB_LABEL="$KB_DIR" ;;
esac
if [ -z "$BACKUP_DIR" ]; then
  BACKUP_DIR="$PROJECT_ROOT/.kb-finalize-backup/$(date +%Y-%m-%dT%H-%M-%S)"
  if [ -e "$BACKUP_DIR" ]; then
    BACKUP_DIR="$BACKUP_DIR-$$"
  fi
fi

echo "🔧 finalize.sh"
echo "   project root:    $PROJECT_ROOT"
echo "   setup dir:       $SETUP_DIR"
echo "   knowledge-base:  $KB_DIR"
echo "   dry-run:         $DRY_RUN"
echo "   keep-setup:      $KEEP_SETUP"
echo "   force:           $FORCE"
echo "   resume:          $RESUME"
echo ""

# -------- preconditions --------

if [ "$RESUME" = false ]; then
  if [ ! -d "$KB_DIR" ]; then
    echo "❌ Refusing: deployed base not found at $KB_DIR" >&2
    echo "   Did the agent finish creating the knowledge base?" >&2
    exit 1
  fi

  # Critical file check: a finalized base should have these
  required=("AGENTS.md" "kb.config.yml" "scripts/kb_ingest.py")
  missing=()
  for f in "${required[@]}"; do
    if [ ! -e "$KB_DIR/$f" ]; then
      missing+=("$f")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "❌ Refusing: deployed base is missing required files:" >&2
    for f in "${missing[@]}"; do echo "   - $f" >&2; done
    echo "   Run scripts/kb_doctor.py inside $KB_LABEL/ first to diagnose." >&2
    exit 1
  fi
fi

# .git and virtualenvs never move: a venv hard-codes its absolute path, and a
# repository is the owner's to relocate.
_kept_in_place() {
  case "$(basename "$1")" in
    .git|.venv) return 0 ;;
  esac
  [ -f "$1/pyvenv.cfg" ]
}

# The base's .gitignore / .gitattributes are merged into the project's own
# (a regular file, not a symlink) instead of conflicting with it: their
# patterns are relative to the base root, which the project root becomes.
_merged_into_root() {
  local own="$PROJECT_ROOT/$(basename "$1")"
  case "$(basename "$1")" in
    .gitignore|.gitattributes) [ -f "$1" ] && [ -f "$own" ] && [ ! -L "$own" ] ;;
    *) return 1 ;;
  esac
}

# The rules of $1 that $2 lacks, each with the comment lines just above it
# in $1, or nothing when $2 lacks none. CRs are ignored when comparing. For
# .gitattributes a catch-all `* ...` rule is left out: it would change the
# line endings of every file the project has no rule for.
_lines_to_add() {
  local catchall=keep
  [ "$(basename "$1")" = .gitattributes ] && catchall=skip
  awk -v catchall="$catchall" '{ sub(/\r$/, "") }
       FILENAME == ARGV[1] { have[$0] = 1; next }
       /^[[:space:]]*(#|$)/ { note = note $0 "\n"; next }
       (catchall == "skip" && $1 == "*") || ($0 in have) || seen[$0]++ { note = ""; next }
       { out = out note $0 "\n"; note = ""; n++ }
       END { sub(/^\n+/, "", out); if (n) printf "%s", out }' "$2" "$1"
}
_count_rules() {
  printf '%s\n' "$1" | grep -c -v -E '^[[:space:]]*(#|$)' || true
}

# Conflict check: would moving overwrite anything at the project root?
conflicts=()
kept=()
shopt -s nullglob dotglob
for entry in "$KB_DIR"/*; do
  base="$(basename "$entry")"
  case "$base" in
    knowledge-base|setup) continue ;;
  esac
  if _kept_in_place "$entry"; then
    kept+=("$base")
    continue
  fi
  _merged_into_root "$entry" && continue
  if [ -e "$PROJECT_ROOT/$base" ] || [ -L "$PROJECT_ROOT/$base" ]; then
    conflicts+=("$base")
  fi
done
shopt -u nullglob dotglob

if [ ${#conflicts[@]} -gt 0 ] && [ "$FORCE" = false ]; then
  echo "❌ Refusing: these entries already exist at $PROJECT_ROOT and would be overwritten:" >&2
  for c in "${conflicts[@]}"; do echo "   - $c" >&2; done
  echo "   Move them aside yourself, or re-run with --force to move them to" >&2
  echo "   .kb-finalize-backup/<timestamp>/ first (nothing is deleted)." >&2
  exit 1
fi

if [ ${#kept[@]} -gt 0 ]; then
  for k in "${kept[@]}"; do
    if [ "$k" = ".git" ]; then
      echo "⚠️  $KB_LABEL/.git stays in place: finalize never moves or deletes a git repository."
      echo "   If it holds the base's history and the project root has none, move it yourself."
    else
      echo "⚠️  $KB_LABEL/$k is a virtualenv and stays in place: a moved venv breaks."
      echo "   Create the venv at the project root instead (kb-docs/01_PREREQUISITES.md):"
      echo "     python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
      echo "   then delete $KB_LABEL/$k yourself."
    fi
  done
  echo ""
fi

# -------- decisions that need kb.config.yml --------

# index.primary_agent from kb.config.yml (line-based: no YAML parser needed).
_primary_agent() {
  local cfg="$PROJECT_ROOT/kb.config.yml"
  [ -f "$KB_DIR/kb.config.yml" ] && cfg="$KB_DIR/kb.config.yml"
  [ -f "$cfg" ] || return 0
  awk '
    function show(value) {
      sub(/^[^:]*:[[:space:]]*/, "", value)
      sub(/[[:space:]]+#.*$/, "", value)
      gsub(/["'\'']/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print tolower(value)
      exit
    }
    { sub(/\r$/, "") }
    # flow style: index: {primary_agent: claude-code, ...}
    /^index[[:space:]]*:[[:space:]]*\{/ && match($0, /primary_agent[[:space:]]*:[^,}]*/) {
      show(substr($0, RSTART, RLENGTH))
    }
    /^[^[:space:]#]/ { section = $0; sub(/[[:space:]]*:.*/, "", section); next }
    section == "index" && /^[[:space:]]+primary_agent[[:space:]]*:/ { show($0) }
  ' "$cfg"
}
PRIMARY_AGENT="$(_primary_agent)"

# -------- dry run --------

_module_sources() {
  local f
  shopt -s nullglob
  for f in "$SETUP_DIR"/[0-9][0-9]_*.md "$SETUP_DIR/README.md"; do
    [ -f "$f" ] && printf '%s\n' "$f"
  done
  shopt -u nullglob
}

if [ "$DRY_RUN" = true ]; then
  shopt -s nullglob dotglob
  for entry in "$KB_DIR"/*; do
    base="$(basename "$entry")"
    case "$base" in
      knowledge-base|setup) continue ;;
    esac
    _kept_in_place "$entry" && continue
    if _merged_into_root "$entry"; then
      echo "🔸 would add to ./$base (at the top) the $(_count_rules "$(_lines_to_add "$entry" "$PROJECT_ROOT/$base")") rule(s) of $KB_LABEL/$base it lacks"
      continue
    fi
    if [ -e "$PROJECT_ROOT/$base" ] || [ -L "$PROJECT_ROOT/$base" ]; then
      echo "🔸 would move aside: ./$base → ${BACKUP_DIR#"$PROJECT_ROOT"/}/$base"
    fi
    echo "🔸 would move: $KB_LABEL/$base → ./$base"
  done
  shopt -u nullglob dotglob
  echo ""
  echo "🔸 would copy into kb-docs/ (existing files kept): $(_module_sources | wc -l | tr -d ' ') instruction module(s) from setup/"
  echo "🔸 would remove (knowledge-base, if empty): $KB_DIR"
  if [ "$KEEP_SETUP" = false ]; then
    echo "🔸 would remove (setup):                    $SETUP_DIR"
  fi
  if [ "$CLAUDE_MD" = "yes" ] || { [ -z "$CLAUDE_MD" ] && [ "$PRIMARY_AGENT" = "claude-code" ]; }; then
    echo "🔸 would write:                             ./CLAUDE.md  (@AGENTS.md)"
  elif [ -z "$CLAUDE_MD" ]; then
    echo "🔸 would ask:                               create CLAUDE.md for Claude Code?"
  fi
  echo ""
  echo "Dry-run complete. Re-run without --dry-run to apply."
  exit 0
fi

# -------- apply (journaled) --------

# Any failure from here on leaves the journal behind and exits 2.
_on_exit() {
  local code=$?
  if [ "$APPLYING" = true ] && [ "$code" -ne 0 ]; then
    echo "" >&2
    echo "❌ finalize stopped part-way. Nothing was deleted; entries already moved stay at the project root." >&2
    echo "   Journal: $JOURNAL" >&2
    if [ -d "$BACKUP_DIR" ]; then
      echo "   Project-root entries moved aside: $BACKUP_DIR" >&2
    fi
    echo "   Fix the problem above, then re-run: bash \"$0\" --resume" >&2
    exit 2
  fi
}
trap _on_exit EXIT

_fail() {
  echo "❌ $1" >&2
  exit 2
}

if [ "$RESUME" = false ]; then
  # One printf into a temp file, then a rename: a full disk leaves no journal
  # at all rather than a truncated one (--resume also requires end=ok).
  if ! printf '%s\n' \
      "# finalize.sh journal: this run has not finished. Continue it with" \
      "#   bash setup/shell/finalize.sh --resume" \
      "started_at=$(date +%Y-%m-%dT%H:%M:%S)" \
      "project_root=$PROJECT_ROOT" \
      "kb_dir=$KB_DIR" \
      "backup_dir=$BACKUP_DIR" \
      "keep_setup=$KEEP_SETUP" \
      "force=$FORCE" \
      "claude_md=$CLAUDE_MD" \
      "end=ok" > "$JOURNAL.tmp" 2>/dev/null \
    || ! mv -f "$JOURNAL.tmp" "$JOURNAL" 2>/dev/null; then
    rm -f "$JOURNAL.tmp" 2>/dev/null || true
    echo "❌ Refusing: could not write $JOURNAL (disk full? read-only folder?)." >&2
    echo "   Nothing was changed." >&2
    exit 1
  fi
fi
APPLYING=true

# -------- move payload --------

shopt -s nullglob dotglob
for entry in "$KB_DIR"/*; do
  base="$(basename "$entry")"
  case "$base" in
    knowledge-base|setup) continue ;;
  esac
  _kept_in_place "$entry" && continue
  if _merged_into_root "$entry"; then
    # Adding only the missing rules keeps a resumed run from adding twice.
    # They go first: the project's own rules come later and keep precedence.
    to_add="$(_lines_to_add "$entry" "$PROJECT_ROOT/$base")" \
      || _fail "could not read $KB_LABEL/$base"
    if [ -n "$to_add" ]; then
      own="$PROJECT_ROOT/$base"
      { printf '# --- rules from %s/%s (AI Knowledge Engine), added by finalize.sh.\n' "$KB_LABEL" "$base"
        printf '# --- The project rules below come later, so they win where both match.\n'
        printf '%s\n' "$to_add"
        printf '# --- end of the AI Knowledge Engine rules\n\n'
        cat "$own"
      } > "$own.kb-finalize.tmp" && mv -f "$own.kb-finalize.tmp" "$own" \
        || { rm -f "$own.kb-finalize.tmp"; _fail "could not update ./$base"; }
    fi
    rm -f "$entry" || _fail "could not remove $KB_LABEL/$base after merging it"
    echo "✅ merged $KB_LABEL/$base into ./$base ($(_count_rules "$to_add") rule(s) added)"
    continue
  fi
  if [ -e "$PROJECT_ROOT/$base" ] || [ -L "$PROJECT_ROOT/$base" ]; then
    if [ "$FORCE" = false ]; then
      _fail "./$base already exists at the project root; move it aside or add --force"
    fi
    mkdir -p "$BACKUP_DIR" || _fail "could not create $BACKUP_DIR"
    mv "$PROJECT_ROOT/$base" "$BACKUP_DIR/$base" || _fail "could not move ./$base aside"
    echo "📦 moved aside ./$base → ${BACKUP_DIR#"$PROJECT_ROOT"/}/$base"
  fi
  mv "$entry" "$PROJECT_ROOT/$base" || _fail "could not move $KB_LABEL/$base"
  echo "✅ moved $KB_LABEL/$base → ./$base"
done
shopt -u nullglob dotglob

# -------- runtime docs: kb-docs/ (before setup/ goes away) --------

KB_DOCS="$PROJECT_ROOT/kb-docs"
copied=0
while IFS= read -r src; do
  [ -n "$src" ] || continue
  name="$(basename "$src")"
  mkdir -p "$KB_DOCS" || _fail "could not create kb-docs/"
  [ -e "$KB_DOCS/$name" ] && continue
  cp -p "$src" "$KB_DOCS/$name" || _fail "could not copy $name into kb-docs/"
  copied=$((copied + 1))
done < <(_module_sources)
if [ -d "$KB_DOCS" ]; then
  echo "📚 kb-docs/: $copied instruction module(s) copied from setup/, existing files kept"
else
  echo "⚠️  no instruction modules found in $SETUP_DIR — kb-docs/ is missing."
  echo "   Copy knowledge-base/[0-9][0-9]_*.md and README.md from the engine repository into kb-docs/."
fi

# -------- cleanup --------

# Try to remove knowledge-base (should be empty after move; tolerate leftovers
# like __pycache__ that re-appeared between scan and removal)
if [ -d "$KB_DIR" ]; then
  remaining=$(find "$KB_DIR" -mindepth 1 ! -name '__pycache__' ! -path '*/__pycache__/*' | wc -l | tr -d ' ')
  if [ "$remaining" = "0" ]; then
    rm -rf "$KB_DIR"
    echo "🧹 removed empty $KB_LABEL/"
  else
    echo "⚠️  $KB_LABEL/ still holds:"
    find "$KB_DIR" -mindepth 1 -maxdepth 1 | sed 's/^/     /'
    echo "   Move out what you still need (see the warnings above), then remove it yourself."
  fi
fi

# Promote double-click launchers from shell/ up to the project root.
# After this, shell/ contains only POSIX *.sh wrappers, and Finder/Explorer-
# friendly *.command / *.bat files live one level up where they are
# discoverable.
if [ -d "$PROJECT_ROOT/shell" ]; then
  promoted=0
  shopt -s nullglob
  for launcher in "$PROJECT_ROOT/shell"/*.command "$PROJECT_ROOT/shell"/*.bat; do
    base="$(basename "$launcher")"
    target="$PROJECT_ROOT/$base"
    if [ -e "$target" ]; then
      # Same name already at root — skip (do not overwrite)
      continue
    fi
    mv "$launcher" "$target"
    chmod +x "$target" 2>/dev/null || true
    promoted=$((promoted + 1))
  done
  shopt -u nullglob
  if [ "$promoted" -gt 0 ]; then
    echo "📌 promoted $promoted double-click launcher(s) from shell/ to project root"
  fi
fi

# Drop stray duplicates of *.sh from the project root that should live only
# in shell/. The agent (or the user) sometimes copies these — finalize cleans
# up so the final layout is canonical.
for name in watcher.sh reindex.sh lint.sh doctor.sh export.sh import.sh \
            install-hooks.sh _kbpy.sh finalize.sh install.sh; do
  if [ -f "$PROJECT_ROOT/$name" ] && [ -f "$PROJECT_ROOT/shell/$name" ]; then
    if cmp -s "$PROJECT_ROOT/$name" "$PROJECT_ROOT/shell/$name"; then
      rm -f "$PROJECT_ROOT/$name"
      echo "🧹 removed duplicate ./$name (canonical copy lives at shell/$name)"
    fi
  fi
done

# Make the launchers executable in their new location
chmod +x "$PROJECT_ROOT"/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/*.command 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/*.command 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/hooks/* 2>/dev/null || true

# Claude Code reads CLAUDE.md, not AGENTS.md. A one-line import is the
# portable bridge (a symlink breaks on Windows).
_write_claude_md() {
  local dest="$PROJECT_ROOT/CLAUDE.md"
  if [ -e "$dest" ]; then
    echo "ℹ️  CLAUDE.md already exists — left untouched"
    return 0
  fi
  printf '%s\n' '@AGENTS.md' > "$dest"
  echo "✅ wrote CLAUDE.md (@AGENTS.md)"
}

create_claude="no"
if [ "$CLAUDE_MD" = "yes" ]; then
  create_claude="yes"
elif [ "$CLAUDE_MD" = "no" ]; then
  create_claude="no"
elif [ "$PRIMARY_AGENT" = "claude-code" ]; then
  echo "ℹ️  kb.config.yml sets index.primary_agent: claude-code"
  create_claude="yes"
else
  echo ""
  echo "Claude Code reads CLAUDE.md, not AGENTS.md."
  echo "If you work in Claude Code, I can create a one-line CLAUDE.md that imports AGENTS.md."
  echo "(Non-interactive runs: pass --claude-md or --no-claude-md.)"
  printf "Use Claude Code and create CLAUDE.md? [y/N] "
  ans=""
  read -r ans || true
  case "$ans" in
    y|Y|yes|YES) create_claude="yes" ;;
    *) create_claude="no" ;;
  esac
fi
if [ "$create_claude" = "yes" ]; then
  _write_claude_md
fi

# Remove the original setup/ folder last: until here --resume can still be
# run from setup/shell/. A failure is only a leftover, not a partial finalize.
if [ "$KEEP_SETUP" = false ]; then
  if [ -d "$SETUP_DIR" ] && [ "$SETUP_DIR" != "$PROJECT_ROOT" ]; then
    if rm -rf "$SETUP_DIR" 2>/dev/null; then
      echo "🧹 removed setup/"
    else
      echo "⚠️  could not remove $SETUP_DIR completely — delete it yourself."
    fi
  fi
else
  echo "ℹ️  setup/ kept on disk (--keep-setup)"
fi

rm -f "$JOURNAL"
APPLYING=false

echo ""
echo "✅ Finalization complete."
if [ -d "$BACKUP_DIR" ]; then
  echo "   Project-root entries you had before are in ${BACKUP_DIR#"$PROJECT_ROOT"/}/."
fi
echo ""
echo "Project root now contains the deployed base. Quick sanity check:"
echo "  ls $PROJECT_ROOT"
echo ""
echo "Next: open START_HERE.md and follow the instructions."
echo "Git users (Full mode): bash shell/install-hooks.sh installs the post-commit reindex hook."
