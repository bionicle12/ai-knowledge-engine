#!/usr/bin/env bash
# finalize.sh — POST-deploy flattening helper.
#
# Run this AFTER the agent has fully deployed the knowledge base inside
# <project-root>/knowledge-base/. This script promotes the deployed base
# from knowledge-base/ up to the project root, then removes the now-empty
# knowledge-base/ folder and the original setup/ folder.
#
# Layout BEFORE finalize:
#   my-project/
#   ├── setup/                   ← upstream instructions (source)
#   │   └── shell/finalize.sh    ← this file
#   └── knowledge-base/          ← deployed base (agent-built)
#       ├── AGENTS.md, kb.config.yml...
#       ├── scripts/, raw/, knowledge/, ...
#       └── reindex.sh, etc.
#
# Layout AFTER finalize:
#   my-project/
#   ├── AGENTS.md, kb.config.yml, START_HERE.md, ...
#   ├── scripts/, shell/, templates/, examples/
#   ├── raw/, knowledge/, processed/, assets/, ...
#   ├── reindex.sh, watcher.sh, watcher-start.command, ...
#   └── (no setup/, no knowledge-base/)
#
# Usage:
#   bash setup/shell/finalize.sh
#
# Optional flags:
#   --kb-dir <path>   override the deployed base location (default: ./knowledge-base)
#   --dry-run         print what would happen without touching anything
#   --keep-setup      do NOT delete setup/ at the end (useful if you want to
#                     re-read the original instructions later)
#   --force           proceed even if the project root contains conflicting files
#   --claude-md       write a one-line CLAUDE.md (`@AGENTS.md`) without asking
#   --no-claude-md    skip the Claude Code / CLAUDE.md question
#
# Exit codes:
#   0 — finalized successfully
#   1 — refused (preconditions not met)
#   2 — partial (some moves failed; project may be in inconsistent state)

set -euo pipefail

KB_DIR=""
DRY_RUN=false
KEEP_SETUP=false
FORCE=false
CLAUDE_MD=""   # "" = ask; yes/no = explicit

while [ $# -gt 0 ]; do
  case "$1" in
    --kb-dir)
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
    --claude-md)
      CLAUDE_MD="yes"
      shift
      ;;
    --no-claude-md)
      CLAUDE_MD="no"
      shift
      ;;
    -h|--help)
      sed -n '1,45p' "$0"
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

# Resolve the deployed knowledge-base location
if [ -n "$KB_DIR" ]; then
  KB_DIR="$(cd "$KB_DIR" && pwd)"
else
  KB_DIR="$PROJECT_ROOT/knowledge-base"
fi

echo "🔧 finalize.sh"
echo "   project root:    $PROJECT_ROOT"
echo "   setup dir:       $SETUP_DIR"
echo "   knowledge-base:  $KB_DIR"
echo "   dry-run:         $DRY_RUN"
echo "   keep-setup:      $KEEP_SETUP"
echo "   force:           $FORCE"
echo ""

# -------- preconditions --------

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
  echo "   Run scripts/kb_doctor.py inside knowledge-base/ first to diagnose." >&2
  exit 1
fi

if [ "$KB_DIR" = "$PROJECT_ROOT" ]; then
  echo "❌ Refusing: knowledge-base equals project root — already flat." >&2
  exit 1
fi

