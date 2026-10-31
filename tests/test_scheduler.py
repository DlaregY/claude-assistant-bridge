"""
Claude Assistant Bridge — Scheduler Tests
Unit tests for the catch-up logic in runner.py.
Run: python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import get_due_time, load_last_runs, append_log


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    """Return a path to a temporary run log file."""
    return str(tmp_path / "run_log.jsonl")


def make_task(
    task_id="test-task",
    schedule_type="daily",
    time="09:00",
    days=None,
    catch_up=True,
    catch_up_window_hours=48,
    enabled=True,
    **kwargs
):
    """Helper to build a task dict."""
    schedule = {"type": schedule_type}
    if schedule_type in ("daily", "weekly", "monthly"):
        schedule["time"] = time
    if schedule_type == "weekly":
        schedule["days"] = days or ["MON"]
    if schedule_type == "monthly":
        schedule["day"] = kwargs.get("day", 1)
    if schedule_type == "once":
        schedule["datetime"] = kwargs.get("datetime", "")
    if schedule_type == "cron":
        schedule["expression"] = kwargs.get("expression", "0 9 * * *")

    return {
        "id": task_id,
        "description": "Test task",
        "schedule": schedule,
        "prompt": "Do something",
        "enabled": enabled,
        "catch_up": catch_up,
        "catch_up_window_hours": catch_up_window_hours,
        "last_run": None,
        "created": "2026-01-01T00:00:00",
        "tags": []
    }


# ---------------------------------------------------------------------------
# get_due_time — daily
# ---------------------------------------------------------------------------

class TestDailySchedule:

    def test_due_today(self):
        """Task scheduled for today should be detected as due."""
        now = datetime.now()
        due_hour = now.hour
        due_minute = max(now.minute - 2, 0)  # 2 minutes ago
        task = make_task(schedule_type="daily", time=f"{due_hour:02d}:{due_minute:02d}")
        after = datetime(2000, 1, 1)
        result = get_due_time(task, after)
        assert result is not None

    def test_not_yet_due_today(self):
        """Task scheduled for the future today should not be due."""
        now = datetime.now()
        future_hour = (now.hour + 2) % 24
        task = make_task(schedule_type="daily", time=f"{future_hour:02d}:00")
        after = datetime.now() - timedelta(minutes=1)
        result = get_due_time(task, after)
        assert result is None

    def test_due_yesterday_detected(self):
        """Task missed yesterday should be detected as due (for catch-up evaluation)."""
        yesterday = datetime.now() - timedelta(days=1)
        task = make_task(
            schedule_type="daily",
            time=f"{yesterday.hour:02d}:{yesterday.minute:02d}"
        )
        # Last run was 2 days ago
        after = datetime.now() - timedelta(days=2)
        result = get_due_time(task, after)
        assert result is not None

    def test_already_ran_today(self):
        """Task that already ran today should not appear due again."""
        now = datetime.now()
        due_minute = max(now.minute - 2, 0)
        task = make_task(schedule_type="daily", time=f"{now.hour:02d}:{due_minute:02d}")
        # Simulate last run happening AFTER the due time
        after = datetime.now() - timedelta(minutes=1)
        result = get_due_time(task, after)
        assert result is None


# ---------------------------------------------------------------------------
# get_due_time — weekly
# ---------------------------------------------------------------------------

class TestWeeklySchedule:

    def test_due_on_correct_day(self):
        """Task due on today's weekday should be detected."""
        now = datetime.now()
        day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        today = day_names[now.weekday()]
        due_minute = max(now.minute - 2, 0)
        task = make_task(
            schedule_type="weekly",
            days=[today],
            time=f"{now.hour:02d}:{due_minute:02d}"
        )
        after = datetime(2000, 1, 1)
        result = get_due_time(task, after)
        assert result is not None

    def test_not_due_on_wrong_day(self):
        """Task not scheduled for today should not be due."""
        now = datetime.now()
        day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        # Pick a day that is not today and not yesterday
        other_days = [d for i, d in enumerate(day_names)
                      if i != now.weekday() and i != (now.weekday() - 1) % 7]
        task = make_task(
            schedule_type="weekly",
            days=[other_days[0]],
            time="09:00"
        )
        after = datetime.now() - timedelta(minutes=10)
        result = get_due_time(task, after)
        assert result is None


# ---------------------------------------------------------------------------
# get_due_time — once
# ---------------------------------------------------------------------------

