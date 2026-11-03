// Triage mode: the few items that matter, one at a time. Swipe right to track, left when done,
// tap to flip to the reasons and sources. Buttons do the same for people who don't swipe.
import { useRef, useState } from "react";
import { CardBody, kindLabel } from "./Cards";
import { timeAgo } from "../lib/format";

export default function CardStack({ cards, onTrack, onDone, onOpen, onUndo, total }) {
  const [dx, setDx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const start = useRef(null);
  const moved = useRef(false);
  const top = cards[0];

  if (!top) {
    return (
      <div className="empty">
        <p style={{ fontSize: 18, color: "var(--ink)" }}>All clear.</p>
        <p>You've been through {total === 1 ? "the one item" : `all ${total} items`} that needed attention.</p>
        {total > 0 && <button className="link" onClick={onUndo}>Start over</button>}
      </div>
    );
  }

  const finish = (dir) => {
    setDx(dir * 600);
    setTimeout(() => {
      setDx(0);
      setFlipped(false);
      (dir > 0 ? onTrack : onDone)(top);
    }, 180);
  };
  const down = (e) => { start.current = e.clientX; moved.current = false; e.currentTarget.setPointerCapture?.(e.pointerId); };
  const move = (e) => {
    if (start.current == null) return;
    const d = e.clientX - start.current;
    if (Math.abs(d) > 6) moved.current = true;
    setDx(d);
  };
  const up = () => {
    if (start.current == null) return;
    start.current = null;
    if (dx > 90) finish(1);
    else if (dx < -90) finish(-1);
    else { setDx(0); if (!moved.current) setFlipped((f) => !f); }
  };

  return (
    <>
      <div className="stack">
        {cards[2] && <div className="layer behind2" aria-hidden />}
        {cards[1] && <div className="layer behind" aria-hidden />}
        <div className="layer top" role="group" aria-label={`${top.company}, ${kindLabel(top)}`}
          style={{ transform: `translateX(${dx}px) rotate(${dx / 30}deg)`, transition: start.current != null ? "none" : undefined }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
          {dx > 30 && <span className="hint track">Track</span>}
          {dx < -30 && <span className="hint done">Done</span>}
          <div className="slab-head"><span className="slab-co" style={{ fontSize: 19 }}>{top.company}</span>
            <span className="slab-meta">{timeAgo(top.filed_at)}</span></div>
          <div className="slab-kind">{kindLabel(top)}</div>
          {!flipped ? (
            <>
              <CardBody card={top} />
              <p className="small faint" style={{ position: "absolute", bottom: 14, left: 18 }}>Tap to see why and the source</p>
            </>
          ) : (
            <div className="small">
              <p className="muted">{top.why}.</p>
              <p className="muted">Priority {top.tier}, score {top.score}.</p>
              <button className="link" onClick={(e) => { e.stopPropagation(); onOpen(top); }} onPointerDown={(e) => e.stopPropagation()}>
                Open full card with sources
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="stack-actions">
        <button className="btn" onClick={() => finish(-1)}>Done</button>
        <button className="btn btn-primary" onClick={() => finish(1)}>Track</button>
      </div>
      <p className="stack-progress">{total - cards.length + 1} of {total}</p>
    </>
  );
}
