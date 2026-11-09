"use client";

import clsx from "clsx";
import { ArrowRight, FileText, Search as SearchIcon, SlidersHorizontal, Table2, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { ExportMenu } from "@/components/ExportMenu";
import { Badge, Button, Card, Confidence, EmptyState, Segmented, Skeleton, StatusBadge } from "@/components/ui";
import { fetcher, type SearchResponse } from "@/lib/api";
import { fmtMoney, humanize } from "@/lib/format";

/** Document text is untrusted: render highlight markers as React nodes, never as HTML. */
function Snippet({ text }: { text: string }) {
  return <>{text.split(/(\u27e6[^\u27e7]*\u27e7)/).map((part, i) =>
    part.startsWith("\u27e6") ? <mark key={i}>{part.slice(1, -1)}</mark> : <span key={i}>{part}</span>)}</>;
}

type Mode = "hybrid" | "keyword" | "semantic";
const ISSUE_CODES = ["total_mismatch", "line_items_mismatch", "missing_field", "duplicate_invoice", "possible_duplicate", "ledger_mismatch", "unverified_value", "low_confidence", "extractor_disagreement"];
const PAGE = 25;
const MAX = 200; // API cap per request
const NO_FILTERS = { review_status: "", supplier: "", date_from: "", date_to: "", min_total: "", max_total: "", currency: "", issue_code: "", record_kind: "" };
const EXAMPLES = ["wheelchair rental", "physical therapy billed to Riverside", "INV-2026", "nursing agency invoices in BDT"];

function SearchInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [debounced, setDebounced] = useState(q);
  const [mode, setMode] = useState<Mode>((sp.get("mode") as Mode) ?? "hybrid");
  const [showFilters, setShowFilters] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const [f, setF] = useState(NO_FILTERS);

  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    const p = new URLSearchParams({ ...(debounced ? { q: debounced } : {}), ...(mode !== "hybrid" ? { mode } : {}) });
    router.replace(`/search${p.toString() ? `?${p}` : ""}`, { scroll: false });
  }, [debounced, mode, router]);

  const params = new URLSearchParams({ mode, limit: String(limit), ...(debounced ? { q: debounced } : {}) });
  Object.entries(f).forEach(([k, v]) => v && params.set(k, v));
  const { data, isLoading } = useSWR<SearchResponse>(`/api/search?${params}`, fetcher, { keepPreviousData: true });
  const setFilter = (v: typeof NO_FILTERS) => { setLimit(PAGE); setF(v); };
  const activeFilters = Object.values(f).filter(Boolean).length;
  const input = "field";
  // a new query or filter starts again from the first page
  const reset = <T,>(set: (v: T) => void) => (v: T) => { setLimit(PAGE); set(v); };

  return (
    <div>
      <PageHeader title="Search" subtitle="Find any processed invoice or ledger row by number, name, amount or plain-language description." actions={<ExportMenu label="Export filtered" params={Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&")} />} />
      <PageBody className="space-y-4">
        <Card className="p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <label className="relative flex-1">
              <span className="sr-only">Search query</span>
              <SearchIcon className="pointer-events-none absolute left-3 top-3 size-4 text-faint" />
              <input autoFocus value={q} onChange={(e) => { setLimit(PAGE); setQ(e.target.value); }} placeholder="Try “hospital bed rental over 500” or an invoice number"
                className="field h-10 pl-9 pr-9 text-[15px]" />
              {q && <button aria-label="Clear search" onClick={() => setQ("")} className="absolute right-2 top-2 grid size-6 place-items-center rounded-sm text-muted hover:bg-surface"><X className="size-4" /></button>}
            </label>
            <Segmented label="Search mode" value={mode} onChange={reset(setMode)} options={[{ value: "hybrid", label: "Hybrid" }, { value: "keyword", label: "Keyword" }, { value: "semantic", label: "Semantic" }]} />
            <button onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters}
              className={clsx("btn inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium ring-1 ring-inset", showFilters || activeFilters ? "bg-accent-soft text-accent ring-accent/30" : "ring-line-strong hover:ring-ink/30")}>
              <SlidersHorizontal className="size-4" /> Filters{activeFilters ? ` · ${activeFilters}` : ""}
            </button>
          </div>
          <p className="mt-2 text-[12px] text-muted">
            {mode === "hybrid" && "Hybrid ranks exact keyword hits and meaning-based matches together."}
            {mode === "keyword" && "Keyword uses PostgreSQL full-text search plus partial matches on numbers and names."}
            {mode === "semantic" && "Semantic finds records by meaning using local text embeddings, even without shared words."}
            {!q && <> Examples: {EXAMPLES.map((e, i) => <button key={e} onClick={() => setQ(e)} className="text-accent underline-draw">{e}{i < EXAMPLES.length - 1 ? "," : ""} </button>)}</>}
          </p>
          {showFilters && (
            <div className="enter mt-4 grid grid-cols-1 gap-3 border-t border-line pt-4 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-[12.5px] text-muted">Review status
                <select className={clsx(input, "mt-1")} value={f.review_status} onChange={(e) => setFilter({ ...f, review_status: e.target.value })}>
                  <option value="">Any</option><option value="needs_review">Needs review</option><option value="auto_approved">Auto-approved</option><option value="approved">Approved</option><option value="corrected">Corrected</option>
                </select>
              </label>
              <label className="text-[12.5px] text-muted">Has issue
                <select className={clsx(input, "mt-1")} value={f.issue_code} onChange={(e) => setFilter({ ...f, issue_code: e.target.value })}>
                  <option value="">Any</option>{ISSUE_CODES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
                </select>
              </label>
              <label className="text-[12.5px] text-muted">Source
                <select className={clsx(input, "mt-1")} value={f.record_kind} onChange={(e) => setFilter({ ...f, record_kind: e.target.value })}>
                  <option value="">Documents and ledgers</option><option value="document">Invoice documents</option><option value="ledger_row">Ledger rows</option>
                </select>
              </label>
              <label className="text-[12.5px] text-muted">Supplier contains
                <input className={clsx(input, "mt-1")} value={f.supplier} onChange={(e) => setFilter({ ...f, supplier: e.target.value })} />
              </label>
              <label className="text-[12.5px] text-muted">Date from<input type="date" className={clsx(input, "mt-1")} value={f.date_from} onChange={(e) => setFilter({ ...f, date_from: e.target.value })} /></label>
              <label className="text-[12.5px] text-muted">Date to<input type="date" className={clsx(input, "mt-1")} value={f.date_to} onChange={(e) => setFilter({ ...f, date_to: e.target.value })} /></label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[12.5px] text-muted">Min total<input inputMode="decimal" className={clsx(input, "mt-1 font-mono")} value={f.min_total} onChange={(e) => setFilter({ ...f, min_total: e.target.value })} /></label>
                <label className="text-[12.5px] text-muted">Max total<input inputMode="decimal" className={clsx(input, "mt-1 font-mono")} value={f.max_total} onChange={(e) => setFilter({ ...f, max_total: e.target.value })} /></label>
              </div>
              <label className="text-[12.5px] text-muted">Currency
                <select className={clsx(input, "mt-1")} value={f.currency} onChange={(e) => setFilter({ ...f, currency: e.target.value })}>
                  <option value="">Any</option>{["USD", "BDT", "EUR", "GBP"].map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
            </div>
          )}
        </Card>

        <div className="flex items-center justify-between text-[13px] text-muted">
          <span aria-live="polite">{data ? `${data.results.length < data.total ? `Showing ${data.results.length} of ${data.total}` : data.total} result${data.total === 1 ? "" : "s"}` : "Searching…"}{data?.took_ms !== undefined && ` · ${data.took_ms} ms`}{data?.mode === "browse" && " · most recent first"}</span>
          {activeFilters > 0 && <button onClick={() => { setLimit(PAGE); setF(NO_FILTERS); }} className="text-accent underline-draw">Clear filters</button>}
        </div>

        <Card className={clsx("overflow-clip transition-opacity", isLoading && data && "opacity-60")}>
          {!data && <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>}
          {data && !data.results.length && <EmptyState icon={<SearchIcon className="size-5" />} title="No matching records">Try another mode or fewer filters.</EmptyState>}
          <ul>
            {data?.results.map((r) => (
              <li key={r.id}>
                <Link href={`/review?doc=${r.document_id}&rec=${r.id}`} className="group flex items-start gap-4 border-b border-line px-4 py-3.5 last:border-0 hover:bg-bg">
                  <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-surface text-muted group-hover:bg-accent-soft group-hover:text-accent">
                    {r.record_kind === "ledger_row" ? <Table2 className="size-4" /> : <FileText className="size-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-mono text-[14px] font-medium">{r.invoice_number ?? "No number"}</span>
                      <span className="truncate text-sm text-ink-2">{r.supplier_name ?? "Unknown supplier"}</span>
                      <StatusBadge status={r.review_status} />
                      {r.record_kind === "ledger_row" && <Badge tone="info">ledger row {r.row_index}</Badge>}
                    </div>
                    <p className="mt-0.5 truncate text-[12.5px] text-muted">
                      {r.filename}{r.page_start ? ` · page ${r.page_start}` : ""} · to {r.customer_name ?? "unknown"} · {r.invoice_date ?? "no date"}
                    </p>
                    {r.snippet && <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-2"><Snippet text={r.snippet} /></p>}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <span className="font-mono text-[14px] font-semibold tabular">{fmtMoney(r.total, r.currency)}</span>
                    <Confidence value={r.confidence} compact />
                  </div>
                  <ArrowRight className="mt-2 size-4 shrink-0 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                </Link>
              </li>
            ))}
          </ul>
          {data && data.results.length < data.total && limit < MAX && (
            <div className="flex items-center justify-between gap-3 border-t border-line bg-bg px-4 py-3 text-[13px] text-muted">
              <span>{data.results.length} of {data.total} shown</span>
              <Button size="sm" loading={isLoading} onClick={() => setLimit((l) => Math.min(MAX, l + PAGE))}>Show {Math.min(PAGE, data.total - data.results.length)} more</Button>
            </div>
          )}
        </Card>
      </PageBody>
    </div>
  );
}

export default function SearchPage() {
  return <Suspense><SearchInner /></Suspense>;
}
