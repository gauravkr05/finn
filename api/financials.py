"""Numbers for the research view, parsed from screener.in tables. No model is involved here."""
from __future__ import annotations

import re

from core.numbers import growth
from core.screener import CompanyPage, Table


def _fy_headers(t: Table, n: int = 6) -> list[str]:
    hs = [h for h in t.headers if re.match(r"Mar \d{4}$", h)]
    return hs[-n:]


def _series(t: Table, headers: list[str], *aliases: str) -> list[float | None]:
    return [t.value(h, *aliases) for h in headers]


def _cagr(a: float | None, b: float | None, years: int) -> float | None:
    if a is None or b is None or a <= 0 or b <= 0 or years <= 0:
        return None
    return ((b / a) ** (1 / years) - 1) * 100


def _r(v, nd=1):
    return None if v is None else round(v, nd)


def build(page: CompanyPage) -> dict:
    an, bs, cf, rt, q = (page.tables[k] for k in ("annual", "balance", "cashflow", "ratios", "quarters"))
    lender = an.row("Financing Profit", "Financing Margin %") is not None
    years = _fy_headers(an)
    sales = _series(an, years, "Sales", "Revenue")
    op = _series(an, years, "Operating Profit", "Financing Profit")
    opm = _series(an, years, "OPM %", "Financing Margin %")
    pat = _series(an, years, "Net Profit")
    bs_years = [h for h in years if h in bs.headers]
    borrow = _series(bs, bs_years, "Borrowings", "Borrowing")
    equity = [((bs.value(h, "Equity Capital") or 0) + (bs.value(h, "Reserves") or 0)) or None for h in bs_years]
    cf_years = [h for h in years if h in cf.headers]
    cfo = _series(cf, cf_years, "Cash from Operating Activity", "Cash from Operating Activities")
    pat_cf = [an.value(h, "Net Profit") for h in cf_years]

    trajectory = {
        "years": years,
        "revenue": sales, "operating_profit": op, "opm": opm, "pat": pat,
        "revenue_cagr_3y": _r(_cagr(sales[-4], sales[-1], 3)) if len(sales) >= 4 else None,
        "pat_cagr_3y": _r(_cagr(pat[-4], pat[-1], 3)) if len(pat) >= 4 else None,
        "opm_change_3y_bps": (int(round((opm[-1] - opm[-4]) * 100))
                              if len(opm) >= 4 and opm[-1] is not None and opm[-4] is not None else None),
        "operating_label": "Financing profit" if lender else "Operating profit (EBITDA)",
    }
    tags = []
    if trajectory["revenue_cagr_3y"] is not None:
        tags.append({"label": "Revenue growing" if trajectory["revenue_cagr_3y"] > 8 else
                     "Revenue flat" if trajectory["revenue_cagr_3y"] > 0 else "Revenue shrinking",
                     "tone": "up" if trajectory["revenue_cagr_3y"] > 8 else "flat" if trajectory["revenue_cagr_3y"] > 0 else "down"})
    if trajectory["opm_change_3y_bps"] is not None and not lender:
        b = trajectory["opm_change_3y_bps"]
        tags.append({"label": "Margins expanding" if b > 100 else "Margins compressing" if b < -100 else "Margins stable",
                     "tone": "up" if b > 100 else "down" if b < -100 else "flat"})
    trajectory["tags"] = tags

    conv = [(_r(c / p * 100, 0) if c is not None and p not in (None, 0) and p > 0 else None)
            for c, p in zip(cfo, pat_cf)]
    last3 = [(c, p) for c, p in zip(cfo[-3:], pat_cf[-3:]) if c is not None and p is not None]
    cum = (sum(c for c, _ in last3) / sum(p for _, p in last3) * 100) if last3 and sum(p for _, p in last3) > 0 else None
    cash = {"years": cf_years, "cfo": cfo, "pat": pat_cf, "conversion_pct": conv, "cumulative_3y_pct": _r(cum, 0),
            "note": "Cash from operations as a share of net profit. Above 100% means profits turn into cash."}
    if lender:
        cash["note"] = ("For lenders, operating cash flow mostly reflects loan-book growth, so conversion "
                        "isn't a quality signal. Shown for completeness.")

    de = [(_r(b / e, 2) if b is not None and e else None) for b, e in zip(borrow, equity)]
    wc = {h: rt.value(h, "Working Capital Days") for h in rt.headers[-4:]} if rt.headers else {}
    ccc = {h: rt.value(h, "Cash Conversion Cycle") for h in rt.headers[-4:]} if rt.headers else {}
    balance = {"years": bs_years, "borrowings": borrow, "net_worth": equity, "debt_to_equity": de,
               "working_capital_days": wc, "cash_conversion_cycle": ccc}

    flags = []
    if cum is not None and cum < 70 and not lender:
        flags.append({"type": "cash_conversion", "severity": "warn",
                      "text": f"Only {cum:.0f}% of the last 3 years' profit turned into operating cash."})
    if len(de) >= 2 and de[-1] is not None and de[-2] is not None and de[-1] > 1 and de[-1] > de[-2] * 1.2 and not lender:
        flags.append({"type": "leverage", "severity": "warn",
                      "text": f"Debt-to-equity rose to {de[-1]:.2f} from {de[-2]:.2f}."})
    if trajectory["opm_change_3y_bps"] is not None and trajectory["opm_change_3y_bps"] < -300 and not lender:
        flags.append({"type": "margins", "severity": "warn",
                      "text": f"Operating margin is down {abs(trajectory['opm_change_3y_bps'])} bps over 3 years."})
    vals = [v for v in ccc.values() if v is not None]
    if len(vals) >= 2 and vals[-1] - vals[0] > 30 and not lender:
        flags.append({"type": "working_capital", "severity": "info",
                      "text": f"Cash conversion cycle lengthened by {vals[-1] - vals[0]:.0f} days."})

    qh = q.headers[-8:]
    quarters = {"headers": qh, "revenue": [q.value(h, "Sales", "Revenue") for h in qh],
                "opm": [q.value(h, "OPM %", "Financing Margin %") for h in qh],
                "pat": [q.value(h, "Net Profit") for h in qh]}

    latest = years[-1] if years else None
    snapshot = {
        "fy": latest,
        "revenue": sales[-1] if sales else None,
        "opm": opm[-1] if opm else None,
        "pat": pat[-1] if pat else None,
        "revenue_growth": _r(growth(sales[-1], sales[-2])) if len(sales) >= 2 else None,
        "pat_growth": _r(growth(pat[-1], pat[-2])) if len(pat) >= 2 else None,
        "debt_to_equity": de[-1] if de else None,
        "ratios": {k: v for k, v in page.ratios.items()
                   if k in ("Market Cap", "Current Price", "Stock P/E", "ROCE", "ROE", "Dividend Yield")},
    }
    return {"lender": lender, "snapshot": snapshot, "trajectory": trajectory, "cash": cash, "balance": balance,
            "quarters": quarters, "flags": flags,
            "source": {"label": f"screener.in ({page.basis})", "url": page.url}}
