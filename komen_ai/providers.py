"""
Komen AI - Multi-provider LLM layer.

Lets Komen AI run on Anthropic, OpenAI, Groq, Gemini, OpenRouter, DeepSeek,
Together, a local Ollama server, or anything else that speaks one of those
APIs. You list providers in priority order; if one fails (bad key, rate
limit, outage, timeout), it automatically falls through to the next.

KEY IDEA: messages are stored in a neutral internal format, NOT any one
vendor's format. Each adapter translates to/from its own wire format. That's
what makes mid-conversation failover safe — provider B can pick up a
conversation that provider A started.

Neutral message format:
    {"role": "user",      "content": "text", "images": [ImagePart, ...]}
    {"role": "assistant", "content": "text", "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "results": [{"id","name","content"}, ...]}

ToolCall:  {"id": str, "name": str, "input": dict}
ImagePart: {"media_type": "image/jpeg", "data": "<base64>"}

Images are optional and only sent to providers that support vision — a
text-only model (e.g. Llama 3.3 on Groq) silently gets the text without them,
so a vision-capable fallback can still take over mid-task.
"""
import json
import uuid

import requests


# Substrings of model names that are known NOT to accept images. Anything
# else is assumed vision-capable; override explicitly with "vision" in a spec.
_TEXT_ONLY_HINTS = (
    "llama-3.1", "llama-3.3", "llama3.1", "llama3.3", "mixtral",
    "gemma2", "deepseek-chat", "deepseek-reasoner", "whisper",
    "text-embedding", "qwen2.5-coder", "codestral",
)


def guess_vision_support(model: str) -> bool:
    m = (model or "").lower()
    return not any(hint in m for hint in _TEXT_ONLY_HINTS)


class ProviderError(Exception):
    """Raised when a provider fails in a way that should trigger failover."""


class LLMResponse:
    def __init__(self, text="", tool_calls=None, provider="", model=""):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.provider = provider
        self.model = model

    @property
    def wants_tools(self):
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseProvider:
    name = "base"

    def __init__(self, api_key: str, model: str, base_url: str = None, timeout: int = 120,
                 vision: bool = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.vision = guess_vision_support(model) if vision is None else vision

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, messages: list, tools: list, max_tokens: int) -> LLMResponse:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicProvider(BaseProvider):
    name = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-5"

    def complete(self, system, messages, tools, max_tokens):
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self._to_wire(messages),
        }
        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t["description"],
                 "input_schema": t["input_schema"]}
                for t in tools
            ]
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload, timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(f"anthropic request failed: {e}")

        if r.status_code != 200:
            raise ProviderError(f"anthropic HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        text_parts, tool_calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block["id"], "name": block["name"],
                                    "input": block.get("input", {})})
        return LLMResponse("\n".join(text_parts), tool_calls, self.name, self.model)

    def _to_wire(self, messages):
        wire = []
        for m in messages:
            if m["role"] == "user":
                if m.get("images") and self.vision:
                    content = [{"type": "text", "text": m.get("content", "")}]
                    for img in m["images"]:
                        content.append({"type": "image", "source": {
                            "type": "base64", "media_type": img["media_type"],
                            "data": img["data"],
                        }})
                    wire.append({"role": "user", "content": content})
                else:
                    wire.append({"role": "user", "content": m.get("content", "")})
            elif m["role"] == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    content.append({"type": "tool_use", "id": tc["id"],
                                     "name": tc["name"], "input": tc["input"]})
                wire.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
            elif m["role"] == "tool":
                wire.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": res["id"], "content": res["content"]}
                    for res in m["results"]
                ]})
        return wire


