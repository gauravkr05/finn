"""Write SAMPLE data so the app can be developed and previewed before the real pipeline has run.

Everything produced here is synthetic and marked `"sample": true`; the app shows a banner saying so.
It runs the real pipeline and research code with a fake exchange feed and a fake model, so the files
have exactly the shape the real run produces. Replace it by running:

    python -m pipeline.run_brief
    python -m api.precompute <TICKERS>
"""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api.documents as documents  # noqa: E402
import api.research as research  # noqa: E402
import core.llm as llm  # noqa: E402
import pipeline.run_brief as rb  # noqa: E402
from core.config import WEB_DATA, load_config  # noqa: E402
from tests import test_pull as tp  # noqa: E402
from tests import test_smoke_pipeline as ts  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
EXTRA = [
    ("BAJFINANCE", "Disclosure of Encumbrance", "Creation of pledge on 1.2% of promoter shareholding", 26),
    ("SUNPHARMA", "Action(s) initiated or orders passed", "Penalty of Rs. 4.2 lakh levied by GST authority", 12),
    ("HDFCBANK", "Outcome of Board Meeting", "Unaudited financial results for the quarter ended September 30, 2026", 60),
    ("RELIANCE", "Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meetings with institutional investors", 8),
    ("MARUTI", "Shareholders meeting", "Voting results of postal ballot", 15),
    ("ASIANPAINT", "Copy of Newspaper Publication", "Newspaper publication of notice", 28),
    ("TRENT", "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Regulation 74(5)", 33),
    ("KPITTECH", "Acquisition", "Acquisition of 100% stake in a German engineering firm for Rs 920 crore", 18),
    ("HINDUNILVR", "Dividend", "Interim dividend of Rs 19 per share; record date November 12", 6),
    ("ICICIBANK", "Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings call held on October 25", 70),
]


