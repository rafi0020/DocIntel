"use client";

import clsx from "clsx";
import { ArrowLeftRight, CornerDownLeft, FileText, Inbox, LayoutDashboard, ListChecks, Search, Table2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type SearchResponse } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { Kbd, StatusBadge } from "./ui";

type Item = { id: string; label: string; hint?: string; icon: React.ReactNode; go: () => void; status?: string };

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("open-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setTimeout(() => input.current?.focus(), 10);
    } else {
      setQ("");
      setRes(null);
    }
  }, [open]);

  useEffect(() => {
    if (!q.trim()) return setRes(null);
    const t = setTimeout(() => {
      api<SearchResponse>(`/api/search?mode=keyword&limit=6&q=${encodeURIComponent(q)}`).then(setRes).catch(() => setRes(null));
    }, 160);
    return () => clearTimeout(t);
  }, [q]);

  const items: Item[] = useMemo(() => {
    const nav: Item[] = [
      { id: "n0", label: "Go to dashboard", icon: <LayoutDashboard className="size-4" />, go: () => router.push("/") },
      { id: "n1", label: "Go to documents", icon: <Inbox className="size-4" />, go: () => router.push("/documents/") },
      { id: "n2", label: "Open review queue", icon: <ListChecks className="size-4" />, go: () => router.push("/review") },
      { id: "n4", label: "Search records", icon: <Search className="size-4" />, go: () => router.push("/search") },
      { id: "n3", label: "Cross-verify two documents", icon: <ArrowLeftRight className="size-4" />, go: () => router.push("/compare") },
    ];
    const recs: Item[] = (res?.results ?? []).map((r) => ({
      id: r.id,
      label: `${r.invoice_number ?? "No number"} · ${r.supplier_name ?? "Unknown supplier"}`,
      hint: `${r.filename} · ${fmtMoney(r.total, r.currency)}`,
      status: r.review_status,
      icon: r.record_kind === "ledger_row" ? <Table2 className="size-4" /> : <FileText className="size-4" />,
      go: () => router.push(`/review?doc=${r.document_id}&rec=${r.id}`),
    }));
    const all: Item[] = q.trim()
      ? [...recs, { id: "s", label: `Search everything for “${q}”`, icon: <Search className="size-4" />, go: () => router.push(`/search?q=${encodeURIComponent(q)}`) }]
      : nav;
    return all;
  }, [res, q, router]);

  useEffect(() => setActive(0), [items.length]);
  useEffect(() => { list.current?.children[active]?.scrollIntoView({ block: "nearest" }); }, [active]);

  if (!open) return null;
  const run = (it: Item) => {
    it.go();
    setOpen(false);
  };
  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center px-4 pt-[12vh]" role="dialog" aria-modal="true" aria-label="Quick find">
      <div className="absolute inset-0 bg-ink/35 backdrop-blur-[2px]" onClick={() => setOpen(false)} />
      <div className="enter relative w-full max-w-[620px] overflow-hidden rounded-lg border border-line bg-card shadow-[var(--shadow-pop)]">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="size-4 text-muted" />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
              if (e.key === "Enter" && items[active]) run(items[active]);
            }}
            placeholder="Find an invoice number, supplier, customer…"
            aria-label="Search records"
            className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-faint"
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul ref={list} className="pane max-h-[50vh] p-1.5 scroll-thin" role="listbox">
          {items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === active}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => run(it)}
                className={clsx("flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm", i === active ? "bg-accent-soft text-ink" : "text-ink-2")}
              >
                <span className={clsx(i === active ? "text-accent" : "text-muted")}>{it.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{it.label}</span>
                  {it.hint && <span className="block truncate text-[12px] text-muted">{it.hint}</span>}
                </span>
                {it.status && <StatusBadge status={it.status} />}
                {i === active && <CornerDownLeft className="size-3.5 text-muted" />}
              </button>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-4 border-t border-line bg-bg px-4 py-2 text-[12px] text-muted">
          <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
          <span className="flex items-center gap-1"><Kbd>↵</Kbd> open</span>
          <span className="ml-auto">{q.trim() ? (res ? `${res.total} match${res.total === 1 ? "" : "es"}` : "Searching…") : "Type to search records"}</span>
        </div>
      </div>
    </div>
  );
}
