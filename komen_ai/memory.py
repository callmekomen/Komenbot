"""
Komen AI - Persistent memory.

Facts survive restarts, so Komen AI stops relearning the same things: your
phone's package names, where your folders live, how you like tasks done.

Stored as JSON at ~/.komen_ai/memory.json (override with KOMEN_MEMORY_FILE).

Each fact:
    {"key": "downloads_path", "value": "C:/Users/me/Downloads",
     "category": "system", "updated": "2026-01-01T00:00:00"}

Keys are unique — writing the same key again updates it rather than
duplicating, which keeps the memory from bloating over months of use.
"""
import datetime
import json
import os
import threading

_lock = threading.Lock()  # memory is touched from Telegram worker threads

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".komen_ai", "memory.json")
MEMORY_FILE = os.environ.get("KOMEN_MEMORY_FILE", DEFAULT_PATH)
MAX_FACTS = int(os.environ.get("KOMEN_MAX_FACTS", "200"))


def _ensure_dir():
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)


def _load() -> list:
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []  # corrupt file shouldn't crash the agent


def _save(facts: list):
    _ensure_dir()
    tmp = MEMORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)
    os.replace(tmp, MEMORY_FILE)  # atomic, so a crash can't corrupt memory


def remember(key: str, value: str, category: str = "general") -> dict:
    key = (key or "").strip().lower().replace(" ", "_")
    if not key:
        return {"error": "A memory key is required."}
    with _lock:
        facts = _load()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for fact in facts:
            if fact["key"] == key:
                fact.update({"value": value, "category": category, "updated": now})
                _save(facts)
                return {"status": "updated", "key": key}
        facts.append({"key": key, "value": value, "category": category, "updated": now})
        if len(facts) > MAX_FACTS:
            facts.sort(key=lambda f: f.get("updated", ""))
            facts = facts[-MAX_FACTS:]  # drop the stalest
        _save(facts)
        return {"status": "saved", "key": key}


def recall(query: str = None, category: str = None) -> dict:
    with _lock:
        facts = _load()
    if category:
        facts = [f for f in facts if f.get("category") == category]
    if query:
        q = query.lower()
        facts = [f for f in facts
                 if q in f["key"].lower() or q in str(f["value"]).lower()]
    return {"facts": [{"key": f["key"], "value": f["value"],
                        "category": f.get("category", "general")} for f in facts]}


def forget(key: str) -> dict:
    key = (key or "").strip().lower().replace(" ", "_")
    with _lock:
        facts = _load()
        remaining = [f for f in facts if f["key"] != key]
        if len(remaining) == len(facts):
            return {"error": f"No memory found with key '{key}'"}
        _save(remaining)
    return {"status": "forgotten", "key": key}


def clear_all() -> dict:
    with _lock:
        _save([])
    return {"status": "cleared"}


def as_prompt_block(limit: int = 60) -> str:
    """
    Renders memory for injection into the system prompt, so the model starts
    every task already knowing these things instead of having to call a tool.
    """
    with _lock:
        facts = _load()
    if not facts:
        return ""
    facts.sort(key=lambda f: f.get("updated", ""), reverse=True)
    lines = [f"- {f['key']}: {f['value']}" for f in facts[:limit]]
    return ("\n\nThings you remember about this user and their machines:\n"
            + "\n".join(lines))
