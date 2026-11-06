"""Thin, swappable LLM layer.

Every call goes through `LLMClient.json_call`:
  model name from config (any LiteLLM string) -> cache -> rate limit -> retry
  -> parse JSON into a Pydantic schema -> one self-correction retry on bad JSON
  -> raw request/response logged to disk with token usage.
Swapping provider or model is a config change, never a code change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# A fake backend lets tests and --dry-run work without any API key.
FakeBackend = Callable[[str, list[dict]], str]


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may be wrapped in ``` fences or prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return text[start:end + 1]


class LLMClient:
    def __init__(self, cfg: dict, log_dir: Path | None = None,
                 fake: FakeBackend | None = None) -> None:
        self.cfg = cfg
        self.models = cfg["models"]
        self.llm_cfg = cfg["llm"]
        self.fake = fake
        self.log_dir = log_dir
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
        self._cache = None
        if self.llm_cfg.get("cache_dir") and fake is None:
            import diskcache
            self._cache = diskcache.Cache(self.llm_cfg["cache_dir"])
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.usage = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "errors": 0}

    # ---------- public ----------
    def model_for(self, role: str) -> str:
        env = os.getenv(f"PROMO_MODEL_{role.upper()}") or os.getenv("PROMO_MODEL")
        return env or self.models[role]

    def json_call(self, role: str, system: str, user: str, schema: type[T],
                  temperature: float | None = None, tag: str = "") -> T:
        """Call the model for `role`, return a validated `schema` instance."""
        model = self.model_for(role)
        if temperature is None:
            temperature = self.llm_cfg.get(f"temperature_{role}", 0.2)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_err = ""
        for attempt in range(2):          # 1 normal try + 1 self-correction try
            if attempt == 1:
                messages = messages + [{"role": "user", "content":
                    f"Your previous reply was not valid. Error: {last_err}\n"
                    "Reply again with ONLY the JSON object matching the schema."}]
            raw = self._complete(model, messages, temperature, tag=f"{tag}#try{attempt}")
            try:
                return schema.model_validate_json(extract_json(raw))
            except (ValueError, ValidationError) as e:
                last_err = str(e)[:800]
                self.usage["errors"] += 1
        raise LLMError(f"{role}: invalid JSON after retry: {last_err}")

    def preflight(self, role: str) -> str:
        """Tiny uncached call so a wrong model/key fails fast. Returns the model that answered."""
        if self.fake is not None:
            return self.model_for(role)
        _, _, used = self._call_with_fallback(
            self.model_for(role), [{"role": "user", "content": "Reply with: ok"}], 0.0,
            "preflight", timeout=self.llm_cfg.get("preflight_timeout_s", 30), retries=0)
        self.models[role] = used          # stick with the model that works for this run
        return used

    def chain(self, model: str) -> list[str]:
        rest = [m for m in (self.models.get("fallbacks") or []) if m != model]
        return [model] + rest

    def _call_with_fallback(self, model: str, messages: list[dict], temperature: float,
                            tag: str, timeout: float | None = None, retries: int | None = None
                            ) -> tuple[str, dict, str]:
        errors = []
        for m in self.chain(model):
            t0 = time.monotonic()
            print(f"  [llm] {tag} -> {m} ...", flush=True)
            try:
                text, usage = self._call_provider(m, messages, temperature, timeout, retries)
            except LLMError as e:
                print(f"  [llm] {m} failed: {str(e)[:160]}", flush=True)
                errors.append(str(e)[:200])   # down, overloaded or not allowed: try the next model
            print(f"  [llm] {tag} done by {m} in {time.monotonic() - t0:.0f} s "
                  f"({usage.get('prompt_tokens', 0)} in / "
                  f"{usage.get('completion_tokens', 0)} out tokens)", flush=True)
            return text, usage, m
        raise LLMError("all models failed: " + " || ".join(errors))

    # ---------- internals ----------
    def _key(self, model: str, messages: list[dict], temperature: float) -> str:
        blob = json.dumps([model, messages, temperature], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _throttle(self) -> None:
        rpm = self.llm_cfg.get("requests_per_minute") or 0
        if rpm <= 0:
            return
        with self._lock:
            wait = self._last_call + 60.0 / rpm - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _complete(self, model: str, messages: list[dict], temperature: float, tag: str) -> str:
        key = self._key(model, messages, temperature)
        if self._cache is not None and key in self._cache:
            self.usage["cached"] += 1
            return self._cache[key]
        if self.fake is not None:
            text, usage = self.fake(model, messages), {}
        else:
            text, usage, used = self._call_with_fallback(model, messages, temperature, tag)
            usage = {**usage, "model_used": used}
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        if self._cache is not None:
            self._cache[key] = text
        self._log(tag, model, messages, text, usage)
        return text

    def _call_provider(self, model: str, messages: list[dict], temperature: float,
                       timeout: float | None = None, retries: int | None = None
                       ) -> tuple[str, dict]:
        import litellm
        from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

        litellm.suppress_debug_info = True
        api_base = os.getenv("PROMO_API_BASE") or self.models.get("api_base")
        api_key = os.getenv("PROMO_API_KEY")   # only for a custom OpenAI-compatible endpoint

        def transient(e: BaseException) -> bool:
            name = type(e).__name__
            return any(s in name for s in ("RateLimit", "Timeout", "ServiceUnavailable",
                                           "InternalServer", "APIConnection"))

        def say_retry(state) -> None:
            err = state.outcome.exception() if state.outcome else None
            wait = state.next_action.sleep if state.next_action else 0
            print(f"  [llm] {type(err).__name__} from {model}; retry "
                  f"{state.attempt_number} in {wait:.0f} s", flush=True)

        @retry(retry=retry_if_exception(transient),
               wait=wait_exponential(multiplier=4, min=8, max=90),
               stop=stop_after_attempt(
                   (self.llm_cfg.get("max_retries", 3) if retries is None else retries) + 1),
               before_sleep=say_retry, reraise=True)
        def _do():
            self._throttle()
            kwargs = {"model": model, "messages": messages,
                      "timeout": timeout or self.llm_cfg.get("timeout_s", 120)}
            if not re.search(r"gemini-(3|flash-latest|flash-lite-latest)", model):
                kwargs["temperature"] = temperature   # Gemini 3+ deprecates sampling params
            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key
            return litellm.completion(**kwargs)

        try:
            resp = _do()
        except Exception as e:  # noqa: BLE001 - turn provider errors into one clear type
            msg = str(e).replace("\n", " ")
            raise LLMError(f"{type(e).__name__} from {model}: {msg[:400]}") from None
        text = resp.choices[0].message.content or ""
        u = getattr(resp, "usage", None)
        usage = {"prompt_tokens": getattr(u, "prompt_tokens", 0),
                 "completion_tokens": getattr(u, "completion_tokens", 0)} if u else {}
        return text, usage

    def _log(self, tag: str, model: str, messages: list[dict], text: str, usage: dict) -> None:
        if not self.log_dir:
            return
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "model": model,
               "usage": usage, "messages": messages, "response": text}
        with open(self.log_dir / "calls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
