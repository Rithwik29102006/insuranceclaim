"""Nebius Token Factory client for ClaimCheck 2.0.

Token Factory exposes an OpenAI-compatible API, so we use the openai package
with Nebius's base URL. All NVIDIA Nemotron calls go through this module.
"""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class NebiusConfigError(Exception):
    """Raised when the API key or model ID is missing from the environment."""


class NebiusResponseError(Exception):
    """Raised when the model's reply cannot be parsed as JSON."""


def get_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    load_dotenv()
    key = api_key or os.getenv("NEBIUS_API_KEY")
    if not key:
        raise NebiusConfigError("NEBIUS_API_KEY is not set. Add it to your .env file.")
    return OpenAI(api_key=key, base_url=base_url or os.getenv("NEBIUS_BASE_URL") or DEFAULT_BASE_URL)


def get_model(kind: str = "reasoning") -> str:
    load_dotenv()
    var = "NEBIUS_MODEL_REASONING" if kind == "reasoning" else "NEBIUS_MODEL_FAST"
    model = os.getenv(var)
    if not model:
        raise NebiusConfigError(f"{var} is not set. Copy a Nemotron model ID from Token Factory into .env.")
    return model


def parse_json_response(content: str | None) -> dict:
    """Pull the JSON object out of a reply, ignoring <think> blocks and ``` fences."""
    if not content:
        raise NebiusResponseError("Model returned an empty response.")
    text = _THINK_BLOCK.sub("", content)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise NebiusResponseError(f"No JSON object found in model response: {text[:200]!r}")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise NebiusResponseError(f"Model returned invalid JSON: {exc}") from exc


def chat_json(client, model: str, system: str, user: str,
              temperature: float = 0.2, max_tokens: int = 4096) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_response(response.choices[0].message.content)