# ---------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, Groq, OpenRouter, DeepSeek, Together, Ollama, ...)
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(BaseProvider):
    """
    Works with any API that implements OpenAI's /chat/completions spec.
    Just point base_url at the right host.
    """
    name = "openai"
    DEFAULT_MODEL = "gpt-4o"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def complete(self, system, messages, tools, max_tokens):
        base = (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": self._to_wire(system, messages),
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t["description"],
                    "parameters": t["input_schema"],
                }}
                for t in tools
            ]
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                          "Content-Type": "application/json"},
                json=payload, timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(f"{self.name} request failed: {e}")

        if r.status_code != 200:
            raise ProviderError(f"{self.name} HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise ProviderError(f"{self.name} returned unexpected shape: {str(data)[:300]}")

        tool_calls = []
        for tc in (message.get("tool_calls") or []):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": tc.get("id") or str(uuid.uuid4()),
                                "name": fn.get("name", ""), "input": args})

        return LLMResponse(message.get("content") or "", tool_calls, self.name, self.model)

    def _to_wire(self, system, messages):
        wire = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                if m.get("images") and self.vision:
                    content = [{"type": "text", "text": m.get("content", "")}]
                    for img in m["images"]:
                        content.append({"type": "image_url", "image_url": {
                            "url": f"data:{img['media_type']};base64,{img['data']}"
                        }})
                    wire.append({"role": "user", "content": content})
                else:
                    wire.append({"role": "user", "content": m.get("content", "")})
            elif m["role"] == "assistant":
                entry = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    entry["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])}}
                        for tc in m["tool_calls"]
                    ]
                wire.append(entry)
            elif m["role"] == "tool":
                for res in m["results"]:
                    wire.append({"role": "tool", "tool_call_id": res["id"],
                                  "content": res["content"]})
        return wire


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

def _clean_schema(schema):
    """Gemini accepts an OpenAPI subset; strip JSON-Schema keys it rejects."""
    if not isinstance(schema, dict):
        return schema
    allowed = {"type", "description", "enum", "properties", "required", "items", "nullable"}
    out = {}
    for k, v in schema.items():
        if k not in allowed:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _clean_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _clean_schema(v)
        else:
            out[k] = v
    return out


