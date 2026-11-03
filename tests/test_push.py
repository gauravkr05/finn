from datetime import datetime, timedelta, timezone

import pytest

from core.config import load_config
from pipeline.enrich.results import Period, ResultsExtract, compute
from pipeline.enrich.spoken import spoken_brief
from pipeline.moves import detect
from pipeline.run_brief import group_related
from pipeline.triage.rules import classify
from pipeline.triage.score import score_item, stated_amount_crore

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.mark.parametrize("subject,text,cat,sub", [
    ("Outcome of Board Meeting", "Titan Company Limited has informed the Exchange about Financial Results for the quarter ended September 30, 2026", "results", "final"),
    ("Board Meeting Intimation", "to consider and approve the financial results for the quarter ending Sep 2026", "results", "intimation"),
    ("Copy of Newspaper Publication", "Publication of financial results in newspapers", "results", "ad"),
    ("Investor Presentation", "Investor presentation for Q2 FY27", "results", "deck"),
    ("Change in Directorate", "Resignation of Mr. A as Chief Financial Officer", "management_change", None),
    ("Credit Rating", "CRISIL has upgraded the long-term rating to AA+", "credit_rating", "upgrade"),
    ("Credit Rating", "ICRA has reaffirmed the rating", "credit_rating", "reaffirm"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings call held on Oct 30", "earnings_call", "transcript"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meeting with institutional investors", "investor_meetings", None),
    ("Trading Window-XBRL", "Closure of trading window", "unclassified", "trading_window"),
    ("Allotment of ESOP / ESPS", "Allotment of 12,000 equity shares under ESOP 2019", "unclassified", "esop"),
    ("Acquisition", "Acquisition of 100% stake in XYZ Pvt Ltd for Rs. 450 crore", "M&A", None),
    ("Action(s) initiated or orders passed", "GST demand order of Rs. 2.3 crore", "litigation", None),
    ("Disclosure of Encumbrance", "Creation of pledge on promoter shares", "pledging", None),
    ("Shareholders meeting", "Voting results of the AGM", "agm_egm", None),
    ("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Certificate under regulation 74(5)", "unclassified", "registry"),
    ("Press Release", "Company bags order worth Rs 1,200 crore", "press_release", None),
    ("Appointment of Statutory Auditor", "Appointment of M/s ABC as statutory auditors", "unclassified", "auditor"),
])
def test_rules(subject, text, cat, sub):
    c = classify(subject, text)
    assert c.category == cat, (subject, c)
    if sub:
        assert c.subtype == sub


def test_role_and_direction():
    c = classify("Change in Directorate", "Resignation of Mr. A as Chief Financial Officer")
    assert c.role == "top" and c.direction == "negative"
    c = classify("Change in Directorate", "Cessation of Ms. B as Independent Director on completion of tenure")
    assert c.role == "independent"


def test_unknown_goes_to_gate():
    assert classify("Updates", "Some text").confidence == "borderline"
    assert classify("Xyz", "").confidence == "unknown"


def _score(subject, text, weight=0.05, hours_ago=2):
    cfg = load_config()
    now = datetime(2026, 11, 3, 8, 30, tzinfo=IST)
    item = {"subject": subject, "text": text, "filed_at": (now - timedelta(hours=hours_ago)).isoformat()}
    cls = classify(subject, text).as_dict()
    return score_item(item, cls, cfg, weight, set(cfg["alerts"]["categories"]), now)


def test_tiers_make_sense():
    assert _score("Outcome of Board Meeting", "financial results for the quarter ended")["tier"] == "critical"
    assert _score("Change in Directorate", "Resignation of CFO")["tier"] == "critical"
    assert _score("Board Meeting Intimation", "to consider financial results")["tier"] == "routine"
    assert _score("Change in Directorate", "Cessation of independent director")["tier"] in ("medium", "routine")
    assert _score("Credit Rating", "reaffirmed")["tier"] == "medium"
    assert _score("Trading Window", "closure of trading window")["tier"] == "routine"
    assert _score("Analysts/Institutional Investor Meet/Con. Call Updates", "meeting with investors")["tier"] == "routine"


