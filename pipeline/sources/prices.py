"""End-of-day price and volume from Yahoo Finance (yfinance). NSE tickers use the .NS suffix."""
from __future__ import annotations

import logging
from datetime import date, timedelta

log = logging.getLogger("finn.prices")


def fetch_eod(symbols: list[str], index_symbols: list[str], days: int = 120) -> dict[str, list[dict]]:
    import yfinance as yf  # imported lazily: heavy, and only the push pipeline needs it

    yahoo = {f"{s}.NS": s for s in symbols}
    yahoo.update({s: s for s in index_symbols})
    start = (date.today() - timedelta(days=days)).isoformat()
    out: dict[str, list[dict]] = {}
    data = yf.download(list(yahoo), start=start, interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)
    for ysym, sym in yahoo.items():
        try:
            df = data[ysym] if ysym in data.columns.get_level_values(0) else None
        except Exception:
            df = None
        if df is None or df.empty:
            df = _fallback_bse(yf, sym, start) if ysym.endswith(".NS") else None
        if df is None or df.empty:
            log.warning("No EOD data for %s", sym)
            continue
        df = df.dropna(subset=["Close"])
        out[sym] = [
            {"d": idx.strftime("%Y-%m-%d"), "c": round(float(row["Close"]), 2),
             "v": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0}
            for idx, row in df.iterrows()
        ]
    return out


def _fallback_bse(yf, sym: str, start: str):
    log.info("Trying BSE (.BO) for %s", sym)
    try:
        return yf.download(f"{sym}.BO", start=start, interval="1d", auto_adjust=False, progress=False)
    except Exception:
        return None
