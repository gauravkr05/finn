"""Unusual end-of-day moves. Mirrors web/src/lib/alerts.js, which recomputes live as thresholds change."""
from __future__ import annotations


def detect(prices: dict[str, list[dict]], symbols: list[str], volume_multiple: float, price_move_pct: float,
           lookback: int, days: int = 30) -> list[dict]:
    out = []
    for sym in symbols:
        rows = prices.get(sym) or []
        for i in range(max(1, len(rows) - days), len(rows)):
            hist = [r["v"] for r in rows[max(0, i - lookback):i] if r["v"]]
            if len(hist) < max(5, lookback // 2):
                continue
            avg = sum(hist) / len(hist)
            vr = rows[i]["v"] / avg if avg else 0
            mv = (rows[i]["c"] / rows[i - 1]["c"] - 1) * 100 if rows[i - 1]["c"] else 0
            if vr >= volume_multiple or abs(mv) >= price_move_pct:
                out.append({"symbol": sym, "date": rows[i]["d"], "close": rows[i]["c"],
                            "move_pct": round(mv, 2), "volume_ratio": round(vr, 2),
                            "trigger": "both" if vr >= volume_multiple and abs(mv) >= price_move_pct
                            else "volume" if vr >= volume_multiple else "price"})
    return sorted(out, key=lambda m: m["date"], reverse=True)
