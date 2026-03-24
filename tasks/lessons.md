# Lessons Learned

## 2026-03-23 ChallengeBoard commits must not include Co-Authored-By Claude trailer
**Pattern**: Default commit style appends `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`. For the ChallengeBoard project, this can break Vercel deployment auth.
**Rule**: Never include the Co-Authored-By trailer on challengeboard commits. Commit using only Gerald's git identity. Note is saved in project memory at `C:/Users/geral/.claude/projects/c--challengeboard/memory/MEMORY.md`.

## 2026-03-23 System-level skills must be in ~/.claude/skills/
**Pattern**: Used `Skill` tool for `session-commit` but it failed — skill only existed in `C:/AIAssistant/skills/`, not registered globally.
**Rule**: Any skill that should work across all projects must be placed at `~/.claude/skills/<name>/SKILL.md`. Project-specific skill directories are not discovered globally.
