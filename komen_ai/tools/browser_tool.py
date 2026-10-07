"""
Browser Tool - lets the agent open pages, click, type, and read content
using Playwright (Chromium).

A single browser/page is kept alive across calls within one run so multi-step
web tasks (search -> click result -> read page) work naturally.
"""
from playwright.sync_api import sync_playwright
from config import HEADLESS_BROWSER

SCHEMA = {
    "name": "browser_action",
    "description": (
        "Control a web browser. Actions: 'open' (navigate to a URL), "
        "'click' (click an element by CSS selector or visible text), "
        "'type' (type text into an element), 'read' (return visible page text), "
        "'screenshot' (save a screenshot to a path)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "click", "type", "read", "screenshot"]},
            "url": {"type": "string", "description": "Required for 'open'"},
            "selector": {"type": "string", "description": "CSS selector, required for 'click'/'type'"},
            "text": {"type": "string", "description": "Text to type, required for 'type'"},
            "path": {"type": "string", "description": "Output path for 'screenshot'"},
        },
        "required": ["action"],
    },
}

_state = {"playwright": None, "browser": None, "page": None}


def _ensure_browser():
    if _state["browser"] is None:
        _state["playwright"] = sync_playwright().start()
        _state["browser"] = _state["playwright"].chromium.launch(headless=HEADLESS_BROWSER)
        _state["page"] = _state["browser"].new_page()
    return _state["page"]


def run(action: str, url: str = None, selector: str = None, text: str = None, path: str = None) -> dict:
    try:
        page = _ensure_browser()
        if action == "open":
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            return {"status": "ok", "title": page.title(), "url": page.url}

        elif action == "click":
            try:
                page.click(selector, timeout=5000)
            except Exception:
                page.get_by_text(selector).first.click(timeout=5000)
            return {"status": "ok"}

        elif action == "type":
            page.fill(selector, text, timeout=5000)
            return {"status": "ok"}

        elif action == "read":
            content = page.inner_text("body")[:6000]
            return {"content": content}

        elif action == "screenshot":
            out_path = path or "screenshot.png"
            page.screenshot(path=out_path)
            return {"status": "ok", "path": out_path}

        return {"error": f"Unknown action: {action}"}
    except Exception as e:
        return {"error": str(e)}


def close():
    if _state["browser"]:
        _state["browser"].close()
        _state["playwright"].stop()
        _state["browser"] = None
