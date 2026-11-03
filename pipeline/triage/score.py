"""Layer 4: materiality score and tier. Simple, explainable, and shown to the investor."""
from __future__ import annotations

import re
from datetime import datetime

from core.config import load_config

SUBTYPE_MOD = {
    ("results", "final"): 1.0, ("results", "deck"): 0.35, ("results", "intimation"): 0.08, ("results", "ad"): 0.05,
    ("results", "press"): 0.35,
    ("earnings_call", "transcript"): 1.0, ("earnings_call", "recording"): 0.3, ("earnings_call", "intimation"): 0.3,
    ("credit_rating", "upgrade"): 0.75, ("credit_rating", "downgrade"): 1.4, ("credit_rating", "reaffirm"): 0.35,
    ("M&A", "incorporation"): 0.15,   # new subsidiary / nominal investment: M&A on paper, rarely material
    ("M&A", "strike_off"): 0.15,
    ("fund_raise", "guarantee"): 0.3,  # guarantee / comfort letter for a group company's borrowing      # striking off / dissolving a (usually dormant) subsidiary
}
ROLE_MOD = {"top": 1.5, "kmp": 0.55, "director": 0.5, "independent": 0.2, "secretarial": 0.15}
ROLE_LABEL = {"top": "CEO/CFO/MD level", "kmp": "senior management", "director": "board member",
              "independent": "independent director", "secretarial": "company secretary"}
CATEGORY_LABEL = {
    "results": "Results", "M&A": "M&A", "fund_raise": "Fund raise", "management_change": "Management change",
    "litigation": "Litigation", "insider_trading": "Insider trade", "earnings_call": "Earnings call",
    "investor_meetings": "Investor meeting", "credit_rating": "Credit rating", "dividend": "Dividend",
    "bonus_split": "Bonus/split", "capex": "Capex", "press_release": "Press release",
    "postal_ballot": "Postal ballot", "agm_egm": "AGM/EGM", "pledging": "Pledging", "unclassified": "Routine filing",
}
SIZE_SENSITIVE = {"M&A", "litigation", "capex", "fund_raise", "press_release"}

_NUM = r"([\d,]+(?:\.\d+)?)"
_SCALE = r"(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn|thousand)?"
# Currency markers -> ISO code. Longer alternatives first so "us$" wins over "$".
_CUR_PREFIX = {
    "rs.": "INR", "rs": "INR", "inr": "INR", "₹": "INR",
    "us$": "USD", "usd": "USD", "$": "USD", "eur": "EUR", "€": "EUR", "gbp": "GBP", "£": "GBP",
    "c$": "CAD", "cad": "CAD", "aed": "AED", "s$": "SGD", "sgd": "SGD", "a$": "AUD", "aud": "AUD",
    "jpy": "JPY", "¥": "JPY", "chf": "CHF", "cny": "CNY", "rmb": "CNY", "hkd": "HKD", "sar": "SAR",
    "qar": "QAR", "myr": "MYR", "zar": "ZAR", "nzd": "NZD", "sek": "SEK", "nok": "NOK", "dkk": "DKK",
}
_CUR_SUFFIX = {
    "canadian dollars": "CAD", "canadian dollar": "CAD", "us dollars": "USD", "us dollar": "USD",
    "u.s. dollars": "USD", "singapore dollars": "SGD", "singapore dollar": "SGD", "australian dollars": "AUD",
    "australian dollar": "AUD", "hong kong dollars": "HKD", "dollars": "USD", "dollar": "USD", "euros": "EUR",
    "euro": "EUR", "pounds sterling": "GBP", "sterling": "GBP", "dirhams": "AED", "dirham": "AED", "yen": "JPY",
    "swiss francs": "CHF", "rupees": "INR",
    **{k: v for k, v in _CUR_PREFIX.items() if k.isalpha() and len(k) == 3},
}


def _alts(keys) -> str:
    return "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))


_AMOUNT_PRE = re.compile(r"(?<![a-z])(" + _alts(_CUR_PREFIX) + r")\s*" + _NUM + r"\s*" + _SCALE + r"(?![a-z])", re.I)
_AMOUNT_POST = re.compile(_NUM + r"\s*" + _SCALE + r"\s*(" + _alts(_CUR_SUFFIX) + r")(?![a-z])", re.I)
_SCALE_UNITS = {"crore": 1e7, "lakh": 1e5, "million": 1e6, "billion": 1e9, "thousand": 1e3}