def test_amount_parsing():
    assert stated_amount_crore("order worth Rs 1,200 crore") == 1200
    assert stated_amount_crore("demand of ₹ 45 lakh") == pytest.approx(0.45)
    assert stated_amount_crore("no money here") is None


def _extract(**cur):
    base = dict(revenue=1000, other_income=20, finance_costs=10, depreciation=40, pbt_before_exceptional=200,
                exceptional_items=None, pbt=200, tax=50, pat=150)
    base.update(cur)
    return ResultsExtract(basis="consolidated", unit="crore", period_end="2026-09-30", page=3,
                          current=Period(**base),
                          prev_quarter=Period(revenue=950, other_income=15, finance_costs=10, depreciation=38,
                                              pbt_before_exceptional=190, pbt=190, tax=48, pat=142),
                          year_ago=Period(revenue=800, other_income=12, finance_costs=12, depreciation=35,
                                          pbt_before_exceptional=150, pbt=150, tax=38, pat=112))


def test_results_math():
    body = compute(_extract())
    rows = {r["metric"]: r for r in body["rows"]}
    assert body["period"] == "Q2 FY27"
    assert rows["EBITDA"]["cur"] == 230  # 200 + 10 + 40 - 20
    assert rows["Revenue"]["yoy"] == 25.0
    assert rows["PAT"]["qoq"] == pytest.approx(5.6, abs=0.1)
    assert body["checks"]["tax_identity"] and body["checks"]["pat_le_pbt"]
    assert not body["flags"]


def test_exceptional_flag_and_ebitda_excludes_one_off():
    body = compute(_extract(exceptional_items=60, pbt=260, tax=65, pat=195))
    rows = {r["metric"]: r for r in body["rows"]}
    assert rows["EBITDA"]["cur"] == 230  # one-off does not inflate EBITDA
    assert body["flags"] and "one-off gain" in body["flags"][0]["text"]
    assert body["checks"]["exceptional_identity"]


def test_exceptional_printed_sign_is_normalised():
    # Titan Q4 FY26 style: "Exceptional item (51)" with "PBT = VII - VIII": 1,526 -> 1,577 is a gain.
    body = compute(_extract(pbt_before_exceptional=200, exceptional_items=-60, pbt=260, tax=65, pat=195))
    assert body["checks"]["exceptional_identity"]
    assert not any(r.get("verify") for r in body["rows"])
    assert "one-off gain" in body["flags"][0]["text"]


def test_exceptional_magnitude_error_still_flagged():
    body = compute(_extract(pbt_before_exceptional=200, exceptional_items=-25, pbt=260, tax=65, pat=195))
    assert body["checks"]["exceptional_identity"] is False
    assert {r["metric"]: r for r in body["rows"]}["PBT"].get("verify") is True


def test_provenance_prefers_reported_results_page():
    # A press release on p.1 quotes PBT and PAT; the statement is on p.3 (the page the model reported).
    texts = ["Press release: Profit before tax 200 crores, PAT 150", "notes",
             "Revenue from operations 1,000 ... Profit before tax 200 ... Net profit 150"]
    body = compute(_extract(), page_texts=texts)
    assert body["provenance"] == {"revenue": 3, "pbt": 3, "pat": 3}


def test_results_verify_on_bad_identity():
    body = compute(_extract(pat=190))  # 200 - 50 != 190
    rows = {r["metric"]: r for r in body["rows"]}
    assert rows["PAT"].get("verify") is True


def test_lakh_units_normalised():
    ex = _extract()
    ex.unit = "lakhs"
    body = compute(ex)
    assert {r["metric"]: r for r in body["rows"]}["Revenue"]["cur"] == 10.0


def test_lender_layout():
    ex = ResultsExtract(basis="standalone", unit="crore", company_type="lender", period_end="2026-09-30",
                        current=Period(revenue=900, other_income=100, pbt_before_exceptional=300, pbt=300,
                                       tax=75, pat=225, provisions=80))
    body = compute(ex, kind="lender")
    metrics = [r["metric"] for r in body["rows"]]
    assert metrics == ["Total income", "Pre-provision profit", "PBT", "PAT"]
    assert body["rows"][1]["cur"] == 380


