import { Fragment, useEffect, useRef, useState } from "react";
import Quote from "../components/Quote";
import Sheet from "../components/Sheet";
import { API, LIVE_TICKERS, loadResearchIndex, loadStaticResearch, pollJob, startResearch } from "../lib/data";
import { bps, cr, istDate, num, pct, tone } from "../lib/format";
import { go } from "../lib/router";

const STEPS = [
  ["resolve", "Find the company on screener.in"],
  ["numbers", "Read the financial tables"],
  ["documents", "Fetch the last four concall transcripts"],
  ["extract", "Pull out management's guidance"],
  ["judge", "Match promises against reported numbers"],
  ["synthesise", "Write the snapshot and the bull and bear cases"],
];

export default function Research({ ticker }) {
  const [index, setIndex] = useState([]);
  const [q, setQ] = useState(ticker || "");
  const [state, setState] = useState({ status: "idle" });
  const timer = useRef(null);

  useEffect(() => { loadResearchIndex().then((i) => setIndex(i.tickers || [])); }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    clearTimeout(timer.current);
    if (!ticker) { setState({ status: "idle" }); return; }
    setQ(ticker);
    run(ticker);
  }, [ticker]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(t) {
    setState({ status: "running", step: "resolve", message: `Looking up ${t}`, pct: 2 });
    try {
      const data = await loadStaticResearch(t);
      setState({ status: "done", result: data, source: "ready" });
      return;
    } catch { /* not pre-computed: go live */ }
    try {
      const r = await startResearch(t);
      if (r.status === "done") return setState({ status: "done", result: r.result, source: "cache" });
      const tick = async () => {
        try {
          const j = await pollJob(r.job_id);
          if (j.status === "done") setState({ status: "done", result: j.result, source: "live" });
          else if (j.status === "error") setState({ status: "error", error: j.error });
          else { setState({ status: "running", ...j }); timer.current = setTimeout(tick, 2000); }
        } catch (e) { setState({ status: "error", error: e.message }); }
      };
      setState({ status: "running", step: "resolve", message: "Waking the research service", pct: 3 });
      timer.current = setTimeout(tick, 1200);
    } catch (e) {
      setState({ status: "error", error: e.message });
    }
  }

  const submit = (e) => {
    e.preventDefault();
    const t = q.trim().toUpperCase().replace(/\.NS$/, "");
    if (t) go(`research/${t}`);
  };

  return (
    <div className="page">
      <h1 className="h-display" style={{ fontSize: 26 }}>Research</h1>
      <p className="small faint" style={{ marginTop: 0 }}>Any NSE company, read from its own annual reports and concall transcripts. No news, no broker notes.</p>
      <form className="search" onSubmit={submit} role="search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="NSE symbol, e.g. POLYCAB" aria-label="NSE symbol"
          autoCapitalize="characters" autoCorrect="off" spellCheck="false" enterKeyHint="search" />
        <button className="btn btn-primary" type="submit">Research</button>
      </form>

      {state.status === "idle" && (
        <>
          {index.length > 0 && (<>
            <h2 className="h-section">Ready now</h2>
            <div className="chips wrap" style={{ flexWrap: "wrap" }}>{index.map((t) => <a key={t} className="chip" href={`#/research/${t}`} style={{ textDecoration: "none" }}>{t}</a>)}</div>
          </>)}
          {API && LIVE_TICKERS.length > 0 && (<>
            <h2 className="h-section">Try a live company</h2>
            <p className="small faint" style={{ marginTop: -6 }}>Not cached: FINN reads the documents now, in about a minute.</p>
            <div className="chips" style={{ flexWrap: "wrap" }}>{LIVE_TICKERS.map((t) => <a key={t} className="chip" href={`#/research/${t}`} style={{ textDecoration: "none" }}>{t}</a>)}</div>
          </>)}
          {!API && <p className="small faint" style={{ marginTop: 18 }}>Live research for other companies needs the research service. This build shows pre-computed companies only.</p>}
        </>
      )}

      {state.status === "running" && <Progress s={state} />}
      {state.status === "error" && (
        <div className="panel" style={{ marginTop: 16 }}>
          <p style={{ marginTop: 0 }}>{state.error}</p>
          <button className="btn" onClick={() => run(ticker)}>Try again</button>
        </div>
      )}
      {state.status === "done" && <Report r={state.result} source={state.source} />}
    </div>
  );
}

function Progress({ s }) {
  const idx = STEPS.findIndex(([k]) => k === s.step);
  return (
    <>
      <ul className="steps" aria-live="polite">
        {STEPS.map(([k, label], i) => (
          <li key={k} className={i < idx ? "done" : i === idx ? "active" : ""}>
            <span>{i < idx ? "✓" : i === idx ? <span className="spin" /> : "·"}</span>
            <span>{label}{i === idx && s.message ? <span className="small faint"><br />{s.message}</span> : null}</span>
          </li>
        ))}
      </ul>
      <p className="small faint">A company FINN hasn't read before takes about a minute. After that it's instant.</p>
    </>
  );
}

