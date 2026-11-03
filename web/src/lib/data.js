// Data loading. Push data is static JSON produced by the pipeline; research comes from static
// pre-computed files first, then from the live research API.
export const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
export const LIVE_TICKERS = (import.meta.env.VITE_LIVE_TICKERS || "")
  .split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

export const loadBrief = () => getJSON("/data/brief.json");
export const loadPrices = () => getJSON("/data/prices.json");
export const loadResearchIndex = () => getJSON("/data/research/index.json").catch(() => ({ tickers: [] }));
export const loadStaticResearch = (t) => getJSON(`/data/research/${t}.json`);

export function warmApi() {
  if (API) fetch(`${API}/health`).catch(() => {});
}

export async function startResearch(ticker, refresh = false) {
  if (!API) throw new Error("Live research isn't connected in this build. Try one of the ready companies.");
  const r = await fetch(`${API}/research/${encodeURIComponent(ticker)}${refresh ? "?refresh=true" : ""}`);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Research API error ${r.status}`);
  return body;
}

export async function pollJob(jobId) {
  const r = await fetch(`${API}/research/jobs/${jobId}`);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Research API error ${r.status}`);
  return body;
}
