"""BSE announcements: fallback when NSE is unreachable. Needs the BSE scrip code (config: bse_code)."""
from __future__ import annotations

import logging
from datetime import datetime

from core.http import Http

log = logging.getLogger("finn.bse")

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
           "Accept": "application/json, text/plain, */*"}


class BSE:
    def __init__(self, http: Http | None = None):
        self.http = http or Http(min_interval=1.2)

    def announcements(self, symbol: str, code: str, start: datetime, end: datetime) -> list[dict]:
        params = {"pageno": 1, "strCat": -1, "strPrevDate": start.strftime("%Y%m%d"), "strScrip": code,
                  "strSearch": "P", "strToDate": end.strftime("%Y%m%d"), "strType": "C", "subcategory": -1}
        data = self.http.get(API, params=params, headers=HEADERS, expect_json=True)
        out = []
        for r in data.get("Table", []):
            try:
                dt = datetime.fromisoformat(str(r.get("NEWS_DT", "")).split(".")[0])
            except ValueError:
                continue
            att = r.get("ATTACHMENTNAME")
            out.append({
                "id": f"bse-{symbol}-{r.get('NEWSID')}",
                "symbol": symbol,
                "company": "",
                "subject": (r.get("CATEGORYNAME") or r.get("SUBCATNAME") or r.get("NEWSSUB") or "").strip(),
                "text": (r.get("HEADLINE") or r.get("NEWSSUB") or "").strip(),
                "url": ATTACH.format(name=att) if att else None,
                "filed_at": dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                "source": "bse",
            })
        return out

    def download(self, url: str) -> bytes:
        return self.http.get_bytes(url, headers=HEADERS)
