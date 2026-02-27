import os
import time
import subprocess
import requests
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import uvicorn

# Load config
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))
PORT = int(os.getenv("WEBHOOK_PORT", 8080))
TASKS_FILE = os.getenv("TASKS_FILE")
RUN_LOG_FILE = os.getenv("RUN_LOG_FILE")
LOGS_DIR = os.getenv("LOGS_DIR")
USER_NAME = os.getenv("USER_DISPLAY_NAME", "User")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

# Logging
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    filename=f"{LOGS_DIR}/webhook.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

app = FastAPI()

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
        except Exception as e:
            print(f"Waiting for cloudflared tunnel... ({i+1}/{retries})")
            time.sleep(delay)
    # Fallback to .env value if cloudflared API not available
    fallback = os.getenv("CLOUDFLARE_TUNNEL_URL", "")
    logging.warning(f"Could not detect tunnel URL, using fallback: {fallback}")
    print(f"Using fallback tunnel URL from .env: {fallback}")
    return fallback

def send_telegram(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4000):
        requests.post(url, json={"chat_id": chat_id, "text": text[i:i+4000]})

def register_webhook(tunnel_url: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{tunnel_url}/webhook"
    resp = requests.post(url, json={"url": webhook_url})
    result = resp.json()
    logging.info(f"Webhook registered: {result}")
    print(f"Webhook registered at {webhook_url} — {result.get('description', '')}")
    if not result.get("ok"):
        raise Exception(f"Telegram rejected webhook: {result.get('description')}")

def run_claude(message: str) -> str:
    system_context = (
        f"You are a personal AI assistant for {USER_NAME}. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE}). "
        f"Tasks file: {TASKS_FILE}. "
        f"Run log: {RUN_LOG_FILE}. "
        f"When the user asks to schedule, list, modify or cancel tasks, read/write the tasks file directly. "
        f"When the user asks about task history or failures, read the run log. "
        f"Keep responses concise — this is a messaging interface. "
        f"User message: {message}"
    )
    result = subprocess.run(
        [r"C:\Users\geral\AppData\Roaming\Claude\claude-code\2.1.51\claude.exe", "-p", system_context, "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip() or result.stderr.strip() or "No response from Claude."

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
        logging.info(f"Responded successfully")

    except Exception as e:
        logging.error(f"Error: {e}")
        if chat_id:
            send_telegram(chat_id, f"❌ Error: {str(e)}")

    return {"ok": True}

@app.on_event("startup")
async def startup():
    print("Waiting 30 seconds for network to initialize...")
    time.sleep(30)
    tunnel_url = get_tunnel_url()
    # Retry webhook registration until network is ready
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