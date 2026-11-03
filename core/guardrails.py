"""Citation guardrail.

A quote counts only if it appears in the source text (fuzzy match after normalisation). The match
also returns the surrounding paragraph, which the app shows with the quote highlighted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")


def _clean(s: str) -> str:
    """Normalise quotes, dashes and whitespace but keep case (for display)."""
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return _WS.sub(" ", s).strip()


@dataclass
class Match:
    found: bool
    score: float
    page: int | None = None
    quote: str = ""          # the quote as it appears in the source
    paragraph: str = ""      # surrounding text, for the highlight drawer


def verify_quote(quote: str, pages: list[str], threshold: float = 90, hint_page: int | None = None,
                 context: int = 280) -> Match:
    q = _canon(_clean(quote).lower())
    if len(q) < 12:
        return Match(False, 0.0)
    order = list(range(len(pages)))
    if hint_page and 1 <= hint_page <= len(pages):  # check the cited page (and neighbours) first
        h = hint_page - 1
        order = sorted(order, key=lambda i: abs(i - h))
    best = Match(False, 0.0)
    for i in order:
        disp = _clean(pages[i])
        text = disp.lower()  # same length as disp for the ASCII-heavy text of filings
        if not text or len(text) != len(disp):
            text = disp = _clean(pages[i]).lower()
        if not text:
            continue
        if "%" in text or "per cent" in text:  # canonicalise on a copy; positions map via a fuzzy pass
            cdisp = _canon(disp)
            ctext = cdisp.lower()
            if q in ctext or (fuzz.partial_ratio(q, ctext) >= threshold and fuzz.partial_ratio(q, text) < threshold):
                al = fuzz.partial_ratio_alignment(q, ctext)
                if al and al.score >= threshold:
                    para = _window(cdisp, al.dest_start, al.dest_end, context)
                    m = Match(True, al.score, i + 1, cdisp[al.dest_start:al.dest_end], para)
                    if m.score > best.score:
                        best = m
                    continue
        if q in text:  # exact hit
            start = text.index(q)
            return Match(True, 100.0, i + 1, disp[start:start + len(q)],
                         _window(disp, start, start + len(q), context))
        al = fuzz.partial_ratio_alignment(q, text, score_cutoff=threshold)
        if al and al.score > best.score:
            best = Match(True, al.score, i + 1, disp[al.dest_start:al.dest_end],
                         _window(disp, al.dest_start, al.dest_end, context))
            if al.score >= 98:
                break
    return best if best.score >= threshold else Match(False, best.score)


def _canon(s: str) -> str:
    s = re.sub(r"\s*%", " percent", s)
    return re.sub(r"(?i)per cent", lambda m: m.group(0)[:3] + m.group(0)[4:], s)


def _window(text: str, start: int, end: int, context: int) -> str:
    a = max(0, start - context)
    b = min(len(text), end + context)
    # snap to sentence-ish boundaries
    left = text.rfind(". ", a, start)
    a = left + 2 if left != -1 else a
    right = text.find(". ", end, b)
    b = right + 1 if right != -1 else b
    return ("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else "")
