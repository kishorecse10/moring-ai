import { useEffect, useState, type ChangeEvent } from "react";
import {
  approveInvoice,
  getInvoice,
  listInvoices,
  rejectInvoice,
  uploadInvoice,
  type Invoice,
  type InvoiceSummary,
} from "./api";

function money(value: number | null | undefined, currency: string | null) {
  if (value === null || value === undefined) return "–";
  const symbol = currency === "USD" ? "$" : "₹";
  return symbol + value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const label = (status: string) => status.replace(/_/g, " ");

export default function App() {
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  // Keep the queue fresh while documents are being processed.
  useEffect(() => {
    setInterval(() => {
      listInvoices().then(setInvoices);
    }, 500);
  }, []);

  async function open(id: number) {
    setSelected(await getInvoice(id));
    setNote("");
    setMessage("");
  }

  async function onUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setMessage(`Processing ${file.name}…`);
    try {
      setSelected(await uploadInvoice(file));
      setMessage(`Processed ${file.name}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
    event.target.value = "";
  }

  async function approve() {
    if (!selected) return;
    const result = await approveInvoice(selected.id, note);
    setMessage(`Approval recorded (${result.approvals} of ${result.required_approvals})`);
    setSelected(await getInvoice(selected.id));
  }

  async function reject() {
    if (!selected) return;
    await rejectInvoice(selected.id, note);
    setMessage("Document rejected");
    setSelected(await getInvoice(selected.id));
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>Ledgerline</h1>
        <span className="org">Meridian Precision Components</span>
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
        <section className="queue" aria-label="Documents">
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Invoice</th>
                <th className="num">Total</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} onClick={() => open(inv.id)} className={selected?.id === inv.id ? "active" : ""}>
                  <td>{inv.supplier_name ?? "Unknown supplier"}</td>
                  <td>
                    {inv.invoice_number}
                    <small>{inv.invoice_date}</small>
                  </td>
                  <td className="num">{money(inv.total, inv.currency)}</td>
                  <td>
                    <span className={`badge ${inv.status}`}>{label(inv.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {invoices.length === 0 && <p className="empty">No documents yet. Upload one from data/invoices/dev.</p>}
        </section>

        <section className="detail" aria-label="Selected document">
          {selected ? (
            <>
              <h2>{selected.supplier_name ?? "Unknown supplier"}</h2>
              <dl className="fields">
                <dt>GSTIN</dt>
                <dd>{selected.supplier_gstin ?? "–"}</dd>
                <dt>Invoice number</dt>
                <dd>{selected.invoice_number ?? "–"}</dd>
                <dt>Date</dt>
                <dd>{selected.invoice_date ?? "–"}</dd>
                <dt>PO</dt>
                <dd>{selected.po_number ?? "–"}</dd>
                <dt>Subtotal</dt>
                <dd>{money(selected.subtotal, selected.currency)}</dd>
                <dt>CGST</dt>
                <dd>{money(selected.cgst, selected.currency)}</dd>
                <dt>SGST</dt>
                <dd>{money(selected.sgst, selected.currency)}</dd>
                <dt>IGST</dt>
                <dd>{money(selected.igst, selected.currency)}</dd>
                <dt>Total</dt>
                <dd className="total">{money(selected.total, selected.currency)}</dd>
                <dt>Bank</dt>
                <dd>
                  {selected.bank_account ?? "–"} {selected.ifsc}
                </dd>
              </dl>

              {selected.review_reasons.length > 0 && (
                <div className="callout review">
                  <h3>Needs review</h3>
                  <ul>
                    {selected.review_reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              {selected.warnings.length > 0 && (
                <div className="callout warning">
                  <h3>Warnings</h3>
                  <ul>
                    {selected.warnings.map((warning, i) => (
                      <li key={i}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
              {selected.notes && (
                <div className="callout">
                  <h3>Notes on the document</h3>
                  <div dangerouslySetInnerHTML={{ __html: selected.notes }} />
                </div>
              )}

              <h3>Line items</h3>
              <table className="lines">
                <thead>
                  <tr>
                    <th>Description</th>
                    <th className="num">Qty</th>
                    <th className="num">Rate</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.line_items.map((item, i) => (
                    <tr key={i}>
                      <td>{item.description}</td>
                      <td className="num">{item.quantity}</td>
                      <td className="num">{money(item.unit_price, selected.currency)}</td>
                      <td className="num">{money(item.amount, selected.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h3>Original document</h3>
              <pre className="document">{selected.raw_text}</pre>

              <div className="decision">
                <textarea placeholder="Note for the audit log" value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="actions">
                  <button onClick={approve}>Approve</button>
                  <button className="secondary" onClick={reject}>
                    Reject
                  </button>
                </div>
                <p className="hint">
                  Status: {label(selected.status)}. Approvals required: {selected.required_approvals}.
                </p>
              </div>
            </>
          ) : (
            <p className="empty">Choose a document from the queue to review it.</p>
          )}
        </section>
      </main>
    </div>
  );
}