def _scale_name(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.lower().rstrip(".")
    return {"crores": "crore", "cr": "crore", "lakhs": "lakh", "lacs": "lakh", "lac": "lakh", "mn": "million",
            "bn": "billion"}.get(s, s)


def stated_amount_crore(text: str, fx_to_inr: dict[str, float] | None = None) -> float | None:
    """Largest money amount mentioned in the text, in ₹ crore. Foreign currencies are converted at the
    rough fixed rates in config.yaml (brief.fx_to_inr); it only needs to be right to an order of magnitude."""
    if fx_to_inr is None:
        fx_to_inr = load_config().get("brief", {}).get("fx_to_inr", {})
    hits: list[tuple[str, str | None, str]] = []
    for m in _AMOUNT_PRE.finditer(text or ""):
        hits.append((m.group(2), m.group(3), _CUR_PREFIX[m.group(1).lower()]))
    for m in _AMOUNT_POST.finditer(text or ""):
        hits.append((m.group(1), m.group(2), _CUR_SUFFIX[m.group(3).lower()]))
    best = None
    for num, scale, cur in hits:
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        rate = 1.0 if cur == "INR" else fx_to_inr.get(cur)
        if rate is None:
            continue
        cr = v * _SCALE_UNITS.get(_scale_name(scale) or "", 1.0) * float(rate) / 1e7
        if best is None or cr > best:
            best = cr
    return best


def size_modifier(category: str, amount_cr: float | None, mcap_cr: float | None) -> tuple[float, str | None]:
    if category not in SIZE_SENSITIVE or amount_cr is None:
        return 1.0, None
    if mcap_cr:
        share = amount_cr / mcap_cr * 100
        amt = f"₹{amount_cr:,.2f} cr" if amount_cr < 10 else f"₹{amount_cr:,.0f} cr"
        note = f"{amt}, {share:.2f}% of market cap" if share < 0.1 else f"{amt}, {share:.1f}% of market cap"
        if share >= 5:
            return 1.4, note
        if share >= 1:
            return 1.15, note
        if share < 0.01:
            return 0.15, note
        if share < 0.1:
            return 0.45, note
        return 1.0, note
    note = f"₹{amount_cr:,.2f} cr" if amount_cr < 10 else f"₹{amount_cr:,.0f} cr"
    return (0.15, note) if amount_cr < 1 else (0.45, note) if amount_cr < 10 else (1.0, note)


def score_item(item: dict, cls: dict, cfg: dict, weight: float, followed: set[str],
               window_end: datetime, mcap_cr: float | None = None) -> dict:
    tri = cfg["triage"]
    cat = cls["category"]
    base = float(tri["base_weights"].get(cat, 0.2))
    mods: dict[str, float] = {}
    reasons: list[str] = []

    sub = SUBTYPE_MOD.get((cat, cls.get("subtype")))
    if sub is not None:
        mods["subtype"] = sub
    if cat == "management_change" and cls.get("role"):
        mods["role"] = ROLE_MOD.get(cls["role"], 0.5)
        reasons.append(ROLE_LABEL.get(cls["role"], "management"))
    direction = cls.get("direction")
    if direction == "negative" and cat in ("management_change", "pledging", "insider_trading", "credit_rating"):
        mods["direction"] = 1.3 if cat != "credit_rating" else 1.0
    if direction == "positive" and cat == "pledging":
        mods["direction"] = 0.7

    amount = stated_amount_crore(f"{item.get('subject', '')} {item.get('text', '')}")
    smod, snote = size_modifier(cat, amount, mcap_cr)
    if mods.get("subtype") is not None and (cat, cls.get("subtype")) == ("M&A", "incorporation"):
        if smod > 1.0:  # a "subscription" worth >=1% of market cap is a real capital decision, not nominal
            del mods["subtype"]
        else:
            reasons.append("new subsidiary set-up")
    if smod != 1.0:
        mods["size"] = smod
    if snote:
        reasons.append(snote)

    mods["portfolio"] = round(1 + 4 * weight, 3)
    reasons.append(f"{weight * 100:.0f}% of your portfolio")
    if cat in followed:
        mods["preference"] = float(tri.get("preference_boost", 1.25))
        reasons.append("a category you follow")

    score = base
    for v in mods.values():
        score *= v
    filed = datetime.fromisoformat(item["filed_at"])
    if (window_end - filed).total_seconds() <= 86400:
        score += float(tri.get("recency_bonus", 0.5))

    t = tri["tiers"]
    tier = ("critical" if score >= t["critical"] else "high" if score >= t["high"]
            else "medium" if score >= t["medium"] else "routine")
    return {
        "score": round(score, 2),
        "tier": tier,
        "why": ", ".join([CATEGORY_LABEL.get(cat, cat)] + reasons),
        "score_parts": {"base": base, **mods},
        "amount_cr": amount,
    }
