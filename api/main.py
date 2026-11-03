"""FINN research API.

GET /health                      warm-up ping (the app calls it on open)
GET /research/{ticker}           cached result, or starts a job and returns {job_id}
GET /research/jobs/{job_id}      progress and result
GET /research/{ticker}?refresh=1 force a fresh run
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import CACHE_DIR

from . import research

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finn.api")

app = FastAPI(title="FINN research API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

RESULTS = CACHE_DIR / "research"
RESULTS.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
ACTIVE: dict[str, str] = {}  # ticker -> running job id
LOCK = threading.Lock()
SEM = threading.Semaphore(2)  # free tier: at most two research runs at once
TICKER = re.compile(r"^[A-Z0-9&\-]{1,20}$")


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat(), "cached": sorted(p.stem for p in RESULTS.glob("*.json"))}


def _work(job_id: str, ticker: str) -> None:
    job = JOBS[job_id]

    def progress(step, msg, pct):
        job.update(step=step, message=msg, pct=pct)

    with SEM:
        try:
            result = research.run(ticker, progress)
            if result.get("complete", True):  # never cache a result whose strong-model steps were skipped
                (RESULTS / f"{ticker}.json").write_text(json.dumps(result, ensure_ascii=False, default=str))
            job.update(status="done", result=result, pct=100)
        except LookupError as e:
            job.update(status="error", error=str(e))
        except Exception as e:  # surface a clear message to the app
            log.exception("research failed for %s", ticker)
            job.update(status="error", error=f"Research failed: {str(e)[:200]}")
        finally:
            with LOCK:
                ACTIVE.pop(ticker, None)


@app.get("/research/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job. The server may have restarted; start the research again.")
    return job


@app.get("/research/{ticker}")
def get_research(ticker: str, refresh: bool = False):
    ticker = ticker.strip().upper().removesuffix(".NS")
    if not TICKER.match(ticker):
        raise HTTPException(400, "Use an NSE symbol such as TITAN or KPITTECH.")
    path = RESULTS / f"{ticker}.json"
    if path.exists() and not refresh:
        return {"status": "done", "cached": True, "result": json.loads(path.read_text())}
    with LOCK:
        if ticker in ACTIVE:
            return {"status": "running", "job_id": ACTIVE[ticker]}
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"job_id": job_id, "ticker": ticker, "status": "running", "step": "queued",
                        "message": "Starting", "pct": 0}
        ACTIVE[ticker] = job_id
    threading.Thread(target=_work, args=(job_id, ticker), daemon=True).start()
    return {"status": "running", "job_id": job_id}
