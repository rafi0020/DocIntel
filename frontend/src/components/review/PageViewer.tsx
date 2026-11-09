"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight, Eye, EyeOff, FileText, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { assetUrl, fetcher, FIELD_LABELS, type PageData, type PageMeta, type Source } from "@/lib/api";
import { Badge, Skeleton } from "../ui";

export type Highlight = { key: string; label: string; source: Source; tone: "active" | "field" | "item" };

export function PageViewer({ docId, pages, page, setPage, highlights, activeKey, onPick }: {
  docId: string; pages: PageMeta[]; page: number; setPage: (n: number) => void;
  highlights: Highlight[]; activeKey: string | null; onPick: (key: string) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [showAll, setShowAll] = useState(true);
  const [mode, setMode] = useState<"image" | "text">("image");
  const [loaded, setLoaded] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const meta = pages.find((p) => p.page_no === page);
  const src = assetUrl(`/api/documents/${docId}/pages/${page}/image`);
  const { data: pageData } = useSWR<PageData>(mode === "text" ? `/api/documents/${docId}/pages/${page}` : null, fetcher);
  const onPage = highlights.filter((h) => h.source.page === page && h.source.box);
  const active = onPage.find((h) => h.key === activeKey);

  // bring the active highlight into view
  useEffect(() => {
    if (!active?.source.box || !scroller.current || loaded !== src) return;
    const el = scroller.current;
    const img = el.querySelector("img");
    if (!img) return;
    const [, y0] = active.source.box;
    el.scrollTo({ top: Math.max(0, y0 * img.clientHeight - el.clientHeight / 3), behavior: "smooth" });
  }, [activeKey, active, loaded, src]);

  const n = pages.length;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-card px-3 py-2">
        <div className="flex items-center gap-1">
          <button aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)} className="btn grid size-8 place-items-center rounded-md hover:bg-surface disabled:opacity-30"><ChevronLeft className="size-4" /></button>
          <label className="flex items-center gap-1.5 text-[13px] text-muted">
            <span className="sr-only">Page number</span>
            <input
              key={page}
              defaultValue={page}
              onKeyDown={(e) => { if (e.key === "Enter") { const v = parseInt((e.target as HTMLInputElement).value); if (v >= 1 && v <= n) setPage(v); } }}
              className="h-7 w-12 rounded-sm border border-line-strong bg-card text-center font-mono text-[13px] tabular text-ink outline-none focus:border-accent"
            />
            <span className="font-mono tabular">/ {n}</span>
          </label>
          <button aria-label="Next page" disabled={page >= n} onClick={() => setPage(page + 1)} className="btn grid size-8 place-items-center rounded-md hover:bg-surface disabled:opacity-30"><ChevronRight className="size-4" /></button>
        </div>
        {meta && (
          <Badge tone={meta.method === "ocr" ? "info" : "muted"}>
            {meta.method === "ocr" ? `OCR · ${Math.round((meta.ocr_confidence ?? 0) * 100)}% confidence` : "Digital text layer"}
          </Badge>
        )}
        {meta?.error && <Badge tone="err">{meta.error}</Badge>}
        <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-1">
          <button onClick={() => setMode(mode === "image" ? "text" : "image")} className={clsx("btn inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12.5px] font-medium", mode === "text" ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface")}>
            <FileText className="size-3.5" /> {mode === "text" ? "Show page" : <><span className="max-sm:hidden">Extracted text</span><span className="sm:hidden">Text</span></>}
          </button>
          <button onClick={() => setShowAll((s) => !s)} aria-pressed={showAll} className="btn inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12.5px] font-medium text-ink-2 hover:bg-surface">
            {showAll ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />} <span className="max-sm:sr-only">Detections</span>
          </button>
          <span className="mx-1 h-5 w-px bg-line max-sm:hidden" />
          <button aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))} className="btn grid size-8 place-items-center rounded-md hover:bg-surface"><ZoomOut className="size-4" /></button>
          <span className="w-11 text-center font-mono text-[12px] text-muted tabular">{Math.round(zoom * 100)}%</span>
          <button aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))} className="btn grid size-8 place-items-center rounded-md hover:bg-surface"><ZoomIn className="size-4" /></button>
          <button aria-label="Fit to width" onClick={() => setZoom(1)} className="btn grid size-8 place-items-center rounded-md hover:bg-surface"><Maximize2 className="size-3.5" /></button>
        </div>
      </div>

      <div ref={scroller} className="pane relative min-h-0 flex-1 bg-canvas p-4 scroll-thin">
        {mode === "text" ? (
          <pre className="mx-auto max-w-[860px] whitespace-pre-wrap rounded-md bg-card p-5 font-mono text-[12.5px] leading-relaxed text-ink-2 shadow-[var(--shadow-card)]">
            {pageData ? pageData.text || "(no text on this page)" : "Loading…"}
          </pre>
        ) : (
          <div className="relative mx-auto bg-card shadow-[var(--shadow-lift)]" style={{ width: `${zoom * 100}%`, maxWidth: zoom === 1 ? 900 : undefined }}>
            {loaded !== src && <Skeleton className="absolute inset-0 rounded-none" />}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img key={src} src={src} alt={`Page ${page}`} onLoad={() => setLoaded(src)} className="block h-auto w-full select-none" draggable={false} style={{ minHeight: loaded === src ? undefined : 600 }} />
            {loaded === src && onPage.filter((h) => showAll || h.key === activeKey).map((h) => {
              const [x0, y0, x1, y1] = h.source.box!;
              const isActive = h.key === activeKey;
              return (
                <button
                  key={h.key + (isActive ? "-a" : "")}
                  onClick={() => onPick(h.key)}
                  title={h.label}
                  aria-label={`Select ${h.label}`}
                  className={clsx("absolute rounded-[2px] transition-colors",
                    isActive ? "box-hit z-10 bg-accent/15 ring-2 ring-accent" : h.tone === "item" ? "bg-info/5 ring-1 ring-info/35 hover:bg-info/15" : "bg-warn/10 ring-1 ring-warn/50 hover:bg-warn/20")}
                  style={{ left: `calc(${x0 * 100}% - 3px)`, top: `calc(${y0 * 100}% - 2px)`, width: `calc(${(x1 - x0) * 100}% + 6px)`, height: `calc(${(y1 - y0) * 100}% + 4px)` }}
                >
                  {isActive && (
                    <span className="absolute -top-6 left-0 whitespace-nowrap rounded-sm bg-accent px-1.5 py-0.5 text-[11px] font-medium text-on-accent shadow">{h.label}</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function SheetViewer({ docId, pages, page, setPage, highlights, activeKey, onPick, recordRow }: {
  docId: string; pages: PageMeta[]; page: number; setPage: (n: number) => void;
  highlights: Highlight[]; activeKey: string | null; onPick: (k: string) => void; recordRow: number | null;
}) {
  const sheet = pages.find((p) => p.page_no === page);
  const { data } = useSWR<PageData>(`/api/documents/${docId}/pages/${page}`, fetcher);
  const rows = data?.layout?.rows ?? [];
  const table = useRef<HTMLDivElement>(null);
  const cells = new Map<string, Highlight>();
  highlights.forEach((h) => { if (h.source.sheet === sheet?.label && h.source.row && h.source.col) cells.set(`${h.source.row}:${h.source.col}`, h); });
  const active = highlights.find((h) => h.key === activeKey);
  const focusRow = active?.source.sheet === sheet?.label ? active?.source.row : recordRow;

  useEffect(() => {
    if (!focusRow || !table.current) return;
    const el = table.current.querySelector<HTMLElement>(`[data-row="${focusRow}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusRow, rows.length]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 overflow-x-auto border-b border-line bg-card px-2 py-1.5 scroll-thin" role="tablist" aria-label="Sheets">
        {pages.map((p) => (
          <button key={p.page_no} role="tab" aria-selected={p.page_no === page} onClick={() => setPage(p.page_no)}
            className={clsx("btn h-8 whitespace-nowrap rounded-md px-3 text-[13px] font-medium", p.page_no === page ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface")}>
            {p.label}
          </button>
        ))}
      </div>
      <div ref={table} className="pane min-h-0 flex-1 bg-card scroll-thin">
        {!data ? <div className="p-4"><Skeleton className="h-64" /></div> : (
          <table className="min-w-full border-collapse font-mono text-[12.5px]">
            <tbody>
              {rows.slice(0, 2000).map((r, i) => {
                const rowNo = i + 1;
                return (
                  <tr key={i} data-row={rowNo} className={clsx(rowNo === recordRow && "bg-accent-soft/60")}>
                    <td className="sticky left-0 z-[1] border-b border-r border-line bg-bg px-2 py-1 text-right text-[11px] text-faint tabular">{rowNo}</td>
                    {r.map((c, j) => {
                      const h = cells.get(`${rowNo}:${j + 1}`);
                      const isActive = h && h.key === activeKey;
                      return (
                        <td key={j} onClick={() => h && onPick(h.key)}
                          className={clsx("whitespace-nowrap border-b border-r border-line px-2.5 py-1 tabular",
                            i === 0 && "font-semibold text-ink",
                            h && "cursor-pointer",
                            isActive ? "box-hit bg-accent/15 outline-2 -outline-offset-2 outline-accent" : h ? "bg-warn-soft/70" : "")}>
                          {c}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {rows.length > 2000 && <p className="p-3 text-[12px] text-muted">Showing the first 2,000 of {rows.length} rows.</p>}
      </div>
    </div>
  );
}

export function fieldHighlights(fields: Record<string, { source: Source | null; value: unknown }>, items: { source?: Source | null; description: string | null }[]): Highlight[] {
  const out: Highlight[] = [];
  Object.entries(fields).forEach(([k, f]) => {
    if (f?.source && f.value !== null && f.value !== undefined) out.push({ key: k, label: FIELD_LABELS[k] ?? k, source: f.source, tone: "field" });
  });
  items.forEach((it, i) => it.source && out.push({ key: `item-${i}`, label: `Line ${i + 1}${it.description ? ` · ${it.description}` : ""}`, source: it.source, tone: "item" }));
  return out;
}
