import json
from pathlib import Path

import pytest

from api import documents, financials, promises
from core.guardrails import verify_quote
from core.pdftext import extract_pages, speaker_chunks, select_guidance_chunks, strip_headers_footers
from core.periods import call_to_quarter, parse_period, quarter_label
from core.screener import parse_company

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def page():
    html = (FX / "screener_company.html").read_text(encoding="utf-8")
    return parse_company(html, "FIXTURE", "consolidated", "https://www.screener.in/company/FIXTURE/consolidated/")


def test_screener_parse(page):
    q = page.tables["quarters"]
    assert q.headers[-1] == "Sep 2026" and q.value("Sep 2026", "Sales") == 1300
    assert page.tables["annual"].value("Mar 2026", "OPM %") == 19
    assert page.ratios["ROCE"].startswith("24.1")
    assert [c.date for c in page.concalls] == ["Oct 2026", "Jul 2026", "Apr 2026", "Jan 2026"]
    assert page.concalls[0].transcript_url.endswith("q2.pdf") and page.annual_reports[0]["year"] == 2026


def test_financials(page):
    fin = financials.build(page)
    assert fin["snapshot"]["fy"] == "Mar 2026" and fin["snapshot"]["revenue"] == 4860
    assert fin["trajectory"]["revenue_cagr_3y"] == pytest.approx(9.5, abs=0.2)
    assert fin["cash"]["cumulative_3y_pct"] == pytest.approx(109, abs=1)
    assert any(t["label"] == "Revenue growing" for t in fin["trajectory"]["tags"])
    assert fin["balance"]["cash_conversion_cycle"]["Mar 2026"] == 55 and not fin["flags"]


def test_periods():
    assert quarter_label(9, 2026) == "Q2 FY27" and quarter_label(3, 2026) == "Q4 FY26"
    assert call_to_quarter(8, 2026) == (6, 2026) and call_to_quarter(1, 2026) == (12, 2025)
    assert parse_period("FY27") == {"kind": "fy", "fy": 2027, "n": None}
    assert parse_period("Q3 FY27")["n"] == 3 and parse_period("H2 FY2027")["kind"] == "half"


def test_transcript_text_and_chunks():
    pages = strip_headers_footers(extract_pages((FX / "transcript_q4fy26.pdf").read_bytes()))
    chunks = speaker_chunks(pages)
    assert {c.speaker for c in chunks} >= {"Moderator", "Rajesh Kumar"}
    picked = select_guidance_chunks(chunks)
    assert picked and all(c.speaker != "Moderator" for c in picked)
    assert any("12 to 15 percent" in c.text for c in picked) and picked[-1].page == 2
    m = verify_quote("For FY27 we remain confident of 12 to 15 percent revenue growth.", pages)
    assert m.found and m.page == 2 and "12 to 15" in m.paragraph


def _claim(metric, ttype, low=None, high=None, period="FY27", direction=None):
    return {"metric": metric, "target": {"type": ttype, "low": low, "high": high, "direction": direction},
            "period": period, "statement": "x", "said_in": "Q4 FY26 call", "said_quarter": "Q4 FY26"}


def test_judge_rules():
    rep = lambda v, prev=None: {"status": "reported", "value": v, "prev": prev, "label": "L"}
    assert promises.judge(_claim("revenue_growth", "range", 12, 15), rep(13), .2, 1)[0] == "kept"
    assert promises.judge(_claim("revenue_growth", "range", 12, 15), rep(10), .2, 1)[0] == "partly"
    assert promises.judge(_claim("revenue_growth", "range", 12, 15), rep(6), .2, 1)[0] == "missed"
    assert promises.judge(_claim("ebitda_margin", "range", 19, 21), rep(18.4), .2, 1)[0] == "partly"
    assert promises.judge(_claim("ebitda_margin", "range", 19, 21), rep(17.5), .2, 1)[0] == "missed"
    assert promises.judge(_claim("revenue_growth", "min", 10), rep(11), .2, 1)[0] == "kept"
    assert promises.judge(_claim("debt", "point", 0, unit := None), rep(3), .2, 1)[0] == "kept"
    assert promises.judge(_claim("revenue_growth", "range", 12, 15), {"status": "pending", "tracking": 13.9,
                          "tracking_label": "2 of 4 quarters reported"}, .2, 1)[0] == "pending"


