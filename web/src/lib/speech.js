// ▶ Listen: the browser's own speech engine. Free, and it starts only on tap (mobile browsers require it).
const pctWords = (v) => (v == null ? "" : `${v >= 0 ? "up" : "down"} ${Math.abs(Math.round(v))} percent`);

function cardSentence(c) {
  const name = c.company || c.symbol;
  if (c.kind === "results" && c.body) {
    const top = c.body.rows.find((r) => r.metric === (c.body.lender ? "Total income" : "Revenue"));
    const pat = c.body.rows.find((r) => r.metric === "PAT");
    const bits = [];
    if (top?.yoy != null) bits.push(`${c.body.lender ? "total income" : "revenue"} ${pctWords(top.yoy)} year on year`);
    if (pat?.yoy != null) bits.push(`profit after tax ${pctWords(pat.yoy)}`);
    return `${name} reported ${c.body.period || "quarterly"} results${bits.length ? ": " + bits.join(", ") : ""}${c.body.flags?.length ? ", including a one-off item" : ""}.`;
  }
  if (c.kind === "people" && c.body?.people?.length) {
    const out = c.body.people.find((p) => ["resigned", "retired", "ceased"].includes(p.change));
    const inn = c.body.people.find((p) => ["appointed", "re-appointed", "redesignated"].includes(p.change));
    if (out && inn) return `${name}: ${out.name} has ${out.change} as ${out.role}, and ${inn.name} takes over.`;
    if (out) return `${name}: ${out.name} has ${out.change} as ${out.role}.`;
    if (inn) return `${name} has appointed ${inn.name} as ${inn.role}.`;
  }
  return `${name}: ${(c.line || c.title || "").replace(/\.$/, "")}.`;
}

export function buildSpoken(items, moves, names, routine, hour = new Date().getHours()) {
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const top = items.filter((c) => c.tier === "critical" || c.tier === "high").slice(0, 3);
  const parts = [`${greet}.`];
  if (top.length) {
    parts.push(top.length === 1 ? "One thing needs your attention." : `${top.length} things need your attention.`);
    top.forEach((c) => parts.push(cardSentence(c)));
  } else parts.push("Nothing material was filed across your portfolio.");
  moves.slice(0, 2).forEach((m) =>
    parts.push(`${names[m.symbol] || m.symbol} moved ${pctWords(m.move_pct)} on ${m.volume_ratio.toFixed(1)} times its usual volume.`));
  if (routine) parts.push(`${routine} routine filings are hidden.`);
  return parts.join(" ");
}

export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export function speak(text, onEnd) {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/(\d)\s*%/g, "$1 percent").replace(/₹\s?/g, "rupees ").replace(/\bcr\b/g, "crore")
    .replace(/\bRs\.?\s?/g, "rupees ");
  const u = new SpeechSynthesisUtterance(clean);
  const voices = window.speechSynthesis.getVoices();
  u.voice = voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang?.startsWith("en-GB"))
    || voices.find((v) => v.lang?.startsWith("en")) || null;
  u.rate = 1.02;
  u.onend = u.onerror = () => onEnd?.();
  window.speechSynthesis.speak(u);
}

export const stopSpeaking = () => canSpeak() && window.speechSynthesis.cancel();
