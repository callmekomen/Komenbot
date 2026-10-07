"""
Memory Tool - lets the agent save and look up facts that persist across
sessions and restarts.
"""
import memory

SCHEMA = {
    "name": "memory_action",
    "description": (
        "Save, look up, or delete long-term facts that persist across "
        "sessions. Use 'remember' whenever you learn something durable and "
        "reusable — an app's package name, a folder path, a device quirk, a "
        "user preference — so you don't have to rediscover it next time. Use "
        "'recall' to search. Facts you already know are injected into your "
        "system prompt automatically, so only call 'recall' to search for "
        "something not already listed there. Do not store secrets, passwords, "
        "or anything sensitive."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["remember", "recall", "forget"]},
            "key": {"type": "string",
                     "description": "Short snake_case identifier, e.g. 'efootball_package'"},
            "value": {"type": "string", "description": "The fact to store (for 'remember')"},
            "category": {"type": "string",
                          "description": "e.g. 'phone', 'pc', 'preference', 'path'"},
            "query": {"type": "string", "description": "Search text (for 'recall')"},
        },
        "required": ["action"],
    },
}


def run(action: str, key: str = None, value: str = None,
        category: str = "general", query: str = None) -> dict:
    if action == "remember":
        if not key or value is None:
            return {"error": "'remember' needs both key and value."}
        return memory.remember(key, value, category)
    elif action == "recall":
        return memory.recall(query=query, category=category if category != "general" else None)
    elif action == "forget":
        return memory.forget(key)
    return {"error": f"Unknown action: {action}"}
