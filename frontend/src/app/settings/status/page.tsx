"use client";

import clsx from "clsx";
import { Activity, ArrowRight, CheckCircle2, Cpu, Database, FileWarning, Layers, ScanText, Server, XCircle, Zap } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Button, Card, EmptyState, Panel, Skeleton, Stat, StatGrid, useToast } from "@/components/ui";
import { api, fetcher, type PingResult, type SystemStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtAgo, fmtMs, humanize, KIND_LABEL } from "@/lib/format";

function Check({ ok, title, value, sub, icon: Icon }: { ok: boolean | "warn"; title: string; value: string; sub?: string; icon: typeof Server }) {
  const tone = ok === true ? "bg-ok" : ok === "warn" ? "bg-warn" : "bg-err";
  return (
    <Card className="flex items-start gap-3 p-4">
      <span className="grid size-9 shrink-0 place-items-center rounded-md bg-surface text-muted"><Icon className="size-4" /></span>
      <div className="min-w-0">
        <p className="flex items-center gap-2 whitespace-nowrap text-[12.5px] text-muted"><span className={clsx("size-2 shrink-0 rounded-full", tone)} />{title}</p>
        <p className="truncate text-[15px] font-semibold " title={value}>{value}</p>
        {sub && <p className="text-[12px] leading-snug text-faint">{sub}</p>}
      </div>
    </Card>
  );
}

export default function StatusPage() {
  const { can } = useAuth();
  const toast = useToast();
  const { data: s } = useSWR<SystemStatus>("/api/system/status", fetcher, { refreshInterval: 10000 });
  const [ping, setPing] = useState<PingResult | null>(null);
  const [busy, setBusy] = useState(false);
  async function runPing() {
    setBusy(true);
    try { setPing(await api<PingResult>("/api/system/ping-model", { method: "POST" })); } catch (e) { toast("err", (e as Error).message); } finally { setBusy(false); }
  }
  if (!s) return <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-56" /></div>;
  const w = s.queue.workers ?? 0;
  const inline = s.queue.mode === "inline";
  const model = s.extraction.enabled ? (s.extraction.model ?? "").split("/").pop() || s.extraction.provider : "Rule engine";
  const failRate = s.last_24h.processed ? Math.round((100 * s.last_24h.failed) / s.last_24h.processed) : 0;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Check ok={s.database.ok} title="Database" value={s.database.ok ? "Connected" : "Unreachable"} sub="PostgreSQL and pgvector" icon={Database} />
        <Check ok={s.queue.ok ? (w === 0 && !inline ? "warn" : true) : false} title="Workers" value={!s.queue.ok ? "Unreachable" : inline ? "Inline" : `${w} worker${w === 1 ? "" : "s"}`} sub={`${s.queue.queued ?? 0} queued`} icon={Server} />
        <Check ok title="Extractor" value={model.replace(/^./, (c) => c.toUpperCase())} sub={s.extraction.enabled ? `${s.extraction.provider} · ${s.extraction.source === "ui" ? "set in the app" : "from .env"}` : "No AI model configured"} icon={Cpu} />
        <Check ok title="OCR engine" value={s.extraction.ocr_engine.replace(/^./, (c) => c.toUpperCase())} sub="Scanned pages and photos" icon={ScanText} />
      </div>

      <Panel title="Model check" description="Send one tiny request to the active model to confirm it answers right now."
        action={can("reviewer") ? <Button size="sm" icon={<Zap className="size-3.5" />} loading={busy} onClick={runPing}>Ping model</Button> : undefined}>
        {!ping ? (
          <p className="text-[13px] text-muted">{can("reviewer") ? "Press Ping model to run a live check." : "Reviewers and administrators can run a live check."}{" "}
            {can("admin") && <Link href="/settings/models/" className="font-medium text-accent underline-draw">Change the model <ArrowRight className="inline size-3.5" /></Link>}</p>
        ) : ping.ok === null ? <p className="text-[13px] text-muted">{ping.message}</p> : (
          <div className={clsx("flex items-start gap-3 rounded-lg border px-4 py-3 text-sm", ping.ok ? "border-ok/30 bg-ok-soft" : "border-err/30 bg-err-soft")}>
            {ping.ok ? <CheckCircle2 className="mt-0.5 size-4 text-ok" /> : <XCircle className="mt-0.5 size-4 text-err" />}
            <div className="min-w-0">{ping.ok ? <><p className="font-medium">Answered in {ping.latency_ms} ms</p><p className="truncate text-[12.5px] text-ink-2">{ping.model}</p></> : <><p className="font-medium text-err">No answer</p><p className="break-words text-[12.5px] text-ink-2">{ping.error}</p></>}</div>
          </div>
        )}
      </Panel>

      <div>
        <h2 className="mb-3 text-[14px] font-semibold">Last 24 hours</h2>
        <StatGrid>
          <Stat label="Processed" value={s.last_24h.processed} sub={`${s.last_24h.pages} pages`} icon={<Layers className="size-4" />} />
          <Stat label="Failed" value={s.last_24h.failed} sub={s.last_24h.processed ? `${failRate}% of processed` : "None yet"} tone={s.last_24h.failed ? "err" : "ok"} icon={<FileWarning className="size-4" />} />
          <Stat label="Average time" value={s.last_24h.avg_ms ? fmtMs(s.last_24h.avg_ms) : "—"} sub="Per document" icon={<Activity className="size-4" />} />
          <Stat label="Slowest 5% (p95)" value={s.last_24h.p95_ms ? fmtMs(s.last_24h.p95_ms) : "—"} sub="Per document" icon={<Activity className="size-4" />} />
        </StatGrid>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="By document type" description="Average processing time, last 24 hours" flush>
          {!s.last_24h.by_kind.length ? <p className="px-5 py-8 text-center text-sm text-muted">Nothing processed in the last 24 hours.</p> : (
            <ul>{s.last_24h.by_kind.map((k) => <li key={k.source_kind} className="flex items-center justify-between border-b border-line px-5 py-2.5 text-[13px] last:border-0"><span>{KIND_LABEL[k.source_kind] ?? humanize(k.source_kind)}</span><span className="font-mono tabular text-muted">{k.documents} docs · {fmtMs(k.avg_ms)}</span></li>)}</ul>
          )}
        </Panel>
        <Panel title="Recent failures" description="Files that could not be read" flush>
          {!s.recent_failures.length ? <EmptyState icon={<CheckCircle2 className="size-5" />} title="No failures">Everything uploaded was processed.</EmptyState> : (
            <ul>{s.recent_failures.map((d) => (
              <li key={d.id}><Link href={`/review/?doc=${d.id}`} className="group flex items-start gap-3 border-b border-line px-5 py-2.5 text-[13px] last:border-0 hover:bg-bg">
                <FileWarning className="mt-0.5 size-4 shrink-0 text-err" /><span className="min-w-0 flex-1"><span className="block truncate font-medium">{d.filename}</span><span className="block truncate text-[12px] text-muted">{humanize(d.error_code ?? "error")}{d.error_message ? `: ${d.error_message}` : ""}</span></span>
                <span className="shrink-0 text-[12px] text-faint">{fmtAgo(d.at)}</span></Link></li>
            ))}</ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
