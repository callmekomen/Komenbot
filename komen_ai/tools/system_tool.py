"""
System Power Tool - shuts down, restarts, sleeps, or locks the PC.
Cross-platform (Windows/Mac/Linux), always asks for confirmation since
these actions are disruptive and hard to undo mid-task.
"""
import subprocess
import sys
from confirm import confirm

SCHEMA = {
    "name": "system_power_action",
    "description": (
        "Shut down, restart, sleep, or lock the PC. Use this instead of raw "
        "shell commands for power actions — it picks the right command for "
        "the current OS automatically."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["shutdown", "restart", "sleep", "lock"]},
            "delay_seconds": {"type": "integer", "description": "Delay before shutdown/restart (default 0)"},
        },
        "required": ["action"],
    },
}


def run(action: str, delay_seconds: int = 0) -> dict:
    desc = f"{action.upper()} this PC" + (f" in {delay_seconds}s" if delay_seconds else "")
    if not confirm(desc):
        return {"error": "User declined this power action."}

    plat = sys.platform
    try:
        if plat == "win32":
            cmd = {
                "shutdown": ["shutdown", "/s", "/t", str(delay_seconds)],
                "restart": ["shutdown", "/r", "/t", str(delay_seconds)],
                "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            }[action]
        elif plat == "darwin":
            cmd = {
                "shutdown": ["sudo", "shutdown", "-h", f"+{max(1, delay_seconds // 60)}"],
                "restart": ["sudo", "shutdown", "-r", f"+{max(1, delay_seconds // 60)}"],
                "sleep": ["pmset", "sleepnow"],
                "lock": ["osascript", "-e",
                         'tell application "System Events" to keystroke "q" using {control down, command down}'],
            }[action]
        else:  # linux
            cmd = {
                "shutdown": ["shutdown", "-h", f"+{max(1, delay_seconds // 60)}" if delay_seconds else "now"],
                "restart": ["shutdown", "-r", f"+{max(1, delay_seconds // 60)}" if delay_seconds else "now"],
                "sleep": ["systemctl", "suspend"],
                "lock": ["loginctl", "lock-session"],
            }[action]

        subprocess.run(cmd, check=False)
        return {"status": "ok", "action": action, "platform": plat}
    except Exception as e:
        return {"error": str(e)}