# Conflict check: would moving overwrite anything important?
conflicts=()
shopt -s nullglob dotglob
for entry in "$KB_DIR"/*; do
  base="$(basename "$entry")"
  case "$base" in
    knowledge-base|setup|.git|.venv) continue ;;
  esac
  if [ -e "$PROJECT_ROOT/$base" ]; then
    conflicts+=("$base")
  fi
done
shopt -u nullglob dotglob

if [ ${#conflicts[@]} -gt 0 ] && [ "$FORCE" = false ]; then
  echo "❌ Refusing: these entries already exist at $PROJECT_ROOT and would be overwritten:" >&2
  for c in "${conflicts[@]}"; do echo "   - $c" >&2; done
  echo "   Re-run with --force to overwrite, or move them aside manually." >&2
  exit 1
fi

# -------- move payload --------

moved=0
shopt -s nullglob dotglob
for entry in "$KB_DIR"/*; do
  base="$(basename "$entry")"
  case "$base" in
    knowledge-base|setup) continue ;;
  esac
  if [ "$DRY_RUN" = true ]; then
    echo "🔸 would move: knowledge-base/$base → ./$base"
  else
    if [ -e "$PROJECT_ROOT/$base" ] && [ "$FORCE" = true ]; then
      rm -rf "$PROJECT_ROOT/$base"
    fi
    mv "$entry" "$PROJECT_ROOT/$base"
    echo "✅ moved knowledge-base/$base → ./$base"
    moved=$((moved + 1))
  fi
done
shopt -u nullglob dotglob

# -------- cleanup --------

if [ "$DRY_RUN" = true ]; then
  echo ""
  echo "🔸 would remove (knowledge-base): $KB_DIR"
  if [ "$KEEP_SETUP" = false ]; then
    echo "🔸 would remove (setup):          $SETUP_DIR"
  fi
  if [ "$CLAUDE_MD" = "yes" ]; then
    echo "🔸 would write:                   ./CLAUDE.md  (@AGENTS.md)"
  else
    echo "🔸 would ask:                     create CLAUDE.md for Claude Code?"
  fi
  echo ""
  echo "Dry-run complete. Re-run without --dry-run to apply."
  exit 0
fi

# Try to remove knowledge-base (should be empty after move; tolerate leftovers
# like __pycache__ that re-appeared between scan and removal)
if [ -d "$KB_DIR" ]; then
  remaining=$(find "$KB_DIR" -mindepth 1 ! -name '__pycache__' ! -path '*/__pycache__/*' | wc -l | tr -d ' ')
  if [ "$remaining" = "0" ]; then
    rm -rf "$KB_DIR"
    echo "🧹 removed empty knowledge-base/"
  else
    echo "⚠️  knowledge-base/ has $remaining leftover entries:"
    find "$KB_DIR" -mindepth 1 -maxdepth 2 | sed 's/^/     /'
    echo "   Inspect and remove manually."
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
for name in watcher.sh reindex.sh lint.sh doctor.sh finalize.sh install.sh; do
  if [ -f "$PROJECT_ROOT/$name" ] && [ -f "$PROJECT_ROOT/shell/$name" ]; then
    if cmp -s "$PROJECT_ROOT/$name" "$PROJECT_ROOT/shell/$name"; then
      rm -f "$PROJECT_ROOT/$name"
      echo "🧹 removed duplicate ./$name (canonical copy lives at shell/$name)"
    fi
  fi
done

# Remove the original setup/ folder unless told otherwise
if [ "$KEEP_SETUP" = false ]; then
  if [ -d "$SETUP_DIR" ]; then
    rm -rf "$SETUP_DIR"
    echo "🧹 removed setup/"
  fi
else
  echo "ℹ️  setup/ kept on disk (--keep-setup)"
fi

# Make the launchers executable in their new location
chmod +x "$PROJECT_ROOT"/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/*.command 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/*.command 2>/dev/null || true

# Claude Code reads CLAUDE.md, not AGENTS.md. A one-line import is the
# portable bridge (a symlink breaks on Windows). Ask unless the caller
# already decided via --claude-md / --no-claude-md.
_write_claude_md() {
  local dest="$PROJECT_ROOT/CLAUDE.md"
  if [ -e "$dest" ]; then
    echo "ℹ️  CLAUDE.md already exists — left untouched"
    return 0
  fi
  printf '%s\n' '@AGENTS.md' > "$dest"
  echo "✅ wrote CLAUDE.md (@AGENTS.md)"
}

create_claude=""
if [ "$CLAUDE_MD" = "yes" ]; then
  create_claude="yes"
elif [ "$CLAUDE_MD" = "no" ]; then
  create_claude="no"
else
  echo ""
  echo "Claude Code reads CLAUDE.md, not AGENTS.md."
  echo "If you work in Claude Code, I can create a one-line CLAUDE.md that imports AGENTS.md."
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

echo ""
echo "✅ Finalization complete."
echo ""
echo "Project root now contains the deployed base. Quick sanity check:"
echo "  ls $PROJECT_ROOT"
echo ""
echo "Next: open START_HERE.md and follow the instructions."
