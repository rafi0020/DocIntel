"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FileText, Layers, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { AreaChart, Donut, HBars } from "@/components/charts";
import { Badge, Panel, Segmented, Skeleton, Stat, StatGrid } from "@/components/ui";
import { fetcher, type Analytics, type AuditEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtAgo, fmtMoney, fmtMs, humanize } from "@/lib/format";

const RANGES = [{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }];

function sentence(e: AuditEvent) {
  const d = e.detail ?? {};
  const name = (d.filename ?? d.invoice_number) as string | undefined;
  switch (e.action) {
    case "document.upload": return <>uploaded <b className="font-medium text-ink">{name}</b></>;
    case "document.delete": return <>deleted <b className="font-medium text-ink">{name}</b></>;
    case "document.reprocess": return <>re-processed <b className="font-medium text-ink">{name}</b></>;
    case "document.reprocess_failed": return <>re-queued {String(d.count)} failed documents</>;
    case "invoice.approve": return <>approved invoice <b className="font-medium text-ink">{name ?? ""}</b></>;
    case "invoice.bulk_approve": return <>approved {String(d.count)} records</>;
    case "invoice.correct": return <>corrected invoice <b className="font-medium text-ink">{name ?? ""}</b></>;
    case "invoice.resolve_issue": return <>resolved an issue ({humanize(String(d.code))})</>;
    case "compare.run": return <>compared <b className="font-medium text-ink">{String(d.left)}</b> with <b className="font-medium text-ink">{String(d.right)}</b></>;
    default: return <>{humanize(e.action.replace(".", " "))}</>;
  }
}

