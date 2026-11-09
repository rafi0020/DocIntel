"use client";

import clsx from "clsx";
import { useEffect, useRef, useState, type ReactNode } from "react";

/** Width of an element, tracked with ResizeObserver, so SVG charts stay crisp at any size. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const niceMax = (v: number) => {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return ([1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].find((s) => n <= s) ?? 10) * p;
};

export type Point = { label: string; value: number; extra?: number };

/** Area + line chart with a hover read-out. `extra` is drawn as a second, smaller series (e.g. failures). */
export function AreaChart({ data, height = 270, name = "Documents", extraName = "Failed" }: { data: Point[]; height?: number; name?: string; extraName?: string }) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 34, r: 8, t: 10, b: 24 };
  const max = niceMax(Math.max(1, ...data.map((d) => d.value)));
  const iw = Math.max(0, w - pad.l - pad.r);
  const ih = height - pad.t - pad.b;
  const x = (i: number) => pad.l + (data.length <= 1 ? iw / 2 : (i / (data.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.value).toFixed(1)}`).join(" ");
  const area = data.length ? `${line} L${x(data.length - 1).toFixed(1)},${pad.t + ih} L${x(0).toFixed(1)},${pad.t + ih} Z` : "";
  const extra = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.extra ?? 0).toFixed(1)}`).join(" ");
  const hasExtra = data.some((d) => d.extra);
  const ticks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(max * t)))];
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 70))));
  const h = hover !== null ? data[hover] : null;
  return (
    <div ref={ref} className="relative" style={{ height }}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={`${name} per day`}
          onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.round(((e.clientX - r.left - pad.l) / Math.max(1, iw)) * (data.length - 1)); setHover(Math.min(data.length - 1, Math.max(0, i))); }}
          onMouseLeave={() => setHover(null)}>
          <defs><linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.22" /><stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" /></linearGradient></defs>
          {ticks.map((t) => (
            <g key={t}><line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeDasharray={t ? "3 4" : undefined} />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize="10.5" fill="var(--color-faint)" className="tabular">{t}</text></g>
          ))}
          {data.map((d, i) => i % labelEvery === 0 && <text key={d.label} x={x(i)} y={height - 6} textAnchor="middle" fontSize="10.5" fill="var(--color-faint)">{d.label}</text>)}
          <path d={area} fill="url(#area-fill)" />
          <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" className="draw" style={{ ["--len" as string]: 2000 }} />
          {hasExtra && <path d={extra} fill="none" stroke="var(--color-err)" strokeWidth="1.5" strokeDasharray="4 3" />}
          {h && hover !== null && (<g><line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--color-line-strong)" /><circle cx={x(hover)} cy={y(h.value)} r="4" fill="var(--color-card)" stroke="var(--color-accent)" strokeWidth="2" /></g>)}
        </svg>
      )}
      {h && hover !== null && (
        <div className="pointer-events-none absolute z-10 rounded-md border border-line bg-card px-2.5 py-1.5 text-[12px] shadow-[var(--shadow-lift)]"
          style={{ left: Math.min(Math.max(x(hover) - 50, 0), Math.max(0, w - 120)), top: 0 }}>
          <p className="font-medium">{h.label}</p>
          <p className="text-muted"><span className="tabular font-semibold text-ink">{h.value}</span> {name.toLowerCase()}{hasExtra && <> · <span className="tabular font-semibold text-err">{h.extra ?? 0}</span> {extraName.toLowerCase()}</>}</p>
        </div>
      )}
    </div>
  );
}

export type Slice = { label: string; value: number; color: string };

export function Donut({ slices, center, sub, size = 168 }: { slices: Slice[]; center: ReactNode; sub?: string; size?: number }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  const r = size / 2 - 12, c = 2 * Math.PI * r;
  let off = 0;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-4">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Review outcome mix">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-surface)" strokeWidth="14" />
          {total > 0 && slices.filter((s) => s.value > 0).map((s) => {
            const len = (s.value / total) * c;
            const el = <circle key={s.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color} strokeWidth="14" strokeDasharray={`${Math.max(0, len - 2)} ${c - Math.max(0, len - 2)}`} strokeDashoffset={-off} transform={`rotate(-90 ${size / 2} ${size / 2})`} />;
            off += len;
            return el;
          })}
        </svg>
        <div className="absolute inset-0 grid place-content-center text-center"><p className="text-[26px] font-semibold leading-none tracking-tight tabular">{center}</p>{sub && <p className="mt-1 text-[11.5px] text-muted">{sub}</p>}</div>
      </div>
      <ul className="space-y-2 text-[13px]">
        {slices.map((s) => (
          <li key={s.label} className="flex items-center gap-2.5"><span className="size-2.5 rounded-sm" style={{ background: s.color }} /><span className="text-ink-2">{s.label}</span>
            <span className="ml-auto pl-4 font-mono tabular text-ink">{s.value}</span><span className="w-10 text-right font-mono text-[12px] text-faint tabular">{total ? Math.round((100 * s.value) / total) : 0}%</span></li>
        ))}
      </ul>
    </div>
  );
}

export function HBars({ items, format = (v: number) => String(v), tone = "accent", empty = "No data yet" }: { items: { label: string; value: number; hint?: string }[]; format?: (v: number) => string; tone?: "accent" | "err" | "warn"; empty?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <p className="py-8 text-center text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-3">
      {items.map((i) => (
        <li key={`${i.label}|${i.hint ?? ""}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]"><span className="min-w-0 truncate text-ink-2" title={i.label}>{i.label}</span><span className="shrink-0 font-mono tabular text-ink">{format(i.value)}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-surface"><div className={clsx("grow h-full rounded-full", tone === "accent" ? "bg-accent" : tone === "err" ? "bg-err" : "bg-warn")} style={{ width: `${Math.max(2, (i.value / max) * 100)}%` }} /></div>
          {i.hint && <p className="mt-0.5 text-[11.5px] text-faint">{i.hint}</p>}
        </li>
      ))}
    </ul>
  );
}

export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  const max = Math.max(1, ...values), w = 72, h = 26;
  const pts = values.map((v, i) => `${((i / Math.max(1, values.length - 1)) * w).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(" ");
  return <svg width={w} height={h} className={className} aria-hidden><polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" /></svg>;
}
