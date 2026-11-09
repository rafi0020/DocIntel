"use client";

import { ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button, Card, Field, useToast } from "@/components/ui";
import { api, json } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function SecurityPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const isKey = user?.via === "api_key";
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true);
    try { await api("/api/auth/me/password", { method: "POST", ...json({ current_password: cur, new_password: next }) }); setCur(""); setNext(""); toast("ok", "Password changed. Your other sessions were signed out."); }
    catch (err) { toast("err", (err as Error).message); } finally { setBusy(false); }
  }
  return (
    <Card className="p-6">
      <h2 className="text-[15px] font-semibold">Password</h2>
      <p className="mt-1 text-[13px] text-muted">Use at least 10 characters with a letter and a number. Changing it signs you out everywhere else.</p>
      <form onSubmit={save} className="mt-5 max-w-md space-y-4">
        <Field label="Current password"><input className="field" type="password" autoComplete="current-password" required value={cur} onChange={(e) => setCur(e.target.value)} disabled={isKey} /></Field>
        <Field label="New password"><input className="field" type="password" autoComplete="new-password" required value={next} onChange={(e) => setNext(e.target.value)} disabled={isKey} /></Field>
        <Button variant="primary" type="submit" loading={busy} disabled={isKey || !cur || next.length < 10}>Change password</Button>
      </form>
      <p className="mt-6 flex items-center gap-2 text-[12.5px] text-muted"><ShieldCheck className="size-4 text-ok" /> Sessions are server-side, cookies are HttpOnly, and every action is audited.</p>
    </Card>
  );
}
