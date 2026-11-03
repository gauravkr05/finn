// Client-side engine: recomputes unusual moves and the ranking whenever the investor changes a rule.
// Mirrors pipeline/moves.py and pipeline/triage/score.py.

export function detectMoves(prices, symbols, { volumeMultiple, priceMovePct, lookback }, days = 30) {
  const out = [];
  for (const sym of symbols) {
    const rows = prices?.[sym] || [];
    for (let i = Math.max(1, rows.length - days); i < rows.length; i++) {
      const hist = rows.slice(Math.max(0, i - lookback), i).map((r) => r.v).filter(Boolean);
      if (hist.length < Math.max(5, Math.floor(lookback / 2))) continue;
      const avg = hist.reduce((a, b) => a + b, 0) / hist.length;
      const vr = avg ? rows[i].v / avg : 0;
      const mv = rows[i - 1].c ? (rows[i].c / rows[i - 1].c - 1) * 100 : 0;
      const volHit = vr >= volumeMultiple;
      const pxHit = Math.abs(mv) >= priceMovePct;
      if (volHit || pxHit) {
        out.push({ symbol: sym, date: rows[i].d, close: rows[i].c, move_pct: +mv.toFixed(2),
          volume_ratio: +vr.toFixed(2), trigger: volHit && pxHit ? "both" : volHit ? "volume" : "price" });
      }
    }
  }
  return out.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : Math.abs(b.move_pct) - Math.abs(a.move_pct)));
}

const scoreParts = (it) => it.trace?.find((x) => x.layer === "L4_score")?.score_parts || null;

// Re-rank with the investor's followed categories (the pipeline used the defaults).
export function rescore(items, prefs, triage, generatedAt) {
  if (!triage) return items;
  const followed = new Set(prefs.categories);
  const end = new Date(generatedAt);
  const t = triage.tiers;
  return items.map((it) => {
    const parts = { ...(scoreParts(it) || {}) };
    if (!Object.keys(parts).length) return it;
    delete parts.preference;
    let s = Object.values(parts).reduce((a, b) => a * b, 1);
    const follows = followed.has(it.category);
    if (follows) s *= triage.preference_boost;
    if ((end - new Date(it.filed_at)) / 1000 <= 86400) s += triage.recency_bonus;
    const tier = s >= t.critical ? "critical" : s >= t.high ? "high" : s >= t.medium ? "medium" : "routine";
    const why = it.why.replace(/, a category you follow$/, "") + (follows ? ", a category you follow" : "");
    return { ...it, score: +s.toFixed(2), tier, why };
  });
}

export const TIER_ORDER = { critical: 3, high: 2, medium: 1, routine: 0 };

export const WINDOWS = [
  { key: "24h", label: "24 hours", hours: 24 },
  { key: "3d", label: "3 days", hours: 72 },
  { key: "1w", label: "1 week", hours: 168 },
];

export function inWindow(iso, windowKey, generatedAt, customFrom) {
  const t = new Date(iso);
  if (windowKey === "custom" && customFrom) return t >= new Date(customFrom + "T00:00:00+05:30");
  const hours = WINDOWS.find((w) => w.key === windowKey)?.hours || 24;
  return (new Date(generatedAt) - t) / 3600000 <= hours;
}

export function sparkPath(rows, w = 80, h = 26) {
  if (!rows?.length) return "";
  const cs = rows.map((r) => r.c);
  const min = Math.min(...cs), max = Math.max(...cs);
  const span = max - min || 1;
  return cs.map((c, i) => `${i ? "L" : "M"}${((i / (cs.length - 1 || 1)) * w).toFixed(1)},${(h - ((c - min) / span) * (h - 2) - 1).toFixed(1)}`).join(" ");
}
