"""Decision log spine: every layer records what it decided about every filing."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


class DecisionLog:
    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)

    def write(self, item_id: str, layer: str, payload: dict) -> None:
        self.rows[item_id].append({"layer": layer, **payload})

    def trace(self, item_id: str) -> list[dict]:
        return self.rows.get(item_id, [])

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for item_id, layers in self.rows.items():
                f.write(json.dumps({"id": item_id, "layers": layers}, default=str) + "\n")
