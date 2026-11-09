"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, json, ROLE_RANK, SESSION_EXPIRED, type Me, type Role } from "./api";

type AuthState = {
  user: Me | null;
  loading: boolean;
  can: (role: Role) => boolean;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try { setUser(await api<Me>("/api/auth/me")); } catch { setUser(null); } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const gone = () => setUser(null);
    window.addEventListener(SESSION_EXPIRED, gone);
    return () => window.removeEventListener(SESSION_EXPIRED, gone);
  }, []);

  const value = useMemo<AuthState>(() => ({
    user, loading,
    can: (role) => !!user && ROLE_RANK[user.role] >= ROLE_RANK[role],
    login: async (email, password, remember) => {
      await api("/api/auth/login", { method: "POST", ...json({ email, password, remember }) });
      await refresh();
    },
    signup: async (name, email, password) => {
      await api("/api/auth/signup", { method: "POST", ...json({ name, email, password }) });
      await refresh();
    },
    logout: async () => {
      try { await api("/api/auth/logout", { method: "POST" }); } finally { setUser(null); }
    },
    refresh,
  }), [user, loading, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside <AuthProvider>");
  return c;
}
