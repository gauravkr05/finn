"""People card: who is joining or leaving, and the incoming person's background.

Appointment filings generally carry a brief profile of the appointee, so the filing itself is the
first (primary) source. Only if it has no usable profile, and a search key is configured, FINN looks
up the person's professional background and summarises it with a link (push-side enrichment, which
the brief allows).
"""
from __future__ import annotations

import logging
import os
from typing import Literal, Optional

import requests
from pydantic import BaseModel, Field

from core.guardrails import verify_quote

log = logging.getLogger("finn.people")

PROMPT = """This is an Indian listed company's stock-exchange filing about a change in management or the board.
List each person joining, leaving or changing role.
For each person give: name, role (e.g. "Chief Financial Officer"), change, effective_date (as written),
reason (only if the filing states one, as a short verbatim phrase) and, if the filing includes a profile/brief
of the person: previous organisations and roles, years of experience, qualifications, and profile_quote
(one sentence copied exactly from the filing's profile). Use null where the filing doesn't say. Never guess."""


class Person(BaseModel):
    name: str
    role: str
    change: Literal["appointed", "resigned", "retired", "ceased", "re-appointed", "redesignated", "other"]
    effective_date: Optional[str] = None
    reason: Optional[str] = None
    previous_roles: list[str] = Field(default_factory=list)
    experience_years: Optional[int] = None
    qualifications: list[str] = Field(default_factory=list)
    profile_quote: Optional[str] = None


class PeopleExtract(BaseModel):
    people: list[Person]


class WebBio(BaseModel):
    summary: str = Field(description="two short sentences on the person's career, only from the search results")
    source_url: Optional[str] = None


def build(router, pdf: bytes, page_texts: list[str] | None, company: str) -> dict:
    ex: PeopleExtract = router.json(task="people_extract", tier="cheap", prompt=PROMPT, schema=PeopleExtract,
                                    pdf=pdf, max_tokens=2000)
    people = []
    for p in ex.people:
        d = p.model_dump()
        if p.profile_quote and page_texts:
            m = verify_quote(p.profile_quote, page_texts)
            d["profile_source"] = ({"page": m.page, "quote": m.quote, "paragraph": m.paragraph, "verified": True}
                                   if m.found else {"verified": False})
        if p.change in ("appointed", "re-appointed", "redesignated") and not (p.previous_roles or p.profile_quote):
            web = web_bio(router, p.name, company, p.role)
            if web:
                d["web_bio"] = web
        people.append(d)
    return {"people": people}


def web_bio(router, name: str, company: str, role: str) -> dict | None:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    try:
        r = requests.post("https://api.tavily.com/search", timeout=30, json={
            "api_key": key, "query": f"{name} {role} {company} career background", "max_results": 4})
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        log.warning("web bio search failed for %s: %s", name, e)
        return None
    if not results:
        return None
    snippets = "\n".join(f"- {x.get('url')}: {x.get('content', '')[:500]}" for x in results)
    try:
        bio = router.json(task="people_web_bio", tier="cheap", schema=WebBio, max_tokens=400, prompt=(
            f"Summarise {name}'s professional background (new {role} at {company}) using ONLY these search "
            f"results. If they are about a different person, say 'No reliable background found.'\n{snippets}"))
    except Exception:
        return None
    return bio.model_dump()
