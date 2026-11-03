"""Model router.

- Two tiers: "cheap" (bulk extraction/classification) and "strong" (synthesis/judgement).
- Every call is cached on disk by a hash of (model, prompt, attached document bytes), so a
  document is processed once, ever. Cached calls cost nothing and are logged as cached.
- Every call is written to a cost ledger (task, model, tokens, estimated paid-tier cost).
- Output is JSON validated against a Pydantic model; one retry with the validation error.
- If no API key is configured, `available()` is False and callers fall back to rules-only mode.

Providers are called over plain REST so there is no SDK version to fight with.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .config import CACHE_DIR, load_config

log = logging.getLogger("finn.llm")
T = TypeVar("T", bound=BaseModel)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMUnavailable(RuntimeError):
    pass


class StrongUnavailable(LLMUnavailable):
    """The strong model is out of quota (or missing) and the caller didn't allow a cheap-model fallback."""


@dataclass
class CallRecord:
    task: str
    tier: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool
    est_usd: float
    ms: int


@dataclass
class Ledger:
    calls: list[CallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, rec: CallRecord) -> None:
        with self._lock:
            self.calls.append(rec)

    def summary(self) -> dict:
        live = [c for c in self.calls if not c.cached]
        by_tier: dict[str, int] = {}
        for c in live:
            by_tier[c.tier] = by_tier.get(c.tier, 0) + 1
        return {
            "model_calls": len(live),
            "cached_calls": len(self.calls) - len(live),
            "by_tier": by_tier,
            "input_tokens": sum(c.input_tokens for c in live),
            "output_tokens": sum(c.output_tokens for c in live),
            "est_usd_if_paid": round(sum(c.est_usd for c in live), 4),
            "by_task": _group_by_task(self.calls),
        }


