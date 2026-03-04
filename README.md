# Claude Assistant Bridge (CAB)

A self-hosted, phone-controlled AI assistant built on Claude Code and Telegram. Text your computer from anywhere and Claude executes tasks on your behalf — organizing files, answering questions, running scheduled workflows, and more.

**Runs on Windows or a Linux VPS. No Docker. No extra cost beyond your Claude Max subscription.**

Built as a clean alternative to OpenClaw for Claude Max users who want phone-based AI control without the complexity, security risks, or Mac-first limitations.

---

## What it does

- **Text your AI from anywhere** — send a message on Telegram, Claude Code executes it on your machine
- **Natural language scheduling** — "every weekday at 8am send me a good morning message" just works
- **Smart catch-up** — if your PC was off when a task was due, the system recovers it intelligently when it comes back on
- **Full audit log** — every task execution is logged to `run_log.jsonl`, queryable via plain English
- **Your data stays local** — tasks, logs, and configuration never leave your machine

---

## Deployment Options

### Windows (local PC)
Full local file access. Claude Code can read, write, and organize anything on your machine. Catch-up logic handles gaps when the PC is off or sleeping.

**Requirements:** Windows 10/11, Python 3.11+, Claude Code, Telegram account, Cloudflare account (free)

→ [docs/setup-windows.md](docs/setup-windows.md)

### Linux VPS (~$5/month)
True 24/7 uptime — tasks fire exactly on schedule, no catch-up needed. Best for reminders, research, drafting, and anything cloud-native.

**Requirements:** Ubuntu 24.04 VPS (Hetzner CPX11 recommended), Python 3.11+, Claude Code, Telegram account, a domain name

→ [docs/setup-linux-vps.md](docs/setup-linux-vps.md)

### Running both simultaneously
Use a different Telegram bot for each deployment. Each registers its own webhook independently. Windows handles local file tasks, VPS handles scheduled and cloud-native tasks.

---

## Quick Start

```bash
git clone https://github.com/DlaregY/claude-assistant-bridge.git
cd claude-assistant-bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values
python setup.py  # interactive wizard — detects Windows or Linux automatically
```

---

## Architecture

```
Your Phone (Telegram)
        ↓
  Telegram Bot API
        ↓  (webhook push, ~1 second latency)
  Cloudflare Tunnel (Windows) / Caddy + domain (Linux VPS)
        ↓
  webhook_server.py  (FastAPI, runs as system service)
        ↓
  Claude Code CLI  (auto-detected per platform)
        ↓
  tasks.json  ←————— scheduled task definitions
        ↓
  runner.py  (every 5 min via Task Scheduler / cron)
        ↓
  run_log.jsonl  ←— append-only execution history
        ↓
  Response → Telegram → Your Phone
```

See [docs/architecture.md](docs/architecture.md) for detailed design decisions and rationale.

---

## Natural Language Scheduling

Send these directly to your bot:

| Message | What happens |
|---------|-------------|
| "Every weekday at 8am send me a good morning message" | Adds a daily task |
| "Remind me every Monday at 9am to review my emails" | Adds a weekly task |
| "What tasks do I have scheduled?" | Lists all tasks |
| "Cancel the morning message" | Disables that task |
| "Run my weekly review right now" | Fires immediately |
| "Did anything fail this week?" | Queries the run log |
| "What would happen if my PC was off at 8am?" | Explains catch-up behavior |

---

## Why not OpenClaw?

OpenClaw is powerful, but for Windows Claude Max users it has real friction:

- Requires Docker or WSL on Windows
- Security concerns from unvetted community skills on ClawHub
- API costs can be significant under heavy use
- Complex setup

CAB runs natively on Windows and Linux, uses your existing Max subscription (flat rate, no surprise bills), and has a codebase small enough to read in an afternoon.

See [docs/comparison-openclaw.md](docs/comparison-openclaw.md) for a full breakdown.

---

## Repository Structure

```
claude-assistant-bridge/
├── setup.py                # Cross-platform setup wizard
├── webhook_server.py       # Telegram webhook receiver
├── runner.py               # Scheduled task runner
├── notes.md                # Auto-maintained general context (gitignored)
├── context/                # Per-project context files (gitignored)
│   └── *.md               #   e.g. myproject.md, vps.md
├── skills/
│   └── task_manager.md     # Claude Code skill for task management
├── services/
│   ├── windows.py          # Windows service registration
│   └── linux.py            # Linux systemd + cron registration
├── docs/
│   ├── architecture.md
│   ├── setup-windows.md
│   ├── setup-linux-vps.md
│   └── comparison-openclaw.md
└── tests/
    ├── test_scheduler.py   # 20 catch-up logic tests
    └── test_webhook.py     # 12 routing and auth tests
```

---

## Contributing

PRs welcome. Please open an issue first for anything beyond small fixes.

---

## License

MIT — Gerald Norby