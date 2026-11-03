// A source paragraph with the exact quoted sentence highlighted. The highlight comes from the same
// step that verified the citation, so what you see is what FINN checked.
export default function Quote({ source, fallback }) {
  if (!source) return null;
  if (source.verified === false) {
    return <p className="small faint">{source.note || "This quote couldn't be checked against the source."}</p>;
  }
  const para = source.paragraph || source.quote || fallback || "";
  const q = source.quote || "";
  const i = q ? para.toLowerCase().indexOf(q.toLowerCase()) : -1;
  return (
    <blockquote className="quote">
      {i >= 0 ? (
        <>
          {para.slice(0, i)}
          <mark>{para.slice(i, i + q.length)}</mark>
          {para.slice(i + q.length)}
        </>
      ) : (
        <mark>{para}</mark>
      )}
      <span className="src">
        {source.doc || "Filing"}
        {source.page ? `, page ${source.page}` : ""}
        {source.url ? <> · <a href={source.url} target="_blank" rel="noreferrer">open PDF</a></> : null}
      </span>
    </blockquote>
  );
}
