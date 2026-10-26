"""Thin LLM client abstraction.

Kept separate from cleaner.py so tests (and the evaluation script) can swap
in a deterministic mock without ever touching the network or a real API key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> tuple[str, Usage]:
        """Return (response_text, usage)."""
        ...


class AnthropicClient:
    """Real client, backed by the Anthropic Python SDK.

    Reads ANTHROPIC_API_KEY from the environment -- never pass a key on the
    command line or hardcode one, or it will end up in your shell history
    and (worse) potentially in a commit.
    """

    def __init__(self, model: str, max_tokens: int = 1000):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it in your shell "
                "(export ANTHROPIC_API_KEY=sk-ant-...) -- never put it in code or a config file."
            )
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "The 'anthropic' package is required. Install with: pip install anthropic"
            ) from e
        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> tuple[str, Usage]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return text, usage


class MockClient:
    """Deterministic stand-in for tests and offline development.

    Ignores the actual grid content and returns a fixed response so the
    parsing/CSV-writing path can be exercised without network access.
    """

    def __init__(self, model: str = "mock-model", fixed_response: str | None = None):
        self.model = model
        self._fixed_response = fixed_response

    def complete(self, system: str, user: str) -> tuple[str, Usage]:
        if self._fixed_response is not None:
            text = self._fixed_response
        else:
            text = '{"columns": ["a", "b"], "rows": [{"values": {"a": "1", "b": "2"}}]}'
        # Rough token estimate for offline testing (~4 chars/token), not billed.
        return text, Usage(input_tokens=len(user) // 4, output_tokens=len(text) // 4)
