"""Research orchestrator for any NSE ticker (R1-R8 in the README)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from core.config import load_config
from core.http import Http
from core.llm import Ledger, Router
from core.screener import fetch_company

from . import documents, financials, promises, synthesis

log = logging.getLogger("finn.research")
IST = timezone(timedelta(hours=5, minutes=30))
Progress = Callable[[str, str, int], None]


def _noop(step: str, msg: str, pct: int) -> None:
    log.info("[%3d%%] %s: %s", pct, step, msg)


def run(ticker: str, progress: Progress = _noop, with_annual_report: bool = False) -> dict:
    cfg = load_config()
    pc, threshold = cfg["promises"], cfg["guardrails"]["quote_match_threshold"]
    ledger = Ledger()
    router = Router(ledger)
    http = Http(min_interval=1.0)
    t0 = datetime.now(IST)

    progress("resolve", f"Looking up {ticker} on screener.in", 5)
    page = fetch_company(http, ticker)

    progress("numbers", "Reading financial tables", 15)
    fin = financials.build(page)

    progress("documents", f"Fetching the last {pc['transcripts']} concall transcripts", 25)
    docs = documents.transcripts(http, page, pc["transcripts"])
    ar = None
    if with_annual_report:
        progress("documents", "Reading the annual report's business pages", 35)
        ar = documents.annual_report(http, page)

    llm_ok = router.available("cheap")
    claims, dropped = [], 0
    strong_skipped: list[str] = []  # strong-model steps not done (quota): such results are never cached
    if llm_ok and docs:
        for i, d in enumerate(docs):
            progress("extract", f"Extracting guidance from the {d.label}", 40 + i * 8)
            try:
                c, dr = promises.extract_claims(router, d, threshold)
                claims += c
                dropped += dr
            except Exception as e:
                log.warning("extraction failed for %s: %s", d.label, e)
        progress("judge", "Matching promises against reported numbers", 75)
        promises.judge_all(page, claims, pc)
        progress("judge", "Checking later calls for follow-through", 80)
        if not promises.qualitative(router, claims, docs, threshold, pc["max_qualitative"]):
            strong_skipped.append("promise_followup")
    drift = promises.drift(claims)

    snap, bb = None, {"bull": [], "bear": [], "facts": {}, "dropped_uncited": 0}
    if llm_ok and (docs or ar):
        progress("synthesise", "Writing the business snapshot", 85)
        try:
            snap = synthesis.snapshot(router, docs, ar, threshold)
        except Exception as e:
            log.warning("snapshot failed: %s", e)
        progress("synthesise", "Building the bull and bear cases", 92)
        bb = synthesis.bull_bear(router, fin, claims, drift, docs, threshold)
        if bb.get("skipped"):
            strong_skipped.append("bull_bear")

    judged = [c for c in claims if c["verdict"] in ("kept", "partly", "missed")]
    score = {"kept": sum(c["verdict"] == "kept" for c in judged), "judged": len(judged),
             "partly": sum(c["verdict"] == "partly" for c in judged),
             "missed": sum(c["verdict"] == "missed" for c in judged),
             "pending": sum(c["verdict"] == "pending" for c in claims),
             "unchecked": sum(c["verdict"] == "unchecked" for c in claims)}
    order = {"missed": 0, "partly": 1, "kept": 2, "pending": 3, "unchecked": 4, "unjudged": 5}
    claims.sort(key=lambda c: (order.get(c["verdict"], 5), [-x for x in c["order"]]))
    for c in claims:
        c.pop("order", None)

    progress("done", "Done", 100)
    return {
        "ticker": page.ticker, "name": page.name, "generated_at": t0.isoformat(),
        "mode": "full" if llm_ok else "numbers-only",
        "documents": [{"label": d.label, "kind": d.kind, "url": d.url, "scanned": d.scanned,
                       "pages": len(d.pages)} for d in docs] + (
            [{"label": ar.label, "kind": ar.kind, "url": ar.url, "scanned": False, "pages": len(ar.pages)}] if ar else []),
        "snapshot": snap, "financials": fin, "promises": claims, "promise_score": score, "drift": drift,
        "bull": bb["bull"], "bear": bb["bear"], "facts": bb["facts"],
        "complete": not strong_skipped,
        "trace": {**ledger.summary(), "dropped_uncited": dropped + bb.get("dropped_uncited", 0),
                  "strong_skipped": strong_skipped, "bull_bear_model": "cheap" if bb.get("fell_back") else "strong",
                  "seconds": round((datetime.now(IST) - t0).total_seconds(), 1)},
    }
