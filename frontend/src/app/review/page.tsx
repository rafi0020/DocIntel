"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowRight, ChevronDown, ChevronLeft, ChevronRight, Download, FileWarning, ListChecks, RotateCw, SkipForward } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { fileIcon } from "@/components/UploadZone";
import { fieldHighlights, PageViewer, SheetViewer } from "@/components/review/PageViewer";
import { RecordPanel } from "@/components/review/RecordPanel";
import { Badge, Button, Card, EmptyState, Progress, Skeleton, StatusBadge, useDismiss, useToast } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api, assetUrl, fetcher, type DocDetail, type InvoiceFull, type SearchResponse } from "@/lib/api";
import { extractorLabel, fmtMoney, humanize, KIND_LABEL } from "@/lib/format";

function useQueue() {
  return useSWR<SearchResponse>("/api/search?needs_review=true&limit=200", fetcher, { refreshInterval: 6000 });
}

const PER_DOC = 6;

function Queue() {
  const { data, isLoading } = useQueue();
  const results = useMemo(() => data?.results ?? [], [data]);
  const byDoc = useMemo(() => {
    const m = new Map<string, typeof results>();
    results.forEach((r) => m.set(r.document_id, [...(m.get(r.document_id) ?? []), r]));
    return [...m.entries()];
  }, [results]);
  return (
    <div>
      <PageHeader title="Review queue" subtitle="Records that failed a check or that the system is not sure about. Approving or correcting one removes it from the queue."
        actions={results[0] && (
          <Link href={`/review?doc=${results[0].document_id}&rec=${results[0].id}`} className="btn inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3.5 text-sm font-medium text-on-accent shadow-sm hover:bg-accent-strong">
            Start reviewing <ArrowRight className="size-4" />
          </Link>
        )} />
      <PageBody>
        {isLoading && !data && <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div>}
        {data && !results.length && (
          <Card><EmptyState icon={<ListChecks className="size-5" />} title="Nothing to review">Every processed record passed validation or has been approved.</EmptyState></Card>
        )}
        <div className="space-y-4">
          {byDoc.map(([docId, recs]) => (
            <Card key={docId} className="overflow-clip">
              <div className="flex items-center gap-3 border-b border-line bg-bg px-4 py-2.5">
                {fileIcon(recs[0].file_type)}
                <span className="min-w-0 truncate text-sm font-medium">{recs[0].filename}</span>
                <Badge tone="warn" className="ml-auto shrink-0">{recs.length} to review</Badge>
              </div>
              <ul>
                {recs.slice(0, PER_DOC).map((r) => (
                  <li key={r.id}>
                    <Link href={`/review?doc=${r.document_id}&rec=${r.id}`} className="group grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto_1rem] items-center gap-x-4 border-b border-line px-4 py-2.5 text-sm last:border-0 hover:bg-accent-soft/40 max-sm:grid-cols-[minmax(0,1fr)_auto_1rem] max-sm:gap-y-0.5">
                      <span className="truncate font-mono text-[13px] max-sm:col-span-1">{r.invoice_number ?? <span className="text-err">no number</span>}</span>
                      <span className="truncate text-ink-2 max-sm:order-last max-sm:col-span-3 max-sm:text-[12.5px] max-sm:text-muted">{r.supplier_name ?? "Unknown supplier"}</span>
                      <span className="text-right font-mono text-[13px] tabular sm:min-w-32">{fmtMoney(r.total, r.currency)}</span>
                      <ArrowRight className="size-3.5 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                    </Link>
                  </li>
                ))}
              </ul>
              {recs.length > PER_DOC && (
                <Link href={`/review?doc=${docId}&rec=${recs[PER_DOC].id}`} className="flex items-center justify-between border-t border-line bg-bg px-4 py-2 text-[12.5px] font-medium text-accent hover:bg-accent-soft/40">
                  {recs.length - PER_DOC} more in this file <ArrowRight className="size-3.5" />
                </Link>
              )}
            </Card>
          ))}
        </div>
      </PageBody>
    </div>
  );
}

