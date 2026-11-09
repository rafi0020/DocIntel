"use client";

import clsx from "clsx";
import { ArrowLeftRight, ArrowRight, CheckCircle2, ChevronDown, Lightbulb, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { PageBody, PageHeader } from "@/components/AppShell";
import { fileIcon } from "@/components/UploadZone";
import { Badge, Button, Card, EmptyState, Segmented, Stat, StatGrid, useToast } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api, fetcher, FIELD_LABELS, type CompareResult, type DocSummary } from "@/lib/api";
import { fmtAgo, fmtMoney, humanize } from "@/lib/format";

const ALL = "__all_invoices__";

function DocPicker({ label, value, onChange, docs, exclude, allowAll }: { label: string; value: string; onChange: (v: string) => void; docs: DocSummary[]; exclude?: string; allowAll?: boolean }) {
  const sel = docs.find((d) => d.id === value);
  const invoiceDocs = docs.filter((d) => d.source_kind !== "spreadsheet");
  return (
    <label className="block min-w-0 flex-1">
      <span className="mb-1.5 block text-[12.5px] font-medium text-muted">{label}</span>
      <span className="relative block">
        <span className="pointer-events-none absolute left-3 top-[9px]">{sel ? fileIcon(sel.file_type) : null}</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} className={clsx("field", sel && "pl-9")}>
          <option value="">Choose a processed document…</option>
          {allowAll && invoiceDocs.length > 1 && (
            <option value={ALL}>All invoice documents ({invoiceDocs.length} files, {invoiceDocs.reduce((s, d) => s + d.invoice_count, 0)} records)</option>
          )}
          {docs.filter((d) => d.id !== exclude).map((d) => (
            <option key={d.id} value={d.id}>{d.filename} · {d.invoice_count} record{d.invoice_count === 1 ? "" : "s"}</option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-[10px] size-4 text-muted" />
      </span>
    </label>
  );
}

function val(field: string, v: unknown) {
  if (v === null || v === undefined) return <span className="text-faint">missing</span>;
  if (["subtotal", "tax", "total"].includes(field)) return <span className="font-mono tabular">{fmtMoney(Number(v))}</span>;
  return String(v);
}

export default function ComparePage() {
  const toast = useToast();
  const { can } = useAuth();
  const { data } = useSWR<{ documents: DocSummary[] }>("/api/documents?limit=500&status=completed,needs_review", fetcher);
  const { data: history, mutate: mutHist } = useSWR<{ id: string; left_filename: string; right_filename: string; summary: CompareResult["summary"]; created_at: string; left_document_id: string; left_document_ids: string[]; right_document_id: string }[]>("/api/compare", fetcher);
  const docs = data?.documents ?? [];
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [res, setRes] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"issues" | "all">("issues");
  const [open, setOpen] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (res) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [res]);

  async function run(l: string | string[] = left, r = right) {
    if (!l || !r || (Array.isArray(l) && !l.length)) return;
    const ids = Array.isArray(l) ? l : l === ALL ? docs.filter((d) => d.source_kind !== "spreadsheet" && d.id !== r).map((d) => d.id) : [l];
    setBusy(true);
    try {
      const out = await api<CompareResult>("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ left_document_ids: ids, right_document_id: r }) });
      setRes(out); mutHist();
      setOpen(out.pairs.find((p) => p.status === "mismatch")?.left_id ?? null);
    } catch (e) { toast("err", (e as Error).message); } finally { setBusy(false); }
  }

  const pairs = useMemo(() => (res?.pairs ?? []).filter((p) => view === "all" || p.status === "mismatch"), [res, view]);
  const s = res?.summary;

  return (
    <div>
      <PageHeader title="Cross-verify" subtitle="Match invoices in one document against another, e.g. a batch of invoice PDFs against the accounts ledger in Excel, and see every difference field by field." />
      <PageBody>
        <Card className="p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end">
            <DocPicker label="Source: invoices received" value={left} onChange={setLeft} docs={docs} exclude={right} allowAll />
            <button aria-label="Swap documents" disabled={left === ALL} onClick={() => { setLeft(right); setRight(left); }} className="btn grid size-9 shrink-0 place-items-center self-center rounded-md bg-card text-muted ring-1 ring-inset ring-line-strong hover:text-accent disabled:cursor-not-allowed disabled:opacity-40 md:self-end">
              <ArrowLeftRight className="size-4" />
            </button>
            <DocPicker label="Reference: e.g. the ledger (XLSX / CSV) or another PDF" value={right} onChange={setRight} docs={docs} exclude={left} />
            <Button variant="primary" loading={busy} disabled={!left || !right || !can("reviewer")} title={can("reviewer") ? undefined : "Viewers cannot run comparisons"} onClick={() => run()}>Compare documents</Button>
          </div>
        </Card>

        {res && s && (
          <div ref={resultsRef} className="enter scroll-mt-4 space-y-4">
            <StatGrid>
              <Stat label="Matched" value={s.matched} sub={`of ${s.left_records} in source`} icon={<ArrowLeftRight className="size-4" />} />
              <Stat label="Fully consistent" value={s.fully_consistent} sub="Every field agrees" tone="ok" icon={<CheckCircle2 className="size-4" />} />
              <Stat label="With differences" value={s.with_mismatches} sub="Need a look" tone={s.with_mismatches ? "err" : "ok"} icon={<XCircle className="size-4" />} />
              <Stat label="Only in source" value={s.only_in_left} sub="Missing from reference" tone={s.only_in_left ? "warn" : "ok"} icon={<ArrowRight className="size-4" />} />
              <Stat label="Only in reference" value={s.only_in_right} sub="No matching document" tone={s.only_in_right ? "warn" : "ok"} icon={<ArrowRight className="size-4 rotate-180" />} />
            </StatGrid>
            <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm">
              <span className="text-muted">Sum of totals</span>
              <span>{res.left.filename}: <b className="font-mono tabular">{fmtMoney(s.left_total_sum)}</b></span>
              <span>{res.right.filename}: <b className="font-mono tabular">{fmtMoney(s.right_total_sum)}</b></span>
              <Badge tone={Math.abs(s.total_sum_difference) < 0.01 ? "ok" : "err"}>difference {fmtMoney(s.total_sum_difference)}</Badge>
              <Button size="sm" className="ml-auto" onClick={() => setRes(null)}>Back to recent comparisons</Button>
            </Card>

            <Card className="overflow-clip">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
                <h2 className="text-sm font-semibold">Matched invoices</h2>
                <Segmented label="Show" value={view} onChange={setView} options={[{ value: "issues", label: "Differences", count: s.with_mismatches }, { value: "all", label: "All", count: s.matched }]} />
              </div>
              {!pairs.length && <EmptyState icon={<CheckCircle2 className="size-5" />} title="No differences">Every matched invoice agrees field by field.</EmptyState>}
              <ul>
                {pairs.map((p) => {
                  const isOpen = open === p.left_id;
                  const bad = p.fields.filter((f) => f.status === "mismatch");
                  return (
                    <li key={p.left_id + p.right_id} className="border-b border-line last:border-0">
                      <button onClick={() => setOpen(isOpen ? null : p.left_id)} aria-expanded={isOpen} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-bg">
                        {p.status === "match" ? <CheckCircle2 className="size-4 text-ok" /> : <XCircle className="size-4 text-err" />}
                        <span className="w-40 truncate font-mono">{p.invoice_number ?? "—"}</span>
                        <span className="min-w-0 flex-1 truncate text-ink-2">
                          {p.status === "match" ? "All fields agree" : bad.map((f) => FIELD_LABELS[f.field] ?? f.field).join(", ") + (p.line_items.some((i) => i.status !== "match") ? ", line items" : "")}
                        </span>
                        <Badge tone="muted">{humanize(p.matched_by)}</Badge>
                        <ChevronDown className={clsx("size-4 text-muted transition-transform", isOpen && "rotate-180")} />
                      </button>
                      {isOpen && (
                        <div className="enter bg-bg px-4 pb-4">
                          <table className="w-full overflow-hidden rounded-md border border-line bg-card text-[13px]">
                            <thead className="bg-surface text-left text-[12px] text-muted">
                              <tr><th className="px-3 py-2 font-medium">Field</th><th className="px-3 py-2 font-medium">{res.left.filename}</th><th className="px-3 py-2 font-medium">{res.right.filename}</th><th className="px-3 py-2 font-medium">Result</th></tr>
                            </thead>
                            <tbody>
                              {p.fields.map((f) => (
                                <tr key={f.field} className={clsx("border-t border-line", f.status === "mismatch" && "bg-err-soft/50")}>
                                  <td className="px-3 py-2 font-medium">{FIELD_LABELS[f.field] ?? f.field}</td>
                                  <td className="px-3 py-2">{val(f.field, f.left)}</td>
                                  <td className="px-3 py-2">{val(f.field, f.right)}</td>
                                  <td className="px-3 py-2">
                                    {f.status === "match" ? <span className="text-ok">match</span> : f.status === "mismatch" ? (
                                      <span className="text-err">
                                        {f.difference !== undefined ? <>off by <span className="font-mono tabular">{fmtMoney(f.difference)}</span></> : "different"}
                                        {f.hint && <span className="mt-0.5 flex items-start gap-1 text-[12px] text-ink-2"><Lightbulb className="mt-px size-3.5 shrink-0 text-warn" />{f.hint}</span>}
                                      </span>
                                    ) : <span className="text-warn">{f.status === "missing_left" ? "missing in source" : "missing in reference"}</span>}
                                  </td>
                                </tr>
                              ))}
                              {p.line_items.filter((i) => i.status !== "match").map((i, k) => (
                                <tr key={`li${k}`} className="border-t border-line bg-err-soft/40">
                                  <td className="px-3 py-2 font-medium">Line · {i.description ?? "?"}</td>
                                  <td className="px-3 py-2 font-mono tabular">{i.left ? `${i.left.quantity ?? "?"} × ${i.left.unit_price ?? "?"} = ${i.left.amount ?? "?"}` : "—"}</td>
                                  <td className="px-3 py-2 font-mono tabular">{i.right ? `${i.right.quantity ?? "?"} × ${i.right.unit_price ?? "?"} = ${i.right.amount ?? "?"}` : "—"}</td>
                                  <td className="px-3 py-2 text-err">{humanize(i.status)}{i.mismatched?.length ? `: ${i.mismatched.join(", ")}` : ""}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div className="mt-2 flex gap-4 text-[12.5px]">
                            <Link className="font-medium text-accent underline-draw" href={`/review?rec=${p.left_id}`}>Open source record</Link>
                            <Link className="font-medium text-accent underline-draw" href={`/review?rec=${p.right_id}`}>Open reference record</Link>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>

            {(res.only_left.length > 0 || res.only_right.length > 0) && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {([["Only in source", res.only_left], ["Only in reference", res.only_right]] as const).map(([title, list]) => (
                  <Card key={title} className="overflow-clip">
                    <h3 className="border-b border-line px-4 py-2.5 text-sm font-semibold">{title} <span className="font-normal text-muted">({list.length})</span></h3>
                    <ul className="max-h-72 overflow-auto scroll-thin">
                      {list.map((x) => (
                        <li key={x.id}><Link href={`/review?rec=${x.id}`} className="flex items-center gap-3 border-b border-line px-4 py-2 text-[13px] last:border-0 hover:bg-bg">
                          <span className="w-36 truncate font-mono">{x.invoice_number ?? "no number"}</span>
                          <span className="min-w-0 flex-1 truncate text-ink-2">{x.supplier_name}</span>
                          <span className="font-mono tabular">{fmtMoney(x.total)}</span>
                          <ArrowRight className="size-3.5 text-faint" />
                        </Link></li>
                      ))}
                      {!list.length && <li className="px-4 py-3 text-[13px] text-muted">None</li>}
                    </ul>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {!res && (
          <Card className="overflow-clip">
            <h2 className="border-b border-line px-4 py-2.5 text-sm font-semibold">Recent comparisons</h2>
            {!history?.length ? (
              <EmptyState icon={<ArrowLeftRight className="size-5" />} title="No comparisons yet">Pick two processed documents above. Typical use: invoices received vs. what was entered in the ledger.</EmptyState>
            ) : (
              <ul>
                {history.map((h) => (
                  <li key={h.id}>
                    <button onClick={() => { const multi = h.left_document_ids.length > 1; setLeft(multi ? ALL : h.left_document_id); setRight(h.right_document_id); run(h.left_document_ids, h.right_document_id); }} className="flex w-full items-center gap-3 border-b border-line px-4 py-2.5 text-left text-[13px] last:border-0 hover:bg-bg">
                      <span className="min-w-0 flex-1 truncate">{h.left_filename} <span className="text-faint">↔</span> {h.right_filename}</span>
                      <Badge tone={h.summary.with_mismatches ? "err" : "ok"}>{h.summary.with_mismatches} with differences</Badge>
                      <span className="w-20 text-right text-muted">{fmtAgo(h.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </PageBody>
    </div>
  );
}
