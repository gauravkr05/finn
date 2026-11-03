"""The Promise Ledger: what management guided vs. what was delivered.

1. Extract: the cheap model lists forward-looking claims from each transcript's guidance chunks.
2. Verify: every quote must exist in the transcript (citation guardrail), else the claim is dropped.
3. Judge numerically in Python against reported numbers (screener.in tables). The model never
   decides whether a number was hit.
4. Judge qualitatively with evidence: the strong model looks for confirmation in LATER transcripts and
   must quote it; no verified quote, no verdict.
5. Drift: flag guidance for the same metric and period that changes between calls.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from core.guardrails import verify_quote
from core.llm import StrongUnavailable
from core.numbers import growth
from core.pdftext import format_chunks
from core.periods import parse_period, quarter_end_of, screener_header
from core.screener import CompanyPage

from .documents import Doc, guidance_chunks, verify_cited

log = logging.getLogger("finn.promises")

Metric = Literal["revenue_growth", "ebitda_margin", "ebit_margin", "pat_growth", "volume_growth", "capex", "debt",
                 "other"]
METRICS = {"revenue_growth", "ebitda_margin", "ebit_margin", "pat_growth", "volume_growth", "capex", "debt", "other"}
NUMERIC = {"revenue_growth", "ebitda_margin", "ebit_margin", "pat_growth", "debt"}
MARGINS = {"ebitda_margin", "ebit_margin"}

EXTRACT_PROMPT = """Below are excerpts from an Indian listed company's earnings-call transcript ({label}).
List management's FORWARD-LOOKING commitments and guidance: growth, margins, profit, capex, debt,
capacity, launches, store/plant openings, market share, etc. Only statements made BY MANAGEMENT count.
An analyst's question ("does the firm maintain its 40-45% guidance?") is not guidance: include it only if
management confirms it in the answer, and then quote management's answer, not the question.
Ignore statements about the past.

For each claim:
- metric: revenue_growth | ebitda_margin | ebit_margin | pat_growth | volume_growth | capex | debt | other
  (ebit_margin for EBIT / operating margin after depreciation, as IT services companies guide;
  ebitda_margin only when EBITDA is meant)
- statement: a short neutral paraphrase (max 15 words)
- target: type range/point/min/max/direction with numbers if stated. "double digit" = min 10.
  "mid-teens" = range 14-16. Margins in percent. Use unit "%" for growth/margins, "crore" for amounts.
  For "debt free" use type point, low 0, unit crore.
- period: the period the claim is for, as FY27 / Q3 FY27 / H2 FY27 (Indian FY: FY27 = Apr 2026-Mar 2027).
  null if not stated.
- scope: "company" if the guidance is for the whole company's consolidated numbers; "segment" if it is
  for a business line, product, geography, subsidiary or JV (then put its name in segment)
- quote: the exact sentence(s) from the excerpt, copied verbatim (max 40 words)
- page: the page number shown in the excerpt tag
- speaker: who said it

Only include clear commitments or guidance. At most 10 claims. Excerpts:

