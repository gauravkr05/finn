// The market day as a line: Opening Brief before the open, Closing Bell after the close, and now.
// This is FINN's point of view drawn: it speaks at two moments, not all day.
const START = 7, END = 18; // 07:00 to 18:00 IST
const pos = (h) => `${3 + ((h - START) / (END - START)) * 94}%`;
const toH = (t) => { const [h, m] = t.split(":").map(Number); return h + m / 60; };
const fmt = (t) => { const [h, m] = t.split(":").map(Number); return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")}`; };

export function istHour(d = new Date()) {
  const s = d.toLocaleString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
  const [h, m] = s.split(":").map(Number);
  return h + m / 60;
}

export default function DayRhythm({ opening = "08:30", closing = "16:00" }) {
  const o = toH(opening), c = toH(closing);
  const nowH = istHour();
  const now = Math.min(END, Math.max(START, nowH));
  const line = { position: "absolute", top: 19, height: 2, background: "var(--line)" };
  return (
    <div role="img" aria-label={`FINN speaks twice a day: Opening Brief at ${opening} and Closing Bell at ${closing} IST.`}
      style={{ position: "relative", height: 52, margin: "8px 0 0" }}>
      <span style={{ position: "absolute", top: 0, left: pos(9.25), fontSize: 11, color: "var(--ink-3)" }}>market hours</span>
      <div style={{ ...line, left: "3%", right: "3%" }} />
      <div style={{ ...line, top: 18, height: 4, borderRadius: 2, background: "var(--ink-3)", left: pos(9.25),
        width: `calc(${pos(15.5)} - ${pos(9.25)})` }} />
      <Dot at={pos(o)} done={nowH >= o} />
      <Dot at={pos(c)} done={nowH >= c} />
      <div title="Now" style={{ position: "absolute", top: 11, left: pos(now), width: 2, height: 18, marginLeft: -1,
        background: "var(--down)", borderRadius: 1 }} />
      <span style={{ position: "absolute", top: 32, left: pos(o), transform: "translateX(-18%)", fontSize: 12,
        color: "var(--ink-2)", whiteSpace: "nowrap" }}>Opening Brief {fmt(opening)}</span>
      <span style={{ position: "absolute", top: 32, left: pos(c), transform: "translateX(-82%)", fontSize: 12,
        color: "var(--ink-2)", whiteSpace: "nowrap" }}>Closing Bell {fmt(closing)}</span>
    </div>
  );
}

function Dot({ at, done }) {
  return (
    <span aria-hidden style={{
      position: "absolute", left: at, top: 13, width: 14, height: 14, marginLeft: -7, borderRadius: "50%",
      background: done ? "var(--indigo)" : "var(--surface)", border: "2.5px solid var(--indigo)", boxSizing: "border-box",
    }} />
  );
}
