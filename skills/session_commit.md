---
name: session-commit
description: "Unified end-of-session SOP for Zo, Longfellow, and VPS. Persists state (git, Hub, memory, lessons) and optionally deploys. Triggers: 'commit', 'session commit', 'wrap up', 'end session', 'goodnight' (autonomous), 'checkpoint commit' (light)."
version: 2.0.0
last-updated: 2026-04-20
canonical-source: https://raw.githubusercontent.com/DlaregY/zo-workspace-backup/master/Skills/session-commit/SKILL.md
compatibility: Runs on Zo Computer, Longfellow (Windows / CAB), and Hetzner VPS (CAB).
metadata:
  author: gerald.zo.computer
---

# Session Commit

End-of-session SOP. Persists meaningful context so the next session can pick up cleanly.

## 0. Trigger detection & mode

Parse the trigger phrase:

| Phrase | MODE | AUTONOMOUS |
|---|---|---|
| `commit`, `session commit`, `wrap up`, `end session` | `full` | false |
| `goodnight`, `gn`, `good night`, `nighty night` | `full` | **true** |
| `checkpoint commit`, `checkpoint` | `checkpoint` | false |

- `MODE=full` runs every applicable step.
- `MODE=checkpoint` runs only git + Hub + terse confirmation, then suggests `/compact`. Used when locking in progress mid-session without ending the chat.
- `AUTONOMOUS=true` skips all pauses (Step 2, loose-ends review) and executes straight through.

## 1. Environment detection

Run once at the start. Sets `ENV`:

```
if [ -f /home/workspace/CLAUDE.md ] && [ -d /home/.z ]; then ENV=zo
elif [ -d /home/claude/claude-assistant-bridge ]; then ENV=vps
elif command -v powershell.exe >/dev/null 2>&1 && powershell.exe -NoProfile -Command "Test-Path C:/AIAssistant" | grep -q True; then ENV=longfellow
else ENV=unknown
fi
```

Workspace roots per env:
- `zo` → `/home/workspace`
- `vps` → `/home/claude/claude-assistant-bridge`
- `longfellow` → `C:/AIAssistant`

## 2. Version check (always, fast, non-blocking)

Fetch the `canonical-source` URL and compare `version:` in its frontmatter to the local one. If remote > local, print a one-line warning:

> ⚠️ session-commit v2.1.0 available (local is v2.0.0). Run with `--sync-skill` to pull.

Skip silently if network unavailable or fetch fails. Never block the commit on this.

## 3. Pre-Commit Review

**Skip entirely if `MODE=checkpoint` or `AUTONOMOUS=true`.**

a. **Reconstruct the session narrative** — 3–6 bullets: attempted, completed, deferred.

b. **Scan objective signals (env-branched)** — run in parallel:
   - `zo`:
     - `git -C /home/workspace status --short`
     - Each known project repo's `git status --short` (Projects/erin, save-my-run, apartmentsetuplab, etc.)
     - `curl -s 'http://localhost:3099/hub/api/items?status=open' | jq '[.[] | select(.updated_at > (now - 86400 | todate))]'` — items touched in last 24h
   - `longfellow`:
     - `git -C C:/AIAssistant status --short`
     - Read `C:/AIAssistant/context/active-session.md` for in-flight task state
   - `vps`:
     - `git -C /home/claude/claude-assistant-bridge status --short`
   - All envs: scan conversation for "TODO", "follow up", "later", "we should also", "don't forget".

c. **Present loose ends + next steps** — if any found, pause:

   > **Session Review**
   > Accomplished: [bullets]
   > Loose ends: [list]
   > Suggested next steps: [list]
   >
   > Tackle any of these, or wrap up now?

   If "skip" / "wrap up" / "just commit" → proceed. Otherwise engage, then re-run from Step 3 when done.

d. If nothing notable — skip pause, note briefly, continue.

## 4. Update project context files

Update the active project's `AGENTS.md` with any new rules, preferences, or state changes discovered this session. Applies across all envs.

- `zo`: e.g. `ftt-config/AGENTS.md`, `Projects/Goldstein/AGENTS.md`
- `longfellow`: `C:/AIAssistant/CLAUDE.md`, relevant context files
- `vps`: `/home/claude/claude-assistant-bridge/CLAUDE.md`

## 5. Project repo commit + push

For each directory touched this session that has its own `.git` (separate from the workspace repo):

1. `git -C <dir> status --porcelain` — if empty, skip.
2. `git -C <dir> add <specific files>` (avoid `-A` to prevent secret leakage).
3. `git -C <dir> commit -m "Session commit: <summary>"` (checkpoint: `"Checkpoint: <summary>"`).
4. `git -C <dir> push`.
5. Report hash + push status. If push fails, report but continue.

**Push is mandatory** — some project agents do `git fetch && reset --hard` on their next run.

### Known project repos

| Project | Dir (zo) | Separate git? |
|---|---|---|
| Erin News Feed | `Projects/erin/` | Yes — `DlaregY/erin.geraldnorby.com` |
| Save My Run | `Projects/save-my-run/` | Check at runtime |
| Apartment Setup Lab | `Projects/apartmentsetuplab/repo/` | Yes — submodule |
| cfareview | `Projects/cfareview/` | Check at runtime |
| ChallengeBoard | `Projects/challengeboard/` | Check at runtime |
| Goldstein | `Projects/Goldstein/` | No — workspace repo |
| FTT | `ftt-config/` | No — workspace repo |

## 6. Workspace repo commit + push [ENV=zo only]

**Always run on Zo.** The workspace repo (`/home/workspace`) holds the majority of state.

