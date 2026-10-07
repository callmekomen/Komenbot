# Komen AI

An autonomous agent that plans and executes open-ended tasks on your **PC**
and **Android phone**. Control it from the terminal, from **Telegram**, or by
voice with **"Hey Komen."**

It is **not tied to any one AI company** — Anthropic, OpenAI, Groq, Gemini,
and others all work, with automatic failover between them.

## How it works

You give it a goal in plain English. The LLM breaks it into steps and calls
tools; results feed back so it can decide the next step, until the task is done.

```
You: "Open Chrome, search for the weather in Tokyo, and tell me the forecast"
  -> browser_action(open, url=google.com)
  -> browser_action(type, text="weather in Tokyo")
  -> browser_action(read)
  -> replies with the forecast
```

## Tools included

| Tool | What it does |
|---|---|
| `run_shell_command` | Runs shell commands on the PC |
| `read_file` / `write_file` / `list_directory` | File system access |
| `browser_action` | Open pages, click, type, read text, screenshot (Playwright) |
| `screen_action` | Mouse/keyboard control + screenshots on the PC (pyautogui) |
| `phone_action` | Tap, swipe, type, launch apps, lock/wake, screenshot on Android (ADB) |
| `system_power_action` | Shut down / restart / sleep / lock the PC |
| `alarm_action` | Set a real phone alarm (ADB) or a scheduled PC notification |
| `memory_action` | Save/recall/forget facts that persist across sessions |

---

## Choosing your AI provider

You give Komen AI a list of providers **in priority order**. It falls through
to the next one whenever the current one fails — bad key, rate limit, outage,
timeout. Failover happens *mid-conversation*: if Groq dies halfway through a
task, Gemini picks up the same conversation and finishes it.

This works because messages are stored in a neutral internal format and
translated per-provider, rather than in any one vendor's wire format.

**Supported out of the box:** `anthropic`, `openai`, `groq`, `gemini`,
`openrouter`, `deepseek`, `together`, `mistral`, `ollama` (local), plus
`custom` for anything else speaking the OpenAI API format.

**No vendor SDKs needed** — everything goes over plain HTTP via `requests`.

### Easy setup

```bash
export KOMEN_PROVIDERS=groq,gemini,anthropic
export GROQ_API_KEY=gsk_...
export GEMINI_API_KEY=AIza...
export ANTHROPIC_API_KEY=sk-ant-...
```

Groq is tried first, then Gemini, then Anthropic. Providers with no key set
are skipped silently, so you can list more than you have keys for.

Override any default model:
```bash
export GROQ_MODEL=llama-3.3-70b-versatile
export GEMINI_MODEL=gemini-2.0-flash
export OPENAI_MODEL=gpt-4o
```

Check what's actually live:
```bash
python main.py --providers
```

### Advanced setup (custom endpoints, multiple keys per provider)

```bash
export KOMEN_PROVIDERS_JSON='[
  {"provider":"groq","api_key":"gsk_...","model":"llama-3.3-70b-versatile"},
  {"provider":"custom","api_key":"xxx","model":"my-model",
   "base_url":"https://my-endpoint.com/v1"},
  {"provider":"ollama","model":"llama3.1"}
]'
```

`custom` covers any OpenAI-compatible endpoint — self-hosted models,
LM Studio, vLLM, a company gateway, whatever.

### Which to pick

- **Groq** — very fast, generous free tier. Good first choice.
- **Gemini** — free tier, solid tool-calling.
- **Anthropic / OpenAI** — strongest at multi-step reasoning, which matters
  for long chained tasks. Paid.
- **Ollama** — fully local and free, nothing leaves your machine, but
  tool-calling quality varies a lot by model. Best as a last-resort fallback.

A practical setup: a fast/cheap provider first, a stronger paid one as backup.

### Caveat: tool-calling quality varies

Every provider here supports tool calling, but **not equally well.** Smaller
and local models are noticeably worse at chaining many steps without getting
confused or hallucinating tool arguments. If complex tasks misbehave, try
moving a stronger model to the front of your chain before assuming a bug.

---

## Vision — it can actually see the screen

When a vision-capable provider is active, screenshots are fed back to the
model **as real images**, not just saved to disk. That's the difference
between "tap 540,1200 and hope" and "find the login button and tap it."

- Screenshots are downscaled to 1568px on the long edge before sending
  (needs Pillow), which keeps image-token costs sane.
- The model is told both the original and sent resolution and instructed to
  scale coordinates back up, so clicks land in the right place.
- It's prompted to screenshot *again* after acting, to verify the screen
  actually changed instead of assuming.

**Vision support is auto-detected from the model name.** Text-only models
(Llama 3.3, Mixtral, DeepSeek-chat, etc.) silently receive the text without
images rather than erroring — so a text-only provider can still sit in your
chain as a fallback. Override the guess explicitly if needed:

```bash
export KOMEN_PROVIDERS_JSON='[{"provider":"custom","api_key":"k",
  "model":"my-vlm","base_url":"https://host/v1","vision":true}]'
```

`python main.py --providers` shows which of your providers can see.

**If you want GUI control to work well, put a vision model first** —
gpt-4o, gemini-2.0-flash, or claude-sonnet. A text-only chain still does
files, shell, apps, alarms and browser text fine; it just can't look at things.

## Memory — it remembers across restarts

Durable facts persist in `~/.komen_ai/memory.json` (override with
`KOMEN_MEMORY_FILE`) and are injected into the system prompt every run, so
Komen AI doesn't rediscover your setup every time.

