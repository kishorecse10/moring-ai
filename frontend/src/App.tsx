import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  REVIEWERS,
  approveInvoice,
  getInvoice,
  getQueue,
  rejectInvoice,
  uploadInvoice,
  type Evidence,
  type Invoice,
  type Queue,
  type SpanRef,
} from "./api";

function money(value: number | string | null | undefined, currency: string | null) {
  if (value === null || value === undefined || value === "") return "–";
  const amount = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(amount)) return String(value);
  const symbol = currency === "INR" || currency === null ? "₹" : currency === "USD" ? "$" : `${currency} `;
  return symbol + amount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const label = (status: string) => status.replace(/_/g, " ");

type Highlight = SpanRef & { kind: "field" | "suspicious"; key: string };

/**
 * The original document with highlighted spans. Built from plain string slices rendered as React text, so a
 * document's markup (dev_013's <img onerror=...>) is shown, never executed. Overlapping spans keep the first.
 */
function DocumentView({ text, highlights, selected }: { text: string; highlights: Highlight[]; selected: string | null }) {
  const selectedRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected, text]);

  const parts: JSX.Element[] = [];
  let cursor = 0;
  const sorted = [...highlights].sort((a, b) => a.start - b.start || b.end - a.end);
  for (const h of sorted) {
    if (h.start < cursor || h.end > text.length || text.slice(h.start, h.end) !== h.text) continue;
    if (h.start > cursor) parts.push(<span key={`t${cursor}`}>{text.slice(cursor, h.start)}</span>);
    const isSelected = h.key === selected;
    parts.push(
      <mark
        key={`h${h.start}`}
        className={`${h.kind}${isSelected ? " selected" : ""}`}
        ref={isSelected ? (el) => (selectedRef.current = el) : undefined}
        title={h.key}
      >
        {text.slice(h.start, h.end)}
      </mark>,
    );
    cursor = h.end;
  }
  if (cursor < text.length) parts.push(<span key={`t${cursor}`}>{text.slice(cursor)}</span>);
  return <pre className="document">{parts}</pre>;
}

/** The "Source" cell: a link to the exact place, or an honest "not sure". */
function SourceCell({ evidence, onShow }: { evidence?: Evidence; onShow: () => void }) {
  if (!evidence) return <span className="src none">–</span>;
  if (evidence.status === "exact")
    return (
      <button className="src exact" onClick={onShow} title={evidence.basis}>
        line {evidence.line}
      </button>
    );
  if (evidence.status === "ambiguous")
    return (
      <span className="src ambiguous" title={evidence.basis}>
        not sure: lines {evidence.candidates.map((c) => c.line).join(", ")}
      </span>
    );
  return <span className="src missing">not in the document</span>;
}

const FIELDS: { key: string; name: string; money?: boolean }[] = [
  { key: "supplier_name", name: "Supplier" },
  { key: "supplier_gstin", name: "GSTIN" },
  { key: "invoice_number", name: "Invoice number" },
  { key: "invoice_date", name: "Date" },
  { key: "po_number", name: "PO" },
  { key: "subtotal", name: "Subtotal", money: true },
  { key: "cgst", name: "CGST", money: true },
  { key: "sgst", name: "SGST", money: true },
  { key: "igst", name: "IGST", money: true },
  { key: "round_off", name: "Round-off", money: true },
  { key: "total", name: "Total", money: true },
  { key: "bank_account", name: "Bank account" },
  { key: "ifsc", name: "IFSC" },
];

