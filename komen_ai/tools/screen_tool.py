"""
Screen Tool - controls the PC's mouse/keyboard and takes screenshots.
Uses pyautogui. Requires a graphical session (won't work on headless servers).
"""
from confirm import confirm

SCHEMA = {
    "name": "screen_action",
    "description": (
        "Control the PC screen directly. Actions: 'screenshot' (save + return path), "
        "'click' (click at x,y), 'move' (move mouse to x,y), 'type' (type text at "
        "current focus), 'hotkey' (press a key combo like ctrl+c), "
        "'open_app' (launch an application by its everyday name, e.g. 'notepad', "
        "'file explorer', 'calculator', 'chrome', 'word' — common names are mapped "
        "automatically for Windows/Mac/Linux)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["screenshot", "click", "move", "type", "hotkey", "open_app"],
            },
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "text": {"type": "string"},
            "keys": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['ctrl','c']"},
            "app_name": {"type": "string"},
            "path": {"type": "string", "description": "Where to save screenshot"},
        },
        "required": ["action"],
    },
}


def _confirm(desc: str) -> bool:
    return confirm(desc)


# Friendly name -> actual command, per OS. Extend this as needed.
_APP_MAP = {
    "win32": {
        "notepad": "notepad.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "task manager": "taskmgr.exe",
        "control panel": "control.exe",
        "cmd": "cmd.exe",
        "terminal": "wt.exe",
        "settings": "start ms-settings:",
    },
    "darwin": {
        "notes": "Notes",
        "finder": "Finder",
        "calculator": "Calculator",
        "chrome": "Google Chrome",
        "safari": "Safari",
        "word": "Microsoft Word",
        "excel": "Microsoft Excel",
        "terminal": "Terminal",
        "preview": "Preview",
    },
    "linux": {
        "terminal": "gnome-terminal",
        "files": "nautilus",
        "file explorer": "nautilus",
        "text editor": "gedit",
        "chrome": "google-chrome",
        "calculator": "gnome-calculator",
    },
}


def _resolve_app(app_name: str) -> str:
    plat = sys.platform if 'sys' in globals() else __import__("sys").platform
    table = _APP_MAP.get(plat, {})
    return table.get(app_name.strip().lower(), app_name)


def run(action: str, x=None, y=None, text=None, keys=None, app_name=None, path=None) -> dict:
    try:
        import pyautogui
    except ImportError:
        return {"error": "pyautogui is not installed. Run: pip install pyautogui"}

    try:
        if action == "screenshot":
            out_path = path or "screen.png"
            pyautogui.screenshot(out_path)
            return {"status": "ok", "path": out_path}

        elif action == "click":
            if not _confirm(f"click at ({x}, {y})"):
                return {"error": "User declined."}
            pyautogui.click(x, y)
            return {"status": "ok"}

        elif action == "move":
            pyautogui.moveTo(x, y)
            return {"status": "ok"}

        elif action == "type":
            if not _confirm(f"type text: {text!r}"):
                return {"error": "User declined."}
            pyautogui.typewrite(text, interval=0.02)
            return {"status": "ok"}

        elif action == "hotkey":
            if not _confirm(f"press hotkey: {'+'.join(keys or [])}"):
                return {"error": "User declined."}
            pyautogui.hotkey(*(keys or []))
            return {"status": "ok"}

        elif action == "open_app":
            import subprocess
            import sys
            resolved = _resolve_app(app_name)
            if not _confirm(f"open application: {app_name} ({resolved})"):
                return {"error": "User declined."}
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", "-a", resolved], check=True)
                elif sys.platform == "win32":
                    subprocess.run(f'start "" "{resolved}"', shell=True, check=True)
                else:
                    subprocess.Popen([resolved])
                return {"status": "ok", "resolved_command": resolved}
            except Exception as e:
                return {"error": f"Could not launch '{app_name}' (tried '{resolved}'): {e}"}

        return {"error": f"Unknown action: {action}"}
    except Exception as e:
        return {"error": str(e)}
