"""
Komen AI - Telegram remote control.

Lets you control your PC/phone from Telegram: send it a task in plain
English, grab a PC or phone screenshot, open apps, or shut down/restart/
sleep/lock the PC. Any risky action asks you to confirm with tap-to-approve
buttons in the chat instead of a terminal y/n prompt.

Setup:
  1. Message @BotFather on Telegram -> /newbot -> follow the prompts.
     You'll get back a token that looks like: 123456789:AAExxxxxxxxxxxxxxxx
  2. Message your new bot once (anything, e.g. "hi").
  3. Find your chat ID: message @userinfobot, or visit
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates in a browser after
     step 2 and look for "chat":{"id": ...}.
  4. Set env vars:
       export TELEGRAM_BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxx
       export TELEGRAM_AUTHORIZED_CHAT_IDS=123456789
       export GROQ_API_KEY=gsk_...       (or any provider — see README)
  5. Run:  python telegram_bot.py

Commands:
  /start            - check the bot is up and you're authorized
  /screenshot       - screenshot the PC and send it back as an image
  /phonescreenshot  - screenshot the phone (via ADB) and send it back
  /openapp <name>   - open an app on the PC by everyday name
  /openphoneapp <n> - open an app on the phone by everyday name
  /shutdown /restart /sleep /lock - PC power actions (asks to confirm)
  (anything else)   - treated as a free-form task for the full agent to plan and run
"""
import asyncio
import concurrent.futures
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

import config
import confirm
import memory
from agent import KomenAgent
from tools import screen_tool, phone_tool, system_tool

_main_loop = None   # asyncio loop the bot runs on, captured via post_init
_bot_app = None     # the Application instance, used to send messages from worker threads
_pending = {}        # confirmation_id -> concurrent.futures.Future

# One agent per chat, so two people (or two devices) don't bleed conversation
# context into each other. Long-term memory is shared on disk; history isn't.
_agents = {}


def _agent_for(chat_id: int) -> KomenAgent:
    if chat_id not in _agents:
        _agents[chat_id] = KomenAgent(verbose=False)
    return _agents[chat_id]


def _authorized(update: Update) -> bool:
    if not config.TELEGRAM_AUTHORIZED_CHAT_IDS:
        return False  # fail closed if nobody's been configured
    return update.effective_chat.id in config.TELEGRAM_AUTHORIZED_CHAT_IDS


def telegram_confirm(description: str) -> bool:
    """
    Registered with confirm.py as the confirmation handler. Runs in a worker
    thread (tool calls are synchronous); sends an inline Yes/No prompt on the
    bot's event loop and blocks this thread until the user taps a button or
    the confirmation times out.
    """
    confirm_id = str(uuid.uuid4())
    future = concurrent.futures.Future()
    _pending[confirm_id] = future

    async def _send():
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes", callback_data=f"confirm:{confirm_id}:yes"),
            InlineKeyboardButton("No", callback_data=f"confirm:{confirm_id}:no"),
        ]])
        for chat_id in config.TELEGRAM_AUTHORIZED_CHAT_IDS:
            await _bot_app.bot.send_message(
                chat_id=chat_id,
                text=f"Confirm action:\n{description}",
                reply_markup=keyboard,
            )

    asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    try:
        return future.result(timeout=config.TELEGRAM_CONFIRM_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        return False
    finally:
        _pending.pop(confirm_id, None)


async def handle_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, confirm_id, answer = query.data.split(":")
    future = _pending.get(confirm_id)
    if future and not future.done():
        future.set_result(answer == "yes")
    await query.edit_message_text(
        query.message.text + f"\n\n{'Approved' if answer == 'yes' else 'Declined'}"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text(
            f"Not authorized. Your chat ID is {update.effective_chat.id} — "
            f"add it to TELEGRAM_AUTHORIZED_CHAT_IDS to use this bot."
        )
        return
    await update.message.reply_text(
        "Komen AI is online. Send a task in plain English, or use:\n"
        "/screenshot, /phonescreenshot\n"
        "/openapp <name>, /openphoneapp <name>\n"
        "/shutdown, /restart, /sleep, /lock\n"
        "/memory (what I remember), /forget <key>, /reset (clear this chat's history)"
    )


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    facts = memory.recall().get("facts", [])
    if not facts:
        await update.message.reply_text("I haven't saved any facts yet.")
        return
    lines = [f"- {f['key']}: {f['value']}" for f in facts[:40]]
    await update.message.reply_text("I remember:\n" + "\n".join(lines))


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /forget <key>")
        return
    await update.message.reply_text(str(memory.forget(" ".join(context.args))))


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    _agents.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "Conversation history cleared. Long-term memory is untouched "
        "(use /forget to remove saved facts)."
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text("Taking a screenshot...")
    result = await asyncio.to_thread(screen_tool.run, action="screenshot", path="/tmp/komen_pc_screen.png")
    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
        return
    with open(result["path"], "rb") as f:
        await update.message.reply_photo(photo=f)


async def cmd_phonescreenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text("Taking a phone screenshot...")
    result = await asyncio.to_thread(phone_tool.run, action="screenshot", path="/tmp/komen_phone_screen.png")
    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
        return
    with open(result["path"], "rb") as f:
        await update.message.reply_photo(photo=f)


async def cmd_openapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /openapp notepad")
        return
    result = await asyncio.to_thread(screen_tool.run, action="open_app", app_name=" ".join(context.args))
    await update.message.reply_text(str(result))


async def cmd_openphoneapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /openphoneapp facebook")
        return
    result = await asyncio.to_thread(phone_tool.run, action="open_app_by_name", app_name=" ".join(context.args))
    await update.message.reply_text(str(result))


async def _power_action(update: Update, action: str):
    if not _authorized(update):
        return
    result = await asyncio.to_thread(system_tool.run, action=action)
    await update.message.reply_text(str(result))


async def cmd_shutdown(update, context): await _power_action(update, "shutdown")
async def cmd_restart(update, context): await _power_action(update, "restart")
async def cmd_sleep(update, context): await _power_action(update, "sleep")
async def cmd_lock(update, context): await _power_action(update, "lock")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any plain message is treated as a free-form task for the full agent."""
    if not _authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    goal = update.message.text
    await update.message.reply_text("Working on it...")
    agent = _agent_for(update.effective_chat.id)
    result = await asyncio.to_thread(agent.run_task, goal)
    await update.message.reply_text(result or "(done, no summary returned)")

    # Send back any screenshots the agent took while completing this task.
    for file_path in agent.produced_files:
        try:
            with open(file_path, "rb") as f:
                await update.message.reply_photo(photo=f)
        except Exception as e:
            await update.message.reply_text(f"(couldn't attach {file_path}: {e})")


async def _post_init(application: Application):
    global _main_loop
    _main_loop = asyncio.get_running_loop()


def main():
    global _bot_app

    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: set TELEGRAM_BOT_TOKEN")
        return
    if not config.PROVIDER_SPECS:
        print("ERROR: no LLM providers configured (set an API key, see README)")
        return
    if not config.TELEGRAM_AUTHORIZED_CHAT_IDS:
        print("WARNING: TELEGRAM_AUTHORIZED_CHAT_IDS is empty — nobody will be able to use this bot.")

    confirm.set_confirm_handler(telegram_confirm)

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    _bot_app = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("phonescreenshot", cmd_phonescreenshot))
    app.add_handler(CommandHandler("openapp", cmd_openapp))
    app.add_handler(CommandHandler("openphoneapp", cmd_openphoneapp))
    app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(handle_confirm_callback, pattern=r"^confirm:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Komen AI Telegram bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
