"""
Shell Tool - lets the agent run commands on the PC.
Includes a blocklist and optional confirmation prompt for safety.
"""
import subprocess
from config import BLOCKED_SHELL_PATTERNS
from confirm import confirm

SCHEMA = {
    "name": "run_shell_command",
    "description": (
        "Run a shell command on the local PC and return its stdout/stderr. "
        "Use for file system checks, running scripts, installing packages, etc. "
        "Do NOT use for anything destructive without a clear, explicit user goal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"},
            "timeout_seconds": {"type": "integer", "description": "Max seconds to allow (default 30)"},
        },
        "required": ["command"],
    },
}


def _is_blocked(command: str) -> bool:
    lowered = command.lower()
    return any(pattern in lowered for pattern in BLOCKED_SHELL_PATTERNS)


def run(command: str, timeout_seconds: int = 30) -> dict:
    if _is_blocked(command):
        return {"error": f"Blocked for safety: command matches a disallowed pattern."}

    if not confirm(f"run shell command:\n  {command}"):
        return {"error": "User declined to run this command."}

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout_seconds
        )
        return {
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout_seconds}s"}
    except Exception as e:
        return {"error": str(e)}
