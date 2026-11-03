import { useEffect, useMemo, useState } from "react";
import Sheet from "./components/Sheet";
import TabBar from "./components/TabBar";
import { CardDetail } from "./components/Cards";
import HowItWorks from "./screens/HowItWorks";
import Portfolio, { StockDetail } from "./screens/Portfolio";
import Research from "./screens/Research";
import Rules from "./screens/Rules";
import Today from "./screens/Today";
import { detectMoves, inWindow, rescore } from "./lib/alerts";
import { loadBrief, loadPrices, warmApi } from "./lib/data";
import { usePrefs } from "./lib/prefs";
import { useRoute } from "./lib/router";

export default function App() {
  const [brief, setBrief] = useState(null);
  const [prices, setPrices] = useState({});
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const route = useRoute();
  const [prefs, update, reset] = usePrefs(brief?.alert_defaults);

  useEffect(() => {
    warmApi(); // wake the research service early so it's ready by the time someone opens Research
    loadBrief().then(setBrief).catch((e) => setError(e.message));
    loadPrices().then(setPrices).catch(() => setPrices({}));
  }, []);

  const items = useMemo(() => (brief ? rescore(brief.items, prefs, brief.triage, brief.generated_at) : []), [brief, prefs]);
  const moves = useMemo(() => (brief ? detectMoves(prices, brief.portfolio.map((p) => p.symbol), prefs, 30) : []), [brief, prices, prefs]);
  const names = useMemo(() => Object.fromEntries((brief?.portfolio || []).map((p) => [p.symbol, p.name])), [brief]);

  if (error) {
    return (
      <div className="app"><div className="page empty">
        <p style={{ fontSize: 18, color: "var(--ink)" }}>No brief yet.</p>
        <p>Run <code>python -m pipeline.run_brief</code> to create <code>web/public/data/brief.json</code>, then reload.</p>
      </div></div>
    );
  }
  if (!brief) return <div className="app"><div className="page empty"><span className="spin" /></div></div>;

  const [tab, arg] = route;
  const unseen = items.filter((c) => (c.tier === "critical" || c.tier === "high") && inWindow(c.filed_at, "24h", brief.generated_at)
    && !prefs.done.includes(c.id) && !prefs.muted.includes(c.symbol)).length;
  const toggleTrack = (c) => update((p) => ({ tracked: p.tracked.includes(c.id) ? p.tracked.filter((x) => x !== c.id) : [...p.tracked, c.id] }));
  const common = { brief, items, moves, prices, prefs, update, onOpen: setOpen, names };

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">FINN</span>
        <span className="run">{tab === "today" ? brief.run : ""}</span>
      </header>
      <main>
        {tab === "today" && <Today {...common} />}
        {tab === "portfolio" && !arg && <Portfolio {...common} />}
        {tab === "portfolio" && arg && <StockDetail symbol={arg} {...common} />}
        {tab === "research" && <Research ticker={arg} />}
        {tab === "rules" && <Rules {...common} reset={reset} />}
        {tab === "how" && <HowItWorks brief={brief} />}
      </main>
      <TabBar current={tab === "how" ? "rules" : tab} todayCount={unseen} />
      {open && (
        <Sheet onClose={() => setOpen(null)} label={`${open.company} details`}>
          <CardDetail card={open} onTrack={toggleTrack} tracked={prefs.tracked.includes(open.id)} />
        </Sheet>
      )}
    </div>
  );
}
