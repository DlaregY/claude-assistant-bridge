"""
Claude Assistant Bridge — Windows Service Registration
Registers cloudflared, webhook server, and task runner as persistent Windows services.
Called by setup.py on Windows. Requires admin privileges.
"""

import os
import sys
import subprocess
import platform

if platform.system() != "Windows":
    print("This module is for Windows only.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list, description: str) -> bool:
    """Run a command, print result, return True on success."""
    print(f"  → {description}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"    ✅ Done")
        return True
    else:
        print(f"    ❌ Failed: {result.stderr.strip() or result.stdout.strip()}")
        return False


def is_admin() -> bool:
    """Check if running as administrator."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_current_username() -> str:
    """Get the current Windows username."""
    return os.environ.get("USERNAME", os.environ.get("USER", ""))


# ---------------------------------------------------------------------------
# Power / battery fix
# ---------------------------------------------------------------------------

def _fix_power_settings(task_name: str) -> None:
    """
    Allow a scheduled task to start on battery and not stop when switching
    to battery. The schtasks CLI doesn't expose these settings, so we
    shell out to PowerShell.
    """
    ps_script = (
        f"$s = New-ScheduledTaskSettingsSet"
        f" -AllowStartIfOnBatteries"
        f" -DontStopIfGoingOnBatteries"
        f" -ExecutionTimeLimit (New-TimeSpan -Hours 72);"
        f" Set-ScheduledTask -TaskName '{task_name}' -Settings $s"
    )
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"    ✅ Power settings fixed (runs on battery)")
    else:
        print(f"    ⚠️  Could not fix power settings: {result.stderr.strip()}")
        print(f"       You may need to manually allow battery operation in Task Scheduler.")


# ---------------------------------------------------------------------------
# Individual service registrations
# ---------------------------------------------------------------------------

def install_cloudflared(tunnel_port: int = 8080) -> bool:
    """
    Register cloudflared as a Windows service via NSSM.
    Creates a persistent tunnel to localhost:<tunnel_port>.
    """
    print("\n[1/3] Registering cloudflared as a Windows service...")

    # Remove existing service if present
    subprocess.run(
        ["nssm", "remove", "cloudflared-tunnel", "confirm"],
        capture_output=True
    )

    ok = run(
        ["nssm", "install", "cloudflared-tunnel",
         "cloudflared", "tunnel", "--url", f"http://localhost:{tunnel_port}"],
        "Installing cloudflared service"
    )
    if not ok:
        return False

    run(
        ["nssm", "set", "cloudflared-tunnel", "Start", "SERVICE_AUTO_START"],
        "Setting auto-start"
    )
    run(
        ["nssm", "start", "cloudflared-tunnel"],
        "Starting cloudflared service"
    )

    # Verify
    result = subprocess.run(
        ["nssm", "status", "cloudflared-tunnel"],
        capture_output=True, text=True
    )
    if "SERVICE_RUNNING" in result.stdout:
        print("    ✅ cloudflared is running")
        return True
    else:
        print(f"    ⚠️  Status: {result.stdout.strip()}")
        return False


def install_webhook_server(project_dir: str, username: str, password: str = None) -> bool:
    """
    Register the webhook server as a Task Scheduler task that runs at login.
    Runs as the specified user so Claude Code credentials are available.
    """
    print("\n[2/3] Registering webhook server as a startup task...")

    # Remove existing task if present
    subprocess.run(
        ["schtasks", "/delete", "/tn", "Claude Assistant Bridge", "/f"],
        capture_output=True
    )

    webhook_path = os.path.join(project_dir, "webhook_server.py")
    python_exe = sys.executable

    cmd = [
        "schtasks", "/create",
        "/tn", "Claude Assistant Bridge",
        "/tr", f"{python_exe} {webhook_path}",
        "/sc", "onlogon",
        "/ru", username,
        "/rl", "highest",
        "/f"
    ]

    if password:
        cmd.extend(["/rp", password])

    ok = run(cmd, f"Creating Task Scheduler entry (runs as {username})")
    if not ok:
        return False

    # Fix battery/power settings — schtasks CLI doesn't expose these,
    # so use PowerShell to allow start on battery and prevent stopping
    _fix_power_settings("Claude Assistant Bridge")

    ok = run(
        ["schtasks", "/run", "/tn", "Claude Assistant Bridge"],
        "Starting webhook server now"
    )
    return ok


def install_runner(project_dir: str, username: str, interval_minutes: int = 5) -> bool:
    """
    Register the task runner as a Task Scheduler task that runs every N minutes.
    """
    print("\n[3/3] Registering task runner as a scheduled task...")

    # Remove existing task if present
    subprocess.run(
        ["schtasks", "/delete", "/tn", "Claude Assistant Bridge Runner", "/f"],
        capture_output=True
    )

    runner_path = os.path.join(project_dir, "runner.py")
    python_exe = sys.executable

    ok = run(
        [
            "schtasks", "/create",
            "/tn", "Claude Assistant Bridge Runner",
            "/tr", f"{python_exe} {runner_path}",
            "/sc", "minute",
            "/mo", str(interval_minutes),
            "/ru", username,
            "/rl", "highest",
            "/f"
        ],
        f"Creating Task Scheduler entry (every {interval_minutes} minutes, runs as {username})"
    )

    if ok:
        _fix_power_settings("Claude Assistant Bridge Runner")

    return ok


# ---------------------------------------------------------------------------
# Main installer (called by setup.py)
# ---------------------------------------------------------------------------

def install_all(project_dir: str, tunnel_port: int = 8080, runner_interval: int = 5):
    """
    Full Windows service installation. Registers all three services.
    Must be run as Administrator.
    """
    print("\n=== Windows Service Installation ===")

    if not is_admin():
        print("\n❌ This installer requires Administrator privileges.")
        print("   Please re-run your terminal as Administrator and try again.")
        sys.exit(1)

    username = get_current_username()
    if not username:
        print("❌ Could not determine current username.")
        sys.exit(1)

    print(f"\nInstalling services for user: {username}")
    print(f"Project directory: {project_dir}")

    results = []
    results.append(install_cloudflared(tunnel_port))
    results.append(install_webhook_server(project_dir, username))
    results.append(install_runner(project_dir, username, runner_interval))

    print("\n=== Installation Summary ===")
    labels = ["cloudflared tunnel", "webhook server", "task runner"]
    all_ok = True
    for label, ok in zip(labels, results):
        status = "✅" if ok else "❌"
        print(f"  {status} {label}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n✅ All services installed successfully.")
        print("   Reboot your PC to verify everything starts automatically.")
    else:
        print("\n⚠️  Some services failed to install. Check the output above.")

    return all_ok


def uninstall_all():
    """Remove all registered services and tasks."""
    print("\n=== Uninstalling Claude Assistant Bridge services ===")

    print("  Removing cloudflared service...")
    subprocess.run(["nssm", "stop", "cloudflared-tunnel"], capture_output=True)
    subprocess.run(["nssm", "remove", "cloudflared-tunnel", "confirm"], capture_output=True)

    print("  Removing webhook server task...")
    subprocess.run(
        ["schtasks", "/delete", "/tn", "Claude Assistant Bridge", "/f"],
        capture_output=True
    )

    print("  Removing runner task...")
    subprocess.run(
        ["schtasks", "/delete", "/tn", "Claude Assistant Bridge Runner", "/f"],
        capture_output=True
    )

    print("✅ All services removed.")


if __name__ == "__main__":
    # Allow running directly for testing
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    install_all(project_dir)
