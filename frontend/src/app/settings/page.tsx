"use client";

import { useState, type FormEvent } from "react";
import { RoleTag } from "@/components/identity";
import { Button, Card, Field, useToast } from "@/components/ui";
import { api, json } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ProfilePage() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  const isKey = user?.via === "api_key";
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true);
    try { await api("/api/auth/me", { method: "PATCH", ...json({ name }) }); await refresh(); toast("ok", "Profile updated"); }
    catch (err) { toast("err", (err as Error).message); } finally { setBusy(false); }
  }
  return (
    <Card className="p-6">
      <h2 className="text-[15px] font-semibold">Profile</h2>
      <p className="mt-1 text-[13px] text-muted">How your name appears on corrections, approvals and the audit log.</p>
      <form onSubmit={save} className="mt-5 max-w-md space-y-4">
        <Field label="Full name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} minLength={2} required disabled={isKey} /></Field>
        <Field label="E-mail"><input className="field" value={user?.email ?? ""} disabled readOnly /></Field>
        <div className="flex items-center gap-3 text-[13px] text-muted">Role <RoleTag role={user?.role ?? "viewer"} /> <span>Only an administrator can change this.</span></div>
        <Button variant="primary" type="submit" loading={busy} disabled={isKey || name.trim() === user?.name}>Save changes</Button>
      </form>
    </Card>
  );
}
