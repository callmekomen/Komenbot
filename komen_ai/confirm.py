"""
Shared confirmation gate used by every tool before a risky action.

By default this asks in the terminal (input()). When Komen AI is driven from
Telegram, telegram_bot.py swaps in a handler that asks via inline Yes/No
buttons in the chat instead. Tools never need to know which mode is active —
they just call confirm(description).
"""
import config

_handler = None  # set by telegram_bot.py (or anything else) to override the default


def set_confirm_handler(fn):
    """fn(description: str) -> bool. Called instead of the terminal prompt."""
    global _handler
    _handler = fn


def confirm(description: str) -> bool:
    if not config.CONFIRM_DESTRUCTIVE_ACTIONS:
        return True
    if _handler is not None:
        return _handler(description)
    print(f"\n[Komen AI] About to: {description}")
    return input("  Proceed? [y/N]: ").strip().lower() == "y"