def test_numeric_provenance():
    body = compute(_extract(), page_texts=["cover", "Revenue from operations 1,000.00 ... Profit before tax 200.00 "
                                                    "Net profit 150.00"])
    assert body["provenance"]["revenue"] == 2 and body["checks"]["found_in_text_layer"]


def test_moves_detection():
    rows = [{"d": f"2026-10-{i:02d}", "c": 100.0, "v": 1000} for i in range(1, 26)]
    rows.append({"d": "2026-10-26", "c": 94.0, "v": 3500})
    m = detect({"X": rows}, ["X"], 2.0, 4.0, 20)
    assert m and m[0]["trigger"] == "both" and m[0]["volume_ratio"] == 3.5


def test_group_related_folds_satellites():
    cards = [
        {"id": "a", "symbol": "T", "category": "results", "subtype": "final", "filed_at": "2026-11-02T18:00:00+05:30", "title": "r"},
        {"id": "b", "symbol": "T", "category": "results", "subtype": "deck", "filed_at": "2026-11-02T18:30:00+05:30", "title": "deck"},
        {"id": "c", "symbol": "T", "category": "earnings_call", "subtype": "intimation", "filed_at": "2026-10-29T10:00:00+05:30", "title": "call"},
        {"id": "d", "symbol": "U", "category": "results", "subtype": "deck", "filed_at": "2026-11-02T18:30:00+05:30", "title": "deck"},
    ]
    out = group_related(cards)
    assert [c["id"] for c in out] == ["a", "d"] and len(out[0]["related"]) == 2


def test_spoken_brief_reads_naturally():
    card = {"symbol": "TITAN", "company": "Titan Company", "tier": "critical", "kind": "results",
            "body": compute(_extract())}
    s = spoken_brief([card], [{"symbol": "CDSL", "move_pct": -6.4, "volume_ratio": 3.1}], 21)
    assert "revenue up 25 percent year on year" in s and "%" not in s and "21 routine filings" in s


# ---- new-subsidiary incorporation (Titan Canada, NSE 28-Oct-2026) and foreign-currency amounts ----
TITAN_SUBJ = "Acquisition"
TITAN_TEXT = ("Titan Company Limited has informed the Exchange about the Company has incorporated Titan Company "
              "Canada Inc. as its wholly owned subsidiary.")


def test_titan_canada_incorporation_is_not_critical():
    c = classify(TITAN_SUBJ, TITAN_TEXT)
    assert (c.category, c.subtype, c.confidence) == ("M&A", "incorporation", "high")
    sc = _score(TITAN_SUBJ, TITAN_TEXT, weight=0.05, hours_ago=2)  # filed in the last 24h: recency bonus too
    assert sc["tier"] in ("medium", "routine")
    assert "new subsidiary set-up" in sc["why"]
    # even the biggest holding (9%) stays out of high
    assert _score(TITAN_SUBJ, TITAN_TEXT, weight=0.09)["tier"] in ("medium", "routine")


@pytest.mark.parametrize("subject,text", [
    ("Acquisition", "Acquisition of 10,000 equity shares of the newly incorporated wholly owned subsidiary, XYZ Pte Ltd"),
    ("General Updates", "Initial subscription of CAD 5,000 to the share capital of the wholly owned subsidiary"),
    ("Updates", "The Company has set up a wholly owned subsidiary in the UAE"),
])
def test_other_incorporation_wordings(subject, text):
    assert classify(subject, text).subtype == "incorporation"


@pytest.mark.parametrize("subject,text", [
    ("Acquisition", "Acquisition of 100% stake in XYZ Pvt Ltd for Rs. 450 crore"),
    ("Acquisition", "Acquisition of XYZ Pte Ltd, a company incorporated in Singapore; it becomes a wholly owned "
                    "subsidiary of the Company"),
    ("Scheme of Arrangement", "Scheme of amalgamation of the wholly owned subsidiary with the Company"),
    ("Sale of stake", "Sale of stake in subsidiary ABC Ltd for Rs 1,000 crore"),
])
def test_real_deals_are_not_incorporation(subject, text):
    c = classify(subject, text)
    assert c.category == "M&A" and c.subtype != "incorporation"


def test_real_acquisition_still_critical():
    assert _score("Acquisition", "Acquisition of 100% stake in XYZ Pvt Ltd for Rs. 450 crore")["tier"] == "critical"


