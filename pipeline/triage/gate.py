"""Layer 3: confidence gate.

High-confidence rule labels are kept as they are. Borderline and unknown filings go to the cheap
model, in one batched call, with ENAM's category definitions. Without an API key the rule label is
kept and the item is marked rules-only, so the pipeline never fails for lack of a model.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from core.llm import LLMUnavailable, Router

from .rules import CATEGORIES, _role, has, ma_subtype

log = logging.getLogger("finn.gate")

DEFINITIONS = """results: quarterly/annual results, the board meeting approving them, results decks, results ads
M&A: acquisition, merger, demerger, joint venture, investing in or selling a stake in a subsidiary
fund_raise: rights issue, QIP, preferential allotment, buyback, commercial paper or other debt
management_change: a CEO, CFO, MD, KMP or director joining, resigning or retiring
litigation: lawsuits, regulatory orders, fines, warnings, insolvency/restructuring proceedings
insider_trading: a promoter or insider buying/selling their own shares
earnings_call: notice, transcript or recording of the earnings conference call
investor_meetings: meetings with specific investors/funds or attending an investor conference
credit_rating: a rating assigned, upgraded, downgraded or reaffirmed
dividend: a cash dividend and its record date
bonus_split: bonus issue or stock split
capex: approving spend on a new plant, facility or capacity expansion
press_release: order wins, launches, partnerships, rumour clarifications not covered above
postal_ballot: postal ballot notice or result
agm_egm: annual/extraordinary general meeting notice or result
pledging: promoter pledging, releasing or changing pledged shares
unclassified: routine paperwork (ESOP allotments, compliance certificates, ESG reports, auditor appointments)"""


class Label(BaseModel):
    id: str
    category: str = Field(description="one of the listed categories")


class Labels(BaseModel):
    labels: list[Label]


def apply_gate(items: list[dict], router: Router) -> dict[str, str]:
    """Returns {item_id: route} where route is 'rules', 'model' or 'rules-only'."""
    routes: dict[str, str] = {}
    pending = [it for it in items if it["cls"]["confidence"] != "high"]
    for it in items:
        routes[it["id"]] = "rules"
    if not pending:
        return routes
    if not router.available("cheap"):
        for it in pending:
            routes[it["id"]] = "rules-only"
        return routes
    for i in range(0, len(pending), 25):
        batch = pending[i:i + 25]
        lines = "\n".join(f'- id={it["id"]} | subject: {it["subject"][:160]} | text: {it["text"][:400]}'
                          for it in batch)
        prompt = ("Classify each Indian stock-exchange filing into exactly one category.\n"
                  f"Categories:\n{DEFINITIONS}\n\nFilings:\n{lines}")
        try:
            out = router.json(task="classify_borderline", tier="cheap", prompt=prompt, schema=Labels,
                              max_tokens=2000)
        except (LLMUnavailable, ValueError, RuntimeError) as e:
            log.warning("Gate model call failed, keeping rule labels: %s", e)
            for it in batch:
                routes[it["id"]] = "rules-only"
            continue
        got = {l.id: l.category for l in out.labels if l.category in CATEGORIES}
        for it in batch:
            if it["id"] in got:
                if got[it["id"]] != it["cls"]["category"]:
                    new = {"category": got[it["id"]], "confidence": "model",
                           "rule": f'model (rules said {it["cls"]["category"]})'}
                    if new["category"] == "results" and has(it["subject"].lower(), "outcome"):
                        # "Outcome of Board Meeting held on <date>" relabelled as results is the results
                        # outcome itself; group_related prefers NSE's standard results filing if there is one.
                        new["subtype"] = "final"
                    if new["category"] == "M&A":
                        sub = ma_subtype(f'{it["subject"]} || {it["text"]}'.lower(), it["text"].lower())
                        if sub:
                            new["subtype"] = sub
                    if new["category"] == "management_change":
                        a = f'{it["subject"]} {it["text"]}'.lower()
                        new["role"] = _role(a)
                        new["direction"] = "negative" if has(a, "resign*", "cessation") else "neutral"
                    it["cls"] = new
                else:
                    it["cls"]["confidence"] = "model-confirmed"
                routes[it["id"]] = "model"
            else:
                routes[it["id"]] = "rules-only"
    return routes
