import { useMemo } from "react";
import { detectMoves } from "../lib/alerts";

const CATS = [
  ["results", "Results", "Quarterly and annual numbers"],
  ["management_change", "Management change", "CEO, CFO, MD, directors"],
  ["M&A", "M&A", "Acquisitions, mergers, stake sales"],
  ["litigation", "Litigation and regulators", "Orders, penalties, insolvency"],
  ["pledging", "Promoter pledging", "Shares pledged or released"],
  ["credit_rating", "Credit rating", "Upgrades and downgrades"],
  ["fund_raise", "Fund raising", "QIP, rights, preferential, buyback, debt"],
  ["insider_trading", "Insider trades", "Promoters buying or selling"],
  ["capex", "Capex", "New plants and capacity"],
  ["press_release", "Press releases", "Orders, launches, partnerships"],
  ["dividend", "Dividends", "Cash payouts and record dates"],
];

export default function Rules({ brief, prices, prefs, update, reset }) {
  const symbols = brief.portfolio.map((p) => p.symbol).filter((s) => !prefs.muted.includes(s));
  const preview = useMemo(() => detectMoves(prices, symbols, prefs, 30), [prices, symbols, prefs]);
  const set = (k) => (e) => update({ [k]: Number(e.target.value) });
  const toggleCat = (k) => update((p) => ({ categories: p.categories.includes(k) ? p.categories.filter((x) => x !== k) : [...p.categories, k] }));
  const toggleMute = (s) => update((p) => ({ muted: p.muted.includes(s) ? p.muted.filter((x) => x !== s) : [...p.muted, s] }));
  return (
    <div className="page">
      <h1 className="h-display" style={{ fontSize: 26 }}>Your rules</h1>
      <p className="small faint" style={{ marginTop: 0 }}>You decide what counts as unusual. FINN re-checks the last 30 days as you move each slider.</p>

      <div className="rule">
        <label htmlFor="vol">Volume spike <span>{prefs.volumeMultiple.toFixed(1)}× average</span></label>
        <input id="vol" type="range" min="1.5" max="5" step="0.1" value={prefs.volumeMultiple} onChange={set("volumeMultiple")} />
        <label htmlFor="px">Price move <span>±{prefs.priceMovePct}% in a day</span></label>
        <input id="px" type="range" min="2" max="10" step="0.5" value={prefs.priceMovePct} onChange={set("priceMovePct")} />
        <div className="row between" style={{ marginTop: 6 }}>
          <span style={{ fontWeight: 500 }}>Average over</span>
          <div className="seg">
            {[10, 20, 50].map((d) => <button key={d} aria-pressed={prefs.lookback === d} onClick={() => update({ lookback: d })}>{d} days</button>)}
          </div>
        </div>
        <p className="preview" style={{ marginTop: 12 }}>
          At these settings: <b>{preview.length}</b> alert{preview.length === 1 ? "" : "s"} in the last 30 trading days
          {preview.length > 0 ? `, most recently ${preview[0].symbol} (${preview[0].move_pct > 0 ? "+" : ""}${preview[0].move_pct}%, ${preview[0].volume_ratio}× volume).` : "."}
        </p>
      </div>

      <h2 className="h-section">Alert me about</h2>
      <p className="small faint" style={{ marginTop: -6 }}>Categories you follow rank higher in every brief.</p>
      <div className="rule">
        {CATS.map(([k, label, hint]) => (
          <div className="toggle" key={k}>
            <span>{label}<br /><span className="small faint">{hint}</span></span>
            <button className="switch" role="switch" aria-checked={prefs.categories.includes(k)} aria-label={label} onClick={() => toggleCat(k)} />
          </div>
        ))}
      </div>

      <h2 className="h-section">Mute a stock</h2>
      <div className="rule">
        {brief.portfolio.map((p) => (
          <div className="toggle" key={p.symbol}>
            <span>{p.name} <span className="small faint">{p.symbol}</span></span>
            <button className="switch" role="switch" aria-checked={!prefs.muted.includes(p.symbol)} aria-label={`Watch ${p.name}`} onClick={() => toggleMute(p.symbol)} />
          </div>
        ))}
      </div>
      <button className="btn" style={{ width: "100%", marginTop: 8 }} onClick={reset}>Restore default rules</button>
      <p className="small faint" style={{ textAlign: "center", marginTop: 18 }}><a href="#/how">How FINN works</a></p>
    </div>
  );
}
