# Lessons Learned

## 2026-07-10 Never let a background service spawn a UAC/RunAs prompt on a loop
**Pattern**: `webhook_server.py`'s tunnel health monitor called `_restart_cloudflared()`, which fell back to `Start-Process -Verb RunAs` when the non-elevated `Restart-Service` failed. On Longfellow the cloudflared quick-tunnel was chronically "unhealthy" (Surfshark VPN mangles DNS → `api.telegram.org` won't resolve), so this fired a UAC prompt every ~2 minutes. Each UAC switches Windows to the **secure desktop**, which grabs ALL keyboard/mouse/mic input system-wide — presenting as escalating, whole-system input lag + phantom clicks that got worse the longer the machine ran. Diagnosed by tailing `logs/webhook.log` (restart storm) while CPU sat idle (input-grab, not CPU-bound).
**Rule**: A headless/background service must NEVER trigger elevation (`-Verb RunAs`, UAC) automatically, especially in a retry loop. If an action needs admin and the process isn't elevated, log and give up — do not prompt. If a service genuinely needs to restart another service, run it as an already-elevated service or grant scoped non-interactive rights; never pop consent UI. Also guard health loops so an empty/unresolved target can't drive infinite restarts.

## 2026-07-10 pythonw.exe has no console → sys.stdout/stderr are None → print() crashes it
**Pattern**: Switched the CAB Task Scheduler action from `python` to `pythonw` (to kill a startup console window). The task kept exiting with `LastTaskResult: 1`. Cause: Task Scheduler launches `pythonw` with no console, so `sys.stdout`/`sys.stderr` are `None`; the first `print()` in `startup()` (and uvicorn's stdout logging) raised and killed the process. Under plain `python` it ran fine, which masked the issue.
**Rule**: Any script meant to run under `pythonw` (or any no-console/headless launch) must guard stdout/stderr at import time: `if sys.stdout is None: sys.stdout = open(os.devnull, 'w')` (same for stderr), placed before any `print`/logging-to-stdout. Route real logs to a file. `pythonw` also hides crashes (no window), so always verify via the log/`LastTaskResult`, not by "no error popped up."

## 2026-07-10 Editing scheduled tasks needs elevation; a self-matching WMI query is a false positive
**Pattern**: `Set-ScheduledTask` / `schtasks /Change` returned "Access is denied" from the non-elevated agent shell (had Gerald run the one-liner in an admin prompt). Separately, `Get-CimInstance Win32_Process | Where CommandLine -match 'RunAs'` kept "finding" a RunAs process — it was matching the very PowerShell command running the query (its own command line contains the string `RunAs`).
**Rule**: Task Scheduler edits (`Set-ScheduledTask`, `schtasks /Change`, `Disable-ScheduledTask`) generally require an elevated shell on Longfellow — hand Gerald the exact admin command. When grepping `Win32_Process` command lines for a token, exclude the current PID (or a distinctive marker) so the query doesn't self-match.

## 2026-05-06 Don't hardcode versioned Claude exe paths — use auto-detection
**Pattern**: `.env` had `CLAUDE_EXE` pointing to a specific versioned `claude.exe`. After Claude auto-updated, that version was deleted and the server started returning `FileNotFoundError`.
**Rule**: Never set `CLAUDE_EXE` in `.env` on Longfellow. The `_find_claude_windows()` auto-detection resolves the current version on each server start. If `.env` overrides it, the override wins and will eventually go stale.

## 2026-05-06 .cmd files require shell=True (or cmd /c) in subprocess on Windows
**Pattern**: Switched `CLAUDE_EXE` to `claude.cmd` thinking it was a stable shim. subprocess.run with a list of args doesn't invoke batch files correctly without `shell=True`, causing args to be silently dropped and Claude returning "Input must be provided via stdin or prompt argument".
**Rule**: When spawning a `.cmd` or `.bat` file via subprocess on Windows, either use `shell=True` or invoke it as `["cmd", "/c", "file.cmd", ...]`. Better: point directly at the `.exe` or `node cli.js`.

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
