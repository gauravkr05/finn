# FINN — notes for Claude Code sessions

FINN is Gaurav's submission for ENAM Holdings' AI Engineer Build Challenge: a mobile-first investor
agent for an 18-stock NSE portfolio. README.md is the full design doc (product, architecture, data
contracts); DEPLOY.md is the run/deploy runbook; PLAN.md is the current session plan (phases 1–5).

- **Push** (`pipeline/`): NSE filings → L2 rule classifier (`triage/rules.py`) → L3 confidence gate
  (cheap model only for borderline/unknown, `triage/gate.py`) → L4 materiality score (`triage/score.py`)
  → L5 enrichment for critical/high (results card, people card, key terms; batched one-liners for
  medium) → L6 writes `web/public/data/brief.json` + `prices.json`. Every layer writes to the decision log.
- **Pull** (`api/`): research on any NSE ticker from screener.in tables + last 4 concall transcripts
  (+ annual report for pre-computed tickers) → Promise Ledger, snapshot, bull/bear, citation guardrail.
  FastAPI in `api/main.py`; `api/precompute.py` caches demo tickers.
- **Shared** (`core/`): `llm.py` model router (cheap/strong tiers, disk cache, cost ledger, Pydantic
  validation, timeout/backoff, Gemini thinkingBudget), `http.py` (curl_cffi browser impersonation),
  `screener.py`, `pdftext.py`, `guardrails.py`, `numbers.py`, `config.py` (loads `.env` itself).
- **Web** (`web/`): Vite + React PWA, reads the JSON in `web/public/data`; deployed on Vercel.
  API deployed on Render via `render.yaml` (Python 3.11, `requirements-api.txt`).
- All tunables live in `config.yaml` (portfolio, tiers/weights, alert defaults, model names, rate limits).

## Rules

- Use the venv `.venv` (Python 3.14) for every Python command: `source .venv/bin/activate`.
- `.env` holds `GEMINI_API_KEY`. Never print, read aloud, or commit `.env`. Don't echo the key in
  commands or output (it's sent as a URL param, so don't log request URLs).
- Keep all tests passing (`python -m pytest -q`; 133 as of 2026-11-03). Add a test with every bug fix.
- Don't change the product design or the README architecture. Fix bugs; ask Gaurav before bigger changes.
- Before each fix, explain in one or two sentences what's wrong and why the change fixes it.
- The model reads, Python does arithmetic and validation (results EBITDA, checks, promise verdicts).
- Read each command before running anything that touches `.env`, deletes files, or pushes to GitHub.
  Don't commit or push unless asked.

## GitHub (repo: https://github.com/gauravkr05/finn, `gh` logged in as gauravkr05)

- Before the first commit, show Gaurav `git status` and confirm `.env`, `.venv`, `.cache` and
  `node_modules` are not included.
- Never commit `.env` or any API key. Before every push, scan the staged files for anything that
  looks like a key (e.g. `AIza…`, `sk-…`, `GEMINI_API_KEY=` with a value).
- Never push until Gaurav says "push". Render and Vercel deploy from this repo, so every push redeploys.

## Running things

```bash
source .venv/bin/activate
python -m pytest -q                                   # offline tests, no key needed
python -m core.llm --list                             # Gemini models this key can use
python -W ignore -m pipeline.run_brief                # full brief (overwrites web/public/data/brief.json)
python -W ignore -m pipeline.run_brief --symbols TITAN   # one stock (brief.json then holds only it)
#   --from-cache  reuse pipeline/out/filings.json   --no-llm  rules only   --skip-prices   -v
python -W ignore -m api.precompute <TICKER> --with-annual-report   # pre-compute research
python -m api.precompute <TICKERS> --clear            # remove cached research
uvicorn api.main:app --host 0.0.0.0                   # research API (GET /research/<T>, /health)
cd web && npm install && npm run dev -- --host        # app; open the Network URL on a phone
python scripts/make_sample_data.py                    # sample brief if no live run yet
```

