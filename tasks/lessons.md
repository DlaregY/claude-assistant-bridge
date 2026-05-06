# Lessons Learned

## 2026-03-24 PostgreSQL cannot change function return type via CREATE OR REPLACE
**Pattern**: Added `last_sign_in_at` column to two admin RPC functions using `CREATE OR REPLACE`. Migration failed with `cannot change return type of existing function (SQLSTATE 42P13)`.
**Rule**: When modifying a Postgres function's return columns (or adding new OUT parameters), always `DROP FUNCTION IF EXISTS <name>(<arg types>)` before the `CREATE OR REPLACE`. This applies to both return column additions and parameter signature changes.

## 2026-03-23 ChallengeBoard commits must not include Co-Authored-By Claude trailer
**Pattern**: Default commit style appends `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`. For the ChallengeBoard project, this can break Vercel deployment auth.
**Rule**: Never include the Co-Authored-By trailer on challengeboard commits. Commit using only Gerald's git identity. Note is saved in project memory at `C:/Users/geral/.claude/projects/c--challengeboard/memory/MEMORY.md`.

## 2026-03-23 System-level skills must be in ~/.claude/skills/
**Pattern**: Used `Skill` tool for `session-commit` but it failed — skill only existed in `C:/AIAssistant/skills/`, not registered globally.
**Rule**: Any skill that should work across all projects must be placed at `~/.claude/skills/<name>/SKILL.md`. Project-specific skill directories are not discovered globally.

## 2026-03-27 Verify custom domain is linked to Vercel project after initial setup
**Pattern**: Domain `apartmentsetuplab.com` was registered through Vercel and DNS pointed at Vercel nameservers, but the domain was never added to the Vercel project. Pushes deployed successfully but the live site served stale content.
**Rule**: After setting up a new Vercel project with a custom domain, verify the domain appears in the project's domain list (`vercel domains ls` or check the project API). Registration and DNS alone are not enough — the domain must be explicitly added to the project.
