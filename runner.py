"""
Claude Assistant Bridge — Task Runner
Reads tasks.json, compares against run_log.jsonl, fires any due or missed tasks.
Designed to be run every 5 minutes via Windows Task Scheduler or Linux cron.
"""

import os
import calendar
import glob
import json
import platform
import subprocess
import requests
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

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
TASKS_FILE = os.getenv("TASKS_FILE")
RUN_LOG_FILE = os.getenv("RUN_LOG_FILE")
LOGS_DIR = os.getenv("LOGS_DIR")
USER_NAME = os.getenv("USER_DISPLAY_NAME", "User")
TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")

# A failing task is retried with exponential backoff (10, 20, 40 ... minutes)
# and abandoned after this many consecutive errors. Per-task "max_retries" in
# tasks.json overrides it. 0 means a single attempt.
DEFAULT_MAX_RETRIES = int(os.getenv("TASK_MAX_RETRIES", "2"))
RETRY_BASE_MINUTES = 10

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
        return "claude"

    versioned = [c for c in candidates if "claude-code" in c]
    if versioned:
        return sorted(versioned)[-1]

    return candidates[0]


def _resolve_claude_exe() -> str:
    """Resolve Claude executable path. Env var always wins."""
    if os.getenv("CLAUDE_EXE"):
        return os.getenv("CLAUDE_EXE")
    if IS_WINDOWS:
        return _find_claude_windows()
    return "claude"


CLAUDE_EXE = _resolve_claude_exe()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOGS_DIR, "runner.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def redact(text: str) -> str:
    """Strip the bot token from anything that gets logged or sent (requests
    errors embed the full URL, which includes the token)."""
    if BOT_TOKEN and text:
        return text.replace(BOT_TOKEN, "<bot-token>")
    return text


