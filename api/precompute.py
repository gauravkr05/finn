"""Pre-compute research for demo tickers into the web app's static data folder.

    python -m api.precompute ASIANPAINT KPITTECH POLYCAB --with-annual-report
    python -m api.precompute PERSISTENT --clear      # remove a ticker you tested live
"""
from __future__ import annotations

import argparse
import json
import logging

from core.config import CACHE_DIR, WEB_DATA

from . import research


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--with-annual-report", action="store_true")
    ap.add_argument("--clear", action="store_true", help="delete cached results for these tickers")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    out = WEB_DATA / "research"
    out.mkdir(parents=True, exist_ok=True)
    for t in (x.upper() for x in args.tickers):
        if args.clear:
            for p in (out / f"{t}.json", CACHE_DIR / "research" / f"{t}.json"):
                p.unlink(missing_ok=True)
            print(f"cleared {t}")
            continue
        res = research.run(t, with_annual_report=args.with_annual_report)
        if not res.get("complete", True):
            print(f"{t}: NOT saved, strong-model steps skipped ({res['trace']['strong_skipped']}); "
                  "re-run when the model quota is available")
            continue
        (out / f"{t}.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
        s, tr = res["promise_score"], res["trace"]
        print(f"{t}: {len(res['promises'])} promises ({s['kept']}/{s['judged']} kept), "
              f"{len(res['bull'])} bull / {len(res['bear'])} bear, {tr['model_calls']} model calls, "
              f"{tr['dropped_uncited']} uncited dropped, {tr['seconds']}s")
    index = sorted(p.stem for p in out.glob("*.json") if p.stem != "index")
    (out / "index.json").write_text(json.dumps({"tickers": index}))
    print("index:", index)


if __name__ == "__main__":
    main()
