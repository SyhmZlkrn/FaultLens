"""Thin client for the AMD Token Factory (OpenAI-compatible chat completions)."""
from __future__ import annotations

import json
import re
import time

from openai import OpenAI

from app import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not (config.AMD_BASE_URL and config.AMD_API_KEY and config.AMD_MODEL):
            raise RuntimeError("Set AMD_BASE_URL, AMD_API_KEY and AMD_MODEL in .env")
        _client = OpenAI(base_url=config.AMD_BASE_URL, api_key=config.AMD_API_KEY)
    return _client


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles ```json fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in model reply")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str, temperature: float = 0.2, max_tokens: int = 1500) -> tuple[dict, dict]:
    """Call the model and return (parsed_json, meta). Retries once if the JSON is broken."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    meta = {"model": config.AMD_MODEL, "calls": 0, "latency_s": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0}
    for attempt in range(2):
        t0 = time.perf_counter()
        resp = client().chat.completions.create(
            model=config.AMD_MODEL, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        meta["calls"] += 1
        meta["latency_s"] += time.perf_counter() - t0
        if resp.usage:
            meta["prompt_tokens"] += resp.usage.prompt_tokens or 0
            meta["completion_tokens"] += resp.usage.completion_tokens or 0
        text = resp.choices[0].message.content or ""
        try:
            return extract_json(text), meta
        except (ValueError, json.JSONDecodeError) as err:
            if attempt == 1:
                raise RuntimeError(f"Model did not return valid JSON: {err}") from err
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "That was not valid JSON. Reply again with only the JSON object."}]
    raise RuntimeError("unreachable")
