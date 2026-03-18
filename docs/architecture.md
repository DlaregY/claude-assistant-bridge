# Architecture

## Overview

Claude Assistant Bridge is built around a simple principle: use the tools you already have, wire them together cleanly, and get out of the way.

The system has three moving parts that run independently and communicate through files:

1. **Webhook server** — always-on HTTP server that receives Telegram messages and routes them to Claude Code
2. **Task runner** — fires every 5 minutes, checks for due or missed scheduled tasks, executes them
3. **Claude Code** — the execution engine that both the webhook server and runner invoke as a subprocess

These three components share several files:

- `tasks.json` — the schedule, managed by Claude Code in response to your natural language requests
- `run_log.jsonl` — the execution history, written by the runner and readable by Claude Code when you ask about task history
- `notes.md` — general persistent context (preferences, account info, recurring instructions), auto-maintained by the assistant
- `context/*.md` — per-project context files (paths, architecture, deployment details), auto-created and updated by the assistant

Nothing is coupled at the code level. The webhook server doesn't know the runner exists. The runner doesn't know the webhook server exists. They communicate entirely through the shared files. This means any component can fail, restart, or be replaced without affecting the others.

---

## Why Telegram

Telegram was chosen over WhatsApp, Signal, iMessage, and Discord for four concrete reasons:

**Webhook support.** Telegram's Bot API pushes messages to your server the instant you send them. The alternatives either require polling (slower, wasteful) or have no official bot API at all.

**Zero approval process.** Creating a Telegram bot takes two minutes via BotFather. WhatsApp requires Meta business account verification. iMessage has no third-party API.

**Simple authentication.** Your numeric user ID is hardcoded as the whitelist. Any message from a different ID is silently ignored. There's no OAuth flow and no tokens beyond the bot token itself.

**Free and stable.** Telegram's Bot API has been stable for years, has no rate limits that matter for personal use, and costs nothing.

---

## Why Cloudflare Tunnel

Telegram webhooks require a publicly accessible HTTPS endpoint. Your home PC doesn't have one by default — it sits behind NAT, has a dynamic IP, and has no TLS certificate.

Cloudflare Tunnel (`cloudflared`) solves all three problems in one command. It creates an encrypted tunnel from Cloudflare's edge to your local port, gives you a public HTTPS URL, and handles the TLS certificate automatically. It's free for the quick tunnel mode used here.

The tunnel URL changes on restart in quick tunnel mode. This is handled by the webhook server's startup routine, which polls cloudflared's local API (`localhost:20241/quicktunnel`) to detect the current URL and re-registers it with Telegram automatically. The user never has to update any configuration.

Quick tunnels can also go stale without warning — the hostname stops resolving while cloudflared still appears to be running. To handle this, the webhook server runs a background health monitor that checks the tunnel every 2 minutes. If the tunnel is unreachable (DNS failure, 530 error, or timeout), the monitor automatically restarts the cloudflared Windows service, detects the new tunnel URL, and re-registers the Telegram webhook. This self-healing loop means stale tunnels are recovered without user intervention, typically within 2-3 minutes.

On a Linux VPS with a static IP, Cloudflare Tunnel is optional — you can point Telegram's webhook directly at your server's IP with a real domain and a Let's Encrypt certificate. The setup guide covers both approaches.

---

## Why Windows Task Scheduler (not a daemon)

The webhook server and task runner could have been implemented as long-running Windows services. Instead, the webhook server runs as a Task Scheduler task on login, and the runner fires every 5 minutes as a separate Task Scheduler task.

This was a deliberate choice for three reasons:

**Credential access.** Windows services run as SYSTEM by default, which has no access to your user's Claude Code authentication. Running as a Task Scheduler task under your own account sidesteps this entirely.

**Simplicity.** Task Scheduler entries are visible and manageable in a UI that Windows users already have. NSSM services are less visible and harder to debug when something goes wrong.

**Separation of concerns.** The webhook server and runner are independent processes. If the runner hangs on a long task, the webhook server keeps accepting messages. If you restart the webhook server, scheduled tasks keep firing.

On Linux, `systemd` manages the webhook server (proper service lifecycle, auto-restart on failure) and `cron` manages the runner (clean, minimal, purpose-built for periodic execution).

---

## The Catch-Up System

The catch-up system solves a specific problem: your PC was off when a task was scheduled to run. What should happen when it comes back on?

The naive answer is "just run it." But that's wrong for time-sensitive tasks — a good morning message delivered at 3pm is useless. And it's potentially right for work tasks — a weekly report that was due yesterday should probably still run today.

The system resolves this with two per-task fields: `catch_up` (boolean) and `catch_up_window_hours` (number or null).

On every runner tick, for each enabled task:

1. Find the last successful run from `run_log.jsonl`
2. Calculate the most recent scheduled due time after that last run
3. If no due time exists, skip
4. If the task is more than one runner interval late (6 minutes), it's a catch-up scenario
5. Apply the task's catch-up rules: skip, catch up within window, or always catch up
6. Log the outcome regardless — `status: skipped` entries are as important as `status: success`

The log being append-only is a deliberate constraint. It means the runner's reconciliation logic always has a complete, trustworthy history. You can grep the log at any time to understand exactly what happened and when. There's no state that can be corrupted.

---

## Webhook Reliability

Telegram retries webhook deliveries when the server doesn't respond within ~60 seconds. Since Claude Code invocations can take minutes, naive request handling leads to a cascade of retries — each spawning a duplicate Claude process and flooding the user with duplicate responses.

The webhook server defends against this with three layers:

1. **Immediate response.** The webhook handler returns HTTP 200 instantly and dispatches message processing to a background `asyncio` task. Telegram sees a fast response and never retries.

