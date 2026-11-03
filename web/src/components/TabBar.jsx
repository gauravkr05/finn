const I = {
  today: <path d="M3 13h4l3-7 4 12 3-5h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />,
  portfolio: <g fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="5" width="16" height="14" rx="3" /><path d="M4 10h16M9 5v14" /></g>,
  research: <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="11" cy="11" r="6" /><path d="M16 16l4 4" /></g>,
  rules: <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></g>,
};
const TABS = [["today", "Today"], ["portfolio", "Portfolio"], ["research", "Research"], ["rules", "Rules"]];

export default function TabBar({ current, todayCount }) {
  return (
    <div className="tabbar">
      <nav aria-label="Main">
        {TABS.map(([k, label]) => (
          <a key={k} href={`#/${k}`} aria-current={current === k ? "page" : undefined}>
            <span style={{ position: "relative" }}>
              <svg viewBox="0 0 24 24">{I[k]}</svg>
              {k === "today" && todayCount > 0 && <span className="badge-dot">{todayCount}</span>}
            </span>
            {label}
          </a>
        ))}
      </nav>
    </div>
  );
}
