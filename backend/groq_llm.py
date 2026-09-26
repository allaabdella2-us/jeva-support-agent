"""
GROQ LLM ADAPTER (openai/gpt-oss-20b, free tier)

Lets the support pipeline use Groq instead of Claude without
changing the agent loop, the tool gateway or the memory code.

How it works:
    The pipeline talks to its LLM through one call:
        client.messages.create(model, max_tokens, system, tools, messages)
    and reads back:
        response.stop_reason   ("tool_use" or "end_turn")
        response.content       text / tool_use blocks

    GroqLLMClient exposes that same interface and translates it to
    Groq's OpenAI-compatible Responses API:

        system prompt           -> instructions
        user / assistant text   -> input messages
        tool_use block          -> function_call item
        tool_result block       -> function_call_output item
        tool definitions        -> {"type": "function", ...}

    Groq's Responses API does not support previous_response_id, so the
    full conversation (including tool calls and results) is re-sent on
    every request. The agent loop already keeps that history.

Setup (backend/.env, or export them in your shell):
    GROQ_API_KEY=gsk_...
    LLM_PROVIDER=groq                 # optional; auto-picked when the key is set

Optional settings:
    GROQ_MODEL             default openai/gpt-oss-20b (try openai/gpt-oss-120b)
    GROQ_REASONING_EFFORT  low | medium | high (default low, fastest)

Quick check:
    python groq_llm.py
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace as NS
from typing import Any

import env  # noqa: F401  loads backend/.env before GROQ_* settings are read

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")


def groq_available() -> bool:
    """True when the openai package is installed and GROQ_API_KEY is set."""
    if not os.environ.get("GROQ_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


# ============================================================
# TRANSLATION: pipeline format -> Groq Responses API
# ============================================================
def _get(block: Any, key: str, default: Any = None) -> Any:
    """Blocks may be dicts (built by us) or objects (returned earlier)."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def to_groq_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-style tool definitions -> OpenAI function tools."""
    converted = []
    for tool in tools:
        schema = dict(tool.get("input_schema") or {"type": "object", "properties": {}})
        schema.setdefault("properties", {})
        converted.append({
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        })
    return converted


def to_groq_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-style message history -> Responses API input items."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        content = message["content"]

        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        for block in content:
            kind = _get(block, "type")
            if kind == "text":
                text_parts.append(_get(block, "text", ""))
            elif kind == "tool_use":
                # Flush any text Claude-style blocks said before the call.
                if text_parts:
                    items.append({"role": "assistant", "content": "\n".join(text_parts)})
                    text_parts = []
                items.append({
                    "type": "function_call",
                    "call_id": _get(block, "id"),
                    "name": _get(block, "name"),
                    "arguments": json.dumps(_get(block, "input") or {}),
                })
            elif kind == "tool_result":
                output = _get(block, "content", "")
                if not isinstance(output, str):
                    output = json.dumps(output)
                items.append({
                    "type": "function_call_output",
                    "call_id": _get(block, "tool_use_id"),
                    "output": output,
                })
        if text_parts:
            items.append({"role": role, "content": "\n".join(text_parts)})
    return items


# ============================================================
# TRANSLATION: Groq Responses API -> pipeline format
# ============================================================
def from_groq_output(response: Any) -> NS:
    """Responses API output -> object with .stop_reason and .content blocks."""
    blocks: list[NS] = []
    for item in getattr(response, "output", None) or []:
        kind = getattr(item, "type", None)
        if kind == "function_call":
            raw = getattr(item, "arguments", None) or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = {}
            blocks.append(NS(
                type="tool_use",
                id=getattr(item, "call_id", None) or getattr(item, "id", None),
                name=item.name,
                input=arguments if isinstance(arguments, dict) else {},
            ))
        elif kind == "message":
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "output_text" and part.text:
                    blocks.append(NS(type="text", text=part.text))
        # "reasoning" items are the model's private chain of thought: skipped.

    if not any(b.type == "text" for b in blocks):
        fallback = getattr(response, "output_text", "") or ""
        if fallback and not any(b.type == "tool_use" for b in blocks):
            blocks.append(NS(type="text", text=fallback))

    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return NS(stop_reason=stop, content=blocks, usage=getattr(response, "usage", None))


# ============================================================
# CLIENT
# ============================================================
class _Messages:
    def __init__(self, client: Any, model: str, reasoning_effort: str | None):
        self._client = client
        self._model = model
        self._effort = reasoning_effort

    def create(
        self,
        *,
        model: str | None = None,       # ignored: the Groq model is configured here
        max_tokens: int = 1024,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]],
    ) -> NS:
        request: dict[str, Any] = {
            "model": self._model,
            "instructions": system,
            "input": to_groq_input(messages),
            # gpt-oss spends tokens on reasoning first, so leave headroom.
            "max_output_tokens": max(max_tokens, 2048),
        }
        if tools:
            request["tools"] = to_groq_tools(tools)
            request["tool_choice"] = "auto"
        if self._effort:
            request["reasoning"] = {"effort": self._effort}
        response = self._client.responses.create(**request)
        return from_groq_output(response)


class GroqLLMClient:
    """
    Drop-in replacement for Anthropic() in the support pipeline:

        claude_client = GroqLLMClient()
        claude_client.messages.create(model=..., max_tokens=..., system=..., tools=..., messages=...)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = GROQ_MODEL,
        reasoning_effort: str | None = GROQ_REASONING_EFFORT,
        max_retries: int = 3,     # free tier is rate limited; retries back off on 429
    ) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            base_url=GROQ_BASE_URL,
            max_retries=max_retries,
        )
        self.messages = _Messages(self._client, model, reasoning_effort)


# ============================================================
# QUICK CHECK: plain answer, then one tool round trip
# ============================================================
if __name__ == "__main__":
    if not groq_available():
        raise SystemExit("Set GROQ_API_KEY in backend/.env and run `pip install -r requirements.txt` first.")

    client = GroqLLMClient()
    print(f"Model: {client.model}\n")

    plain = client.messages.create(
        max_tokens=256,
        system="Answer in one sentence.",
        messages=[{"role": "user", "content": "Explain the importance of fast language models"}],
    )
    print("Plain answer:", plain.content[0].text if plain.content else "(empty)")

    tools = [{
        "name": "get_order_status",
        "description": "Get the status of one of the customer's orders.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    }]
    history: list[dict[str, Any]] = [{"role": "user", "content": "Where is my order A-104?"}]
    first = client.messages.create(
        max_tokens=512, system="You are an order support agent. Use tools for order data.",
        tools=tools, messages=history,
    )
    print("\nStop reason:", first.stop_reason)
    calls = [b for b in first.content if b.type == "tool_use"]
    if calls:
        print("Tool requested:", calls[0].name, calls[0].input)
        history.append({"role": "assistant", "content": first.content})
        history.append({"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": calls[0].id,
            "content": json.dumps({"found": True, "order": {
                "id": "A-104", "status": "shipped", "carrier": "UPS",
                "tracking_number": "1Z999AA", "estimated_delivery": "2026-09-27"}}),
        }]})
        final = client.messages.create(
            max_tokens=512, system="You are an order support agent. Use tools for order data.",
            tools=tools, messages=history,
        )
        print("Final reply:", " ".join(b.text for b in final.content if b.type == "text"))
