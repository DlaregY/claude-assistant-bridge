"""
Claude Assistant Bridge — Webhook Server
Receives Telegram messages and routes them to Claude Code for execution.
Runs as a persistent service (Windows: Task Scheduler, Linux: systemd).
"""

import os
import glob
import time
import asyncio
import platform
import subprocess
import requests
import logging
import importlib.util
from datetime import datetime
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import uvicorn

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))
PORT = int(os.getenv("WEBHOOK_PORT", 8080))
TASKS_FILE = os.getenv("TASKS_FILE")
RUN_LOG_FILE = os.getenv("RUN_LOG_FILE")
LOGS_DIR = os.getenv("LOGS_DIR")
USER_NAME = os.getenv("USER_DISPLAY_NAME", "User")
TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")
BOT_HANDLERS = os.getenv("BOT_HANDLERS", "")  # comma-separated handler module paths

# ---------------------------------------------------------------------------
# Claude executable resolution
# ---------------------------------------------------------------------------

def _find_claude_windows() -> str:
    """
    Search known Windows installation paths for claude.exe.
    Returns the path to the most recent version found, or 'claude' as fallback.
    """
    appdata = os.environ.get("APPDATA", "")
    patterns = [
        os.path.join(appdata, "Claude", "claude-code", "*", "claude.exe"),
        os.path.join(appdata, "npm", "claude.cmd"),
        os.path.join(appdata, "npm", "claude"),
    ]
    candidates = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        candidates.extend(matches)

    if not candidates:
        return "claude"  # Hope it's on PATH

    # Prefer versioned claude-code installs, pick the most recent by path sort
    versioned = [c for c in candidates if "claude-code" in c]
    if versioned:
        return sorted(versioned)[-1]  # Highest version number last alphabetically

    return candidates[0]


def _resolve_claude_exe() -> str:
    """Resolve Claude executable path. Env var always wins."""
    if os.getenv("CLAUDE_EXE"):
        return os.getenv("CLAUDE_EXE")
    if IS_WINDOWS:
        found = _find_claude_windows()
        return found
    return "claude"  # Linux: assume on PATH after `npm install -g`


CLAUDE_EXE = _resolve_claude_exe()


# ---------------------------------------------------------------------------
# Handler plugin system
# ---------------------------------------------------------------------------

_handlers = []

def load_handlers():
    """Load bot handler plugins specified in BOT_HANDLERS env var."""
    if not BOT_HANDLERS:
        return
    config = {
        "claude_exe": CLAUDE_EXE,
        "user_name": USER_NAME,
        "timezone": TIMEZONE,
        "allowed_user_id": ALLOWED_USER_ID,
        "logs_dir": LOGS_DIR,
        "base_dir": os.path.dirname(__file__),
    }
    for path in BOT_HANDLERS.split(","):
        path = path.strip()
        if not path:
            continue
        try:
            spec = importlib.util.spec_from_file_location("handler", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "setup"):
                mod.setup(app, config)
                logging.info(f"Loaded handler: {path}")
            _handlers.append(mod)
        except Exception as e:
            logging.error(f"Failed to load handler {path}: {e}")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOGS_DIR, "webhook.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    await startup()
    # Start tunnel health monitor for quick tunnels (not static URLs)
    if not os.getenv("CLOUDFLARE_TUNNEL_URL", ""):
        health_task = asyncio.create_task(_tunnel_health_loop())
    yield
    if not os.getenv("CLOUDFLARE_TUNNEL_URL", ""):
        health_task.cancel()

app = FastAPI(lifespan=lifespan)

def get_tunnel_url(retries=10, delay=3) -> str:
    """Poll cloudflared's local API to get the current tunnel URL."""
    for i in range(retries):
        try:
            resp = requests.get("http://localhost:20241/quicktunnel", timeout=3)
            if resp.status_code == 200:
                url = "https://" + resp.json()["hostname"]
                logging.info(f"Detected tunnel URL: {url}")
                print(f"Detected tunnel URL: {url}")
                return url
        except Exception:
            print(f"Waiting for cloudflared tunnel... ({i+1}/{retries})")
            time.sleep(delay)
    fallback = os.getenv("CLOUDFLARE_TUNNEL_URL", "")
    logging.warning(f"Could not detect tunnel URL, using fallback: {fallback}")
    print(f"Using fallback tunnel URL from .env: {fallback}")
    return fallback