def test_delivered_from_tables(page):
    d = promises.delivered(page, "revenue_growth", parse_period("FY27"))
    assert d["status"] == "pending" and d["tracking"] == pytest.approx(13.9, abs=0.1)
    d = promises.delivered(page, "revenue_growth", parse_period("FY26"))
    assert d["status"] == "reported" and d["value"] == pytest.approx(14.9, abs=0.1)
    d = promises.delivered(page, "ebitda_margin", parse_period("Q2 FY27"))
    assert d["status"] == "reported" and d["value"] == pytest.approx(17.9, abs=0.2)
    d = promises.delivered(page, "revenue_growth", parse_period("Q2 FY27"))
    assert d["value"] == pytest.approx(13.0, abs=0.1)


def test_drift_detects_lowered_guidance():
    a = _claim("revenue_growth", "range", 12, 15)
    a.update(order=(2026, 4), said_in="Q4 FY26 call")
    b = _claim("revenue_growth", "range", 8, 10)
    b.update(order=(2026, 10), said_in="Q2 FY27 call")
    out = promises.drift([a, b])
    assert out and out[0]["direction"] == "lowered"


# ---------------------------------------------------------------- end-to-end with fakes
class FakeResp:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content


class FakeHttp:
    def __init__(self, *a, **k):
        pass

    def get(self, url, **kw):
        if "screener.in" in url:
            return FakeResp((FX / "screener_company.html").read_text(encoding="utf-8"))
        raise FileNotFoundError(url)

    def get_bytes(self, url, **kw):
        name = {"q2.pdf": "transcript_q2fy27.pdf", "q4.pdf": "transcript_q4fy26.pdf"}.get(url.rsplit("/", 1)[-1])
        if not name:
            raise RuntimeError("missing")
        return (FX / name).read_bytes()


def fake_json(self, *, task, tier, prompt, schema, pdf=None, system=None, max_tokens=4096, allow_fallback=True):
    from core.llm import CallRecord
    self.ledger.add(CallRecord(task, tier, "fake", 100, 50, False, 0.0, 1))
    if task == "promise_extract" and "Q4 FY26" in prompt:
        data = {"claims": [
            {"metric": "revenue_growth", "statement": "Revenue growth 12-15% in FY27",
             "target": {"type": "range", "low": 12, "high": 15, "unit": "%"}, "period": "FY27",
             "quote": "For FY27 we remain confident of 12 to 15 percent revenue growth.", "page": 2},
            {"metric": "other", "statement": "Commission Dahej plant by Q3 FY27",
             "target": {"type": "direction", "direction": "up"}, "period": "Q3 FY27",
             "quote": "We will commission the new Dahej plant by the third quarter of FY27.", "page": 2},
            {"metric": "ebitda_margin", "statement": "Invented claim", "target": {"type": "range", "low": 30, "high": 32},
             "period": "FY27", "quote": "We will double margins to thirty percent next year.", "page": 2},
        ]}
    elif task == "promise_extract":
        data = {"claims": [{"metric": "revenue_growth", "statement": "Revenue growth 8-10% in FY27",
                            "target": {"type": "range", "low": 8, "high": 10, "unit": "%"}, "period": "FY27",
                            "quote": "We now expect 8 to 10 percent revenue growth for FY27.", "page": 1}]}
    elif task == "promise_followup":
        data = {"results": [{"id": 0, "verdict": "kept", "reason": "Plant commissioned early",
                             "evidence_quote": "The Dahej plant was commissioned in September, ahead of schedule.",
                             "evidence_doc": "Q2 FY27 call"}]}
    elif task == "snapshot":
        data = {"business": "A decorative paints maker with an industrial coatings arm.",
                "segments": [{"name": "Decorative", "detail": "about 80% of revenue"}],
                "quotes": [{"text": "Decorative paints contribute about 80 percent of revenue.", "doc": "Q2 FY27 call", "page": 1}]}
    elif task == "bull_bear":
        data = {"bull": [{"text": "Steady growth", "fact_ids": ["F1"]}, {"text": "Uncited", "fact_ids": []}],
                "bear": [{"text": "Guidance cut", "fact_ids": [],
                          "quote": "We now expect 8 to 10 percent revenue growth for FY27.", "quote_doc": "Q2 FY27 call"}]}
    else:
        raise AssertionError(task)
    return schema.model_validate(data)


