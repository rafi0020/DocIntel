"use client";

import clsx from "clsx";
import {
  ArrowLeftRight, ChevronsLeft, ChevronsRight, FolderOpen, History, LayoutDashboard, ListChecks, Menu, Search, ShieldCheck, Upload, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import useSWR from "swr";
import { fetcher, type Stats } from "@/lib/api";
import { AuthProvider, useAuth } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";
import { CommandPalette } from "./CommandPalette";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { UploadDialog } from "./UploadDialog";
import { UserCard } from "./UserCard";
import { Kbd, ToastProvider } from "./ui";

export { initials, RoleTag, ThemeSwitch } from "./identity";

const PUBLIC = /^\/(login|signup)\/?$/;

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-lg bg-accent text-on-accent" style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" width={size * 0.6} height={size * 0.6} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M6 3h8l4 4v14H6z" /><path d="M9.5 14.5l2 2 3.5-4" />
      </svg>
    </span>
  );
}

const WORKSPACE = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/documents", label: "Documents", icon: FolderOpen },
  { href: "/review", label: "Review queue", icon: ListChecks, badge: true },
  { href: "/search", label: "Search", icon: Search },
  { href: "/compare", label: "Cross-verify", icon: ArrowLeftRight },
];
const ADMIN = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/audit", label: "Audit log", icon: History },
];

