# FINN – Claude Code Session Plan

## Before the first prompt

Open a terminal in Code-OSS and start Claude Code from the project folder:

```bash
cd ~/Music/finn
claude
```

Throughout, read each command or change before approving it, especially anything touching .env, deleting files, or pushing to GitHub.

---

## Phase 1: Understand the project and get the brief working

This is FINN, my submission for ENAM Holdings' AI Engineer Build Challenge: a mobile-first investor agent with a push side (prioritised brief of NSE filings, results/people cards, price and volume alerts) and a pull side (research on any NSE ticker with a "Promise Ledger"). Read README.md and DEPLOY.md first, then skim core/, pipeline/ and api/.

### Rules for this whole session

- The venv is .venv (Python 3.14). Activate it for every Python command.
- .env holds my GEMINI_API_KEY. Never print, read aloud, or commit .env.
- Keep all 40 tests passing (`python -m pytest -q`). Add a test when you fix a bug.
- Don't change the product design or the architecture described in the README. Fix bugs; ask me before bigger changes.
- Before each fix, explain in one or two sentences what's wrong and why your change fixes it.

### Tasks

1. Check core/llm.py has timeout handling and the "thinking_budget" setting. If not, add them: retry timeouts and connection errors with backoff and then raise RuntimeError; send thinkingConfig with thinkingBudget 0 for the cheap Gemini tier and retry without it if the API rejects it. Also add `timeout_s: 90` under models and `thinking_budget: 0` on the cheap model in config.yaml. In pipeline/run_brief.py, make sure one failed enrichment can never stop the run.
2. Run `python -m core.llm --list` and make sure the model names in config.yaml exist for my key. Prefer specific versioned names if the "-latest" ones are overloaded.
3. Run: `python -W ignore -m pipeline.run_brief --symbols TITAN`
   Fix whatever breaks in the NSE fetch, the PDF download, or the Gemini extraction. Then show me the TITAN card from web/public/data/brief.json, and check the results numbers against the actual filing PDF.
4. Create a CLAUDE.md summarising the project, the rules above, and how to run things, so future sessions start with this context.

**(For me)** When it finishes, check the Titan numbers yourself: open the results PDF and compare Revenue and PAT.

---

## Phase 2: The full portfolio, and the app on your phone

Now run the full portfolio: `python -W ignore -m pipeline.run_brief`

If NSE fails for some stocks, retry with --from-cache or a short pause; fix real bugs. When it finishes, summarise: filings per tier, how many were classified by rules vs the model, how many results/people/keyterms cards were built, how many failed and why, and the cost ledger.

Then look at every critical and high card in brief.json and tell me any that look wrong (wrong category, wrong numbers, missing people details). Fix the cause, not the symptom.

Finally, start the web app (`cd web && npm install && npm run dev -- --host`) and tell me the Network URL so I can open it on my phone.

**(For me)** Open the app on your phone and go through Today, a results card, Triage, Listen, Portfolio and Rules. Tell Claude Code anything that looks off.

---

## Phase 3: The research companies

Now the pull side. Help me pick 3-4 research demo companies (at least one outside the portfolio): for each candidate, fetch its screener.in page and check it has 4 recent concall transcripts with explicit numeric guidance. Start with KPITTECH, POLYCAB, PERSISTENT and DIXON.

For each good one run: `python -W ignore -m api.precompute <TICKER> --with-annual-report`

Fix whatever breaks in screener parsing, transcript download, or extraction. For each finished ticker, show me 3 promises with their verdicts and quotes so I can check them against the transcript, and tell me how many claims the citation guardrail dropped.

Then start the API (`uvicorn api.main:app --host 0.0.0.0`) and test live research on 3 other tickers that aren't pre-computed. Tell me which 3 work well, then clear them with: `python -m api.precompute <TICKERS> --clear`

---

## Phase 4: GitHub and deployment

**(For me)** I'll create the accounts and click through Render and Vercel myself. Claude Code prepares everything else.

Prepare for deployment:

1. git init if needed, check .gitignore covers .env, .venv, .cache, node_modules and web/dist, then show me `git status` before the first commit. Don't push until I say so.
2. Make sure render.yaml and requirements-api.txt will work on Render (Python 3.11), and that web/ builds with `npm run build`.
3. Give me a short checklist of exactly what to click in Render and Vercel, and which environment variables to set (VITE_API_URL, VITE_LIVE_TICKERS, GEMINI_API_KEY).

**(For me)** After I create the GitHub repository and give you the URL, I'll tell you to push. Then I'll do Render and Vercel using your checklist, and paste back any build errors.

---

## Phase 5: Final polish

Final pass before submission:

1. Run the pipeline once more so the brief is fresh, commit and push web/public/data.
2. Update README.md: real Vercel and Render links in the top table, add a docs/ folder for 3 screenshots I'll provide, and correct anything in the README that no longer matches the code.
3. Read SUBMISSION.md's email draft and fill in the facts from my real runs (filings classified by rules vs model, costs, number of research companies). Leave the wording for me to edit.