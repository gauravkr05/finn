"""Results card.

The model reads the results PDF (sent as bytes: filings are often scanned or use complex tables).
Python does all arithmetic and all validation:

    EBITDA = PBT before exceptional items + finance costs + depreciation - other income

One-off exceptional items are flagged (never "adjusted away"), accounting identities are checked,
each figure is looked up in the PDF's text layer when one exists, and the latest quarter's revenue
is cross-checked against screener.in. Anything that fails is marked "verify in filing".
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.numbers import growth, margin, number_spellings, to_crore, unit_factor
from core.periods import quarter_label, screener_header

log = logging.getLogger("finn.results")

PROMPT = """You are reading an Indian listed company's quarterly financial results filing.

Extract the QUARTERLY figures (not half-year, nine-month or full-year columns) for three columns:
- current: the latest "quarter ended"
- prev_quarter: the immediately preceding quarter
- year_ago: the same quarter one year earlier

Rules:
- Prefer the CONSOLIDATED statement if the filing has one; otherwise standalone. Report which.
- Copy numbers exactly as printed, in the unit stated in the table header (e.g. "₹ in crore", "Rs. in lakhs").
  Do not convert units. Report the unit.
- Losses and expenses that reduce profit are negative only where the filing shows them as negative.
- exceptional_items: as it affects profit (a gain is positive, a loss/impairment is negative). null if none.
- pbt_before_exceptional: "Profit before exceptional items and tax". If the filing has no exceptional
  items line, set it equal to pbt.
- pat: "Net profit for the period" (before other comprehensive income).
- excise_duty: the "Excise duty" line if the filing shows it under expenses (common for tobacco, alcohol,
  fuel). revenue stays "Revenue from operations" as printed (gross); do not subtract it yourself.
- For banks and NBFCs also fill interest_earned, interest_expended, provisions (provisions and
  contingencies / impairment on financial instruments) and set company_type to "lender".
