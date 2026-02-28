#!/usr/bin/env python3
"""
Claude Assistant Bridge — Setup Wizard
Guides a new user through full installation on Windows or Linux.
Run: python setup.py
"""

import os
import sys
import json
import platform
import subprocess
import shutil
from datetime import datetime

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def header(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def section(text: str):
    print(f"\n--- {text} ---")


def success(text: str):
    print(f"  ✅ {text}")


def warn(text: str):
    print(f"  ⚠️  {text}")


def error(text: str):
    print(f"  ❌ {text}")


def ask(prompt: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        value = input(f"  {prompt} [{default}]: ").strip()
        return value if value else default
    else:
        while True:
            value = input(f"  {prompt}: ").strip()
            if value:
                return value
            print("  (required — please enter a value)")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no."""
    hint = "Y/n" if default else "y/N"
    value = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not value:
        return default
    return value.startswith("y")


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

def check_python():
    section("Checking Python version")
    version = sys.version_info
    if version.major == 3 and version.minor >= 11:
        success(f"Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        error(f"Python 3.11+ required. Found: {version.major}.{version.minor}")
        print("  Download from: https://python.org/downloads")
        return False


def check_claude_code():
    section("Checking Claude Code")
    if IS_WINDOWS:
        from webhook_server import _find_claude_windows
        exe = _find_claude_windows()
    else:
        exe = shutil.which("claude") or "claude"

    result = subprocess.run(
        [exe, "--version"], capture_output=True, text=True
    )
    if result.returncode == 0:
        success(f"Claude Code found: {exe}")
        success(f"Version: {result.stdout.strip()}")
        return exe
    else:
        error("Claude Code not found.")
        print("  Install from: https://claude.ai/code")
        print("  After installing, re-run this setup wizard.")
        return None


def check_cloudflared():
    section("Checking cloudflared")
    result = subprocess.run(
        ["cloudflared", "--version"], capture_output=True, text=True
    )
    if result.returncode == 0:
        success(f"cloudflared: {result.stdout.strip()}")
        return True
    else:
        warn("cloudflared not found.")
        if IS_WINDOWS:
            print("  Installing via winget...")
            ok = subprocess.run(
                ["winget", "install", "Cloudflare.cloudflared"],
                capture_output=False
            )
            return ok.returncode == 0
        else:
            print("  Install with:")
            print("    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared")
            print("    chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/")
            input("  Press Enter once cloudflared is installed...")
            return True


def check_nssm():
    if not IS_WINDOWS:
        return True
    section("Checking NSSM")
    result = subprocess.run(["nssm", "version"], capture_output=True, text=True)
    if result.returncode == 0:
        success(f"NSSM found")
        return True
    else:
        warn("NSSM not found.")
        print("  Installing via winget...")
        ok = subprocess.run(
            ["winget", "install", "NSSM.NSSM"],
            capture_output=False
        )
        return ok.returncode == 0


def install_python_deps(project_dir: str):
    section("Installing Python dependencies")
    req_file = os.path.join(project_dir, "requirements.txt")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        success("Dependencies installed")
        return True
    else:
        error(f"pip install failed: {result.stderr.strip()}")
        return False


# ---------------------------------------------------------------------------
# Telegram setup
# ---------------------------------------------------------------------------

def setup_telegram():
    section("Telegram Bot Setup")
    print()
    print("  You need a Telegram bot token and your personal user ID.")
    print()
    print("  Step 1 — Create a bot:")
    print("    1. Open Telegram and search for @BotFather")
    print("    2. Send: /newbot")
    print("    3. Follow the prompts to name your bot")
    print("    4. Copy the token BotFather gives you")
    print()
    bot_token = ask("Paste your bot token here")

    print()
    print("  Step 2 — Find your user ID:")
    print("    1. In Telegram, search for @userinfobot")
    print("    2. Send: /start")
    print("    3. Copy the 'Id' number it shows you")
    print()
    user_id = ask("Paste your Telegram user ID (numbers only)")

    try:
        int(user_id)
    except ValueError:
        error("User ID must be a number. Please re-run setup.")
        sys.exit(1)

    return bot_token, user_id


# ---------------------------------------------------------------------------
# Path and identity setup
# ---------------------------------------------------------------------------

def setup_paths():
    section("File Paths and Identity")

    if IS_WINDOWS:
        default_dir = "C:/AIAssistant"
    else:
        default_dir = os.path.expanduser("~/claude-assistant-bridge")

    print(f"\n  Where should CAB store its data files?")
    data_dir = ask("Data directory", default_dir)
    data_dir = data_dir.replace("\\", "/")

    user_name = ask("Your first name (used in Claude prompts)", "User")

    print("\n  Your timezone (used in task scheduling)")
    print("  Examples: America/Chicago, America/New_York, America/Los_Angeles, Europe/London")
    timezone = ask("Timezone", "America/Chicago")

    return {
        "data_dir": data_dir,
        "tasks_file": f"{data_dir}/tasks.json",
        "run_log_file": f"{data_dir}/run_log.jsonl",
        "logs_dir": f"{data_dir}/logs",
        "user_name": user_name,
        "timezone": timezone,
    }


# ---------------------------------------------------------------------------
# Write config files
# ---------------------------------------------------------------------------

def write_env(project_dir: str, bot_token: str, user_id: str, paths: dict,
              claude_exe: str = "", tunnel_url: str = "", port: int = 8080):
    section("Writing .env file")
    env_path = os.path.join(project_dir, ".env")

    lines = [
        "# Claude Assistant Bridge — Environment Configuration",
        "# Generated by setup.py on " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "# Telegram",
        f"TELEGRAM_BOT_TOKEN={bot_token}",
        f"TELEGRAM_ALLOWED_USER_ID={user_id}",
        "",
        "# Cloudflare Tunnel (fallback — auto-detected at runtime)",
        f"CLOUDFLARE_TUNNEL_URL={tunnel_url}",
        "",
        "# Local server",
        f"WEBHOOK_PORT={port}",
        "",
        "# File paths",
        f"TASKS_FILE={paths['tasks_file']}",
        f"RUN_LOG_FILE={paths['run_log_file']}",
        f"LOGS_DIR={paths['logs_dir']}",
        "",
        "# Identity",
        f"USER_DISPLAY_NAME={paths['user_name']}",
        f"TIMEZONE={paths['timezone']}",
    ]

    if claude_exe:
        lines += ["", "# Claude executable (auto-detected — override if needed)", f"CLAUDE_EXE={claude_exe}"]

    with open(env_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    success(".env written")


def create_data_files(paths: dict):
    section("Creating data directories and files")

    os.makedirs(paths["data_dir"], exist_ok=True)
    os.makedirs(paths["logs_dir"], exist_ok=True)

    # tasks.json
    tasks_path = paths["tasks_file"]
    if not os.path.exists(tasks_path):
        initial = {
            "version": "1.0",
            "tasks": []
        }
        with open(tasks_path, "w") as f:
            json.dump(initial, f, indent=2)
        success(f"Created tasks.json")
    else:
        warn("tasks.json already exists — skipping")

    # run_log.jsonl
    log_path = paths["run_log_file"]
    if not os.path.exists(log_path):
        open(log_path, "w").close()
        success("Created run_log.jsonl")
    else:
        warn("run_log.jsonl already exists — skipping")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def send_test_message(bot_token: str, user_id: str) -> bool:
    section("Sending test message to Telegram")
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": int(user_id),
            "text": "✅ Claude Assistant Bridge is set up and ready! Send me a message to get started."
        }, timeout=10)
        if resp.json().get("ok"):
            success("Test message sent — check Telegram!")
            return True
        else:
            error(f"Telegram error: {resp.json().get('description')}")
            return False
    except Exception as e:
        error(f"Could not reach Telegram: {e}")
        return False


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def main():
    header("Claude Assistant Bridge — Setup Wizard")
    print(f"\n  Platform: {platform.system()}")
    print(f"  Python:   {sys.version.split()[0]}")
    print()
    print("  This wizard will set up your personal AI assistant.")
    print("  It takes about 10-15 minutes.")
    print()
    input("  Press Enter to begin...")

    project_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Dependency checks ---
    header("Step 1: Checking Dependencies")

    if not check_python():
        sys.exit(1)

    claude_exe = check_claude_code()
    if not claude_exe:
        sys.exit(1)

    if not check_cloudflared():
        error("cloudflared is required. Please install it and re-run setup.")
        sys.exit(1)

    if IS_WINDOWS and not check_nssm():
        error("NSSM is required on Windows. Please install it and re-run setup.")
        sys.exit(1)

    if not install_python_deps(project_dir):
        sys.exit(1)

    # --- Telegram ---
    header("Step 2: Telegram Configuration")
    bot_token, user_id = setup_telegram()

    # --- Paths ---
    header("Step 3: File Paths and Identity")
    paths = setup_paths()

    # --- Write config ---
    header("Step 4: Writing Configuration")
    write_env(
        project_dir=project_dir,
        bot_token=bot_token,
        user_id=user_id,
        paths=paths,
        claude_exe=claude_exe if IS_WINDOWS else "",
    )
    create_data_files(paths)

    # --- Services ---
    header("Step 5: Installing Services")

    if IS_WINDOWS:
        print("\n  ⚠️  The next step requires Administrator privileges.")
        print("  If prompted by Windows UAC, click Yes.")
        proceed = ask_yes_no("Install Windows services now?", default=True)
        if proceed:
            from services.windows import install_all
            install_all(project_dir)
    else:
        print("\n  Installing systemd service and cron job.")
        print("  You may be prompted for your sudo password.")
        proceed = ask_yes_no("Install Linux services now?", default=True)
        if proceed:
            from services.linux import install_all
            install_all(project_dir, paths["logs_dir"])

    # --- Verification ---
    header("Step 6: Verification")

    import requests as req_check
    send_test_message(bot_token, user_id)

    # --- Done ---
    header("Setup Complete!")
    print()
    print("  Your Claude Assistant Bridge is ready.")
    print()
    print("  Try sending your bot a message on Telegram:")
    print('    "What time is it?"')
    print('    "Add a task: every weekday at 8am send me a good morning message"')
    print('    "What tasks do I have scheduled?"')
    print()
    if IS_WINDOWS:
        print("  Services installed:")
        print("    • cloudflared tunnel (NSSM service, auto-starts on boot)")
        print("    • webhook server (Task Scheduler, runs on login)")
        print("    • task runner (Task Scheduler, runs every 5 minutes)")
        print()
        print("  Reboot your PC to verify everything starts automatically.")
    else:
        print("  Services installed:")
        print("    • webhook server (systemd, auto-starts on boot)")
        print("    • task runner (cron, runs every 5 minutes)")
    print()
    print("  Docs: https://github.com/DlaregY/claude-assistant-bridge")
    print()


if __name__ == "__main__":
    main()
