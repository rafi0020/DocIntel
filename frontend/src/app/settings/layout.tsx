"use client";

import clsx from "clsx";
import { Activity, Cpu, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { PageBody, PageHeader } from "@/components/AppShell";
import { useAuth } from "@/lib/auth";

const TABS = [
  { href: "/settings/", label: "Profile", icon: UserRound, hint: "Your name and role" },
  { href: "/settings/security/", label: "Security", icon: ShieldCheck, hint: "Password" },
  { href: "/settings/models/", label: "Models & API", icon: Cpu, hint: "AI model, key, OCR", admin: true },
  { href: "/settings/status/", label: "System status", icon: Activity, hint: "Health and last 24 hours" },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { can } = useAuth();
  const tabs = TABS.filter((t) => !t.admin || can("admin"));
  const active = (href: string) => (href === "/settings/" ? path === "/settings/" || path === "/settings" : path.startsWith(href.replace(/\/$/, "")));
  return (
    <div>
      <PageHeader title="Settings" subtitle="Your account, system configuration and status." />
      <PageBody>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[232px_minmax(0,1fr)] lg:gap-8">
          <nav aria-label="Settings sections" className="flex flex-wrap gap-1 lg:sticky lg:top-20 lg:block lg:space-y-1 lg:self-start">
            {tabs.map(({ href, label, icon: Icon, hint }) => (
              <Link key={href} href={href} aria-current={active(href) ? "page" : undefined}
                className={clsx("btn flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium lg:w-full", active(href) ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface hover:text-ink")}>
                <Icon className="size-4 shrink-0" />
                <span className="whitespace-nowrap"><span className="block leading-tight">{label}</span><span className="hidden text-[11.5px] font-normal leading-tight text-muted lg:block">{hint}</span></span>
              </Link>
            ))}
          </nav>
          <div className="min-w-0 space-y-5">{children}</div>
        </div>
      </PageBody>
    </div>
  );
}
