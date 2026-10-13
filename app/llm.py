"""Thin client for the AMD Token Factory (OpenAI-compatible chat completions)."""
from __future__ import annotations

import json
import re
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from app import config

_client: OpenAI | None = None

# Errors that mean "this model is busy or down right now", so the next Token Factory model is tried.
BUSY_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


def client() -> OpenAI:
    global _client
    if _client is None:
        if not (config.AMD_BASE_URL and config.AMD_API_KEY and config.AMD_MODEL):
            raise RuntimeError("Set AMD_BASE_URL, AMD_API_KEY and AMD_MODEL in .env")
        # No hidden retries: a busy model should fail fast and fall through to the next one.
        _client = OpenAI(base_url=config.AMD_BASE_URL, api_key=config.AMD_API_KEY,
                         timeout=config.LLM_TIMEOUT_S, max_retries=0)
    return _client


def models() -> list[str]:
    """Main model first, then fallbacks. All are served by the AMD Token Factory."""
    return list(dict.fromkeys([config.AMD_MODEL, *config.AMD_FALLBACK_MODELS]))


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles ```json fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^.*?</think>", "", text, flags=re.S)  # some servers drop the opening tag
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object in model reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])  # ignores any text after the object
    if not isinstance(obj, dict):
        raise ValueError("Model reply was not a JSON object")
    return obj


def complete(messages: list[dict], meta: dict, temperature: float, max_tokens: int) -> str:
    """One chat call, moving down the model list while models are busy. Updates meta in place."""
    errors = []
    for model in models():
        t0 = time.perf_counter()
        try:
            resp = client().chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        except BUSY_ERRORS as err:
            errors.append(f"{model}: {type(err).__name__}")
            continue
        finally:
            meta["latency_s"] += time.perf_counter() - t0
        meta["calls"] += 1
        meta["model"] = model
        if resp.usage:
            meta["prompt_tokens"] += resp.usage.prompt_tokens or 0
            meta["completion_tokens"] += resp.usage.completion_tokens or 0
        return resp.choices[0].message.content or ""
    raise RuntimeError("All AMD Token Factory models are busy right now (" + "; ".join(errors)
                       + "). Wait a minute and try again.")


# Reasoning models spend tokens in <think> before the JSON, so leave plenty of room.
def chat_json(system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096) -> tuple[dict, dict]:
    """Call the model and return (parsed_json, meta). Retries once if the JSON is broken."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    meta = {"model": config.AMD_MODEL, "calls": 0, "latency_s": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0}
    for attempt in range(2):
        text = complete(messages, meta, temperature, max_tokens)
        try:
            return extract_json(text), meta
        except (ValueError, json.JSONDecodeError) as err:
            if attempt == 1:
                raise RuntimeError(f"Model did not return valid JSON: {err}") from err
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "That was not valid JSON. Reply again with only the JSON object."}]
    raise RuntimeError("unreachable")
