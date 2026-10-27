"""LLM clients: OpenAI Chat Completions (httpx) and a deterministic mock.

`get_llm()` returns an OpenAI-backed client when a key is configured and
mock mode is not forced, otherwise the scripted MockLLM. Both expose the same
`chat(messages, tools, meta)` contract so agent code is mode-agnostic.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .. import config


class LLMError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    def __init__(self, budget: str):
        super().__init__(f"{budget} budget exceeded")
        self.budget = budget


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    mock: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class BaseLLM:
    mode = "base"
    model = ""

    def chat(self, messages: list[dict[str, Any]],
             tools: Optional[list[dict[str, Any]]] = None,
             meta: Optional[dict[str, Any]] = None) -> LLMResult:
        raise NotImplementedError


class OpenAIClient(BaseLLM):
    mode = "openai"

    def __init__(self, model: Optional[str] = None):
        if not config.OPENAI_API_KEY:
            raise LLMError("OPENAI_API_KEY is not set")
        self.model = model or config.OPENAI_MODEL
        self._client = httpx.Client(
            base_url=config.OPENAI_BASE_URL, timeout=httpx.Timeout(90.0, connect=15.0),
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}",
                     "Content-Type": "application/json"})

    def chat(self, messages, tools=None, meta=None) -> LLMResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages,
                                "temperature": 0.2}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last_error: Optional[str] = None
        for attempt in range(4):
            started = time.monotonic()
            try:
                resp = self._client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_error = f"transport error: {exc}"
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json(), int((time.monotonic() - started) * 1000))
                last_error = f"HTTP {resp.status_code}: {resp.text[:400]}"
                if resp.status_code not in {429, 500, 502, 503, 504}:
                    break
            time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"OpenAI request failed: {last_error}")

    @staticmethod
    def _parse(data: dict[str, Any], duration_ms: int) -> LLMResult:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except ValueError:
                args = {"_unparsed": str(args_raw)}
            tool_calls.append(ToolCall(id=raw.get("id") or f"call_{len(tool_calls)}",
                                       name=fn.get("name") or "", args=args))
        usage = data.get("usage") or {}
        return LLMResult(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            model=data.get("model", ""),
            mock=False,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            duration_ms=duration_ms)


def get_llm(model: Optional[str] = None) -> BaseLLM:
    if config.LLM_MODE == "openai":
        try:
            return OpenAIClient(model)
        except LLMError:
            pass
    from .mock import MockLLM
    return MockLLM(model)
