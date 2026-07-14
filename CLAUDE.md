# Starting a coding task
- All work happens on a logically-named branch — always, no exceptions. The
  global rule puts that branch in a fresh worktree; this repo's exception, for
  changes under `claude-config/`, is ONLY that the branch lives in the main
  checkout instead of a separate worktree. Nothing else about the workflow changes.
  - Why the exception: `claude-config/` files are live-symlinked into `~/.claude`
    (CLAUDE.md, settings.json, statusline-command.sh), so they can only be tested
    via their live effect on the running Claude session — a worktree's copies
    would not be the loaded config.
  - So: create a new descriptively-named branch in the main checkout (unless it is
    already on a non-main branch whose name/history continue this work). Never
    work directly on `main`; confirm the checkout is on `main` before branching,
    to avoid clobbering another agent's in-progress work.
- The commit-as-you-go rule applies in full here — commit in small logical units
  as you work, never in one lump at the end. This repo grants no exception to it.
- Skill directories are also symlinked into `~/.claude/skills/`, but the worktree
  exception does NOT extend to them: an agent can test-run a skill from its
  worktree-local copy, so skill changes follow the normal worktree rule.