const TABS = [["snapshot", "Snapshot"], ["promises", "Promises"], ["numbers", "Numbers"], ["cash", "Cash"], ["bullbear", "Bull and bear"], ["sources", "Sources"]];

function Report({ r, source }) {
  const [tab, setTab] = useState("snapshot");
  const [sheet, setSheet] = useState(null);
  const fin = r.financials;
  return (
    <>
      <h2 style={{ fontSize: 22, fontWeight: 500, margin: "20px 0 2px" }}>{r.name}</h2>
      <p className="small faint" style={{ margin: 0 }}>
        {r.ticker}, read {istDate(r.generated_at)} from {r.documents.length} documents{source === "live" ? ", just now" : ""}.
        {r.trace?.model_calls != null ? ` ${r.trace.model_calls} model calls.` : ""}
      </p>
      {r.sample && <div className="banner">Sample research on a fictional company, for previewing the layout.</div>}
      {r.complete === false && <div className="banner">Some checks need the stronger model, which has reached its free daily limit. Promises marked "not checked today" weren't judged; this result isn't saved.</div>}
      {r.mode === "numbers-only" && <div className="banner">No model key on the research service, so only the numbers are shown.</div>}
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-pressed={tab === k} aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "snapshot" && <Snapshot r={r} />}
      {tab === "promises" && <Promises r={r} />}
      {tab === "numbers" && <Numbers fin={fin} />}
      {tab === "cash" && <Cash fin={fin} />}
      {tab === "bullbear" && <BullBear r={r} onCite={setSheet} />}
      {tab === "sources" && <Sources r={r} />}
      {sheet && <Sheet onClose={() => setSheet(null)} label="Citation">{sheet}</Sheet>}
    </>
  );
}

