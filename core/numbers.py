"""Number helpers: unit normalisation, growth maths, Indian digit grouping."""
from __future__ import annotations

import re

UNIT_TO_CRORE = {
    "crore": 1.0, "crores": 1.0, "cr": 1.0,
    "lakh": 0.01, "lakhs": 0.01, "lac": 0.01,
    "million": 0.1, "millions": 0.1, "mn": 0.1,
    "billion": 100.0, "bn": 100.0,
    "thousand": 1e-4, "thousands": 1e-4,
    "rupees": 1e-7, "inr": 1e-7,
}
# Table headers word the unit freely ("₹ in Crores", "(Rupees in Crores unless otherwise stated)", "in million",
# "Rs. in lakhs", "(₹ Mn)"), so find the scale word rather than matching the whole string. Order matters:
# "Rupees in Crores" is crore, and only a bare rupee header means rupees.
_UNIT_PATTERNS = [
    (re.compile(r"crore|(?<![a-z])crs?(?![a-z])"), 1.0),
    (re.compile(r"lakh|(?<![a-z])lacs?(?![a-z])"), 0.01),
    (re.compile(r"million|(?<![a-z])mn(?![a-z])|(?<![a-z])mio(?![a-z])"), 0.1),
    (re.compile(r"billion|(?<![a-z])bn(?![a-z])"), 100.0),
    (re.compile(r"thousand|(?<![a-z])'?000s?(?![a-z0-9])"), 1e-4),
    (re.compile(r"rupee|(?<![a-z])(?:inr|rs)(?![a-z])|₹"), 1e-7),
]


def unit_factor(unit: str | None) -> float | None:
    """Multiplier from the stated unit to ₹ crore, or None if the unit can't be recognised."""
    u = (unit or "").strip().lower()
    if not u:
        return None
    if u in UNIT_TO_CRORE:
        return UNIT_TO_CRORE[u]
    for pat, factor in _UNIT_PATTERNS:
        if pat.search(u):
            return factor
    return None


def to_crore(value: float | None, unit: str | None) -> float | None:
    """Convert to ₹ crore. An unrecognised unit is assumed to be crore; callers should check
    unit_factor() and flag the figure for verification in that case."""
    if value is None:
        return None
    factor = unit_factor(unit)
    return value * (1.0 if factor is None else factor)


def growth(cur: float | None, base: float | None) -> float | None:
    """Percentage change; None when undefined. Uses |base| so a loss shrinking reads as positive."""
    if cur is None or base is None or base == 0:
        return None
    return (cur - base) / abs(base) * 100.0


def margin(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def indian_group(n: float, decimals: int = 2) -> str:
    """12345678.9 -> '1,23,45,678.90' (Indian lakh/crore grouping)."""
    neg = n < 0
    s = f"{abs(n):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = whole + ("." + frac if decimals else "")
    return ("-" if neg else "") + out


def number_spellings(v: float) -> list[str]:
    """Ways a reported figure might be printed in a filing's text layer."""
    out = set()
    for d in (2, 1, 0):
        if d == 0 and abs(v - round(v)) > 1e-6:
            continue
        out.add(f"{abs(v):.{d}f}")
        out.add(f"{abs(v):,.{d}f}")
        out.add(indian_group(abs(v), d))
    return sorted(out, key=len, reverse=True)
