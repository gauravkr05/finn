"""HTTP client.

Uses curl_cffi with browser impersonation when available: NSE and screener.in accept it far more
reliably than plain `requests`. It is not a guarantee (cloud IPs can still be blocked), which is why
every source has a cache and a fallback. Requests are spaced politely.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("finn.http")

try:  # pragma: no cover - import guard
    from curl_cffi import requests as _client

    _HAS_CFFI = True
except Exception:  # pragma: no cover
    import requests as _client  # type: ignore

    _HAS_CFFI = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class Http:
    def __init__(self, min_interval: float = 0.8, timeout: float = 30.0):
        self.s = _client.Session(impersonate="chrome") if _HAS_CFFI else _client.Session()
        if not _HAS_CFFI:
            self.s.headers.update({"User-Agent": UA})
        self.s.headers.update({"Accept-Language": "en-IN,en;q=0.9"})
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0

    def _wait(self) -> None:
        dt = time.time() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.time()

    def get(self, url: str, *, headers: dict | None = None, params: dict | None = None,
            retries: int = 2, expect_json: bool = False):
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._wait()
            try:
                r = self.s.get(url, headers=headers or {}, params=params, timeout=self.timeout)
                if r.status_code in (429, 503) and attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    raise FileNotFoundError(url)
                r.raise_for_status()
                return r.json() if expect_json else r
            except FileNotFoundError:
                raise
            except Exception as e:  # network errors, JSON errors, HTTP errors
                last_exc = e
                log.warning("GET %s failed (attempt %d): %s", url, attempt + 1, e)
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"GET failed after {retries + 1} attempts: {url}: {last_exc}")

    def get_bytes(self, url: str, **kw) -> bytes:
        return self.get(url, **kw).content