2. **Update ID deduplication.** Every Telegram update has a unique `update_id`. The server tracks recently seen IDs (10-minute TTL) and silently drops duplicates. This catches any retries that arrive before the immediate response or during transient issues.

3. **Per-chat locking.** An `asyncio.Lock` per chat ID serializes message processing. If two messages arrive for the same chat in quick succession, the second waits for the first to finish. This prevents concurrent Claude Code processes from corrupting the session state.

---

## Why JSONL for the Run Log

The run log uses newline-delimited JSON (JSONL) rather than a database or a plain log file.

**vs. SQLite:** JSONL requires no schema migrations, no connection management, no query language. It's a plain text file you can open in any editor. The runner only needs to scan it sequentially to find last successful runs, which is fast enough for hundreds of tasks.

**vs. plain text logs:** JSONL is structured. Claude Code can read it and answer questions like "what failed this week?" without any parsing logic baked into the runner. The structure is the query interface.

**vs. JSON array:** An append-only file can never be in a partially-written, corrupted state. A JSON array requires reading and rewriting the entire file on every update, which creates a corruption window if the process is killed mid-write.

---

## Security Model

**Authentication:** Your Telegram user ID is the only authentication mechanism. The webhook server rejects any message not from that ID before processing begins. The ID is a number, not a secret — but the attacker would also need your bot token to send a message that appears to come from your ID, and the bot token is stored only in `.env`.

**Claude Code permissions:** The `--dangerously-skip-permissions` flag is used to allow Claude Code to run without interactive permission prompts. This is appropriate here because the only person who can send commands is you, via the authenticated Telegram channel. The flag is named to be alarming because it disables a safety guardrail — in this architecture, the Telegram authentication layer replaces that guardrail.

**Local execution:** Claude Code runs with your user account's file system permissions. It can read and write anything your user can. This is intentional — the value of the system is that Claude Code can actually do things on your machine. The tradeoff is that a compromised bot token combined with a Telegram user ID spoof would give an attacker the same access. Keep your bot token secret.

**No data leaves your machine** except the Telegram messages themselves and Claude Code's API calls to Anthropic. Tasks, logs, and configuration stay local.

---

## Cross-Platform Design

The codebase targets Windows and Linux with the same source files. Platform differences are contained in two places:

**Executable resolution (`webhook_server.py`, `runner.py`):** Both files call `_resolve_claude_exe()`, which checks the `CLAUDE_EXE` environment variable first, then auto-detects by searching known Windows installation paths, then falls back to `claude` on PATH for Linux.

**Service registration (`services/windows.py`, `services/linux.py`):** All platform-specific service management is isolated here. `setup.py` detects the OS and calls the appropriate module. The core application files have no awareness of how they are being managed as services.

This means the same `webhook_server.py` and `runner.py` files run unchanged on both platforms. A new deployment target (macOS, for example) only requires adding a `services/macos.py` module.

---

## What Claude Code Receives

Every invocation passes the user's message as a positional argument and appends a system prompt with context. For interactive messages, the system prompt includes:

```
You are a personal AI assistant for [NAME].
Current time: 2026-02-27 18:30 (America/Chicago).
Tasks file: C:/AIAssistant/tasks.json.
Run log: C:/AIAssistant/run_log.jsonl.
Keep responses concise — this is a messaging interface.

## Notes

[contents of notes.md, if any]

## Project Context

[contents of all context/*.md files, if any]

## Context Management

[instructions for auto-updating notes.md and context/ files]

## Task Management Skill

[contents of skills/task_manager.md]
```

The system prompt is passed via `--append-system-prompt`, and the user's message is passed as the positional `prompt` argument. On the first message, `--session-id <uuid>` creates a persistent session. Subsequent messages use `--resume <uuid>` to continue the conversation with full history. Sessions auto-expire after 6 hours of inactivity (configurable via `SESSION_TIMEOUT_HOURS`), and the user can send `/new` to start a fresh conversation at any time.

The skill file and context files are injected inline so Claude Code has complete context without needing to discover it. The assistant auto-maintains `notes.md` (general preferences) and `context/<project-name>.md` files (per-project details) as it learns new information during conversations.

For scheduled tasks, the skill is omitted and replaced with task-specific context:

```
You are a personal AI assistant for [NAME].
Current time: 2026-02-27 09:00 (America/Chicago).
This is a scheduled task (trigger: scheduled).
Complete the following task and provide the result as your response.
Task: [prompt from tasks.json]
```

---

## Limitations

**PC must be on.** The catch-up system handles gaps but cannot eliminate them. Tasks do not execute while the machine is off. A Linux VPS deployment eliminates this constraint.

**No GUI automation.** Claude Code is a terminal process. It cannot click through desktop applications, interact with browser UIs, or control GUI software. It can read and write files, run shell commands, make HTTP requests, and use its built-in web search and coding tools.

**Single user.** The system is designed for one person. Multi-user support would require replacing the single `TELEGRAM_ALLOWED_USER_ID` with a whitelist and routing responses back to the correct chat ID.

**Sequential task execution.** The runner processes tasks one at a time. If a task takes 2 minutes and three tasks are due simultaneously, they queue. For personal use this is rarely a problem. A parallel execution model would require more complex concurrency management.

**OAuth token expiry on VPS.** Claude Code uses OAuth tokens that expire every few hours. On Windows, the desktop app refreshes tokens automatically. On a Linux VPS there is no desktop session, so tokens expire and must be renewed manually or via automation. The recommended solution is a scheduled task on a Windows CAB instance that copies fresh credentials to the VPS every 2 hours via SCP. See `docs/setup-linux-vps.md` for details.