function Snapshot({ r }) {
  const s = r.snapshot, f = r.financials.snapshot, sc = r.promise_score;
  return (
    <>
      <div className="panel">
        {s ? <p style={{ marginTop: 0 }}>{s.business}</p> : <p className="muted" style={{ marginTop: 0 }}>No business description could be verified from the sources.</p>}
        {s?.segments?.length > 0 && <div className="facts">{s.segments.map((x) => <span className="fact" key={x.name}><b>{x.name}</b> {x.detail}</span>)}</div>}
        {s?.sources?.slice(0, 1).map((q, i) => <Quote key={i} source={q} />)}
      </div>
      <div className="panel">
        <dl className="kv">
          <dt>{f.fy?.replace("Mar ", "FY")} revenue</dt><dd>{cr(f.revenue)} <span className={tone(f.revenue_growth)}>{pct(f.revenue_growth)}</span></dd>
          <dt>{r.financials.lender ? "Financing margin" : "Operating margin"}</dt><dd>{f.opm ?? "—"}%</dd>
          <dt>Net profit</dt><dd>{cr(f.pat)} <span className={tone(f.pat_growth)}>{pct(f.pat_growth)}</span></dd>
          {f.debt_to_equity != null && <><dt>Debt to equity</dt><dd>{f.debt_to_equity}</dd></>}
          {Object.entries(f.ratios || {}).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
        </dl>
      </div>
      {sc?.judged > 0 && (
        <div className="panel">
          <b style={{ fontWeight: 500 }}>Management kept {sc.kept} of {sc.judged} checkable promises</b>
          <ScoreBar sc={sc} />
          <span className="small faint">See the Promises tab for each one, with the quote and the delivered number.</span>
        </div>
      )}
      {r.financials.flags.map((fl) => <div key={fl.type} className="flag" style={{ marginRight: 6 }}>⚠ {fl.text}</div>)}
    </>
  );
}

function ScoreBar({ sc }) {
  const t = sc.judged || 1;
  return (
    <div className="ledger-score" aria-hidden>
      <span style={{ width: `${(sc.kept / t) * 100}%`, background: "var(--up)" }} />
      <span style={{ width: `${(sc.partly / t) * 100}%`, background: "var(--amber)" }} />
      <span style={{ width: `${(sc.missed / t) * 100}%`, background: "var(--down)" }} />
    </div>
  );
}

const V = { kept: ["✓", "up", "Kept"], partly: ["◐", "", "Partly"], missed: ["✗", "down", "Missed"], pending: ["…", "faint", "Pending"], unchecked: ["–", "faint", "Not checked today: model limit reached"], unjudged: ["?", "faint", "Can't check"] };

function Promises({ r }) {
  const sc = r.promise_score;
  if (!r.promises.length) return <p className="muted">No forward-looking guidance could be extracted and verified from the transcripts.</p>;
  return (
    <>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>{sc.kept} kept, {sc.partly} partly, {sc.missed} missed, {sc.pending} still pending{sc.unchecked ? `, ${sc.unchecked} not checked today` : ""}</b>
        <ScoreBar sc={sc} />
        <p className="small faint" style={{ margin: 0 }}>Numbers are checked in code against reported results. Other promises need a quote from a later call to count.</p>
      </div>
      {r.drift?.map((d, i) => (
        <div key={i} className="panel" style={{ borderColor: "var(--amber)" }}>
          <b style={{ fontWeight: 500 }}>Guidance {d.direction}: {d.metric.replace("_", " ")} for {d.period}</b>
          <p className="small muted" style={{ margin: "4px 0 0" }}>{d.history.map((h) => `${h.low}${h.high != null && h.high !== h.low ? "–" + h.high : ""}% (${h.said_in})`).join(", then ")}</p>
        </div>
      ))}
      <div className="panel">
        {r.promises.map((c, i) => {
          const [icon, cls, vlabel] = V[c.verdict] || V.unjudged;
          const label = c.verdict === "unchecked" && c.reason ? c.reason : vlabel;
          return (
            <details key={i} className="promise">
              <summary>
                <span className={`verdict ${cls}`} aria-label={label}>{icon}</span>
                <span><span>{c.statement}</span><br />
                  <span className="small faint">{label}. Said in the {c.said_in}{c.period ? `, for ${c.period}` : ""}{c.period_assumed ? " (period assumed)" : ""}.</span>
                  {c.reason && c.verdict !== "unchecked" && <><br /><span className="small muted">{c.reason}</span></>}
                </span>
              </summary>
              <div style={{ paddingLeft: 34 }}>
                <Quote source={c.source} />
                {c.delivered?.source && <p className="small faint">Delivered figure from {c.delivered.source}.</p>}
                {c.evidence && <><p className="small" style={{ marginBottom: 0 }}>Follow-up evidence:</p><Quote source={c.evidence} /></>}
              </div>
            </details>
          );
        })}
      </div>
    </>
  );
}

function Bars({ labels, series, colors, h = 120, fmt = (v) => num(v) }) {
  const all = series.flat().filter((v) => v != null);
  const max = Math.max(1, ...all), min = Math.min(0, ...all);
  const W = 320, pad = 18, n = labels.length, k = series.length;
  const bw = (W - pad) / n;
  const y = (v) => h - 16 - ((v - min) / (max - min || 1)) * (h - 30);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${h}`} role="img">
      {labels.map((l, i) => (
        <g key={l}>
          {series.map((s, j) => s[i] != null && (
            <rect key={j} x={pad / 2 + i * bw + j * ((bw - 6) / k) + 3} width={(bw - 6) / k - 2} y={Math.min(y(s[i]), y(0))}
              height={Math.abs(y(s[i]) - y(0))} rx="2" fill={colors[j]} />
          ))}
          <text x={pad / 2 + i * bw + bw / 2} y={h - 3} textAnchor="middle">{l.replace(/^Mar 20/, "FY")}</text>
          {k === 1 && series[0][i] != null && <text x={pad / 2 + i * bw + bw / 2} y={y(series[0][i]) - 3} textAnchor="middle">{fmt(series[0][i])}</text>}
        </g>
      ))}
    </svg>
  );
}

function Numbers({ fin }) {
  const t = fin.trajectory, b = fin.balance;
  return (
    <>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>Revenue, ₹ crore</b>
        <div className="row wrap" style={{ gap: 6, margin: "6px 0" }}>{t.tags.map((x) => <span key={x.label} className={`tag ${x.tone === "up" ? "good" : x.tone === "down" ? "bad" : ""}`}>{x.label}</span>)}</div>
        <Bars labels={t.years} series={[t.revenue]} colors={["var(--indigo)"]} />
        <p className="small muted" style={{ margin: "6px 0 0" }}>3-year revenue growth {t.revenue_cagr_3y ?? "—"}% a year, net profit {t.pat_cagr_3y ?? "—"}% a year.</p>
      </div>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>{fin.lender ? "Financing margin" : "Operating margin"}, %</b>
        <Bars labels={t.years} series={[t.opm]} colors={["var(--ink-3)"]} h={100} fmt={(v) => `${v}%`} />
        {t.opm_change_3y_bps != null && <p className="small muted" style={{ margin: "6px 0 0" }}>{bps(t.opm_change_3y_bps)} over three years.</p>}
      </div>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>Balance sheet</b>
        <table className="nums">
          <thead><tr><th></th>{b.years.slice(-4).map((y) => <th key={y}>{y.replace("Mar 20", "FY")}</th>)}</tr></thead>
          <tbody>
            <tr><td>Borrowings</td>{b.borrowings.slice(-4).map((v, i) => <td key={i}>{num(v)}</td>)}</tr>
            <tr><td>Net worth</td>{b.net_worth.slice(-4).map((v, i) => <td key={i}>{num(v)}</td>)}</tr>
            <tr><td>Debt / equity</td>{b.debt_to_equity.slice(-4).map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
          </tbody>
        </table>
        {Object.keys(b.cash_conversion_cycle || {}).length > 0 && (
          <p className="small muted">Cash conversion cycle: {Object.entries(b.cash_conversion_cycle).map(([k, v]) => `${v ?? "—"} days (${k.replace("Mar 20", "FY")})`).join(", ")}.</p>
        )}
      </div>
      <p className="small faint">Source: {fin.source.label}. <a href={fin.source.url} target="_blank" rel="noreferrer">Open</a></p>
    </>
  );
}

function Cash({ fin }) {
  const c = fin.cash;
  return (
    <div className="panel">
      <b style={{ fontWeight: 500 }}>Do profits turn into cash?</b>
      <p className="small muted" style={{ margin: "4px 0 8px" }}>{c.note}</p>
      <div className="row small" style={{ gap: 14 }}>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "var(--indigo)", borderRadius: 2 }} /> Cash from operations</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "var(--line)", borderRadius: 2 }} /> Net profit</span>
      </div>
      <Bars labels={c.years} series={[c.cfo, c.pat]} colors={["var(--indigo)", "var(--line)"]} />
      {c.cumulative_3y_pct != null && (
        <p style={{ marginBottom: 0 }}>Over three years, operating cash was <b style={{ fontWeight: 500 }}>{c.cumulative_3y_pct}%</b> of net profit.</p>
      )}
      {fin.flags.filter((f) => f.type === "cash_conversion").map((f) => <span key="cc" className="flag">⚠ {f.text}</span>)}
    </div>
  );
}

function BullBear({ r, onCite }) {
  const cite = (p) => onCite(
    <div>
      <h3 style={{ marginTop: 4 }}>{p.text}</h3>
      {p.facts.map((f) => <p key={f.id} className="small"><b>{f.id}</b> {f.text}</p>)}
      {p.source && <Quote source={p.source} />}
    </div>
  );
  const side = (title, pts) => (
    <div className="side">
      <h4>{title}</h4>
      {pts.length ? (
        <ol>{pts.map((p, i) => <li key={i}>{p.text} <button className="cite" onClick={() => cite(p)}>{p.source ? "quote" : p.facts.map((f) => f.id).join(" ")}</button></li>)}</ol>
      ) : <p className="small muted">No point survived the citation check.</p>}
    </div>
  );
  return (
    <>
      <div className="bb">{side("Bull case", r.bull)}{side("Bear case", r.bear)}</div>
      <p className="small faint">Every point cites a computed fact or a verified quote; tap a citation to see it. {r.trace?.dropped_uncited ? `${r.trace.dropped_uncited} uncited claim${r.trace.dropped_uncited === 1 ? " was" : "s were"} dropped.` : ""}</p>
    </>
  );
}

function Sources({ r }) {
  const t = r.trace || {};
  return (
    <>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>Documents read</b>
        {r.documents.map((d) => (
          <p key={d.url} className="small" style={{ margin: "6px 0" }}>
            <a href={d.url} target="_blank" rel="noreferrer">{d.label}</a> <span className="faint">{d.kind}{d.scanned ? ", scanned (quotes not checkable)" : d.pages ? `, ${d.pages} pages` : ""}</span>
          </p>
        ))}
        <p className="small" style={{ margin: "6px 0" }}><a href={r.financials.source.url} target="_blank" rel="noreferrer">{r.financials.source.label}</a> <span className="faint">financial tables</span></p>
      </div>
      <div className="panel">
        <b style={{ fontWeight: 500 }}>What it cost</b>
        <dl className="kv small" style={{ marginTop: 8 }}>
          <dt>Model calls</dt><dd>{t.model_calls ?? 0} ({Object.entries(t.by_tier || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "none"})</dd>
          <dt>Cached</dt><dd>{t.cached_calls ?? 0}</dd>
          <dt>Tokens</dt><dd>{num((t.input_tokens || 0) + (t.output_tokens || 0))}</dd>
          <dt>Uncited claims dropped</dt><dd>{t.dropped_uncited ?? 0}</dd>
          <dt>Time</dt><dd>{t.seconds ?? "—"} s</dd>
        </dl>
      </div>
    </>
  );
}
