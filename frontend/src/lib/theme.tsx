"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeMode = "light" | "dark" | "system";
const KEY = "di.theme";
const Ctx = createContext<{ mode: ThemeMode; setMode: (m: ThemeMode) => void; resolved: "light" | "dark" }>({ mode: "system", setMode: () => {}, resolved: "light" });

/** Runs before first paint (inlined in <head>) so there is no flash of the wrong theme. */
export const THEME_BOOT = `try{var t=localStorage.getItem('${KEY}')||'system';var d=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=d?'dark':'light'}catch(e){}`;

function resolve(m: ThemeMode): "light" | "dark" {
  return m === "dark" || (m === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    let saved: ThemeMode = "system";
    try { saved = (localStorage.getItem(KEY) as ThemeMode) || "system"; } catch { /* private mode */ }
    setModeState(saved);
  }, []);

  useEffect(() => {
    const apply = () => { const r = resolve(mode); setResolved(r); document.documentElement.dataset.theme = r; };
    apply();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    try { localStorage.setItem(KEY, m); } catch { /* ignore */ }
  }, []);

  return <Ctx.Provider value={{ mode, setMode, resolved }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
