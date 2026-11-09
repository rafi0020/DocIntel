"use client";

import clsx from "clsx";
import { FileSpreadsheet, FileText, ImageIcon, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { uploadFiles, type DocSummary } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { Progress, useToast } from "./ui";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.xlsx,.xls,.csv";

export function fileIcon(type: string, className = "size-4") {
  if (["xlsx", "xls", "csv"].includes(type)) return <FileSpreadsheet className={clsx(className, "text-ok")} />;
  if (["png", "jpg", "jpeg", "tif", "tiff"].includes(type)) return <ImageIcon className={clsx(className, "text-info")} />;
  return <FileText className={clsx(className, "text-err")} />;
}

export function UploadZone({ onUploaded, initialFiles }: { onUploaded: (docs: DocSummary[]) => void; initialFiles?: File[] | null }) {
  const [drag, setDrag] = useState(false);
  const [batch, setBatch] = useState<{ files: File[]; progress: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const depth = useRef(0); // dragenter/leave fire for every child; count them so the highlight does not flicker
  const toast = useToast();

  async function start(list: FileList | File[]) {
    const files = Array.from(list);
    if (!files.length || batch) return;
    setBatch({ files, progress: 0 });
    try {
      const res = await uploadFiles(files, (p) => setBatch((b) => (b ? { ...b, progress: p } : b)));
      onUploaded(res.documents);
      if (res.documents.length) toast("ok", `${res.documents.length} file${res.documents.length > 1 ? "s" : ""} queued for processing`);
      res.rejected.forEach((r) => toast("err", `${r.filename}: ${r.reason}`));
    } catch (e) {
      toast("err", (e as Error).message);
    } finally {
      setBatch(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  // files dropped on the page rather than on the zone itself
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (initialFiles?.length) start(initialFiles); }, [initialFiles]);

  const total = batch?.files.reduce((s, f) => s + f.size, 0) ?? 0;
  return (
    <div
      data-dropzone
      onDragEnter={(e) => { e.preventDefault(); depth.current++; setDrag(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDrag(false); }}
      onDrop={(e) => { e.preventDefault(); depth.current = 0; setDrag(false); start(e.dataTransfer.files); }}
      className={clsx(
        "relative rounded-lg border-[1.5px] border-dashed bg-card transition-colors",
        drag ? "border-accent bg-accent-soft/60" : "border-line-strong hover:border-accent/60",
      )}
    >
      {batch ? (
        <div className="flex flex-col gap-3 px-6 py-6">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Uploading {batch.files.length} file{batch.files.length > 1 ? "s" : ""} · {fmtBytes(total)}</span>
            <span className="font-mono text-muted tabular">{Math.round(batch.progress * 100)}%</span>
          </div>
          <Progress value={batch.progress} live />
          <div className="flex flex-wrap gap-1.5">
            {batch.files.slice(0, 12).map((f) => (
              <span key={f.name + f.size} className="inline-flex items-center gap-1.5 rounded-sm bg-surface px-2 py-1 text-[12px] text-ink-2">
                {fileIcon(f.name.split(".").pop()?.toLowerCase() ?? "", "size-3.5")} {f.name}
              </span>
            ))}
            {batch.files.length > 12 && <span className="px-2 py-1 text-[12px] text-muted">+{batch.files.length - 12} more</span>}
          </div>
        </div>
      ) : (
        <button type="button" onClick={() => inputRef.current?.click()} className="group flex w-full flex-col items-center gap-2 px-6 py-8 text-center sm:flex-row sm:gap-5 sm:text-left">
          <span className={clsx("grid size-12 shrink-0 place-items-center rounded-lg transition-colors", drag ? "bg-accent text-on-accent" : "bg-accent-soft text-accent group-hover:bg-accent group-hover:text-on-accent")}>
            <UploadCloud className="size-6" />
          </span>
          <span className="flex-1">
            <span className="block font-medium text-ink">{drag ? "Drop to start processing" : "Drop invoices, receipts, scans or ledgers here"}</span>
            <span className="mt-0.5 block text-sm text-muted">PDF (any length), JPG, PNG, TIFF, XLSX, XLS, CSV · up to 50 files at once. Processing starts immediately.</span>
          </span>
          <span className="btn inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-on-accent shadow-sm group-hover:bg-accent-strong">Choose files</span>
        </button>
      )}
      <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden" aria-label="Choose files to upload" onChange={(e) => e.target.files && start(e.target.files)} />
    </div>
  );
}
