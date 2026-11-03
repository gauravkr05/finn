// The investor's own rules, kept on this device.
import { useCallback, useEffect, useState } from "react";

const KEY = "finn.prefs.v2";

function read() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

function save(p) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable: keep in memory */
  }
}

export function usePrefs(defaults) {
  const [prefs, setPrefs] = useState(() => ({ ...baseline(defaults), ...read() }));
  useEffect(() => {
    if (defaults) setPrefs((p) => ({ ...baseline(defaults), ...read(), ...stripDefaults(p) }));
  }, [defaults]);
  const update = useCallback((patch) => {
    setPrefs((p) => {
      const next = { ...p, ...(typeof patch === "function" ? patch(p) : patch), touched: true };
      save(next);
      return next;
    });
  }, []);
  const reset = useCallback(() => {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    setPrefs(baseline(defaults));
  }, [defaults]);
  return [prefs, update, reset];
}

const stripDefaults = (p) => (p.touched ? p : {});

function baseline(d) {
  return {
    volumeMultiple: d?.volume_multiple ?? 2,
    priceMovePct: d?.price_move_pct ?? 4,
    lookback: d?.lookback_days ?? 20,
    categories: d?.categories ?? [],
    muted: [],
    tracked: [],
    done: [],
  };
}
