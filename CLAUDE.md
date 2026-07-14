# Starting a coding task
- Exception to the global "fresh worktree" rule, for changes under `claude-config/`:
  those files are live-symlinked into `~/.claude` (CLAUDE.md, settings.json,
  statusline-command.sh), and a worktree's copies would not be the live, loaded config —
  so they can only be tested via their live effect on the running Claude session. Work
  in-place on a new branch in the main checkout instead of a worktree. First confirm the
  main checkout is on `main` (or already on a branch continuing this work) to avoid
  clobbering another agent's in-progress work.
- Skill directories are also symlinked into `~/.claude/skills/`, but this exception does
  NOT extend to them: an agent can test-run a skill from its worktree-local copy, so skill
  changes follow the normal worktree rule.
