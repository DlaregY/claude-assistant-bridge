"""
Claude Assistant Bridge — Task Runner
Reads tasks.json, compares against run_log.jsonl, fires any due or missed tasks.
Designed to be run every 5 minutes via Windows Task Scheduler.
"""

import os
import json
import subprocess
import requests
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))
TASKS_FILE = os.getenv("TASKS_FILE")
RUN_LOG_FILE = os.getenv("RUN_LOG_FILE")
LOGS_DIR = os.getenv("LOGS_DIR")
USER_NAME = os.getenv("USER_DISPLAY_NAME", "User")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
CLAUDE_EXE = os.getenv(
    "CLAUDE_EXE",
    r"C:\Users\geral\AppData\Roaming\Claude\claude-code\2.1.51\claude.exe"
)

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOGS_DIR, "runner.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def send_telegram(text: str):
    """Send a message to the whitelisted user."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ALLOWED_USER_ID, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")


def load_tasks() -> list:
    """Load enabled tasks from tasks.json."""
    if not os.path.exists(TASKS_FILE):
        logging.warning(f"tasks.json not found at {TASKS_FILE}")
        return []
    with open(TASKS_FILE, "r") as f:
        data = json.load(f)
    return [t for t in data.get("tasks", []) if t.get("enabled", False)]


def load_last_runs() -> dict:
    """
    Read run_log.jsonl and return a dict of task_id -> datetime of last successful run.
    """
    last_runs = {}
    if not os.path.exists(RUN_LOG_FILE):
        return last_runs
    with open(RUN_LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("status") == "success":
                    task_id = entry["task_id"]
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if task_id not in last_runs or ts > last_runs[task_id]:
                        last_runs[task_id] = ts
            except Exception:
                continue
    return last_runs


def append_log(entry: dict):
    """Append a single result entry to run_log.jsonl."""
    with open(RUN_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_due_time(task: dict, after: datetime) -> datetime | None:
    """
    Return the most recent scheduled due time for a task after a given datetime.
    Returns None if the task was not due in that window.
    """
    schedule = task.get("schedule", {})
    stype = schedule.get("type")
    now = datetime.now()

    if stype == "daily":
        hour, minute = map(int, schedule["time"].split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if after < candidate <= now:
            return candidate
        # Check yesterday
        candidate_yesterday = candidate - timedelta(days=1)
        if after < candidate_yesterday <= now:
            return candidate_yesterday

    elif stype == "weekly":
        days_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
        hour, minute = map(int, schedule["time"].split(":"))
        target_days = [days_map[d.upper()] for d in schedule.get("days", [])]
        # Check last 7 days
        for days_back in range(8):
            candidate = (now - timedelta(days=days_back)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate.weekday() in target_days and after < candidate <= now:
                return candidate

    elif stype == "monthly":
        hour, minute = map(int, schedule["time"].split(":"))
        day = schedule.get("day", 1)
        try:
            candidate = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if after < candidate <= now:
                return candidate
            # Check last month
            first_of_month = now.replace(day=1)
            last_month = first_of_month - timedelta(days=1)
            candidate_last = last_month.replace(
                day=min(day, last_month.day),
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if after < candidate_last <= now:
                return candidate_last
        except ValueError:
            pass  # day doesn't exist in this month

    elif stype == "once":
        due = datetime.fromisoformat(schedule["datetime"])
        if after < due <= now:
            return due

    elif stype == "cron":
        # Basic cron support for common patterns
        # For full cron support, install: pip install croniter
        try:
            from croniter import croniter
            cron = croniter(schedule["expression"], after)
            candidate = cron.get_next(datetime)
            if candidate <= now:
                return candidate
        except ImportError:
            logging.warning("croniter not installed — skipping cron task. Run: pip install croniter")

    return None


def run_task(task: dict, trigger: str) -> bool:
    """Execute a task via Claude Code. Returns True on success."""
    task_id = task["id"]
    prompt = task["prompt"]
    system_context = (
        f"You are a personal AI assistant for {USER_NAME}. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE}). "
        f"This is a scheduled task (trigger: {trigger}). "
        f"Complete the following task and send the result to the user via Telegram "
        f"by calling the send_telegram tool or including the response naturally. "
        f"Task: {prompt}"
    )
    start = datetime.now()
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", system_context, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=300, cwd=os.path.dirname(TASKS_FILE)
        )
        duration = (datetime.now() - start).seconds
        output = result.stdout.strip()

        if result.returncode == 0 and output:
            # Send result to Telegram
            send_telegram(f"✅ [{task['description']}]\n\n{output}")
            append_log({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "task_id": task_id,
                "trigger": trigger,
                "status": "success",
                "duration_seconds": duration
            })
            logging.info(f"Task {task_id} completed successfully ({duration}s)")
            return True
        else:
            error = result.stderr.strip() or "No output"
            raise Exception(error)

    except Exception as e:
        duration = (datetime.now() - start).seconds
        append_log({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "task_id": task_id,
            "trigger": trigger,
            "status": "error",
            "duration_seconds": duration,
            "error": str(e)
        })
        logging.error(f"Task {task_id} failed: {e}")
        send_telegram(f"❌ Scheduled task failed: [{task['description']}]\n\nError: {str(e)}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.info("Runner started")
    now = datetime.now()
    tasks = load_tasks()
    last_runs = load_last_runs()

    if not tasks:
        logging.info("No enabled tasks found")
        return

    for task in tasks:
        task_id = task["id"]
        last_success = last_runs.get(task_id)

        # If never run, treat as if run at the epoch so everything looks due
        after = last_success if last_success else datetime(2000, 1, 1)

        due_time = get_due_time(task, after)

        if due_time is None:
            # Not due since last run
            continue

        # Determine if this is on-time or a catch-up
        minutes_late = (now - due_time).total_seconds() / 60
        is_catchup = minutes_late > 6  # More than one runner interval late = catch-up

        if is_catchup:
            catch_up = task.get("catch_up", False)
            window = task.get("catch_up_window_hours")

            if not catch_up:
                reason = f"catch_up=false, missed by {int(minutes_late)}min"
                append_log({
                    "timestamp": now.isoformat(timespec="seconds"),
                    "task_id": task_id,
                    "trigger": "scheduled",
                    "status": "skipped",
                    "reason": reason
                })
                logging.info(f"Task {task_id} skipped: {reason}")
                continue

            if window is not None:
                hours_late = minutes_late / 60
                if hours_late > window:
                    reason = f"missed by {hours_late:.1f}h, window={window}h"
                    append_log({
                        "timestamp": now.isoformat(timespec="seconds"),
                        "task_id": task_id,
                        "trigger": "catch_up",
                        "status": "skipped",
                        "reason": reason
                    })
                    logging.info(f"Task {task_id} skipped (outside catch-up window): {reason}")
                    continue

            trigger = "catch_up"
            logging.info(f"Task {task_id} running as catch-up (missed by {int(minutes_late)}min)")
        else:
            trigger = "scheduled"
            logging.info(f"Task {task_id} running on schedule")

        run_task(task, trigger)

    logging.info("Runner finished")


if __name__ == "__main__":
    main()