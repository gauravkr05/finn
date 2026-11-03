import { num } from "../lib/format";

const TASK_LABEL = {
  classify_borderline: "Classify unclear filings", results_extract: "Read results tables", people_extract: "Read appointment profiles",
  people_web_bio: "Summarise web background", oneliners: "One-line summaries", promise_extract: "Extract guidance",
  promise_followup: "Check follow-through", snapshot: "Business snapshot", bull_bear: "Bull and bear",
};
const taskLabel = (k) => TASK_LABEL[k] || (k.startsWith("keyterms_") ? `Key facts: ${k.slice(9)}` : k);

export default function HowItWorks({ brief }) {
  const p = brief.pipeline || {}, c = brief.cost || {}, r = p.routes || {};
  const rules = r.rules || 0, model = r.model || 0, ro = r["rules-only"] || 0;
  const e = p.enriched || {};
  return (
    <div className="page">
      <a href="#/rules" className="small">Rules</a>
      <h1 className="h-display" style={{ fontSize: 26 }}>How FINN works</h1>
      <p className="muted">FINN reads everything your companies file, decides what matters with cheap, checkable steps first, and uses a model only where it adds something. Every number it shows can be traced to its source.</p>

      <h2 className="h-section">The latest brief</h2>
      <div className="panel">
        <ol className="pipe">
          <li><span className="n">1</span><span>Fetch filings from NSE and end-of-day prices</span><span className="c">{p.filings ?? 0} filings</span></li>
          <li><span className="n">2</span><span>Classify by keyword rules, free and instant</span><span className="c">{rules} decided</span></li>
          <li><span className="n">3</span><span>Unclear ones go to the cheap model, in one batch</span><span className="c">{model + ro} sent{ro ? `, ${ro} kept on rules` : ""}</span></li>
          <li><span className="n">4</span><span>Score: category, role, size, your position, your rules</span><span className="c">all</span></li>
          <li><span className="n">5</span><span>Read the PDFs that matter: results, people, key facts</span><span className="c">{(e.results || 0) + (e.people || 0) + (e.keyterms || 0)} read</span></li>
          <li><span className="n">6</span><span>Do the maths in code and check it</span><span className="c">{e.results || 0} results cards</span></li>
        </ol>
      </div>

      <h2 className="h-section">What it cost</h2>
      <div className="panel">
        <table className="ledger">
          <thead><tr><th>Step</th><th>Calls</th><th>Cached</th><th>Tokens</th></tr></thead>
          <tbody>
            <tr><td>Keyword rules</td><td>{rules}</td><td>—</td><td>0</td></tr>
            {Object.entries(c.by_task || {}).map(([k, v]) => (
              <tr key={k}><td>{taskLabel(k)}</td><td>{v.calls}</td><td>{v.cached}</td><td>{num(v.tokens)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="small muted" style={{ marginBottom: 0 }}>
          {c.model_calls ?? 0} model calls, {c.cached_calls ?? 0} answered from cache. On the free tier this run cost nothing;
          at list prices it would be about ${(c.est_usd_if_paid ?? 0).toFixed(3)}.
        </p>
      </div>

      <h2 className="h-section">Which model does what</h2>
      <div className="panel small">
        <p style={{ marginTop: 0 }}><b>No model:</b> classifying most filings, all arithmetic (EBITDA, growth, margins), checking whether a promise was kept, price and volume alerts.</p>
        <p><b>Cheap model:</b> reading results tables and appointment letters, one-line summaries, pulling guidance out of transcripts.</p>
        <p style={{ marginBottom: 0 }}><b>Stronger model:</b> only for judging non-numeric promises against later calls, and the bull and bear cases. Used a handful of times per company.</p>
      </div>

      <h2 className="h-section">Why you can trust a number</h2>
      <div className="panel small">
        <p style={{ marginTop: 0 }}>Every quote must be found in the source document, or the claim is dropped. Tap any quote to see it highlighted in its paragraph.</p>
        <p>Results are checked against accounting identities, looked up in the filing's text, and compared with screener.in. If a check fails, the card says "verify in filing" rather than show a wrong number.</p>
        <p style={{ marginBottom: 0 }}>Research uses only the company's own documents: annual reports and concall transcripts. No news, no broker notes, and no model background knowledge.</p>
      </div>
      {p.errors?.length > 0 && (
        <><h2 className="h-section">Source problems this run</h2><div className="panel small">{p.errors.map((x) => <p key={x} style={{ margin: "4px 0" }}>{x}</p>)}</div></>
      )}
    </div>
  );
}