def test_research_end_to_end(monkeypatch, tmp_path):
    import api.research as research
    import core.llm as llm

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(research, "Http", FakeHttp)
    monkeypatch.setattr(documents, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.Router, "json", fake_json)
    res = research.run("FIXTURE")
    claims = {c["statement"]: c for c in res["promises"]}
    assert "Invented claim" not in claims, "citation guardrail must drop unverifiable quotes"
    assert res["trace"]["dropped_uncited"] >= 2  # invented promise + uncited bull point
    assert claims["Revenue growth 12-15% in FY27"]["verdict"] == "pending"
    assert claims["Revenue growth 12-15% in FY27"]["source"]["page"] == 2
    assert claims["Commission Dahej plant by Q3 FY27"]["verdict"] == "kept"
    assert claims["Commission Dahej plant by Q3 FY27"]["evidence"]["doc"] == "Q2 FY27 call"
    assert res["drift"] and res["drift"][0]["direction"] == "lowered"
    assert len(res["bull"]) == 1 and len(res["bear"]) == 1 and res["bear"][0]["source"]["page"] == 1
    assert res["documents"][0]["label"] == "Q4 FY26 call"
    json.dumps(res, default=str)


def test_one_document_per_quarter_prefers_transcript():
    from api.documents import _pick_per_quarter
    from core.screener import Concall

    calls = [  # as listed on screener.in, newest first
        Concall("Oct 2026", "https://x/t-oct", "https://x/p-oct"),
        Concall("Sep 2026", None, "https://x/p-investor-day"),       # same quarter as Aug (Q1 FY27)
        Concall("Aug 2026", "https://x/t-aug", "https://x/p-aug"),
        Concall("Jan 2026", "https://x/t-jan", None),
        Concall("Jan 2026", "https://x/t-jan", "https://x/p-jan"),    # duplicate listing
        Concall("Oct 2025", None, "https://x/p-oct25"),              # presentation-only quarter: fallback
    ]
    got = [(c.date, url, kind) for c, url, kind, y, m in _pick_per_quarter(calls)]
    assert got == [("Oct 2026", "https://x/t-oct", "transcript"), ("Aug 2026", "https://x/t-aug", "transcript"),
                   ("Jan 2026", "https://x/t-jan", "transcript"), ("Oct 2025", "https://x/p-oct25", "presentation")]


def _dixon_claim(metric, ttype, low, high=None, unit="%", scope="company", period="FY26"):
    c = _claim(metric, ttype, low, high, period=period)
    c["target"]["unit"], c["scope"] = unit, scope
    return c


def test_comparable_units_and_scope():
    assert promises.comparable(_dixon_claim("revenue_growth", "point", 5200, unit="crore", scope="segment")) is None
    assert promises.comparable(_dixon_claim("revenue_growth", "point", 3, unit="x", scope="segment")) is None
    assert promises.comparable(_dixon_claim("revenue_growth", "point", 56000, unit="crore")) == "amount"
    assert promises.comparable(_dixon_claim("revenue_growth", "point", 3, unit="x")) == "multiple"
    assert promises.comparable(_dixon_claim("revenue_growth", "range", 15, 17)) == "pct"
    assert promises.comparable(_dixon_claim("revenue_growth", "range", 190, 200, unit="million")) is None
    assert promises.comparable(_dixon_claim("ebitda_margin", "range", 11, 13, unit="crore")) is None
    assert promises.comparable(_claim("revenue_growth", "range", 12, 15)) == "pct"  # old claims: no unit/scope


def test_segment_and_amount_claims_are_not_judged_as_growth(page):
    """DIXON Q3 FY26: "telecom revenue close to INR 5,200 crores" was judged 'missed: 25.8% vs guided 5200%'."""
    cfg = {"partly_band_relative": .2, "partly_band_points": 1}
    seg = _dixon_claim("revenue_growth", "point", 5200, 5200, unit="crore", scope="segment")
    fy26_sales = promises.delivered_amount(page, "revenue_growth", parse_period("FY26"))["value"]
    amt = _dixon_claim("revenue_growth", "point", round(fy26_sales * 0.9), unit="crore")
    mult = _dixon_claim("revenue_growth", "point", 3, unit="x")
    promises.judge_all(page, [seg, amt, mult], cfg)
    assert seg["verdict"] == "unjudged" and seg["judged_by"] == "pending-qualitative"
    assert amt["verdict"] == "kept" and "₹" in amt["reason"] and "cr" in amt["reason"] and "%" not in amt["reason"]
    assert mult["verdict"] == "missed" and "200%" in mult["reason"]  # 3x = +200% vs ~15% delivered


def test_drift_ignores_mixed_units_and_segments():
    a = _dixon_claim("revenue_growth", "range", 15, 17, period="FY27")
    a.update(order=(2026, 4), said_in="Q4 FY26 call")
    b = _dixon_claim("revenue_growth", "point", 56000, unit="crore", period="FY27")
    b.update(order=(2026, 8), said_in="Q1 FY27 call")
    c = _dixon_claim("revenue_growth", "range", 6700, 7000, unit="crore", scope="segment", period="FY27")
    c.update(order=(2026, 8), said_in="Q1 FY27 call")
    assert promises.drift([a, b, c]) == []


