"use client";

import clsx from "clsx";
import { Activity, BookOpenText, ChevronsUpDown, Cpu, Keyboard, LogOut, Settings, SlidersHorizontal, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import useSWR from "swr";
import { API_URL, fetcher, type Health } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { initials, RoleTag, ThemeSwitch } from "./identity";
import { useDismiss } from "./ui";

type Level = "ok" | "warn" | "down";
const DOT: Record<Level, string> = { ok: "bg-ok", warn: "bg-warn", down: "bg-err" };

function useSystem() {
  const { data, error } = useSWR<Health>("/api/health", fetcher, { refreshInterval: 15000 });
  const rows: { label: string; value: string; level: Level }[] = [];
  let overall: Level = "warn";
  if (error) overall = "down";
  if (data) {
    const model = data.extraction.llm_provider === "rules" ? "Rule engine" : (data.extraction.llm_model ?? "").split("/").pop() || data.extraction.llm_provider;
    const workers = data.queue.workers ?? (data.queue.mode === "inline" ? "inline" : 0);
    rows.push(
      { label: "Database", value: data.database.ok ? "Connected" : "Unreachable", level: data.database.ok ? "ok" : "down" },
      { label: "Queue", value: data.queue.ok ? `${workers} worker${workers === 1 ? "" : "s"} · ${data.queue.queued ?? 0} queued` : "Unreachable", level: data.queue.ok ? (workers === 0 ? "warn" : "ok") : "down" },
      { label: "Extractor", value: model ?? "", level: "ok" },
      { label: "OCR", value: data.extraction.ocr_engine, level: "ok" },
    );
    overall = rows.some((r) => r.level === "down") ? "down" : rows.some((r) => r.level === "warn") ? "warn" : "ok";
  }
  const text = error ? "API unreachable" : overall === "ok" ? "All systems normal" : overall === "warn" ? "Needs attention" : "Problem detected";
  return { rows, overall, text, ready: !!data || !!error };
}

function Item({ href, icon: Icon, label, hint, onClick, external, danger }: { href?: string; icon: typeof Settings; label: string; hint?: string; onClick?: () => void; external?: boolean; danger?: boolean }) {
  const cls = clsx("btn flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13.5px]", danger ? "text-err hover:bg-err-soft" : "text-ink hover:bg-surface");
  const inner = <><Icon className={clsx("size-4 shrink-0", danger ? "" : "text-muted")} /><span className="flex-1">{label}</span>{hint && <span className="text-[12px] text-faint">{hint}</span>}</>;
  if (href && external) return <a role="menuitem" href={href} target="_blank" rel="noreferrer" onClick={onClick} className={cls}>{inner}</a>;
  if (href) return <Link role="menuitem" href={href} onClick={onClick} className={cls}>{inner}</Link>;
  return <button role="menuitem" onClick={onClick} className={cls}>{inner}</button>;
}

/** Everything about "me and the system" in one place: account, settings, status, API, shortcuts, sign out. */
export function UserCard({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { user, can, logout } = useAuth();
  const router = useRouter();
  const sys = useSystem();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  if (!user) return null;
  const go = () => { setOpen(false); onNavigate?.(); };

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label={`Account and system: ${user.name}, ${sys.text}`}
        className={clsx("btn group flex w-full items-center rounded-lg border border-line bg-card text-left hover:border-line-strong hover:bg-bg", open && "border-line-strong bg-bg", collapsed ? "justify-center p-1.5" : "gap-2.5 px-2.5 py-2")}>
        <span className="relative grid size-8 shrink-0 place-items-center rounded-full bg-accent text-[12px] font-semibold text-on-accent">
          {initials(user.name)}
          <span className={clsx("absolute -bottom-0.5 -right-0.5 size-3 rounded-full ring-2 ring-card", sys.ready ? DOT[sys.overall] : "bg-faint", sys.overall === "ok" && "pulse-dot")} aria-hidden />
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium leading-tight">{user.name}</span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] leading-tight text-muted"><span className="capitalize">{user.role}</span><span aria-hidden>·</span><span className="truncate">{sys.ready ? sys.text : "Checking…"}</span></span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-faint group-hover:text-muted" />
          </>
        )}
      </button>

      {open && (
        <div role="menu" aria-label="Account and system"
          className={clsx("pop absolute z-50 max-h-[calc(100dvh-6rem)] w-[316px] overflow-y-auto rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-pop)] scroll-thin",
            collapsed ? "bottom-0 left-full ml-3 origin-bottom-left" : "bottom-full left-0 mb-2 origin-bottom-left")}>
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-[13px] font-semibold text-on-accent">{initials(user.name)}</span>
            <div className="min-w-0"><p className="truncate text-sm font-semibold">{user.name}</p><p className="truncate text-[12.5px] text-muted">{user.email}</p><div className="mt-1"><RoleTag role={user.role} /></div></div>
          </div>
          <Item href="/settings/security/" icon={UserRound} label="Profile & password" onClick={go} />
          <Item href="/settings/" icon={Settings} label="Settings" onClick={go} />
          <div className="flex items-center justify-between px-2.5 py-1.5 text-[13.5px]"><span className="flex items-center gap-2.5 text-ink"><SlidersHorizontal className="size-4 text-muted" /> Theme</span><ThemeSwitch /></div>

          <div className="my-1.5 border-t border-line" />
          <div className="px-2.5 pb-1 pt-1">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-faint"><Activity className="size-3.5" /> System status</span>
              <Link href="/settings/status/" onClick={go} className="text-[12px] font-medium text-accent underline-draw">Details</Link>
            </div>
            <p className="mb-2 flex items-center gap-2 text-[13px] font-medium"><span className={clsx("size-2 rounded-full", sys.ready ? DOT[sys.overall] : "bg-faint")} />{sys.ready ? sys.text : "Checking…"}</p>
            <dl className="space-y-1.5 rounded-lg bg-bg px-3 py-2.5 text-[12.5px]">
              {sys.rows.map((r) => (
                <div key={r.label} className="flex items-center gap-2"><dt className="flex w-[72px] items-center gap-1.5 text-muted"><span className={clsx("size-1.5 rounded-full", DOT[r.level])} />{r.label}</dt><dd className="min-w-0 flex-1 truncate text-right text-ink-2 first-letter:uppercase" title={r.value}>{r.value}</dd></div>
              ))}
              {!sys.rows.length && <p className="text-muted">{sys.ready ? "The API is not responding." : "Checking…"}</p>}
            </dl>
            {can("admin") && <Link href="/settings/models/" onClick={go} className="btn mt-2 flex items-center gap-2 rounded-md px-1 py-1 text-[12.5px] font-medium text-accent hover:bg-accent-soft"><Cpu className="size-3.5" /> Models & API settings</Link>}
          </div>

          <div className="my-1.5 border-t border-line" />
          <Item href={`${API_URL}/docs`} external icon={BookOpenText} label="API reference" onClick={go} />
          <Item icon={Keyboard} label="Keyboard shortcuts" hint="?" onClick={() => { go(); window.dispatchEvent(new Event("open-shortcuts")); }} />

          <div className="my-1.5 border-t border-line" />
          <Item icon={LogOut} label="Sign out" danger onClick={async () => { setOpen(false); await logout(); router.replace("/login/"); }} />
        </div>
      )}
    </div>
  );
}
