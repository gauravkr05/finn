"""NSE corporate announcements.

NSE's JSON API needs a browser-like session: visit the site first to receive cookies, then call the
API with a Referer. Field names are read defensively because the API is undocumented.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from core.http import Http

log = logging.getLogger("finn.nse")

HOME = "https://www.nseindia.com"
FILINGS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements"


class NSE:
    def __init__(self, http: Http | None = None):
        self.http = http or Http(min_interval=1.2)
        self._warm = False

    def _warmup(self) -> None:
        if self._warm:
            return
        for url in (HOME, FILINGS_PAGE):
            try:
                self.http.get(url, headers={"Accept": "text/html"})
            except Exception as e:
                log.warning("NSE warm-up %s failed: %s", url, e)
        self._warm = True

    def announcements(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        self._warmup()
        params = {"index": "equities", "symbol": symbol,
                  "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
        headers = {"Accept": "application/json, text/plain, */*", "Referer": FILINGS_PAGE}
        try:
            data = self.http.get(API, params=params, headers=headers, expect_json=True)
        except RuntimeError:
            self._warm = False  # cookies may have expired: re-warm once and retry
            self._warmup()
            data = self.http.get(API, params=params, headers=headers, expect_json=True)
        rows = data if isinstance(data, list) else data.get("data", [])
        return [f for f in (normalise(r, symbol) for r in rows) if f]

    def download(self, url: str) -> bytes:
        self._warmup()
        return self.http.get_bytes(url, headers={"Referer": FILINGS_PAGE})


def _parse_dt(raw: dict) -> datetime | None:
    for key, fmt in (("sort_date", "%Y-%m-%d %H:%M:%S"), ("an_dt", "%d-%b-%Y %H:%M:%S"),
                     ("exchdisstime", "%d-%b-%Y %H:%M:%S"), ("dt", "%d%m%Y%H%M%S")):
        val = raw.get(key)
        if val:
            try:
                return datetime.strptime(str(val).strip(), fmt)
            except ValueError:
                continue
    return None


def normalise(raw: dict, symbol: str) -> dict | None:
    dt = _parse_dt(raw)
    if dt is None:
        return None
    subject = (raw.get("desc") or raw.get("subject") or "").strip()
    text = (raw.get("attchmntText") or raw.get("attchmnt_text") or raw.get("text") or "").strip()
    url = (raw.get("attchmntFile") or raw.get("attachment") or "").strip() or None
    seq = str(raw.get("seq_id") or raw.get("an_id") or "")
    fid = seq or hashlib.sha1(f"{symbol}{dt}{subject}{text[:80]}".encode()).hexdigest()[:12]
    return {
        "id": f"nse-{symbol}-{fid}",
        "symbol": symbol,
        "company": (raw.get("sm_name") or "").strip(),
        "subject": subject,
        "text": text,
        "url": url,
        "filed_at": dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"),  # NSE timestamps are IST
        "source": "nse",
    }
