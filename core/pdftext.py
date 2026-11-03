"""PDF text extraction and transcript chunking (pure Python, low memory).

Transcripts are born-digital, so pypdf extraction is fast and keeps exact page numbers. Keeping the
text in Python is what makes the citation guardrail and the highlight drawer possible.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader

SCANNED_THRESHOLD = 500  # total characters; below this a PDF is treated as scanned


def extract_pages(pdf: bytes, max_pages: int | None = None) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf))
    pages = []
    for i, page in enumerate(reader.pages):
        if max_pages and i >= max_pages:
            break
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def is_scanned(pages: list[str]) -> bool:
    return sum(len(p.strip()) for p in pages) < SCANNED_THRESHOLD


_PAGE_NUM = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.I)


def strip_headers_footers(pages: list[str]) -> list[str]:
    """Drop lines that repeat on more than half the pages (letterheads, footers) and bare page numbers."""
    if len(pages) < 3:
        return [_drop_page_numbers(p) for p in pages]
    counts: Counter[str] = Counter()
    for p in pages:
        lines = {ln.strip() for ln in p.splitlines() if ln.strip()}
        counts.update(lines)
    limit = len(pages) / 2
    repeated = {ln for ln, c in counts.items() if c > limit and len(ln) < 160}
    cleaned = []
    for p in pages:
        keep = [ln for ln in p.splitlines() if ln.strip() not in repeated]
        cleaned.append(_drop_page_numbers("\n".join(keep)))
    return cleaned


def _drop_page_numbers(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not _PAGE_NUM.match(ln))


# "Rajesh Kumar:" / "Moderator:" / "Mr. A. Sharma:" at the start of a line
_SPEAKER = re.compile(r"^\s*((?:Mr\.|Ms\.|Mrs\.|Dr\.)?\s*[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4})\s*:\s+", re.M)


@dataclass
class Chunk:
    speaker: str
    text: str
    page: int  # 1-based page where the turn starts
    idx: int


def speaker_chunks(pages: list[str], max_chars: int = 2500) -> list[Chunk]:
    """Split a transcript into speaker turns, tracking the starting page of each."""
    joined, offsets = "", []
    for i, p in enumerate(pages):
        offsets.append((len(joined), i + 1))
        joined += p + "\n"

    def page_at(pos: int) -> int:
        pg = 1
        for start, num in offsets:
            if start <= pos:
                pg = num
            else:
                break
        return pg

    matches = list(_SPEAKER.finditer(joined))
    chunks: list[Chunk] = []
    if not matches:  # no speaker labels: fall back to fixed windows per page
        for i, p in enumerate(pages):
            for j in range(0, len(p), max_chars):
                chunks.append(Chunk("", p[j:j + max_chars], i + 1, len(chunks)))
        return chunks
    for k, m in enumerate(matches):
        end = matches[k + 1].start() if k + 1 < len(matches) else len(joined)
        body = joined[m.end():end].strip()
        if not body:
            continue
        spk = m.group(1).strip()
        for j in range(0, len(body), max_chars):
            chunks.append(Chunk(spk, body[j:j + max_chars], page_at(m.start() + j), len(chunks)))
    return chunks


GUIDANCE_TERMS = [
    "guidance", "guide", "expect", "outlook", "target", "aim", "aspire", "confident", "will be",
    "we will", "going forward", "next year", "this year", "full year", "fy2", "fy 2", "h2", "second half",
    "margin", "growth", "double digit", "double-digit", "teens", "percent", "%", "capex", "capacity",
    "crore", "debt", "launch", "commission", "by the end of", "trajectory", "range", "band",
]


def guidance_score(text: str) -> int:
    t = text.lower()
    return sum(t.count(term) for term in GUIDANCE_TERMS)


def select_guidance_chunks(chunks: list[Chunk], budget_chars: int = 12000) -> list[Chunk]:
    """Keep the turns most likely to contain guidance, within a character budget, in original order."""
    scored = [(guidance_score(c.text), c) for c in chunks
              if c.speaker.lower() != "moderator" and len(c.text) > 120]
    scored.sort(key=lambda x: x[0], reverse=True)
    picked, used = [], 0
    for score, c in scored:
        if score == 0:
            break
        if used + len(c.text) > budget_chars:
            continue
        picked.append(c)
        used += len(c.text)
    return sorted(picked, key=lambda c: c.idx)


def opening_remarks(chunks: list[Chunk], budget_chars: int = 7000) -> list[Chunk]:
    """Management's prepared remarks: the turns after the moderator's intro, before Q&A starts."""
    out, used, started = [], 0, False
    for c in chunks:
        spk = c.speaker.lower()
        if spk == "moderator":
            if started and re.search(r"question|q&a|first question", c.text, re.I):
                break
            continue
        started = True
        if used + len(c.text) > budget_chars:
            break
        out.append(c)
        used += len(c.text)
    return out


def format_chunks(chunks: list[Chunk], doc_label: str) -> str:
    return "\n\n".join(f"[{doc_label} p.{c.page}] {c.speaker or 'Speaker'}: {c.text}" for c in chunks)
