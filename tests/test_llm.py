"""Model router: strong -> cheap fallback on a persistent 429 quota error, thinking config, ledger."""
import json

import pytest
from pydantic import BaseModel

import core.llm as llm

QUOTA_ZERO = ("You exceeded your current quota, please check your plan and billing details.\n* Quota exceeded for "
              "metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, "
              "model: gemini-3.1-pro")
QUOTA_RPM = ("You exceeded your current quota.\n* Quota exceeded for metric: generate_content_free_tier_requests, "
             "limit: 5, description: Generate content requests per minute limit exceeded on Free Tier.")


class Out(BaseModel):
    ok: bool


class Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok_resp():
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                      "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10}})


def err_resp(status, msg):
    return Resp(status, {"error": {"code": status, "message": msg}})


@pytest.fixture
def router(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    r = llm.Router()
    r.cfg = {**r.cfg, "min_interval_s": 0,
             "cheap": {"provider": "gemini", "name": "flash-x", "thinking_budget": 0},
             "strong": {"provider": "gemini", "name": "pro-x"}}
    return r


def install(monkeypatch, handler):
    calls = []

    def fake_post(url, *, headers, params, json, timeout):
        model = url.split("/models/")[1].split(":")[0]
        calls.append((model, json))
        return handler(model, len(calls))

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return calls


def test_strong_falls_back_to_cheap_on_quota_429(monkeypatch, router):
    calls = install(monkeypatch, lambda m, n: err_resp(429, QUOTA_ZERO) if m == "pro-x" else ok_resp())
    assert router.json(task="bull_bear", tier="strong", prompt="p", schema=Out).ok
    assert [m for m, _ in calls] == ["pro-x", "flash-x"]  # "limit: 0" is persistent: no backoff retries
    assert "thinkingConfig" not in calls[0][1]["generationConfig"]  # strong uses the model's default thinking
    assert calls[1][1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}  # cheap's own setting
    rec = router.ledger.calls[-1]
    assert (rec.model, rec.tier) == ("flash-x", "cheap")
    # the fallback sticks for the rest of the run
    router.json(task="bull_bear", tier="strong", prompt="q", schema=Out)
    assert [m for m, _ in calls][-1] == "flash-x" and len(calls) == 3


def test_transient_rate_limit_is_retried_not_fallen_back(monkeypatch, router):
    calls = install(monkeypatch, lambda m, n: err_resp(429, QUOTA_RPM) if n == 1 else ok_resp())
    router.json(task="bull_bear", tier="strong", prompt="p", schema=Out)
    assert [m for m, _ in calls] == ["pro-x", "pro-x"]
    assert router.ledger.calls[-1].model == "pro-x" and not router._fallback_strong


def test_rate_limit_that_never_clears_falls_back(monkeypatch, router):
    calls = install(monkeypatch, lambda m, n: err_resp(429, QUOTA_RPM) if m == "pro-x" else ok_resp())
    router.json(task="bull_bear", tier="strong", prompt="p", schema=Out)
    assert [m for m, _ in calls] == ["pro-x"] * 4 + ["flash-x"]
    assert router.ledger.calls[-1].model == "flash-x"


def test_cheap_quota_error_raises(monkeypatch, router):
    install(monkeypatch, lambda m, n: err_resp(429, QUOTA_ZERO))
    with pytest.raises(RuntimeError, match="429"):
        router.json(task="x", tier="cheap", prompt="p", schema=Out)


def test_validation_retry_is_cached(monkeypatch, router):
    answers = iter(['{"ok": "not-a-bool"}', '{"ok": true}'])

    def handler(m, n):
        r = ok_resp()
        r._payload["candidates"][0]["content"]["parts"][0]["text"] = next(answers)
        return r

    calls = install(monkeypatch, handler)
    assert router.json(task="x", tier="cheap", prompt="p", schema=Out).ok
    assert len(calls) == 2
    assert router.json(task="x", tier="cheap", prompt="p", schema=Out).ok  # re-run: both answers from cache
    assert len(calls) == 2


def test_bare_400_on_thinking_budget_retries_without_it(monkeypatch, router):
    # gemini-3.5-flash-lite answers thinkingBudget 0 with a bare "Request contains an invalid argument."
    def handler(m, n):
        body = calls[-1][1]
        if "thinkingConfig" in body["generationConfig"]:
            return err_resp(400, "Request contains an invalid argument.")
        return ok_resp()

    calls = install(monkeypatch, handler)
    assert router.json(task="x", tier="cheap", prompt="p", schema=Out).ok
    assert len(calls) == 2 and "thinkingConfig" not in calls[1][1]["generationConfig"]
    router.json(task="y", tier="cheap", prompt="q", schema=Out)  # remembered: no failing first attempt
    assert len(calls) == 3


def test_other_400_without_thinking_config_raises(monkeypatch, router):
    calls = install(monkeypatch, lambda m, n: err_resp(400, "Request contains an invalid argument."))
    with pytest.raises(RuntimeError, match="400"):
        router.json(task="x", tier="strong", prompt="p", schema=Out)  # strong sends no thinkingConfig
    assert len(calls) == 1


def test_thinking_gets_output_headroom_and_thought_parts_are_dropped(monkeypatch, router):
    def handler(m, n):
        return Resp(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "Let's pick quotes without linebreaks...", "thought": True}, {"text": '{"ok": true}'}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 900}})

    calls = install(monkeypatch, handler)
    assert router.json(task="bull_bear", tier="strong", prompt="p", schema=Out, max_tokens=2000).ok
    assert calls[0][1]["generationConfig"]["maxOutputTokens"] == 2000 + 8192   # strong thinks by default
    assert router.ledger.calls[-1].output_tokens == 910                        # thinking is billed
    router.json(task="x", tier="cheap", prompt="p", schema=Out, max_tokens=2000)
    assert calls[1][1]["generationConfig"]["maxOutputTokens"] == 2000          # thinkingBudget 0: no headroom


