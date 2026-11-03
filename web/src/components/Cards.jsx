import { Fragment } from "react";
import { bps, cr, crShort, initials, istDate, istTime, pct, timeAgo, tone } from "../lib/format";
import Quote from "./Quote";

const KIND_LABEL = {
  results: (c) => `${c.body?.period || "Quarterly"} results`,
  people: () => "Management change",
};
export const kindLabel = (c) => (KIND_LABEL[c.kind]?.(c)) || c.category_label || "Filing";

// ---------------------------------------------------------------- bodies
export function ResultsTable({ body, compact }) {
  if (!body?.rows) return null;
  return (
    <>
      <table className="nums">
        <thead>
          <tr><th></th><th>{body.unit.replace("₹ ", "₹ ")}</th><th>QoQ</th><th>YoY</th></tr>
        </thead>
        <tbody>
          {body.rows.map((r) => (
            <tr key={r.metric}>
              <td>{r.metric}{r.net_of_excise && <span className="small faint"> net of excise</span>}{r.verify && <span className="verify">verify in filing</span>}</td>
              <td>{crShort(r.cur)}</td>
              <td className={tone(r.qoq)}>{pct(r.qoq, 0)}</td>
              <td className={tone(r.yoy)}>{pct(r.yoy, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!compact && body.margins?.ebitda_margin != null && (
        <p className="small muted" style={{ margin: "8px 0 0" }}>
          EBITDA margin {body.margins.ebitda_margin}%, <span className={tone(body.margins.yoy_bps)}>{bps(body.margins.yoy_bps)}</span> YoY
        </p>
      )}
      {body.flags?.map((f) => <span key={f.type} className="flag">⚠ {f.text}</span>)}
    </>
  );
}

function Person({ p }) {
  const leaving = ["resigned", "retired", "ceased"].includes(p.change);
  const sub = [p.role, p.change, p.effective_date && `from ${p.effective_date}`].filter(Boolean).join(", ");
  return (
    <div className="person">
      <span className={`avatar ${leaving ? "out" : ""}`}>{initials(p.name)}</span>
      <div>
        <div className="nm">{p.name}</div>
        <div className="rl">{sub}</div>
        {!leaving && (p.previous_roles?.length || p.experience_years || p.qualifications?.length) ? (
          <ul>
            {p.previous_roles?.slice(0, 3).map((r) => <li key={r}>{r}</li>)}
            {p.experience_years ? <li>{p.experience_years} years of experience</li> : null}
            {p.qualifications?.length ? <li>{p.qualifications.join(", ")}</li> : null}
          </ul>
        ) : null}
        {p.reason && <div className="small faint">Reason given: {p.reason}</div>}
        {p.web_bio && <div className="small muted">{p.web_bio.summary}</div>}
      </div>
    </div>
  );
}

export function PeopleBody({ body }) {
  return body?.people?.map((p) => <Person key={p.name + p.change} p={p} />) || null;
}

export function Facts({ facts }) {
  if (!facts?.length) return null;
  return <div className="facts">{facts.map((f) => <span className="fact" key={f.label}>{f.label} <b>{f.value}</b></span>)}</div>;
}

export function CardBody({ card, compact }) {
  if (card.kind === "results") return <ResultsTable body={card.body} compact={compact} />;
  if (card.kind === "people") return <PeopleBody body={card.body} />;
  return (
    <>
      <p className="slab-line">{card.line || card.text || card.title}</p>
      {card.kind === "keyterms" && <Facts facts={card.body?.facts} />}
    </>
  );
}

// ---------------------------------------------------------------- slab (what matters) and row (the rest)
export function Slab({ card, onOpen, read, tracked, now }) {
  return (
    <button className={`slab ${card.tier} ${read ? "read" : ""}`} onClick={() => onOpen(card)}>
      {tracked && <span className="pin">Tracking</span>}
      <div className="slab-head">
        <span className="slab-co">{card.company}</span>
        <span className="slab-meta">{timeAgo(card.filed_at, now)}</span>
      </div>
      <div className="slab-kind">{kindLabel(card)}</div>
      <CardBody card={card} compact />
      <div className="slab-why">{card.why}</div>
    </button>
  );
}

export function Row({ card, onOpen, now }) {
  return (
    <button className="rowitem" onClick={() => onOpen(card)}>
      <span className="t"><b style={{ fontWeight: 500 }}>{card.company}</b> <span className="faint">{card.category_label}</span></span>
      <span className="r">{timeAgo(card.filed_at, now)}</span>
      <span className="s">{card.line || card.title}</span>
    </button>
  );
}

// ---------------------------------------------------------------- detail sheet
const CHECK_LABEL = {
  pat_le_pbt: "PAT is not above PBT",
  tax_identity: "PBT − tax = PAT",
  exceptional_identity: "PBT before exceptional + exceptional = PBT",
  cross_check_screener: "Revenue matches screener.in's quarterly table",
  found_in_text_layer: "Figures found in the filing's text",
};

const PART_LABEL = { base: "Category weight", subtype: "Filing type", role: "Role", direction: "Direction",
  size: "Size vs market cap", portfolio: "Your position size", preference: "You follow this category" };

export function CardDetail({ card, onTrack, tracked }) {
  const b = card.body || {};
  const parts = card.trace?.find((t) => t.layer === "L4_score")?.score_parts || {};
  return (
    <div>
      <div className="slab-head"><span className="slab-co" style={{ fontSize: 20 }}>{card.company}</span></div>
      <div className="slab-kind">{kindLabel(card)}, filed {istDate(card.filed_at)} at {istTime(card.filed_at)}</div>
      <CardBody card={card} />

      {card.kind === "results" && (
        <>
          <h3>Three quarters side by side</h3>
          <table className="nums">
            <thead><tr><th></th><th>This qtr</th><th>Last qtr</th><th>Year ago</th></tr></thead>
            <tbody>{b.rows.map((r) => <tr key={r.metric}><td>{r.metric}</td><td>{crShort(r.cur)}</td><td>{crShort(r.prev_q)}</td><td>{crShort(r.prev_y)}</td></tr>)}</tbody>
          </table>
          <p className="small faint">{b.basis === "consolidated" ? "Consolidated" : "Standalone"} figures, {b.unit}. {b.note}</p>
          {b.flags?.map((f) => f.type === "exceptional" && (
            <p key="ex" className="small muted">PBT before the one-off: {cr(f.pbt_before)}. After: {cr(f.pbt_after)}. FINN shows reported numbers only, so no "adjusted" profit is estimated.</p>
          ))}
          <h3>Checks</h3>
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
            {Object.entries(b.checks || {}).map(([k, v]) => (
              <li key={k} className="small" style={{ padding: "3px 0" }}>
                <span className={v ? "up" : "down"}>{v ? "✓" : "✗"}</span> {CHECK_LABEL[k] || k}
                {k === "found_in_text_layer" && v && b.provenance ? `, page ${Object.values(b.provenance)[0]}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}

      {card.kind === "people" && b.people?.some((p) => p.profile_source?.verified) && (
        <><h3>From the filing</h3>{b.people.map((p) => p.profile_source?.verified && <Quote key={p.name} source={{ ...p.profile_source, doc: "Filing" }} />)}</>
      )}
      {card.kind === "keyterms" && b.source?.verified && (<><h3>From the filing</h3><Quote source={{ ...b.source, doc: "Filing", url: card.url }} /></>)}
      {card.kind === "people" && b.people?.some((p) => p.web_bio) && (
        <p className="small faint">Background marked as web-sourced is a summary of public search results{b.people.find((p) => p.web_bio?.source_url) ? <>: <a href={b.people.find((p) => p.web_bio?.source_url).web_bio.source_url} target="_blank" rel="noreferrer">source</a></> : ""}.</p>
      )}

      {card.related?.length > 0 && (
        <>
          <h3>Filed alongside</h3>
          {card.related.map((r) => (
            <div key={r.filed_at + r.title} className="small" style={{ padding: "3px 0" }}>
              {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title} <span className="faint">{timeAgo(r.filed_at)}</span>
            </div>
          ))}
        </>
      )}

      <h3>Why is this here?</h3>
      <p className="small muted" style={{ marginTop: 0 }}>{card.why}. Priority {card.tier}, score {card.score}.</p>
      <dl className="kv small">
        {Object.entries(parts).map(([k, v]) => <Fragment key={k}><dt>{PART_LABEL[k] || k}</dt><dd>{k === "base" ? v : `× ${v}`}</dd></Fragment>)}
      </dl>
      <p className="small faint">
        Classified by {card.route === "rules" ? "keyword rules (no model call)" : card.route === "model" ? "rules, then the cheap model" : "rules only"}.
        {card.kind !== "plain" && card.kind !== "oneliner" ? " Details extracted by the cheap model, then checked in code." : ""}
      </p>

      <div className="row" style={{ gap: 10, marginTop: 18 }}>
        {card.url && <a className="btn" href={card.url} target="_blank" rel="noreferrer" style={{ textDecoration: "none", flex: 1, textAlign: "center" }}>Open filing</a>}
        {onTrack && <button className={`btn ${tracked ? "" : "btn-primary"}`} style={{ flex: 1 }} onClick={() => onTrack(card)}>{tracked ? "Stop tracking" : "Track"}</button>}
      </div>
    </div>
  );
}