function NavItem({ href, label, icon: Icon, active, collapsed, count, onNavigate }: {
  href: string; label: string; icon: typeof Search; active: boolean; collapsed: boolean; count?: number; onNavigate?: () => void;
}) {
  return (
    <Link href={href} onClick={onNavigate} title={collapsed ? label : undefined} aria-current={active ? "page" : undefined}
      className={clsx("btn group relative flex h-9 items-center gap-2.5 rounded-md text-[13.5px] font-medium", collapsed ? "justify-center px-0" : "px-2.5",
        active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface hover:text-ink")}>
      <Icon className="size-[17px] shrink-0" strokeWidth={active ? 2.2 : 1.9} />
      {!collapsed && <span className="truncate">{label}</span>}
      {!!count && !collapsed && <span className="ml-auto rounded-full bg-warn-soft px-1.5 py-px font-mono text-[11px] font-semibold text-warn tabular">{count}</span>}
      {!!count && collapsed && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-warn ring-2 ring-card" />}
    </Link>
  );
}

function Sidebar({ collapsed, onToggle, onNavigate, drawer }: { collapsed: boolean; onToggle?: () => void; onNavigate?: () => void; drawer?: boolean }) {
  const path = usePathname();
  const { can } = useAuth();
  const { data: stats } = useSWR<Stats>("/api/stats", fetcher, { refreshInterval: 6000 });
  const review = stats?.records.by_review_status?.needs_review ?? 0;
  const isActive = (href: string, exact?: boolean) => (exact ? path === href : path.startsWith(href));
  const c = collapsed && !drawer;
  return (
    <div className="flex h-full flex-col bg-card">
      <div className={clsx("flex h-14 shrink-0 items-center border-b border-line", c ? "justify-center" : "gap-2.5 px-4")}>
        <Logo />
        {!c && <span className="text-[15px] font-semibold tracking-tight">DocIntel</span>}
      </div>
      <nav aria-label="Main" className="flex-1 space-y-6 overflow-y-auto px-3 py-4 scroll-thin">
        <div className="space-y-0.5">
          {!c && <p className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-faint">Workspace</p>}
          {WORKSPACE.map((n) => <NavItem key={n.href} {...n} count={n.badge ? review : undefined} active={isActive(n.href, n.exact)} collapsed={c} onNavigate={onNavigate} />)}
        </div>
        {can("admin") && (
          <div className="space-y-0.5">
            {!c && <p className="flex items-center gap-1.5 px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-faint"><ShieldCheck className="size-3" /> Administration</p>}
            {c && <div className="mx-2 border-t border-line" />}
            {ADMIN.map((n) => <NavItem key={n.href} {...n} active={isActive(n.href)} collapsed={c} onNavigate={onNavigate} />)}
          </div>
        )}
      </nav>
      <div className="shrink-0 space-y-2 border-t border-line p-3">
        {onToggle && !drawer && (
          <button onClick={onToggle} aria-label={c ? "Expand sidebar" : "Collapse sidebar"} title={c ? "Expand sidebar" : "Collapse sidebar"}
            className={clsx("btn flex h-8 w-full items-center gap-2 rounded-md text-[12.5px] font-medium text-muted hover:bg-surface hover:text-ink", c ? "justify-center" : "px-2.5")}>
            {c ? <ChevronsRight className="size-4" /> : <><ChevronsLeft className="size-4" /> Collapse</>}
          </button>
        )}
        <UserCard collapsed={c} onNavigate={onNavigate} />
      </div>
    </div>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  const { can } = useAuth();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur lg:px-6">
      <button aria-label="Open menu" onClick={onMenu} className="btn grid size-9 place-items-center rounded-md hover:bg-surface lg:hidden"><Menu className="size-5" /></button>
      <button onClick={() => window.dispatchEvent(new Event("open-palette"))}
        className="btn flex h-9 min-w-0 flex-1 max-w-md items-center gap-2.5 rounded-lg border border-line bg-card px-3 text-left text-[13px] text-muted shadow-[var(--shadow-card)] hover:border-line-strong">
        <Search className="size-4" /> <span className="flex-1 truncate">Search invoices, suppliers, numbers…</span>
        <span className="hidden gap-0.5 sm:flex"><Kbd>Ctrl</Kbd><Kbd>K</Kbd></span>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {can("reviewer") && (
          <button onClick={() => window.dispatchEvent(new Event("open-upload"))}
            className="btn inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3.5 text-[13px] font-medium text-on-accent shadow-sm hover:bg-accent-strong">
            <Upload className="size-4" /> <span className="max-sm:sr-only">Upload</span>
          </button>
        )}
      </div>
    </header>
  );
}

function Splash() {
  return <div className="grid min-h-dvh place-items-center bg-bg"><div className="enter flex items-center gap-3"><Logo size={36} /><span className="text-lg font-semibold tracking-tight">DocIntel</span></div></div>;
}

function Frame({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, loading, can } = useAuth();
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const isPublic = PUBLIC.test(path);

  useEffect(() => { try { setCollapsed(localStorage.getItem("di.sidebar") === "1"); } catch { /* ignore */ } }, []);
  useEffect(() => setDrawer(false), [path]);
  const toggle = () => setCollapsed((c) => { try { localStorage.setItem("di.sidebar", c ? "0" : "1"); } catch { /* ignore */ } return !c; });

  useEffect(() => {
    if (loading) return;
    if (!user && !isPublic) router.replace(`/login/?next=${encodeURIComponent(path + window.location.search)}`);
    if (user && isPublic) { const n = new URLSearchParams(window.location.search).get("next"); router.replace(n && n.startsWith("/") && !n.startsWith("//") ? n : "/"); }
  }, [loading, user, isPublic, path, router]);

  if (isPublic) return loading || user ? <Splash /> : <>{children}</>;
  if (loading || !user) return <Splash />;

  const denied = path.startsWith("/admin") && !can("admin");
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[90] focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:shadow-lg">Skip to content</a>
      <div className="min-h-dvh lg:flex">
        <div className={clsx("sticky top-0 z-40 hidden h-dvh shrink-0 border-r border-line transition-[width] duration-200 lg:block", collapsed ? "w-[68px]" : "w-[248px]")}>
          <Sidebar collapsed={collapsed} onToggle={toggle} />
        </div>
        {drawer && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div className="fade absolute inset-0 bg-ink/45" onClick={() => setDrawer(false)} />
            <aside className="enter absolute inset-y-0 left-0 w-[280px] border-r border-line shadow-[var(--shadow-pop)]">
              <button aria-label="Close menu" onClick={() => setDrawer(false)} className="btn absolute right-2 top-2.5 z-10 grid size-9 place-items-center rounded-md hover:bg-surface"><X className="size-5" /></button>
              <Sidebar collapsed={false} drawer onNavigate={() => setDrawer(false)} />
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onMenu={() => setDrawer(true)} />
          <main id="main" className="min-w-0 flex-1">
            {denied ? (
              <div className="page-x py-16"><div className="page-w mx-auto max-w-md rounded-xl border border-line bg-card p-8 text-center shadow-[var(--shadow-card)]">
                <ShieldCheck className="mx-auto mb-3 size-8 text-muted" />
                <h1 className="text-lg font-semibold">Administrators only</h1>
                <p className="mt-1 text-sm text-muted">Your role ({user.role}) cannot open this page. Ask an administrator if you need access.</p>
                <Link href="/" className="btn mt-5 inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-on-accent">Back to dashboard</Link>
              </div></div>
            ) : children}
          </main>
        </div>
      </div>
      <UploadDialog />
      <ShortcutsDialog />
      <CommandPalette />
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>
          <Frame>{children}</Frame>
        </ToastProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export function PageHeader({ title, subtitle, actions, docTitle }: { title: string; subtitle?: ReactNode; actions?: ReactNode; docTitle?: string }) {
  useEffect(() => { document.title = `${docTitle ?? title} · DocIntel`; }, [title, docTitle]);
  return (
    <div className="page-x">
      <div className="page-w flex flex-wrap items-end justify-between gap-x-6 gap-y-3 pb-1 pt-7">
        <div className="min-w-0 max-w-[68ch]">
          <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm leading-relaxed text-muted">{subtitle}</p>}
        </div>
        {/* reserved action slot: the header keeps the same height whether or not actions are present */}
        <div className={clsx("flex min-h-9 flex-wrap items-center gap-2", !actions && "max-sm:hidden")}>{actions}</div>
      </div>
    </div>
  );
}

/** Standard page content frame: same max width, gutters and vertical rhythm on every screen. */
export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="page-x enter py-6">
      <div className={clsx("page-w space-y-6", className)}>{children}</div>
    </div>
  );
}
