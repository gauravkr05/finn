"""Snapshot (what the company does) and Bull vs. Bear, from primary sources only.

Snapshot: management's own opening remarks in the latest call (plus annual-report business pages for
pre-computed tickers). Bull/Bear: the strong model may only cite numbered facts FINN computed or quotes
that pass the citation guardrail; points with no valid citation are dropped.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from core.pdftext import format_chunks

from .documents import Doc, guidance_chunks, opening, verify_cited

log = logging.getLogger("finn.synthesis")

RULES = ("Use ONLY the material provided below. Do not use any outside knowledge about this company, its "
         "industry or news. If something isn't in the material, leave it out.")


class Segment(BaseModel):
    name: str
    detail: str = Field(description="max 15 words, e.g. share of revenue if stated")


class SnapQuote(BaseModel):
    text: str = Field(description="exact sentence copied from the material")
    doc: str
    page: Optional[int] = None


class Snapshot(BaseModel):
    business: str = Field(description="2-3 plain sentences: what the company does and how it makes money")
    segments: list[Segment] = Field(default_factory=list)
    quotes: list[SnapQuote] = Field(default_factory=list, description="1-3 supporting quotes")


class Point(BaseModel):
    text: str = Field(description="one tight sentence, max 25 words")
    fact_ids: list[str] = Field(default_factory=list)
    quote: Optional[str] = Field(None, description="exact sentence from a transcript excerpt, if used")
    quote_doc: Optional[str] = None


class BullBear(BaseModel):
    bull: list[Point]
    bear: list[Point]


def snapshot(router, docs: list[Doc], ar: Doc | None, threshold: float) -> dict | None:
    latest = next((d for d in reversed(docs) if not d.scanned and d.chunks), None)
    parts, by_label = [], {}
    if latest:
        parts.append(format_chunks(opening(latest) or latest.chunks[:4], latest.label))
        by_label[latest.label] = latest
    if ar:
        parts.append(format_chunks(ar.chunks, ar.label))
        by_label[ar.label] = ar
    if not parts:
        return None
    prompt = (f"{RULES}\nDescribe the business for an investor: what it does, its segments and revenue mix if "
              "stated. Quote 1-3 exact supporting sentences, with the document label and page from the tags.\n\n"
              + "\n\n".join(parts))
    snap: Snapshot = router.json(task="snapshot", tier="cheap", prompt=prompt, schema=Snapshot, max_tokens=1500)
    quotes = []
    for q in snap.quotes:
        ref = q.doc if not q.page or "p." in (q.doc or "") else f"{q.doc} p.{q.page}"
        d, m = verify_cited(q.text, ref, list(by_label.values()), threshold)
        if d:
            quotes.append({"doc": d.label, "url": d.url, "page": m.page, "quote": m.quote, "paragraph": m.paragraph})
    return {"business": snap.business, "segments": [s.model_dump() for s in snap.segments], "sources": quotes,
            "verified": bool(quotes), "from": list(by_label)}


def facts_pack(fin: dict, claims: list[dict], drift: list[dict]) -> dict[str, str]:
    facts: dict[str, str] = {}
    s, t, c = fin["snapshot"], fin["trajectory"], fin["cash"]

    def add(text):
        facts[f"F{len(facts) + 1}"] = text

    if s.get("revenue") is not None:
        add(f"{s['fy']}: revenue ₹{s['revenue']:,.0f} cr ({s.get('revenue_growth')}% YoY), net profit "
            f"₹{(s.get('pat') or 0):,.0f} cr ({s.get('pat_growth')}% YoY), operating margin {s.get('opm')}%")
    if t.get("revenue_cagr_3y") is not None:
        add(f"3-year revenue CAGR {t['revenue_cagr_3y']}%, net profit CAGR {t.get('pat_cagr_3y')}%")
    if t.get("opm_change_3y_bps") is not None:
        add(f"Operating margin changed {t['opm_change_3y_bps']} bps over 3 years")
    if c.get("cumulative_3y_pct") is not None and not fin["lender"]:
        add(f"Operating cash flow was {c['cumulative_3y_pct']}% of net profit over the last 3 years")
    if s.get("debt_to_equity") is not None:
        add(f"Debt-to-equity {s['debt_to_equity']}")
    for k, v in (s.get("ratios") or {}).items():
        add(f"{k}: {v}")
    for f in fin["flags"]:
        add(f"Flag: {f['text']}")
    for cl in claims:
        if cl.get("verdict") in ("kept", "partly", "missed"):
            add(f"Promise ({cl['said_in']}): {cl['statement']} -> {cl['verdict']} ({cl.get('reason', '')})")
    for d in drift:
        add(f"Guidance drift on {d['metric']} for {d['period']}: {d['direction']} across calls")
    return facts


def bull_bear(router, fin: dict, claims: list[dict], drift: list[dict], docs: list[Doc], threshold: float) -> dict:
    facts = facts_pack(fin, claims, drift)
    latest = [d for d in docs if not d.scanned][-2:]
    excerpts = "\n\n".join(format_chunks(guidance_chunks(d)[:6], d.label) for d in latest if d.chunks)
    prompt = (f"{RULES}\nWrite a tight investment Bull case and Bear case, 3 points each. Every point must cite "
              "fact_ids from the FACTS list and/or quote an exact sentence from the EXCERPTS (with quote_doc). "
              "Be specific; no generic statements.\n\nFACTS:\n"
              + "\n".join(f"{k}: {v}" for k, v in facts.items()) + f"\n\nEXCERPTS:\n{excerpts}")
    try:
        bb: BullBear = router.json(task="bull_bear", tier="strong", prompt=prompt, schema=BullBear, max_tokens=2000)
    except Exception as e:
        log.warning("bull/bear failed: %s", e)
        return {"bull": [], "bear": [], "facts": facts, "dropped_uncited": 0, "skipped": True}
    dropped = 0

    def clean(points: list[Point]) -> list[dict]:
        nonlocal dropped
        out = []
        for p in points:
            ids = [i for i in p.fact_ids if i in facts]
            src = None
            d, m = verify_cited(p.quote, p.quote_doc, docs, threshold)
            if d:
                src = {"doc": d.label, "url": d.url, "page": m.page, "quote": m.quote, "paragraph": m.paragraph}
            if not ids and not src:
                dropped += 1
                continue
            out.append({"text": p.text, "facts": [{"id": i, "text": facts[i]} for i in ids], "source": src})
        return out

    bull, bear = clean(bb.bull), clean(bb.bear)
    fell_back = router._effective_tier("strong") != "strong"
    if fell_back and dropped:
        # Written by the cheap model because the strong one was out of quota: keep it only if every
        # single point passed the citation check.
        log.warning("bull/bear from the cheap model had %d uncited point(s); not shown", dropped)
        return {"bull": [], "bear": [], "facts": facts, "dropped_uncited": dropped, "skipped": True}
    return {"bull": bull, "bear": bear, "facts": facts, "dropped_uncited": dropped, "fell_back": fell_back}
