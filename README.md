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

Symlink or copy individual skill directories into `~/.claude/skills/` to make them available globally, or into a project's `.claude/skills/` to scope them to that repo:

```bash
ln -s ~/personal-claude-skills/some-skill ~/.claude/skills/some-skill
```

## Adding a new skill

1. Create a new directory at the repo root named for the skill.
2. Add a `SKILL.md` with frontmatter (`name`, `description`) and clear step-by-step instructions.
3. Keep instructions focused — link out to `references/` for background material Claude only needs occasionally.
4. Test it locally before committing (symlink into `~/.claude/skills/`, restart Claude Code, invoke it).

## License

Personal use; no license granted for reuse unless stated otherwise in an individual skill's directory.
