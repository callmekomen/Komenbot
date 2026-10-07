"""
Komen AI - Configuration
Loads settings from environment variables (or a local .env file if present).
"""
import json
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can still be set manually


# ---------------------------------------------------------------------------
# LLM PROVIDERS
# ---------------------------------------------------------------------------
# Komen AI is provider-agnostic. You list providers in priority order and it
# falls through to the next one whenever the current one fails (bad key,
# rate limit, outage, timeout).
#
# EASY WAY — set KOMEN_PROVIDERS to a comma-separated priority list, then
# set that provider's usual API key env var:
#
#   export KOMEN_PROVIDERS=groq,gemini,anthropic
#   export GROQ_API_KEY=gsk_...
#   export GEMINI_API_KEY=AIza...
#   export ANTHROPIC_API_KEY=sk-ant-...
#
# Optionally override a model:
#   export GROQ_MODEL=llama-3.3-70b-versatile
#
# ADVANCED WAY — full control via JSON (useful for custom/self-hosted
# endpoints, or two keys from the same provider):
#
#   export KOMEN_PROVIDERS_JSON='[
#     {"provider":"groq","api_key":"gsk_...","model":"llama-3.3-70b-versatile"},
#     {"provider":"custom","api_key":"xxx","model":"my-model",
#      "base_url":"https://my-endpoint.com/v1"}
#   ]'
#
# Supported provider names: anthropic, openai, groq, gemini, openrouter,
# deepseek, together, mistral, ollama, custom
# ---------------------------------------------------------------------------

# Where each provider looks for its key/model by default.
_ENV_KEYS = {
    "anthropic":  ("ANTHROPIC_API_KEY",  "ANTHROPIC_MODEL"),
    "openai":     ("OPENAI_API_KEY",     "OPENAI_MODEL"),
    "groq":       ("GROQ_API_KEY",       "GROQ_MODEL"),
    "gemini":     ("GEMINI_API_KEY",     "GEMINI_MODEL"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_MODEL"),
    "deepseek":   ("DEEPSEEK_API_KEY",   "DEEPSEEK_MODEL"),
    "together":   ("TOGETHER_API_KEY",   "TOGETHER_MODEL"),
    "mistral":    ("MISTRAL_API_KEY",    "MISTRAL_MODEL"),
    "ollama":     ("OLLAMA_API_KEY",     "OLLAMA_MODEL"),   # Ollama ignores the key
    "custom":     ("CUSTOM_API_KEY",     "CUSTOM_MODEL"),
}


def _load_provider_specs():
    # Advanced: explicit JSON wins if present.
    raw_json = os.environ.get("KOMEN_PROVIDERS_JSON", "").strip()
    if raw_json:
        try:
            specs = json.loads(raw_json)
            if isinstance(specs, list):
                return specs
            print("WARNING: KOMEN_PROVIDERS_JSON must be a JSON list; ignoring it.")
        except json.JSONDecodeError as e:
            print(f"WARNING: KOMEN_PROVIDERS_JSON is not valid JSON ({e}); ignoring it.")

    # Easy: comma-separated names, keys pulled from their usual env vars.
    names = os.environ.get("KOMEN_PROVIDERS", "").strip()
    if not names:
        # Nothing declared — fall back to whichever keys happen to be set,
        # in a sensible default order.
        names = "anthropic,openai,groq,gemini,openrouter,deepseek,together,mistral"

    specs = []
    for name in [n.strip().lower() for n in names.split(",") if n.strip()]:
        key_var, model_var = _ENV_KEYS.get(name, (None, None))
        if not key_var:
            print(f"WARNING: unknown provider '{name}' in KOMEN_PROVIDERS; skipping.")
            continue
        api_key = os.environ.get(key_var, "")
        if name == "ollama" and not api_key:
            api_key = "ollama"  # local server needs no real key, but must be non-empty
        if not api_key:
            continue  # silently skip providers with no key set
        specs.append({
            "provider": name,
            "api_key": api_key,
            "model": os.environ.get(model_var, "") or None,
            "base_url": os.environ.get(f"{name.upper()}_BASE_URL", "") or None,
        })
    return specs


PROVIDER_SPECS = _load_provider_specs()

# Kept for backwards compatibility with older scripts/checks.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MAX_TOKENS = int(os.environ.get("KOMEN_MAX_TOKENS", "4096"))


# ---------------------------------------------------------------------------
# Vision & context
# ---------------------------------------------------------------------------
# Screenshots are sent to the model as real images when the active provider
# supports vision. Images are expensive in tokens, so only the most recent
# few are kept in history; older ones are replaced with a placeholder.
MAX_IMAGES_IN_HISTORY = int(os.environ.get("KOMEN_MAX_IMAGES", "3"))

# Hard cap on conversation length, so long sessions don't blow the context
# window or run up cost. Oldest messages are dropped first.
MAX_HISTORY_MESSAGES = int(os.environ.get("KOMEN_MAX_HISTORY", "40"))


# ---------------------------------------------------------------------------
# Agent behavior
# ---------------------------------------------------------------------------
MAX_AGENT_STEPS = int(os.environ.get("KOMEN_MAX_STEPS", "25"))  # safety cap on tool-call loops


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
# If True, the agent asks for confirmation before any action that modifies
# the system (shell commands, file writes, phone actions, power actions).
CONFIRM_DESTRUCTIVE_ACTIONS = os.environ.get("KOMEN_CONFIRM", "true").lower() != "false"

# Commands that are always blocked outright, regardless of confirmation.
# Note: shutdown/restart/sleep are NOT blocked — use system_power_action.
BLOCKED_SHELL_PATTERNS = [
    "rm -rf /", "mkfs", ":(){:|:&};:", "dd if=", "> /dev/sda",
    "adb reboot bootloader", "format c:",
]


# ---------------------------------------------------------------------------
# Phone (ADB)
# ---------------------------------------------------------------------------
ADB_PATH = os.environ.get("ADB_PATH", "adb")  # assumes adb is on PATH
DEFAULT_DEVICE_ID = os.environ.get("KOMEN_DEVICE_ID", "")  # blank = first connected device


# ---------------------------------------------------------------------------
# Browser automation
# ---------------------------------------------------------------------------
HEADLESS_BROWSER = os.environ.get("KOMEN_HEADLESS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Telegram remote control
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# The chat ID(s) allowed to control this bot. Get yours by messaging
# @userinfobot, or via https://api.telegram.org/bot<TOKEN>/getUpdates
_raw_chat_ids = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "")
TELEGRAM_AUTHORIZED_CHAT_IDS = [
    int(cid.strip()) for cid in _raw_chat_ids.split(",") if cid.strip()
]
TELEGRAM_CONFIRM_TIMEOUT_SECONDS = int(os.environ.get("KOMEN_CONFIRM_TIMEOUT", "120"))
