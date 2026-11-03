"""One-liners and key terms.

- Key terms (critical/high M&A, litigation, fund raise, capex, ratings, pledging, insider trades): the
  cheap model reads the filing PDF and returns a one-line summary plus labelled facts.
- One-liners (medium tier): no PDF; the exchange's own description text is summarised in batches, one
  model call per batch, which keeps the cost of the long tail close to zero.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from core.guardrails import verify_quote

log = logging.getLogger("finn.summaries")

KEYTERM_HINTS = {
    "M&A": "target company, deal type (acquisition/merger/JV/stake sale), consideration and stake %, expected completion",
    "litigation": "authority or court, nature of the order or case, amount involved, company's stated view",
    "fund_raise": "instrument (QIP/rights/preferential/buyback/NCD/CP), amount, price, purpose",
    "capex": "amount, what is being built, location, capacity, timeline",
    "credit_rating": "agency, instrument, rating, action (upgrade/downgrade/reaffirm), outlook",
    "pledging": "promoter, shares pledged/released, pledged % before and after",
    "insider_trading": "who, buy or sell, number of shares, value, holding before and after",
    "press_release": "what was announced, order value, customer, timeline",
}


class Fact(BaseModel):
    label: str
    value: str


class KeyTerms(BaseModel):
    line: str = Field(description="one sentence, max 22 words, what happened and the key number")
    facts: list[Fact] = Field(default_factory=list, description="2-5 short label/value pairs")
    quote: Optional[str] = Field(None, description="one sentence copied exactly from the filing supporting the line")


def keyterms(router, category: str, pdf: bytes, page_texts: list[str] | None, about: str = "") -> dict:
    # A board-meeting outcome PDF often covers several decisions; tell the model which one this filing is.
    focus = (f"The exchange lists this filing as: {about[:400]}\nSummarise THAT item only, even if the PDF "
             "covers other decisions too.\n") if about else ""
    prompt = (f"Summarise this Indian stock-exchange filing ({category}) for an investor.\n" + focus +
              f"Facts to look for: {KEYTERM_HINTS.get(category, 'the key facts')}.\n"
              "Only use what the filing says; omit facts it doesn't state.")
    kt: KeyTerms = router.json(task=f"keyterms_{category}", tier="cheap", prompt=prompt, schema=KeyTerms,
                               pdf=pdf, max_tokens=800)
    out = kt.model_dump()
    if kt.quote and page_texts:
        m = verify_quote(kt.quote, page_texts)
        out["source"] = ({"page": m.page, "quote": m.quote, "paragraph": m.paragraph, "verified": True}
                         if m.found else {"verified": False})
    return out


class Line(BaseModel):
    id: str
    line: str


class Lines(BaseModel):
    lines: list[Line]


def oneliners(router, items: list[dict], batch: int = 15) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        listing = "\n".join(f'- id={it["id"]} | {it["symbol"]} | {it["subject"][:120]} | {it["text"][:500]}'
                            for it in chunk)
        prompt = ("For each Indian stock-exchange filing below, write one plain-English line (max 18 words) saying "
                  "what happened, including any number stated. Use only the given text; if it says nothing "
                  "specific, restate the subject plainly. No hype.\n" + listing)
        try:
            res: Lines = router.json(task="oneliners", tier="cheap", prompt=prompt, schema=Lines, max_tokens=2000)
            out.update({l.id: l.line for l in res.lines})
        except Exception as e:
            log.warning("one-liner batch failed: %s", e)
    return out