def test_large_subscription_into_subsidiary_not_buried():
    item = {"subject": "Updates", "text": "Subscription to the share capital of the wholly owned subsidiary "
                                          "for Rs 20,000 crore", "filed_at": datetime(2026, 11, 3, 6, tzinfo=IST).isoformat()}
    cfg = load_config()
    cls = classify(item["subject"], item["text"]).as_dict()
    assert cls["subtype"] == "incorporation"
    sc = score_item(item, cls, cfg, 0.05, set(cfg["alerts"]["categories"]), datetime(2026, 11, 3, 8, 30, tzinfo=IST),
                    mcap_cr=300000)
    assert "subtype" not in sc["score_parts"] and sc["tier"] == "critical"


@pytest.mark.parametrize("text,cr", [
    ("to be subscribed in cash (not exceeding 5,000 Canadian Dollars)", 0.031),
    ("initial investment of CAD 5,000", 0.031),
    ("deal value of US$ 25 million", 215.0),
    ("USD 1.2 bn", 10320.0),
    ("consideration of €5 million", 48.5),
    ("AED 10 mn", 23.4),
    ("order worth Rs 1,200 crore and USD 2 million", 1200.0),
])
def test_foreign_currency_amounts(text, cr):
    assert stated_amount_crore(text) == pytest.approx(cr, rel=0.01)


def test_foreign_amount_is_tiny_vs_market_cap():
    cfg = load_config()
    item = {"subject": "Acquisition", "text": "Acquisition of 100% stake in XYZ Ltd for CAD 5,000",
            "filed_at": datetime(2026, 11, 2, 8, tzinfo=IST).isoformat()}
    cls = classify(item["subject"], item["text"]).as_dict()
    sc = score_item(item, cls, cfg, 0.05, set(cfg["alerts"]["categories"]), datetime(2026, 11, 3, 8, 30, tzinfo=IST),
                    mcap_cr=300000)
    assert sc["score_parts"]["size"] == 0.15 and sc["tier"] != "critical"


# ---- results satellites and roles: real NSE texts from the 3-Nov-2026 portfolio run ----
@pytest.mark.parametrize("subject,text,cat,sub", [
    ("Analysts/Institutional Investor Meet/Con. Call Updates",
     "Transcript of the discussion on the Unaudited Financial Results (Consolidated and Standalone) of the Company for "
     "the quarter and half year ended September 30, 2026, at the analyst meet held on October 30, 2026, is attached",
     "earnings_call", "transcript"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates",
     "Audio recording of the discussion on the Unaudited Financial Results (Consolidated and Standalone) of the Company",
     "earnings_call", "recording"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates",
     "ICICI Bank Limited has informed the Exchange about transcript of the call with media and of earnings call with "
     "analysts and investors on the financial results for the quarter and six months ended September 30, 2026",
     "earnings_call", "transcript"),
    ("Press Release", "In continuation of our letter of today's date on the Unaudited Financial Results (Consolidated "
                      "and Standalone) for the quarter, we attach a copy of media release being issued by the Company.",
     "results", "press"),
    ("Press Release", 'Maruti Suzuki India Limited has informed the Exchange regarding a press release dated October 27, '
                      '2026, titled "Maruti Suzuki India Limited Financial Results Q2 and H1 FY 2026-27".', "results", "press"),
    ("General Updates", "Trading in equity shares of Jio Platforms Limited (JPL) will commence from October 28, 2026."
                        "Further, a meeting of board of directors of JPL is scheduled to be held on Friday, October 30, "
                        "2026, inter alia, to consider and approve the standalone and consolidated unaudited financial "
                        "results of JPL", "results", "intimation"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates",
     "The meeting of the Board of Directors of the Company is scheduled on October 30, 2026, inter alia, to consider and "
     "approve a. the standalone and consolidated unaudited financial results", "results", "intimation"),
    ("Dividend", "The Board of Directors at its meeting held today has approved the audited standalone and unaudited "
                 "consolidated financial results and payment of interim dividend of Rs. 5.75", "dividend", None),
    ("Outcome of Board Meeting", "In continuation of our letter dated October 27, 2026, we wish to inform you that the "
                                 "Board at its meeting held today, has, inter alia: approved the unaudited Financial "
                                 "Results (Consolidated and Standalone) for the quarter", "results", "final"),
])
def test_results_satellites(subject, text, cat, sub):
    c = classify(subject, text)
    assert (c.category, c.subtype) == (cat, sub)


