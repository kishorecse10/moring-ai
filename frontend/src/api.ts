export const ORG_ID = "meridian";
export const CURRENT_USER = "kavya.iyer";

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

export type LineItem = {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number;
};

export type Invoice = InvoiceSummary & {
  raw_text: string;
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
};

export type DecisionResult = {
  id: number;
  status: string;
  approvals?: number;
  required_approvals?: number;
};

const orgHeaders = { "X-Org-Id": ORG_ID };

export async function listInvoices(): Promise<InvoiceSummary[]> {
  const response = await fetch("/api/invoices", { headers: orgHeaders });
  return response.json();
}

export async function getInvoice(id: number): Promise<Invoice> {
  const response = await fetch(`/api/invoices/${id}`);
  return response.json();
}

export async function uploadInvoice(file: File): Promise<Invoice> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/invoices", { method: "POST", headers: orgHeaders, body });
  if (!response.ok) throw new Error(`Couldn't process ${file.name} (HTTP ${response.status})`);
  return response.json();
}

async function decide(id: number, action: "approve" | "reject", note: string): Promise<DecisionResult> {
  const response = await fetch(`/api/invoices/${id}/${action}`, {
    method: "POST",
    headers: { ...orgHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: CURRENT_USER, note }),
  });
  return response.json();
}

export const approveInvoice = (id: number, note: string) => decide(id, "approve", note);
export const rejectInvoice = (id: number, note: string) => decide(id, "reject", note);
