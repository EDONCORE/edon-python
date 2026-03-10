"""
EDON @govern decorator — add governance to any function in one line.

Install:
    pip install edon

Run:
    EDON_API_KEY=your-key python examples/decorator_basic.py
"""

import os
import edon

# ── Configure once at startup ─────────────────────────────────
edon.configure(
    api_key=os.environ["EDON_API_KEY"],
    agent_id="my-python-agent",
)


# ── Govern any function with one decorator ────────────────────

@edon.govern(action_type="email.send")
def send_email(to: str, subject: str, body: str) -> None:
    """Send an email — only runs if EDON allows it."""
    print(f"  → Sending email to {to}: {subject}")


@edon.govern(action_type="file.read")
def read_file(path: str) -> str:
    """Read a file — likely ALLOWED."""
    return open(path).read()


@edon.govern(action_type="shell.exec")
def run_command(command: str) -> str:
    """Run a shell command — likely BLOCKED by policy."""
    import subprocess
    return subprocess.check_output(command, shell=True).decode()


@edon.govern(action_type="database.delete")
def delete_records(table: str, where: str) -> int:
    """Delete DB records — likely BLOCKED by policy."""
    print(f"  → Deleting from {table} where {where}")
    return 0


# ── Run ───────────────────────────────────────────────────────
print("\n--- EDON Governance Demo ---\n")

# This will likely ALLOW (file.read is within scope)
try:
    print("Testing file.read...")
    read_file("/tmp/test.txt")
    print("  ✓ Allowed\n")
except edon.EdonBlockedError as e:
    print(f"  ✗ Blocked: {e.reason}\n")

# This will likely ALLOW (email.draft/send depends on policy)
try:
    print("Testing email.send...")
    send_email("team@company.com", "Weekly Update", "Here's the update...")
    print("  ✓ Allowed\n")
except edon.EdonBlockedError as e:
    print(f"  ✗ Blocked: {e.reason}\n")

# This will likely BLOCK (shell.exec is outside founder_mode scope)
try:
    print("Testing shell.exec...")
    run_command("ls /tmp")
    print("  ✓ Allowed\n")
except edon.EdonBlockedError as e:
    print(f"  ✗ Blocked: {e.reason}\n")
    print(f"    reason_code: {e.reason_code}")
    print(f"    action_id:   {e.action_id}\n")

# This will likely BLOCK (database.delete is outside scope)
try:
    print("Testing database.delete...")
    delete_records("users", "created_at < '2024-01-01'")
    print("  ✓ Allowed\n")
except edon.EdonBlockedError as e:
    print(f"  ✗ Blocked: {e.reason}\n")

print("All decisions logged to EDON audit trail.")
print("View at: https://edoncore.com/console\n")