@pytest.mark.parametrize("text,role", [
    ("Trent Limited has informed the Exchange regarding Appointment of Mr Rajiv Dube as Non- Executive Director of the "
     "company w.e.f. October 30, 2026.", "independent"),
    ("Appointment of Mr. A as Non-Executive Director", "independent"),
    ("KPIT Technologies Limited has informed the Exchange regarding Appointment of Independent Director, Mr. Anant "
     "Talaulicar - Chairman of the Board, on the Board of KPIT Technologies Inc., material subsidiary", "independent"),
    ("Trent Limited has informed the Exchange about Retirement of Mr. Noel N Tata as the Chairman", "top"),
    ("Change in Managing Director and Chief Executive Officer of the Bank", "top"),
    ("Appointment of Mr. B as Executive Director", "top"),
])
def test_roles(text, role):
    assert classify("Appointment", text).role == role


def test_group_related_one_parent_per_company():
    now = datetime(2026, 10, 29, 18, tzinfo=IST)
    mk = lambda i, cat, sub, text, h: {"id": str(i), "symbol": "ASIANPAINT", "category": cat, "subtype": sub,
                                       "title": f"t{i}", "text": text, "url": None,
                                       "filed_at": (now - timedelta(hours=h)).isoformat()}
    cards = [mk(1, "results", "final", "The Board ... approved the results", 3),
             mk(2, "results", "final", "Asian Paints Limited has submitted to the Exchange, the financial results", 2),
             mk(3, "results", "press", "media release on results", 1),
             mk(4, "results", None, "Outcome of Board Meeting held today", 2.5)]
    out = group_related(cards)
    assert [c["id"] for c in out] == ["2"]
    assert {r["title"] for r in out[0]["related"]} == {"t1", "t3", "t4"}


def test_gate_outcome_relabelled_as_results_is_final():
    from pipeline.triage.gate import Label, Labels, apply_gate

    class FakeRouter:
        def available(self, tier="cheap"):
            return True

        def json(self, **kw):
            return Labels(labels=[Label(id="a", category="results"), Label(id="b", category="results")])

    items = [{"id": "a", "subject": "Outcome of Board Meeting",
              "text": "Trent Limited has submitted to the Exchange about Outcome of Board Meeting held today"},
             {"id": "b", "subject": "Updates",
              "text": "Report of auditors on financial statements for the quarter and half year ended September 30, 2026"}]
    for it in items:
        it["cls"] = classify(it["subject"], it["text"]).as_dict()
    apply_gate(items, FakeRouter())
    assert items[0]["cls"]["category"] == "results" and items[0]["cls"]["subtype"] == "final"
    assert items[1]["cls"]["category"] == "results" and "subtype" not in items[1]["cls"]


def test_revenue_net_of_excise_itc_q2fy27():
    # ITC consolidated, Q2 FY27 filing p.9: revenue from operations and excise duty (₹ crore)
    ex = ResultsExtract(
        basis="consolidated", unit="crore", period_end="2026-09-30", page=9,
        current=Period(revenue=30578.40, excise_duty=10309.77, other_income=507.36, finance_costs=38.27,
                       depreciation=490.60, pbt_before_exceptional=5720.28, exceptional_items=-25.66, pbt=5694.62,
                       tax=1465.29, pat=4229.33),
        prev_quarter=Period(revenue=29523.30, excise_duty=10408.93, pbt=5860.85, pat=4508.79),
        year_ago=Period(revenue=21255.86, excise_duty=1754.23, pbt=6978.68, pat=5186.55))
    body = compute(ex, screener_revenue={"Sep 2026": 20269.0})
    rev = body["rows"][0]
    assert rev["metric"] == "Revenue" and rev["net_of_excise"] and rev["cur"] == pytest.approx(20268.6, abs=0.1)
    assert rev["yoy"] == pytest.approx(3.9, abs=0.1)  # gross would have shown +43.9%
    assert body["checks"]["cross_check_screener"] and "verify" not in rev
    assert "net of excise" in body["note"]
    assert body["margins"]["ebitda_margin"] == pytest.approx(5741.8 / 20268.6 * 100, abs=0.1)


