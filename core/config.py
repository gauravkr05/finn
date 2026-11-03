"""Configuration and paths shared by the push pipeline and the research API."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = ROOT / "web" / "public" / "data"
CACHE_DIR = Path(os.environ.get("FINN_CACHE_DIR", ROOT / ".cache"))
OUT_DIR = ROOT / "pipeline" / "out"


def _load_dotenv() -> None:
    """Minimal .env loader so we don't need python-dotenv."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else Path(os.environ.get("FINN_CONFIG", ROOT / "config.yaml"))
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def portfolio_map() -> dict[str, dict]:
    return {p["symbol"]: p for p in load_config()["portfolio"]}
