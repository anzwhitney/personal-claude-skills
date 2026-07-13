# personal-claude-skills

Personal collection of [Claude Code](https://claude.com/claude-code) skills — reusable, invokable capabilities that extend how Claude works for me across projects.

## What's a skill?

A skill is a directory containing a `SKILL.md` file with instructions Claude loads on demand (via the `Skill` tool, or by typing `/skill-name`) instead of keeping them in context all the time. Good candidates for skills:

- Multi-step workflows I run often (release checklists, report generation, code review passes)
- Domain knowledge that's tedious to re-explain every session
- Conventions specific to how I want Claude to behave, not specific to any one project

## Layout

```
skill-name/
  SKILL.md          # required: frontmatter + instructions
  scripts/           # optional: helper scripts the skill can run
  references/        # optional: docs the skill can read for extra detail
```

`SKILL.md` frontmatter:

```markdown
---
name: skill-name
description: One or two sentences covering what this does AND when to use it — this is what Claude matches against, so be specific about trigger phrases and scenarios.
---

Instructions and steps go here.
```

## Installing

Run `./install.sh` to symlink every skill in this repo into `~/.claude/skills/` (and to install the personal setup files — see below). It's idempotent: safe to re-run after adding or updating a skill, and it backs up any real files it would overwrite.

To scope a single skill to one project instead, symlink it directly into that project's `.claude/skills/`:

```bash
ln -s ~/personal-claude-skills/some-skill some-project/.claude/skills/some-skill
```

## Adding a new skill

1. Create a new directory at the repo root named for the skill.
2. Add a `SKILL.md` with frontmatter (`name`, `description`) and clear step-by-step instructions.
3. Keep instructions focused — link out to `references/` for background material Claude only needs occasionally.
4. Test it locally before committing (`./install.sh`, restart Claude Code, invoke it).

## Personal setup (`claude-config/`)

Alongside skills, this repo also holds my personal Claude Code setup — `CLAUDE.md`, `settings.json`, `statusline-command.sh` — under `claude-config/`, so a new device can be brought up to my configuration with one command:

```bash
git clone <this-repo> ~/personal-claude-skills
~/personal-claude-skills/install.sh
```

`install.sh` symlinks these files into `~/.claude/`, so the repo stays the single source of truth — edits made live in `~/.claude/` (including via `/config` or by Claude itself) land directly in git. Machine-local files (`settings.local.json`, session/cache/history data) are intentionally excluded and stay real files outside the repo.

This is distinct from a project-level `CLAUDE.md` for working on this repo itself, which may be added separately.

## License

Personal use; no license granted for reuse unless stated otherwise in an individual skill's directory.
