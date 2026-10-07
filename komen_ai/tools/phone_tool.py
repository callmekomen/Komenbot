"""
Phone Tool - controls an Android phone over ADB (USB or Wi-Fi debugging).

Setup required on the phone:
  1. Enable Developer Options -> USB debugging (Settings > About Phone > tap
     Build Number 7x, then Settings > Developer Options).
  2. Connect via USB and accept the "allow debugging" prompt, OR
     run `adb tcpip 5555` then `adb connect <phone-ip>:5555` for Wi-Fi.
  3. Confirm `adb devices` shows your device before running the agent.
"""
import subprocess
from config import ADB_PATH, DEFAULT_DEVICE_ID
from confirm import confirm

SCHEMA = {
    "name": "phone_action",
    "description": (
        "Control an Android phone connected via ADB. Actions: 'tap' (x,y), "
        "'swipe' (x1,y1,x2,y2), 'type' (type text into focused field), "
        "'key' (press a key like HOME, BACK, ENTER), 'open_app' (launch by "
        "exact package name, e.g. com.whatsapp), 'open_app_by_name' (launch by "
        "everyday name, e.g. 'facebook', 'whatsapp', 'efootball' — resolves to "
        "the installed package automatically), 'lock' (lock/sleep the phone "
        "screen), 'wake' (wake the phone screen up), 'screenshot' (pull a "
        "screenshot to a local path), 'list_apps' (list installed packages)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["tap", "swipe", "type", "key", "open_app", "open_app_by_name",
                         "screenshot", "list_apps", "lock", "wake"],
            },
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
            "text": {"type": "string"},
            "key_event": {"type": "string", "description": "e.g. HOME, BACK, ENTER"},
            "package_name": {"type": "string"},
            "app_name": {"type": "string", "description": "Everyday app name, for 'open_app_by_name'"},
            "path": {"type": "string"},
        },
        "required": ["action"],
    },
}

# Common friendly name -> package name, tried first (exact + fast).
# Falls back to fuzzy-matching installed packages if not found here.
_KNOWN_PACKAGES = {
    "facebook": "com.facebook.katana",
    "messenger": "com.facebook.orca",
    "instagram": "com.instagram.android",
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "gmail": "com.google.android.gm",
    "chrome": "com.android.chrome",
    "maps": "com.google.android.apps.maps",
    "spotify": "com.spotify.music",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "tiktok": "com.zhiliaoapp.musically",
    "telegram": "org.telegram.messenger",
    "netflix": "com.netflix.mediaclient",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "gallery": "com.google.android.apps.photos",
    "photos": "com.google.android.apps.photos",
    "play store": "com.android.vending",
}


def _resolve_package(app_name: str) -> dict:
    """Try known map first, then fuzzy-match against installed packages."""
    key = app_name.strip().lower()
    if key in _KNOWN_PACKAGES:
        return {"package": _KNOWN_PACKAGES[key], "match_type": "known"}

    try:
        result = _adb("shell", "pm", "list", "packages", "-3")
        packages = [line.replace("package:", "").strip() for line in result.stdout.splitlines()]
    except Exception as e:
        return {"error": f"Could not list installed packages: {e}"}

    tokens = key.replace(" ", "").replace("-", "")
    candidates = [p for p in packages if tokens in p.lower().replace(".", "")]
    if len(candidates) == 1:
        return {"package": candidates[0], "match_type": "fuzzy"}
    elif len(candidates) > 1:
        return {"error": f"Multiple packages match '{app_name}': {candidates}. "
                          f"Use 'open_app' with the exact package_name instead."}
    else:
        return {"error": f"No installed package found matching '{app_name}'. "
                          f"Try 'list_apps' to see what's installed, then use 'open_app' "
                          f"with the exact package_name."}

_KEY_EVENTS = {
    "HOME": "KEYCODE_HOME",
    "BACK": "KEYCODE_BACK",
    "ENTER": "KEYCODE_ENTER",
    "APP_SWITCH": "KEYCODE_APP_SWITCH",
}


def _adb(*args, timeout=15):
    cmd = [ADB_PATH]
    if DEFAULT_DEVICE_ID:
        cmd += ["-s", DEFAULT_DEVICE_ID]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result


def _confirm(desc: str) -> bool:
    return confirm(desc)


def run(action, x=None, y=None, x2=None, y2=None, text=None, key_event=None,
        package_name=None, app_name=None, path=None) -> dict:
    try:
        if action == "tap":
            if not _confirm(f"tap at ({x}, {y})"):
                return {"error": "User declined."}
            r = _adb("shell", "input", "tap", str(x), str(y))

        elif action == "swipe":
            if not _confirm(f"swipe ({x},{y}) -> ({x2},{y2})"):
                return {"error": "User declined."}
            r = _adb("shell", "input", "swipe", str(x), str(y), str(x2), str(y2))

        elif action == "type":
            if not _confirm(f"type text on phone: {text!r}"):
                return {"error": "User declined."}
            escaped = (text or "").replace(" ", "%s")
            r = _adb("shell", "input", "text", escaped)

        elif action == "key":
            keycode = _KEY_EVENTS.get((key_event or "").upper(), key_event)
            r = _adb("shell", "input", "keyevent", keycode)

        elif action == "open_app":
            if not _confirm(f"open app: {package_name}"):
                return {"error": "User declined."}
            r = _adb("shell", "monkey", "-p", package_name,
                      "-c", "android.intent.category.LAUNCHER", "1")

        elif action == "open_app_by_name":
            resolved = _resolve_package(app_name or "")
            if "error" in resolved:
                return resolved
            pkg = resolved["package"]
            if not _confirm(f"open app: {app_name} ({pkg})"):
                return {"error": "User declined."}
            r = _adb("shell", "monkey", "-p", pkg,
                      "-c", "android.intent.category.LAUNCHER", "1")
            return {"status": "ok" if r.returncode == 0 else "error",
                     "resolved_package": pkg, "match_type": resolved["match_type"],
                     "stdout": r.stdout, "stderr": r.stderr}

        elif action == "screenshot":
            out_path = path or "phone_screen.png"
            _adb("shell", "screencap", "-p", "/sdcard/komen_screen.png")
            r = _adb("pull", "/sdcard/komen_screen.png", out_path)
            return {"status": "ok", "path": out_path, "stderr": r.stderr}

        elif action == "lock":
            if not _confirm("lock the phone screen"):
                return {"error": "User declined."}
            r = _adb("shell", "input", "keyevent", "223")  # KEYCODE_SLEEP

        elif action == "wake":
            r = _adb("shell", "input", "keyevent", "224")  # KEYCODE_WAKEUP

        elif action == "list_apps":
            r = _adb("shell", "pm", "list", "packages", "-3")
            packages = [line.replace("package:", "") for line in r.stdout.splitlines()]
            return {"packages": packages[:100]}

        else:
            return {"error": f"Unknown action: {action}"}

        return {"status": "ok" if r.returncode == 0 else "error",
                 "stdout": r.stdout, "stderr": r.stderr}
    except FileNotFoundError:
        return {"error": "adb not found. Install Android Platform Tools and ensure 'adb' is on PATH."}
    except Exception as e:
        return {"error": str(e)}