- page: the 1-based PDF page where the main results table is.
- period_end: the current quarter's end date as YYYY-MM-DD.
- Use null for anything not present. Never estimate."""


class Period(BaseModel):
    revenue: Optional[float] = Field(None, description="Revenue from operations")
    excise_duty: Optional[float] = Field(None, description="Excise duty shown as an expense line, if any")
    other_income: Optional[float] = None
    total_income: Optional[float] = None
    finance_costs: Optional[float] = None
    depreciation: Optional[float] = None
    pbt_before_exceptional: Optional[float] = None
    exceptional_items: Optional[float] = None
    pbt: Optional[float] = None
    tax: Optional[float] = None
    pat: Optional[float] = None
    interest_earned: Optional[float] = None
    interest_expended: Optional[float] = None
    provisions: Optional[float] = None


class ResultsExtract(BaseModel):
    basis: Literal["consolidated", "standalone"]
    unit: str = Field(description="unit in the table header, e.g. crore, lakh, million")
    company_type: Literal["lender", "non_lender"] = "non_lender"
    period_end: Optional[str] = None
    page: Optional[int] = None
    current: Period
    prev_quarter: Optional[Period] = None
    year_ago: Optional[Period] = None


COLS = ("current", "prev_quarter", "year_ago")


def _get(ex: ResultsExtract, col: str, field: str) -> float | None:
    p = getattr(ex, col)
    return getattr(p, field) if p is not None else None


def _cr(ex: ResultsExtract, col: str, field: str) -> float | None:
    return to_crore(_get(ex, col, field), ex.unit)


def compute(ex: ResultsExtract, kind: str | None = None, page_texts: list[str] | None = None,
            screener_revenue: dict[str, float] | None = None) -> dict:
    lender = kind == "lender" or ex.company_type == "lender"
    vals: dict[str, dict[str, float | None]] = {}
    for col in COLS:
        pbt = _cr(ex, col, "pbt")
        exc = _cr(ex, col, "exceptional_items")
        pbt_pre = _cr(ex, col, "pbt_before_exceptional")
        if exc and pbt is not None and pbt_pre is not None:
            # Filings often print "PBT = VII - VIII" with a gain shown as "(51)", so the model copies the
            # printed sign. Normalise to "as it affects profit" when only the flipped sign fits the identity.
            tol = max(0.5, abs(pbt) * 0.01)
            if abs(pbt_pre + exc - pbt) > tol and abs(pbt_pre - exc - pbt) <= tol:
                exc = -exc
        if pbt_pre is None and pbt is not None:
            pbt_pre = pbt - exc if exc is not None else pbt
        revenue, excise = _cr(ex, col, "revenue"), _cr(ex, col, "excise_duty")
        if revenue is not None and excise:
            # Revenue from operations includes excise collected for the government; screener.in and analysts
            # use it net of excise, otherwise an excise change reads as growth (ITC Q2 FY27: +44% gross, +4% net).
            revenue = revenue - abs(excise)
        v: dict[str, float | None] = {
            "revenue": revenue, "other_income": _cr(ex, col, "other_income"),
            "total_income": _cr(ex, col, "total_income"), "finance_costs": _cr(ex, col, "finance_costs"),
            "depreciation": _cr(ex, col, "depreciation"), "pbt_pre": pbt_pre, "exceptional": exc, "pbt": pbt,
            "tax": _cr(ex, col, "tax"), "pat": _cr(ex, col, "pat"), "provisions": _cr(ex, col, "provisions"),
        }
        if lender:
            if v["total_income"] is None and v["revenue"] is not None:
                v["total_income"] = v["revenue"] + (v["other_income"] or 0)
            v["ppop"] = (pbt_pre + v["provisions"]) if (pbt_pre is not None and v["provisions"] is not None) else None
        else:
            parts = [pbt_pre, v["finance_costs"], v["depreciation"], v["other_income"]]
            v["ebitda"] = (pbt_pre + v["finance_costs"] + v["depreciation"] - v["other_income"]
                           if all(x is not None for x in parts) else None)
        vals[col] = v

    # ---- checks on the current quarter ----
    cur = vals["current"]
    checks: dict[str, bool | None] = {}
    verify: set[str] = set()
    pbt, tax, pat = cur["pbt"], cur["tax"], cur["pat"]
    if pbt is not None and pat is not None:
        checks["pat_le_pbt"] = pat <= pbt + max(0.5, abs(pbt) * 0.01) or (tax is not None and tax < 0)
        if not checks["pat_le_pbt"]:
            verify.add("PAT")
    if pbt is not None and tax is not None and pat is not None:
        checks["tax_identity"] = abs(pbt - tax - pat) <= max(0.5, abs(pbt) * 0.02)
        if not checks["tax_identity"]:
            verify.add("PAT")
    if cur["pbt_pre"] is not None and cur["exceptional"] is not None and pbt is not None:
        checks["exceptional_identity"] = abs(cur["pbt_pre"] + cur["exceptional"] - pbt) <= max(0.5, abs(pbt) * 0.01)
        if not checks["exceptional_identity"]:
            verify.add("PBT")
    if unit_factor(ex.unit) is None:  # don't silently treat an unknown unit as crore
        checks["unit_recognised"] = False
        verify.update({"Revenue", "Total income", "PBT", "PAT"})
    top_metric = "total_income" if lender else "revenue"
    if screener_revenue and ex.period_end:
        try:
            d = date.fromisoformat(ex.period_end)
            ref = screener_revenue.get(screener_header(d.month, d.year))
            if ref and cur[top_metric]:
                checks["cross_check_screener"] = abs(cur[top_metric] - ref) <= max(1.0, abs(ref) * 0.03)
                if not checks["cross_check_screener"]:
                    verify.add("Total income" if lender else "Revenue")
        except ValueError:
            pass

    # ---- numeric provenance in the PDF text layer ----
    provenance: dict[str, int | None] = {}
    if page_texts and any(t.strip() for t in page_texts):
        compact = [t.replace(" ", "") for t in page_texts]
        # Look on the results-table page the model reported first, so a press release quoting the
        # same rounded figure doesn't become the cited page.
        order = list(range(len(compact)))
        if ex.page and 1 <= ex.page <= len(compact):
            order.remove(ex.page - 1)
            order.insert(0, ex.page - 1)
        for field in ("revenue", "pbt", "pat", "total_income"):
            raw = _get(ex, "current", field)
            if raw is None:
                continue
            provenance[field] = next((i + 1 for i in order
                                      if any(s in compact[i] for s in number_spellings(raw))), None)
        checks["found_in_text_layer"] = bool(provenance) and all(v is not None for v in provenance.values())

    # ---- rows ----
    def row(metric: str, key: str, verify_name: str | None = None) -> dict:
        c, q, y = (vals[col].get(key) for col in COLS)
        r = {"metric": metric, "cur": _round(c), "prev_q": _round(q), "prev_y": _round(y),
             "qoq": _round(growth(c, q), 1), "yoy": _round(growth(c, y), 1)}
        if (verify_name or metric) in verify:
            r["verify"] = True
        return r

    if lender:
        rows = [row("Total income", "total_income"), row("Pre-provision profit", "ppop"),
                row("PBT", "pbt"), row("PAT", "pat")]
        note = "Lender: EBITDA isn't meaningful for banks and NBFCs, so the card shows total income and pre-provision operating profit."
    else:
        net = _get(ex, "current", "excise_duty")
        rows = [row("Revenue", "revenue"), row("EBITDA", "ebitda"), row("PBT", "pbt"), row("PAT", "pat")]
        if net:
            rows[0]["net_of_excise"] = True
        note = "EBITDA = PBT before exceptional items + finance costs + depreciation − other income."
        if net:
            note += " Revenue is shown net of excise duty, as reported in the filing's expenses."

    margins = {}
    if not lender:
        m = {col: margin(vals[col].get("ebitda"), vals[col]["revenue"]) for col in COLS}
        if m["current"] is not None:
            margins = {"ebitda_margin": _round(m["current"], 1),
                       "qoq_bps": _bps(m["current"], m["prev_quarter"]),
                       "yoy_bps": _bps(m["current"], m["year_ago"])}

    flags = []
    exc, pre = cur["exceptional"], cur["pbt_pre"]
    if exc and pre and abs(exc) > 0.05 * abs(pre):
        kind_word = "gain" if exc > 0 else "charge"
        flags.append({"type": "exceptional", "severity": "warn",
                      "text": f"Includes ₹{abs(exc):,.0f} cr one-off {kind_word}",
                      "pbt_before": _round(pre), "pbt_after": _round(pbt)})

    label = None
    if ex.period_end:
        try:
            d = date.fromisoformat(ex.period_end)
            label = quarter_label(d.month, d.year)
        except ValueError:
            pass
    return {
        "basis": ex.basis, "unit": "₹ crore", "lender": lender, "period": label,
        "rows": rows, "margins": margins, "flags": flags, "checks": checks,
        "provenance": provenance, "page": ex.page, "note": note,
    }


def _round(v: float | None, nd: int = 1) -> float | None:
    return None if v is None else round(v, nd)


def _bps(a: float | None, b: float | None) -> int | None:
    return None if a is None or b is None else int(round((a - b) * 100))


def extract(router, pdf: bytes) -> ResultsExtract:
    return router.json(task="results_extract", tier="cheap", prompt=PROMPT, schema=ResultsExtract, pdf=pdf,
                       max_tokens=3000)