`-W ignore` hides yfinance/pandas deprecation noise. Caches: `.cache/` (PDFs, LLM responses keyed
by model+prompt+doc hash, screener pages, market caps); `pipeline/out/` (raw filings, decision log).

## Known state (2026-11-03)

- Model probing: `gemini-flash-latest`, `gemini-3.7-flash`, `gemini-3.8-flash` returned 503 (high
  demand); 2.5 models are retired for new keys. The free tier gives `gemini-3.5-flash` only
  **20 requests/day**, so (Gaurav's decision) cheap = `gemini-3.5-flash-lite` (own quota,
  `thinkingBudget: 0`). Model calls are precious: never re-run extraction needlessly; LLM responses
  (including validation retries) are cached on disk. Every pro model (`gemini-pro-latest`, `gemini-3.1-pro-preview`) returns
  429 `limit: 0` on this free key, so (Gaurav's decision) strong = `gemini-3.5-flash` with its default
  thinking (no `thinking_budget` key → no thinkingConfig sent). The router falls back strong→cheap on
  404 or on a persistent quota 429 (`limit: 0`/per-day immediately; per-minute only after backoff
  retries are exhausted, since Gemini's RPM errors also say "quota"). The ledger records the model and
  tier that actually answered.
- Filings about incorporating a (wholly owned) subsidiary or a nominal subscription into one are
  `M&A` / subtype `incorporation` (score modifier 0.15 unless the amount is ≥1% of market cap).
  Amounts in foreign currencies are converted with rough rates in `brief.fx_to_inr`.
- TITAN Q2 FY27 results are due 5 Nov 2026 (call at 6 pm IST); the Q1 FY27 filing
  (`TITAN_07082026160159_SEresultQ127.pdf`, consolidated table p. 9) was used to verify extraction.
- Results classification: only the results filing itself is `results/final`; transcripts/recordings
  that mention results are `earnings_call`, results press releases are `results/press`, "scheduled …
  to consider" notices are `intimation`. `group_related` keeps one `final` per company (prefers NSE's
  "has submitted to the Exchange, the financial results" filing) and folds the rest in as related.
- Results Revenue is net of excise duty when the filing shows excise as an expense (ITC), matching
  screener.in; the row keeps `metric: "Revenue"` (speech code looks it up) with `net_of_excise: true`.
- Units: `core.numbers.unit_factor` reads the scale word from free-form headers ("₹ in Crores", "in million");
  an unrecognised unit sets `checks.unit_recognised=False` and flags the rows (never silently crore).
- flash-lite rejects `thinkingBudget: 0` with a bare 400; the router retries once without it and remembers.
- M&A housekeeping subtypes `incorporation` / `strike_off` and `fund_raise/guarantee` (comfort letters,
  guarantees) carry low score modifiers; the gate applies the same detection after a model relabel.
- screener.in: after one network failure the cross-check is skipped for the rest of the run.
- Roles: "Non-Executive Director" is normalised before matching, so it isn't read as "executive director".
- Research (Phase 3): demo tickers DIXON, POLYCAB, PERSISTENT (pre-computed with --with-annual-report);
  live-tested and cleared: COFORGE, ASTRAL, TATAELXSI (good "Try a live ticker" pills). `DEMO.json` in
  web/public/data/research is sample data from make_sample_data.py.
- Promise Ledger rules: one document per quarter (transcript preferred); claims carry `scope`
  (company/segment) — Python judges only company-scope claims in comparable units (% , Nx, ₹ crore);
  segment claims go to the evidence-quoted follow-up. Unstated period = FY in progress at the call date.
  `ebit_margin` = (Operating Profit − Depreciation)/Sales from screener; `ebitda_margin` = OP/Sales.
- Model-cited references echo excerpt tags ("[Q2 FY27 call p.4]"): always resolve them with
  `api.documents.verify_cited`, never by exact label.
- Thinking models: thought parts are dropped, `thinking_headroom_tokens` is added to maxOutputTokens,
  and MAX_TOKENS responses raise instead of being cached.
- NSE results PDFs can print revenue only as components (Titan: sale of products + other operating
  revenue), so revenue may legitimately show as "not found in text layer".
