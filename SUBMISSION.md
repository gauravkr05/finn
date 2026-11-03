# Submission checklist

Send to **assessment@enam.com** with the subject **ENAM - IIT screening - 2027**.

## What to include

- [ ] **Prototype link** (Vercel URL), tested on a real phone (see DEPLOY.md, step 8)
- [ ] **GitHub repository** link, public, with no `.env` or API keys committed
- [ ] **AI build history**: share links or exports of the AI conversations used to plan and build
      FINN (this planning/build conversation included). In Claude: open the chat → Share → copy link.
- [ ] **README** top section: replace the placeholder links and add 3 phone screenshots
      (Opening Brief with a results card, the sources sheet with a highlighted quote, the Promise Ledger)
- [ ] **Covering email** below, with the bracketed parts filled in and edited into your own voice

Before sending, re-read the email aloud. Every claim in it should be something the reviewer can see
in the app or the code.

---

## Covering email (draft — edit into your own words)

**Subject:** ENAM - IIT screening - 2027

Dear ENAM team,

Please find my submission for the AI Engineer Build Challenge.

- Prototype (open on a phone): [VERCEL LINK]
- Repository: [GITHUB LINK]
- AI build history: [SHARE LINKS]

[If submitting after 1 November: one honest sentence on why, and thanks for considering it.]

**What I built**

FINN is a mobile-first agent built on one idea: an investor shouldn't have to watch an app all day.
FINN speaks at two moments, an Opening Brief before the market opens and a Closing Bell after it
closes, and in between only alerts on thresholds the investor sets. Every item answers what
happened, why it matters to this portfolio, and what to check, and every number can be traced to
the line it came from.

- **Push:** a ranked digest of all filings across an 18-stock portfolio for any window, with routine
  paperwork collapsed. Results cards show Revenue, EBITDA, PBT and PAT, QoQ and YoY, extracted from
  the filing; people cards show who is joining or leaving and their background, taken from the
  filing itself. Price and volume alerts recompute instantly as the investor moves the sliders. A
  swipe-to-triage mode and a spoken brief are there for the 60-second morning check.
- **Pull:** research on any NSE ticker from its own transcripts and annual report. The centrepiece
  is a Promise Ledger: what management guided over the last four calls versus what was delivered,
  with drift detection when guidance is quietly lowered.

**Key decisions and trade-offs**

1. *Rules before models.* Exchange subject lines are regular, so keyword rules classify most filings
   for free; a confidence gate sends only the unclear ones to a cheap model in one batch. [In my last
   run, X of Y filings needed no model call.]
2. *Models read, code calculates.* EBITDA, growth rates and whether a promise was kept are computed
   in Python against reported numbers, never by the model.
3. *Trust is enforced, not requested.* Every quote must be found in its source document or the claim
   is dropped; results are checked against accounting identities and screener.in, and show "verify
   in filing" rather than a wrong number. EBITDA excludes exceptional items, one-offs are flagged,
   and lenders get a different card because EBITDA is meaningless for banks.
4. *Static-first.* The push brief is pre-built JSON on a CDN, so the core demo can't fail; research
   for new companies runs live with visible progress.
5. *Cost.* Model routing (cheap for extraction, stronger only for judgement), caching by content
   hash, and chunking transcripts by speaker turn. The whole demo runs on free tiers; the in-app
   "How FINN works" page shows the cost ledger for the latest run.

**What I left out, deliberately:** trading and recommendations, news and sentiment on the research
side (the brief rules them out, and they're noisy), chat as the main interface, intraday data,
accounts and a hosted database.

**Where I'd take it next:** native push notifications on the two-a-day rhythm; learning each
investor's taste from what they track or dismiss; a grounded "ask about this card"; and deeper
annual-report analysis (related-party transactions, contingent liabilities, auditor remarks).

Some patterns come from earlier work: the confidence-gated funnel and decision log from my intraday
trading pipeline, and the citation guardrail from a citation-backed legal analysis system I built
during an internship.

Thank you for the interesting problem.

Best regards,
Gaurav Kumar
IIT Kanpur, [roll number] | gauravkr23@iitk.ac.in | [phone]