class TestOnceSchedule:

    def test_due_in_past(self):
        """One-time task with past datetime should be detected as due."""
        past = datetime.now() - timedelta(minutes=5)
        task = make_task(
            schedule_type="once",
            datetime=past.isoformat(timespec="seconds")
        )
        after = datetime(2000, 1, 1)
        result = get_due_time(task, after)
        assert result is not None

    def test_not_due_in_future(self):
        """One-time task with future datetime should not be due."""
        future = datetime.now() + timedelta(minutes=10)
        task = make_task(
            schedule_type="once",
            datetime=future.isoformat(timespec="seconds")
        )
        after = datetime(2000, 1, 1)
        result = get_due_time(task, after)
        assert result is None

    def test_not_due_if_already_ran(self):
        """One-time task that already ran should not fire again."""
        past = datetime.now() - timedelta(minutes=5)
        task = make_task(
            schedule_type="once",
            datetime=past.isoformat(timespec="seconds")
        )
        # Last run was after the due time
        after = datetime.now() - timedelta(minutes=3)
        result = get_due_time(task, after)
        assert result is None


# ---------------------------------------------------------------------------
# Catch-up logic
# ---------------------------------------------------------------------------

class TestCatchUpLogic:

    def test_catch_up_false_skips_missed_task(self):
        """Task with catch_up=False should not run if missed."""
        # This is tested indirectly — get_due_time returns the due time,
        # the runner then decides based on catch_up flag.
        # Here we verify the due time IS detected (runner would then skip it).
        past = datetime.now() - timedelta(hours=3)
        task = make_task(
            schedule_type="once",
            datetime=past.isoformat(timespec="seconds"),
            catch_up=False
        )
        after = datetime(2000, 1, 1)
        result = get_due_time(task, after)
        # Due time is found — it's the runner's job to apply catch_up=False
        assert result is not None

    def test_catch_up_window_detection(self):
        """Task missed by more than window should be identifiable."""
        past = datetime.now() - timedelta(hours=50)
        task = make_task(
            schedule_type="once",
            datetime=past.isoformat(timespec="seconds"),
            catch_up=True,
            catch_up_window_hours=48
        )
        after = datetime(2000, 1, 1)
        due_time = get_due_time(task, after)
        assert due_time is not None

        # Verify: hours_late > window
        hours_late = (datetime.now() - due_time).total_seconds() / 3600
        assert hours_late > task["catch_up_window_hours"]

    def test_catch_up_within_window(self):
        """Task missed within the window should have hours_late < window."""
        past = datetime.now() - timedelta(hours=24)
        task = make_task(
            schedule_type="once",
            datetime=past.isoformat(timespec="seconds"),
            catch_up=True,
            catch_up_window_hours=48
        )
        after = datetime(2000, 1, 1)
        due_time = get_due_time(task, after)
        assert due_time is not None

        hours_late = (datetime.now() - due_time).total_seconds() / 3600
        assert hours_late < task["catch_up_window_hours"]


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------

class TestRunLog:

    def test_load_last_runs_empty(self, tmp_log, monkeypatch):
        """Empty log should return empty dict."""
        open(tmp_log, "w").close()
        monkeypatch.setenv("RUN_LOG_FILE", tmp_log)
        import importlib
        import runner
        importlib.reload(runner)
        # Patch the global
        runner.RUN_LOG_FILE = tmp_log
        result = runner.load_last_runs()
        assert result == {}

    def test_load_last_runs_success_entry(self, tmp_log, monkeypatch):
        """Should return the most recent successful run per task."""
        import runner
        runner.RUN_LOG_FILE = tmp_log

        ts1 = "2026-02-20T09:00:00"
        ts2 = "2026-02-27T09:00:00"

        with open(tmp_log, "w") as f:
            f.write(json.dumps({"timestamp": ts1, "task_id": "task-a",
                                "trigger": "scheduled", "status": "success"}) + "\n")
            f.write(json.dumps({"timestamp": ts2, "task_id": "task-a",
                                "trigger": "scheduled", "status": "success"}) + "\n")

        result = runner.load_last_runs()
        assert "task-a" in result
        assert result["task-a"] == datetime.fromisoformat(ts2)

    def test_load_last_runs_ignores_errors(self, tmp_log, monkeypatch):
        """Error entries should not count as last successful run."""
        import runner
        runner.RUN_LOG_FILE = tmp_log

        ts_success = "2026-02-20T09:00:00"
        ts_error = "2026-02-27T09:00:00"

        with open(tmp_log, "w") as f:
            f.write(json.dumps({"timestamp": ts_success, "task_id": "task-a",
                                "trigger": "scheduled", "status": "success"}) + "\n")
            f.write(json.dumps({"timestamp": ts_error, "task_id": "task-a",
                                "trigger": "scheduled", "status": "error",
                                "error": "timeout"}) + "\n")

        result = runner.load_last_runs()
        # Should return the success timestamp, not the error timestamp
        assert result["task-a"] == datetime.fromisoformat(ts_success)

    def test_append_log_creates_valid_jsonl(self, tmp_log, monkeypatch):
        """append_log should write valid JSON lines."""
        import runner
        runner.RUN_LOG_FILE = tmp_log

        entry = {
            "timestamp": "2026-02-27T09:00:00",
            "task_id": "test-task",
            "trigger": "scheduled",
            "status": "success",
            "duration_seconds": 10
        }
        runner.append_log(entry)

        with open(tmp_log, "r") as f:
            lines = f.readlines()

        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["task_id"] == "test-task"
        assert parsed["status"] == "success"

    def test_append_log_is_append_only(self, tmp_log, monkeypatch):
        """Multiple appends should produce multiple lines."""
        import runner
        runner.RUN_LOG_FILE = tmp_log

        for i in range(3):
            runner.append_log({
                "timestamp": f"2026-02-27T09:0{i}:00",
                "task_id": "test-task",
                "trigger": "scheduled",
                "status": "success",
                "duration_seconds": i
            })

        with open(tmp_log, "r") as f:
            lines = [l for l in f.readlines() if l.strip()]

        assert len(lines) == 3

    def test_load_last_runs_malformed_line_skipped(self, tmp_log, monkeypatch):
        """Malformed JSON lines should be silently skipped."""
        import runner
        runner.RUN_LOG_FILE = tmp_log

        with open(tmp_log, "w") as f:
            f.write("this is not json\n")
            f.write(json.dumps({"timestamp": "2026-02-27T09:00:00", "task_id": "task-a",
                                "trigger": "scheduled", "status": "success"}) + "\n")

        result = runner.load_last_runs()
        assert "task-a" in result