def test_truncated_output_raises_and_is_not_cached(monkeypatch, router):
    truncated = Resp(200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [
        {"text": '{"bull": [{"text": "Dixon has'}]}}], "usageMetadata": {}})
    calls = install(monkeypatch, lambda m, n: truncated if n == 1 else ok_resp())
    with pytest.raises(RuntimeError, match="truncated"):
        router.json(task="bull_bear", tier="strong", prompt="p", schema=Out)
    assert router.json(task="bull_bear", tier="strong", prompt="p", schema=Out).ok  # not served from cache
    assert len(calls) == 2


def test_no_fallback_when_caller_forbids_it(monkeypatch, router):
    calls = install(monkeypatch, lambda m, n: err_resp(429, QUOTA_ZERO) if m == "pro-x" else ok_resp())
    with pytest.raises(llm.StrongUnavailable):
        router.json(task="promise_followup", tier="strong", prompt="p", schema=Out, allow_fallback=False)
    assert [m for m, _ in calls] == ["pro-x"]                       # never asked the cheap model
    with pytest.raises(llm.StrongUnavailable):                       # and doesn't retry the strong one
        router.json(task="promise_followup", tier="strong", prompt="q", schema=Out, allow_fallback=False)
    assert len(calls) == 1
    assert router.json(task="bull_bear", tier="strong", prompt="r", schema=Out).ok   # fallback still allowed here
    assert calls[-1][0] == "flash-x"


def test_bare_list_is_wrapped_for_single_list_schema(monkeypatch, router):
    from pydantic import BaseModel

    class Items(BaseModel):
        items: list[int]

    def handler(m, n):
        r = ok_resp()
        r._payload["candidates"][0]["content"]["parts"][0]["text"] = "[1, 2]"
        return r

    install(monkeypatch, handler)
    assert router.json(task="x", tier="cheap", prompt="p", schema=Items).items == [1, 2]
