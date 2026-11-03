"""Layer 2: keyword classifier for exchange filings.

Exchange subject lines are highly regular ("Outcome of Board Meeting", "Change in Directorate",
"Credit Rating"), so most filings can be classified for free. Each result carries a confidence:

- high:       the subject line (or an unambiguous phrase) decides it  -> no model call
- borderline: only weak body-text evidence                            -> cheap model decides
- unknown:    nothing matched                                         -> cheap model classifies

Also extracted here, for scoring: subtype (e.g. results "intimation" vs "final"), the role in a
management change, and the direction of a change (upgrade/downgrade, resignation, pledge created).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]


@dataclass
class Classification:
    category: str
    confidence: str                 # high | borderline | unknown
    subtype: str | None = None
    role: str | None = None         # top | kmp | director | independent | secretarial
    direction: str | None = None    # positive | negative | neutral
    rule: str = ""
    also: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}


_CACHE: dict[str, re.Pattern] = {}


def _pat(p: str) -> re.Pattern:
    if p not in _CACHE:
        prefix = p.endswith("*")
        core = re.escape(p.rstrip("*"))
        _CACHE[p] = re.compile(r"(?<![a-z0-9])" + core + ("" if prefix else r"(?![a-z0-9])"))
    return _CACHE[p]


def has(text: str, *pats: str) -> bool:
    return any(_pat(p).search(text) for p in pats)


ROLE_TOP = ("chief executive*", "ceo", "chief financial*", "cfo", "managing director", "md", "md & ceo",
            "whole time director", "whole-time director", "wholetime director", "executive director",
            "executive chairman")
ROLE_CHAIR = ("chairman", "chairperson")
ROLE_INDEP = ("independent director", "nonexecutive*", "nominee director")
ROLE_SEC = ("company secretary", "compliance officer")
ROLE_KMP = ("key managerial*", "kmp", "senior management", "chief operating*", "coo", "cto",
            "chief technology*", "chief risk*", "chief human*", "chro", "chief business*", "business head",
            "chief information*", "cio", "president")


def _role(a: str) -> str:
    # "Non- Executive Director" must not match "executive director", so normalise it first.
    a = re.sub(r"non[\s-]*executive", "nonexecutive", a)
    if has(a, *ROLE_TOP):
        return "top"
    # An independent / non-executive appointment that merely mentions "Chairman of the Board" stays independent.
    if has(a, *ROLE_INDEP):
        return "independent"
    if has(a, *ROLE_CHAIR):
        return "top"
    if has(a, *ROLE_SEC):
        return "secretarial"
    if has(a, *ROLE_KMP):
        return "kmp"
    return "director"


def _also(a: str) -> list[str]:
    tags = []
    if has(a, "resignation*", "appointment*", "cessation"):
        tags.append("management_change")
    if has(a, "dividend*"):
        tags.append("dividend")
    if has(a, "acquisition*", "acquire*", "amalgamation", "merger", "demerger", "joint venture"):
        tags.append("M&A")
    if has(a, "qualified institutions placement", "qip", "preferential*", "rights issue", "buyback", "buy-back",
           "non-convertible debenture*", "fund raising", "raising of funds"):
        tags.append("fund_raise")
    if has(a, "capex", "capacity expansion", "capital expenditure", "new plant"):
        tags.append("capex")
    return tags


_SUBSIDIARY = ("subsidiary", "subsidiaries", "step-down", "step down")
_INCORPORATED = ("has incorporated", "have incorporated", "has been incorporated", "incorporation of", "incorporated a",
                 "incorporated as", "set up a", "setting up of", "setting up a", "formation of")
_NOMINAL = ("initial subscription", "nominal", "subscription to the share capital", "subscription to share capital",
            "subscription to the equity", "subscribed to the share capital")
# Words that mean a real transaction with an outside party. Exchange subjects often say "Acquisition" for a
# new subsidiary, so only the body is checked.
_REAL_DEAL = ("acquisition of", "acquire*", "acquired", "share purchase agreement", "amalgamation", "merger",
              "demerger", "scheme of arrangement", "slump sale", "business transfer agreement", "divest*",
              "disinvest*", "sale of stake", "stake sale", "joint venture")


_STRIKE_OFF = ("strike off", "strike-off", "struck off", "striking off", "voluntary liquidation", "members' voluntary",
               "dissolution of", "dissolved", "winding up of", "winding-up of", "deregistration", "de-registration")


def ma_subtype(a: str, b: str) -> str | None:
    """Group-housekeeping M&A that is rarely material: a new or dissolved subsidiary."""
    if has(a, *_STRIKE_OFF) and not has(b, *_REAL_DEAL):
        return "strike_off"
    if _is_incorporation(a, b):
        return "incorporation"
    return None


def _is_incorporation(a: str, b: str) -> bool:
    """A newly incorporated (wholly owned) subsidiary, or a nominal investment into one: M&A on paper,
    rarely material. An acquisition notice describing its target as "a company incorporated in X" is not."""
    if not has(a, *_SUBSIDIARY):
        return False
    if has(a, "newly incorporated", "newly formed", "newly set up", "newly set-up"):
        return True
    return has(a, *_INCORPORATED, *_NOMINAL) and not has(b, *_REAL_DEAL)


def classify(subject: str, text: str = "") -> Classification:
    s = (subject or "").lower()
    b = (text or "").lower()
    a = f"{s} || {b}"

    # --- routine paperwork that would otherwise trip other rules ---------------------------
    if has(a, "trading window"):
        return Classification("unclassified", "high", "trading_window", rule="trading window")
    if has(a, "74(5)", "regulation 74", "loss of share certificate*", "duplicate share certificate*",
           "issue of duplicate*", "spurious*"):
        return Classification("unclassified", "high", "registry", rule="registry paperwork")
    if has(s, "newspaper publication", "copy of newspaper*") or has(a, "newspaper advertisement*"):
        if has(a, "result*"):
            return Classification("results", "high", "ad", rule="results newspaper ad")
        return Classification("unclassified", "high", "newspaper", rule="newspaper publication")
    if has(a, "statutory auditor*", "secretarial auditor*", "cost auditor*", "internal auditor*", "scrutinizer*",
           "registrar and share transfer*", "registrar & share transfer*"):
        return Classification("unclassified", "high", "auditor", rule="auditor/scrutinizer appointment")

    # --- results ---------------------------------------------------------------------------
    results_words = ("financial result*", "results for the quarter", "results for quarter", "unaudited result*",
                     "audited result*", "quarterly result*", "limited review report", "standalone and consolidated result*")
    deck_words = ("investor presentation", "earnings presentation", "results presentation", "earnings update")
    if has(s, *deck_words):
        return Classification("results", "high", "deck", rule="results deck")
    if has(a, *results_words):
        # Many satellite filings mention "financial results"; only the results filing itself is "final".
        if has(b, "transcript*"):
            return Classification("earnings_call", "high", "transcript", rule="results call transcript")
        if has(b, "audio recording*", "video recording*", "recording of", "audio/video", "webcast"):
            return Classification("earnings_call", "high", "recording", rule="results call recording")
        if not has(s, "outcome") and (
                has(s, "board meeting intimation", "prior intimation", "intimation of board meeting")
                or has(b, "is scheduled", "scheduled on", "scheduled to be held", "will be held", "to consider and approve",
                       "inter alia, to consider", "inter-alia, to consider", "prior intimation")):
            return Classification("results", "high", "intimation", rule="results board-meeting intimation")
        if has(s, "press release", "media release") or has(b, "media release", "press release"):
            return Classification("results", "high", "press", rule="results press release")
        if has(s, "dividend*"):  # the same board outcome filed again under the "Dividend" subject
            return Classification("dividend", "high", rule="dividend (results outcome)", also=["results"])
        return Classification("results", "high", "final", rule="results filing", also=_also(b))
    if has(a, *deck_words):
        return Classification("results", "high", "deck", rule="results deck")

    # --- pledging / insider / credit rating ------------------------------------------------
    if has(a, "pledge*", "encumbrance*", "invocation of*"):
        direction = "positive" if has(a, "release*", "revocation", "revoked") else "negative"
        return Classification("pledging", "high", direction=direction, rule="pledge/encumbrance")
    if has(a, "insider trading", "regulation 7(2)", "reg. 7(2)", "reg 7(2)", "prohibition of insider trading") \
            or has(s, "sast", "takeover*", "substantial acquisition*"):
        direction = "negative" if has(a, "sale", "sold", "dispos*") else "positive" if has(a, "acqui*", "purchase*", "bought") else "neutral"
        return Classification("insider_trading", "high", direction=direction, rule="insider/SAST disclosure")
    if has(a, "credit rating*", "crisil", "icra", "care ratings", "careedge", "care edge", "india ratings",
           "acuite", "brickwork", "rating agency"):
        if has(a, "upgrad*"):
            return Classification("credit_rating", "high", "upgrade", direction="positive", rule="rating upgrade")
        if has(a, "downgrad*", "negative watch", "watch with negative*"):
            return Classification("credit_rating", "high", "downgrade", direction="negative", rule="rating downgrade")
        return Classification("credit_rating", "high", "reaffirm", direction="neutral", rule="rating reaffirmed/assigned")

    # --- management change ------------------------------------------------------------------
    mgmt_subject = has(s, "change in directorate", "change in director*", "change in management",
                       "change in key managerial*", "resignation*", "appointment*", "cessation", "re-appointment",
                       "reappointment", "retirement")
    mgmt_body = has(b, "resignation of", "appointment of", "cessation of", "resigned as", "appointed as",
                    "has resigned", "steps down", "superannuation")
    if mgmt_subject or mgmt_body:
        direction = "negative" if has(a, "resign*", "cessation", "steps down", "step down") else "neutral"
        return Classification("management_change", "high" if mgmt_subject else "borderline",
                              role=_role(a), direction=direction, rule="management change")

    # --- earnings call / investor meetings ----------------------------------------------------
    # NSE files both calls and investor meetings under "Analysts/Institutional Investor Meet/Con. Call Updates",
    # so when the subject is that combined label, the body decides.
    call = b if has(s, "investor meet*") else a
    if has(call, "transcript*"):
        return Classification("earnings_call", "high", "transcript", rule="concall transcript")
    if has(call, "audio recording*", "recording of", "video recording*", "webcast", "audio/video", "audio link"):
        return Classification("earnings_call", "high", "recording", rule="concall recording")
    if has(call, "earnings call", "conference call", "con. call", "concall", "con call", "earnings conference*"):
        return Classification("earnings_call", "high", "intimation", rule="concall notice")
    if has(a, "analyst*", "institutional investor*", "investor meet*", "investors meet*", "roadshow", "road show",
           "investor conference*", "one-on-one", "group meeting*"):
        return Classification("investor_meetings", "high", rule="investor meeting")

    # --- corporate actions ---------------------------------------------------------------------
    if has(a, "esop*", "esos", "esps", "employee stock*", "employees stock*"):
        return Classification("unclassified", "high", "esop", rule="ESOP allotment")
    if has(s, "guarantee*", "surety", "letter of comfort", "letters of comfort") or has(
            b, "letter of comfort", "corporate guarantee", "becoming a surety"):
        # Comfort letters / guarantees backing a subsidiary's borrowing: debt-side, not a deal.
        return Classification("fund_raise", "high", "guarantee", rule="guarantee / letter of comfort")
    sub = ma_subtype(a, b)
    if sub == "incorporation":
        return Classification("M&A", "high", sub, rule="new subsidiary incorporated / nominal investment")
    if sub == "strike_off":
        return Classification("M&A", "high", sub, rule="subsidiary strike-off / dissolution")
    ma = ("acquisition*", "acquire*", "amalgamation", "merger", "demerger", "scheme of arrangement", "joint venture",
          "share purchase agreement", "strategic investment", "stake in", "divest*", "disinvest*", "sale of stake",
          "slump sale", "business transfer agreement")
    if has(a, *ma):
        return Classification("M&A", "high" if has(s, *ma) or has(s, "regulation 30") else "borderline", rule="M&A")
    fr = ("qualified institutions placement", "qip", "rights issue", "preferential issue", "preferential allotment",
          "buyback", "buy-back", "buy back", "commercial paper*", "non-convertible debenture*", "ncd*",
          "fund raising", "raising of funds", "bond issue", "debenture*", "warrants")
    if has(a, *fr):
        return Classification("fund_raise", "high" if has(s, *fr) or has(s, "allotment*") else "borderline",
                              rule="fund raise")
    lit = ("litigation*", "order passed", "orders passed", "action(s) initiated", "actions initiated", "penalty",
           "show cause", "demand order", "tax demand", "insolvency", "nclt", "nclat", "arbitral award", "arbitration",
           "high court", "supreme court", "tribunal", "regulatory action", "sebi order", "adjudication*", "fine imposed")
    if has(a, *lit):
        return Classification("litigation", "high" if has(s, *lit) else "borderline", rule="litigation/regulatory")
    capex = ("capacity expansion", "capex", "capital expenditure", "new plant", "greenfield", "brownfield",
             "manufacturing facility", "commercial production", "commissioning", "commissioned", "new facility")
    if has(a, *capex):
        return Classification("capex", "high" if has(s, *capex) else "borderline", rule="capex")
    if has(a, "bonus issue", "bonus share*", "sub-division", "subdivision", "stock split", "split of"):
        return Classification("bonus_split", "high", rule="bonus/split")
    if has(a, "dividend*"):
        return Classification("dividend", "high", rule="dividend")
    if has(a, "postal ballot"):
        return Classification("postal_ballot", "high", rule="postal ballot")
    if has(a, "annual general meeting", "agm", "extra-ordinary general meeting", "extraordinary general meeting",
           "egm", "shareholders meeting", "shareholders' meeting", "scrutinizer*", "voting result*", "e-voting"):
        return Classification("agm_egm", "high", rule="AGM/EGM")
    if has(a, "record date"):
        return Classification("dividend", "borderline", rule="record date")

    # --- routine compliance ----------------------------------------------------------------------
    if has(a, "compliance certificate", "certificate under", "brsr", "business responsibility*",
           "sustainability report*", "esg", "secretarial compliance", "regulation 24a", "reconciliation of share capital",
           "statement of deviation*", "related party transaction*", "investor complaint*", "registrar",
           "shareholding pattern", "allotment of*", "closure of", "familiarisation", "familiarization",
           "loss of certificate*", "change in address", "registered office"):
        return Classification("unclassified", "high", "compliance", rule="routine compliance")

    # --- general news ----------------------------------------------------------------------------
    pr = ("order win*", "bagged", "receipt of order*", "order from", "orders from", "order received", "contract*",
          "launch*", "partnership", "collaboration", "clarification*", "agreement", "mou", "approval from", "usfda")
    if has(s, "press release", "media release"):
        return Classification("press_release", "high", rule="press release")
    if has(a, *pr):
        return Classification("press_release", "borderline", rule="general news")
    if has(s, "outcome of board meeting", "board meeting intimation", "general update*", "update*"):
        return Classification("unclassified", "borderline", rule="generic update")
    return Classification("unclassified", "unknown", rule="no rule matched")