class GeminiProvider(BaseProvider):
    name = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash"

    def complete(self, system, messages, tools, max_tokens):
        base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        payload = {
            "contents": self._to_wire(messages),
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if tools:
            payload["tools"] = [{"function_declarations": [
                {"name": t["name"], "description": t["description"],
                 "parameters": _clean_schema(t["input_schema"])}
                for t in tools
            ]}]

        try:
            r = requests.post(
                f"{base}/models/{self.model}:generateContent",
                headers={"Content-Type": "application/json",
                          "x-goog-api-key": self.api_key},
                json=payload, timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(f"gemini request failed: {e}")

        if r.status_code != 200:
            raise ProviderError(f"gemini HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(f"gemini returned no candidates: {str(data)[:300]}")

        text_parts, tool_calls = [], []
        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({"id": str(uuid.uuid4()), "name": fc.get("name", ""),
                                    "input": fc.get("args", {})})
        return LLMResponse("\n".join(text_parts), tool_calls, self.name, self.model)

    def _to_wire(self, messages):
        wire = []
        for m in messages:
            if m["role"] == "user":
                parts = [{"text": m.get("content", "")}]
                if m.get("images") and self.vision:
                    for img in m["images"]:
                        parts.append({"inline_data": {
                            "mime_type": img["media_type"], "data": img["data"],
                        }})
                wire.append({"role": "user", "parts": parts})
            elif m["role"] == "assistant":
                parts = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for tc in m.get("tool_calls", []):
                    parts.append({"functionCall": {"name": tc["name"], "args": tc["input"]}})
                wire.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif m["role"] == "tool":
                wire.append({"role": "user", "parts": [
                    {"functionResponse": {"name": res["name"],
                                            "response": {"result": res["content"]}}}
                    for res in m["results"]
                ]})
        return wire


# ---------------------------------------------------------------------------
# Registry + failover chain
# ---------------------------------------------------------------------------

# Presets so you only need an API key for the common ones.
PRESETS = {
    "anthropic":  {"cls": AnthropicProvider, "model": "claude-sonnet-5", "base_url": None},
    "openai":     {"cls": OpenAICompatibleProvider, "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1"},
    "groq":       {"cls": OpenAICompatibleProvider, "model": "llama-3.3-70b-versatile",
                    "base_url": "https://api.groq.com/openai/v1"},
    "gemini":     {"cls": GeminiProvider, "model": "gemini-2.0-flash", "base_url": None},
    "openrouter": {"cls": OpenAICompatibleProvider, "model": "openai/gpt-4o",
                    "base_url": "https://openrouter.ai/api/v1"},
    "deepseek":   {"cls": OpenAICompatibleProvider, "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1"},
    "together":   {"cls": OpenAICompatibleProvider,
                    "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                    "base_url": "https://api.together.xyz/v1"},
    "mistral":    {"cls": OpenAICompatibleProvider, "model": "mistral-large-latest",
                    "base_url": "https://api.mistral.ai/v1"},
    "ollama":     {"cls": OpenAICompatibleProvider, "model": "llama3.1",
                    "base_url": "http://localhost:11434/v1"},
    # Generic escape hatch: any other OpenAI-compatible endpoint.
    "custom":     {"cls": OpenAICompatibleProvider, "model": None, "base_url": None},
}


def build_provider(spec: dict) -> BaseProvider:
    """
    spec = {"provider": "groq", "api_key": "...", "model": "...", "base_url": "..."}
    model/base_url are optional and fall back to the preset's defaults.
    """
    key = (spec.get("provider") or "").lower()
    preset = PRESETS.get(key)
    if not preset:
        raise ValueError(f"Unknown provider '{key}'. Known: {', '.join(PRESETS)}")
    cls = preset["cls"]
    provider = cls(
        api_key=spec.get("api_key", ""),
        model=spec.get("model") or preset["model"],
        base_url=spec.get("base_url") or preset["base_url"],
        vision=spec.get("vision"),  # None = auto-detect from model name
    )
    provider.name = key  # so logs say "groq" not "openai"
    return provider


class ProviderChain:
    """
    Holds providers in priority order and tries each in turn until one works.

    On a failure it logs the reason and moves on. If every provider fails,
    it raises ProviderError with the full list of what went wrong.
    """

    def __init__(self, specs: list, verbose=True):
        self.providers = []
        self.verbose = verbose
        for spec in specs:
            try:
                p = build_provider(spec)
            except ValueError as e:
                self._log(f"[providers] skipping: {e}")
                continue
            if not p.is_configured():
                self._log(f"[providers] skipping '{p.name}': no API key set")
                continue
            self.providers.append(p)

    def _log(self, msg):
        if self.verbose:
            print(msg)

    def describe(self):
        return [f"{p.name} ({p.model}{', vision' if p.vision else ', text-only'})"
                for p in self.providers]

    def has_vision(self) -> bool:
        return any(p.vision for p in self.providers)

    def complete(self, system, messages, tools, max_tokens) -> LLMResponse:
        if not self.providers:
            raise ProviderError(
                "No LLM providers configured. Set at least one API key "
                "(see README: 'Choosing your AI provider')."
            )
        errors = []
        for provider in self.providers:
            try:
                response = provider.complete(system, messages, tools, max_tokens)
                if provider is not self.providers[0]:
                    self._log(f"[providers] using fallback: {provider.name}")
                return response
            except ProviderError as e:
                self._log(f"[providers] {provider.name} failed, trying next: {e}")
                errors.append(f"{provider.name}: {e}")
            except Exception as e:
                self._log(f"[providers] {provider.name} raised {type(e).__name__}, trying next: {e}")
                errors.append(f"{provider.name}: {type(e).__name__}: {e}")
        raise ProviderError("All providers failed:\n  " + "\n  ".join(errors))
