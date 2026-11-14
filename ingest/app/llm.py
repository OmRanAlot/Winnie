"""Minimal LLM abstraction: a Protocol, an Anthropic implementation, and a scripted fake."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

Message = dict[str, str]  # {"role": "user"|"assistant", "content": "..."}


class LLM(Protocol):
    def complete(
        self, *, system: str, messages: Sequence[Message], model: str, max_tokens: int = 4096
    ) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: str) -> None:
        import anthropic  # lazy

        self._client: Any = anthropic.Anthropic(api_key=api_key)

    def complete(
        self, *, system: str, messages: Sequence[Message], model: str, max_tokens: int = 4096
    ) -> str:
        resp = self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=list(messages)
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class FakeLLM:
    """Scripted responses, consumed in order (the last one repeats). Entries may be callables
    taking (system, messages) so a test can branch on the prompt. Records every call."""

    def __init__(self, responses: Sequence[str | Callable[[str, Sequence[Message]], str]]) -> None:
        if not responses:
            raise ValueError("FakeLLM needs at least one response")
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, messages: Sequence[Message], model: str, max_tokens: int = 4096
    ) -> str:
        self.calls.append({"system": system, "messages": list(messages), "model": model})
        entry = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return entry(system, messages) if callable(entry) else entry