def filings():
    base = ts._filings()
    now = datetime.now(IST)
    for i, (s, subj, txt, h) in enumerate(EXTRA, start=len(base)):
        base.append({"id": f"nse-{s}-{i}", "symbol": s, "company": s, "subject": subj, "text": txt,
                     "url": f"https://nsearchives.nseindia.com/{s}{i}.pdf",
                     "filed_at": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+05:30"), "source": "nse"})
    return base


_RESULTS_CALLS = {"n": 0}
LENDER = {"basis": "standalone", "unit": "crore", "company_type": "lender", "period_end": "2026-09-30", "page": 3,
          "current": {"revenue": 84200, "other_income": 11900, "pbt_before_exceptional": 23400, "pbt": 23400,
                      "tax": 5600, "pat": 17800, "provisions": 3100},
          "prev_quarter": {"revenue": 82100, "other_income": 11200, "pbt_before_exceptional": 22800, "pbt": 22800,
                           "tax": 5500, "pat": 17300, "provisions": 2900},
          "year_ago": {"revenue": 77500, "other_income": 10700, "pbt_before_exceptional": 21300, "pbt": 21300,
                       "tax": 5100, "pat": 16200, "provisions": 2700}}


def fake_json(self, **kw):
    if kw["task"] == "results_extract":
        _RESULTS_CALLS["n"] += 1
        if _RESULTS_CALLS["n"] == 1:  # highest score first: HDFCBANK, a lender
            from core.llm import CallRecord
            self.ledger.add(CallRecord("results_extract", "cheap", "fake", 1000, 200, False, 0.0, 1))
            return kw["schema"].model_validate(LENDER)
    return ts.fake_json(self, **kw)


def prices(symbols, indices, days=85):
    rnd = random.Random(7)
    out = {}
    start = datetime.now(IST).date() - timedelta(days=int(days * 1.45))
    dates, d = [], start
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    for s in symbols + indices:
        px = {"^NSEI": 24500.0, "^INDIAVIX": 13.0}.get(s, rnd.uniform(300, 4000))
        vol = rnd.uniform(4e5, 6e6)
        rows = []
        for i, dt in enumerate(dates):
            px *= 1 + rnd.gauss(0.0004, 0.012 if not s.startswith("^") else 0.007)
            v = vol * math.exp(rnd.gauss(0, 0.25))
            rows.append({"d": dt, "c": round(px, 2), "v": int(v) if not s.startswith("^") else 0})
        out[s] = rows
    # a few unusual days so the alerts have something to find
    for s, back, mv, vm in (("CDSL", 1, -6.4, 3.1), ("DIXON", 3, 5.2, 2.4), ("TRENT", 6, -2.1, 2.7),
                            ("POLYCAB", 1, -4.6, 1.6)):
        r = out[s]
        i = len(r) - back
        r[i]["c"] = round(r[i - 1]["c"] * (1 + mv / 100), 2)
        avg = sum(x["v"] for x in r[i - 20:i]) / 20
        r[i]["v"] = int(avg * vm)
    return out


def main():
    cfg = load_config()
    tmp = Path(tempfile.mkdtemp())
    llm.CACHE_DIR = tmp
    import os

    os.environ.setdefault("GEMINI_API_KEY", "sample")
    llm.Router.json = fake_json
    rb.Fetcher.__init__ = lambda self: (setattr(self, "errors", []), setattr(self, "source_counts", {"nse": 0, "bse": 0}))[0]
    rb.Fetcher.filings = lambda self, p, s, e: filings()
    rb.Fetcher.pdf = lambda self, url: (ROOT / "tests/fixtures/transcript_q4fy26.pdf").read_bytes()
    rb.market_caps = lambda syms: {"LT": 480000, "KPITTECH": 38000, "SUNPHARMA": 420000}
    rb.screener_revenue = lambda http, sym: {"Sep 2026": 16180}
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    p = prices([x["symbol"] for x in cfg["portfolio"]], [i["symbol"] for i in cfg["context_indices"]])
    (WEB_DATA / "prices.json").write_text(json.dumps(p, separators=(",", ":")))

    brief = rb.run(Namespace(symbols=None, no_llm=False, from_cache=False, skip_prices=True))
    brief["sample"] = True
    for it in brief["items"]:
        it["company"] = next((x["name"] for x in cfg["portfolio"] if x["symbol"] == it["symbol"]), it["symbol"])
        if it["kind"] == "keyterms":  # the fake model can't read PDFs: use the filing text for the sample
            it["line"] = it["text"]
            it["body"] = {"facts": [], "source": None}
        if it["kind"] == "oneliner":
            it["line"] = it["text"]
    from pipeline.enrich.spoken import spoken_brief
    now = datetime.fromisoformat(brief["generated_at"])
    last24 = [c for c in brief["items"] if (now - datetime.fromisoformat(c["filed_at"])).total_seconds() <= 86400]
    latest = brief["moves"][0]["date"] if brief["moves"] else None
    brief["spoken_brief"] = spoken_brief(last24, [m for m in brief["moves"] if m["date"] == latest],
                                         sum(c["tier"] == "routine" for c in last24), "Good morning",
                                         {x["symbol"]: x["name"] for x in cfg["portfolio"]})
    brief["cost"]["est_usd_if_paid"] = 0.0
    (WEB_DATA / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, separators=(",", ":"), default=str))

    research.Http = tp.FakeHttp
    documents.CACHE_DIR = tmp
    llm.Router.json = tp.fake_json
    res = research.run("FIXTURE")
    res["ticker"], res["name"], res["sample"] = "DEMO", "Demo Paints Ltd (sample)", True
    out = WEB_DATA / "research"
    out.mkdir(exist_ok=True)
    (out / "DEMO.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
    (out / "index.json").write_text(json.dumps({"tickers": ["DEMO"]}))
    print(f"Sample data written to {WEB_DATA} ({len(brief['items'])} items).")


if __name__ == "__main__":
    main()