export default function App() {
  const [queue, setQueue] = useState<Queue>({ counts: { review: 0, approve: 0 }, items: [] });
  const [tab, setTab] = useState<"review" | "approve">("review");
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState(REVIEWERS[0]);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  const refresh = useCallback(() => getQueue().then(setQueue).catch(() => undefined), []);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const items = useMemo(() => queue.items.filter((i) => i.bucket === tab), [queue, tab]);

  const open = useCallback(async (id: number) => {
    try {
      setSelected(await getInvoice(id));
      setFocusKey(null);
      setNote("");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }, []);

  async function onUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setMessage(`Processing ${file.name}…`);
    try {
      const inv = await uploadInvoice(file);
      setSelected(inv);
      setTab(inv.needs_review ? "review" : "approve");
      setMessage(`Processed ${file.name}`);
      refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
    event.target.value = "";
  }

  const move = useCallback(
    (step: number) => {
      if (items.length === 0) return;
      const index = selected ? items.findIndex((i) => i.id === selected.id) : -1;
      const next = items[Math.min(items.length - 1, Math.max(0, index + step))];
      if (next && next.id !== selected?.id) open(next.id);
    },
    [items, selected, open],
  );

  // The server enforces every approval rule and is safe under retries; `busy` only prevents accidental repeats.
  const decide = useCallback(
    async (action: "approve" | "reject") => {
      if (!selected || busy) return;
      setBusy(true);
      try {
        if (action === "approve") {
          const r = await approveInvoice(selected.id, user, note);
          setMessage(`Approval recorded by ${user} (${r.approvals} of ${r.required_approvals}).`);
        } else {
          await rejectInvoice(selected.id, user, note);
          setMessage("Document rejected.");
        }
        await refresh();
        const after = await getInvoice(selected.id);
        if (after.status === "approved" || after.status === "rejected") move(1);
        else setSelected(after);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [selected, busy, user, note, refresh, move],
  );

  // Keyboard: j/k next and previous, a approve, r reject, n write a note. Ignored while typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.tagName === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") move(1);
      else if (e.key === "k" || e.key === "ArrowUp") move(-1);
      else if (e.key === "a") decide("approve");
      else if (e.key === "r") decide("reject");
      else if (e.key === "n") {
        e.preventDefault();
        noteRef.current?.focus();
      } else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move, decide]);

  const highlights: Highlight[] = useMemo(() => {
    if (!selected) return [];
    const out: Highlight[] = [];
    for (const [key, e] of Object.entries(selected.evidence ?? {}))
      if (e.status === "exact") out.push({ ...e, kind: "field", key });
    for (const x of selected.explanations ?? [])
      for (const ev of x.evidence)
        if (ev.field.startsWith("suspicious")) out.push({ ...ev, kind: "suspicious", key: `${x.code}:${ev.start}` });
    return out;
  }, [selected]);

  const blocked =
    selected &&
    (selected.review_reasons.includes("duplicate")
      ? "Duplicates can't be approved (policy 4.4)."
      : selected.document_type === "credit_note"
        ? "Credit notes are never approved for payment."
        : null);

  return (
    <div className="app">
      <header className="topbar">
        <h1>Ledgerline</h1>
        <span className="org">Meridian Precision Components</span>
        <label className="acting">
          Acting as{" "}
          <select value={user} onChange={(e) => setUser(e.target.value)} aria-label="Acting as (no sign-in yet)">
            {REVIEWERS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="upload">
          Upload document
          <input type="file" accept=".txt,.eml,.json" onChange={onUpload} />
        </label>
      </header>
      {message && (
        <p className="message" role="status">
          {message}
        </p>
      )}

      <main className="layout">
        <section className="queue" aria-label="Queue">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "review"} onClick={() => setTab("review")}>
              Needs review <span className="count">{queue.counts.review}</span>
            </button>
            <button role="tab" aria-selected={tab === "approve"} onClick={() => setTab("approve")}>
              Ready to approve <span className="count">{queue.counts.approve}</span>
            </button>
          </div>
          <ul className="items">
            {items.map((item) => (
              <li key={item.id}>
                <button className={selected?.id === item.id ? "item active" : "item"} onClick={() => open(item.id)}>
                  <span className="row">
                    <strong>{item.supplier_name ?? "Unknown supplier"}</strong>
                    <span className="num">{money(item.total, item.currency)}</span>
                  </span>
                  <span className="row muted">
                    <span>
                      {item.invoice_number ?? "–"} · {item.invoice_date ?? "no date"}
                    </span>
                    {item.days_since_invoice !== null && (
                      <span className={item.days_since_invoice >= 30 ? "age late" : "age"}>
                        {item.days_since_invoice} days
                      </span>
                    )}
                  </span>
                  {item.reason_titles.length > 0 && (
                    <span className="reasons">
                      {item.reason_titles.map((t) => (
                        <span key={t} className="chip">
                          {t}
                        </span>
                      ))}
                    </span>
                  )}
                  {item.required_approvals > 1 && (
                    <span className="muted">
                      approvals {item.approvals} of {item.required_approvals}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {items.length === 0 && <p className="empty">Nothing waiting here.</p>}
          <p className="keys">Keys: j / k next and previous · a approve · r reject · n note</p>
        </section>

        <section className="detail" aria-label="Selected document">
          {selected ? (
            <>
              <h2>
                {selected.supplier_name ?? "Unknown supplier"} <span className={`badge ${selected.status}`}>{label(selected.status)}</span>
              </h2>

              {selected.explanations?.length > 0 && (
                <div className="reasons-panel">
                  {selected.explanations.map((x) => (
                    <article key={x.code} className={`reason ${x.code}`}>
                      <h3>{x.title}</h3>
                      <p>{x.detail}</p>
                      <p className="action">{x.action}</p>
                      {x.evidence.length > 0 && (
                        <p className="evidence">
                          {x.evidence.map((ev) => {
                            const key = ev.field.startsWith("suspicious") ? `${x.code}:${ev.start}` : ev.field;
                            return (
                              <button key={`${ev.field}${ev.start}`} className="src exact" onClick={() => setFocusKey(key)}>
                                {ev.field.replace(/_/g, " ")}, line {ev.line}
                              </button>
                            );
                          })}
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              )}

              <div className="split">
                <div>
                  <h3>Extracted values</h3>
                  <table className="fields">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th className="num">Value</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {FIELDS.map((f) => {
                        const value = (selected as unknown as Record<string, string | number | null>)[f.key];
                        if (value === null || value === undefined) return null;
                        return (
                          <tr key={f.key} className={focusKey === f.key ? "active" : ""}>
                            <td>{f.name}</td>
                            <td className="num">{f.money ? money(value, selected.currency) : value}</td>
                            <td>
                              <SourceCell evidence={selected.evidence?.[f.key]} onShow={() => setFocusKey(f.key)} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  <h3>Line items</h3>
                  <table className="lines">
                    <thead>
                      <tr>
                        <th>Description</th>
                        <th className="num">Qty</th>
                        <th className="num">Rate</th>
                        <th className="num">Amount</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.line_items.map((item, i) => {
                        const key = `line_items[${i}].amount`;
                        return (
                          <tr key={i} className={focusKey === key ? "active" : ""}>
                            <td>{item.description}</td>
                            <td className="num">{item.quantity}</td>
                            <td className="num">{money(item.unit_price, selected.currency)}</td>
                            <td className="num">{money(item.amount, selected.currency)}</td>
                            <td>
                              <SourceCell evidence={selected.evidence?.[key]} onShow={() => setFocusKey(key)} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  {selected.notes && (
                    <div className="callout">
                      <h3>Notes on the document</h3>
                      {/* Plain text only: this comes from the vendor's document. */}
                      <p className="notes">{selected.notes}</p>
                    </div>
                  )}

                  <div className="decision">
                    {selected.approvals?.length > 0 && (
                      <p className="hint">
                        Approved so far by {selected.approvals.map((a) => a.user_id).join(", ")}.
                      </p>
                    )}
                    <textarea
                      ref={noteRef}
                      placeholder={selected.needs_review ? "Note for the audit log (required to approve)" : "Note for the audit log"}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <div className="actions">
                      <button onClick={() => decide("approve")} disabled={busy || !!blocked} title={blocked ?? undefined}>
                        Approve as {user}
                      </button>
                      <button className="secondary" onClick={() => decide("reject")} disabled={busy}>
                        Reject
                      </button>
                    </div>
                    <p className="hint">
                      {blocked ?? `Approvals required: ${selected.required_approvals}.`} The server enforces these rules.
                    </p>
                  </div>
                </div>

                <div>
                  <h3>Original document</h3>
                  <DocumentView text={selected.raw_text} highlights={highlights} selected={focusKey} />
                </div>
              </div>
            </>
          ) : (
            <p className="empty">Choose a document from the queue, or press j.</p>
          )}
        </section>
      </main>
    </div>
  );
}
