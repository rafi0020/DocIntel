"use client";

import { KeyRound, Plus, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { initials, PageBody, PageHeader, RoleTag } from "@/components/AppShell";
import { Badge, Button, Card, Field, Modal, Skeleton, Stat, StatGrid, useToast } from "@/components/ui";
import { api, fetcher, json, type Role, type UserRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtAgo } from "@/lib/format";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything, plus users and the audit log",
  reviewer: "Upload, correct, approve, re-process",
  viewer: "Read-only access",
};

export default function UsersPage() {
  const toast = useToast();
  const { user: me } = useAuth();
  const { data, mutate } = useSWR<{ users: UserRow[] }>("/api/users", fetcher);
  const [adding, setAdding] = useState(false);
  const [resetFor, setResetFor] = useState<UserRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "reviewer" as Role });
  const [pw, setPw] = useState("");
  const users = data?.users ?? [];

  const patch = async (u: UserRow, body: Record<string, unknown>, ok: string) => {
    try { await api(`/api/users/${u.id}`, { method: "PATCH", ...json(body) }); toast("ok", ok); mutate(); }
    catch (e) { toast("err", (e as Error).message); mutate(); }
  };
  async function create(ev: FormEvent) {
    ev.preventDefault(); setBusy(true);
    try { await api("/api/users", { method: "POST", ...json(form) }); toast("ok", `${form.name} can now sign in`); setAdding(false); setForm({ name: "", email: "", password: "", role: "reviewer" }); mutate(); }
    catch (e) { toast("err", (e as Error).message); } finally { setBusy(false); }
  }
  async function reset(ev: FormEvent) {
    ev.preventDefault(); if (!resetFor) return; setBusy(true);
    try { await api(`/api/users/${resetFor.id}`, { method: "PATCH", ...json({ new_password: pw }) }); toast("ok", "Password reset. Their sessions were signed out."); setResetFor(null); setPw(""); }
    catch (e) { toast("err", (e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      <PageHeader title="Users" subtitle="Control who can sign in and what they can do. Every change is written to the audit log."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add user</Button>} />
      <PageBody>
        <StatGrid>
          <Stat label="Total users" value={users.length || "—"} icon={<UserCheck className="size-4" />} />
          <Stat label="Administrators" value={users.filter((u) => u.role === "admin" && u.is_active).length} icon={<ShieldCheck className="size-4" />} />
          <Stat label="Reviewers" value={users.filter((u) => u.role === "reviewer" && u.is_active).length} tone="ok" icon={<UserCheck className="size-4" />} />
          <Stat label="Deactivated" value={users.filter((u) => !u.is_active).length} tone="warn" icon={<UserX className="size-4" />} />
        </StatGrid>
        <Card className="overflow-clip">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead><tr className="border-b border-line bg-bg text-left text-[12px] text-muted">
                <th className="px-4 py-2.5 font-medium">User</th><th className="px-3 py-2.5 font-medium">Role</th><th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Last sign-in</th><th className="px-3 py-2.5 font-medium">Joined</th><th className="w-[120px] px-3 py-2.5" />
              </tr></thead>
              <tbody>
                {!data && Array.from({ length: 4 }).map((_, i) => <tr key={i} className="border-b border-line"><td colSpan={6} className="px-4 py-3"><Skeleton className="h-9" /></td></tr>)}
                {users.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id} className="border-b border-line last:border-0 hover:bg-bg">
                      <td className="px-4 py-3"><div className="flex items-center gap-3">
                        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent">{initials(u.name)}</span>
                        <div className="min-w-0"><p className="truncate font-medium">{u.name}{self && <span className="ml-2 text-[12px] font-normal text-muted">(you)</span>}</p><p className="truncate text-[12.5px] text-muted">{u.email}</p></div>
                      </div></td>
                      <td className="px-3 py-3">
                        <select aria-label={`Role for ${u.name}`} value={u.role} onChange={(e) => patch(u, { role: e.target.value }, `${u.name} is now ${e.target.value}`)} className="field h-8 w-[130px] text-[13px] capitalize" title={ROLE_HELP[u.role]}>
                          {(["admin", "reviewer", "viewer"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </td>
                      <td className="px-3 py-3">{u.is_active ? <Badge tone="ok" dot>Active</Badge> : <Badge tone="muted" dot>Deactivated</Badge>}</td>
                      <td className="px-3 py-3 text-muted">{u.last_login_at ? fmtAgo(u.last_login_at) : "Never"}</td>
                      <td className="px-3 py-3 text-muted">{u.created_at ? new Date(u.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : ""}</td>
                      <td className="px-3 py-3"><div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon={<KeyRound className="size-3.5" />} onClick={() => setResetFor(u)} aria-label={`Reset password for ${u.name}`}>Reset</Button>
                        <Button size="sm" variant="ghost" disabled={self} title={self ? "You cannot deactivate yourself" : undefined} onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? `${u.name} was deactivated` : `${u.name} was reactivated`)}>{u.is_active ? "Deactivate" : "Activate"}</Button>
                      </div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
        <Card className="p-5">
          <h2 className="text-[14px] font-semibold">What each role can do</h2>
          <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(Object.keys(ROLE_HELP) as Role[]).map((r) => <div key={r} className="rounded-lg bg-bg p-3"><dt><RoleTag role={r} /></dt><dd className="mt-1.5 text-[13px] text-ink-2">{ROLE_HELP[r]}</dd></div>)}
          </dl>
        </Card>
      </PageBody>

      <Modal open={adding} onClose={() => setAdding(false)} title="Add a user" description="They can sign in straight away. Share the password through a secure channel and ask them to change it."
        footer={<><Button onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={() => (document.getElementById("add-user-form") as HTMLFormElement)?.requestSubmit()}>Create user</Button></>}>
        <form id="add-user-form" onSubmit={create} className="space-y-3.5 pb-2">
          <Field label="Full name"><input className="field" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="E-mail"><input className="field" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="At least 10 characters with a letter and a number."><input className="field" type="text" autoComplete="off" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Role" hint={ROLE_HELP[form.role]}>
            <select className="field capitalize" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{(["reviewer", "viewer", "admin"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}</select>
          </Field>
        </form>
      </Modal>
      <Modal open={!!resetFor} onClose={() => setResetFor(null)} title={`Reset password for ${resetFor?.name ?? ""}`} description="All of their active sessions will be signed out."
        footer={<><Button onClick={() => setResetFor(null)}>Cancel</Button><Button variant="primary" loading={busy} onClick={() => (document.getElementById("reset-form") as HTMLFormElement)?.requestSubmit()}>Reset password</Button></>}>
        <form id="reset-form" onSubmit={reset} className="pb-2"><Field label="New password" hint="At least 10 characters with a letter and a number."><input className="field" type="text" autoComplete="off" required value={pw} onChange={(e) => setPw(e.target.value)} /></Field></form>
      </Modal>
    </div>
  );
}