# ---------------------------------------------------------------------------
# Issue #1: consumed state and monthly clamping
# ---------------------------------------------------------------------------

class _FixedDatetime(datetime):
    """datetime subclass whose now() is pinned, for get_due_time tests."""
    fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def _pin_now(monkeypatch, when):
    import runner
    _FixedDatetime.fixed = when
    monkeypatch.setattr(runner, "datetime", _FixedDatetime)


def _write_log(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestRunState:

    def test_skipped_entry_is_consumed(self, tmp_log):
        """A skipped entry must advance the search window so the same due time
        is not logged as skipped again on the next pass."""
        import runner
        runner.RUN_LOG_FILE = tmp_log
        _write_log(tmp_log, [
            {"timestamp": "2026-03-01T08:05:00", "task_id": "t", "trigger": "scheduled", "status": "skipped"},
        ])
        st = runner.load_run_state()["t"]
        assert st["consumed"] == datetime(2026, 3, 1, 8, 5)
        assert st["error_count"] == 0

    def test_errors_since_consumed_are_counted(self, tmp_log):
        import runner
        runner.RUN_LOG_FILE = tmp_log
        _write_log(tmp_log, [
            {"timestamp": "2026-03-01T08:00:00", "task_id": "t", "trigger": "scheduled", "status": "success"},
            {"timestamp": "2026-03-02T08:00:30", "task_id": "t", "trigger": "scheduled", "status": "error"},
            {"timestamp": "2026-03-02T08:10:30", "task_id": "t", "trigger": "scheduled", "status": "error"},
        ])
        st = runner.load_run_state()["t"]
        assert st["consumed"] == datetime(2026, 3, 1, 8, 0)
        assert st["error_count"] == 2
        assert st["last_error"] == datetime(2026, 3, 2, 8, 10, 30)

    def test_success_resets_error_count(self, tmp_log):
        import runner
        runner.RUN_LOG_FILE = tmp_log
        _write_log(tmp_log, [
            {"timestamp": "2026-03-02T08:00:30", "task_id": "t", "trigger": "scheduled", "status": "error"},
            {"timestamp": "2026-03-02T08:10:30", "task_id": "t", "trigger": "scheduled", "status": "success"},
        ])
        st = runner.load_run_state()["t"]
        assert st["error_count"] == 0
        assert st["consumed"] == datetime(2026, 3, 2, 8, 10, 30)

    def test_load_last_runs_still_reports_successes_only(self, tmp_log):
        """The success-only view is kept for callers that want it."""
        import runner
        runner.RUN_LOG_FILE = tmp_log
        _write_log(tmp_log, [
            {"timestamp": "2026-03-01T08:00:00", "task_id": "t", "trigger": "scheduled", "status": "success"},
            {"timestamp": "2026-03-02T08:05:00", "task_id": "t", "trigger": "scheduled", "status": "skipped"},
        ])
        assert runner.load_last_runs()["t"] == datetime(2026, 3, 1, 8, 0)


class TestMainRetryLoop:
    """Drive runner.main() against a temp log with run_task stubbed out."""

    def _setup(self, tmp_path, monkeypatch, entries, now, task):
        import runner
        log = str(tmp_path / "run_log.jsonl")
        _write_log(log, entries)
        runner.RUN_LOG_FILE = log
        monkeypatch.setattr(runner, "load_tasks", lambda: [task])
        monkeypatch.setattr(runner, "send_telegram", lambda *a, **k: None)
        calls = []
        monkeypatch.setattr(runner, "run_task", lambda t, trig, **kw: calls.append((trig, kw)) or False)
        _pin_now(monkeypatch, now)
        return runner, log, calls

    def test_missed_task_with_catch_up_false_is_skipped_once(self, tmp_path, monkeypatch):
        task = make_task(schedule_type="daily", time="08:00", catch_up=False)
        now = datetime(2026, 3, 2, 12, 0)
        runner, log, calls = self._setup(tmp_path, monkeypatch, [], now, task)
        runner.main()
        runner.main()
        runner.main()
        entries = [json.loads(l) for l in open(log) if l.strip()]
        assert [e["status"] for e in entries] == ["skipped"]
        assert calls == []

    def test_once_task_skipped_does_not_log_forever(self, tmp_path, monkeypatch):
        task = make_task(schedule_type="once", datetime="2026-03-01T08:00:00", catch_up=False)
        now = datetime(2026, 3, 2, 12, 0)
        runner, log, calls = self._setup(tmp_path, monkeypatch, [], now, task)
        for _ in range(5):
            runner.main()
        entries = [json.loads(l) for l in open(log) if l.strip()]
        assert len(entries) == 1

    def test_failing_task_backs_off_then_gives_up(self, tmp_path, monkeypatch):
        task = make_task(schedule_type="daily", time="08:00", catch_up=True, catch_up_window_hours=None)
        task["max_retries"] = 2
        due = datetime(2026, 3, 2, 8, 0)
        # two errors already logged: at 08:00:30 and 08:10:30
        entries = [
            {"timestamp": "2026-03-02T08:00:30", "task_id": task["id"], "trigger": "scheduled", "status": "error"},
            {"timestamp": "2026-03-02T08:10:30", "task_id": task["id"], "trigger": "catch_up", "status": "error"},
        ]
        # 08:15: inside the 20-minute backoff after the second error -> no attempt
        runner, log, calls = self._setup(tmp_path, monkeypatch, entries, due + timedelta(minutes=15), task)
        runner.main()
        assert calls == []
        # 08:35: backoff elapsed -> third and final attempt
        _pin_now(monkeypatch, due + timedelta(minutes=35))
        runner.main()
        assert len(calls) == 1 and calls[0][1] == {"attempt": 3, "max_attempts": 3}
        # a third error is logged by the real run_task; simulate it, then no more attempts today
        with open(log, "a") as f:
            f.write(json.dumps({"timestamp": "2026-03-02T08:35:30", "task_id": task["id"],
                                "trigger": "catch_up", "status": "error"}) + "\n")
        _pin_now(monkeypatch, due + timedelta(hours=6))
        runner.main()
        assert len(calls) == 1
        # next day's due time is found normally
        _pin_now(monkeypatch, datetime(2026, 3, 3, 8, 2))
        runner.main()
        assert len(calls) == 2 and calls[1][1]["attempt"] == 1


class TestMonthlyClamp:

    def test_day_31_fires_on_last_day_of_short_month(self, monkeypatch):
        _pin_now(monkeypatch, datetime(2026, 4, 30, 9, 1))
        task = make_task(schedule_type="monthly", time="09:00", day=31)
        assert get_due_time(task, datetime(2000, 1, 1)) == datetime(2026, 4, 30, 9, 0)

    def test_day_31_not_due_before_last_day(self, monkeypatch):
        _pin_now(monkeypatch, datetime(2026, 4, 29, 9, 1))
        task = make_task(schedule_type="monthly", time="09:00", day=31)
        assert get_due_time(task, datetime(2026, 3, 31, 9, 0)) is None

    def test_missed_day_31_caught_up_in_short_month(self, monkeypatch):
        """PC off on 31 March: the 1 April pass must still see the March due time."""
        _pin_now(monkeypatch, datetime(2026, 4, 1, 10, 0))
        task = make_task(schedule_type="monthly", time="09:00", day=31)
        assert get_due_time(task, datetime(2026, 2, 28, 9, 0)) == datetime(2026, 3, 31, 9, 0)

    def test_day_31_in_long_month_unchanged(self, monkeypatch):
        _pin_now(monkeypatch, datetime(2026, 5, 31, 9, 1))
        task = make_task(schedule_type="monthly", time="09:00", day=31)
        assert get_due_time(task, datetime(2000, 1, 1)) == datetime(2026, 5, 31, 9, 0)