1. `git -C /home/workspace status --short` — if empty, skip.
2. Review staged changes. Verify no secret files (`.env`, `credentials.json`, unencrypted tokens).
3. If submodules were updated in Step 5, their new SHAs need to be registered here:
   `git -C /home/workspace add Projects/apartmentsetuplab` (or relevant submodule path).
4. `git -C /home/workspace add <files>` (prefer specific paths; `-A` only if changes are reviewed).
5. `git -C /home/workspace commit -m "Session commit: <summary>"`.
6. `git -C /home/workspace push` → `zo-workspace-backup`.

If push fails, report and continue. The nightly 3:11 AM backup will retry.

## 7. CAB deploy to VPS [conditional]

Run if this session modified CAB code (`webhook_server.py`, `runner.py`, `setup.py`, `skills/*.md`, `services/*.py`, or any imported module):

- `ENV=longfellow`: always run if Step 5 committed the CAB repo.
- `ENV=zo`: run only if the session operated on the CAB codebase remotely (rare).
- `ENV=vps`: skip — you are the VPS.

```bash
ssh root@178.156.228.92 "cd /home/claude/claude-assistant-bridge && git pull && systemctl restart claude-assistant-bridge"
```

Report pull + restart status. If SSH fails, report and continue.

## 8. Global memory

**Skip if `MODE=checkpoint`.**

Append *universal* facts (cross-project, cross-session) to the global memory file:

- `zo` → `/home/workspace/MEMORY.md`
- `longfellow` → `C:/Users/geral/.claude/projects/C--AIAssistant/memory/MEMORY.md`
- `vps` → `/home/claude/MEMORY.md` (create if missing)

Edit in place. Do not duplicate existing entries. Project-specific details stay in `<project>/AGENTS.md`.

## 9. Hub sync [ENV=zo only]

**Skip on other envs — they don't have Hub access.**

Fetch and sync.

a. **Resolve completed items**:
```bash
curl -s -X POST http://localhost:3099/hub/api/items/update \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $HUB_API_SECRET" \
  --data '{"id": <id>, "status": "resolved", "resolved_note": "<what was done>"}'
```

b. **Add new follow-ups** (for each new task/bug/idea discovered):
```bash
curl -s -X POST http://localhost:3099/hub/api/items \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $HUB_API_SECRET" \
  --data '{"project_slug": "<slug>", "title": "<title>", "type": "<type>", "severity": "medium", "source": "session-commit"}'
```

Default unknown project → `inbox`. Default severity → `medium`.

Use `bash -lc` on Zo if `HUB_API_SECRET` isn't loaded in the shell (it's sourced via `BASH_ENV=~/.zo_secrets`).

If Hub API unreachable, report and continue.

## 10. Lessons critique

**Skip if `MODE=checkpoint`.**

Briefly assess: what went well, what was wasted, what could be better. If a reusable lesson emerged, classify and save:

**Is the lesson general or project-specific?**

- **General** (applies across projects / to Gerald's workflow broadly):
  - `zo` → append to `/home/workspace/LESSONS.md`
  - `longfellow` → append to `C:/AIAssistant/LESSONS.md`
  - `vps` → append to `/home/claude/LESSONS.md`
- **Project-specific** → append to `<project>/LESSONS.md` (create if missing).

Format:

```markdown
## [YYYY-MM-DD] Brief title
**Pattern**: What happened.
**Rule**: What to do differently next time.
```

If no reusable lesson emerged, skip. Not every session produces one.

## 11. Confirmation

### MODE=full

Respond with a bulleted summary:

> **Session committed.** (env: zo)
> - **Project repos**: Committed `<hash>` to erin (pushed) | skipped save-my-run (clean)
> - **Workspace repo**: Committed `<hash>` (pushed to zo-workspace-backup)
> - **CAB deploy**: n/a (no CAB changes) | Deployed + restarted
> - **Docs**: Updated ftt-config/AGENTS.md, MEMORY.md
> - **Hub**: Resolved 3 items, added 2 follow-ups
> - **Lessons**: Saved general lesson "Verify port 22 before assuming host is down"
> - **Version check**: current (v2.0.0)

If `AUTONOMOUS=true` and Step 3 was skipped, include a **Loose ends for next session** section with any signals that were detected but not surfaced.

If any step failed, report explicitly.

### MODE=checkpoint

Single line, terse:

> ✅ Checkpoint `<hash>` (project + workspace pushed, hub synced). Consider `/compact`.

## 12. Sync command (manual, rare)

If the user invokes `session commit --sync-skill` or `sync session-commit skill`:

1. Fetch `canonical-source` URL.
2. Parse remote `version:`. If remote <= local, report "already up to date" and stop.
3. If `ENV=zo` and local `SKILL.md` has uncommitted changes, **refuse**: "Local skill has uncommitted edits. Commit or discard first."
4. Overwrite local `SKILL.md` with remote content.
5. If `ENV=zo`, propagate to other environments:
   - `scp` new SKILL.md to Longfellow: `scp /home/workspace/Skills/session-commit/SKILL.md longfellow:C:/AIAssistant/skills/session_commit.md`
   - `scp` to VPS: `scp /home/workspace/Skills/session-commit/SKILL.md root@178.156.228.92:/home/claude/claude-assistant-bridge/skills/session_commit.md`
6. Report which environments got synced and any failures.

## Execution Notes

| Action | Zo Chat | Claude Code |
|---|---|---|
| Edit MEMORY.md / AGENTS.md | `edit_file_llm` | `Edit` |
| Git | `run_bash_command` | `Bash` |
| Hub API writes | `bash -lc` + `Authorization: Bearer $HUB_API_SECRET` | Same |
| SSH to VPS / Longfellow | `run_bash_command` | `Bash` |
| Read files | `read_file` | `Read` |
