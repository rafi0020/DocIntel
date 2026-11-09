"use client";

import clsx from "clsx";
import { AlertCircle, AlertTriangle, Check, CheckCheck, Copy, Crosshair, History, Info, Plus, Sparkles, Trash2, Undo2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AMOUNT_FIELDS, api, FIELD_LABELS, FIELD_ORDER, type DocEvent, type InvoiceFull, type Issue, type LineItem } from "@/lib/api";
import { fmtAgo, fmtMoney, fmtMs, humanize } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Confidence, Kbd, StatusBadge, useToast } from "../ui";

type Tab = "data" | "issues" | "history" | "json";

const METHOD_LABEL: Record<string, string> = { "llm+rules": "AI + rules agree", llm: "AI", rules: "Rules", ledger: "Spreadsheet cell", manual: "Corrected" };

function sevIcon(sev: string, cls = "size-4") {
  if (sev === "error") return <AlertCircle className={clsx(cls, "text-err")} />;
  if (sev === "warning") return <AlertTriangle className={clsx(cls, "text-warn")} />;
  return <Info className={clsx(cls, "text-info")} />;
}

function toStr(v: unknown) {
  return v === null || v === undefined ? "" : String(v);
}

export function RecordPanel({ rec, events, activeKey, setActiveKey, onSaved, onNext }: {
  rec: InvoiceFull; events: DocEvent[]; activeKey: string | null; setActiveKey: (k: string | null) => void;
  onSaved: (r: InvoiceFull) => void; onNext?: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const readOnly = !can("reviewer");
  const [tab, setTab] = useState<Tab>("data");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [items, setItems] = useState<LineItem[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);

  useEffect(() => { setDraft({}); setItems(null); }, [rec.id]);

  const dirtyFields = Object.keys(draft).filter((k) => draft[k] !== toStr(rec.fields[k]?.value));
  const dirty = dirtyFields.length > 0 || items !== null;
  const openIssues = rec.issues.filter((i) => !i.resolved && i.severity !== "info");
  const byField = useMemo(() => {
    const m: Record<string, Issue[]> = {};
    rec.issues.filter((i) => !i.resolved).forEach((i) => { (m[i.field ?? "_"] ||= []).push(i); });
    return m;
  }, [rec.issues]);

  async function save() {
    setSaving(true);
    try {
      const fields: Record<string, string | null> = {};
      dirtyFields.forEach((k) => (fields[k] = draft[k].trim() === "" ? null : draft[k]));
      const r = await api<InvoiceFull>(`/api/invoices/${rec.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields, line_items: items ?? undefined, reviewer: "reviewer" }),
      });
      onSaved(r);
      setDraft({}); setItems(null);
      const errs = r.issues.filter((i) => !i.resolved && i.severity === "error").length;
      toast(errs ? "info" : "ok", errs ? `Saved · ${errs} error${errs > 1 ? "s" : ""} still open` : "Saved · all checks pass");
    } catch (e) { toast("err", (e as Error).message); } finally { setSaving(false); }
  }

  async function approve() {
    setApproving(true);
    try {
      const r = await api<InvoiceFull>(`/api/invoices/${rec.id}/approve`, { method: "POST" });
      onSaved(r);
      toast("ok", "Record approved");
      onNext?.();
    } catch (e) { toast("err", (e as Error).message); } finally { setApproving(false); }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (readOnly) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); if (dirty) save(); }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (!dirty) approve(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const json = useMemo(() => {
    const o: Record<string, unknown> = {};
    FIELD_ORDER.forEach((k) => (o[k] = rec.fields[k]?.value ?? null));
    o.line_items = rec.line_items.map(({ description, quantity, unit_price, amount }) => ({ description, quantity, unit_price, amount }));
    o.validation = { needs_review: rec.needs_review, issues: rec.issues.filter((i) => !i.resolved).map((i) => ({ code: i.code, severity: i.severity, field: i.field, message: i.message })) };
    return JSON.stringify(o, null, 2);
  }, [rec]);

  const itemList = items ?? rec.line_items;
  const itemsSum = itemList.reduce((s, i) => s + (Number(i.amount) || 0), 0);
  const subtotal = Number(draft.subtotal ?? rec.subtotal ?? NaN);

  return (
    <div className="flex min-h-0 flex-col bg-card lg:h-full">
      {/* record header */}
      <div className="border-b border-line px-5 pb-3 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[12px] text-muted">{rec.record_kind === "ledger_row" ? `Ledger row ${rec.row_index} · ${rec.sheet_name}` : `Invoice record · page ${rec.page_start}${rec.page_end && rec.page_end !== rec.page_start ? `–${rec.page_end}` : ""}`}</p>
            <h2 className="truncate text-[17px] font-semibold tracking-tight">{rec.invoice_number ?? "No invoice number"}</h2>
            <p className="truncate text-[13px] text-ink-2">{rec.supplier_name ?? "Unknown supplier"} → {rec.customer_name ?? "unknown customer"}</p>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <StatusBadge status={rec.review_status} />
            <span className="text-[15px] font-semibold tabular">{fmtMoney(rec.total, rec.currency)}</span>
          </div>
        </div>
        <div className="mt-3 flex gap-1" role="tablist" aria-label="Record views">
          {([
            ["data", "Extracted data"],
            ["issues", `Issues${openIssues.length ? ` · ${openIssues.length}` : ""}`],
            ["history", "History"],
            ["json", "JSON"],
          ] as [Tab, string][]).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={clsx("btn h-8 rounded-md px-3 text-[13px] font-medium", tab === k ? "bg-ink text-bg" : "text-muted hover:bg-surface hover:text-ink")}>{l}</button>
          ))}
        </div>
      </div>

      <div className="pane min-h-0 flex-1 scroll-thin">
        {tab === "data" && (
          <div className="space-y-5 px-5 py-4">
            {openIssues.filter((i) => i.severity === "error").length > 0 && (
              <div className="rounded-md border border-err/25 bg-err-soft/60 p-3">
                <p className="mb-1.5 text-[12.5px] font-semibold text-err">Must be fixed before approval</p>
                <ul className="space-y-1">
                  {openIssues.filter((i) => i.severity === "error").map((i) => (
                    <li key={i.id}>
                      <button onClick={() => i.field && i.field !== "line_items" ? setActiveKey(i.field) : setTab("issues")} className="flex w-full gap-2 text-left text-[13px] text-ink-2 hover:text-ink">
                        {sevIcon("error", "size-3.5 mt-0.5 shrink-0")} <span>{i.message}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="space-y-1">
              {FIELD_ORDER.map((k) => {
                const f = rec.fields[k] ?? { value: null, confidence: 0, source: null, method: null, note: null, candidate: null };
                const val = draft[k] ?? toStr(f.value);
                const edited = draft[k] !== undefined && draft[k] !== toStr(f.value);
                const issues = (byField[k] ?? []).filter((i) => i.severity !== "info");
                const isActive = activeKey === k;
                return (
                  <div key={k} className={clsx("rounded-md border px-3 py-2 transition-colors", isActive ? "border-accent bg-accent-soft/40" : "border-transparent hover:bg-bg")}>
                    <div className="mb-1 flex items-center gap-2">
                      <label htmlFor={`f-${k}`} className="text-[12.5px] font-medium text-ink-2">{FIELD_LABELS[k]}</label>
                      {f.method && <span className="text-[11px] text-faint">{METHOD_LABEL[f.method] ?? f.method}</span>}
                      {edited && <Badge tone="accent">edited</Badge>}
                      <span className="ml-auto flex items-center gap-1">
                        {f.value !== null && <Confidence value={f.method === "manual" ? 1 : f.confidence} compact />}
                        <button aria-label={`Show ${FIELD_LABELS[k]} on the page`} disabled={!f.source} onClick={() => setActiveKey(isActive ? null : k)}
                          className={clsx("btn grid size-7 place-items-center rounded-sm disabled:opacity-25", isActive ? "text-accent" : "text-muted hover:bg-surface hover:text-ink")}>
                          <Crosshair className="size-3.5" />
                        </button>
                      </span>
                    </div>
                    <input
                      id={`f-${k}`}
                      readOnly={readOnly}
                      value={val}
                      onFocus={() => f.source && setActiveKey(k)}
                      onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
                      placeholder={f.value === null ? "Not found in the document" : undefined}
                      inputMode={AMOUNT_FIELDS.has(k) ? "decimal" : undefined}
                      className={clsx("h-9 w-full rounded-md border bg-card px-2.5 text-[14px] outline-none transition-colors placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/15",
                        AMOUNT_FIELDS.has(k) && "font-mono tabular",
                        edited ? "border-accent" : issues.some((i) => i.severity === "error") ? "border-err/50" : issues.length ? "border-warn/50" : "border-line-strong")}
                    />
                    {f.value === null && f.candidate !== null && f.candidate !== undefined && draft[k] === undefined && (
                      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-warn">
                        <Sparkles className="size-3.5" /> Proposed “{String(f.candidate)}” but it is not on the page, so it was not used.
                        <button className="font-medium text-accent underline-draw" onClick={() => setDraft((d) => ({ ...d, [k]: String(f.candidate) }))}>Use it anyway</button>
                      </p>
                    )}
                    {issues.map((i) => (
                      <p key={i.id} className={clsx("mt-1.5 flex gap-1.5 text-[12px] leading-snug", i.severity === "error" ? "text-err" : "text-warn")}>
                        {sevIcon(i.severity, "size-3.5 mt-px shrink-0")} {i.message}
                      </p>
                    ))}
                    {f.note && !issues.length && f.method !== "manual" && <p className="mt-1 text-[12px] text-muted">{f.note}</p>}
                  </div>
                );
              })}
            </div>

            {/* line items */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-[13px] font-semibold">Line items <span className="font-normal text-muted">({itemList.length})</span></h3>
                <div className="flex gap-1">
                  {items !== null && <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() => setItems(null)}>Undo</Button>}
                  <Button size="sm" variant="ghost" disabled={readOnly} icon={<Plus className="size-3.5" />} onClick={() => setItems([...(items ?? rec.line_items), { description: "", quantity: null, unit_price: null, amount: null }])}>Add line</Button>
                </div>
              </div>
              <div className="overflow-hidden rounded-md border border-line">
                <table className="w-full text-[12.5px]">
                  <thead className="bg-bg text-left text-[11.5px] text-muted">
                    <tr><th className="px-2 py-1.5 font-medium">Description</th><th className="w-14 px-1 py-1.5 text-right font-medium">Qty</th><th className="w-20 px-1 py-1.5 text-right font-medium">Price</th><th className="w-24 px-2 py-1.5 text-right font-medium">Amount</th><th className="w-7" /></tr>
                  </thead>
                  <tbody>
                    {itemList.map((it, i) => {
                      const bad = it.quantity != null && it.unit_price != null && it.amount != null && Math.abs(it.quantity * it.unit_price - it.amount) > Math.max(0.02, Math.abs(it.amount) * 0.005);
                      const upd = (patch: Partial<LineItem>) => setItems((itemList).map((x, j) => (j === i ? { ...x, ...patch } : x)));
                      const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/,/g, "")));
                      const key = `item-${i}`;
                      return (
                        <tr key={i} className={clsx("border-t border-line", activeKey === key && "bg-accent-soft/50", bad && "bg-err-soft/40")} onClick={() => it.source && setActiveKey(key)}>
                          <td className="px-1 py-0.5"><input aria-label={`Line ${i + 1} description`} value={it.description ?? ""} onChange={(e) => upd({ description: e.target.value })} className="h-7 w-full rounded-sm bg-transparent px-1 outline-none focus:bg-card focus:ring-1 focus:ring-accent" /></td>
                          <td className="px-0.5"><input aria-label={`Line ${i + 1} quantity`} value={it.quantity ?? ""} onChange={(e) => upd({ quantity: num(e.target.value) })} className="h-7 w-full rounded-sm bg-transparent px-1 text-right font-mono tabular outline-none focus:bg-card focus:ring-1 focus:ring-accent" /></td>
                          <td className="px-0.5"><input aria-label={`Line ${i + 1} unit price`} value={it.unit_price ?? ""} onChange={(e) => upd({ unit_price: num(e.target.value) })} className="h-7 w-full rounded-sm bg-transparent px-1 text-right font-mono tabular outline-none focus:bg-card focus:ring-1 focus:ring-accent" /></td>
                          <td className="px-0.5"><input aria-label={`Line ${i + 1} amount`} value={it.amount ?? ""} onChange={(e) => upd({ amount: num(e.target.value) })} className={clsx("h-7 w-full rounded-sm bg-transparent px-1 text-right font-mono tabular outline-none focus:bg-card focus:ring-1 focus:ring-accent", bad && "text-err")} title={bad ? "Quantity × price does not equal amount" : undefined} /></td>
                          <td className="px-0.5"><button aria-label={`Remove line ${i + 1}`} onClick={(e) => { e.stopPropagation(); setItems(itemList.filter((_, j) => j !== i)); }} className="btn grid size-6 place-items-center rounded-sm text-faint hover:bg-err-soft hover:text-err"><Trash2 className="size-3" /></button></td>
                        </tr>
                      );
                    })}
                    {!itemList.length && <tr><td colSpan={5} className="px-3 py-4 text-center text-muted">No line items found</td></tr>}
                  </tbody>
                  {itemList.length > 0 && (
                    <tfoot>
                      <tr className="border-t border-line bg-bg text-[12px]">
                        <td colSpan={3} className="px-2 py-1.5 text-muted">Sum of lines{!Number.isNaN(subtotal) && <> vs subtotal <span className="font-mono tabular">{fmtMoney(subtotal)}</span></>}</td>
                        <td className={clsx("px-2 py-1.5 text-right font-mono font-semibold tabular", !Number.isNaN(subtotal) && Math.abs(itemsSum - subtotal) > 0.02 ? "text-err" : "text-ok")}>{fmtMoney(itemsSum)}</td>
                        <td />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          </div>
        )}

        {tab === "issues" && (
          <div className="space-y-2 px-5 py-4">
            {!rec.issues.length && <p className="py-8 text-center text-sm text-muted">No issues: every check passed.</p>}
            {rec.issues.map((i) => (
              <div key={i.id} className={clsx("rounded-md border p-3", i.resolved ? "border-line opacity-60" : i.severity === "error" ? "border-err/30" : i.severity === "warning" ? "border-warn/30" : "border-line")}>
                <div className="flex items-start gap-2">
                  {sevIcon(i.severity, "size-4 mt-0.5 shrink-0")}
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] font-semibold text-ink-2">{humanize(i.code)}{i.field && <span className="font-normal text-muted"> · {FIELD_LABELS[i.field] ?? humanize(i.field)}</span>}</p>
                    <p className="mt-0.5 text-[13px] text-ink">{i.message}</p>
                    {typeof i.details?.document_id === "string" && (
                      <Link href={`/review?doc=${i.details.document_id}${typeof i.details.invoice_id === "string" ? `&rec=${i.details.invoice_id}` : ""}`} className="mt-1 inline-block text-[12px] font-medium text-accent underline-draw">Open the other document</Link>
                    )}
                    {typeof i.details?.invoice_id === "string" && typeof i.details?.document_id !== "string" && (
                      <Link href={`/review?rec=${i.details.invoice_id}`} className="mt-1 inline-block text-[12px] font-medium text-accent underline-draw">Open the matching record</Link>
                    )}
                  </div>
                  {!i.resolved && i.severity !== "info" && !readOnly && (
                    <Button size="sm" variant="ghost" onClick={async () => {
                      try { onSaved(await api<InvoiceFull>(`/api/invoices/${rec.id}/issues/${i.id}/resolve`, { method: "POST" })); toast("ok", "Issue marked resolved"); }
                      catch (e) { toast("err", (e as Error).message); }
                    }}>Resolve</Button>
                  )}
                  {i.resolved && <Badge tone="ok">resolved</Badge>}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "history" && (
          <div className="space-y-6 px-5 py-4">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold"><History className="size-4 text-muted" /> Corrections</h3>
              {!rec.corrections.length ? <p className="text-[13px] text-muted">No manual changes yet.</p> : (
                <ol className="space-y-2">
                  {rec.corrections.slice().reverse().map((c) => (
                    <li key={c.id} className="rounded-md bg-bg px-3 py-2 text-[12.5px]">
                      <span className="font-medium">{c.field === "_status" ? "Status" : FIELD_LABELS[c.field] ?? humanize(c.field)}</span>
                      {c.field !== "line_items" ? (
                        <> <span className="text-muted line-through">{toStr(c.old_value?.value) || "empty"}</span> → <span className="font-medium text-accent-strong">{toStr(c.new_value?.value) || "empty"}</span></>
                      ) : <span className="text-muted"> edited</span>}
                      <span className="block text-[11.5px] text-faint">{c.corrected_by} · {fmtAgo(c.created_at)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
            <section>
              <h3 className="mb-2 text-[13px] font-semibold">Processing history</h3>
              <ol className="relative space-y-3 border-l border-line pl-4">
                {events.map((e) => (
                  <li key={e.id} className="relative text-[12.5px]">
                    <span className={clsx("absolute -left-[21px] top-1 size-2.5 rounded-full ring-2 ring-card", e.status === "error" ? "bg-err" : e.status === "warning" ? "bg-warn" : e.status === "started" ? "bg-faint" : "bg-ok")} />
                    <span className="font-medium">{humanize(e.stage)}</span> <span className="text-muted">{e.status}{e.duration_ms != null && ` · ${fmtMs(e.duration_ms)}`}</span>
                    {e.attempt > 1 && <Badge className="ml-1.5">attempt {e.attempt}</Badge>}
                    {e.message && <span className="block text-muted">{e.message}</span>}
                  </li>
                ))}
              </ol>
            </section>
          </div>
        )}

        {tab === "json" && (
          <div className="px-5 py-4">
            <div className="mb-2 flex justify-end">
              <Button size="sm" icon={<Copy className="size-3.5" />} onClick={() => { navigator.clipboard?.writeText(json); toast("ok", "JSON copied"); }}>Copy JSON</Button>
            </div>
            <pre className="overflow-auto rounded-md bg-code p-4 font-mono text-[12px] leading-relaxed text-code-ink scroll-thin">{json}</pre>
          </div>
        )}
      </div>

      {/* action bar */}
      <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 border-t border-line bg-bg px-5 py-3">
        {readOnly ? (
          <span className="text-[12.5px] text-muted">Read-only access: viewers can inspect records but not change them.</span>
        ) : dirty ? (
          <>
            <span className="text-[12.5px] text-muted">{dirtyFields.length + (items ? 1 : 0)} unsaved change{dirtyFields.length + (items ? 1 : 0) > 1 ? "s" : ""}</span>
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => { setDraft({}); setItems(null); }}>Discard</Button>
            <Button size="sm" variant="primary" loading={saving} icon={<Check className="size-3.5" />} onClick={save}>Save and re-check <span className="ml-1 hidden opacity-70 sm:inline"><Kbd>Ctrl S</Kbd></span></Button>
          </>
        ) : (
          <>
            <span className="text-[12.5px] text-muted">{rec.needs_review ? "Edit a field to correct it, or approve as is." : "This record passed review."}</span>
            <Button size="sm" variant="primary" className="ml-auto" loading={approving} disabled={!rec.needs_review} icon={<CheckCheck className="size-3.5" />} onClick={approve}>
              Approve record <span className="ml-1 hidden opacity-70 sm:inline"><Kbd>Ctrl ↵</Kbd></span>
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
