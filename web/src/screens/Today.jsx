import { useMemo, useState } from "react";
import CardStack from "../components/CardStack";
import DayRhythm, { istHour } from "../components/DayRhythm";
import { Row, Slab } from "../components/Cards";
import Spark from "../components/Spark";
import { TIER_ORDER, WINDOWS, inWindow } from "../lib/alerts";
import { istDate, istTime, pct, plural, tone } from "../lib/format";
import { buildSpoken, canSpeak, speak, stopSpeaking } from "../lib/speech";

export default function Today({ brief, items, moves, prices, prefs, update, onOpen, names }) {
  const [win, setWin] = useState("24h");
  const [custom, setCustom] = useState("");
  const [mode, setMode] = useState("list");
  const [showRoutine, setShowRoutine] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const gen = brief.generated_at;

  const visible = useMemo(() => items
    .filter((c) => inWindow(c.filed_at, win, gen, custom) && !prefs.muted.includes(c.symbol))
    .sort((a, b) => TIER_ORDER[b.tier] - TIER_ORDER[a.tier] || b.score - a.score), [items, win, gen, custom, prefs.muted]);
  const attention = visible.filter((c) => c.tier === "critical" || c.tier === "high");
  const glance = visible.filter((c) => c.tier === "medium");
  const routine = visible.filter((c) => c.tier === "routine");

  const latestDate = moves[0]?.date;
  const winMoves = useMemo(() => {
    const hours = WINDOWS.find((w) => w.key === win)?.hours || (custom ? (new Date(gen) - new Date(custom)) / 3600000 : 24);
    const days = Math.max(1, Math.round(hours / 24));
    const dates = [...new Set(moves.map((m) => m.date))].slice(0, days);
    return moves.filter((m) => dates.includes(m.date) && !prefs.muted.includes(m.symbol));
  }, [moves, win, custom, gen, prefs.muted]);

  const stackCards = attention.filter((c) => !prefs.done.includes(c.id) && !prefs.tracked.includes(c.id));
  const n = attention.length;
  const headline = n === 0 ? "Nothing needs your attention." : n === 1 ? "One thing needs your attention." : `${n} things need your attention.`;

  const listen = () => {
    if (speaking) { stopSpeaking(); setSpeaking(false); return; }
    const text = win === "24h" && brief.spoken_brief ? brief.spoken_brief
      : buildSpoken(visible, winMoves, names, routine.length, istHour());
    setSpeaking(true);
    speak(text, () => setSpeaking(false));
  };

  return (
    <div className="page">
      <DayRhythm opening={brief.rhythm?.opening} closing={brief.rhythm?.closing} />
      <h1 className="h-display">{headline}</h1>
      <p className="small faint" style={{ margin: 0 }}>
        {brief.run}, prepared {istDate(gen)} at {istTime(gen)}. {routine.length ? `${plural(routine.length, "routine filing")} hidden.` : ""}
      </p>
      {brief.sample && (
        <div className="banner">Sample data for previewing the app. Run the pipeline to load real filings and prices.</div>
      )}
      {brief.mode === "rules-only" && !brief.sample && (
        <div className="banner">Running on rules only (no model key), so results and people cards show the filing without extracted numbers.</div>
      )}

      <div className="chips" style={{ marginTop: 14 }} role="group" aria-label="Time window">
        {WINDOWS.map((w) => (
          <button key={w.key} className="chip" aria-pressed={win === w.key} onClick={() => setWin(w.key)}>{w.label}</button>
        ))}
        <button className="chip" aria-pressed={win === "custom"} onClick={() => setWin("custom")}>Custom</button>
      </div>
      {win === "custom" && (
        <label className="small muted row" style={{ marginTop: 8 }}>
          Since
          <input type="date" value={custom} onChange={(e) => setCustom(e.target.value)}
            max={gen.slice(0, 10)} min={new Date(new Date(gen) - (brief.lookback_days || 14) * 864e5).toISOString().slice(0, 10)}
            style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "6px 8px", background: "var(--surface)" }} />
        </label>
      )}

      <div className="row between" style={{ marginTop: 12 }}>
        {canSpeak() ? (
          <button className="listen" onClick={listen} aria-pressed={speaking}>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>{speaking ? <rect x="2" y="2" width="8" height="8" fill="currentColor" /> : <path d="M2 1l9 5-9 5z" fill="currentColor" />}</svg>
            {speaking ? "Stop" : "Listen"}
          </button>
        ) : <span />}
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={mode === "list"} onClick={() => setMode("list")}>List</button>
          <button aria-pressed={mode === "stack"} onClick={() => setMode("stack")}>Triage</button>
        </div>
      </div>

      {brief.context?.length > 0 && (
        <div className="context">
          {brief.context.map((c) => (
            <span key={c.symbol}>{c.label} <b>{c.close.toLocaleString("en-IN")}</b> <span className={tone(c.change_pct)}>{pct(c.change_pct, 2)}</span></span>
          ))}
        </div>
      )}

      {mode === "stack" ? (
        <CardStack cards={stackCards} total={attention.length} onOpen={onOpen}
          onTrack={(c) => update((p) => ({ tracked: [...new Set([...p.tracked, c.id])] }))}
          onDone={(c) => update((p) => ({ done: [...new Set([...p.done, c.id])] }))}
          onUndo={() => update((p) => ({ done: p.done.filter((id) => !attention.some((c) => c.id === id)),
            tracked: p.tracked.filter((id) => !attention.some((c) => c.id === id)) }))} />
      ) : (
        <>
          {attention.length > 0 && <h2 className="h-section">Needs attention <span className="count">{attention.length}</span></h2>}
          {attention.map((c) => (
            <Slab key={c.id} card={c} onOpen={onOpen} read={prefs.done.includes(c.id)} tracked={prefs.tracked.includes(c.id)} now={gen} />
          ))}

          <h2 className="h-section">Unusual moves <span className="count">{winMoves.length}</span></h2>
          <p className="small faint" style={{ marginTop: -6 }}>
            End-of-day {latestDate ? `as of ${istDate(latestDate)}` : ""}: volume above {prefs.volumeMultiple}× its {prefs.lookback}-day average, or a move beyond ±{prefs.priceMovePct}%. <a href="#/rules">Change</a>
          </p>
          {winMoves.length ? (
            <div className="rows">
              {winMoves.map((m) => (
                <a key={m.symbol + m.date} className="rowitem" href={`#/portfolio/${m.symbol}`} style={{ textDecoration: "none", color: "inherit" }}>
                  <span className="move" style={{ gridColumn: "1 / -1" }}>
                    <span><b style={{ fontWeight: 500 }}>{names[m.symbol] || m.symbol}</b><br />
                      <span className="small faint">{istDate(m.date)}, volume {m.volume_ratio.toFixed(1)}× average</span></span>
                    <Spark rows={(prices[m.symbol] || []).filter((r) => r.d <= m.date).slice(-30)} />
                    <span className={tone(m.move_pct)} style={{ textAlign: "right", fontWeight: 500 }}>{pct(m.move_pct)}</span>
                  </span>
                  {sameDayFiling(items, m) && <span className="s">Filed that day: {sameDayFiling(items, m).title}</span>}
                </a>
              ))}
            </div>
          ) : <p className="small muted">No stock crossed your thresholds in this window.</p>}

          {glance.length > 0 && <h2 className="h-section">Worth a glance <span className="count">{glance.length}</span></h2>}
          {glance.length > 0 && <div className="rows">{glance.map((c) => <Row key={c.id} card={c} onOpen={onOpen} now={gen} />)}</div>}

          {routine.length > 0 && (
            <>
              <button className="disclosure" onClick={() => setShowRoutine((s) => !s)} aria-expanded={showRoutine}>
                {showRoutine ? "Hide" : "Show"} {plural(routine.length, "routine filing")}
                <span className="small faint"> (trading windows, ESOP allotments, meeting notices, compliance certificates)</span>
              </button>
              {showRoutine && <div className="rows" style={{ marginTop: 8 }}>{routine.map((c) => <Row key={c.id} card={c} onOpen={onOpen} now={gen} />)}</div>}
            </>
          )}
          {visible.length === 0 && <p className="empty">No filings in this window. Try a longer one.</p>}
        </>
      )}
    </div>
  );
}

function sameDayFiling(items, m) {
  return items.find((c) => c.symbol === m.symbol && c.filed_at.slice(0, 10) === m.date && c.tier !== "routine");
}