{chunks}"""


class Target(BaseModel):
    type: Literal["range", "point", "min", "max", "direction"]
    low: Optional[float] = None
    high: Optional[float] = None
    unit: Optional[str] = None
    direction: Optional[Literal["up", "down", "flat"]] = None


class Claim(BaseModel):
    metric: Metric
    statement: str
    target: Target
    scope: Literal["company", "segment"] = "company"
    segment: Optional[str] = None

    @field_validator("metric", mode="before")
    @classmethod
    def _known_metric(cls, v):  # the cheap model sometimes invents a metric name; keep the claim as "other"
        return v if v in METRICS else "other"

    @field_validator("scope", mode="before")
    @classmethod
    def _known_scope(cls, v):
        return v if v in ("company", "segment") else "segment"
    period: Optional[str] = None
    quote: str
    page: Optional[int] = None
    speaker: Optional[str] = None


class Claims(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class Followup(BaseModel):
    id: int
    verdict: Literal["kept", "partly", "missed", "pending"]
    reason: str = Field(description="max 20 words")
    evidence_quote: Optional[str] = Field(None, description="exact sentence from a LATER transcript")
    evidence_doc: Optional[str] = Field(None, description="label of the transcript the quote is from")


class Followups(BaseModel):
    results: list[Followup] = Field(default_factory=list)


# ------------------------------------------------------------------ extraction
def extract_claims(router, doc: Doc, threshold: float) -> tuple[list[dict], int]:
    """Returns (claims, dropped_uncited)."""
    if doc.scanned:
        prompt = EXTRACT_PROMPT.format(label=doc.label, chunks="(see attached PDF)")
        res = router.json(task="promise_extract", tier="cheap", prompt=prompt, schema=Claims, pdf=doc.pdf,
                          max_tokens=3000)
    else:
        chunks = guidance_chunks(doc)
        if not chunks:
            return [], 0
        prompt = EXTRACT_PROMPT.format(label=doc.label, chunks=format_chunks(chunks, doc.label))
        res = router.json(task="promise_extract", tier="cheap", prompt=prompt, schema=Claims, max_tokens=3000)
    out, dropped = [], 0
    for c in res.claims:
        d = c.model_dump()
        d.update({"said_in": doc.label, "said_quarter": doc.quarter, "doc_url": doc.url, "order": doc.order})
        if doc.scanned:
            d["source"] = {"doc": doc.label, "page": c.page, "verified": False,
                           "note": "Scanned transcript: quote could not be checked."}
        else:
            m = verify_quote(c.quote, doc.pages, threshold, hint_page=c.page)
            if not m.found:
                dropped += 1
                continue
            d["source"] = {"doc": doc.label, "url": doc.url, "page": m.page, "quote": m.quote,
                           "paragraph": m.paragraph, "verified": True}
        out.append(d)
    return out, dropped


# ------------------------------------------------------------------ delivered numbers
def _qheaders_for_fy(fy: int) -> list[str]:
    return [screener_header(*quarter_end_of(q, fy)) for q in (1, 2, 3, 4)]


def delivered(page: CompanyPage, metric: str, period: dict | None) -> dict:
    an, q, bs = page.tables["annual"], page.tables["quarters"], page.tables["balance"]
    sales, opm, op, np_ = ("Sales", "Revenue"), ("OPM %", "Financing Margin %"), \
        ("Operating Profit", "Financing Profit"), ("Net Profit",)
    dep = ("Depreciation",)
    name = "EBIT margin" if metric == "ebit_margin" else "Operating margin"

    def margin_of(get) -> float | None:
        """EBITDA-style (screener's operating profit) or EBIT margin = (operating profit - depreciation) / sales."""
        o, s_ = get(op), get(sales)
        if o is None or not s_:
            return None
        if metric == "ebit_margin":
            d = get(dep)
            if d is None:
                return None
            o -= d
        return round(o / s_ * 100, 1)
    if period is None:
        return {"status": "unknown_period"}
    fy, kind, n = period["fy"], period["kind"], period["n"]

    def sum_q(headers, aliases):
        vals = [q.value(h, *aliases) for h in headers]
        return None if any(v is None for v in vals) else sum(vals)

    if kind == "fy":
        h, h0 = f"Mar {fy}", f"Mar {fy - 1}"
        if metric == "debt":
            cur, prev = bs.value(h, "Borrowings"), bs.value(h0, "Borrowings")
            if cur is None:
                return {"status": "pending"}
            return {"status": "reported", "value": cur, "prev": prev, "unit": "crore",
                    "label": f"Borrowings, {h}", "source": "screener.in balance sheet"}
        if h in an.headers and an.value(h, *sales) is not None:
            if metric in MARGINS:
                v = margin_of(lambda al: an.value(h, *al))
                prev = margin_of(lambda al: an.value(h0, *al)) if h0 in an.headers else None
                return {"status": "reported", "value": v, "prev": prev, "unit": "%",
                        "label": f"{name} FY{fy % 100}", "source": "screener.in annual P&L"}
            aliases = sales if metric == "revenue_growth" else np_
            v = growth(an.value(h, *aliases), an.value(h0, *aliases))
            return {"status": "reported", "value": None if v is None else round(v, 1), "unit": "%",
                    "label": f"{'Revenue' if metric == 'revenue_growth' else 'PAT'} growth FY{fy % 100}",
                    "source": "screener.in annual P&L"}
        # year not finished: track year-to-date
        cur_h = [x for x in _qheaders_for_fy(fy) if x in q.headers]
        if not cur_h:
            return {"status": "pending"}
        prev_h = [screener_header(*_shift_year(x)) for x in cur_h]
        if metric in MARGINS:
            ytd = margin_of(lambda al: sum_q(cur_h, al))
        elif metric in ("revenue_growth", "pat_growth"):
            aliases = sales if metric == "revenue_growth" else np_
            ytd = growth(sum_q(cur_h, aliases), sum_q(prev_h, aliases)) if all(h in q.headers for h in prev_h) else None
        else:
            ytd = None
        return {"status": "pending", "tracking": None if ytd is None else round(ytd, 1),
                "tracking_label": f"{len(cur_h)} of 4 quarters reported"}

    hs = ([screener_header(*quarter_end_of(n, fy))] if kind == "quarter"
          else [screener_header(*quarter_end_of(x, fy)) for x in ((1, 2) if n == 1 else (3, 4))])
    if not all(h in q.headers for h in hs):
        return {"status": "pending"}
    label = f"{'Q' if kind == 'quarter' else 'H'}{n} FY{fy % 100}"
    if metric in MARGINS:
        return {"status": "reported", "value": margin_of(lambda al: sum_q(hs, al)), "unit": "%",
                "label": f"{name} {label}", "source": "screener.in quarterly results"}
    if metric in ("revenue_growth", "pat_growth"):
        aliases = sales if metric == "revenue_growth" else np_
        prev = [screener_header(*_shift_year(h)) for h in hs]
        if not all(h in q.headers for h in prev):
            return {"status": "unknown_period"}
        v = growth(sum_q(hs, aliases), sum_q(prev, aliases))
        return {"status": "reported", "value": None if v is None else round(v, 1), "unit": "%",
                "label": f"{'Revenue' if metric == 'revenue_growth' else 'PAT'} growth {label} YoY",
                "source": "screener.in quarterly results"}
    return {"status": "unknown_period"}


def delivered_amount(page: CompanyPage, metric: str, period: dict | None) -> dict:
    """Absolute revenue / PAT in ₹ crore for an amount target ("revenue of ₹56,000 crore in FY27")."""
    an, q = page.tables["annual"], page.tables["quarters"]
    aliases = ("Sales", "Revenue") if metric == "revenue_growth" else ("Net Profit",)
    name = "Revenue" if metric == "revenue_growth" else "PAT"
    if period is None:
        return {"status": "unknown_period"}
    fy, kind, n = period["fy"], period["kind"], period["n"]
    if kind == "fy":
        v = an.value(f"Mar {fy}", *aliases)
        if v is None:
            return {"status": "pending"}
        return {"status": "reported", "value": v, "unit": "crore", "label": f"{name} FY{fy % 100}",
                "source": "screener.in annual P&L"}
    hs = ([screener_header(*quarter_end_of(n, fy))] if kind == "quarter"
          else [screener_header(*quarter_end_of(x, fy)) for x in ((1, 2) if n == 1 else (3, 4))])
    vals = [q.value(h, *aliases) for h in hs]
    if any(v is None for v in vals):
        return {"status": "pending"}
    label = f"{'Q' if kind == 'quarter' else 'H'}{n} FY{fy % 100}"
    return {"status": "reported", "value": sum(vals), "unit": "crore", "label": f"{name} {label}",
            "source": "screener.in quarterly results"}


def _shift_year(header: str) -> tuple[int, int]:
    mon, yr = header.split()
    from core.periods import MONTH_ABBR

    return MONTH_ABBR.index(mon) + 1, int(yr) - 1


# ------------------------------------------------------------------ judging
def judge(claim: dict, d: dict, band_rel: float, band_pts: float) -> tuple[str, str]:
    """Returns (verdict, reason). Pure function: tested."""
    t = claim["target"]
    if d.get("status") == "pending":
        tr = d.get("tracking")
        return "pending", (f"Period not complete; tracking {tr}% ({d['tracking_label']})" if tr is not None
                           else "Target period not reported yet")
    if d.get("status") != "reported" or d.get("value") is None:
        return "unjudged", "Couldn't match this to reported numbers"
    v = d["value"]
    if claim["metric"] == "debt":
        if t["type"] == "point" and (t.get("low") or 0) == 0:
            return ("kept", f"Borrowings ₹{v:,.0f} cr") if v <= 5 else ("missed", f"Borrowings still ₹{v:,.0f} cr")
        if t["type"] == "direction" and d.get("prev") is not None:
            ok = v < d["prev"] if t.get("direction") == "down" else v > d["prev"]
            return ("kept" if ok else "missed"), f"Borrowings ₹{d['prev']:,.0f} cr → ₹{v:,.0f} cr"
    if t["type"] == "direction":
        base = d.get("prev")
        if claim["metric"] in MARGINS and base is not None:
            ok = v > base if t.get("direction") == "up" else v < base if t.get("direction") == "down" else abs(v - base) < 1
            return ("kept" if ok else "missed"), f"{d['label']}: {v}% vs {base}% a year earlier"
        if t.get("direction") == "up":
            return ("kept" if v > 0 else "missed"), f"{d['label']}: {v}%"
        return "unjudged", "Direction-only guidance"
    low = t.get("low") if t.get("low") is not None else t.get("high")
    high = t.get("high")
    amount = d.get("unit") == "crore"
    fmt = (lambda x: f"₹{x:,.0f} cr") if amount else (lambda x: f"{x:g}%")
    if t["type"] == "max":
        if high is None:
            return "unjudged", "No number in the guidance"
        return ("kept" if v <= high else "missed"), f"{d['label']}: {fmt(v)} vs at most {fmt(high)}"
    if low is None:
        return "unjudged", "No number in the guidance"
    margin_like = claim["metric"] in MARGINS
    target_txt = f"{fmt(low)}–{fmt(high)}" if (high is not None and high != low) else fmt(low)
    if v >= low:
        return "kept", f"{d['label']}: {fmt(v)} vs guided {target_txt}"
    near = (v >= low - band_pts) if margin_like else (low > 0 and v >= low * (1 - band_rel))
    return ("partly" if near else "missed"), f"{d['label']}: {fmt(v)} vs guided {target_txt}"


_PCT_UNITS = {None, "", "%", "percent", "per cent", "pct"}
_CRORE_UNITS = {"crore", "crores", "cr", "₹ crore", "inr crore", "rs crore"}


def comparable(claim: dict) -> str | None:
    """How Python can compare this claim with screener.in's company-level numbers, or None if it can't
    (segment guidance, volumes, unusual units): those go to the qualitative follow-up instead."""
    if claim["metric"] not in NUMERIC or claim.get("scope", "company") != "company":
        return None
    unit = (claim["target"].get("unit") or "").strip().lower() or None
    if claim["metric"] == "debt":
        return "amount" if unit in _CRORE_UNITS | {None} else None
    if unit in _PCT_UNITS:
        return "pct"
    if claim["metric"] in ("revenue_growth", "pat_growth"):
        if unit in ("x", "times"):
            return "multiple"
        if unit in _CRORE_UNITS:
            return "amount"
    return None


def _as_growth_pct(target: dict) -> dict:
    """"3x" -> +200% growth."""
    conv = lambda v: None if v is None else round((v - 1) * 100, 1)
    return {**target, "low": conv(target.get("low")), "high": conv(target.get("high")), "unit": "%"}


def judge_all(page: CompanyPage, claims: list[dict], cfg: dict) -> None:
    for c in claims:
        mode = comparable(c)
        if mode is None:
            c["verdict"], c["reason"], c["judged_by"] = "unjudged", "", "pending-qualitative"
            continue
        period = parse_period(c.get("period"))
        if period is None and c.get("order") and tuple(c["order"]) != (0, 0):
            # Unstated period: the financial year in progress on the call date. A Q4 FY26 call happens in
            # May 2026, when FY26 is already over, so its forward guidance is for FY27.
            y, m = tuple(c["order"])
            period = {"kind": "fy", "fy": y + 1 if m >= 4 else y, "n": None}
            c["period_assumed"] = True
        elif period is None and c.get("said_quarter"):
            fy = parse_period(c["said_quarter"])
            period = {"kind": "fy", "fy": fy["fy"], "n": None} if fy else None
            c["period_assumed"] = True
        if mode == "amount" and c["metric"] != "debt":
            d = delivered_amount(page, c["metric"], period)
        else:
            d = delivered(page, c["metric"], period)
        c["delivered"] = d
        judged = {**c, "target": _as_growth_pct(c["target"])} if mode == "multiple" else c
        c["verdict"], c["reason"] = judge(judged, d, cfg["partly_band_relative"], cfg["partly_band_points"])
        c["judged_by"] = "python"


UNCHECKED_REASON = "Not checked today: model limit reached"
UNAVAILABLE_REASON = "Not checked today: model unavailable"


def qualitative(router, claims: list[dict], docs: list[Doc], threshold: float, limit: int) -> bool:
    """Returns False if the strong model was unavailable and the claims were left unchecked."""
    usable = [d for d in docs if not d.scanned]
    has_later = lambda c: any(d.order > tuple(c["order"]) for d in usable)
    for c in claims:  # nothing after the latest call to check against: don't spend a model slot on it
        if c["verdict"] == "unjudged" and not has_later(c):
            c["verdict"], c["reason"], c["judged_by"] = "pending", "Said in the latest call; nothing later to check yet", "none"
    todo = sorted((c for c in claims if c["verdict"] == "unjudged"), key=lambda c: tuple(c["order"]))[:limit]
    if not todo:
        return True
    later_text = []
    for c in todo:
        later = [d for d in docs if d.order > tuple(c["order"]) and not d.scanned]
        words = {w for w in c["statement"].lower().split() if len(w) > 4}
        picked = []
        for d in later:
            scored = sorted(d.chunks, key=lambda ch: -sum(ch.text.lower().count(w) for w in words))[:2]
            picked += [(d, ch) for ch in scored]
        c["_later"] = picked
        later_text.append(picked)
    listing = []
    for i, c in enumerate(todo):
        ev = "\n".join(f"  [{d.label} p.{ch.page}] {ch.text[:1200]}" for d, ch in c["_later"]) or "  (no later calls)"
        listing.append(f"Claim {i} (said in {c['said_in']}): {c['statement']} | quote: \"{c['quote']}\"\n"
                       f"Later excerpts:\n{ev}")
    prompt = ("You check whether management delivered on past commitments, using ONLY the later transcript excerpts. "
              "For each claim give a verdict: kept, partly, missed, or pending (if the excerpts don't settle it).\n"
              "Rules:\n"
              "- kept/partly/missed need an actual OUTCOME for the SAME metric and the SAME period the claim was "
              "about (e.g. a full-year FY26 target needs the FY26 figure, not one later quarter).\n"
              "- Repeating, reiterating or 'remaining on track' for a target is NOT delivery: that is pending.\n"
              "- A deadline that later calls push back (e.g. 'by April' becomes 'by Q2') is missed.\n"
              "- Any verdict other than pending MUST include evidence_quote copied exactly from a later excerpt and "
              "evidence_doc naming it.\n\n" + "\n\n".join(listing))
    try:
        # Judging delivery needs the strong model; a weaker model judged reiterations as "kept".
        res = router.json(task="promise_followup", tier="strong", prompt=prompt, schema=Followups, max_tokens=2500,
                          allow_fallback=False)
    except Exception as e:  # quota, overload (503) or truncated output: leave unchecked, never guess
        log.warning("qualitative follow-up skipped: %s", e)
        reason = UNCHECKED_REASON if isinstance(e, StrongUnavailable) else UNAVAILABLE_REASON
        for c in claims:
            c.pop("_later", None)
            if c["verdict"] == "unjudged":
                c["verdict"], c["reason"], c["judged_by"] = "unchecked", reason, "none"
        return False
    got = {r.id: r for r in res.results}
    for i, c in enumerate(todo):
        c.pop("_later", None)
        r = got.get(i)
        c["judged_by"] = "model+evidence"
        if not r or r.verdict == "pending" or not r.evidence_quote:
            c["verdict"] = "pending"
            c["reason"] = (r.reason if r and r.reason else "No follow-up found in later calls")
            continue
        later_docs = [d for d in docs if d.order > tuple(c["order"])]
        doc, m = verify_cited(r.evidence_quote, r.evidence_doc, later_docs, threshold)
        if not doc:
            c["verdict"], c["reason"] = "pending", "No verifiable follow-up in later calls"
            continue
        c["verdict"], c["reason"] = r.verdict, r.reason
        c["evidence"] = {"doc": doc.label, "url": doc.url, "page": m.page, "quote": m.quote, "paragraph": m.paragraph}
    for c in claims:
        c.pop("_later", None)
    return True


def drift(claims: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for c in claims:
        p = parse_period(c.get("period"))
        if comparable(c) is None or not p or c["target"].get("low") is None:
            continue  # segment guidance and mixed units would show fake "drift"
        unit = (c["target"].get("unit") or "%").strip().lower()
        groups.setdefault((c["metric"], p["kind"], p["fy"], p["n"], unit), []).append(c)
    out = []
    for (metric, kind, fy, n, _unit), cs in groups.items():
        cs = sorted(cs, key=lambda c: tuple(c["order"]))
        hist = [{"said_in": c["said_in"], "low": c["target"].get("low"), "high": c["target"].get("high")} for c in cs]
        distinct = {(h["low"], h["high"]) for h in hist}
        if len(cs) >= 2 and len(distinct) >= 2:
            first, last = hist[0]["low"], hist[-1]["low"]
            out.append({"metric": metric, "period": cs[0].get("period"), "history": hist,
                        "direction": "lowered" if last < first else "raised" if last > first else "reshaped"})
    return out
