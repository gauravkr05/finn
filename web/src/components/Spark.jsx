import { sparkPath } from "../lib/alerts";

export default function Spark({ rows, w = 80, h = 26, className = "spark" }) {
  if (!rows?.length) return <svg className={className} />;
  const first = rows[0].c, last = rows[rows.length - 1].c;
  return (
    <svg className={className} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <path d={sparkPath(rows, w, h)} fill="none" stroke={last >= first ? "var(--up)" : "var(--down)"} strokeWidth="1.5" />
    </svg>
  );
}