export default function Dashboard() {
  const { user } = useAuth();
  const [days, setDays] = useState("30");
  const { data: a } = useSWR<Analytics>(`/api/analytics?days=${days}`, fetcher, { refreshInterval: 10000 });
  const { data: feed } = useSWR<{ events: AuditEvent[] }>("/api/activity?limit=8", fetcher, { refreshInterval: 10000 });
  const [cur, setCur] = useState(0);

  const series = useMemo(() => (a?.daily ?? []).map((d) => ({ label: new Date(d.day + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }), value: d.documents, extra: d.failed })), [a]);
  const mix = a?.review_mix ?? {};
  const clean = (mix.auto_approved ?? 0) + (mix.approved ?? 0) + (mix.corrected ?? 0);
  const first = user?.name ?? "";
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const issues = useMemo(() => {
    const m = new Map<string, { code: string; errors: number; warnings: number }>();
    (a?.issues ?? []).forEach((i) => { const r = m.get(i.code) ?? { code: i.code, errors: 0, warnings: 0 }; if (i.severity === "error") r.errors += i.count; else r.warnings += i.count; m.set(i.code, r); });
    return [...m.values()].sort((x, y) => y.errors + y.warnings - (x.errors + x.warnings));
  }, [a]);
  const spend = a?.spend[Math.min(cur, Math.max(0, (a?.spend.length ?? 1) - 1))];

  return (
    <div>
      <PageHeader title={`${hello}, ${first}`} docTitle="Dashboard" subtitle="Here is what is happening with your documents."
        actions={<Segmented label="Time range" value={days} onChange={setDays} options={RANGES} />} />
      <PageBody>
        {a && a.kpis.open_errors > 0 && (
          <Link href="/review/" className="lift enter flex items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm">
            <AlertTriangle className="size-4 shrink-0 text-warn" />
            <span className="min-w-0 flex-1"><b className="font-semibold">{a.kpis.needs_review} records need a human.</b> <span className="text-ink-2">{a.kpis.open_errors} open validation errors are waiting in the review queue.</span></span>
            <span className="hidden items-center gap-1 font-medium text-warn sm:flex">Start reviewing <ArrowRight className="size-4" /></span>
          </Link>
        )}

        {!a ? <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[92px]" />)}</div> : (
          <StatGrid>
            <Stat label="Documents" value={a.kpis.documents} sub={`${a.kpis.records} records extracted`} icon={<Layers className="size-4" />} />
            <Stat label="Success rate" value={a.kpis.success_rate == null ? "—" : `${a.kpis.success_rate}%`} sub="Documents processed without failure" tone="ok" icon={<CheckCircle2 className="size-4" />} />
            <Stat label="Clean pass rate" value={a.kpis.clean_rate == null ? "—" : `${a.kpis.clean_rate}%`} sub="Records approved or auto-approved" tone="ok" icon={<ShieldCheck className="size-4" />} />
            <Stat label="Need review" value={a.kpis.needs_review} sub={`${a.kpis.open_errors} open errors`} tone="warn" icon={<AlertTriangle className="size-4" />} />
            <Stat label="Avg. processing" value={a.kpis.avg_processing_ms ? fmtMs(a.kpis.avg_processing_ms) : "—"} sub="Per document, end to end" icon={<Clock3 className="size-4" />} />
          </StatGrid>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Panel title="Documents processed" description={`Per day, last ${days} days. Dashed line shows failures.`}>
              {a ? <AreaChart data={series} /> : <Skeleton className="h-[270px]" />}
            </Panel>
          </div>
          <Panel title="Review outcomes" description="What happened to every extracted record">
            {a ? <Donut center={a.kpis.clean_rate == null ? "—" : `${Math.round(a.kpis.clean_rate)}%`} sub="clean" slices={[
              { label: "Auto-approved", value: mix.auto_approved ?? 0, color: "var(--color-ok)" },
              { label: "Approved by a person", value: mix.approved ?? 0, color: "var(--color-accent)" },
              { label: "Corrected", value: mix.corrected ?? 0, color: "var(--color-info)" },
              { label: "Needs review", value: mix.needs_review ?? 0, color: "var(--color-warn)" },
            ]} /> : <Skeleton className="h-[168px]" />}
            {a && !clean && !mix.needs_review && <p className="mt-3 text-center text-sm text-muted">No records yet.</p>}
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Top suppliers by invoiced value" description="From invoice documents, by currency"
            action={a && a.spend.length > 1 ? <Segmented label="Currency" value={String(Math.min(cur, a.spend.length - 1))} onChange={(v) => setCur(+v)} options={a.spend.map((s, i) => ({ value: String(i), label: s.currency }))} /> : undefined}>
            {!a ? <Skeleton className="h-52" /> : spend ? (
              <>
                <p className="mb-4 text-[13px] text-muted">Total <span className="font-mono text-[15px] font-semibold text-ink tabular">{fmtMoney(spend.total, spend.currency)}</span></p>
                <HBars items={spend.suppliers.map((s) => ({ label: s.name, value: s.total, hint: `${s.invoices} invoice${s.invoices === 1 ? "" : "s"}` }))} format={(v) => fmtMoney(v)} />
              </>
            ) : <p className="py-10 text-center text-sm text-muted">Upload invoices to see supplier totals.</p>}
          </Panel>
          <Panel title="Open validation issues" description="Unresolved checks that failed" action={<Link href="/review/" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent underline-draw">Review queue <ArrowRight className="size-3.5" /></Link>}>
            {!a ? <Skeleton className="h-52" /> : <HBars tone="warn" empty="No open issues. Everything passed validation." items={issues.map((i) => ({ label: humanize(i.code), value: i.errors + i.warnings, hint: [i.errors && `${i.errors} blocking`, i.warnings && `${i.warnings} warning${i.warnings === 1 ? "" : "s"}`].filter(Boolean).join(" · ") }))} />}
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Team activity" description={`Last ${days} days`} flush>
            {!a ? <div className="p-5"><Skeleton className="h-40" /></div> : !a.team.length ? <p className="px-5 py-10 text-center text-sm text-muted">No activity yet.</p> : (
              <div className="overflow-x-auto scroll-thin"><table className="w-full min-w-[320px] text-[13px]">
                <thead><tr className="border-b border-line text-left text-[12px] text-muted"><th className="px-4 py-2 font-medium sm:px-5">Person</th><th className="px-2 py-2 text-right font-medium sm:px-3">Uploads</th><th className="px-2 py-2 text-right font-medium sm:px-3">Approvals</th><th className="px-4 py-2 text-right font-medium sm:px-5"><span className="max-sm:hidden">Corrections</span><span className="sm:hidden">Edits</span></th></tr></thead>
                <tbody>{a.team.map((t) => (
                  <tr key={`${t.user}-${t.uploads}-${t.approvals}`} className="border-b border-line last:border-0"><td className="px-4 py-2.5 font-medium sm:px-5">{t.user}</td>
                    <td className="px-2 py-2.5 text-right font-mono tabular sm:px-3">{t.uploads}</td><td className="px-2 py-2.5 text-right font-mono tabular sm:px-3">{t.approvals}</td><td className="px-4 py-2.5 text-right font-mono tabular sm:px-5">{t.corrections}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Panel>
          <Panel title="Recent activity" description="Across the whole team" flush>
            {!feed ? <div className="p-5"><Skeleton className="h-40" /></div> : !feed.events.length ? <p className="px-5 py-10 text-center text-sm text-muted">Nothing yet. Upload a document to get started.</p> : (
              <ul>{feed.events.map((e) => (
                <li key={e.id} className="flex items-start gap-3 border-b border-line px-5 py-2.5 text-[13px] last:border-0">
                  <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-surface text-muted"><FileText className="size-3" /></span>
                  <p className="min-w-0 flex-1 break-words text-ink-2 [overflow-wrap:anywhere] line-clamp-2"><b className="font-medium text-ink">{e.user ?? "Someone"}</b> {sentence(e)}</p>
                  <span className="shrink-0 text-[12px] text-faint">{fmtAgo(e.created_at)}</span>
                </li>
              ))}</ul>
            )}
          </Panel>
        </div>

        {a && Object.keys(a.source_kinds).length > 0 && (
          <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">Sources: {Object.entries(a.source_kinds).map(([k, v]) => <Badge key={k}>{humanize(k)} · {v}</Badge>)}</p>
        )}
      </PageBody>
    </div>
  );
}