# ---------------------------------------------------------------------------
# Tunnel health monitor
# ---------------------------------------------------------------------------

TUNNEL_CHECK_INTERVAL = 120  # seconds between health checks
TUNNEL_SERVICE_NAME = "cloudflared-tunnel"

# Current tunnel URL — updated by startup and health monitor
_current_tunnel_url: str = ""


def _restart_cloudflared() -> bool:
    """Restart the cloudflared Windows service via PowerShell (needs elevation)."""
    logging.info("Restarting cloudflared service...")
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Restart-Service {TUNNEL_SERVICE_NAME}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logging.info("cloudflared service restarted successfully")
            return True
        # Try elevated restart if direct restart fails (access denied)
        result = subprocess.run(
            ["powershell", "-Command",
             f"Start-Process powershell -ArgumentList '-Command','Restart-Service {TUNNEL_SERVICE_NAME}' -Verb RunAs -Wait"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logging.info("cloudflared service restarted via elevation")
            return True
        logging.error(f"Failed to restart cloudflared: {result.stderr.strip()}")
        return False
    except Exception as e:
        logging.error(f"Exception restarting cloudflared: {e}")
        return False


def _check_tunnel_health(tunnel_url: str) -> bool:
    """Verify the tunnel hostname resolves and responds."""
    try:
        resp = requests.head(tunnel_url, timeout=10, allow_redirects=True)
        return resp.status_code < 530  # 530 = Cloudflare origin error
    except Exception:
        return False


async def _tunnel_health_loop():
    """Background loop that monitors tunnel health and self-heals."""
    global _current_tunnel_url
    # Let the server finish starting up
    await asyncio.sleep(TUNNEL_CHECK_INTERVAL)

    while True:
        try:
            if _current_tunnel_url and not _current_tunnel_url.startswith("https://"):
                await asyncio.sleep(TUNNEL_CHECK_INTERVAL)
                continue

            healthy = await asyncio.to_thread(_check_tunnel_health, _current_tunnel_url)
            if not healthy:
                logging.warning(f"Tunnel unhealthy ({_current_tunnel_url}), restarting cloudflared...")
                await asyncio.to_thread(_restart_cloudflared)
                # Wait for cloudflared to come back up
                await asyncio.sleep(15)
                new_url = await asyncio.to_thread(get_tunnel_url, 15, 3)
                if new_url and new_url != _current_tunnel_url:
                    logging.info(f"Tunnel URL changed: {_current_tunnel_url} -> {new_url}")
                    _current_tunnel_url = new_url
                    await asyncio.to_thread(register_webhook, new_url)
                elif new_url:
                    # Same URL, just re-register to be safe
                    await asyncio.to_thread(register_webhook, new_url)
                else:
                    logging.error("Could not detect new tunnel URL after restart")
        except Exception as e:
            logging.error(f"Tunnel health check error: {e}")

        await asyncio.sleep(TUNNEL_CHECK_INTERVAL)


def send_telegram(chat_id: int, text: str):
    """Send a message to a Telegram chat, splitting if over 4000 chars."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4000):
        requests.post(url, json={"chat_id": chat_id, "text": text[i:i+4000]})


def register_webhook(tunnel_url: str):
    """Register webhook URLs with Telegram for all bots. Raises on failure."""
    # Main CAB bot
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{tunnel_url}/webhook"
    resp = requests.post(url, json={"url": webhook_url})
    result = resp.json()
    logging.info(f"CAB webhook registered: {result}")
    print(f"CAB webhook registered at {webhook_url} — {result.get('description', '')}")
    if not result.get("ok"):
        raise Exception(f"Telegram rejected CAB webhook: {result.get('description')}")

    # Handler webhooks
    for handler in _handlers:
        if hasattr(handler, "register_webhooks"):
            try:
                handler.register_webhooks(tunnel_url)
            except Exception as e:
                logging.error(f"Handler webhook registration failed: {e}")


def load_skill(skill_path: str) -> str:
    """Load a skill file and return its contents, or empty string if not found."""
    full_path = os.path.join(os.path.dirname(__file__), skill_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def load_context_files() -> str:
    """Load all per-project context files from context/ directory."""
    context_dir = os.path.join(os.path.dirname(__file__), "context")
    if not os.path.isdir(context_dir):
        return ""
    parts = []
    for path in sorted(glob.glob(os.path.join(context_dir, "*.md"))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            parts.append(f"### {name}\n{content}")
    return "\n\n".join(parts)


def run_claude(message: str) -> str:
    """Invoke Claude Code with the user message and system context."""
    task_manager_skill = load_skill("skills/task_manager.md")
    notes = load_skill("notes.md")
    project_context = load_context_files()
    base_dir = os.path.dirname(__file__)

    system_context = (
        f"You are a personal AI assistant for {USER_NAME}. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE}). "
        f"Tasks file: {TASKS_FILE}. "
        f"Run log: {RUN_LOG_FILE}. "
        f"Keep responses concise — this is a messaging interface.\n\n"
    )

    if notes:
        system_context += f"## Notes\n\n{notes}\n\n"

    if project_context:
        system_context += f"## Project Context\n\n{project_context}\n\n"

    system_context += (
        f"## Context Management\n\n"
        f"You have read/write access to persistent context files. "
        f"Automatically update them when you learn relevant information.\n\n"
        f"**notes.md** ({os.path.join(base_dir, 'notes.md')}): "
        f"General preferences, account info, recurring instructions. "
        f"Update when you learn preferences, usernames, or things Gerald asks you to remember.\n\n"
        f"**context/<project-name>.md** ({os.path.join(base_dir, 'context', '')}): "
        f"Per-project details — paths, architecture, deployment info, decisions. "
        f"Create a new file when encountering a project for the first time. "
        f"Update existing files when learning new project details.\n\n"
        f"Do NOT note: one-off tasks, general knowledge, passwords/tokens, "
        f"or anything already captured in existing files.\n\n"
    )

    if task_manager_skill:
        system_context += f"## Task Management Skill\n\n{task_manager_skill}\n\n"

    system_context += f"User message: {message}"

    result = subprocess.run(
        [CLAUDE_EXE, "-p", system_context, "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace"
    )
    return result.stdout.strip() or result.stderr.strip() or "No response from Claude."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    chat_id = None
    try:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "")

        if user_id != ALLOWED_USER_ID:
            logging.warning(f"Rejected message from unauthorized user {user_id}")
            return {"ok": True}

        if not text:
            return {"ok": True}

        logging.info(f"Received: {text}")
        send_telegram(chat_id, "⏳ Working on it...")

        response = run_claude(text)
        send_telegram(chat_id, response)
        logging.info("Responded successfully")

    except Exception as e:
        logging.error(f"Error: {e}")
        if chat_id:
            send_telegram(chat_id, f"❌ Error: {str(e)}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def startup():
    global _current_tunnel_url
    print(f"Platform: {platform.system()}")
    print(f"Claude executable: {CLAUDE_EXE}")
    load_handlers()
    static_url = os.getenv("CLOUDFLARE_TUNNEL_URL", "")
    if static_url:
        print(f"Using static URL: {static_url}")
        tunnel_url = static_url
    else:
        print("Waiting 30 seconds for network to initialize...")
        time.sleep(30)
        tunnel_url = get_tunnel_url()
    _current_tunnel_url = tunnel_url
    for attempt in range(20):
        try:
            register_webhook(tunnel_url)
            break
        except Exception as e:
            print(f"Webhook registration attempt {attempt+1} failed: {e}, retrying in 8s...")
            time.sleep(8)
    print(f"Claude Assistant Bridge running on port {PORT}")
    if not static_url:
        print(f"Tunnel health monitor active (checking every {TUNNEL_CHECK_INTERVAL}s)")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)