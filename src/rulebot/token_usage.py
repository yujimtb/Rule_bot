from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens_override: int = 0

    @property
    def total_tokens(self) -> int:
        if self.total_tokens_override > 0:
            return self.total_tokens_override
        return self.input_tokens + self.output_tokens + self.reasoning_output_tokens

    @property
    def effective_tokens(self) -> int:
        return max(self.total_tokens - self.cached_input_tokens, 0)

    def to_dict(self) -> dict[str, int]:
        return {
            "total_tokens": self.total_tokens,
            "effective_tokens": self.effective_tokens,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
        }

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if self.total_tokens_override > 0 or other.total_tokens_override > 0:
            total_tokens_override = self.total_tokens + other.total_tokens
        else:
            total_tokens_override = 0
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            total_tokens_override=total_tokens_override,
        )


def usage_from_dict(value: object) -> TokenUsage:
    if not isinstance(value, dict):
        return TokenUsage()
    total_tokens = _int_value(value.get("total_tokens")) + _int_value(value.get("totalTokens"))
    return TokenUsage(
        input_tokens=_int_value(value.get("input_tokens")) + _int_value(value.get("inputTokens")),
        cached_input_tokens=(
            _int_value(value.get("cached_input_tokens"))
            + _int_value(value.get("cachedInputTokens"))
            + _int_value(value.get("cache_read_input_tokens"))
            + _int_value(value.get("cache_creation_input_tokens"))
        ),
        output_tokens=_int_value(value.get("output_tokens")) + _int_value(value.get("outputTokens")),
        reasoning_output_tokens=(
            _int_value(value.get("reasoning_output_tokens")) + _int_value(value.get("reasoningOutputTokens"))
        ),
        total_tokens_override=total_tokens,
    )


def parse_codex_json_output(stdout: str) -> tuple[str, TokenUsage]:
    messages: list[str] = []
    usage = TokenUsage()

    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    messages.append(text.strip())
        elif event.get("type") == "turn.completed":
            usage += usage_from_dict(event.get("usage"))

    text = "\n".join(messages).strip()
    if not text:
        text = stdout.strip()
    return text, usage


def parse_claude_json_output(stdout: str) -> tuple[str, TokenUsage]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip(), TokenUsage()
    if not isinstance(data, dict):
        return stdout.strip(), TokenUsage()

    result = data.get("structured_output")
    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False)
    else:
        text_value = data.get("result") or data.get("text") or data.get("message") or ""
        text = text_value if isinstance(text_value, str) else json.dumps(text_value, ensure_ascii=False)

    usage = usage_from_dict(data.get("usage"))
    return text.strip(), usage


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
