"""The ▶ Listen script: a short brief written for the ear, not the eye (units spelled out)."""
from __future__ import annotations


def _pct(v: float | None) -> str:
    if v is None:
        return ""
    word = "up" if v >= 0 else "down"
    return f"{word} {abs(v):.0f} percent"


def _row(card: dict, metric: str) -> dict | None:
    for r in (card.get("body") or {}).get("rows", []):
        if r["metric"] == metric:
            return r
    return None


def card_sentence(card: dict) -> str:
    name = card.get("company") or card["symbol"]
    kind = card.get("kind")
    if kind == "results":
        body = card["body"]
        top = _row(card, "Total income" if body.get("lender") else "Revenue")
        pat = _row(card, "PAT")
        bits = []
        if top and top.get("yoy") is not None:
            bits.append(f"{'total income' if body.get('lender') else 'revenue'} {_pct(top['yoy'])} year on year")
        if pat and pat.get("yoy") is not None:
            bits.append(f"profit after tax {_pct(pat['yoy'])}")
        s = f"{name} reported {body.get('period') or 'quarterly'} results" + (": " + ", ".join(bits) if bits else "")
        if body.get("flags"):
            s += ", including a one-off item"
        return s + "."
    if kind == "people":
        ppl = (card.get("body") or {}).get("people", [])
        out = [p for p in ppl if p["change"] in ("resigned", "retired", "ceased")]
        inn = [p for p in ppl if p["change"] in ("appointed", "re-appointed", "redesignated")]
        if out and inn:
            return f"{name}: {out[0]['name']} has {out[0]['change']} as {out[0]['role']}, and {inn[0]['name']} takes over."
        if out:
            return f"{name}: {out[0]['name']} has {out[0]['change']} as {out[0]['role']}."
        if inn:
            return f"{name} has appointed {inn[0]['name']} as {inn[0]['role']}."
    line = card.get("line") or card.get("title") or ""
    return f"{name}: {line.rstrip('.')}."


def spoken_brief(cards: list[dict], moves: list[dict], routine_count: int, greeting: str = "Good morning",
                 names: dict[str, str] | None = None) -> str:
    top = [c for c in cards if c["tier"] in ("critical", "high")][:3]
    parts = [f"{greeting}."]
    if top:
        n = len(top)
        parts.append(f"{'One thing needs' if n == 1 else f'{n} things need'} your attention.")
        parts += [card_sentence(c) for c in top]
    else:
        parts.append("Nothing material was filed across your portfolio.")
    for m in moves[:2]:
        parts.append(f"{(names or {}).get(m['symbol'], m['symbol'])} moved {_pct(m['move_pct'])} on {m['volume_ratio']:.1f} times its usual volume.")
    if routine_count:
        parts.append(f"{routine_count} routine filings are hidden.")
    return " ".join(parts).replace("  ", " ")
