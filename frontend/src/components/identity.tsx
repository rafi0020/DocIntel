"use client";

import clsx from "clsx";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemeMode } from "@/lib/theme";

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}

const ROLE_TONE: Record<string, string> = { admin: "bg-accent-soft text-accent", reviewer: "bg-ok-soft text-ok", viewer: "bg-surface text-muted" };
export function RoleTag({ role }: { role: string }) {
  return <span className={clsx("rounded-full px-2 py-px text-[11px] font-medium capitalize", ROLE_TONE[role] ?? ROLE_TONE.viewer)}>{role}</span>;
}

const THEMES: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "light", label: "Light", icon: Sun }, { mode: "dark", label: "Dark", icon: Moon }, { mode: "system", label: "System", icon: Monitor },
];

export function ThemeSwitch() {
  const { mode, setMode } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-md bg-surface p-0.5">
      {THEMES.map(({ mode: m, label, icon: Icon }) => (
        <button key={m} role="radio" aria-checked={mode === m} aria-label={label} title={label} onClick={() => setMode(m)}
          className={clsx("btn grid h-7 w-8 place-items-center rounded-[5px]", mode === m ? "bg-card text-ink shadow-sm" : "text-muted hover:text-ink")}>
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
