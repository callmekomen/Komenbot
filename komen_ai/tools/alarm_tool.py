"""
Alarm Tool.

- 'set_phone_alarm': fires an Android SET_ALARM intent over ADB. This hands
  the alarm to whatever clock app is installed (Google Clock, Samsung Clock,
  etc.) so it shows up as a real alarm — it isn't a fake timer in this script.
  Most clock apps support SKIP_UI=true (sets it directly); a few will open
  the clock app's "add alarm" screen pre-filled instead.

- 'set_pc_alarm': there's no OS-level "alarm" concept on desktop, so this
  schedules a background timer that fires a desktop notification (and a
  terminal beep as a fallback) at the requested time. The process running
  Komen AI (main.py or telegram_bot.py) has to stay running for it to fire.
"""
import datetime
import subprocess
import threading
import uuid

from config import ADB_PATH, DEFAULT_DEVICE_ID
from confirm import confirm

try:
    from plyer import notification as _notification
except ImportError:
    _notification = None

SCHEMA = {
    "name": "alarm_action",
    "description": (
        "Set or manage alarms. 'set_phone_alarm' sets a real alarm in the "
        "phone's clock app via ADB. 'set_pc_alarm' schedules a desktop "
        "notification at a specific time (fires only while this program keeps "
        "running). 'list_pc_alarms' lists alarms currently scheduled on the "
        "PC. 'cancel_pc_alarm' cancels one by its id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set_phone_alarm", "set_pc_alarm", "list_pc_alarms", "cancel_pc_alarm"],
            },
            "hour": {"type": "integer", "description": "0-23, 24-hour format"},
            "minute": {"type": "integer", "description": "0-59"},
            "label": {"type": "string", "description": "Optional label/message for the alarm"},
            "alarm_id": {"type": "string", "description": "Required for cancel_pc_alarm"},
        },
        "required": ["action"],
    },
}

_active_pc_alarms = {}  # alarm_id -> {"fires_at": iso str, "label": str, "timer": Timer}


def _adb(*args, timeout=15):
    cmd = [ADB_PATH]
    if DEFAULT_DEVICE_ID:
        cmd += ["-s", DEFAULT_DEVICE_ID]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _seconds_until(hour: int, minute: int):
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)  # next occurrence, e.g. tomorrow
    return (target - now).total_seconds(), target


def _fire_pc_alarm(alarm_id: str, label: str):
    _active_pc_alarms.pop(alarm_id, None)
    message = label or "Alarm!"
    if _notification is not None:
        try:
            _notification.notify(title="Komen AI Alarm", message=message, timeout=60)
        except Exception:
            pass
    print(f"\a\n[Komen AI] ALARM: {message}")  # terminal bell, always fires as a fallback


def set_pc_alarm(hour: int, minute: int, label: str = None) -> dict:
    delay, target = _seconds_until(hour, minute)
    alarm_id = str(uuid.uuid4())[:8]
    timer = threading.Timer(delay, _fire_pc_alarm, args=(alarm_id, label))
    timer.daemon = True
    timer.start()
    _active_pc_alarms[alarm_id] = {"fires_at": target.isoformat(), "label": label, "timer": timer}
    return {"status": "ok", "alarm_id": alarm_id, "fires_at": target.isoformat(),
            "note": "This will only fire while Komen AI keeps running."}


def list_pc_alarms() -> dict:
    return {"alarms": [
        {"id": aid, "fires_at": v["fires_at"], "label": v["label"]}
        for aid, v in _active_pc_alarms.items()
    ]}


def cancel_pc_alarm(alarm_id: str) -> dict:
    entry = _active_pc_alarms.pop(alarm_id, None)
    if not entry:
        return {"error": f"No active PC alarm with id '{alarm_id}'"}
    entry["timer"].cancel()
    return {"status": "cancelled", "alarm_id": alarm_id}


def set_phone_alarm(hour: int, minute: int, label: str = None) -> dict:
    if not confirm(f"set a phone alarm for {hour:02d}:{minute:02d}" +
                    (f" ({label})" if label else "")):
        return {"error": "User declined."}
    args = [
        "shell", "am", "start", "-a", "android.intent.action.SET_ALARM",
        "--ei", "android.intent.extra.alarm.HOUR", str(hour),
        "--ei", "android.intent.extra.alarm.MINUTES", str(minute),
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true",
    ]
    if label:
        args += ["--es", "android.intent.extra.alarm.MESSAGE", label]
    try:
        r = _adb(*args)
        return {"status": "ok" if r.returncode == 0 else "error",
                "stdout": r.stdout, "stderr": r.stderr}
    except FileNotFoundError:
        return {"error": "adb not found. Install Android Platform Tools and ensure 'adb' is on PATH."}
    except Exception as e:
        return {"error": str(e)}


def run(action: str, hour: int = None, minute: int = None, label: str = None,
        alarm_id: str = None) -> dict:
    if action == "set_pc_alarm":
        return set_pc_alarm(hour, minute, label)
    elif action == "set_phone_alarm":
        return set_phone_alarm(hour, minute, label)
    elif action == "list_pc_alarms":
        return list_pc_alarms()
    elif action == "cancel_pc_alarm":
        return cancel_pc_alarm(alarm_id)
    return {"error": f"Unknown action: {action}"}