It saves things on its own — a resolved package name, a folder path, a device
quirk, a stated preference — and you can drive it directly: "remember my
work folder is D:/projects", "what do you remember?", "forget my downloads path".

- Keys are unique, so re-saving updates instead of duplicating.
- Capped at `KOMEN_MAX_FACTS` (default 200); stalest are dropped first.
- Writes are atomic and a corrupted file degrades to empty rather than crashing.
- It's told not to store secrets or passwords.

In Telegram: `/memory` to list, `/forget <key>` to remove, `/reset` to clear
the *conversation* (memory survives).

## Context handling

Long sessions used to grow unbounded. Now:
- History caps at `KOMEN_MAX_HISTORY` messages (default 40), dropping oldest
  first while preserving the original goal and never orphaning a tool result.
- Only the last `KOMEN_MAX_IMAGES` screenshots (default 3) stay in context;
  older ones become text placeholders, since images dominate token cost.
- Telegram keeps **one agent per chat**, so separate chats don't bleed
  context into each other.

---

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

**For phone control**, install [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)
so `adb` is on your PATH, then on the phone:
- Enable Developer Options (Settings → About Phone → tap "Build Number" 7 times)
- Enable USB Debugging (Settings → Developer Options)
- Connect via USB, or `adb tcpip 5555` + `adb connect <phone-ip>:5555` for Wi-Fi
- Confirm with `adb devices`

**For PC GUI control** (`screen_action`), run in a normal graphical desktop
session, not a headless server.

## Running

```bash
python main.py                          # interactive terminal mode
python main.py "organize my Downloads"  # one-shot task
python main.py --providers              # show configured providers
python telegram_bot.py                  # remote control via Telegram
python voice_assistant.py               # "Hey Komen" voice control
```

---

## Controlling it from Telegram

Talk to Komen AI from your phone while it runs on your laptop.

1. Message **@BotFather** on Telegram → `/newbot`. You get a token.
2. Message your new bot once so it can see your chat.
3. Get your chat ID: message **@userinfobot**, or visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`.
4. Set:
   ```bash
   export TELEGRAM_BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxx
   export TELEGRAM_AUTHORIZED_CHAT_IDS=123456789
   ```
   (Comma-separate for multiple chats. Anyone not listed is ignored.)
5. Run `python telegram_bot.py`
6. **Just talk to it normally — no slash needed:**
   - "screenshot my phone" → takes it, sends the image back
   - "restart my laptop" → confirms, then restarts
   - "lock my phone" / "open facebook" / "set an alarm for 7pm"

   Optional shortcuts also exist: `/screenshot`, `/phonescreenshot`,
   `/openapp <name>`, `/openphoneapp <name>`, `/shutdown`, `/restart`,
   `/sleep`, `/lock`.

**Confirmations over Telegram** arrive as **Yes/No buttons** instead of a
terminal prompt. No response within `KOMEN_CONFIRM_TIMEOUT` seconds
(default 120) counts as declined.

**Important:** the laptop must stay on and running `telegram_bot.py` — this
is your own machine listening, not a cloud service. You can't shut it down
remotely and then turn it back on.

---

## Voice control ("Hey Komen")

Listens through the PC mic, wakes on "Hey Komen," replies "Hi, how may I
help you?" out loud, then executes what you say next.

```bash
pip install SpeechRecognition pyttsx3 pyaudio
python voice_assistant.py
```

`pyaudio` is the fussy one:
- **Windows:** if pip fails → `pip install pipwin` then `pipwin install pyaudio`
- **Mac:** `brew install portaudio` first
- **Linux:** `sudo apt install portaudio19-dev python3-pyaudio` first

**How it hears and talks:** transcription uses Google's free web speech API
(no key needed, but sends short audio clips — only after detecting speech,
not a constant stream — and needs internet). Talking back uses `pyttsx3`,
fully offline via your OS's built-in voice. For zero audio leaving your
machine, swap in [Vosk](https://alphacephei.com/vosk/) (bigger setup, not
wired in by default).

**Limits:** it only listens on the machine it runs on, and it mishears
sometimes — fuzzy matching covers "hey comment"/"hey command," but noisy
rooms will trip it up.

---

## Safety notes

- Actions that change something (shell commands, file writes, clicks,
  typing, phone taps, power actions) **ask you to confirm** — terminal
  prompt for `main.py`, Yes/No buttons for Telegram. Disable with
  `KOMEN_CONFIRM=false` (not recommended).
- Only chat IDs in `TELEGRAM_AUTHORIZED_CHAT_IDS` can use the bot. Keep your
  bot token secret.
- A blocklist in `config.py` stops obviously dangerous shell commands
  (`rm -rf /`, disk wipes, fork bombs) even if confirmed.
- `MAX_AGENT_STEPS` (default 25) caps tool calls per task, so a confused
  agent can't loop forever.
- Review `config.py` before giving Komen AI access to anything sensitive.

## Extending it

**New tool:** create a file in `tools/` with a `SCHEMA` dict and a `run(...)`
function, then register it in `tools/__init__.py` (`ALL_SCHEMAS` + `DISPATCH`).
Every provider picks it up automatically.

**New AI provider:** if it speaks the OpenAI format, just use `custom` with a
`base_url` — no code needed. Otherwise subclass `BaseProvider` in
`providers.py`, implement `complete()` plus the wire translation, and add it
to `PRESETS`.
