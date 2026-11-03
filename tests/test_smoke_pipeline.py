"""Runs the whole push pipeline offline: fake exchange feed, fake prices, fake model."""
import json
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pipeline.run_brief as rb

FX = Path(__file__).parent / "fixtures"
IST = timezone(timedelta(hours=5, minutes=30))


def _filings():
    now = datetime.now(IST)
    f = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    rows = [
        ("TITAN", "Outcome of Board Meeting", "Financial Results for the quarter ended September 30, 2026", 3),
        ("TITAN", "Investor Presentation", "Investor presentation on financial results", 2),
        ("POLYCAB", "Change in Directorate", "Resignation of Mr. X as Chief Financial Officer and appointment of Ms. Y as CFO", 5),
        ("DIXON", "Credit Rating", "ICRA has upgraded the long-term rating to AA+", 30),
        ("LT", "Press Release", "L&T bags order worth Rs 2,500 crore", 20),
        ("ITC", "Trading Window", "Closure of trading window", 40),
        ("INFY", "Updates", "Infosys signs a strategic collaboration agreement", 10),
        ("TCS", "Allotment of ESOP / ESPS", "Allotment of equity shares under ESOP", 50),
    ]
    return [{"id": f"nse-{s}-{i}", "symbol": s, "company": s, "subject": subj, "text": txt,
             "url": f"https://nsearchives.nseindia.com/{s}{i}.pdf", "filed_at": f(h), "source": "nse"}
            for i, (s, subj, txt, h) in enumerate(rows)]


def fake_json(self, *, task, tier, prompt, schema, pdf=None, system=None, max_tokens=4096, allow_fallback=True):
    from core.llm import CallRecord
    self.ledger.add(CallRecord(task, tier, "fake", 1000, 200, False, 0.001, 1))
    if task == "results_extract":
        data = {"basis": "consolidated", "unit": "crore", "period_end": "2026-09-30", "page": 2,
                "current": {"revenue": 16200, "other_income": 120, "finance_costs": 210, "depreciation": 190,
                            "pbt_before_exceptional": 1450, "exceptional_items": -160, "pbt": 1290, "tax": 330, "pat": 960},
                "prev_quarter": {"revenue": 15100, "other_income": 110, "finance_costs": 200, "depreciation": 185,
                                 "pbt_before_exceptional": 1380, "pbt": 1380, "tax": 350, "pat": 1030},
                "year_ago": {"revenue": 13700, "other_income": 100, "finance_costs": 180, "depreciation": 170,
                             "pbt_before_exceptional": 1250, "pbt": 1250, "tax": 320, "pat": 930}}
    elif task == "people_extract":
        data = {"people": [{"name": "Mr. X", "role": "Chief Financial Officer", "change": "resigned"},
                           {"name": "Ms. Y", "role": "Chief Financial Officer", "change": "appointed",
                            "previous_roles": ["CFO, Example Cables (2019-2026)"], "experience_years": 22,
                            "qualifications": ["Chartered Accountant"]}]}
    elif task.startswith("keyterms"):
        data = {"line": "Order worth ₹2,500 crore for a metro project.",
                "facts": [{"label": "Order value", "value": "₹2,500 cr"}]}
    elif task == "oneliners":
        import re
        ids = re.findall(r"id=(\S+)", prompt)
        data = {"lines": [{"id": i, "line": "Summary line."} for i in ids]}
    elif task == "classify_borderline":
        import re
        ids = re.findall(r"id=(\S+)", prompt)
        data = {"labels": [{"id": i, "category": "press_release"} for i in ids]}
    else:
        raise AssertionError(task)
    return schema.model_validate(data)


