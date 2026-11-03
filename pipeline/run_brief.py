"""Push pipeline: fetch -> classify -> gate -> score -> enrich -> write JSON for the app.

    python -m pipeline.run_brief                 # full run
    python -m pipeline.run_brief --no-llm        # rules only (no API key needed)
    python -m pipeline.run_brief --from-cache    # reuse the last fetched filings (e.g. if NSE blocks you)
    python -m pipeline.run_brief --symbols TITAN INFY
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from core.config import CACHE_DIR, OUT_DIR, WEB_DATA, load_config
from core.http import Http
from core.llm import Ledger, Router
from core.pdftext import extract_pages

from .decision_log import DecisionLog
from .enrich import people as people_mod
from .enrich import results as results_mod
from .enrich import summaries
from .enrich.spoken import spoken_brief
from .moves import detect
from .triage.gate import apply_gate
from .triage.rules import classify
from .triage.score import CATEGORY_LABEL, score_item

log = logging.getLogger("finn.run")
IST = timezone(timedelta(hours=5, minutes=30))
KEYTERM_CATS = {"M&A", "litigation", "fund_raise", "capex", "credit_rating", "pledging", "insider_trading",
                "press_release"}


def _pdf_cache(url: str) -> "Path":  # noqa: F821
    d = CACHE_DIR / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")


class Fetcher:
    def __init__(self):
        from .sources.bse import BSE
        from .sources.nse import NSE

        self.http = Http(min_interval=1.2)
        self.nse = NSE(self.http)
        self.bse = BSE(self.http)
        self.errors: list[str] = []
        self.source_counts = {"nse": 0, "bse": 0}

    def filings(self, portfolio: list[dict], start: datetime, end: datetime) -> list[dict]:
        out = []
        for p in portfolio:
            sym = p["symbol"]
            try:
                rows = self.nse.announcements(sym, start, end)
                self.source_counts["nse"] += len(rows)
            except Exception as e:
                rows = []
                if p.get("bse_code"):
                    try:
                        rows = self.bse.announcements(sym, str(p["bse_code"]), start, end)
                        self.source_counts["bse"] += len(rows)
                    except Exception as e2:
                        self.errors.append(f"{sym}: NSE and BSE failed ({e2})")
                else:
                    self.errors.append(f"{sym}: NSE failed ({str(e)[:120]})")
            for r in rows:
                r["company"] = p.get("name") or r.get("company") or sym
            out.extend(rows)
            log.info("%-11s %3d filings", sym, len(rows))
        return out

    def pdf(self, url: str) -> bytes | None:
        if not url or not url.lower().split("?")[0].endswith(".pdf"):
            return None
        path = _pdf_cache(url)
        if path.exists():
            return path.read_bytes()
        try:
            data = (self.bse if "bseindia" in url else self.nse).download(url)
        except Exception as e:
            log.warning("PDF download failed %s: %s", url, e)
            return None
        if not data.startswith(b"%PDF"):
            return None
        path.write_bytes(data)
        return data


def market_caps(symbols: list[str]) -> dict[str, float]:
    """Market cap in ₹ crore, used to size deal/order/penalty amounts. Cached for a day."""
    path = CACHE_DIR / "mcap.json"
    if path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < 86400:
        return json.loads(path.read_text())
    caps: dict[str, float] = {}
    try:
        import yfinance as yf

        for s in symbols:
            try:
                mc = yf.Ticker(f"{s}.NS").fast_info.get("marketCap")
                if mc:
                    caps[s] = round(float(mc) / 1e7, 0)
            except Exception:
                continue
    except Exception as e:
        log.warning("market caps unavailable: %s", e)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(caps))
    return caps


def screener_revenue(http: Http, symbol: str) -> dict[str, float]:
    from core.screener import fetch_company

    if getattr(http, "screener_down", False):
        return {}
    try:
        page = fetch_company(http, symbol)
    except Exception as e:
        log.info("screener cross-check unavailable for %s: %s", symbol, e)
        if isinstance(e, RuntimeError):  # network failure after retries: don't spend 90 s on every company
            log.warning("screener.in unreachable; skipping the revenue cross-check for the rest of this run")
            http.screener_down = True
        return {}
    t = page.tables["quarters"]
    row = t.row("Sales", "Revenue")
    if not row:
        return {}
    return {h: v for h, v in zip(t.headers, row) if v is not None}


def group_related(cards: list[dict]) -> list[dict]:
    """Fold a results card's satellites (deck, ad, press release, call notice/recording, duplicate outcome
    filings) into one parent per company."""
    parents: dict[str, dict] = {}
    for c in sorted(cards, key=lambda c: c["filed_at"]):  # earliest first
        if c["category"] == "results" and c.get("subtype") == "final":
            # Several "final" filings per company are common (outcome letter + the results filing itself).
            # Prefer NSE's standard results filing, which carries the results PDF.
            standard = "submitted to the exchange" in (c.get("text") or "").lower()
            cur = parents.get(c["symbol"])
            if cur is None or (standard and "submitted to the exchange" not in (cur.get("text") or "").lower()):
                parents[c["symbol"]] = c
    out = []
    for c in cards:
        p = parents.get(c["symbol"])
        satellite = (c["category"] == "results" and c.get("subtype") in ("deck", "ad", "intimation", "press", "final", None)) or (
            c["category"] == "earnings_call" and c.get("subtype") in ("intimation", "recording"))
        if p is not None and p is not c and satellite and abs(
                (datetime.fromisoformat(c["filed_at"]) - datetime.fromisoformat(p["filed_at"])).total_seconds()) <= 6 * 86400:
            p.setdefault("related", []).append({"title": c["title"], "filed_at": c["filed_at"], "url": c.get("url"),
                                                "category": c["category"]})
            continue
        out.append(c)
    return out


def run(args) -> dict:
    cfg = load_config()
    portfolio = cfg["portfolio"]
    if args.symbols:
        wanted = {s.upper() for s in args.symbols}
        portfolio = [p for p in portfolio if p["symbol"] in wanted]
    pmap = {p["symbol"]: p for p in portfolio}
    now = datetime.now(IST).replace(microsecond=0)
    start = now - timedelta(days=cfg["brief"]["lookback_days"])
    ledger = Ledger()
    router = Router(ledger)
    dlog = DecisionLog()
    use_llm = not args.no_llm and router.available("cheap")
    if not args.no_llm and not use_llm:
        log.warning("No GEMINI_API_KEY found: running rules-only. Rich cards need a key.")
    fetcher = Fetcher()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    # ---- prices -------------------------------------------------------------------------------
    prices_path = WEB_DATA / "prices.json"
    prices: dict = {}
    if not args.skip_prices:
        from .sources.prices import fetch_eod

        idx = [i["symbol"] for i in cfg.get("context_indices", [])]
        try:
            prices = fetch_eod([p["symbol"] for p in cfg["portfolio"]], idx, cfg["brief"]["price_days"])
            prices_path.write_text(json.dumps(prices, separators=(",", ":")))
            log.info("Prices: %d series", len(prices))
        except Exception as e:
            fetcher.errors.append(f"prices: {e}")
    if not prices and prices_path.exists():
        prices = json.loads(prices_path.read_text())

    # ---- filings ------------------------------------------------------------------------------
    raw_path = OUT_DIR / "filings.json"
    if args.from_cache and raw_path.exists():
        filings = json.loads(raw_path.read_text())
        filings = [f for f in filings if f["symbol"] in pmap]
        log.info("Loaded %d cached filings", len(filings))
    else:
        filings = fetcher.filings(portfolio, start, now)
        raw_path.write_text(json.dumps(filings, indent=1))
    seen, items = set(), []
    for f in sorted(filings, key=lambda x: x["filed_at"], reverse=True):
        key = (f["symbol"], f["subject"].lower(), f["text"][:120].lower(), f["filed_at"][:16])
        if f["id"] in seen or key in seen:
            continue
        seen.update({f["id"], key})
        items.append(f)

    # ---- L2 rules / L3 gate / L4 score ------------------------------------------------------------
    for it in items:
        it["cls"] = classify(it["subject"], it["text"]).as_dict()
        dlog.write(it["id"], "L2_rules", it["cls"])
    routes = apply_gate(items, router) if use_llm else {
        it["id"]: ("rules" if it["cls"]["confidence"] == "high" else "rules-only") for it in items}
    for it in items:
        dlog.write(it["id"], "L3_gate", {"route": routes[it["id"]], "category": it["cls"]["category"]})

    caps = market_caps(list(pmap)) if not args.skip_prices else {}
    followed = set(cfg["alerts"]["categories"])
    cards = []
    for it in items:
        sc = score_item(it, it["cls"], cfg, pmap[it["symbol"]]["weight"], followed, now, caps.get(it["symbol"]))
        dlog.write(it["id"], "L4_score", {k: sc[k] for k in ("score", "tier", "score_parts")})
        cards.append({
            "id": it["id"], "symbol": it["symbol"], "company": it["company"],
            "category": it["cls"]["category"], "category_label": CATEGORY_LABEL.get(it["cls"]["category"]),
            "subtype": it["cls"].get("subtype"), "role": it["cls"].get("role"),
            "direction": it["cls"].get("direction"), "also": it["cls"].get("also", []),
            "tier": sc["tier"], "score": sc["score"], "why": sc["why"],
            "title": it["subject"] or CATEGORY_LABEL.get(it["cls"]["category"], "Filing"),
            "text": it["text"][:600], "filed_at": it["filed_at"], "url": it.get("url"), "source": it["source"],
            "kind": "plain", "route": routes[it["id"]],
        })
    cards = group_related(cards)

    # ---- L5 enrichment ------------------------------------------------------------------------------
    enr = cfg["enrich"]
    counts = {"results": 0, "people": 0, "keyterms": 0, "oneliners": 0, "failed": 0}
    rev_http = Http(min_interval=2.0)
    by_priority = sorted(cards, key=lambda c: c["score"], reverse=True)
    for c in by_priority:
        if not use_llm or c["tier"] not in ("critical", "high"):
            continue
        want_results = c["category"] == "results" and c.get("subtype") == "final" and counts["results"] < enr["max_results_cards"]
        want_people = c["category"] == "management_change" and counts["people"] < enr["max_people_cards"]
        want_keyterms = c["category"] in KEYTERM_CATS
        if not (want_results or want_people or want_keyterms):
            continue
        try:  # one bad PDF, download or model hiccup must not stop the brief
            pdf = fetcher.pdf(c.get("url"))
            if pdf is None:
                dlog.write(c["id"], "L5_enrich", {"skipped": "no PDF attachment"})
                continue
            try:
                pages = extract_pages(pdf, max_pages=60)
            except Exception:
                pages = []
            if want_results:
                ex = results_mod.extract(router, pdf)
                kind = pmap[c["symbol"]].get("kind")
                ref = screener_revenue(rev_http, c["symbol"]) if kind != "lender" else {}
                c["body"] = results_mod.compute(ex, kind, pages, ref)
                c["kind"] = "results"
                counts["results"] += 1
            elif want_people:
                c["body"] = people_mod.build(router, pdf, pages, c["company"])
                c["kind"] = "people"
                counts["people"] += 1
            else:
                kt = summaries.keyterms(router, c["category"], pdf, pages, about=f'{c["title"]}: {c["text"]}')
                c["kind"], c["line"], c["body"] = "keyterms", kt["line"], {"facts": kt["facts"],
                                                                            "source": kt.get("source")}
                counts["keyterms"] += 1
            dlog.write(c["id"], "L5_enrich", {"kind": c["kind"]})
        except Exception as e:
            counts["failed"] += 1
            dlog.write(c["id"], "L5_enrich", {"error": str(e)[:200]})
            log.warning("Enrichment failed for %s: %s", c["id"], e)

    # critical items land here too when they have no PDF to enrich (e.g. an exchange news-verification query)
    need_lines = [c for c in cards if c["kind"] == "plain" and c["tier"] in ("critical", "high", "medium")]
    if use_llm and need_lines:
        lines = summaries.oneliners(router, [{"id": c["id"], "symbol": c["symbol"], "subject": c["title"],
                                              "text": c["text"]} for c in need_lines], enr["oneliner_batch"])
        for c in need_lines:
            if c["id"] in lines:
                c["line"], c["kind"] = lines[c["id"]], "oneliner"
                counts["oneliners"] += 1
                dlog.write(c["id"], "L5_enrich", {"kind": "oneliner"})

    # ---- L6 digest ------------------------------------------------------------------------------------
    for c in cards:
        c["trace"] = dlog.trace(c["id"])
    cards.sort(key=lambda c: (-{"critical": 3, "high": 2, "medium": 1, "routine": 0}[c["tier"]], -c["score"]))
    al = cfg["alerts"]
    moves = detect(prices, list(pmap), al["volume_multiple"], al["price_move_pct"], al["lookback_days"], days=10)
    last24 = [c for c in cards if (now - datetime.fromisoformat(c["filed_at"])).total_seconds() <= 86400]
    hour = now.hour + now.minute / 60
    run_name = "Opening Brief" if hour < 12 else "Closing Bell" if hour >= 15.5 else "Midday update"
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    recent_moves = [m for m in moves if m["date"] == (moves[0]["date"] if moves else None)]
    routes_count: dict[str, int] = {}
    for r in routes.values():
        routes_count[r] = routes_count.get(r, 0) + 1

    context = []
    for ix in cfg.get("context_indices", []):
        s = prices.get(ix["symbol"]) or []
        if len(s) >= 2:
            context.append({"label": ix["label"], "symbol": ix["symbol"], "close": s[-1]["c"],
                            "change_pct": round((s[-1]["c"] / s[-2]["c"] - 1) * 100, 2), "date": s[-1]["d"]})

    brief = {
        "version": 2,
        "sample": False,
        "generated_at": now.isoformat(),
        "run": run_name,
        "lookback_days": cfg["brief"]["lookback_days"],
        "rhythm": {"opening": "08:30", "closing": "16:00"},
        "mode": "full" if use_llm else "rules-only",
        "portfolio": [{k: p.get(k) for k in ("symbol", "name", "sector", "weight", "kind")} for p in cfg["portfolio"]],
        "context": context,
        "alert_defaults": al,
        "triage": {"tiers": cfg["triage"]["tiers"], "preference_boost": cfg["triage"]["preference_boost"],
                   "recency_bonus": cfg["triage"]["recency_bonus"]},
        "items": cards,
        "moves": moves,
        "spoken_brief": spoken_brief([c for c in cards if c in last24], recent_moves,
                                     sum(1 for c in last24 if c["tier"] == "routine"), greeting,
                                     {p["symbol"]: p["name"] for p in cfg["portfolio"]}),
        "pipeline": {
            "filings": len(items), "routes": routes_count, "enriched": counts,
            "sources": fetcher.source_counts, "errors": fetcher.errors[:20],
        },
        "cost": ledger.summary(),
    }
    (WEB_DATA / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, separators=(",", ":"), default=str))
    dlog.dump(OUT_DIR / "decision_log.jsonl")
    log.info("Wrote brief: %d items (%s), %d model calls, %d cached. Errors: %d",
             len(cards), routes_count, brief["cost"]["model_calls"], brief["cost"]["cached_calls"],
             len(fetcher.errors))
    return brief


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build FINN's push brief")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--no-llm", action="store_true", help="rules only, no model calls")
    ap.add_argument("--from-cache", action="store_true", help="reuse pipeline/out/filings.json")
    ap.add_argument("--skip-prices", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    brief = run(args)
    errs = brief["pipeline"]["errors"]
    if errs:
        print("\nSome sources failed:", *errs, sep="\n  ", file=sys.stderr)


if __name__ == "__main__":
    main()
