"use client";

import { ChevronDown, Download, FileJson, FileSpreadsheet, FileText } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
import { useDismiss } from "./ui";

const FORMATS = [
  { id: "csv", label: "CSV", hint: "Opens in Excel or Sheets", icon: FileText },
  { id: "xlsx", label: "Excel workbook", hint: ".xlsx with a frozen header", icon: FileSpreadsheet },
  { id: "json", label: "JSON", hint: "For other systems", icon: FileJson },
];

/** Download extracted records. `params` are the same filters search accepts, so "export what I see" is one click. */
export function ExportMenu({ params = "", label = "Export" }: { params?: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="btn inline-flex h-9 items-center gap-2 rounded-md bg-card px-3.5 text-sm font-medium text-ink ring-1 ring-inset ring-line-strong hover:ring-ink/30">
        <Download className="size-4" /> {label} <ChevronDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div role="menu" className="pop absolute right-0 z-30 mt-1.5 w-64 origin-top-right rounded-lg border border-line bg-card p-1 shadow-[var(--shadow-pop)]">
          {FORMATS.map(({ id, label: l, hint, icon: Icon }) => (
            <a key={id} role="menuitem" href={`${API_URL}/api/export?format=${id}${params ? `&${params}` : ""}`} onClick={close}
              className="flex items-center gap-3 rounded-md px-2.5 py-2 text-sm hover:bg-surface">
              <span className="grid size-8 place-items-center rounded-md bg-surface text-muted"><Icon className="size-4" /></span>
              <span><span className="block font-medium">{l}</span><span className="block text-[12px] text-muted">{hint}</span></span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
