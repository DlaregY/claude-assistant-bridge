# Claude Assistant Bridge (CAB)

A self-hosted, phone-controlled AI assistant built on Claude Code and Telegram. Text your PC from anywhere and Claude executes tasks on your behalf — organizing files, answering questions, running scheduled workflows, and more.

**Windows-native. No Docker. No extra cost beyond your Claude Max subscription.**

Built as a clean alternative to OpenClaw for Windows users who want phone-based AI control without the complexity, security risks, or Mac-only limitations.

---

## What it does

- **Text your AI from anywhere** — send a message on Telegram, Claude Code executes it on your PC
- **Scheduled tasks** — set recurring tasks in plain English ("every Monday at 9am summarize my Downloads folder")
- **Smart catch-up** — if your PC was off, the system recovers missed tasks intelligently when it comes back on
- **Full audit log** — every task execution is logged, gaps when the PC was off are visible
- **Runs entirely on your machine** — your data never leaves your PC

---

## Requirements

- Windows 10 or 11
- Python 3.11+
- [Claude Code](https://claude.ai/code) with an active Max or Pro subscription
- A free [Telegram](https://telegram.org) account
- A free [Cloudflare](https://cloudflare.com) account (for the tunnel)

---

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/claude-assistant-bridge.git
cd claude-assistant-bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values (see Setup Guide below)
python webhook_server.py
```

Full setup takes about 30 minutes. See [docs/setup-windows.md](docs/setup-windows.md) for the complete step-by-step walkthrough.

---

## Architecture

```
Your Phone (Telegram)
        ↓
  Telegram Bot API
        ↓  (webhook push)
  Cloudflare Tunnel
        ↓
  webhook_server.py  (FastAPI, runs as Windows service)
        ↓
  Claude Code CLI
        ↓
  tasks.json + run_log.jsonl
        ↓
  Windows Task Scheduler (runner.py, every 5 min)
        ↓
  Response → Telegram → Your Phone
```

See [docs/architecture.md](docs/architecture.md) for detailed design decisions.

---

## Project Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core pipeline — Telegram → Claude Code → response | ✅ Complete |
| 2 | Task scheduler + catch-up logging | 🔄 In progress |
| 3 | Natural language scheduling via Telegram | ⏳ Planned |
| 4 | Open source release, docs, tests, setup wizard | ⏳ Planned |

---

## Why not OpenClaw?

OpenClaw is a powerful project, but for Windows Claude Max users it has real friction:

- Requires Docker or WSL on Windows
- Security concerns from unvetted community skills
- API pricing can be expensive under heavy use
- Complex setup not suitable for non-technical users

CAB is purpose-built for Windows, runs natively, uses your existing Max subscription (flat rate, no surprise bills), and has a security model simple enough to audit yourself.

See [docs/comparison-openclaw.md](docs/comparison-openclaw.md) for a full breakdown.

---

## Contributing

PRs welcome. Please open an issue first for anything beyond small fixes.

---

## License

MIT
