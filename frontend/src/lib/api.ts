export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type DocStatus = "queued" | "processing" | "completed" | "needs_review" | "failed";

export interface DocSummary {
  id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  status: DocStatus;
  stage: string | null;
  progress: number;
  source_kind: string | null;
  page_count: number | null;
  invoice_count: number;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  processing_ms: number | null;
  extractor: string | null;
  uploaded_by: string | null;
  uploaded_by_id: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface Source { page?: number; box?: [number, number, number, number]; sheet?: string; row?: number; col?: number }
export interface FieldValue {
  value: string | number | null;
  confidence: number;
  source: Source | null;
  method: string | null;
  note: string | null;
  candidate: string | number | null;
}
export interface LineItem { description: string | null; quantity: number | null; unit_price: number | null; amount: number | null; confidence?: number; source?: Source | null }
export interface Issue { id: number; code: string; severity: "error" | "warning" | "info"; field: string | null; message: string; details: Record<string, unknown>; resolved: boolean }
export interface CorrectionEntry { id: number; field: string; old_value: { value: unknown } | null; new_value: { value: unknown } | null; corrected_by: string; note: string | null; created_at: string | null }

export interface InvoiceSummary {
  id: string;
  document_id: string;
  position: number;
  record_kind: "document" | "ledger_row";
  page_start: number | null;
  page_end: number | null;
  sheet_name: string | null;
  row_index: number | null;
  invoice_number: string | null;
  invoice_date: string | null;
  supplier_name: string | null;
  customer_name: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  currency: string | null;
  confidence: number | null;
  review_status: string;
  needs_review: boolean;
  extractor: string | null;
  issue_counts: { error: number; warning: number; info: number };
}
export interface InvoiceFull extends InvoiceSummary {
  fields: Record<string, FieldValue>;
  line_items: LineItem[];
  issues: Issue[];
  corrections: CorrectionEntry[];
}
export interface PageMeta { page_no: number; label: string | null; method: string; ocr_confidence: number | null; width: number | null; height: number | null; error: string | null }
export interface DocEvent { id: number; attempt: number; stage: string; status: string; message: string | null; duration_ms: number | null; created_at: string | null }
export interface DocDetail extends DocSummary { pages: PageMeta[]; invoices: InvoiceSummary[]; events: DocEvent[] }
export interface PageData { page_no: number; label: string | null; method: string; ocr_confidence: number | null; text: string; layout: { words?: { t: string; b: number[]; c: number; l: number }[]; rows?: string[][] } | null; width: number | null; height: number | null; error: string | null }

export interface SearchResult {
  id: string; document_id: string; filename: string; file_type: string; record_kind: string;
  invoice_number: string | null; invoice_date: string | null; supplier_name: string | null; customer_name: string | null;
  total: number | null; currency: string | null; review_status: string; needs_review: boolean; confidence: number | null;
  page_start: number | null; sheet_name: string | null; row_index: number | null; score: number | null; snippet: string | null;
}
export interface SearchResponse { mode: string; total: number; results: SearchResult[]; took_ms?: number }

export interface Stats {
  documents: { total: number; by_status: Record<string, number> };
  records: { total: number; by_review_status: Record<string, number> };
  top_issues: { code: string; severity: string; count: number }[];
  performance: { source_kind: string; documents: number; avg_ms: number; p95_ms: number; pages: number }[];
  amounts_by_currency: { currency: string | null; invoices: number; total: number }[];
}
export interface Health { status: string; database: { ok: boolean }; queue: { mode: string; ok: boolean; queued?: number; workers?: number }; extraction: { llm_provider: string; llm_model: string | null; ocr_engine: string }; auth_required: boolean; signup_enabled?: boolean }

export interface FieldDiff { field: string; left: unknown; right: unknown; status: "match" | "mismatch" | "missing_left" | "missing_right"; difference?: number; hint?: string | null }
export interface ItemDiff { description: string | null; status: string; left: LineItem | null; right: LineItem | null; mismatched?: string[] }
export interface ComparePair { left_id: string; right_id: string; status: "match" | "mismatch"; fields: FieldDiff[]; line_items: ItemDiff[]; mismatch_count: number; matched_by: string; invoice_number: string | null }
export interface CompareResult {
  id: string;
  left: { id: string; filename: string; file_type: string; count?: number };
  right: { id: string; filename: string; file_type: string };
  summary: { left_records: number; right_records: number; matched: number; fully_consistent: number; with_mismatches: number; only_in_left: number; only_in_right: number; left_total_sum: number; right_total_sum: number; total_sum_difference: number };
  pairs: ComparePair[];
  only_left: { id: string; invoice_number: string | null; total: number | null; supplier_name: string | null }[];
  only_right: { id: string; invoice_number: string | null; total: number | null; supplier_name: string | null }[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Fired when the server says the session is gone; the shell listens and returns to the sign-in page. */
export const SESSION_EXPIRED = "docintel:session-expired";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the API is running.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg?: string }) => d.msg).join("; ") : JSON.stringify(j.detail ?? j);
    } catch { /* keep status text */ }
    if (res.status === 401 && !path.startsWith("/api/auth/login") && !path.startsWith("/api/auth/signup") && typeof window !== "undefined") {
      window.dispatchEvent(new Event(SESSION_EXPIRED));
    }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const json = (body: unknown): RequestInit => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const fetcher = <T,>(path: string) => api<T>(path);

