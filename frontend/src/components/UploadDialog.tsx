"use client";

import clsx from "clsx";
import { ArrowRight, CheckCircle2, UploadCloud, X, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { fetcher, type DocSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes } from "@/lib/format";
import { fileIcon, UploadZone } from "./UploadZone";
import { Progress, StatusBadge } from "./ui";

/** Global upload: opened from the top bar, or by dragging files anywhere over the window. Shows live processing for what was just sent. */
export function UploadDialog() {
  const { can } = useAuth();
  const { mutate } = useSWRConfig();
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState<DocSummary[]>([]);
  const [incoming, setIncoming] = useState<File[] | null>(null);

  const close = useCallback(() => { setOpen(false); setIncoming(null); }, []);
  const refreshLists = useCallback(() => mutate((k) => typeof k === "string" && (k.startsWith("/api/documents") || k.startsWith("/api/stats") || k.startsWith("/api/search") || k.startsWith("/api/analytics"))), [mutate]);

  useEffect(() => {
    if (!can("reviewer")) return;
    const onOpen = () => setOpen(true);
    let depth = 0;
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const enter = (e: DragEvent) => { if (hasFiles(e)) { depth++; setOpen(true); } };
    const leave = (e: DragEvent) => { if (hasFiles(e)) depth = Math.max(0, depth - 1); };
    const over = (e: DragEvent) => { if (hasFiles(e)) e.preventDefault(); };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth = 0;
      // a drop outside the zone still uploads: hand the files to the zone
      const target = e.target as HTMLElement;
      if (!target.closest("[data-dropzone]") && e.dataTransfer?.files.length) { setOpen(true); setIncoming(Array.from(e.dataTransfer.files)); }
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("open-upload", onOpen);
    window.addEventListener("dragenter", enter); window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over); window.addEventListener("drop", drop);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("open-upload", onOpen);
      window.removeEventListener("dragenter", enter); window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over); window.removeEventListener("drop", drop);
      window.removeEventListener("keydown", key);
    };
  }, [can, close]);

  const ids = sent.map((d) => d.id).join(",");
  const { data } = useSWR<{ documents: DocSummary[] }>(open && ids ? `/api/documents/status?ids=${ids}` : null, fetcher, {
    refreshInterval: (d) => (d?.documents.every((x) => !["queued", "processing"].includes(x.status)) ? 0 : 900),
    onSuccess: (d) => { if (d.documents.every((x) => !["queued", "processing"].includes(x.status))) refreshLists(); },
  });
  const live = new Map((data?.documents ?? []).map((d) => [d.id, d]));
  const done = sent.length > 0 && sent.every((d) => !["queued", "processing"].includes((live.get(d.id) ?? d).status));

  if (!open || !can("reviewer")) return null;
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center p-4">
      <div className="fade absolute inset-0 bg-ink/45 backdrop-blur-[2px]" onClick={close} />
      <div role="dialog" aria-modal="true" aria-labelledby="upload-title" className="pop relative flex max-h-[88dvh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-line bg-card shadow-[var(--shadow-pop)]">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 id="upload-title" className="flex items-center gap-2 text-[15px] font-semibold"><UploadCloud className="size-4 text-accent" /> Upload documents</h2>
          <button onClick={close} aria-label="Close" className="btn grid size-8 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink"><X className="size-4" /></button>
        </div>
        <div className="space-y-4 overflow-y-auto p-5 scroll-thin">
          <UploadZone initialFiles={incoming} onUploaded={(docs) => { setSent((s) => [...docs, ...s]); setIncoming(null); refreshLists(); }} />
          {sent.length > 0 && (
            <div>
              <div className="mb-2 flex items-center justify-between text-[13px]">
                <p className="font-medium">{done ? "All files processed" : "Processing…"}</p>
                <Link href="/documents/" onClick={close} className="inline-flex items-center gap-1 font-medium text-accent underline-draw">Open documents <ArrowRight className="size-3.5" /></Link>
              </div>
              <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
                {sent.slice(0, 50).map((d0) => {
                  const d = live.get(d0.id) ?? d0;
                  const busy = d.status === "queued" || d.status === "processing";
                  return (
                    <li key={d.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-surface">{fileIcon(d.file_type)}</span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{d.filename}</p>
                        {busy ? <Progress value={d.progress} live className="mt-1.5" /> : <p className={clsx("truncate text-[12px]", d.status === "failed" ? "text-err" : "text-muted")}>{d.status === "failed" ? d.error_message : `${d.invoice_count} record${d.invoice_count === 1 ? "" : "s"} · ${fmtBytes(d.size_bytes)}`}</p>}
                      </div>
                      {d.status === "failed" ? <XCircle className="size-4 text-err" /> : busy ? <StatusBadge status={d.status} /> : <CheckCircle2 className="size-4 text-ok" />}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
