"""
Claude Assistant Bridge — Linux Service Registration
Creates systemd unit files for the webhook server and cron entry for the runner.
Called by setup.py on Linux. Requires sudo for systemd installation.
"""

import os
import sys
import subprocess
import platform
import getpass

if platform.system() != "Linux":
    print("This module is for Linux only.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list, description: str, use_sudo: bool = False) -> bool:
    """Run a command, print result, return True on success."""
    print(f"  → {description}...")
    if use_sudo:
        cmd = ["sudo"] + cmd
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"    ✅ Done")
        return True
    else:
        print(f"    ❌ Failed: {result.stderr.strip() or result.stdout.strip()}")
        return False


def write_file(path: str, content: str, use_sudo: bool = False) -> bool:
    """Write content to a file, optionally using sudo via tee."""
    print(f"  → Writing {path}...")
    try:
        if use_sudo:
            proc = subprocess.run(
                ["sudo", "tee", path],
                input=content, capture_output=True, text=True
            )
            if proc.returncode != 0:
                print(f"    ❌ Failed: {proc.stderr.strip()}")
                return False
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
        print(f"    ✅ Done")
        return True
    except Exception as e:
        print(f"    ❌ Failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Systemd unit file for webhook server
# ---------------------------------------------------------------------------

WEBHOOK_SERVICE_TEMPLATE = """[Unit]
Description=Claude Assistant Bridge — Webhook Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={project_dir}
ExecStart={python_exe} {project_dir}/webhook_server.py
Restart=on-failure
RestartSec=10
StandardOutput=append:{logs_dir}/webhook.log
StandardError=append:{logs_dir}/webhook.log
Environment="PATH={path}:/usr/lib/node_modules/.bin"
Environment="HOME=/home/{user}"

[Install]
WantedBy=multi-user.target
"""


def install_webhook_service(project_dir: str, logs_dir: str) -> bool:
    """Create and enable the webhook server systemd service."""
    print("\n[1/2] Installing webhook server as a systemd service...")

    user = getpass.getuser()
    python_exe = sys.executable
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    unit_content = WEBHOOK_SERVICE_TEMPLATE.format(
        user=user,
        project_dir=project_dir,
        python_exe=python_exe,
        logs_dir=logs_dir,
        path=path
    )

    unit_path = "/etc/systemd/system/claude-assistant-bridge.service"

    ok = write_file(unit_path, unit_content, use_sudo=True)
    if not ok:
        return False

    run(["systemctl", "daemon-reload"], "Reloading systemd", use_sudo=True)
    run(["systemctl", "enable", "claude-assistant-bridge"], "Enabling service on boot", use_sudo=True)
    ok = run(["systemctl", "start", "claude-assistant-bridge"], "Starting service", use_sudo=True)

    # Verify
    result = subprocess.run(
        ["systemctl", "is-active", "claude-assistant-bridge"],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "active":
        print("    ✅ Webhook server is running")
        return True
    else:
        print(f"    ⚠️  Service status: {result.stdout.strip()}")
        print("    Run: sudo journalctl -u claude-assistant-bridge -n 50")
        return False


# ---------------------------------------------------------------------------
# Cron entry for runner
# ---------------------------------------------------------------------------

def install_runner_cron(project_dir: str, interval_minutes: int = 5) -> bool:
    """Add a cron entry to run runner.py every N minutes."""
    print("\n[2/2] Installing task runner as a cron job...")

    python_exe = sys.executable
    runner_path = os.path.join(project_dir, "runner.py")
    log_path = os.path.join(project_dir, "logs", "runner.log")
    cron_comment = "# Claude Assistant Bridge — task runner"
    cron_line = f"*/{interval_minutes} * * * * {python_exe} {runner_path} >> {log_path} 2>&1"

    # Read existing crontab
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    # Remove any existing CAB runner entries
    lines = [
        line for line in existing.splitlines()
        if "claude-assistant-bridge" not in line.lower()
        and "runner.py" not in line
        and "Claude Assistant Bridge" not in line
    ]

    # Add new entry
    lines.append(cron_comment)
    lines.append(cron_line)
    new_crontab = "\n".join(lines) + "\n"

    # Install
    proc = subprocess.run(
        ["crontab", "-"],
        input=new_crontab, capture_output=True, text=True
    )
    if proc.returncode == 0:
        print(f"    ✅ Cron job added (every {interval_minutes} minutes)")
        return True
    else:
        print(f"    ❌ Failed: {proc.stderr.strip()}")
        return False


# ---------------------------------------------------------------------------
# Main installer (called by setup.py)
# ---------------------------------------------------------------------------

def install_all(project_dir: str, logs_dir: str, runner_interval: int = 5):
    """
    Full Linux service installation.
    Installs systemd service for webhook server and cron job for runner.
    """
    print("\n=== Linux Service Installation ===")
    print(f"Project directory: {project_dir}")
    print(f"Logs directory: {logs_dir}")

    os.makedirs(logs_dir, exist_ok=True)

    results = []
    results.append(install_webhook_service(project_dir, logs_dir))
    results.append(install_runner_cron(project_dir, runner_interval))

    print("\n=== Installation Summary ===")
    labels = ["webhook server (systemd)", "task runner (cron)"]
    all_ok = True
    for label, ok in zip(labels, results):
        status = "✅" if ok else "❌"
        print(f"  {status} {label}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n✅ All services installed successfully.")
        print("   The webhook server is running now and will auto-start on reboot.")
        print("   The task runner will fire every 5 minutes via cron.")
    else:
        print("\n⚠️  Some services failed. Check the output above.")
        print("   For webhook server logs: sudo journalctl -u claude-assistant-bridge -f")
        print("   For runner logs: tail -f logs/runner.log")

    return all_ok


def uninstall_all():
    """Remove all registered services and cron entries."""
    print("\n=== Uninstalling Claude Assistant Bridge services ===")

    print("  Stopping and removing systemd service...")
    subprocess.run(["sudo", "systemctl", "stop", "claude-assistant-bridge"], capture_output=True)
    subprocess.run(["sudo", "systemctl", "disable", "claude-assistant-bridge"], capture_output=True)
    subprocess.run(["sudo", "rm", "-f", "/etc/systemd/system/claude-assistant-bridge.service"], capture_output=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], capture_output=True)

    print("  Removing cron entry...")
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        lines = [
            line for line in result.stdout.splitlines()
            if "runner.py" not in line and "Claude Assistant Bridge" not in line
        ]
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       capture_output=True, text=True)

    print("✅ All services removed.")


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(project_dir, "logs")
    install_all(project_dir, logs_dir)
