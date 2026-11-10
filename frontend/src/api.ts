export const ORG_ID = "meridian";

// There is no sign-in yet (FINDINGS: "found but not fixed"). The reviewer picks who they are acting as, so the
// two-person rule can be exercised; the server counts distinct user_ids, which is only as strong as this choice.
export const REVIEWERS = ["kavya.iyer", "farhan.sheikh", "sunil.joshi"];

export type InvoiceSummary = {
  id: number;
  document_id: string;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  total: number | null;
  status: string;
  needs_review: number | boolean;
};

export type QueueItem = InvoiceSummary & {
  bucket: "review" | "approve";
  review_reasons: string[];
  reason_titles: string[];
  required_approvals: number;
  approvals: number;
  days_since_invoice: number | null;
  document_type: string | null;
};

export type Queue = { counts: { review: number; approve: number }; items: QueueItem[] };

export type SpanRef = { start: number; end: number; text: string; line: number };

/** Where an extracted value came from. Offsets are computed by the server, never by the model. */
export type Evidence =
  | ({ status: "exact"; basis: string; also_at?: SpanRef[] } & SpanRef)
  | { status: "ambiguous"; basis: string; candidates: SpanRef[] }
  | { status: "not_found" };

export type Explanation = {
  code: string;
  title: string;
  detail: string;
  action: string;
  evidence: (SpanRef & { field: string })[];
};

export type LineItem = {
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
};

export type Invoice = InvoiceSummary & {
  raw_text: string;
  document_type: string | null;
  supplier_gstin: string | null;
  subtotal: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  round_off: number | null;
  bank_account: string | null;
  ifsc: string | null;
  po_number: string | null;
  notes: string | null;
  line_items: LineItem[];
  warnings: string[];
  review_reasons: string[];
  required_approvals: number;
  approvals: { user_id: string; note: string; created_at: string }[];
  evidence: Record<string, Evidence>;
  explanations: Explanation[];
};

export type DecisionResult = {
  id: number;
  status: string;
  approvals?: number;
  required_approvals?: number;
};

const orgHeaders = { "X-Org-Id": ORG_ID };

async function ok<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (HTTP ${response.status})`);
  }
  return response.json();
}

export async function getQueue(): Promise<Queue> {
  return ok(await fetch("/api/queue", { headers: orgHeaders }));
}

export async function getInvoice(id: number): Promise<Invoice> {
  return ok(await fetch(`/api/invoices/${id}`, { headers: orgHeaders }));
}

export async function uploadInvoice(file: File): Promise<Invoice> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/invoices", { method: "POST", headers: orgHeaders, body });
  if (!response.ok) throw new Error(`Couldn't process ${file.name} (HTTP ${response.status})`);
  return response.json();
}

async function decide(id: number, action: "approve" | "reject", user: string, note: string): Promise<DecisionResult> {
  const response = await fetch(`/api/invoices/${id}/${action}`, {
    method: "POST",
    headers: { ...orgHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: user, note }),
  });
  return ok(response);
}

export const approveInvoice = (id: number, user: string, note: string) => decide(id, "approve", user, note);
export const rejectInvoice = (id: number, user: string, note: string) => decide(id, "reject", user, note);
