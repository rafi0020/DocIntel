"use client";

import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { Children, createContext, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode, type RefObject } from "react";
import { STATUS_META } from "@/lib/format";

/** Close a popover on Escape or on a press outside of `ref`. */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const press = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    window.addEventListener("keydown", key);
    window.addEventListener("pointerdown", press);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("pointerdown", press); };
  }, [open, onClose, ref]);
}

type Tone = "accent" | "ok" | "warn" | "err" | "muted" | "info";
const TONES: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent-strong ring-accent/20",
  ok: "bg-ok-soft text-ok ring-ok/20",
  warn: "bg-warn-soft text-warn ring-warn/25",
  err: "bg-err-soft text-err ring-err/20",
  info: "bg-info-soft text-info ring-info/20",
  muted: "bg-surface text-muted ring-line-strong/60",
};

export function Badge({ tone = "muted", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[11.5px] font-medium ring-1 ring-inset", TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { label: status, tone: "muted" as const };
  return (
    <Badge tone={m.tone}>
      <span className={clsx("size-1.5 rounded-full bg-current", status === "processing" && "pulse-dot")} />
      {m.label}
    </Badge>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "destructive"; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode };
export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "btn inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-accent text-on-accent shadow-sm hover:bg-accent-strong",
        variant === "secondary" && "bg-card text-ink ring-1 ring-inset ring-line-strong hover:ring-ink/30 hover:shadow-sm",
        variant === "ghost" && "text-ink-2 hover:bg-surface",
        variant === "danger" && "bg-card text-err ring-1 ring-inset ring-err/30 hover:bg-err-soft",
        variant === "destructive" && "bg-err text-on-accent shadow-sm hover:bg-err/90",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-lg border border-line bg-card shadow-[var(--shadow-card)]", className)}>{children}</div>;
}

/** A titled card: same header, padding and height behaviour everywhere. */
export function Panel({ title, description, action, children, className, flush }: { title: string; description?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <Card className={clsx("flex h-full flex-col overflow-clip", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-5 pb-1 pt-4">
        <div className="min-w-0 max-w-full"><h2 className="text-[14px] font-semibold tracking-tight">{title}</h2>{description && <p className="mt-0.5 text-[12.5px] text-muted">{description}</p>}</div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      <div className={clsx("min-h-0 flex-1", flush ? "pt-2" : "px-5 pb-5 pt-3")}>{children}</div>
    </Card>
  );
}

const STAT_TONE = { warn: "bg-warn-soft text-warn", err: "bg-err-soft text-err", ok: "bg-ok-soft text-ok", accent: "bg-accent-soft text-accent" } as const;

/** One KPI card. Same height as its neighbours, caption wraps instead of being cut off. */
export function Stat({ label, value, sub, tone = "accent", icon, aside }: { label: string; value: ReactNode; sub?: ReactNode; tone?: keyof typeof STAT_TONE; icon?: ReactNode; aside?: ReactNode }) {
  return (
    <Card className="flex h-full items-start gap-3 p-4">
      {icon && <span className={clsx("grid size-9 shrink-0 place-items-center rounded-md", STAT_TONE[tone])}>{icon}</span>}
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] text-muted">{label}</p>
        <p className={clsx("text-[22px] font-semibold leading-tight tracking-tight tabular", !icon && tone !== "accent" && STAT_TONE[tone].split(" ")[1])}>{value}</p>
        {sub && <p className="mt-0.5 text-[12px] leading-snug text-faint">{sub}</p>}
      </div>
      {aside && <div className="shrink-0 self-end">{aside}</div>}
    </Card>
  );
}

/** KPI row that never leaves an orphan: 5 cards run 2+2+1(wide) on phones, 3+2 on tablets, 5 across on desktop. */
export function StatGrid({ children }: { children: ReactNode }) {
  const items = Children.toArray(children);
  const n = items.length;
  return (
    <div className={clsx("grid grid-cols-2 gap-3", n === 5 ? "md:grid-cols-6 xl:grid-cols-5" : n === 4 ? "md:grid-cols-4" : "md:grid-cols-3")}>
      {items.map((c, i) => (
        <div key={i} className={clsx("min-w-0",
          n % 2 === 1 && i === n - 1 && "col-span-2",
          n === 5 ? (i < 3 ? "md:col-span-2 xl:col-span-1" : "md:col-span-3 xl:col-span-1") : "md:col-span-1")}>{c}</div>
      ))}
    </div>
  );
}

/** Generic dialog: Escape and backdrop click close it, focus moves inside. */
export function Modal({ open, title, description, onClose, children, footer, wide }: { open: boolean; title: string; description?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    (box.current?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])"))?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[65] grid place-items-center p-4">
      <div className="fade absolute inset-0 bg-ink/45 backdrop-blur-[2px]" onClick={onClose} />
      <div ref={box} role="dialog" aria-modal="true" aria-label={title} className={clsx("pop relative flex max-h-[90dvh] w-full flex-col overflow-hidden rounded-xl border border-line bg-card shadow-[var(--shadow-pop)]", wide ? "max-w-2xl" : "max-w-md")}>
        <div className="flex items-start justify-between gap-4 px-5 pb-2 pt-5">
          <div><h2 className="text-[16px] font-semibold tracking-tight">{title}</h2>{description && <p className="mt-1 text-sm text-muted">{description}</p>}</div>
          <button data-close onClick={onClose} aria-label="Close" className="btn -mr-1.5 -mt-1 grid size-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink"><X className="size-4" /></button>
        </div>
        <div className="overflow-y-auto px-5 py-3 scroll-thin">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line bg-bg px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return <label className="block text-[13px] font-medium text-ink-2">{label}<span className="mt-1.5 block">{children}</span>{hint && <span className="mt-1 block text-[12px] font-normal text-muted">{hint}</span>}</label>;
}

export function ConfirmDialog({ open, title, children, confirmLabel, tone = "danger", busy, onConfirm, onCancel }: {
  open: boolean; title: string; children?: ReactNode; confirmLabel: string; tone?: "danger" | "primary"; busy?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[65] grid place-items-center p-4">
      <div className="fade absolute inset-0 bg-ink/45" onClick={onCancel} />
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" className="pop relative w-full max-w-md rounded-lg border border-line bg-card p-5 shadow-[var(--shadow-pop)]">
        <h2 id="confirm-title" className="text-[16px] font-semibold tracking-tight">{title}</h2>
        {children && <div className="mt-1.5 text-sm text-ink-2">{children}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <button ref={cancelRef} onClick={onCancel} className="btn h-9 rounded-md px-3.5 text-sm font-medium text-ink-2 ring-1 ring-inset ring-line-strong hover:bg-surface">Cancel</button>
          <Button variant={tone === "danger" ? "destructive" : "primary"} loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

export function Progress({ value, live, tone = "accent", className }: { value: number; live?: boolean; tone?: "accent" | "err" | "ok"; className?: string }) {
  return (
    <div className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-surface", className)} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={clsx("h-full rounded-full transition-[width] duration-500 ease-out", tone === "accent" && "bg-accent", tone === "err" && "bg-err", tone === "ok" && "bg-ok", live && "progress-live")}
        style={{ width: `${Math.max(3, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function Confidence({ value, compact }: { value: number | null | undefined; compact?: boolean }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = value >= 0.85 ? "bg-ok" : value >= 0.5 ? "bg-warn" : "bg-err";
  return (
    <span className="inline-flex items-center gap-1.5" title={`Confidence ${pct}%`}>
      <span className={clsx("relative h-1.5 overflow-hidden rounded-full bg-surface", compact ? "w-8" : "w-12")}>
        <span className={clsx("absolute inset-y-0 left-0 rounded-full", tone)} style={{ width: `${pct}%` }} />
      </span>
      <span className="font-mono text-[11px] text-muted tabular">{pct}%</span>
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-sm border border-line-strong bg-card px-1 font-mono text-[10.5px] text-muted shadow-[0_1px_0_var(--color-line-strong)]">{children}</kbd>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton rounded-md", className)} />;
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-md bg-surface p-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "btn inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[4px] px-3 text-[13px] font-medium",
            value === o.value ? "bg-card text-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
          {o.count !== undefined && <span className={clsx("font-mono text-[11px] tabular", value === o.value ? "text-accent" : "text-faint")}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="mb-1 grid size-11 place-items-center rounded-lg bg-surface text-muted">{icon}</div>
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- toasts */
type Toast = { id: number; tone: "ok" | "err" | "info"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-[360px] max-w-[calc(100vw-2.5rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role={t.tone === "err" ? "alert" : "status"} className={clsx("enter pointer-events-auto rounded-md border bg-card px-3.5 py-2.5 text-sm shadow-[var(--shadow-pop)]",
            t.tone === "ok" && "border-ok/30", t.tone === "err" && "border-err/40", t.tone === "info" && "border-line")}>
            <span className={clsx("mr-2 inline-block size-2 rounded-full", t.tone === "ok" && "bg-ok", t.tone === "err" && "bg-err", t.tone === "info" && "bg-accent")} />
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