def test_pipeline_offline(monkeypatch, tmp_path):
    import core.llm as llm

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.Router, "json", fake_json)
    monkeypatch.setattr(rb, "WEB_DATA", tmp_path / "web")
    monkeypatch.setattr(rb, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(rb.Fetcher, "__init__", lambda self: (setattr(self, "errors", []), setattr(self, "source_counts", {"nse": 8, "bse": 0}))[0])
    monkeypatch.setattr(rb.Fetcher, "filings", lambda self, p, s, e: _filings())
    monkeypatch.setattr(rb.Fetcher, "pdf", lambda self, url: (FX / "transcript_q4fy26.pdf").read_bytes())
    monkeypatch.setattr(rb, "market_caps", lambda syms: {"LT": 480000})
    monkeypatch.setattr(rb, "screener_revenue", lambda http, sym: {"Sep 2026": 16180})
    prices = {s: [{"d": f"2026-10-{i:02d}", "c": 100.0, "v": 1000} for i in range(1, 29)] for s in ["TITAN", "CDSL"]}
    prices["CDSL"].append({"d": "2026-10-29", "c": 93.6, "v": 3100})
    prices["^NSEI"] = [{"d": "2026-10-28", "c": 24500.0, "v": 0}, {"d": "2026-10-29", "c": 24610.0, "v": 0}]
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "prices.json").write_text(json.dumps(prices))

    brief = rb.run(Namespace(symbols=None, no_llm=False, from_cache=False, skip_prices=True))
    items = {i["id"]: i for i in brief["items"]}
    titan = items["nse-TITAN-0"]
    assert titan["tier"] == "critical" and titan["kind"] == "results"
    assert titan["body"]["flags"][0]["text"].startswith("Includes ₹160 cr one-off charge")
    assert titan["body"]["checks"]["cross_check_screener"] is True
    assert "nse-TITAN-1" not in items and titan["related"][0]["title"] == "Investor Presentation"
    assert items["nse-POLYCAB-2"]["kind"] == "people" and items["nse-POLYCAB-2"]["tier"] == "critical"
    assert items["nse-DIXON-3"]["kind"] == "keyterms" and items["nse-DIXON-3"]["tier"] == "high"
    assert items["nse-LT-4"]["kind"] == "oneliner" and items["nse-LT-4"]["tier"] == "medium"
    assert items["nse-ITC-5"]["tier"] == "routine"
    assert items["nse-INFY-6"]["route"] == "model"
    assert brief["moves"] and brief["moves"][0]["symbol"] == "CDSL"
    assert "percent" in brief["spoken_brief"] and brief["cost"]["model_calls"] >= 4
    assert brief["context"][0]["label"] == "Nifty 50"
    assert (tmp_path / "web" / "brief.json").exists() and (tmp_path / "out" / "decision_log.jsonl").exists()


def test_failed_enrichment_does_not_stop_run(monkeypatch, tmp_path):
    """A PDF fetch that raises (POLYCAB) and a model call that raises (TITAN) are counted as failed;
    the rest of the brief is still built and written."""
    import core.llm as llm

    def flaky_json(self, *, task, **kw):
        if task == "results_extract":
            raise RuntimeError("Model API unreachable after retries: ReadTimeout")
        return fake_json(self, task=task, **kw)

    def flaky_pdf(self, url):
        if "POLYCAB" in url:
            raise OSError("disk full while caching PDF")
        return (FX / "transcript_q4fy26.pdf").read_bytes()

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.Router, "json", flaky_json)
    monkeypatch.setattr(rb, "WEB_DATA", tmp_path / "web")
    monkeypatch.setattr(rb, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(rb.Fetcher, "__init__", lambda self: (setattr(self, "errors", []), setattr(self, "source_counts", {"nse": 8, "bse": 0}))[0])
    monkeypatch.setattr(rb.Fetcher, "filings", lambda self, p, s, e: _filings())
    monkeypatch.setattr(rb.Fetcher, "pdf", flaky_pdf)
    monkeypatch.setattr(rb, "market_caps", lambda syms: {"LT": 480000})
    monkeypatch.setattr(rb, "screener_revenue", lambda http, sym: {})
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "prices.json").write_text("{}")

    brief = rb.run(Namespace(symbols=None, no_llm=False, from_cache=False, skip_prices=True))
    items = {i["id"]: i for i in brief["items"]}
    assert brief["pipeline"]["enriched"]["failed"] == 2
    # failed rich cards fall back to a one-liner rather than staying blank
    assert items["nse-TITAN-0"]["kind"] == "oneliner" and items["nse-POLYCAB-2"]["kind"] == "oneliner"
    assert items["nse-DIXON-3"]["kind"] == "keyterms"
    assert (tmp_path / "web" / "brief.json").exists()


def test_screener_outage_trips_once(monkeypatch):
    import core.screener as scr
    from core.http import Http

    calls = []

    def down(http, sym):
        calls.append(sym)
        raise RuntimeError("GET failed after 3 attempts: timeout")

    monkeypatch.setattr(scr, "fetch_company", down)
    http = Http(min_interval=0)
    assert rb.screener_revenue(http, "SUNPHARMA") == {} and rb.screener_revenue(http, "MARUTI") == {}
    assert calls == ["SUNPHARMA"]


def test_screener_unknown_ticker_does_not_trip(monkeypatch):
    import core.screener as scr
    from core.http import Http

    calls = []

    def missing(http, sym):
        calls.append(sym)
        raise LookupError("not found")

    monkeypatch.setattr(scr, "fetch_company", missing)
    http = Http(min_interval=0)
    rb.screener_revenue(http, "A"), rb.screener_revenue(http, "B")
    assert calls == ["A", "B"]


def test_keyterms_prompt_names_the_item():
    from pipeline.enrich import summaries

    seen = {}

    class R:
        def json(self, *, prompt, schema, **kw):
            seen["prompt"] = prompt
            return schema.model_validate({"line": "x", "facts": []})

    summaries.keyterms(R(), "M&A", b"%PDF", None, about="Sale or disposal: strike-off of Somit Solutions Limited")
    assert "Somit Solutions" in seen["prompt"] and "THAT item only" in seen["prompt"]
