import Spark from "../components/Spark";
import { Row } from "../components/Cards";
import { istDate, pct, plural, tone } from "../lib/format";

const BADGE = (c) => {
  if (c.kind === "results") return { t: "Results out", cls: "" };
  if (c.category === "management_change" && c.role === "top") return { t: "Leadership change", cls: "warn" };
  if (c.category === "pledging") return { t: c.direction === "positive" ? "Pledge released" : "Pledge up", cls: c.direction === "positive" ? "" : "warn" };
  if (c.category === "credit_rating" && c.subtype !== "reaffirm") return { t: `Rating ${c.subtype}`, cls: c.subtype === "downgrade" ? "warn" : "" };
  if (c.category === "M&A") return { t: "M&A", cls: "" };
  if (c.category === "litigation") return { t: "Litigation", cls: "warn" };
  return null;
};

function last(prices, sym) {
  const r = prices[sym] || [];
  if (r.length < 2) return {};
  return { close: r[r.length - 1].c, chg: (r[r.length - 1].c / r[r.length - 2].c - 1) * 100 };
}

export default function Portfolio({ brief, items, moves, prices, prefs }) {
  const latest = moves[0]?.date;
  return (
    <div className="page">
      <h1 className="h-display" style={{ fontSize: 26 }}>Your portfolio</h1>
      <p className="small faint" style={{ marginTop: 0 }}>{plural(brief.portfolio.length, "holding")}. Badges show what changed in the last {brief.lookback_days} days.</p>
      <div className="rows" style={{ marginTop: 14 }}>
        {[...brief.portfolio].sort((a, b) => b.weight - a.weight).map((p) => {
          const { close, chg } = last(prices, p.symbol);
          const events = items.filter((c) => c.symbol === p.symbol && c.tier !== "routine");
          const badges = events.map(BADGE).filter(Boolean).filter((b, i, a) => a.findIndex((x) => x.t === b.t) === i);
          const mv = moves.find((m) => m.symbol === p.symbol && m.date === latest);
          if (mv?.trigger !== "price" && mv) badges.unshift({ t: `Vol ${mv.volume_ratio.toFixed(1)}×`, cls: "warn" });
          if (prefs.tracked.some((id) => id.includes(`-${p.symbol}-`))) badges.unshift({ t: "Tracking", cls: "good" });
          const muted = prefs.muted.includes(p.symbol);
          return (
            <a key={p.symbol} className="rowitem" href={`#/portfolio/${p.symbol}`} style={{ textDecoration: "none", color: "inherit", opacity: muted ? 0.55 : 1 }}>
              <span className="holding" style={{ gridColumn: "1 / -1" }}>
                <span><span className="sym">{p.symbol}</span><br /><span className="nm">{p.name}, {(p.weight * 100).toFixed(0)}%</span></span>
                <Spark rows={(prices[p.symbol] || []).slice(-30)} w={72} />
                <span className="px">{close ? close.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : "—"}<br />
                  <span className={`small ${tone(chg)}`}>{pct(chg)}</span></span>
                {(badges.length > 0 || muted) && (
                  <span className="badges">
                    {muted && <span className="tag">Muted</span>}
                    {badges.slice(0, 3).map((b) => <span key={b.t} className={`tag ${b.cls}`}>{b.t}</span>)}
                  </span>
                )}
              </span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

export function StockDetail({ symbol, brief, items, moves, prices, onOpen }) {
  const p = brief.portfolio.find((x) => x.symbol === symbol);
  const rows = prices[symbol] || [];
  const { close, chg } = last(prices, symbol);
  const events = [
    ...items.filter((c) => c.symbol === symbol).map((c) => ({ when: c.filed_at, card: c })),
    ...moves.filter((m) => m.symbol === symbol).map((m) => ({ when: m.date + "T16:00:00+05:30", move: m })),
  ].sort((a, b) => (a.when < b.when ? 1 : -1));
  return (
    <div className="page">
      <a href="#/portfolio" className="small">Portfolio</a>
      <h1 className="h-display" style={{ fontSize: 26 }}>{p?.name || symbol}</h1>
      <p className="small faint" style={{ marginTop: 0 }}>{symbol}{p ? `, ${p.sector}, ${(p.weight * 100).toFixed(0)}% of portfolio` : ""}</p>
      <div className="panel">
        <div className="row between"><b style={{ fontSize: 22, fontWeight: 500 }}>{close?.toLocaleString("en-IN") || "—"}</b>
          <span className={tone(chg)}>{pct(chg)} last close</span></div>
        <Spark rows={rows.slice(-60)} w={320} h={70} className="chart" />
        <p className="small faint" style={{ margin: 0 }}>Last 60 trading days, end-of-day close.</p>
      </div>
      <a className="btn btn-primary" href={`#/research/${symbol}`} style={{ display: "block", textAlign: "center", textDecoration: "none", marginTop: 12 }}>
        Research {symbol}
      </a>
      <h2 className="h-section">What happened</h2>
      {events.length === 0 && <p className="small muted">Nothing filed or flagged in the last {brief.lookback_days} days.</p>}
      <ul className="timeline">
        {events.map((e, i) => e.card ? (
          <li key={i} className={e.card.tier === "critical" || e.card.tier === "high" ? "hi" : ""}>
            <div className="small faint">{istDate(e.when)}, {e.card.category_label}</div>
            <button className="link" style={{ textAlign: "left", color: "var(--ink)" }} onClick={() => onOpen(e.card)}>
              {e.card.line || e.card.title}
            </button>
          </li>
        ) : (
          <li key={i} className="hi">
            <div className="small faint">{istDate(e.when)}, unusual move</div>
            <span className={tone(e.move.move_pct)}>{pct(e.move.move_pct)}</span> on {e.move.volume_ratio.toFixed(1)}× average volume
          </li>
        ))}
      </ul>
    </div>
  );
}

export { Row };