/** Image / download URLs: the session cookie travels with them, no key in the URL. */
export function assetUrl(path: string) {
  return `${API_URL}${path}`;
}

/** Upload with real progress events (fetch has no upload progress). */
export function uploadFiles(files: File[], onProgress: (fraction: number) => void): Promise<{ documents: DocSummary[]; rejected: { filename: string; reason: string }[] }> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/documents`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        let msg = `Upload failed (${xhr.status})`;
        try { msg = JSON.parse(xhr.responseText).detail ?? msg; } catch { /* ignore */ }
        reject(new ApiError(xhr.status, msg));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error: is the API running?"));
    xhr.send(fd);
  });
}

export const FIELD_LABELS: Record<string, string> = {
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  supplier_name: "Supplier",
  customer_name: "Customer",
  subtotal: "Subtotal",
  tax: "Tax",
  total: "Total",
  currency: "Currency",
};
export const FIELD_ORDER = Object.keys(FIELD_LABELS);
export const AMOUNT_FIELDS = new Set(["subtotal", "tax", "total"]);

export type Role = "admin" | "reviewer" | "viewer";
export const ROLE_RANK: Record<Role, number> = { viewer: 0, reviewer: 1, admin: 2 };
export interface Me { id: string | null; email: string; name: string; role: Role; via: string }
export interface UserRow { id: string; email: string; name: string; role: Role; is_active: boolean; last_login_at: string | null; created_at: string | null }
export interface AuthConfig { allow_signup: boolean }
export interface AuditEvent { id: number; action: string; user: string | null; user_email: string | null; target_type: string | null; target_id: string | null; detail: Record<string, unknown> | null; created_at: string; ip?: string | null }

export interface Analytics {
  days: number;
  kpis: { documents: number; records: number; success_rate: number | null; clean_rate: number | null; avg_processing_ms: number | null; open_errors: number; needs_review: number };
  daily: { day: string; documents: number; failed: number; records: number }[];
  review_mix: Record<string, number>;
  document_status: Record<string, number>;
  source_kinds: Record<string, number>;
  spend: { currency: string; total: number; suppliers: { name: string; invoices: number; total: number }[] }[];
  issues: { code: string; severity: string; count: number }[];
  team: { user: string; uploads: number; approvals: number; corrections: number }[];
}

export interface ProviderPreset { id: string; base_url: string | null; model: string | null }
export interface ModelsConfig {
  source: "ui" | "env"; enabled: boolean; provider: string; model: string | null; base_url: string | null;
  key_set: boolean; key_hint: string | null; key_unreadable: boolean;
  timeout_s: number; max_retries: number; temperature: number; max_chars: number; concurrency: number; json_mode: boolean; ocr_engine: string;
  updated_by: string | null; updated_at: string | null; providers: ProviderPreset[];
}
export interface ModelsForm {
  enabled: boolean; provider: string; model: string; base_url: string; api_key: string; clear_key: boolean;
  timeout_s: number; max_retries: number; temperature: number; max_chars: number; concurrency: number; json_mode: boolean; ocr_engine: string;
}
export interface PingResult { ok: boolean | null; latency_ms?: number; model?: string; reply?: string; error?: string; message?: string; cached?: boolean }
export interface SystemStatus {
  database: { ok: boolean; error?: string };
  queue: { mode: string; ok: boolean; queued?: number; workers?: number; error?: string };
  extraction: { enabled: boolean; provider: string; model: string | null; ocr_engine: string; source: "ui" | "env" };
  last_24h: { processed: number; failed: number; avg_ms: number | null; p95_ms: number | null; pages: number; by_kind: { source_kind: string; documents: number; avg_ms: number }[] };
  recent_failures: { id: string; filename: string; error_code: string | null; error_message: string | null; at: string }[];
}
