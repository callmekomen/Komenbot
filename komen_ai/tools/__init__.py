"""
Central registry of every tool Komen AI can call.
Add a new tool by: writing a module with a SCHEMA + run function(s),
then registering it in ALL_SCHEMAS and DISPATCH below.
"""
from . import (shell_tool, file_tool, browser_tool, screen_tool, phone_tool,
               system_tool, alarm_tool, memory_tool)

ALL_SCHEMAS = [
    shell_tool.SCHEMA,
    file_tool.SCHEMA_READ,
    file_tool.SCHEMA_WRITE,
    file_tool.SCHEMA_LIST,
    browser_tool.SCHEMA,
    screen_tool.SCHEMA,
    phone_tool.SCHEMA,
    system_tool.SCHEMA,
    alarm_tool.SCHEMA,
    memory_tool.SCHEMA,
]

DISPATCH = {
    "run_shell_command": lambda i: shell_tool.run(**i),
    "read_file": lambda i: file_tool.read_file(**i),
    "write_file": lambda i: file_tool.write_file(**i),
    "list_directory": lambda i: file_tool.list_directory(**i),
    "browser_action": lambda i: browser_tool.run(**i),
    "screen_action": lambda i: screen_tool.run(**i),
    "phone_action": lambda i: phone_tool.run(**i),
    "system_power_action": lambda i: system_tool.run(**i),
    "alarm_action": lambda i: alarm_tool.run(**i),
    "memory_action": lambda i: memory_tool.run(**i),
}


def execute_tool(name: str, tool_input: dict) -> dict:
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"No such tool: {name}"}
    try:
        return fn(tool_input)
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    except Exception as e:
        return {"error": f"Tool '{name}' raised an exception: {e}"}