def test_unstated_period_is_the_fy_in_progress_at_the_call(page):
    """DIXON Q4 FY26 call (May 2026): "keep growing 15-17%" with no period is FY27 guidance, not FY26."""
    cfg = {"partly_band_relative": .2, "partly_band_points": 1}
    c = _dixon_claim("revenue_growth", "range", 15, 17, period=None)
    c.update(said_quarter="Q4 FY26", order=(2026, 5))
    promises.judge_all(page, [c], cfg)
    assert c["period_assumed"] and c["verdict"] == "pending"   # FY27 not complete in the fixture
    d = _dixon_claim("revenue_growth", "range", 15, 17, period=None)
    d.update(said_quarter="Q3 FY26", order=(2026, 1))            # Jan 2026 call: FY26 still in progress
    promises.judge_all(page, [d], cfg)
    assert d["delivered"]["label"].endswith("FY26")


def test_qualitative_skips_claims_from_the_latest_call():
    from api.documents import Doc
    from api.promises import Followup, Followups

    docs = [Doc("Q1 FY27 call", "transcript", "u1", order=(2026, 8), pages=["We launched the plant in Q2."]),
            Doc("Q2 FY27 call", "transcript", "u2", order=(2026, 10), pages=["The plant is now running."])]
    old = {"verdict": "unjudged", "order": (2026, 8), "said_in": "Q1 FY27 call", "statement": "plant by Q2",
           "quote": "q"}
    latest = {"verdict": "unjudged", "order": (2026, 10), "said_in": "Q2 FY27 call", "statement": "new plant",
              "quote": "q"}
    seen = {}

    class R:
        def json(self, *, prompt, schema, **kw):
            seen["prompt"] = prompt
            return Followups(results=[Followup(id=0, verdict="pending", reason="Target period has not elapsed yet")])

    promises.qualitative(R(), [old, latest], docs, 90, 6)
    assert "plant by Q2" in seen["prompt"] and "new plant" not in seen["prompt"]
    assert latest["verdict"] == "pending" and "latest call" in latest["reason"]
    assert old["verdict"] == "pending" and old["reason"] == "Target period has not elapsed yet"


@pytest.mark.parametrize("ref", ["[Q2 FY27 call p.4]", "Q2 FY27 call p.4", "Q2 FY27 call", "Q2 FY27 call, page 4",
                                 "[Q1 FY27 call p.9]", None])
def test_verify_cited_resolves_echoed_tags(ref):
    """bull_bear / follow-up quote_doc came back as "[Q2 FY27 call p.4]" and every such citation was dropped."""
    from api.documents import Doc, verify_cited

    docs = [Doc("Q1 FY27 call", "transcript", "u1", pages=["Nothing relevant here at all."]),
            Doc("Q2 FY27 call", "transcript", "u2",
                pages=["intro", "x", "y", "This marks our 26th sequential quarter of revenue growth. More text."])]
    d, m = verify_cited("This marks our 26th sequential quarter of revenue growth.", ref, docs, 90)
    assert d is docs[1] and m.page == 4


def test_verify_cited_still_rejects_invented_quotes():
    from api.documents import Doc, verify_cited

    docs = [Doc("Q2 FY27 call", "transcript", "u2", pages=["Revenue grew 7.8% quarter on quarter."])]
    assert verify_cited("Revenue grew 25% and margins doubled this quarter.", "[Q2 FY27 call p.1]", docs, 90) == (None, None)


def test_ebit_guidance_is_judged_against_ebit_not_opm():
    """COFORGE (screener.in, Nov 2026): EBIT guidance was compared with OPM (EBITDA-style), turning a
    13.7% EBIT year into 'kept at 18%'."""
    from core.screener import CompanyPage, Table

    q = Table(headers=["Dec 2025", "Mar 2026"], rows={"Sales": [4200.0, 4450.0], "Operating Profit": [800.0, 876.0],
                                                     "Depreciation": [170.0, 180.0], "OPM %": [19.0, 19.7]})
    an = Table(headers=["Mar 2025", "Mar 2026"], rows={"Sales": [12073.0, 16403.0], "Operating Profit": [1694.0, 2936.0],
                                                       "Depreciation": [428.0, 682.0], "OPM %": [14.0, 18.0]})
    page = CompanyPage("COFORGE", "Coforge", "consolidated", "u", {"quarters": q, "annual": an, "balance": Table()},
                       {}, [], [])
    cfg = {"partly_band_relative": .2, "partly_band_points": 1}
    q4 = _dixon_claim("ebit_margin", "point", 15, period="Q4 FY26")
    fy = _dixon_claim("ebit_margin", "point", 14, period="FY26")
    ebitda = _dixon_claim("ebitda_margin", "point", 14, period="FY26")
    promises.judge_all(page, [q4, fy, ebitda], cfg)
    assert q4["verdict"] == "kept" and "EBIT margin Q4 FY26: 15.6%" in q4["reason"]
    assert fy["verdict"] == "partly" and "13.7%" in fy["reason"]
    assert ebitda["verdict"] == "kept" and "Operating margin FY26: 17.9%" in ebitda["reason"]


