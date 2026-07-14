#!/usr/bin/env bash
# Claude Code statusline
# Shows: active model, 5h/7d rate-limit usage (%), and context usage as a fallback
# when weekly "credits used" data is not exposed to statusline scripts.

input=$(cat)

# --- Current directory / repo ---------------------------------------------
raw_dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // empty')
cwd="${raw_dir/#$HOME/\~}"

# If we're inside a git repo, show "repo ⎇ branch" instead of the raw path.
if [ -n "$raw_dir" ] && git -C "$raw_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  repo=$(basename "$(git -C "$raw_dir" rev-parse --show-toplevel 2>/dev/null)")
  branch=$(git -C "$raw_dir" branch --show-current 2>/dev/null)
  if [ -z "$branch" ]; then
    branch=$(git -C "$raw_dir" rev-parse --short HEAD 2>/dev/null)
  fi
  location="$repo ⎇ $branch"
else
  location="$cwd"
fi

# --- Model -------------------------------------------------------------
model=$(echo "$input" | jq -r '.model.display_name // "?"')

# --- Rate limits (Claude.ai subscription usage) -------------------------
# Only present for subscribers, and only after the first API response of
# the session. There is no "credits used" field available to statusline
# scripts -- only used_percentage for the 5-hour and 7-day windows.
five_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
week_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')

usage=""
if [ -n "$five_pct" ]; then
  usage="5h:$(printf '%.0f' "$five_pct")%"
fi
if [ -n "$week_pct" ]; then
  wk="7d:$(printf '%.0f' "$week_pct")%"
  if [ -n "$usage" ]; then
    usage="$usage $wk"
  else
    usage="$wk"
  fi
fi

# Fallback when no rate-limit data is available yet (e.g. first turn of a
# session, or account without Claude.ai subscription usage reporting):
# show context window usage instead, since that's the closest real signal
# statusline scripts can access.
if [ -z "$usage" ]; then
  ctx_used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
  if [ -n "$ctx_used" ]; then
    usage="ctx:$(printf '%.0f' "$ctx_used")%"
  else
    usage="usage: n/a"
  fi
fi

# --- Auto-compact window usage -------------------------------------------
# autoCompactWindow isn't exposed in the statusline JSON, so read it from
# settings directly. Fall back to the model's actual context_window_size
# if the user hasn't set a custom autoCompactWindow.
used_tokens=$(echo "$input" | jq -r '.context_window.total_input_tokens // empty')
compact_window=$(jq -r '.autoCompactWindow // empty' ~/.claude/settings.json 2>/dev/null)
if [ -z "$compact_window" ]; then
  compact_window=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
fi

if [ -n "$used_tokens" ] && [ -n "$compact_window" ] && [ "$compact_window" != "0" ]; then
  ac_pct=$(awk -v u="$used_tokens" -v w="$compact_window" 'BEGIN { printf "%.0f", (u / w) * 100 }')
  usage="$usage ac:${ac_pct}%"
fi

# --- Compose (dim colors for terminal readability) ----------------------
if [ -n "$location" ]; then
  printf '\033[2m%s\033[0m \033[2m|\033[0m \033[2m%s\033[0m \033[2m|\033[0m \033[2m%s\033[0m' "$model" "$usage" "$location"
else
  printf '\033[2m%s\033[0m \033[2m|\033[0m \033[2m%s\033[0m' "$model" "$usage"
fi
