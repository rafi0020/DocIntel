"use client";

import clsx from "clsx";
import { Check, Eye, EyeOff, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import { AuthLayout } from "@/components/AuthLayout";
import { fetcher, type AuthConfig } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const RULES = [
  { ok: (p: string) => p.length >= 10, label: "At least 10 characters" },
  { ok: (p: string) => /[A-Za-z]/.test(p), label: "A letter" },
  { ok: (p: string) => /\d/.test(p), label: "A number" },
];

export default function SignupPage() {
  const { signup } = useAuth();
  const { data: cfg } = useSWR<AuthConfig>("/api/auth/config", fetcher);
  useEffect(() => { document.title = "Create account · DocIntel"; }, []);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const valid = name.trim().length >= 2 && /\S+@\S+\.\S+/.test(email) && RULES.every((r) => r.ok(password));

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true); setError("");
    try { await signup(name, email, password); } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  return (
    <AuthLayout>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Create your account</h1>
      <p className="mt-1 text-sm text-muted">You can upload, review and approve documents. An administrator can change your role later.</p>
      {cfg && !cfg.allow_signup ? (
        <p className="mt-6 rounded-md border border-line bg-surface px-3 py-3 text-sm text-ink-2">Self-service sign-up is turned off for this workspace. Ask an administrator to create an account for you.</p>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
          <label className="block text-[13px] font-medium text-ink-2">Full name
            <input className="field mt-1.5 h-10" autoComplete="name" autoFocus required value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="block text-[13px] font-medium text-ink-2">Work e-mail
            <input className="field mt-1.5 h-10" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </label>
          <label className="block text-[13px] font-medium text-ink-2">Password
            <span className="relative mt-1.5 block">
              <input className="field h-10 pr-10" type={show ? "text" : "password"} autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} className="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded text-muted hover:text-ink">
                {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </span>
          </label>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]" aria-label="Password requirements">
            {RULES.map((r) => { const ok = r.ok(password); return (
              <li key={r.label} className={clsx("flex items-center gap-1.5", ok ? "text-ok" : "text-muted")}>
                <span className={clsx("grid size-3.5 place-items-center rounded-full", ok ? "bg-ok text-on-accent" : "border border-line-strong")}>{ok && <Check className="size-2.5" strokeWidth={3.5} />}</span>{r.label}
              </li>); })}
          </ul>
          {error && <p role="alert" className="enter rounded-md border border-err/30 bg-err-soft px-3 py-2 text-[13px] text-err">{error}</p>}
          <button disabled={busy || !valid} className="btn flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent text-sm font-medium text-on-accent shadow-sm hover:bg-accent-strong disabled:opacity-50">
            {busy && <Loader2 className="size-4 animate-spin" />} Create account
          </button>
        </form>
      )}
      <p className="mt-6 text-center text-sm text-muted">Already have an account? <Link href="/login/" className="font-medium text-accent underline-draw">Sign in</Link></p>
    </AuthLayout>
  );
}
