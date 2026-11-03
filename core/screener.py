"""screener.in company page: financial tables, top ratios and document links.

The page is plain HTML (no login needed for these sections). Parsing is isolated here so a layout
change only touches one module; tests run against a saved fixture.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

BASE = "https://www.screener.in/company/{ticker}/{suffix}"

SECTIONS = {
    "quarters": "quarters",
    "profit-loss": "annual",
    "balance-sheet": "balance",
    "cash-flow": "cashflow",
    "ratios": "ratios",
}

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


@dataclass
class Table:
    headers: list[str] = field(default_factory=list)          # e.g. ["Sep 2025", "Dec 2025", ..., "TTM"]
    rows: dict[str, list[float | None]] = field(default_factory=dict)

    def row(self, *aliases: str) -> list[float | None] | None:
        """First row whose label starts with any alias (case-insensitive)."""
        for a in aliases:
            al = a.lower()
            for label, vals in self.rows.items():
                if label.lower() == al:
                    return vals
        for a in aliases:
            al = a.lower()
            for label, vals in self.rows.items():
                if label.lower().startswith(al):
                    return vals
        return None

    def value(self, header: str, *aliases: str) -> float | None:
        r = self.row(*aliases)
        if r is None or header not in self.headers:
            return None
        return r[self.headers.index(header)]


@dataclass
class Concall:
    date: str                 # "Aug 2026"
    transcript_url: str | None
    ppt_url: str | None


@dataclass
class CompanyPage:
    ticker: str
    name: str
    basis: str                # consolidated | standalone
    url: str
    tables: dict[str, Table]
    ratios: dict[str, str]
    concalls: list[Concall]
    annual_reports: list[dict]  # [{"year": 2026, "url": ...}]


def _num(text: str) -> float | None:
    t = text.replace(",", "").replace("%", "").replace("\xa0", " ").strip()
    if t in ("", "-", "—"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _label(td) -> str:
    txt = td.get_text(" ", strip=True).replace("\xa0", " ")
    txt = re.sub(r"\s*\+\s*$", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def parse_table(section) -> Table:
    table = section.find("table", class_="data-table") if section else None
    if table is None:
        return Table()
    head = table.find("thead")
    headers = [th.get_text(" ", strip=True) for th in head.find_all("th")][1:] if head else []
    rows: dict[str, list[float | None]] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = _label(tds[0])
        if not label or label in rows:
            continue
        rows[label] = [_num(td.get_text(" ", strip=True)) for td in tds[1:]]
    return Table(headers, rows)


def parse_company(html: str, ticker: str, basis: str, url: str) -> CompanyPage:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ticker

    tables = {key: parse_table(soup.find("section", id=sid)) for sid, key in SECTIONS.items()}

    ratios: dict[str, str] = {}
    top = soup.find(id="top-ratios")
    if top:
        for li in top.find_all("li"):
            n, v = li.find(class_="name"), li.find(class_="value")
            if n and v:
                ratios[n.get_text(" ", strip=True)] = re.sub(r"\s+", " ", v.get_text(" ", strip=True))

    concalls: list[Concall] = []
    docs = soup.find("section", id="documents") or soup
    cc = docs.find("div", class_="concalls")
    if cc:
        for li in cc.find_all("li"):
            date_el = li.find("div")
            date = date_el.get_text(" ", strip=True) if date_el else ""
            t_url = p_url = None
            for a in li.find_all("a"):
                label = (a.get_text(" ", strip=True) + " " + (a.get("title") or "")).lower()
                href = a.get("href")
                if not href:
                    continue
                if "transcript" in label and not t_url:
                    t_url = href
                elif "ppt" in label and not p_url:
                    p_url = href
            if date:
                concalls.append(Concall(date, t_url, p_url))

    annual_reports: list[dict] = []
    ar = docs.find("div", class_="annual-reports")
    if ar:
        for a in ar.find_all("a"):
            m = re.search(r"(20\d\d)", a.get_text(" ", strip=True))
            if m and a.get("href"):
                annual_reports.append({"year": int(m.group(1)), "url": a["href"]})
    annual_reports.sort(key=lambda x: x["year"], reverse=True)
    concalls.sort(key=lambda c: month_key(c.date), reverse=True)
    return CompanyPage(ticker, name, basis, url, tables, ratios, concalls, annual_reports)


def month_key(label: str) -> tuple[int, int]:
    """'Aug 2026' -> (2026, 8). Unknown -> (0, 0)."""
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", label.strip())
    if not m:
        return (0, 0)
    return (int(m.group(2)), _MONTHS.get(m.group(1).title(), 0))


def fetch_company(http, ticker: str) -> CompanyPage:
    """Consolidated first (group view), standalone if the consolidated page has no quarterly data."""
    ticker = ticker.strip().upper()
    last_err: Exception | None = None
    for suffix, basis in (("consolidated/", "consolidated"), ("", "standalone")):
        url = BASE.format(ticker=ticker, suffix=suffix)
        try:
            html = http.get(url).text
        except FileNotFoundError as e:
            last_err = e
            continue
        page = parse_company(html, ticker, basis, url)
        if page.tables["quarters"].rows:
            return page
    if last_err:
        raise LookupError(f"{ticker} was not found on screener.in. Check the NSE symbol.")
    raise LookupError(f"screener.in has no financial tables for {ticker}.")
