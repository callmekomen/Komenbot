"""
Komen AI - Agent core.

Provider-agnostic plan -> act -> observe loop with:
  - VISION: screenshots are fed back to the model as actual images, so it can
    see the screen instead of guessing coordinates blindly.
  - MEMORY: durable facts are injected into the system prompt every run and
    can be written by the model mid-task.
  - CONTEXT TRIMMING: history is capped so long sessions don't blow the
    context window or run up costs.

Messages stay in providers.py's neutral format, so failover mid-task is safe.
"""
import config
import images
import memory
from providers import ProviderChain, ProviderError
from tools import ALL_SCHEMAS, execute_tool

BASE_SYSTEM_PROMPT = """You are Komen AI, an autonomous agent that completes tasks on a \
user's PC and Android phone by calling tools.

Rules you must follow:
- Break the user's goal into concrete steps before acting.
- Use tools one at a time and read each result before deciding the next step.
- To open an app, prefer the friendly-name actions ('open_app' on PC, \
'open_app_by_name' on phone) over guessing exact paths or package names. \
If a phone app name can't be resolved, use 'list_apps' to see what's installed.
- For shutting down, restarting, sleeping, or locking the PC, use \
'system_power_action' rather than raw shell commands.
- If a step fails, explain what happened and try a reasonable alternative rather \
than repeating the exact same failing action.
- If the task requires an irreversible or risky action (deleting files, sending \
messages, purchases, etc.), state clearly what you're about to do — the tools \
themselves will prompt the human for confirmation on sensitive actions.
- When the goal is complete, stop calling tools and give a clear final summary \
of what you did.

USING YOUR EYES:
- When you take a screenshot, the image is attached to the next message — you \
can actually see it. Look before you act.
- NEVER guess tap or click coordinates. Take a screenshot, find the element in \
the image, estimate its pixel position from the image, then act.
- Screenshots may be downscaled before you see them. The attachment tells you \
both the original and sent resolution — scale your coordinates back up to the \
ORIGINAL resolution before clicking or tapping.
- After an action that should change the screen, take another screenshot to \
verify it actually worked instead of assuming it did.

USING YOUR MEMORY:
- Facts you've saved appear below. Trust them, but re-verify if one looks stale.
- When you discover something durable and reusable (a package name, a folder \
path, a device quirk, a user preference), save it with memory_action so you \
never have to rediscover it.
- Don't store secrets, passwords, or anything sensitive.
"""


class KomenAgent:
    def __init__(self, provider_specs: list = None, verbose: bool = True):
        self.verbose = verbose
        self.chain = ProviderChain(provider_specs or config.PROVIDER_SPECS, verbose=verbose)
        self.messages = []
        self.produced_files = []   # files generated during the last run_task
        self.pending_images = []   # images to attach to the next model call

        if self.verbose:
            available = self.chain.describe()
            if available:
                print(f"[Komen AI] Provider chain: {' -> '.join(available)}")
                if not self.chain.has_vision():
                    print("[Komen AI] NOTE: no vision-capable provider configured — "
                          "screenshots won't be seen, only saved.")
            else:
                print("[Komen AI] WARNING: no providers configured. Set an API key.")

    def _log(self, *args):
        if self.verbose:
            print(*args)

    def _system_prompt(self) -> str:
        return BASE_SYSTEM_PROMPT + memory.as_prompt_block()

    def _trim_history(self):
        """
        Keep context bounded. Two separate pressures:
          1. Too many messages -> drop the oldest, but never split an
             assistant tool_calls message from its matching tool results
             (providers reject that as malformed).
          2. Too many images -> images dominate token cost, so keep only the
             most recent few and replace older ones with a text placeholder.
        """
        max_msgs = config.MAX_HISTORY_MESSAGES
        if len(self.messages) > max_msgs:
            keep = self.messages[-max_msgs:]
            # Never start on orphaned tool results.
            while keep and keep[0]["role"] == "tool":
                keep.pop(0)
            # Always retain the original goal for context.
            if self.messages and self.messages[0] not in keep:
                keep.insert(0, self.messages[0])
            dropped = len(self.messages) - len(keep)
            if dropped > 0:
                self._log(f"[Komen AI] (trimmed {dropped} old messages from context)")
            self.messages = keep

        image_msgs = [m for m in self.messages if m.get("images")]
        excess = len(image_msgs) - config.MAX_IMAGES_IN_HISTORY
        for m in image_msgs[:max(0, excess)]:
            count = len(m["images"])
            m["images"] = []
            m["content"] = (m.get("content", "") +
                            f" [{count} older screenshot(s) dropped from context]")

    def _attach_images_for(self, tool_name: str, tool_input: dict, result: dict):
        """If a tool produced an image file, queue it to be SEEN next turn."""
        if not isinstance(result, dict) or not result.get("path"):
            return
        if tool_input.get("action") != "screenshot":
            return
        if not self.chain.has_vision():
            return

        encoded = images.encode_image(result["path"])
        if "error" in encoded:
            self._log(f"[Komen AI] (couldn't attach screenshot: {encoded['error']})")
            return

        where = "phone" if tool_name == "phone_action" else "PC"
        note = f"Screenshot of the {where}."
        if encoded.get("original_size"):
            note += (f" Original resolution {encoded['original_size']}, "
                     f"shown to you at {encoded['sent_size']} — scale any "
                     f"coordinates back up to the original before acting.")
        self.pending_images.append({"note": note, "image": {
            "media_type": encoded["media_type"], "data": encoded["data"]}})

    def run_task(self, goal: str) -> str:
        self.produced_files = []
        self.messages.append({"role": "user", "content": goal})

        for _ in range(config.MAX_AGENT_STEPS):
            self._trim_history()
            try:
                response = self.chain.complete(
                    system=self._system_prompt(),
                    messages=self.messages,
                    tools=ALL_SCHEMAS,
                    max_tokens=config.MAX_TOKENS,
                )
            except ProviderError as e:
                return f"[Komen AI] Could not reach any AI provider.\n{e}"

            if response.text.strip():
                self._log(f"\n[Komen AI] {response.text.strip()}")

            self.messages.append({
                "role": "assistant",
                "content": response.text,
                "tool_calls": response.tool_calls,
            })

            if not response.wants_tools:
                return response.text

            results = []
            for tc in response.tool_calls:
                self._log(f"[Komen AI] -> calling {tc['name']}({tc['input']})")
                result = execute_tool(tc["name"], tc["input"])
                self._log(f"[Komen AI] <- result: {str(result)[:300]}")

                if isinstance(result, dict) and result.get("path"):
                    self.produced_files.append(result["path"])
                self._attach_images_for(tc["name"], tc["input"], result)

                results.append({"id": tc["id"], "name": tc["name"], "content": str(result)})

            self.messages.append({"role": "tool", "results": results})

            # Screenshots ride in on a following user message, because most
            # provider APIs don't allow images inside tool-result blocks.
            if self.pending_images:
                self.messages.append({
                    "role": "user",
                    "content": " ".join(p["note"] for p in self.pending_images),
                    "images": [p["image"] for p in self.pending_images],
                })
                self.pending_images = []

        return "[Komen AI] Reached max step limit without finishing. Task may be incomplete."

    def reset(self):
        """Clear conversation history (memory on disk is untouched)."""
        self.messages = []
        self.pending_images = []
        self.produced_files = []
