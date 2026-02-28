# CAB vs OpenClaw

OpenClaw is impressive. It's viral for good reasons — the idea of texting your computer and having it do things is genuinely powerful, and the community around it has built thousands of skills and integrations. This document isn't a dismissal of OpenClaw. It's an honest comparison of the two approaches for a specific user: a Claude Max subscriber on Windows who wants reliable phone-based AI control.

---

## The Core Idea Is the Same

Both systems give you the same fundamental capability: send a message from your phone, have an AI execute it on a computer, get a response back. OpenClaw pioneered this pattern. CAB implements the same pattern with different architectural choices.

---

## Where They Differ

### Setup complexity

OpenClaw on Windows requires Docker or WSL. Neither is trivial for non-developers. Docker has its own learning curve, resource overhead, and occasional conflicts with other software. WSL requires enabling Windows features and understanding the Linux/Windows file system boundary.

CAB runs natively on Windows with no virtualization layer. Setup is a single Python script.

### Security model

OpenClaw's power comes from its open community. Anyone can publish a skill to ClawHub. That same openness is its security liability — Cisco's AI security team found a third-party skill performing data exfiltration and prompt injection without user awareness, and the project has no dedicated security team or bug bounty program.

The project's own maintainer said publicly: "if you can't understand how to run a command line, this is far too dangerous of a project for you to use safely."

CAB has a smaller attack surface by design. There are no third-party skills, no community registry, no external code executing in your environment. The system is small enough to read in an afternoon. What you see is what runs.

### Cost model

OpenClaw is model-agnostic, which matters for cost. Using it with Claude via the API can run $50-300/month depending on usage volume. Using it with local models via Ollama can bring that to near zero.

CAB is designed for Claude Max subscribers ($100-200/month flat rate). Under a flat-rate subscription, more Claude usage costs nothing marginal. Every task and message is effectively free beyond the base subscription. If you're already paying for Claude Max, CAB costs zero additional dollars. If you're not, OpenClaw with a local model is genuinely cheaper.

### Windows support

OpenClaw was built Mac-first. Windows support exists but typically goes through Docker, which adds overhead and complexity.

CAB was built Windows-first. It uses Windows Task Scheduler, NSSM, and native Python — tools that are standard on Windows and require no additional infrastructure.

### Skill ecosystem

OpenClaw has 5,700+ community-built skills on ClawHub covering everything from Spotify control to smart home integration. CAB has one skill file: `task_manager.md`.

This is the clearest advantage OpenClaw holds. If you need pre-built integrations with dozens of external services out of the box, OpenClaw's ecosystem is unmatched.

The counterargument: Claude Code can interact with any service that has an API, a web interface, or a file format — without a dedicated skill. You don't need a "Gmail skill" when Claude Code can read your email via the web or write a Python script to interact with the Gmail API on the spot. The skill ecosystem is a shortcut, not a capability boundary.

### 24/7 uptime

OpenClaw is typically hosted on a server or always-on device, giving it true 24/7 availability.

CAB on Windows requires your PC to be on. The catch-up system handles offline gaps gracefully, but tasks don't execute while the machine is sleeping. CAB on a Linux VPS achieves the same 24/7 uptime as OpenClaw — see `docs/setup-linux-vps.md`.

---

## Honest Summary

| | CAB (Windows) | CAB (Linux VPS) | OpenClaw |
|---|---|---|---|
| Setup difficulty | Low | Medium | Medium-High |
| Windows native | ✅ | N/A | ⚠️ (Docker) |
| Security model | Auditable, minimal | Auditable, minimal | Community trust required |
| Cost (Claude Max user) | $0 extra | ~$5/month extra | $0 extra if local models |
| 24/7 uptime | ⚠️ PC must be on | ✅ | ✅ |
| Skill ecosystem | Build your own | Build your own | 5,700+ pre-built |
| Model flexibility | Claude only | Claude only | Any model |
| Open source | ✅ MIT | ✅ MIT | ✅ |

---

## Who Should Use What

**Use CAB if:**
- You're a Claude Max subscriber and want zero additional cost
- You're on Windows and don't want to deal with Docker or WSL
- You want a system you can fully understand and audit
- You're comfortable building custom integrations with Claude Code rather than installing pre-built skills
- You want your data to stay on your machine

**Use OpenClaw if:**
- You want a large pre-built skill ecosystem immediately
- You're using local models and cost is a primary concern
- You're comfortable with Docker and understand the security tradeoffs
- You want a large community to draw on for ideas and support

**Use both if:**
- You want OpenClaw's community skills for certain integrations and CAB's simplicity for scheduled tasks and file operations

---

## On OpenClaw's Trajectory

OpenClaw's creator joined OpenAI in February 2026, and the project moved to an open-source foundation. The community remains active but the original vision and primary maintainer have departed. What this means for long-term development is unclear.

CAB has no such dependency. It's a small, self-contained system that works as long as Claude Code and Telegram's Bot API exist.
