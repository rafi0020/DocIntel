export function fmtMoney(v: number | null | undefined, currency?: string | null) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${currency} ${n}` : n;
}

export function fmtBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtMs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} m ${Math.round((ms % 60000) / 1000)} s`;
}

export function fmtAgo(iso: string | null) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function humanize(code: string) {
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "hybrid(openai_compatible:claude-haiku-4-5)" -> "Rules + AI · claude-haiku-4-5" */
export function extractorLabel(x: string | null | undefined) {
  if (!x) return "";
  if (x === "rules") return "Rules engine";
  if (x === "spreadsheet") return "Spreadsheet parser";
  const m = x.match(/^hybrid\((?:[^:)]*:)?(?:[^/)]*\/)?([^)]*)\)$/);
  return m ? `Rules + AI · ${m[1]}` : x;
}

export const STATUS_META: Record<string, { label: string; tone: "accent" | "ok" | "warn" | "err" | "muted" | "info" }> = {
  queued: { label: "Queued", tone: "muted" },
  processing: { label: "Processing", tone: "accent" },
  completed: { label: "Completed", tone: "ok" },
  needs_review: { label: "Needs review", tone: "warn" },
  failed: { label: "Failed", tone: "err" },
  auto_approved: { label: "Auto-approved", tone: "ok" },
  approved: { label: "Approved", tone: "ok" },
  corrected: { label: "Corrected", tone: "info" },
};

export const KIND_LABEL: Record<string, string> = {
  digital_pdf: "Digital PDF",
  scanned_pdf: "Scanned PDF",
  mixed_pdf: "Mixed PDF",
  image: "Image · OCR",
  spreadsheet: "Spreadsheet",
};
