"""Primary documents for research: last 4 concall transcripts (presentation as fallback) and, for
pre-computed tickers only, the latest annual report."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

from core.config import CACHE_DIR
from core.pdftext import (Chunk, extract_pages, is_scanned, opening_remarks, select_guidance_chunks,
                          speaker_chunks, strip_headers_footers)
from core.periods import call_to_quarter, quarter_label
from core.screener import CompanyPage, month_key

log = logging.getLogger("finn.docs")
BSE_HEADERS = {"Referer": "https://www.bseindia.com/"}


@dataclass
class Doc:
    label: str               # "Q1 FY27 call" / "AR FY2026"
    kind: str                # transcript | presentation | annual_report
    url: str
    call_month: str = ""     # "Aug 2026"
    quarter: str = ""        # quarter discussed, "Q1 FY27"
    order: tuple = (0, 0)    # sort key, newest last
    pages: list[str] = field(default_factory=list)
    scanned: bool = False
    pdf: bytes | None = None
    chunks: list[Chunk] = field(default_factory=list)


def _fetch(http, url: str) -> bytes | None:
    d = CACHE_DIR / "docs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if path.exists():
        return path.read_bytes()
    try:
        data = http.get_bytes(url, headers=BSE_HEADERS if "bseindia" in url else None)
    except Exception as e:
        log.warning("download failed %s: %s", url, e)
        return None
    if not data.startswith(b"%PDF"):
        log.warning("not a PDF: %s", url)
        return None
    path.write_bytes(data)
    return data


def load_doc(http, doc: Doc, max_pages: int | None = None) -> Doc | None:
    pdf = _fetch(http, doc.url)
    if pdf is None:
        return None
    try:
        pages = extract_pages(pdf, max_pages=max_pages)
    except Exception as e:
        log.warning("text extraction failed for %s: %s", doc.label, e)
        pages = []
    doc.scanned = is_scanned(pages)
    if doc.scanned:
        doc.pdf = pdf  # sent to the model as bytes; quotes can't be verified
    else:
        doc.pages = strip_headers_footers(pages)
        doc.chunks = speaker_chunks(doc.pages)
    return doc


def _pick_per_quarter(concalls) -> list[tuple]:
    """One document per quarter discussed, newest quarter first, preferring a transcript.

    screener.in can list the same call twice (POLYCAB Jan 2026) or a presentation-only event in a
    quarter that already has a results call (PERSISTENT Sep 2026, an investor day)."""
    best: dict[tuple, tuple] = {}
    seen_urls: set[str] = set()
    for c in concalls:
        url, kind = (c.transcript_url, "transcript") if c.transcript_url else (c.ppt_url, "presentation")
        if not url or url in seen_urls:
            continue
        y, m = month_key(c.date)
        if not y:
            continue
        seen_urls.add(url)
        key = call_to_quarter(m, y)
        cur = best.get(key)
        if cur is None or (cur[2] == "presentation" and kind == "transcript"):
            best[key] = (c, url, kind, y, m)
    return [best[k] for k in sorted(best, key=lambda k: (k[1], k[0]), reverse=True)]


def transcripts(http, page: CompanyPage, n: int = 4) -> list[Doc]:
    docs: list[Doc] = []
    for c, url, kind, y, m in _pick_per_quarter(page.concalls):
        if len(docs) >= n:
            break
        qm, qy = call_to_quarter(m, y)
        q = quarter_label(qm, qy)
        doc = Doc(label=f"{q} {'call' if kind == 'transcript' else 'presentation'}", kind=kind, url=url,
                  call_month=c.date, quarter=q, order=(y, m))
        loaded = load_doc(http, doc)
        if loaded:
            docs.append(loaded)
    docs.sort(key=lambda d: d.order)
    return docs


AR_TERMS = ["segment", "business overview", "our business", "revenue mix", "products", "brands", "customers",
            "business segments", "company overview", "at a glance"]


def annual_report(http, page: CompanyPage) -> Doc | None:
    if not page.annual_reports:
        return None
    ar = page.annual_reports[0]
    doc = Doc(label=f"AR FY{ar['year']}", kind="annual_report", url=ar["url"], order=(ar["year"], 3))
    loaded = load_doc(http, doc, max_pages=400)
    if not loaded or loaded.scanned:
        return None
    scored = []
    for i, p in enumerate(loaded.pages):
        low = p.lower()
        s = sum(low.count(t) for t in AR_TERMS)
        if s and len(p) > 400:
            scored.append((s, i))
    keep = sorted(i for _, i in sorted(scored, reverse=True)[:5])
    loaded.chunks = [Chunk("Annual report", re.sub(r"\s+", " ", loaded.pages[i])[:2400], i + 1, k)
                     for k, i in enumerate(keep)]
    return loaded


_REF = re.compile(r"^\s*\[?\s*(.*?)\s*(?:[,;]?\s*p(?:age)?\.?\s*(\d+))?\s*\]?\s*$", re.I)


def verify_cited(quote: str | None, ref: str | None, docs: list[Doc], threshold: float):
    """Verify a model-cited quote. Models echo the excerpt tag ("[Q2 FY27 call p.4]") instead of the bare
    label, so parse label + page from the reference; if the label is unknown, look in every document.
    Returns (doc, match) for the first document where the quote verifies, else (None, None)."""
    from core.guardrails import verify_quote

    if not quote:
        return None, None
    label, page = None, None
    if ref:
        m = _REF.match(ref)
        if m:
            label, page = m.group(1), int(m.group(2)) if m.group(2) else None
    named = [d for d in docs if d.label == label]
    for d in named + [d for d in docs if d not in named]:
        if d.scanned or not d.pages:
            continue
        match = verify_quote(quote, d.pages, threshold, hint_page=page if d in named else None)
        if match.found:
            return d, match
    return None, None


def guidance_chunks(doc: Doc) -> list[Chunk]:
    return select_guidance_chunks(doc.chunks)


def opening(doc: Doc) -> list[Chunk]:
    return opening_remarks(doc.chunks)
