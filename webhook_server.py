"""
Claude Assistant Bridge — Webhook Server
Receives Telegram messages and routes them to Claude Code for execution.
Runs as a persistent service (Windows: Task Scheduler, Linux: systemd).
"""

import os
import glob
import time
import platform
import subprocess
import requests
import logging
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
    yield

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


def send_telegram(chat_id: int, text: str):
    """Send a message to a Telegram chat, splitting if over 4000 chars."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4000):
        requests.post(url, json={"chat_id": chat_id, "text": text[i:i+4000]})


def register_webhook(tunnel_url: str):
    """Register the webhook URL with Telegram. Raises on failure."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{tunnel_url}/webhook"
    resp = requests.post(url, json={"url": webhook_url})
    result = resp.json()
    logging.info(f"Webhook registered: {result}")
    print(f"Webhook registered at {webhook_url} — {result.get('description', '')}")
    if not result.get("ok"):
        raise Exception(f"Telegram rejected webhook: {result.get('description')}")


def load_skill(skill_path: str) -> str:
    """Load a skill file and return its contents, or empty string if not found."""
    full_path = os.path.join(os.path.dirname(__file__), skill_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def run_claude(message: str) -> str:
    """Invoke Claude Code with the user message and system context."""
    task_manager_skill = load_skill("skills/task_manager.md")

    system_context = (
        f"You are a personal AI assistant for {USER_NAME}. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE}). "
        f"Tasks file: {TASKS_FILE}. "
        f"Run log: {RUN_LOG_FILE}. "
        f"Keep responses concise — this is a messaging interface.\n\n"
    )

    if task_manager_skill:
        system_context += f"## Task Management Skill\n\n{task_manager_skill}\n\n"

    system_context += f"User message: {message}"

    result = subprocess.run(
        [CLAUDE_EXE, "-p", system_context, "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=120,
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
    print(f"Platform: {platform.system()}")
    print(f"Claude executable: {CLAUDE_EXE}")
    print("Waiting 30 seconds for network to initialize...")
    time.sleep(30)
    tunnel_url = get_tunnel_url()
    for attempt in range(20):
        try:
            register_webhook(tunnel_url)
            break
        except Exception as e:
            print(f"Webhook registration attempt {attempt+1} failed: {e}, retrying in 8s...")
            time.sleep(8)
    print(f"Claude Assistant Bridge running on port {PORT}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)