---
name: session-commit
description: "End-of-session procedure for persisting context, committing code, deploying, and recording lessons. Triggered by: 'commit', 'wrap up', 'end session', 'goodnight' (and variations)."
compatibility: Created for Longfellow (Windows / Claude Assistant Bridge)
metadata:
  author: gerald.longfellow
---
# Session Commit

Persist all meaningful context from the current session. If the session was trivial (quick Q&A, no state changes, no new facts), skip to Step 8 and confirm that nothing needed persisting.

**Trigger detection**: This skill activates when the user says "commit", "wrap up", "end session", "goodnight", "good night", "gn", or "nighty night."

**Autonomous mode**: If the trigger word is any variation of "goodnight", set `AUTONOMOUS=true`. In autonomous mode, skip the pause in Step 0d — the user is going to bed. Execute all steps without waiting for input, then summarize at the end.

## Steps

### 0. Pre-Commit Review

Before persisting anything, take stock of the session and surface unfinished business.

**Skip this entire step if `AUTONOMOUS=true`.** Instead, silently note any loose ends and include them in the confirmation summary (Step 9) so the user sees them next session.

a. **Reconstruct the session narrative** — From conversation context, summarize in 3–6 bullets: what was attempted, what was completed, and what was explicitly deferred or left open.

b. **Scan objective signals** — Run the following and cross-reference against the session narrative:
   - `git -C C:/AIAssistant status --short` — any staged/unstaged changes that were not committed
   - Read `C:/AIAssistant/context/active-session.md` — check "Current Task" and "Key Decisions" for items touched this session but possibly incomplete
   - Scan the conversation for phrases like "TODO", "follow up", "later", "next step", "we should also", "don't forget" — signals of deferred work

c. **Identify loose ends and next steps** — Compile a short list of:
   - **Loose ends**: Things started but not finished, errors not fully resolved, changes not committed, or tasks mentioned but never acted on
   - **Natural next steps**: Logical follow-ons that would make the session's work more complete

d. **Pause and present to Gerald** — If any loose ends or next steps were found, present them:

   > **Session Review**
   > Here's what we accomplished: [bullet list]
   >
   > Before I wrap up, I noticed a few things:
   > - **Loose ends**: [list]
   > - **Suggested next steps**: [list]
   >
   > Want to tackle any of these before I commit, or should I skip ahead and wrap up now?

   Wait for Gerald's response. If he says "skip" / "wrap up" / "just commit", proceed to Step 1. If he engages with a loose end, help him complete it, then re-run from Step 0 when that work is done.

e. **If nothing notable was found** — Skip the pause. Note briefly that the session looked clean, then proceed to Step 1.

### 1. Update Active Session — Mark In-Progress

Update `C:/AIAssistant/context/active-session.md`:
- Set **Status** to `committing`
- Set **Current Task** to `Session commit in progress`
- Set **Last Updated** to current timestamp

This signals to any crash-recovery logic that a commit was in flight.

### 2. Re-Document

Before committing, ensure documentation reflects reality:

a. Run `git diff HEAD` to see all uncommitted changes.

b. For each meaningful change, check whether any documentation files need updating:
   - `CLAUDE.md` — project context, architecture, known issues, pending items
   - `README.md` — if public-facing info changed
   - `docs/*.md` — if the changed functionality is covered there
   - Test counts in "Development Conventions" if tests were added/removed

c. Update the "Pending Items" section of `CLAUDE.md` if the session created or resolved any.

### 3. Commit

a. Run `git status` — if nothing to commit, skip to Step 5.

b. Stage all relevant changes. Prefer naming specific files over `git add -A`. Never stage secrets (`.env`, credentials).

c. Commit with a descriptive message in imperative mood, following the project's existing style:
   ```
   git commit -m "<imperative summary of session work>"
   ```

### 4. Push

```
git push
```

If push fails (auth, network), report the failure but continue. The local commit is still valuable.

### 5. Deploy to VPS

**Only if the commit touched server-side files**: `webhook_server.py`, `runner.py`, `setup.py`, `skills/*.md`, `services/*.py`, or any Python module they import.

```bash
ssh root@178.156.228.92 "cd /home/claude/claude-assistant-bridge && git pull && systemctl restart claude-assistant-bridge"
```

- If the session only touched docs or Windows-only files, skip.
- If SSH/deploy fails, report but continue.

### 6. Update Memory

Extract any *universal* facts learned this session to the memory file at `C:/Users/geral/.claude/projects/C--AIAssistant/memory/MEMORY.md`:
- New infrastructure details (IPs, ports, services)
- User preferences discovered
- Cross-project patterns

Edit in place. Do not overwrite existing content. Do not duplicate info already present. Project-specific details stay in `CLAUDE.md` or `context/*.md`.

### 7. Critique and Lessons Learned

Briefly assess the session:
- What went well?
- What was wasted effort?
- What could be improved next time?

If the critique surfaces a **reusable lesson** (mistake to avoid, better approach, user correction), append to `C:/AIAssistant/tasks/lessons.md`:

```markdown
## [YYYY-MM-DD] Brief title
**Pattern**: What happened
**Rule**: What to do differently
```

Create the file with a `# Lessons Learned` header if it doesn't exist yet.

If no reusable lesson emerged, skip this step.

### 8. Set Active Session to Idle

Update `C:/AIAssistant/context/active-session.md`:
- Set **Status** to `idle`
- Set **Last Updated** to current timestamp
- Set **Current Task** to `None — session committed.`
- Clear **Key Decisions Made** and **Pending User Questions**
- In **Recent Context**, write a 1–2 line summary of what this session accomplished (breadcrumb for next session)

### 9. Confirmation

Respond with a bulleted summary:

> **Session committed.**
> - **Git**: Committed `<hash>` — "<message>" (pushed to origin)
> - **VPS**: Deployed and restarted (or: skipped / failed)
> - **Docs**: Updated X, Y (or: no doc changes needed)
> - **Memory**: Added note about X (or: no new facts)
> - **Lessons**: Saved lesson about X (or: no new lessons)
> - **Active session**: Set to idle

If in autonomous mode and loose ends were found in Step 0, append:
> - **Loose ends for next session**: [list]

If any step failed, report it explicitly.
