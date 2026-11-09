"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { Badge, Button, Card, EmptyState, Skeleton } from "@/components/ui";
import { fetcher, type AuditEvent } from "@/lib/api";
import { humanize } from "@/lib/format";

const GROUPS = [
  { value: "", label: "All events" }, { value: "auth", label: "Sign-ins" }, { value: "document", label: "Documents" },
  { value: "invoice", label: "Records" }, { value: "user", label: "User admin" }, { value: "compare", label: "Cross-verify" }, { value: "export", label: "Exports" },
];
const TONE = (a: string) => (a.includes("failed") || a.includes("delete") ? "err" : a.startsWith("auth") ? "info" : a.startsWith("user") ? "warn" : a.includes("approve") ? "ok" : "muted") as "err" | "info" | "warn" | "ok" | "muted";

function detailText(e: AuditEvent) {
  const d = e.detail ?? {};
  const parts = [d.filename, d.invoice_number, d.email, d.reason, d.format && `${d.format} · ${d.rows} rows`, d.count && `${d.count} items`, d.left && `${d.left} ↔ ${d.right}`, d.code].filter(Boolean);
  return parts.map(String).join(" · ") || (e.target_id ? e.target_id.slice(0, 8) : "");
}

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [who, setWho] = useState("");
  const [debounced, setDebounced] = useState("");
  const [days, setDays] = useState("30");
  const [limit, setLimit] = useState(50);
  useEffect(() => { const t = setTimeout(() => setDebounced(who), 250); return () => clearTimeout(t); }, [who]);
  const qs = new URLSearchParams({ days, limit: String(limit), ...(action ? { action } : {}), ...(debounced ? { user: debounced } : {}) });
  const { data, isLoading } = useSWR<{ total: number; events: AuditEvent[] }>(`/api/audit?${qs}`, fetcher, { keepPreviousData: true, refreshInterval: 15000 });
  return (
    <div>
      <PageHeader title="Audit log" subtitle="Who did what, and when. Sign-ins, uploads, corrections, approvals and administrative changes are recorded automatically." />
      <PageBody>
        <Card className="overflow-clip">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <select aria-label="Event type" className="field w-44" value={action} onChange={(e) => { setLimit(50); setAction(e.target.value); }}>{GROUPS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}</select>
            <select aria-label="Time range" className="field w-36" value={days} onChange={(e) => setDays(e.target.value)}>{["1", "7", "30", "90", "365"].map((d) => <option key={d} value={d}>{d === "1" ? "Last 24 hours" : `Last ${d} days`}</option>)}</select>
            <label className="relative min-w-[200px] flex-1 sm:max-w-xs"><span className="sr-only">Filter by user e-mail</span><Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-faint" /><input className="field pl-8" placeholder="Filter by user e-mail" value={who} onChange={(e) => { setLimit(50); setWho(e.target.value); }} /></label>
            <span className="ml-auto text-[13px] text-muted">{data ? `${data.total} event${data.total === 1 ? "" : "s"}` : ""}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="th-sticky w-full min-w-[820px] text-sm">
              <thead><tr className="text-left text-[12px] text-muted"><th className="px-4 py-2.5 font-medium">Time</th><th className="px-3 py-2.5 font-medium">User</th><th className="px-3 py-2.5 font-medium">Event</th><th className="px-3 py-2.5 font-medium">Details</th><th className="px-4 py-2.5 font-medium">IP</th></tr></thead>
              <tbody>
                {isLoading && !data && Array.from({ length: 6 }).map((_, i) => <tr key={i} className="border-b border-line"><td colSpan={5} className="px-4 py-3"><Skeleton className="h-6" /></td></tr>)}
                {data?.events.map((e) => (
                  <tr key={e.id} className="border-b border-line last:border-0 hover:bg-bg">
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[12px] text-muted tabular">{new Date(e.created_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                    <td className="px-3 py-2.5"><span className="block max-w-[200px] truncate font-medium">{e.user ?? "Unknown"}</span>{e.user_email && e.user_email !== e.user && <span className="block max-w-[200px] truncate text-[12px] text-muted">{e.user_email}</span>}</td>
                    <td className="px-3 py-2.5"><Badge tone={TONE(e.action)}>{humanize(e.action.replace(".", " · ").replace(/_/g, " "))}</Badge></td>
                    <td className="max-w-[360px] truncate px-3 py-2.5 text-ink-2" title={detailText(e)}>{detailText(e)}</td>
                    <td className="px-4 py-2.5 font-mono text-[12px] text-muted">{e.ip ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && !data.events.length && <EmptyState icon={<Search className="size-5" />} title="No events match">Try a wider time range or another event type.</EmptyState>}
          </div>
          {data && data.events.length < data.total && limit < 500 && <div className="flex justify-center border-t border-line bg-bg px-4 py-3"><Button size="sm" onClick={() => setLimit((l) => Math.min(500, l + 50))}>Load more</Button></div>}
        </Card>
      </PageBody>
    </div>
  );
}
