"""Indian financial-year helpers. FY27 = April 2026 to March 2027."""
from __future__ import annotations

import re
from datetime import date

QUARTER_END_MONTH = {1: 6, 2: 9, 3: 12, 4: 3}
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def quarter_of_end(month: int, year: int) -> tuple[int, int]:
    """Quarter-end month/year -> (quarter number, FY end year). Sep 2026 -> (2, 2027)."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(month)
    if q is None:
        raise ValueError(f"not a quarter-end month: {month}")
    return q, (year + 1 if month in (6, 9, 12) else year)


def quarter_label(month: int, year: int) -> str:
    q, fy = quarter_of_end(month, year)
    return f"Q{q} FY{fy % 100:02d}"


def quarter_end_of(q: int, fy: int) -> tuple[int, int]:
    """(2, 2027) -> (9, 2026)."""
    m = QUARTER_END_MONTH[q]
    return m, (fy - 1 if m in (6, 9, 12) else fy)


def screener_header(month: int, year: int) -> str:
    return f"{MONTH_ABBR[month - 1]} {year}"


def call_to_quarter(month: int, year: int) -> tuple[int, int]:
    """An earnings call in Aug 2026 discusses the quarter ended Jun 2026. Returns quarter-end (month, year)."""
    if month in (4, 5, 6):
        return 3, year
    if month in (7, 8, 9):
        return 6, year
    if month in (10, 11, 12):
        return 9, year
    return 12, year - 1


def parse_period(text: str | None) -> dict | None:
    """'FY27' / 'FY2027' / 'Q3 FY27' / 'H2 FY27' -> {'kind': 'fy'|'quarter'|'half', 'fy': 2027, 'n': 3}."""
    if not text:
        return None
    t = text.upper().replace(" ", "")
    m = re.search(r"(Q[1-4]|H[12])?-?FY'?(\d{2,4})", t)
    if not m:
        return None
    fy = int(m.group(2))
    fy = fy + 2000 if fy < 100 else fy
    if m.group(1):
        kind = "quarter" if m.group(1)[0] == "Q" else "half"
        return {"kind": kind, "fy": fy, "n": int(m.group(1)[1])}
    return {"kind": "fy", "fy": fy, "n": None}


def fy_of(d: date) -> int:
    return d.year + 1 if d.month >= 4 else d.year
