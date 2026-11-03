import { useEffect } from "react";

export default function Sheet({ onClose, children, label }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label}>
        <div className="grabber" />
        {children}
        <button className="btn" style={{ width: "100%", marginTop: 22 }} onClick={onClose}>Close</button>
      </div>
    </>
  );
}
