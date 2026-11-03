// Formatting helpers. Amounts are ₹ crore with Indian digit grouping.
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

export const cr = (v) => (v == null ? "—" : `₹${(Math.abs(v) >= 100 ? inr : inr1).format(v)} cr`);
export const crShort = (v) => (v == null ? "—" : (Math.abs(v) >= 100 ? inr : inr1).format(v));
export const num = (v, d = 0) => (v == null ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: d }).format(v));
export const pct = (v, d = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`);
export const tone = (v) => (v == null || v === 0 ? "" : v > 0 ? "up" : "down");
export const bps = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)} bps`);

export function timeAgo(iso, ref = new Date()) {
  const s = (new Date(ref) - new Date(iso)) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  const d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : `${d}d ago`;
}

export function istTime(iso) {
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit" });
}

export function istDate(iso) {
  return new Date(iso).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });
}

export const initials = (name = "") =>
  name.replace(/^(Mr|Ms|Mrs|Dr)\.?\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
