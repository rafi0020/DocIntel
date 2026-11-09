"use client";

import { Eye, EyeOff, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import { AuthLayout } from "@/components/AuthLayout";
import { fetcher, type AuthConfig } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const { data: cfg } = useSWR<AuthConfig>("/api/auth/config", fetcher);
  useEffect(() => { document.title = "Sign in · DocIntel"; }, []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true); setError("");
    try { await login(email, password, remember); } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  return (
    <AuthLayout>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Sign in</h1>
      <p className="mt-1 text-sm text-muted">Use your work e-mail and password.</p>

      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        <label className="block text-[13px] font-medium text-ink-2">E-mail
          <input className="field mt-1.5 h-10" type="email" autoComplete="username" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
        </label>
        <label className="block text-[13px] font-medium text-ink-2">Password
          <span className="relative mt-1.5 block">
            <input className="field h-10 pr-10" type={show ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} className="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded text-muted hover:text-ink">
              {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </span>
        </label>
        <label className="flex items-center gap-2 text-[13px] text-ink-2"><input type="checkbox" className="size-4 accent-[var(--color-accent)]" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Keep me signed in on this device</label>
        {error && <p role="alert" className="enter rounded-md border border-err/30 bg-err-soft px-3 py-2 text-[13px] text-err">{error}</p>}
        <button disabled={busy || !email || !password} className="btn flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent text-sm font-medium text-on-accent shadow-sm hover:bg-accent-strong disabled:opacity-50">
          {busy && <Loader2 className="size-4 animate-spin" />} Sign in
        </button>
      </form>

      {cfg?.allow_signup && <p className="mt-6 text-center text-sm text-muted">New here? <Link href="/signup/" className="font-medium text-accent underline-draw">Create an account</Link></p>}

    </AuthLayout>
  );
}