def test_followup_prompt_states_the_judging_rules():
    """flash-lite counted 'reiterated the FY30 target' as kept and an April->Q2 slip as kept."""
    from api.documents import Doc
    from api.promises import Followups

    seen = {}

    class R:
        def json(self, *, prompt, schema, **kw):
            seen["p"] = prompt
            return Followups()

    docs = [Doc("Q1", "transcript", "u", order=(2026, 1), pages=["a"]), Doc("Q2", "transcript", "u", order=(2026, 5), pages=["b"])]
    promises.qualitative(R(), [{"verdict": "unjudged", "order": (2026, 1), "said_in": "Q1", "statement": "x", "quote": "q"}],
                         docs, 90, 6)
    assert "NOT delivery" in seen["p"] and "SAME period" in seen["p"]
    assert "push back" in seen["p"] and "is missed" in seen["p"]
    assert "BY MANAGEMENT" in promises.EXTRACT_PROMPT and "not the question" in promises.EXTRACT_PROMPT


def test_strong_quota_out_marks_promises_unchecked_and_result_is_not_saved(monkeypatch, tmp_path):
    """Promise judging must not fall back to the cheap model; the result says so and is never cached."""
    from api import precompute, research
    from core.llm import StrongUnavailable

    def fake_run(t, with_annual_report=False, progress=None):
        return {"ticker": t, "promises": [], "promise_score": {"kept": 0, "judged": 0}, "bull": [], "bear": [],
                "complete": False, "trace": {"strong_skipped": ["promise_followup"], "model_calls": 1,
                                             "dropped_uncited": 0, "seconds": 1}}

    monkeypatch.setattr(research, "run", fake_run)
    monkeypatch.setattr(precompute, "WEB_DATA", tmp_path)
    precompute.main(["XYZ"])
    assert not (tmp_path / "research" / "XYZ.json").exists()

    class R:
        def json(self, **kw):
            assert kw.get("allow_fallback") is False
            raise StrongUnavailable("quota")

    from api.documents import Doc

    docs = [Doc("Q1", "transcript", "u", order=(2026, 1), pages=["a"]), Doc("Q2", "transcript", "u", order=(2026, 5), pages=["b"])]
    c = {"verdict": "unjudged", "order": (2026, 1), "said_in": "Q1", "statement": "x", "quote": "q"}
    assert promises.qualitative(R(), [c], docs, 90, 6) is False
    assert c["verdict"] == "unchecked" and c["reason"] == "Not checked today: model limit reached"


def test_api_does_not_cache_incomplete_results(monkeypatch, tmp_path):
    import api.main as m

    monkeypatch.setattr(m, "RESULTS", tmp_path)
    monkeypatch.setattr(m.research, "run", lambda t, p: {"ticker": t, "complete": False})
    m.JOBS["j1"] = {"status": "running"}
    m.ACTIVE["ABC"] = "j1"
    m._work("j1", "ABC")
    assert m.JOBS["j1"]["status"] == "done" and not (tmp_path / "ABC.json").exists()


def test_any_strong_failure_leaves_promises_unchecked():
    from api.documents import Doc

    class R:
        def json(self, **kw):
            raise RuntimeError("Model API error 503: high demand")

    docs = [Doc("Q1", "transcript", "u", order=(2026, 1), pages=["a"]), Doc("Q2", "transcript", "u", order=(2026, 5), pages=["b"])]
    c = {"verdict": "unjudged", "order": (2026, 1), "said_in": "Q1", "statement": "x", "quote": "q"}
    assert promises.qualitative(R(), [c], docs, 90, 6) is False
    assert c["verdict"] == "unchecked" and c["reason"] == "Not checked today: model unavailable"


def test_cheap_model_json_quirks_are_tolerated():
    from api.promises import Claims

    c = Claims.model_validate({"claims": [{"metric": "gross_margin", "statement": "s", "target": {"type": "point"},
                                           "quote": "q", "scope": "division"}]})
    assert c.claims[0].metric == "other" and c.claims[0].scope == "segment"
