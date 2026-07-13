#!/usr/bin/env bash
set -euo pipefail

# Symlink personal Claude setup from this repo into ~/.claude/.
# Idempotent: correct symlinks are left as-is; pre-existing real files are backed up.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/.install-backup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$CLAUDE_DIR"

link() {
  local src="$1" dest="$2"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    echo "ok:      $dest"
    return
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    mkdir -p "$BACKUP_DIR"
    mv "$dest" "$BACKUP_DIR/"
    echo "backup:  $dest -> $BACKUP_DIR/"
  fi
  ln -s "$src" "$dest"
  echo "linked:  $dest -> $src"
}

link "$REPO_DIR/claude-config/CLAUDE.md"             "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/claude-config/settings.json"         "$CLAUDE_DIR/settings.json"
link "$REPO_DIR/claude-config/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"

# Skills live as individual top-level directories in this repo (see README.md),
# each containing a SKILL.md. Symlink each one into ~/.claude/skills/.
mkdir -p "$CLAUDE_DIR/skills"
for skill_dir in "$REPO_DIR"/*/; do
  skill_name="$(basename "$skill_dir")"
  [ "$skill_name" = "claude-config" ] && continue
  [ -f "$skill_dir/SKILL.md" ] || continue
  link "${skill_dir%/}" "$CLAUDE_DIR/skills/$skill_name"
done