def _group_by_task(calls: list[CallRecord]) -> dict:
    out: dict[str, dict] = {}
    for c in calls:
        t = out.setdefault(c.task, {"calls": 0, "cached": 0, "tokens": 0, "model": c.model})
        if c.cached:
            t["cached"] += 1
        else:
            t["calls"] += 1
            t["tokens"] += c.input_tokens + c.output_tokens
    return out


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class Router:
    def __init__(self, ledger: Ledger | None = None):
        cfg = load_config()["models"]
        self.cfg = cfg
        self.ledger = ledger or Ledger()
        self.cache_dir = CACHE_DIR / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_call = 0.0
        self._lock = threading.Lock()
        self._fallback_strong = False
        self._no_thinking: set[str] = set()

    # ---------- availability ----------
    def _key_for(self, provider: str) -> str | None:
        return os.environ.get("GEMINI_API_KEY") if provider == "gemini" else os.environ.get("ANTHROPIC_API_KEY")

    def available(self, tier: str = "cheap") -> bool:
        return bool(self._key_for(self.cfg[tier]["provider"]))

    # ---------- public API ----------
    def json(self, *, task: str, tier: str, prompt: str, schema: Type[T],
             pdf: bytes | None = None, system: str | None = None, max_tokens: int = 4096,
             allow_fallback: bool = True) -> T:
        """Call a model and return a validated Pydantic object."""
        if not self.available(tier):
            if tier == "strong" and self.available("cheap"):
                tier = "cheap"
            else:
                raise LLMUnavailable(f"No API key for tier '{tier}'")
        full_prompt = prompt + "\n\nReturn ONLY valid JSON matching this JSON schema:\n" + json.dumps(
            schema.model_json_schema(), separators=(",", ":"))
        retries = int(self.cfg.get("max_retries", 1))
        last_err = ""
        for attempt in range(retries + 1):
            p = full_prompt if not last_err else (
                full_prompt + f"\n\nYour previous answer failed validation: {last_err[:800]}\nFix it.")
            text = self._call(task=task, tier=tier, prompt=p, pdf=pdf, system=system,
                              max_tokens=max_tokens, allow_fallback=allow_fallback)  # retry prompts embed the error, so they cache separately
            try:
                raw = _strip_fences(text)
                fields = list(schema.model_fields)
                if raw.startswith("[") and len(fields) == 1:  # {"claims": [...]} answered as a bare [...]
                    raw = json.dumps({fields[0]: json.loads(raw)})
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                last_err = str(e)
                log.warning("[%s] schema validation failed (attempt %d): %s", task, attempt + 1, last_err[:200])
        raise ValueError(f"[{task}] model output failed validation: {last_err[:300]}")

    # ---------- internals ----------
    def _effective_tier(self, tier: str) -> str:
        """The tier whose model actually answers (strong falls back to cheap once it's unavailable)."""
        return "cheap" if tier == "strong" and self._fallback_strong else tier

    def _model(self, tier: str) -> tuple[str, str]:
        t = self.cfg[self._effective_tier(tier)]
        return t["provider"], t["name"]

    def _cache_key(self, model: str, prompt: str, pdf: bytes | None, system: str | None) -> str:
        h = hashlib.sha256()
        h.update(model.encode())
        h.update((system or "").encode())
        h.update(prompt.encode())
        if pdf:
            h.update(hashlib.sha256(pdf).digest())
        return h.hexdigest()

    def _price(self, tier: str, tin: int, tout: int) -> float:
        p = self.cfg.get("price_per_mtok", {}).get(tier, {"input": 0, "output": 0})
        return tin / 1e6 * p["input"] + tout / 1e6 * p["output"]

    def _call(self, *, task, tier, prompt, pdf, system, max_tokens, use_cache=True, allow_fallback=True) -> str:
        if tier == "strong" and self._fallback_strong and not allow_fallback:
            strong = self.cfg["strong"]["name"]  # an answer the strong model gave earlier is still valid
            cpath = self.cache_dir / f"{self._cache_key(strong, prompt, pdf, system)}.json"
            if use_cache and cpath.exists():
                self.ledger.add(CallRecord(task, "strong", strong, 0, 0, True, 0.0, 0))
                return json.loads(cpath.read_text(encoding="utf-8"))["text"]
            raise StrongUnavailable(f"[{task}] strong model unavailable (quota/limit); not using the cheap model")
        provider, model = self._model(tier)
        eff = self._effective_tier(tier)
        key = self._cache_key(model, prompt, pdf, system)
        cpath = self.cache_dir / f"{key}.json"
        if use_cache and cpath.exists():
            data = json.loads(cpath.read_text(encoding="utf-8"))
            self.ledger.add(CallRecord(task, eff, model, 0, 0, True, 0.0, 0))
            return data["text"]

        with self._lock:  # space calls to respect free-tier rate limits
            wait = float(self.cfg.get("min_interval_s", 0)) - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

        t0 = time.time()
        try:
            text, tin, tout = (self._gemini if provider == "gemini" else self._anthropic)(
                model, prompt, pdf, system, max_tokens, eff)
        except (_ModelNotFound, _QuotaExhausted) as e:
            if tier == "strong" and not self._fallback_strong:
                why = "quota exhausted (429)" if isinstance(e, _QuotaExhausted) else "not available (404)"
                log.warning("Strong model '%s' %s; falling back to cheap model '%s' for the rest of the run.",
                            model, why, self.cfg["cheap"]["name"])
                self._fallback_strong = True
                return self._call(task=task, tier=tier, prompt=prompt, pdf=pdf, system=system,
                                  max_tokens=max_tokens, use_cache=use_cache, allow_fallback=allow_fallback)
            raise
        ms = int((time.time() - t0) * 1000)
        self.ledger.add(CallRecord(task, eff, model, tin, tout, False, self._price(eff, tin, tout), ms))
        cpath.write_text(json.dumps({"model": model, "task": task, "text": text}), encoding="utf-8")
        return text

    def _post(self, url, *, headers, body, params=None) -> dict:
        timeout = float(self.cfg.get("timeout_s", 90))
        for attempt in range(4):
            try:
                r = requests.post(url, headers=headers, params=params, json=body, timeout=timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < 3:
                    delay = 8 * (attempt + 1)
                    log.warning("Model API %s; retrying in %ss", type(e).__name__, delay)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Model API unreachable after retries: {type(e).__name__}") from e
            if r.status_code == 404:
                raise _ModelNotFound(r.text[:300])
            if r.status_code == 429 and "quota" in r.text.lower() and (_persistent_quota(r.text) or attempt >= 3):
                raise _QuotaExhausted(f"Model API error 429 (quota): {r.text[:300]}")
            if r.status_code in (429, 500, 503) and attempt < 3:
                delay = 8 * (attempt + 1)
                log.warning("Model API %s; retrying in %ss", r.status_code, delay)
                time.sleep(delay)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Model API error {r.status_code}: {r.text[:500]}")
            return r.json()
        raise RuntimeError("Model API: too many retries")

    def _gemini(self, model, prompt, pdf, system, max_tokens, tier="cheap"):
        parts: list[dict[str, Any]] = []
        if pdf:
            parts.append({"inline_data": {"mime_type": "application/pdf",
                                          "data": base64.b64encode(pdf).decode()}})
        parts.append({"text": prompt})
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        budget = self.cfg[tier].get("thinking_budget", 0 if tier == "cheap" else None)
        if budget is not None and model not in self._no_thinking:
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": int(budget)}
        self._set_output_budget(body["generationConfig"], max_tokens)
        url, params = GEMINI_URL.format(model=model), {"key": os.environ["GEMINI_API_KEY"]}
        try:
            data = self._post(url, headers={"Content-Type": "application/json"}, params=params, body=body)
        except RuntimeError as e:
            # Some models reject a thinking budget with a message that names it, others (gemini-3.5-flash-lite)
            # with a bare 400 "Request contains an invalid argument". Either way, retry once without it.
            msg = str(e)
            if "thinkingConfig" not in body["generationConfig"] or not (
                    "thinking" in msg.lower() or msg.startswith("Model API error 400")):
                raise
            log.info("Model %s doesn't accept a thinking budget; retrying without it.", model)
            self._no_thinking.add(model)
            body["generationConfig"].pop("thinkingConfig")
            self._set_output_budget(body["generationConfig"], max_tokens)
            data = self._post(url, headers={"Content-Type": "application/json"}, params=params, body=body)
        cands = data.get("candidates") or []
        if not cands:
            raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:300]}")
        if cands[0].get("finishReason") == "MAX_TOKENS":
            # Raised, not returned, so the cut-off text is never cached (the cache key ignores max_tokens).
            raise RuntimeError(f"Model output truncated (MAX_TOKENS, limit {body['generationConfig']['maxOutputTokens']})")
        # Thinking models may return their reasoning as parts flagged "thought"; the answer is the rest.
        text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []) if not p.get("thought"))
        usage = data.get("usageMetadata", {})
        out_tokens = int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0))  # both billed
        return text, int(usage.get("promptTokenCount", 0)), out_tokens

    def _set_output_budget(self, gc: dict, max_tokens: int) -> None:
        """Gemini counts thinking tokens against maxOutputTokens. Unless thinking is switched off
        (thinkingBudget 0), add headroom so the reasoning can't crowd out the JSON answer."""
        thinking_off = gc.get("thinkingConfig", {}).get("thinkingBudget") == 0
        gc["maxOutputTokens"] = max_tokens + (0 if thinking_off else int(self.cfg.get("thinking_headroom_tokens", 8192)))

    def _anthropic(self, model, prompt, pdf, system, max_tokens, tier="cheap"):
        content: list[dict[str, Any]] = []
        if pdf:
            content.append({"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf).decode()}})
        content.append({"type": "text", "text": prompt})
        body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                                "messages": [{"role": "user", "content": content}]}
        if system:
            body["system"] = system
        data = self._post(ANTHROPIC_URL, headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
            "content-type": "application/json"}, body=body)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


class _ModelNotFound(RuntimeError):
    pass


class _QuotaExhausted(RuntimeError):
    """429 quota error that won't clear by waiting a few seconds."""


def _persistent_quota(text: str) -> bool:
    """Gemini also says "quota" for per-minute rate limits, which clear quickly. A zero limit or a
    per-day limit won't, so there's no point backing off; anything else is persistent only once
    the normal backoff retries are used up."""
    t = text.lower()
    return "limit: 0" in t or "per day" in t or "perday" in t


def list_gemini_models() -> list[str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("Set GEMINI_API_KEY in .env first.")
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key, "pageSize": 200},
                     timeout=30)
    r.raise_for_status()
    return [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


if __name__ == "__main__":  # python -m core.llm --list
    if "--list" in sys.argv:
        for name in list_gemini_models():
            print(name)
    else:
        print("Usage: python -m core.llm --list")
