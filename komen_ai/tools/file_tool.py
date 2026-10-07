"""
File Tool - read, write, and list files on the PC.
"""
import os
from confirm import confirm

SCHEMA_READ = {
    "name": "read_file",
    "description": "Read the contents of a text file at the given path.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

SCHEMA_WRITE = {
    "name": "write_file",
    "description": "Write (or overwrite) text content to a file at the given path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
        },
        "required": ["path", "content"],
    },
}

SCHEMA_LIST = {
    "name": "list_directory",
    "description": "List files and folders inside a given directory path.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}


def read_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return {"content": f.read()[:20000]}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str, append: bool = False) -> dict:
    mode_word = "append to" if append else "overwrite"
    if not confirm(f"{mode_word} file: {path}"):
        return {"error": "User declined this file write."}
    try:
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return {"status": "ok", "bytes_written": len(content)}
    except Exception as e:
        return {"error": str(e)}


def list_directory(path: str) -> dict:
    try:
        entries = os.listdir(path)
        return {"entries": entries}
    except Exception as e:
        return {"error": str(e)}
