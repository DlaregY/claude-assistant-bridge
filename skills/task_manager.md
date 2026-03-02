# Task Manager Skill

You have the ability to create, read, update, and delete scheduled tasks on behalf of the user. Tasks are stored in a JSON file on the user's computer. You can also query the run log to answer questions about task history.

---

## Files

- **Tasks file:** Defined in the TASKS_FILE environment variable (e.g. `C:/AIAssistant/tasks.json`)
- **Run log:** Defined in the RUN_LOG_FILE environment variable (e.g. `C:/AIAssistant/run_log.jsonl`)

Always read the current tasks.json before making any changes so you don't overwrite existing tasks.

---

## tasks.json Structure

```json
{
  "version": "1.0",
  "tasks": [
    {
      "id": "unique-kebab-case-id",
      "description": "Short human-readable description",
      "schedule": { ... },
      "prompt": "The exact instruction Claude Code will execute when this task fires.",
      "enabled": true,
      "catch_up": true,
      "catch_up_window_hours": 48,
      "last_run": null,
      "created": "2026-01-01T00:00:00",
      "tags": ["optional", "tags"]
    }
  ]
}
```

---

## Schedule Types

### daily
```json
"schedule": { "type": "daily", "time": "09:00" }
```

### weekly
```json
"schedule": { "type": "weekly", "days": ["MON", "WED", "FRI"], "time": "09:00" }
```
Valid day values: MON TUE WED THU FRI SAT SUN

### monthly
```json
"schedule": { "type": "monthly", "day": 1, "time": "09:00" }
```

### once
```json
"schedule": { "type": "once", "datetime": "2026-03-01T14:00:00" }
```

### cron
```json
"schedule": { "type": "cron", "expression": "0 9 * * 1-5" }
```

---

## Catch-Up Rules

`catch_up` controls what happens if the PC was off when a task was due.

| Scenario | catch_up | catch_up_window_hours |
|----------|----------|----------------------|
| Time-sensitive (morning message, reminders) | false | null |
| Work tasks (reports, summaries) | true | 48 |
| Critical tasks (must always run) | true | null |

**Default when user doesn't specify:** use `catch_up: true` and `catch_up_window_hours: 48` unless the task is clearly time-sensitive.

---

## Writing Task Prompts

The `prompt` field is what Claude Code actually executes. Write it as a clear, self-contained instruction:

**Good:**
> "Check the Downloads folder and summarize any files added in the last 7 days. Include file names, sizes, and types."

**Bad:**
> "Check downloads"

Always include:
- Specific file paths if relevant
- What output to produce
- Any relevant context (e.g. "this runs every Monday")

The prompt does NOT need to say "send to Telegram" — that's handled automatically by the runner.

---

## Operations

### Adding a task

1. Read the current tasks.json
2. Generate a unique kebab-case `id` (e.g. `weekly-downloads-summary`)
3. Set `created` to the current datetime
4. Set `last_run` to null
5. Set `enabled` to true
6. Write the updated file

Always confirm back to the user: what the task will do, when it will run, and whether it will catch up if missed.

### Listing tasks

Read tasks.json and present a clean summary. Example format:
```
📋 Your scheduled tasks:

1. Weekly Downloads Summary [weekly-downloads-summary]
   Every Monday at 9:00am | Catch-up: yes (48hr window)
   Status: enabled

2. Morning Standup [morning-standup]
   Weekdays at 8:00am | Catch-up: no
   Status: enabled
```

### Disabling / enabling a task

Set `enabled: false` to pause, `enabled: true` to resume. Never delete unless user explicitly asks to delete.

### Deleting a task

Remove the entry from the tasks array entirely. Confirm with the user before doing this.

### Modifying a task

Read → update the specific field(s) → write. Do not change fields the user didn't mention.

### Running a task immediately

The user may ask to run a task "right now" or "immediately." In this case:
1. Find the task in tasks.json
2. Execute its prompt directly yourself (don't wait for the runner)
3. Append a manual log entry to run_log.jsonl with `"trigger": "manual"`

---

## Querying the Run Log

run_log.jsonl is an append-only file. Each line is a JSON object:

```json
{"timestamp": "2026-02-27T09:02:14", "task_id": "weekly-review", "trigger": "scheduled", "status": "success", "duration_seconds": 18}
{"timestamp": "2026-02-27T09:02:14", "task_id": "morning-standup", "trigger": "scheduled", "status": "skipped", "reason": "catch_up=false, missed by 360min"}
{"timestamp": "2026-02-27T09:05:01", "task_id": "weekly-review", "trigger": "manual", "status": "error", "error": "Claude Code timeout"}
```

**status values:** success, error, skipped
**trigger values:** scheduled, catch_up, manual

Common queries:
- "What ran today?" → filter by timestamp date
- "Did anything fail this week?" → filter status=error, last 7 days
- "What was skipped while my PC was off?" → filter status=skipped
- "When did X last run?" → filter by task_id, status=success, most recent

---

## ID Generation Rules

- Lowercase kebab-case only: `weekly-report` not `Weekly Report`
- Descriptive but concise: `morning-standup` not `task-1`
- Never reuse an existing ID
- Max 40 characters