function Workspace({ docId, recId }: { docId: string; recId: string | null }) {
  const router = useRouter();
  const toast = useToast();
  const { can } = useAuth();
  const { data: doc, mutate: mutDoc, error } = useSWR<DocDetail>(`/api/documents/${docId}`, fetcher, {
    refreshInterval: (d) => (d && ["queued", "processing"].includes(d.status) ? 1000 : 0),
  });
  const records = useMemo(() => doc?.invoices ?? [], [doc]);
  const current = records.find((r) => r.id === recId) ?? records.find((r) => r.needs_review) ?? records[0];
  const { data: rec, mutate: mutRec } = useSWR<InvoiceFull>(current ? `/api/invoices/${current.id}` : null, fetcher);
  const { data: queue, mutate: mutQueue } = useQueue();
  const [page, setPage] = useState(1);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const closeMenu = useCallback(() => setMenu(false), []);
  useDismiss(menuRef, menu, closeMenu);
  const isSheet = doc?.source_kind === "spreadsheet";
  useEffect(() => { if (doc) document.title = `${doc.filename} · DocIntel`; }, [doc?.filename]); // eslint-disable-line react-hooks/exhaustive-deps

  // jump to the record's page/sheet when the record changes
  useEffect(() => {
    if (!rec || !doc) return;
    setActiveKey(null);
    if (rec.sheet_name) {
      const p = doc.pages.find((x) => x.label === rec.sheet_name);
      if (p) setPage(p.page_no);
    } else if (rec.page_start) setPage(rec.page_start);
  }, [rec?.id, doc?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // selecting a field jumps to the page it came from
  const pick = useCallback((key: string | null) => {
    setActiveKey(key);
    if (!key || !rec) return;
    const src = key.startsWith("item-") ? rec.line_items[+key.slice(5)]?.source : rec.fields[key]?.source;
    if (src?.page && src.page !== page) setPage(src.page);
    if (src?.sheet && doc) {
      const p = doc.pages.find((x) => x.label === src.sheet);
      if (p && p.page_no !== page) setPage(p.page_no);
    }
    if (!key.startsWith("item-")) document.getElementById(`f-${key}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [rec, page, doc]);

  const idx = current ? records.findIndex((r) => r.id === current.id) : -1;
  const goRec = useCallback((id: string) => router.replace(`/review?doc=${docId}&rec=${id}`, { scroll: false }), [router, docId]);
  const nextInQueue = useCallback(async () => {
    const q = await mutQueue();
    const nxt = (q?.results ?? []).find((r) => r.id !== current?.id);
    if (nxt) router.push(`/review?doc=${nxt.document_id}&rec=${nxt.id}`);
    else { toast("ok", "Review queue is empty"); router.push("/documents/"); }
  }, [mutQueue, current?.id, router, toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA"].includes(t.tagName) || e.ctrlKey || e.metaKey) return;
      if (e.key === "j" && idx < records.length - 1) goRec(records[idx + 1].id);
      if (e.key === "k" && idx > 0) goRec(records[idx - 1].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, records, goRec]);

  if (error) return <div className="p-8"><Card><EmptyState icon={<FileWarning className="size-5" />} title="Document not found">It may have been deleted. <Link className="text-accent" href="/documents/">Back to documents</Link></EmptyState></Card></div>;
  if (!doc) return <div className="grid grid-cols-1 h-[70dvh] gap-0 lg:h-[calc(100dvh-3.5rem)] lg:grid-cols-[1fr_470px]"><Skeleton className="m-4" /><Skeleton className="m-4 max-lg:hidden" /></div>;

  const highlights = rec ? fieldHighlights(rec.fields, rec.line_items) : [];
  const busy = ["queued", "processing"].includes(doc.status);

  return (
    <div className="flex flex-col lg:h-[calc(100dvh-3.5rem)]">
      {/* top bar */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-card px-4 py-2.5">
        <Link href="/documents/" aria-label="Back to documents" className="btn grid size-8 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink"><ChevronLeft className="size-4" /></Link>
        <span className="grid size-8 place-items-center rounded-md bg-surface">{fileIcon(doc.file_type)}</span>
        <div className="min-w-0 flex-1 basis-32 sm:flex-none">
          <p className="max-w-[340px] truncate text-sm font-semibold" title={doc.filename}>{doc.filename}</p>
          <p className="text-[12px] text-muted">{doc.source_kind ? KIND_LABEL[doc.source_kind] : doc.file_type.toUpperCase()} · {doc.page_count ?? "?"} {isSheet ? "sheet" : "page"}{doc.page_count === 1 ? "" : "s"} {doc.extractor !== "spreadsheet" && <span className="max-sm:hidden">· {extractorLabel(doc.extractor)}</span>}</p>
        </div>
        <StatusBadge status={doc.status} />

        {records.length > 1 && current && (
          <div ref={menuRef} className="relative ml-2 flex items-center gap-1">
            <button aria-label="Previous record" disabled={idx <= 0} onClick={() => goRec(records[idx - 1].id)} className="btn grid size-8 place-items-center rounded-md hover:bg-surface disabled:opacity-30"><ChevronLeft className="size-4" /></button>
            <button onClick={() => setMenu((m) => !m)} aria-expanded={menu} className="btn inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium ring-1 ring-inset ring-line-strong hover:ring-ink/30">
              Record <span className="font-mono tabular">{idx + 1}/{records.length}</span>
              <span className="text-muted">· {records.filter((r) => r.needs_review).length} to review</span>
              <ChevronDown className="size-3.5" />
            </button>
            <button aria-label="Next record" disabled={idx >= records.length - 1} onClick={() => goRec(records[idx + 1].id)} className="btn grid size-8 place-items-center rounded-md hover:bg-surface disabled:opacity-30"><ChevronRight className="size-4" /></button>
            {menu && (
              <>
                <div className="pop absolute left-0 top-10 z-40 max-h-[60vh] w-[min(420px,calc(100vw-2rem))] overflow-auto rounded-md border border-line bg-card p-1 shadow-[var(--shadow-pop)] scroll-thin">
                  {records.map((r, i) => (
                    <button key={r.id} onClick={() => { goRec(r.id); setMenu(false); }}
                      className={clsx("flex w-full items-center gap-3 rounded-sm px-2.5 py-2 text-left text-[13px] hover:bg-surface", r.id === current.id && "bg-accent-soft")}>
                      <span className="w-6 font-mono text-[11px] text-faint tabular">{i + 1}</span>
                      <span className={clsx("size-2 rounded-full", r.needs_review ? "bg-warn" : "bg-ok")} />
                      <span className="w-28 truncate font-mono">{r.invoice_number ?? "—"}</span>
                      <span className="min-w-0 flex-1 truncate text-ink-2">{r.supplier_name ?? ""}</span>
                      <span className="font-mono tabular">{fmtMoney(r.total)}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <a href={assetUrl(`/api/documents/${doc.id}/file`)} aria-label="Download original file" className="btn inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-ink-2 hover:bg-surface"><Download className="size-3.5" /> <span className="max-sm:sr-only">Original</span></a>
          {can("reviewer") && <Button size="sm" icon={<RotateCw className="size-3.5" />} disabled={busy} onClick={async () => {
            try { await api(`/api/documents/${doc.id}/reprocess?force=true`, { method: "POST" }); toast("info", "Re-processing started"); mutDoc(); }
            catch (e) { toast("err", (e as Error).message); }
          }}><span className="max-sm:sr-only">Re-process</span></Button>}
          <Button size="sm" variant="primary" icon={<SkipForward className="size-3.5" />} onClick={nextInQueue}>
            <span className="max-sm:hidden">Next in queue</span><span className="sm:hidden">Next</span> {queue && <span className="font-mono opacity-80 tabular">{queue.total}</span>}
          </Button>
        </div>
      </div>

      {busy ? (
        <div className="grid flex-1 place-items-center p-8">
          <Card className="w-full max-w-md p-6">
            <p className="mb-1 font-medium">Processing {doc.filename}</p>
            <p className="mb-4 text-sm text-muted">{humanize(doc.stage ?? "queued")}…</p>
            <Progress value={doc.progress} live />
          </Card>
        </div>
      ) : doc.status === "failed" ? (
        <div className="grid flex-1 place-items-center p-8">
          <Card className="w-full max-w-lg p-6">
            <div className="mb-3 flex items-center gap-2 text-err"><AlertTriangle className="size-5" /><p className="font-semibold">Processing failed: {humanize(doc.error_code ?? "error")}</p></div>
            <p className="mb-5 text-sm text-ink-2">{doc.error_message}</p>
            <Button variant="primary" icon={<RotateCw className="size-4" />} onClick={async () => {
              try { await api(`/api/documents/${doc.id}/reprocess`, { method: "POST" }); mutDoc(); } catch (e) { toast("err", (e as Error).message); }
            }}>Retry processing</Button>
          </Card>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="h-[68dvh] min-w-0 lg:h-auto lg:min-h-0 lg:flex-1">
            {isSheet ? (
              <SheetViewer docId={doc.id} pages={doc.pages} page={page} setPage={setPage} highlights={highlights} activeKey={activeKey} onPick={pick} recordRow={rec?.sheet_name && doc.pages.find((p) => p.page_no === page)?.label === rec.sheet_name ? rec.row_index : null} />
            ) : (
              <PageViewer docId={doc.id} pages={doc.pages} page={page} setPage={setPage} highlights={highlights} activeKey={activeKey} onPick={pick} />
            )}
          </div>
          <div className="w-full border-t border-line lg:min-h-0 lg:w-[470px] lg:shrink-0 lg:border-l lg:border-t-0">
            {rec ? (
              <RecordPanel rec={rec} events={doc.events} activeKey={activeKey} setActiveKey={pick}
                onSaved={(r) => { mutRec(r, { revalidate: false }); mutDoc(); mutQueue(); }}
                onNext={records.length > 1 && records.some((r) => r.needs_review && r.id !== rec.id)
                  ? () => { const n = records.find((r) => r.needs_review && r.id !== rec.id); if (n) goRec(n.id); }
                  : nextInQueue} />
            ) : records.length === 0 ? (
              <EmptyState icon={<FileWarning className="size-5" />} title="No invoice data found">The file was read, but no invoice fields were recognised.</EmptyState>
            ) : <div className="p-5"><Skeleton className="h-96" /></div>}
          </div>
        </div>
      )}
    </div>
  );
}

function ResolveRecord({ recId }: { recId: string }) {
  const router = useRouter();
  const { data } = useSWR<InvoiceFull>(`/api/invoices/${recId}`, fetcher);
  useEffect(() => { if (data) router.replace(`/review?doc=${data.document_id}&rec=${data.id}`); }, [data, router]);
  return <div className="p-8"><Skeleton className="h-40" /></div>;
}

function ReviewRouter() {
  const sp = useSearchParams();
  const doc = sp.get("doc");
  const rec = sp.get("rec");
  if (doc) return <Workspace docId={doc} recId={rec} />;
  if (rec) return <ResolveRecord recId={rec} />;
  return <Queue />;
}

export default function ReviewPage() {
  return <Suspense fallback={<div className="p-8"><Skeleton className="h-40" /></div>}><ReviewRouter /></Suspense>;
}