def send_telegram(text: str):
    """Send a message to the whitelisted user."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ALLOWED_USER_ID, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {redact(str(e))}")


def load_tasks() -> list:
    """Load enabled tasks from tasks.json."""
    if not os.path.exists(TASKS_FILE):
        logging.warning(f"tasks.json not found at {TASKS_FILE}")
        return []
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [t for t in data.get("tasks", []) if t.get("enabled", False)]


def load_last_runs() -> dict:
    """
    Read run_log.jsonl and return a dict of task_id -> datetime of last successful run.
    """
    last_runs = {}
    if not os.path.exists(RUN_LOG_FILE):
        return last_runs
    with open(RUN_LOG_FILE, "r", encoding="utf-8") as f:
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


def load_run_state() -> dict:
    """
    Read run_log.jsonl and return, per task_id:
      consumed    - datetime after which the next due time is searched: the latest
                    success or skipped entry, or the latest error once the task
                    has exhausted its retries (see max_retries in main()).
      error_count - consecutive errors since that point
      last_error  - datetime of the most recent of those errors
    Treating skipped and exhausted-error entries as consumed is what stops a
    missed or failing task from being re-evaluated on every 5-minute pass.
    """
    state = {}
    if not os.path.exists(RUN_LOG_FILE):
        return state
    with open(RUN_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                task_id = entry["task_id"]
                ts = datetime.fromisoformat(entry["timestamp"])
                status = entry.get("status")
            except Exception:
                continue
            st = state.setdefault(task_id, {"consumed": None, "error_count": 0, "last_error": None})
            if status in ("success", "skipped"):
                if st["consumed"] is None or ts > st["consumed"]:
                    st["consumed"] = ts
                    st["error_count"] = 0
                    st["last_error"] = None
            elif status == "error":
                if st["consumed"] is None or ts > st["consumed"]:
                    st["error_count"] += 1
                    if st["last_error"] is None or ts > st["last_error"]:
                        st["last_error"] = ts
    return state


def append_log(entry: dict):
    """Append a single result entry to run_log.jsonl."""
    with open(RUN_LOG_FILE, "a", encoding="utf-8") as f:
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
        candidate_yesterday = candidate - timedelta(days=1)
        if after < candidate_yesterday <= now:
            return candidate_yesterday

    elif stype == "weekly":
        days_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
        hour, minute = map(int, schedule["time"].split(":"))
        target_days = [days_map[d.upper()] for d in schedule.get("days", [])]
        for days_back in range(8):
            candidate = (now - timedelta(days=days_back)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate.weekday() in target_days and after < candidate <= now:
                return candidate

    elif stype == "monthly":
        hour, minute = map(int, schedule["time"].split(":"))
        day = schedule.get("day", 1)
        # Clamp to the month's length so day 29-31 fires on the last day of
        # shorter months instead of raising ValueError and never running.
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        candidate = now.replace(
            day=min(day, days_in_month), hour=hour, minute=minute, second=0, microsecond=0
        )
        if after < candidate <= now:
            return candidate
        first_of_month = now.replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        candidate_last = last_month.replace(
            day=min(day, last_month.day),
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if after < candidate_last <= now:
            return candidate_last

    elif stype == "once":
        due = datetime.fromisoformat(schedule["datetime"])
        if after < due <= now:
            return due

    elif stype == "cron":
        try:
            from croniter import croniter
            cron = croniter(schedule["expression"], after)
            candidate = cron.get_next(datetime)
            if candidate <= now:
                return candidate
        except ImportError:
            logging.warning("croniter not installed — skipping cron task. Run: pip install croniter")

    return None


def run_task(task: dict, trigger: str, attempt: int = 1, max_attempts: int = 1) -> bool:
    """Execute a task via Claude Code. Returns True on success."""
    task_id = task["id"]
    prompt = task["prompt"]
    system_context = (
        f"You are a personal AI assistant for {USER_NAME}. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE}). "
        f"This is a scheduled task (trigger: {trigger}). "
        f"Complete the following task and provide the result as your response. "
        f"Task: {prompt}"
    )
    start = datetime.now()
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", system_context, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
            cwd=os.path.dirname(TASKS_FILE)
        )
        duration = (datetime.now() - start).seconds
        output = result.stdout.strip()

        if result.returncode == 0 and output:
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
            raise Exception(result.stderr.strip() or "No output from Claude")

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
        logging.error(f"Task {task_id} failed (attempt {attempt}/{max_attempts}): {redact(str(e))}")
        if attempt < max_attempts:
            retry_note = f"Will retry in about {RETRY_BASE_MINUTES * 2 ** (attempt - 1)} minutes."
        else:
            retry_note = "No more retries until the next scheduled time."
        send_telegram(
            f"❌ Scheduled task failed (attempt {attempt}/{max_attempts}): [{task['description']}]\n\n"
            f"Error: {redact(str(e))}\n{retry_note}"
        )
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.info(f"Runner started (platform: {platform.system()}, claude: {CLAUDE_EXE})")
    now = datetime.now()
    tasks = load_tasks()
    run_state = load_run_state()

    if not tasks:
        logging.info("No enabled tasks found")
        return

    for task in tasks:
        task_id = task["id"]
        try:
            st = run_state.get(task_id, {"consumed": None, "error_count": 0, "last_error": None})
            max_retries = int(task.get("max_retries", DEFAULT_MAX_RETRIES))
            max_attempts = max_retries + 1
            after = st["consumed"]
            attempt = st["error_count"] + 1
            if st["error_count"] >= max_attempts:
                # Retries exhausted: the failed due time is consumed and the
                # next due time starts a fresh attempt count.
                after = max(after or datetime(2000, 1, 1), st["last_error"])
                attempt = 1
            elif st["error_count"] > 0:
                backoff = timedelta(minutes=RETRY_BASE_MINUTES * 2 ** (st["error_count"] - 1))
                if now < st["last_error"] + backoff:
                    continue
            after = after or datetime(2000, 1, 1)
            due_time = get_due_time(task, after)

            if due_time is None:
                continue

            minutes_late = (now - due_time).total_seconds() / 60
            is_catchup = minutes_late > 6

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

            run_task(task, trigger, attempt=attempt, max_attempts=max_attempts)
        except Exception as e:
            logging.error(f"Task {task_id} errored during scheduling: {redact(str(e))}")
            continue

    logging.info("Runner finished")


if __name__ == "__main__":
    main()