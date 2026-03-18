# Linux VPS Setup Guide

This guide walks through deploying Claude Assistant Bridge on a Linux VPS for true 24/7 uptime. Tasks fire exactly on schedule regardless of whether your personal computer is on.

**Total cost:** ~$5/month (Hetzner CPX11)
**Time:** 30-45 minutes
**Prerequisites:** A Telegram bot token and Claude Max or Pro subscription

---

## 1. Provision a VPS

[Hetzner](https://hetzner.com) offers the best price/performance for this use case.

1. Sign up at hetzner.com → create a new project
2. Click **Add Server** and select:
   - **Location:** US (Ashburn) or whichever is closest to you
   - **Image:** Ubuntu 24.04
   - **Type:** CPX11 (~$4.99/month) — 2 vCPU, 2GB RAM, more than enough
   - **SSH Key:** add your public key (recommended) or use a root password
3. Click **Create & Buy** — server is ready in about 30 seconds

Note your server's IP address from the Hetzner dashboard.

---

## 2. Point a Domain at Your Server

Telegram requires HTTPS for webhooks. The cleanest solution is a subdomain pointed at your VPS with automatic TLS via Caddy.

In your DNS provider, add an **A record**:
- **Name:** `cab` (or any subdomain you prefer)
- **Value:** your server's IP address
- **TTL:** 300

This creates `cab.yourdomain.com`. Verify it's working:

```bash
ping cab.yourdomain.com
```

You should see your server's IP in the response. If not, wait a few minutes for DNS propagation.

---

## 3. Initial Server Setup

SSH into your server as root:

```bash
ssh root@YOUR_SERVER_IP
```

Update the system and install dependencies:

```bash
apt update && apt upgrade -y && apt install -y python3 python3-pip python3-venv nodejs npm git caddy
```

Install Claude Code:

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

---

## 4. Create a Non-Root User

Claude Code refuses to run as root with `--dangerously-skip-permissions`. Create a dedicated user:

```bash
useradd -m -s /bin/bash claude
```

---

## 5. Authenticate Claude Code

Claude Code stores credentials in `~/.claude/.credentials.json`. The easiest approach is to copy your existing credentials from your local machine rather than going through the interactive auth flow over SSH.

**On your local machine** (in a separate terminal):

```bash
# macOS / Linux
scp ~/.claude/.credentials.json root@YOUR_SERVER_IP:/home/claude/.claude/.credentials.json

# Windows (Command Prompt)
scp %USERPROFILE%\.claude\.credentials.json root@YOUR_SERVER_IP:/home/claude/.claude/.credentials.json
```

Back on the server, fix ownership and verify:

```bash
chown -R claude:claude /home/claude/.claude

# Test that auth works
su - claude -c "claude -p 'say hello' --dangerously-skip-permissions"
```

You should see a response like `Hello! How can I help you today?`

---

## 6. Configure Caddy (HTTPS)

Caddy automatically provisions and renews TLS certificates via Let's Encrypt.

```bash
cat > /etc/caddy/Caddyfile << 'EOF'
cab.yourdomain.com {
    reverse_proxy localhost:8080
}
EOF

systemctl restart caddy
systemctl status caddy
```

You should see `Active: active (running)` and a log line about enabling automatic TLS.

---

## 7. Clone and Configure CAB

Switch to the claude user:

```bash
su - claude
git clone https://github.com/DlaregY/claude-assistant-bridge.git
cd claude-assistant-bridge
pip install -r requirements.txt --break-system-packages
```

Create the `.env` file:

```bash
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_USER_ID=your_telegram_user_id
CLOUDFLARE_TUNNEL_URL=https://cab.yourdomain.com
WEBHOOK_PORT=8080
TASKS_FILE=/home/claude/claude-assistant-bridge/tasks.json
RUN_LOG_FILE=/home/claude/claude-assistant-bridge/run_log.jsonl
LOGS_DIR=/home/claude/claude-assistant-bridge/logs
USER_DISPLAY_NAME=YourName
TIMEZONE=America/Chicago
EOF
```

Replace the placeholder values:
- `TELEGRAM_BOT_TOKEN` — from BotFather
- `TELEGRAM_ALLOWED_USER_ID` — your numeric Telegram user ID (get it from @userinfobot)
- `CLOUDFLARE_TUNNEL_URL` — your subdomain (e.g. `https://cab.yourdomain.com`)
- `USER_DISPLAY_NAME` — your first name
- `TIMEZONE` — your timezone (e.g. `America/New_York`, `America/Los_Angeles`, `Europe/London`)

Create data files:

```bash
mkdir -p logs context
echo '{"version": "1.0", "tasks": []}' > tasks.json
touch run_log.jsonl notes.md
```

---

## 8. Test Manually

Before installing services, verify everything works:

```bash
python3 webhook_server.py
```

You should see:

```
Platform: Linux
Claude executable: claude
Using static URL: https://cab.yourdomain.com
Webhook registered at https://cab.yourdomain.com/webhook — Webhook was set
Claude Assistant Bridge running on port 8080
```

Send a message to your bot on Telegram. You should get a response within a few seconds.

Press **Ctrl+C** to stop.

---

## 9. Install Services

Switch back to root and run the service installer:

```bash
exit  # back to root
cd /home/claude/claude-assistant-bridge
python3 services/linux.py
```

This installs:
- A `systemd` service that starts the webhook server on boot
- A `cron` job under the `claude` user that runs the task runner every 5 minutes

> **Important:** The cron job is always installed under the `claude` user, even when this script runs as root. Claude Code refuses `--dangerously-skip-permissions` under root, so the runner **must** run as `claude`.

Verify the service is running:

```bash
systemctl status claude-assistant-bridge --no-pager
```

You should see `Active: active (running)`.

---

## 10. Verify the systemd Service File

Check the generated service file to ensure it's running as the `claude` user:

```bash
cat /etc/systemd/system/claude-assistant-bridge.service
```

The `User=` line should say `claude`, not `root`. If it says `root`, fix it:

```bash
sed -i 's/User=root/User=claude/' /etc/systemd/system/claude-assistant-bridge.service
```

Also verify the PATH includes the npm global bin directory. The `Environment="PATH=..."` line should include `/usr/lib/node_modules/.bin`. If it doesn't, add it manually or re-run the installer after pulling the latest version of the repo.

After any changes:

```bash
systemctl daemon-reload
systemctl restart claude-assistant-bridge
```

---

## 11. Reboot Test

```bash
reboot
```

Wait 30 seconds, SSH back in, and verify:

```bash
systemctl status claude-assistant-bridge --no-pager
```

Send a Telegram message to confirm the full loop works after reboot.

---

## Useful Commands

```bash
# Check webhook server status
systemctl status claude-assistant-bridge

# View webhook server logs
tail -f /home/claude/claude-assistant-bridge/logs/webhook.log

# View task runner logs
tail -f /home/claude/claude-assistant-bridge/logs/runner.log

# Restart webhook server
systemctl restart claude-assistant-bridge

# View cron jobs
crontab -l -u claude

# Check recent task executions
tail -20 /home/claude/claude-assistant-bridge/run_log.jsonl

# Manually trigger the task runner
su - claude -c "python3 /home/claude/claude-assistant-bridge/runner.py"
```

---

## Credentials Renewal

Claude Code uses OAuth tokens that expire every few hours. When a token expires, your VPS bot will respond with a 401 authentication error. The fix is to copy fresh credentials from your local machine to the VPS.

**Manual fix (when it breaks):**

On your Windows machine:

```cmd
scp %USERPROFILE%\.claude\.credentials.json root@YOUR_SERVER_IP:/home/claude/.claude/.credentials.json
ssh root@YOUR_SERVER_IP "chown claude:claude /home/claude/.claude/.credentials.json"
```

Claude Code reads credentials fresh on each invocation — no service restart needed.

**Automated fix (recommended):**

If you're also running CAB on Windows, use your Windows bot to schedule automatic renewal. Send this message to your Windows bot:

> "Add a task: every 2 hours copy my Claude credentials to the VPS. Run: scp C:/Users/YOUR_USERNAME/.claude/.credentials.json root@YOUR_SERVER_IP:/home/claude/.claude/.credentials.json && ssh root@YOUR_SERVER_IP 'chown claude:claude /home/claude/.claude/.credentials.json'"

This keeps the VPS credentials fresh automatically as long as your Windows machine is on. No restart needed — Claude Code picks up the updated credentials on its next invocation.

---

## Notes

**No cloudflared needed.** With a static IP and a real domain, Caddy handles HTTPS directly. Cloudflared is unnecessary on a VPS.

**Catch-up logic is less important here.** Since the VPS runs 24/7, tasks fire exactly on schedule. The catch-up system still works correctly but rarely triggers.

**Credentials will expire.** Claude Code's OAuth tokens refresh automatically, but if you ever get auth errors, re-copy your `.credentials.json` from your local machine and restart the service.

**Conversations have memory.** Claude remembers context within a session. Sessions auto-reset after 6 hours of inactivity (configurable via `SESSION_TIMEOUT_HOURS` in `.env`). Send `/new` to start a fresh conversation at any time.

**Running both Windows and VPS simultaneously** is fine — just use a different Telegram bot for each. Each bot registers its own webhook URL independently.