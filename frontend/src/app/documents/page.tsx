"use client";

import clsx from "clsx";
import { ArrowRight, Layers, MoreHorizontal, RefreshCcw, RotateCw, Search, Trash2, Upload, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { ExportMenu } from "@/components/ExportMenu";
import { fileIcon } from "@/components/UploadZone";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Progress, Segmented, Skeleton, StatusBadge, useDismiss, useToast } from "@/components/ui";
import { api, fetcher, json, type DocSummary, type Stats } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtAgo, fmtBytes, fmtMs, humanize, KIND_LABEL } from "@/lib/format";

type Filter = "all" | "active" | "needs_review" | "completed" | "failed";
const FILTER_STATUS: Record<Filter, string> = { all: "", active: "queued,processing", needs_review: "needs_review", completed: "completed", failed: "failed" };

function RowMenu({ doc, onChange, onDelete, canDelete }: { doc: DocSummary; onChange: () => void; onDelete: () => void; canDelete: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  const toast = useToast();
  const busy = ["queued", "processing"].includes(doc.status);
  const reprocess = async () => {
    setOpen(false);
    try { await api(`/api/documents/${doc.id}/reprocess?force=true`, { method: "POST" }); toast("info", "Re-processing started"); onChange(); }
    catch (e) { toast("err", (e as Error).message); }
  };
  return (
    <div ref={ref} className="relative">
      <button aria-label={`More actions for ${doc.filename}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="btn grid size-8 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink">
        <MoreHorizontal className="size-4" />
      </button>
      {open && (
        <div role="menu" className="pop absolute right-0 z-20 mt-1 w-48 origin-top-right rounded-md border border-line bg-card p-1 shadow-[var(--shadow-pop)]">
          <button role="menuitem" className="flex w-full items-center gap-2 rounded-sm px-2.5 py-2 text-left text-sm hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40" disabled={busy} onClick={reprocess}>
            <RotateCw className="size-4 text-muted" /> Re-process
          </button>
          <button role="menuitem" disabled={!canDelete} title={canDelete ? undefined : "Only the uploader or an administrator can delete this"} className="flex w-full items-center gap-2 rounded-sm px-2.5 py-2 text-left text-sm text-err hover:bg-err-soft disabled:cursor-not-allowed disabled:opacity-40" onClick={() => { setOpen(false); onDelete(); }}>
            <Trash2 className="size-4" /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

export default function DocumentsPage() {
  const toast = useToast();
  const { user, can } = useAuth();
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [toDelete, setToDelete] = useState<DocSummary[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const qs = new URLSearchParams({ limit: "200", ...(FILTER_STATUS[filter] ? { status: FILTER_STATUS[filter] } : {}), ...(q ? { q } : {}) });
  const { data, mutate, isLoading } = useSWR<{ total: number; documents: DocSummary[] }>(`/api/documents?${qs}`, fetcher, {
    refreshInterval: (d) => (d?.documents.some((x) => x.status === "queued" || x.status === "processing") ? 1200 : 8000),
    keepPreviousData: true,
  });
  const { data: stats, mutate: mutStats } = useSWR<Stats>("/api/stats", fetcher, { refreshInterval: 4000 });
  const by = stats?.documents.by_status ?? {};
  const needsReview = stats?.records.by_review_status?.needs_review ?? 0;
  const docs = data?.documents ?? [];
  const mine = (d: DocSummary) => can("admin") || d.uploaded_by_id === user?.id;

  useEffect(() => { setPicked((p) => new Set([...p].filter((id) => docs.some((d) => d.id === id)))); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { mutate(); mutStats(); };
  const retryFailed = async () => {
    try {
      const r = await api<{ requeued: string[] }>("/api/documents/reprocess-failed", { method: "POST" });
      toast("ok", `${r.requeued.length} failed document${r.requeued.length === 1 ? "" : "s"} re-queued`);
      refresh();
    } catch (e) { toast("err", (e as Error).message); }
  };
  const bulk = async (action: "reprocess" | "delete", ids: string[]) => {
    try {
      const r = await api<{ done: string[]; skipped: { reason: string }[] }>("/api/documents/bulk", { method: "POST", ...json({ ids, action }) });
      toast(r.skipped.length ? "info" : "ok", `${r.done.length} ${action === "delete" ? "deleted" : "re-queued"}${r.skipped.length ? ` · ${r.skipped.length} skipped (${r.skipped[0].reason})` : ""}`);
      setPicked(new Set()); refresh();
    } catch (e) { toast("err", (e as Error).message); }
  };
  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    await bulk("delete", toDelete.map((d) => d.id));
    setDeleting(false); setToDelete(null);
  };
  const allPicked = docs.length > 0 && docs.every((d) => picked.has(d.id));
  const togglePick = (id: string) => setPicked((p) => { const n = new Set(p); if (!n.delete(id)) n.add(id); return n; });
  const selected = docs.filter((d) => picked.has(d.id));

  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle="Every uploaded file, its processing state and what needs a human."
        actions={<>
          <ExportMenu label="Export records" />
          {can("reviewer") && (by.failed ?? 0) > 0 && <Button icon={<RefreshCcw className="size-4" />} onClick={retryFailed}>Retry {by.failed} failed</Button>}
          {needsReview > 0 && <Link href="/review/" className="btn inline-flex h-9 items-center gap-2 rounded-md bg-card px-3.5 text-sm font-medium ring-1 ring-inset ring-line-strong hover:ring-ink/30">Review {needsReview} <ArrowRight className="size-4" /></Link>}
        </>}
      />
      <PageBody>
        <Card className="overflow-clip">
          {selected.length > 0 && can("reviewer") ? (
            <div className="enter flex flex-wrap items-center gap-3 border-b border-accent/30 bg-accent-soft px-4 py-2.5 text-sm">
              <button aria-label="Clear selection" onClick={() => setPicked(new Set())} className="btn grid size-7 place-items-center rounded-md text-accent hover:bg-card/60"><X className="size-4" /></button>
              <span className="font-medium text-accent">{selected.length} selected</span>
              <span className="ml-auto flex gap-2">
                <Button size="sm" icon={<RotateCw className="size-3.5" />} onClick={() => bulk("reprocess", selected.map((d) => d.id))}>Re-process</Button>
                <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} onClick={() => setToDelete(selected.filter(mine))} disabled={!selected.some(mine)}>Delete</Button>
              </span>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
              <Segmented label="Filter documents" value={filter} onChange={setFilter} options={[
                { value: "all", label: "All", count: stats?.documents.total },
                { value: "active", label: "In progress", count: (by.queued ?? 0) + (by.processing ?? 0) },
                { value: "needs_review", label: "Needs review", count: by.needs_review ?? 0 },
                { value: "completed", label: "Completed", count: by.completed ?? 0 },
                { value: "failed", label: "Failed", count: by.failed ?? 0 },
              ]} />
              <label className="relative w-full sm:w-64">
                <span className="sr-only">Filter by filename</span>
                <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-faint" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by filename" className="field pl-8" />
              </label>
            </div>
          )}
          <div className="overflow-x-auto xl:overflow-visible">
            <table className="th-sticky w-full text-sm">
              <thead>
                <tr className="text-left text-[12px] font-medium text-muted">
                  <th className="w-10 py-2.5 pl-4">{can("reviewer") && <input type="checkbox" aria-label="Select all" className="size-4 accent-[var(--color-accent)]" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(docs.map((d) => d.id)))} />}</th>
                  <th className="px-3 py-2.5 font-medium">File</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 text-right font-medium max-md:hidden">Records</th>
                  <th className="px-3 py-2.5 text-right font-medium max-md:hidden">Pages</th>
                  <th className="px-3 py-2.5 text-right font-medium max-md:hidden">Time</th>
                  <th className="px-3 py-2.5 font-medium max-md:hidden">Uploaded</th>
                  <th className="w-[100px] px-3 py-2.5 md:w-[140px]" />
                </tr>
              </thead>
              <tbody>
                {isLoading && !data && Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-line"><td colSpan={8} className="px-4 py-3"><Skeleton className="h-8" /></td></tr>
                ))}
                {docs.map((d) => {
                  const busy = d.status === "queued" || d.status === "processing";
                  const href = `/review?doc=${d.id}`;
                  return (
                    <tr key={d.id} className={clsx("group border-b border-line transition-colors last:border-0 hover:bg-bg", d.status === "failed" && "bg-err-soft/40", picked.has(d.id) && "bg-accent-soft/50")}>
                      <td className="w-10 py-3 pl-4">{can("reviewer") && <input type="checkbox" aria-label={`Select ${d.filename}`} className="size-4 accent-[var(--color-accent)]" checked={picked.has(d.id)} onChange={() => togglePick(d.id)} />}</td>
                      <td className="max-w-[190px] px-3 py-3 sm:max-w-[360px]">
                        <div className="flex items-center gap-3">
                          <span className="grid size-8 shrink-0 place-items-center rounded-md bg-surface">{fileIcon(d.file_type)}</span>
                          <div className="min-w-0">
                            {busy || d.status === "failed"
                              ? <p className="truncate font-medium">{d.filename}</p>
                              : <Link href={href} className="underline-draw block truncate font-medium hover:text-accent">{d.filename}</Link>}
                            <p className="truncate text-[12px] text-muted">
                              {d.source_kind ? KIND_LABEL[d.source_kind] ?? d.source_kind : d.file_type.toUpperCase()} · {fmtBytes(d.size_bytes)}
                              {d.attempts > 1 && ` · attempt ${d.attempts}`}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        {busy ? (
                          <div className="w-36 sm:w-44">
                            <div className="mb-1.5 flex items-center justify-between text-[12px]">
                              <StatusBadge status={d.status} />
                              <span className="font-mono text-muted tabular">{Math.round(d.progress * 100)}%</span>
                            </div>
                            <Progress value={d.progress} live />
                            <p className="mt-1 truncate text-[11.5px] text-muted">{humanize(d.stage ?? "queued")}</p>
                          </div>
                        ) : d.status === "failed" ? (
                          <div className="max-w-[170px] sm:max-w-[260px]">
                            <StatusBadge status="failed" />
                            <p className="mt-1 text-[12px] leading-snug text-err">{humanize(d.error_code ?? "error")}: <span className="text-ink-2">{d.error_message}</span></p>
                          </div>
                        ) : <StatusBadge status={d.status} />}
                      </td>
                      <td className="px-3 py-3 text-right tabular max-md:hidden">{busy ? "—" : d.invoice_count}</td>
                      <td className="px-3 py-3 text-right tabular max-md:hidden">{d.page_count ?? "—"}</td>
                      <td className="px-3 py-3 text-right text-muted tabular max-md:hidden">{fmtMs(d.processing_ms)}</td>
                      <td className="px-3 py-3 text-muted max-md:hidden"><span className="block">{fmtAgo(d.created_at)}</span>{d.uploaded_by && <span className="block max-w-[130px] truncate text-[12px] text-faint">{d.uploaded_by}</span>}</td>
                      <td className="px-3 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {d.status === "failed" && can("reviewer") ? (
                            <Button size="sm" icon={<RotateCw className="size-3.5" />} onClick={async () => {
                              try { await api(`/api/documents/${d.id}/reprocess`, { method: "POST" }); toast("info", "Re-processing started"); refresh(); }
                              catch (e) { toast("err", (e as Error).message); }
                            }}>Retry</Button>
                          ) : !busy && d.status !== "failed" ? (
                            <Link href={href} className="btn inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-accent hover:bg-accent-soft">
                              {d.status === "needs_review" ? "Review" : "Open"} <ArrowRight className="size-3.5" />
                            </Link>
                          ) : null}
                          {can("reviewer") && <RowMenu doc={d} onChange={refresh} canDelete={mine(d)} onDelete={() => setToDelete([d])} />}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {data && !docs.length && (
              <EmptyState icon={<Layers className="size-5" />} title={filter === "all" && !q ? "No documents yet" : "Nothing matches this filter"}>
                {filter === "all" && !q
                  ? <>Invoices, receipts, scans and spreadsheets are processed in the background.{can("reviewer") && <div className="mt-4"><Button variant="primary" icon={<Upload className="size-4" />} onClick={() => window.dispatchEvent(new Event("open-upload"))}>Upload documents</Button></div>}</>
                  : <Badge>{filter}</Badge>}
              </EmptyState>
            )}
          </div>
        </Card>
      </PageBody>
      <ConfirmDialog open={!!toDelete} title={toDelete && toDelete.length > 1 ? `Delete ${toDelete.length} documents?` : "Delete this document?"} confirmLabel="Delete" busy={deleting} onConfirm={confirmDelete} onCancel={() => setToDelete(null)}>
        {toDelete && toDelete.length === 1 ? <><span className="font-medium text-ink">{toDelete[0].filename}</span> and every record, issue and correction extracted from it will be removed.</> : "Every record, issue and correction extracted from these documents will be removed."} This cannot be undone.
      </ConfirmDialog>
    </div>
  );
}
