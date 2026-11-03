# Running and deploying FINN

A step-by-step path from a fresh clone to a link you can open on a phone. Budget about 2–3 hours,
most of it waiting for the first pipeline and research runs.

## 0. What you need

- Python 3.10+ and Node 18+
- A free Gemini API key from https://aistudio.google.com
- Free accounts on GitHub, Vercel and Render

## 1. Set up and check everything works offline

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # paste your GEMINI_API_KEY
pytest -q                                              # expect: 40 passed
python -m core.llm --list                              # model names your key can use
```

If `gemini-flash-latest` or `gemini-pro-latest` is missing from that list, put names that are
present into `models.cheap.name` and `models.strong.name` in `config.yaml` (a "flash" model for
cheap, a "pro" model for strong). If the strong model isn't available, FINN falls back to the cheap
one automatically and logs a warning.

## 2. Build the first real brief

```bash
python -m pipeline.run_brief
```

This fetches 14 days of NSE filings for the 18 stocks in `config.yaml`, ~4 months of prices, then
classifies, scores and enriches. The first run takes a few minutes (it reads results PDFs during
results season); later runs reuse the cache and are much faster.

At the end it prints a summary and any source errors. Then:

```bash
cd web && npm install && npm run dev
```

Open the "Network" URL on your phone (same Wi-Fi). The sample-data banner should be gone.

**If NSE blocks you** (errors like `NSE failed`): wait a minute and run again; NSE's cookies
expire quickly. To retry enrichment without re-downloading filings, use
`python -m pipeline.run_brief --from-cache`. To test one stock: `--symbols TITAN`.
To run without any model: `--no-llm`.

**If a results card shows "verify in filing"**, that is the validation working: one of the
accounting checks failed, so FINN refused to show a possibly wrong number. Open the filing and
compare; if the extraction was wrong, tell me the filing and I can tighten the prompt.

## 3. Choose and pre-compute the research demo companies

Pick 3–4 companies (at least one outside the portfolio). On screener.in, check each company's
Documents section has **four recent concall transcripts** and that the calls contain **numeric
guidance** (growth or margin ranges). Then:

```bash
python -m api.precompute KPITTECH POLYCAB <THIRD> --with-annual-report
```

Each ticker prints a summary such as `KPITTECH: 9 promises (4/6 kept), 3 bull / 3 bear, 12 model
calls, 1 uncited dropped, 74s`. Open Research in the app to check them. If a company yields almost
no promises, its transcripts probably lack explicit guidance; swap it for another.

## 4. Pick the "Try a live company" tickers

Run the API locally and test 3 companies that are **not** pre-computed:

```bash
uvicorn api.main:app --reload
# in another terminal, or in the browser:
curl http://localhost:8000/research/PERSISTENT      # returns a job_id
curl http://localhost:8000/research/jobs/<job_id>   # poll until "done"
```

Keep the three that work well, then clear them so the reviewer's tap runs the real live pipeline:

```bash
python -m api.precompute PERSISTENT COFORGE ASTRAL --clear
```

## 5. Push to GitHub

```bash
git init && git add . && git commit -m "FINN prototype"
git branch -M main
git remote add origin https://github.com/<you>/finn.git
git push -u origin main
```

Check on GitHub that `.env` is **not** in the repository.

## 6. Deploy the research API on Render

1. Render dashboard → New → Blueprint → select the repo. It reads `render.yaml`.
2. Set the `GEMINI_API_KEY` environment variable when asked.
3. When it's live, open `https://<your-service>.onrender.com/health`. You should see `{"ok": true, ...}`.

The free tier sleeps after inactivity and takes ~30–60 s to wake. The app pings `/health` as soon
as it opens, so it's usually awake by the time someone reaches Research.

If screener.in or BSE block Render's servers, live research for new companies will fail with a
clear message; the pre-computed companies still work because they're served by Vercel.

## 7. Deploy the app on Vercel

1. Vercel → Add New → Project → import the repo.
2. **Root Directory: `web`**. Framework preset: Vite (auto-detected).
3. Environment variables:
   - `VITE_API_URL` = your Render URL, e.g. `https://finn-api.onrender.com`
   - `VITE_LIVE_TICKERS` = the three tickers from step 4, e.g. `PERSISTENT,COFORGE,ASTRAL`
4. Deploy. Open the URL on your phone and "Add to Home Screen".

## 8. Phone checklist before you submit

- [ ] Today: headline count matches the cards; switching 24 hours / 3 days / 1 week changes the list
- [ ] A results card opens; the sheet shows three quarters and the checks
- [ ] Triage mode: swipe right and left both work, and the buttons work
- [ ] Listen reads the brief aloud (check the phone isn't on silent)
- [ ] Rules: moving the volume slider changes the alert count immediately
- [ ] Portfolio → a stock → its timeline and "Research" button
- [ ] Research: a ready company loads instantly; a live company shows progress and finishes
- [ ] Promises tab: tap a promise, the quote is highlighted in its paragraph
- [ ] How FINN works shows the cost ledger

## 9. Refreshing the data

Re-run `python -m pipeline.run_brief`, then commit and push `web/public/data`. Vercel redeploys
automatically. The included GitHub Actions workflow can do this on a schedule (add
`GEMINI_API_KEY` as a repository secret), but NSE may block GitHub's servers; local runs are the
reliable option.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `NSE failed` for every stock | Run again after a minute; check you can open nseindia.com in a browser; try `--symbols` for one stock |
| `Model API error 404` | Model name not available to your key: run `python -m core.llm --list` and update `config.yaml` |
| `Model API 429` repeatedly | Free-tier rate limit: increase `models.min_interval_s` in `config.yaml` |
| `was not found on screener.in` | Use the NSE symbol exactly as screener.in does (e.g. `M&M`, `BAJAJ-AUTO`) |
| App shows "No brief yet" | `web/public/data/brief.json` is missing: run the pipeline or `python scripts/make_sample_data.py` |
| Research says live research isn't connected | `VITE_API_URL` not set in Vercel; redeploy after setting it |
