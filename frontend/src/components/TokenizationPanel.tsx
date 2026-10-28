import type { TokenizationResult } from "../types";

interface Props {
  result: TokenizationResult | null;
  source?: string; // where the tokens came from, e.g. "task task_x" or "preview"
}

/** Original text with token boundaries, token table, tokenizer name and an honest approximation badge. */
export function TokenizationPanel({ result, source }: Props) {
  if (!result) {
    return <p className="empty">No tokenization yet. Submit a command or use "Preview tokens".</p>;
  }
  const approximate = !result.is_live_model_tokenization || result.tokens.some((t) => t.is_approximate);
  return (
    <section className="tokenization" aria-label="Tokenization">
      <div className="kv-row">
        <span className="kv"><b>Tokenizer</b> <code>{result.tokenizer_name}</code></span>
        {approximate ? (
          <span className="badge badge--warning" role="status">Approximation — not the model's tokenizer; no token IDs</span>
        ) : (
          <span className="badge badge--info">Real tokenizer output</span>
        )}
        <span className="kv"><b>Tokens</b> {result.tokens.length}</span>
        {source && <span className="kv muted">{source}</span>}
      </div>
      {result.note && <p className="note">{result.note}</p>}
      <p className="note">Tokenization is shown for inspection only. It does not decide any physical action.</p>

      <div className="token-text" aria-label="Original text with token boundaries">
        {segments(result).map((seg, i) =>
          seg.token === null ? (
            <span key={i} className="token-gap">{seg.text}</span>
          ) : (
            <span key={i} className={`token token--${seg.token % 2 ? "odd" : "even"}`} title={`#${seg.token}`}
                  data-token-index={seg.token}>
              {seg.text}
            </span>
          ),
        )}
      </div>

      <table className="table">
        <thead>
          <tr><th>#</th><th>Text</th><th>Span</th><th>Token ID</th><th>Role</th></tr>
        </thead>
        <tbody>
          {result.tokens.map((t) => (
            <tr key={t.index}>
              <td>{t.index}</td>
              <td><code>{t.text}</code></td>
              <td>{t.start}–{t.end}</td>
              <td>{t.token_id === null ? <span className="muted">n/a</span> : t.token_id}</td>
              <td>{t.role ?? <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function segments(result: TokenizationResult): { text: string; token: number | null }[] {
  const out: { text: string; token: number | null }[] = [];
  let pos = 0;
  for (const t of [...result.tokens].sort((a, b) => a.start - b.start)) {
    if (t.start > pos) out.push({ text: result.raw_text.slice(pos, t.start), token: null });
    out.push({ text: result.raw_text.slice(t.start, t.end), token: t.index });
    pos = Math.max(pos, t.end);
  }
  if (pos < result.raw_text.length) out.push({ text: result.raw_text.slice(pos), token: null });
  return out;
}
