# Windows Setup Guide

This guide walks through deploying Claude Assistant Bridge on a Windows PC. Your computer becomes a personal AI assistant you control from your phone via Telegram.

**Total cost:** $0 beyond your existing Claude Max subscription
**Time:** 30-45 minutes
**Prerequisites:** A Claude Max or Pro subscription and a Telegram account

---

## 1. Install Required Software

### Python 3.11+

Check if Python is already installed:

```cmd
python --version
```

If you see `Python 3.11.x` or higher, skip ahead. Otherwise download from [python.org/downloads](https://python.org/downloads). During installation, check **"Add Python to PATH"**.

### Claude Code

Download and install from [claude.ai/code](https://claude.ai/code). After installing, verify:

```cmd
claude --version
```

If the command isn't found, Claude Code may not be on your PATH. You can find the executable at:

```
C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude-code\VERSION\claude.exe
```

CAB auto-detects this path, so you don't need to add it to PATH manually.

### NSSM (Service Manager)

NSSM is used to run cloudflared as a persistent Windows service.

```cmd
winget install NSSM.NSSM
```

### Cloudflare Tunnel

Cloudflared creates a secure HTTPS tunnel from Cloudflare's network to your local machine — required because Telegram needs a public HTTPS endpoint to push messages to.

```cmd
winget install Cloudflare.cloudflared
```

---

## 2. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send: `/newbot`
3. Choose a name for your bot (e.g. "My Assistant")
4. Choose a username ending in `bot` (e.g. `myassistant_bot`)
5. BotFather will give you a **bot token** — save it, you'll need it shortly

### Find Your Telegram User ID

1. In Telegram, search for **@userinfobot**
2. Send: `/start`
3. It will reply with your numeric user ID — save this too

---

## 3. Clone the Repository

```cmd
git clone https://github.com/DlaregY/claude-assistant-bridge.git
cd claude-assistant-bridge
pip install -r requirements.txt
```

---

## 4. Configure Your Environment

Copy the example config:

```cmd
cp .env.example .env
notepad .env
```

Fill in your values:

```
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_ALLOWED_USER_ID=your_numeric_telegram_user_id
CLOUDFLARE_TUNNEL_URL=
WEBHOOK_PORT=8080
TASKS_FILE=C:/AIAssistant/tasks.json
RUN_LOG_FILE=C:/AIAssistant/run_log.jsonl
LOGS_DIR=C:/AIAssistant/logs
USER_DISPLAY_NAME=YourFirstName
TIMEZONE=America/Chicago
```

**Timezone examples:** `America/New_York`, `America/Chicago`, `America/Los_Angeles`, `America/Denver`, `Europe/London`

Leave `CLOUDFLARE_TUNNEL_URL` blank — it's auto-detected at runtime.

Save and close Notepad.

### Create Data Files

```cmd
mkdir logs
mkdir context
echo {"version": "1.0", "tasks": []} > tasks.json
type nul > run_log.jsonl
type nul > notes.md
```

---

## 5. Start the Cloudflare Tunnel

Open a separate Command Prompt and run:

```cmd
cloudflared tunnel --url http://localhost:8080
```

After a few seconds you'll see a line like:

```
Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):
https://something-random.trycloudflare.com
```

Leave this window open — you'll make it a permanent service in step 7.

---

## 6. Test Manually

In your original Command Prompt:

```cmd
python webhook_server.py
```

You should see:

```
Platform: Windows
Claude executable: C:\Users\...\claude.exe
Waiting 30 seconds for network to initialize...
Detected tunnel URL: https://something-random.trycloudflare.com
Webhook registered at https://something-random.trycloudflare.com/webhook — Webhook was set
Claude Assistant Bridge running on port 8080
```

Open Telegram and send a message to your bot. You should get a response within a few seconds.

Press **Ctrl+C** to stop once you've confirmed it works.

---

## 7. Install Persistent Services

CAB needs three things to survive reboots:

- **cloudflared** running as a Windows service (via NSSM)
- **webhook_server.py** launching at login (via Task Scheduler)
- **runner.py** firing every 5 minutes (via Task Scheduler)

Open **Command Prompt as Administrator** (right-click → Run as administrator) and run:

```cmd
cd C:\path\to\claude-assistant-bridge
python services/windows.py
```

This handles all three registrations automatically.

### Why Task Scheduler instead of a Windows service for the webhook server?

Windows services run as the SYSTEM account by default, which has no access to your Claude Code authentication. Task Scheduler can run as your user account, inheriting your credentials. This is why the webhook server and runner run via Task Scheduler rather than NSSM.

---

## 8. Verify Everything is Running

Check cloudflared:

```cmd
nssm status cloudflared-tunnel
```

Should show `SERVICE_RUNNING`.

Check the webhook server and runner:

```cmd
schtasks /query /tn "Claude Assistant Bridge"
schtasks /query /tn "Claude Assistant Bridge Runner"
```

Both should show `Ready` or `Running`.

Send another Telegram message to confirm the full loop works.

---

## 9. Reboot Test

Restart your PC. After logging back in, wait about 45 seconds for services to initialize, then send a Telegram message. You should get a response without having started anything manually.

---

## Natural Language Task Scheduling

Once the system is running, you can manage scheduled tasks entirely through Telegram:

| Message | Result |
|---------|--------|
| "Every weekday at 8am send me a good morning message" | Creates a recurring task |
| "Remind me every Monday at 9am to review my emails" | Creates a weekly task |
| "What tasks do I have scheduled?" | Lists all tasks |
| "Disable the morning message" | Pauses that task |
| "Run my weekly review right now" | Fires immediately |
| "Did anything fail this week?" | Queries the run log |
| "What happens to my tasks if my PC is off?" | Explains catch-up behavior |

---

## Useful Commands

```cmd
REM Check webhook server logs
type C:\AIAssistant\logs\webhook.log

REM Check task runner logs
type C:\AIAssistant\logs\runner.log

REM Restart the webhook server
schtasks /end /tn "Claude Assistant Bridge"
schtasks /run /tn "Claude Assistant Bridge"

REM Manually trigger the task runner
python C:\AIAssistant\runner.py

REM Check recent task executions
type C:\AIAssistant\run_log.jsonl
```

---

## Troubleshooting

**"Claude not found" error**

CAB auto-detects Claude Code's location. If it fails, add the full path to `.env`:

```
CLAUDE_EXE=C:/Users/YOUR_USERNAME/AppData/Roaming/Claude/claude-code/VERSION/claude.exe
```

**Webhook server starts but Telegram messages get no response**

Check that cloudflared is running and the tunnel URL was detected:

```cmd
nssm status cloudflared-tunnel
type C:\AIAssistant\logs\webhook.log
```

**"Not logged in" error from Claude Code**

The service is running as the wrong user. Ensure the Task Scheduler tasks are configured to run as your user account, not SYSTEM. Re-run `services/windows.py` as Administrator if needed.

**Garbled characters in responses (â€" instead of —)**

This encoding issue is fixed in the current version (`encoding="utf-8"` is set in both `webhook_server.py` and `runner.py`). If you still see it, pull the latest version and restart.

**Tasks not firing on schedule**

Check the runner log for skipped entries:

```cmd
type C:\AIAssistant\run_log.jsonl
type C:\AIAssistant\logs\runner.log
```

If entries show `status: skipped` with `catch_up=false`, the task missed its window. If entries show `status: error`, check the error field for details. If the runner starts but never logs "Runner finished", a task definition may be malformed — check `tasks.json` for syntax issues (cron tasks must use the `"expression"` key, not `"cron"`).

---

## Notes

**The tunnel URL changes on restart.** Cloudflared's free quick tunnel generates a new URL each time cloudflared restarts. CAB handles this automatically — the webhook server detects the new URL and re-registers with Telegram on startup. No manual intervention needed.

**Your PC must be on for tasks to execute.** If the PC is off at a scheduled task time, CAB uses catch-up logic to run the task when the PC wakes up, within the configured window. Tasks with `catch_up: false` are skipped entirely if missed.

**notes.md is auto-maintained by the assistant.** Every conversation injects `notes.md` as context and instructs the AI to update it with project paths, preferences, and decisions. You can also edit it manually to pre-populate context. This file is gitignored.

**Want 24/7 uptime?** Deploy CAB on a Linux VPS instead — see [docs/setup-linux-vps.md](docs/setup-linux-vps.md). You can run both simultaneously with separate Telegram bots.