def test_no_excise_line_keeps_revenue_as_printed():
    body = compute(_extract())
    assert body["rows"][0]["cur"] == 1000 and "net_of_excise" not in body["rows"][0]


@pytest.mark.parametrize("unit,factor", [
    ("in million", 0.1), ("in Million", 0.1), ("(₹ Mn)", 0.1), ("fin Million", 0.1),   # SUNPHARMA/MARUTI/KPIT
    ("₹ in Crores", 1.0), ("Rupees in Crores", 1.0), ("(Rupees in Crores unless otherwise stated)", 1.0),
    ("Rs. In Crore", 1.0), ("₹ crore", 1.0), ("Crore", 1.0), ("Rs in crores", 1.0),
    ("Rs. in lakhs", 0.01), ("₹ in Lacs", 0.01), ("in billion", 100.0), ("₹ in thousands", 1e-4),
    ("Rupees", 1e-7), ("in ₹", 1e-7), ("furlongs", None), ("", None),
])
def test_unit_factor(unit, factor):
    from core.numbers import unit_factor
    assert unit_factor(unit) == (pytest.approx(factor) if factor is not None else None)


def test_million_filing_converted_to_crore():
    # KPITTECH Q2 FY27 consolidated (p.9, "₹ in million"): revenue 16,909.66 mn = ₹1,691 cr
    ex = _extract(revenue=16909.66)
    ex.unit = "in million"
    assert compute(ex)["rows"][0]["cur"] == pytest.approx(1691.0, abs=0.1)


def test_unknown_unit_is_flagged_not_guessed():
    ex = _extract()
    ex.unit = "furlongs"
    body = compute(ex)
    assert body["checks"]["unit_recognised"] is False
    rows = {r["metric"]: r for r in body["rows"]}
    assert rows["Revenue"]["verify"] and rows["PAT"]["verify"]


@pytest.mark.parametrize("subject,text", [
    ("Sale or disposal", "KPIT Technologies Limited has informed the Exchange that the Board of Directors of the Company "
                         "approved the Strike-off of Somit Solutions Limited, wholly owned step-down subsidiary of the Company."),
    ("Other Restructuring", "Disclosure under Regulation 30 of the Securities and Exchange Board of India (Listing "
                            "Obligations and Disclosure Requirements) Regulations, 2015   Voluntary strike off of Hamleys "
                            "(Franchising) Limited"),
])
def test_subsidiary_strike_off_is_low(subject, text):
    c = classify(subject, text)
    assert (c.category, c.subtype, c.confidence) == ("M&A", "strike_off", "high")
    assert _score(subject, text, weight=0.09)["tier"] in ("medium", "routine")


def test_sale_of_subsidiary_is_not_strike_off():
    c = classify("Sale or disposal", "Sale of stake in subsidiary ABC Ltd; the subsidiary will be dissolved after the sale")
    assert c.subtype != "strike_off"


def test_gate_relabel_to_ma_detects_housekeeping():
    from pipeline.triage.gate import Label, Labels, apply_gate

    class FakeRouter:
        def available(self, tier="cheap"):
            return True

        def json(self, **kw):
            return Labels(labels=[Label(id="a", category="M&A")])

    it = {"id": "a", "subject": "General Updates", "text": "Update on the winding up of XYZ Pte Ltd, a step-down subsidiary"}
    it["cls"] = {"category": "unclassified", "confidence": "borderline"}
    apply_gate([it], FakeRouter())
    assert it["cls"]["category"] == "M&A" and it["cls"]["subtype"] == "strike_off"


def test_letter_of_comfort_is_not_ma():
    subj = "Giving guarantees/indemnity/ becoming a surety for third party"
    text = ("KPIT Technologies Limited has informed the Exchange about Issue of Letter of Comfort in favor of KPIT "
            "Technologies (UK) Limited, a wholly-owned subsidiary of the Company.")
    c = classify(subj, text)
    assert (c.category, c.subtype, c.confidence) == ("fund_raise", "guarantee", "high")
    assert _score(subj, text, weight=0.03)["tier"] in ("medium", "routine")
